#!/usr/bin/env python3
"""セキュリティインシデント・ニュース収集スクリプト.

各社 RSS / RDF / Atom を取得し、正規化・重複排除・分類して
data/news.json に書き出す。標準ライブラリのみで動作する。
"""

from __future__ import annotations

import gzip
import html
import io
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_FILE = DATA_DIR / "news.json"

JST = timezone(timedelta(hours=9))
MAX_ITEMS = 900
MAX_AGE_DAYS = 120
TIMEOUT = 30
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

FEEDS = [
    # --- 国内 ---
    {"name": "Security NEXT", "url": "https://www.security-next.com/feed", "region": "jp", "lang": "ja"},
    {"name": "ScanNetSecurity", "url": "https://scan.netsecurity.ne.jp/rss/index.rdf", "region": "jp", "lang": "ja"},
    {"name": "JPCERT/CC 注意喚起", "url": "https://www.jpcert.or.jp/rss/jpcert.rdf", "region": "jp", "lang": "ja"},
    {"name": "JVN 脆弱性情報", "url": "https://jvn.jp/rss/jvn.rdf", "region": "jp", "lang": "ja"},
    {
        "name": "ITmedia エンタープライズ",
        "url": "https://rss.itmedia.co.jp/rss/2.0/enterprise.xml",
        "region": "jp",
        "lang": "ja",
        "require_keywords": [
            "セキュリティ", "サイバー", "攻撃", "侵害", "不正アクセス", "情報漏えい",
            "情報漏洩", "マルウェア", "ランサム", "脆弱性", "フィッシング", "詐欺",
            "個人情報", "標的型", "ウイルス", "ハッキング", "ゼロデイ", "DDoS",
        ],
    },
    # --- 海外 ---
    {"name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews", "region": "world", "lang": "en"},
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/", "region": "world", "lang": "en"},
    {"name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/", "region": "world", "lang": "en"},
    {"name": "The Record", "url": "https://therecord.media/feed", "region": "world", "lang": "en"},
    {"name": "Dark Reading", "url": "https://www.darkreading.com/rss.xml", "region": "world", "lang": "en"},
    {"name": "SecurityWeek", "url": "https://www.securityweek.com/feed/", "region": "world", "lang": "en"},
    {"name": "CISA Advisories", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml", "region": "world", "lang": "en"},
    {"name": "JPCERT/CC (EN)", "url": "https://www.jpcert.or.jp/english/rss/jpcert-en.rdf", "region": "world", "lang": "en"},
    {"name": "Unit 42", "url": "https://unit42.paloaltonetworks.com/feed/", "region": "world", "lang": "en"},
]

# タグ判定: 上から順に評価し、最大 3 個まで付与
TAG_RULES = [
    ("ランサムウェア", ["ランサム", "ransomware", "ransom"]),
    ("情報漏えい", ["情報漏えい", "情報漏洩", "漏えい", "漏洩", "data breach", "breach", "leaked", "exposed data"]),
    ("脆弱性", ["脆弱性", "vulnerability", "cve-", "zero-day", "ゼロデイ", "patch", "脆弱"]),
    ("標的型攻撃", ["標的型", "標的型攻撃", "spear-phishing", "apt", "targeted attack"]),
    ("フィッシング", ["フィッシング", "phishing", "smishing", "偽サイト", "なりすまし"]),
    ("マルウェア", ["マルウェア", "malware", "trojan", "backdoor", "botnet", "stealer", "ワーム", "ウイルス"]),
    ("不正アクセス", ["不正アクセス", "unauthorized access", "hacked", "ハッキング", "侵入", "compromised"]),
    ("サイバー攻撃", ["サイバー攻撃", "cyberattack", "cyber attack", "ddos", "攻撃"]),
    ("サプライチェーン", ["サプライチェーン", "supply chain", "third-party", "委託先"]),
    ("内部不正", ["内部不正", "insider"]),
    ("規制・法令", ["個人情報保護", "gdpr", "法改正", "規制", "regulation", "compliance", "プライバシー"]),
    ("注意喚起", ["注意喚起", "advisory", "注意情報", "警報"]),
]

BADGE_KEYS = ("重要", "緊急", "crit", "severe", "critical")


def http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/xml, application/atom+xml, text/xml, */*",
            "Accept-Language": "ja,en;q=0.8",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return raw


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(text: str | None, limit: int = 260) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for el in node:
        if local(el.tag) in names:
            if el.text and el.text.strip():
                return el.text.strip()
            # Atom の <link href="..."> など
            href = el.attrib.get("href")
            if href:
                return href
    return ""


def entry_link(node: ET.Element) -> str:
    fallback = ""
    for el in node:
        if local(el.tag) != "link":
            continue
        href = el.attrib.get("href")
        rel = el.attrib.get("rel", "alternate")
        text = (el.text or "").strip()
        if rel == "alternate" and (href or text):
            return href or text
        if href and not fallback:
            fallback = href
        elif text and not fallback:
            fallback = text
    return fallback


def entry_date(node: ET.Element) -> datetime | None:
    raw = child_text(node, ("pubdate", "published", "updated", "date", "issued", "modified"))
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        cleaned = raw.replace("Z", "+00:00")
        for candidate in (cleaned, cleaned[:19], cleaned[:10]):
            try:
                dt = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
    if dt is None:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title).lower()
    t = re.sub(r"[「」『』【】\[\]（）()〈〉《》\"'’“”\-–—_/.,:;!?！？、。・…\s]+", "", t)
    return t


def classify(title: str, summary: str) -> list[str]:
    haystack = f"{title} {summary}".lower()
    tags: list[str] = []
    for label, keys in TAG_RULES:
        if any(k in haystack for k in keys):
            tags.append(label)
        if len(tags) >= 3:
            break
    return tags


def parse_feed(feed: dict) -> tuple[list[dict], str]:
    raw = http_get(feed["url"])
    root = ET.fromstring(raw)
    nodes = [n for n in root.iter() if local(n.tag) in ("item", "entry")]
    items: list[dict] = []
    require = [k.lower() for k in feed.get("require_keywords", [])]
    for node in nodes:
        title = strip_html(child_text(node, ("title",)), 200)
        if not title:
            continue
        url = entry_link(node)
        if not url.startswith("http"):
            continue
        summary = strip_html(
            child_text(node, ("description", "summary", "content", "encoded", "subtitle")), 240
        )
        if require and not any(k in f"{title} {summary}".lower() for k in require):
            continue
        published = entry_date(node)
        if published is None:
            published = datetime.now(JST)
        items.append(
            {
                "title": title,
                "url": url.split("#")[0],
                "summary": summary,
                "source": feed["name"],
                "region": feed["region"],
                "lang": feed["lang"],
                "published": published.isoformat(),
                "tags": classify(title, summary),
            }
        )
    return items, "ok"


def load_existing() -> list[dict]:
    if not OUT_FILE.exists():
        return []
    try:
        payload = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return payload.get("items", [])


def main() -> int:
    existing = load_existing()
    collected: list[dict] = []
    status: list[dict] = []

    for feed in FEEDS:
        try:
            items, state = parse_feed(feed)
        except (urllib.error.URLError, ET.ParseError, OSError, ValueError) as exc:
            state = f"error: {type(exc).__name__}"
            items = []
            print(f"[warn] {feed['name']}: {exc}", file=sys.stderr)
        else:
            print(f"[ok] {feed['name']}: {len(items)} items")
        status.append({"name": feed["name"], "region": feed["region"], "status": state, "count": len(items)})
        collected.extend(items)

    # 新規 → 既存 → 重複排除（URL 優先、次にタイトル正規化キー）
    merged: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in collected + existing:
        url_key = item["url"].rstrip("/").lower()
        title_key = normalize_title(item["title"])
        if url_key in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        merged.append(item)

    cutoff = datetime.now(JST) - timedelta(days=MAX_AGE_DAYS)
    fresh: list[dict] = []
    for item in merged:
        try:
            published = datetime.fromisoformat(item["published"])
        except (KeyError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=JST)
        published = published.astimezone(JST)
        if published < cutoff:
            continue
        item["published"] = published.isoformat()
        if not item.get("tags"):
            item["tags"] = classify(item["title"], item.get("summary", ""))
        fresh.append(item)

    fresh.sort(key=lambda i: i["published"], reverse=True)
    # 将来日付（配信元の予約投稿など）は現在時刻に丸める
    now = datetime.now(JST)
    for item in fresh:
        if datetime.fromisoformat(item["published"]) > now:
            item["published"] = now.isoformat()
    fresh.sort(key=lambda i: i["published"], reverse=True)
    fresh = fresh[:MAX_ITEMS]

    ok_sources = sum(1 for s in status if s["status"] == "ok")
    payload = {
        "generated_at": datetime.now(JST).isoformat(),
        "total": len(fresh),
        "sources_ok": ok_sources,
        "sources_total": len(status),
        "sources": status,
        "items": fresh,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    jp = sum(1 for i in fresh if i["region"] == "jp")
    print(f"wrote {len(fresh)} items (jp={jp}, world={len(fresh) - jp}) / sources ok={ok_sources}/{len(status)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
