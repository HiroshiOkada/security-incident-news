#!/usr/bin/env python3
"""RSS/Atom から記事素材を収集し data/raw.json に保存する。

サイトに載せるかどうかの判断は curate.py (AI) が行う。
ここでは「候補プール」を作るだけ。
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
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_FILE = DATA_DIR / "raw.json"

JST = timezone(timedelta(hours=9))
MAX_AGE_DAYS = 10
MAX_ITEMS = 400
TIMEOUT = 30
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

FEEDS = [
    # 国内
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
            "情報漏洩", "マルウェア", "ランサム", "脆弱性", "フィッシング", "個人情報",
            "標的型", "ハッキング", "ゼロデイ", "DDoS",
        ],
    },
    # 海外
    {"name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews", "region": "world", "lang": "en"},
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/", "region": "world", "lang": "en"},
    {"name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/", "region": "world", "lang": "en"},
    {"name": "The Record", "url": "https://therecord.media/feed", "region": "world", "lang": "en"},
    {"name": "SecurityWeek", "url": "https://www.securityweek.com/feed/", "region": "world", "lang": "en"},
    {"name": "CISA Advisories", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml", "region": "world", "lang": "en"},
    {"name": "JPCERT/CC (EN)", "url": "https://www.jpcert.or.jp/english/rss/jpcert-en.rdf", "region": "world", "lang": "en"},
]

GOOGLE_FEEDS = [
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=%E6%83%85%E5%A0%B1%E6%BC%8F%E3%81%88%E3%81%84&hl=ja&gl=JP&ceid=JP:ja",
        "region": "jp", "lang": "ja", "use_item_source": True, "limit": 14, "google": True,
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=%E4%B8%8D%E6%AD%A3%E3%82%A2%E3%82%AF%E3%82%BB%E3%82%B9&hl=ja&gl=JP&ceid=JP:ja",
        "region": "jp", "lang": "ja", "use_item_source": True, "limit": 14, "google": True,
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=%E3%83%A9%E3%83%B3%E3%82%B5%E3%83%A0%E3%82%A6%E3%82%A7%E3%82%A2&hl=ja&gl=JP&ceid=JP:ja",
        "region": "jp", "lang": "ja", "use_item_source": True, "limit": 12, "google": True,
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=%E8%84%86%E5%BC%B1%E6%80%A7+%E6%82%AA%E7%94%A8&hl=ja&gl=JP&ceid=JP:ja",
        "region": "jp", "lang": "ja", "use_item_source": True, "limit": 12, "google": True,
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=data+breach&hl=en-US&gl=US&ceid=US:en",
        "region": "world", "lang": "en", "use_item_source": True, "limit": 14, "google": True,
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=ransomware+attack&hl=en-US&gl=US&ceid=US:en",
        "region": "world", "lang": "en", "use_item_source": True, "limit": 12, "google": True,
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=critical+vulnerability+exploited&hl=en-US&gl=US&ceid=US:en",
        "region": "world", "lang": "en", "use_item_source": True, "limit": 12, "google": True,
    },
]

ALL_FEEDS = FEEDS + GOOGLE_FEEDS

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


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


def strip_html(text: str | None, limit: int = 400) -> str:
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
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title).lower()
    return re.sub(r"[「」『』【】\[\]（）()〈〉《》\"'’“”\-–—_/.,:;!?！？、。・…\s]+", "", t)


def parse_feed(feed: dict) -> list[dict]:
    root = ET.fromstring(http_get(feed["url"]))
    nodes = [n for n in root.iter() if local(n.tag) in ("item", "entry")]
    if feed.get("limit"):
        nodes = nodes[: feed["limit"]]
    items: list[dict] = []
    require = [k.lower() for k in feed.get("require_keywords", [])]
    for node in nodes:
        title = strip_html(child_text(node, ("title",)), 400)
        if not title:
            continue
        publisher = feed["name"]
        if feed.get("use_item_source"):
            src = strip_html(child_text(node, ("source",)), 60)
            if src:
                publisher = src
                for sep in (" - ", " | ", "｜"):
                    if title.endswith(sep + src):
                        title = title[: -(len(sep) + len(src))].strip()
        if len(title) > 220:
            title = title[:220].rstrip() + "…"
        url = entry_link(node)
        if not url.startswith("http"):
            continue
        summary = strip_html(
            child_text(node, ("description", "summary", "content", "encoded", "subtitle")), 500
        )
        if require and not any(k in f"{title} {summary}".lower() for k in require):
            continue
        published = entry_date(node) or datetime.now(JST)
        if published > datetime.now(JST):
            published = datetime.now(JST)
        items.append(
            {
                "title": title,
                "url": url.split("#")[0],
                "summary": summary,
                "source": publisher,
                "feed": feed["name"],
                "region": feed["region"],
                "lang": feed["lang"],
                "via": "google" if feed.get("google") else "direct",
                "published": published.isoformat(),
            }
        )
    return items


def main() -> int:
    items: list[dict] = []
    status = []
    for feed in ALL_FEEDS:
        try:
            got = parse_feed(feed)
            state = "ok"
        except (urllib.error.URLError, ET.ParseError, OSError, ValueError) as exc:
            print(f"[warn] {feed['name']}: {exc}", file=sys.stderr)
            got, state = [], f"error: {type(exc).__name__}"
        label = feed["name"]
        if feed.get("google"):
            query = feed["url"].split("q=")[1].split("&")[0]
            label = f"Google News『{urllib.parse.unquote_plus(query)}』"
        print(f"[{state}] {label}: {len(got)}")
        status.append({"name": label, "status": state, "count": len(got)})
        items.extend(got)

    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    merged: list[dict] = []
    cutoff = datetime.now(JST) - timedelta(days=MAX_AGE_DAYS)
    for item in items:
        key = item["url"].rstrip("/").lower()
        tkey = normalize_title(item["title"])
        if key in seen_urls or tkey in seen_titles:
            continue
        if datetime.fromisoformat(item["published"]) < cutoff:
            continue
        seen_urls.add(key)
        seen_titles.add(tkey)
        merged.append(item)

    merged.sort(key=lambda i: i["published"], reverse=True)
    merged = merged[:MAX_ITEMS]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps({"collected_at": datetime.now(JST).isoformat(), "sources": status, "items": merged},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    ok = sum(1 for s in status if s["status"] == "ok")
    print(f"raw items: {len(merged)} (sources ok={ok}/{len(status)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
