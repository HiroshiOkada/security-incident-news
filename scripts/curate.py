#!/usr/bin/env python3
"""収集した素材から「本当に重要な事件」を AI で選び、記事を書き、過去事件をフォローアップする。

- 新規記事は通常 1 件、同日に複数の重大事件があれば最大 3 件
- 既存記事は、関連する新着記事があればタイムラインに追記
- 出力: data/incidents.json, data/skipped.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw.json"
INCIDENTS = DATA / "incidents.json"
SKIPPED = DATA / "skipped.json"

JST = timezone(timedelta(hours=9))
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [
    m.strip()
    for m in os.environ.get(
        "CURATOR_MODELS", "deepseek/deepseek-v4.1-flash-1017,deepseek/deepseek-v4-flash"
    ).split(",")
    if m.strip()
]
MAX_CANDIDATES = 70
MAX_DIRECT = 42
MAX_NEW_PER_RUN = 3
CANDIDATE_WINDOW_HOURS = int(os.environ.get("CURATOR_WINDOW_HOURS", "96"))
FOLLOWUP_WINDOW_DAYS = 45
SKIP_TTL_DAYS = 5


def now_jst() -> datetime:
    return datetime.now(JST)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    env = Path("/workspace/mail-pipeline/.env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("OPENROUTER_API_KEY が設定されていません")


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def call_llm(messages: list[dict], max_tokens: int = 3600, temperature: float = 0.3) -> dict:
    key = api_key()
    last_err = ""
    for model in MODELS:
        for attempt in range(2):
            body = json.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                }
            ).encode()
            req = urllib.request.Request(
                API_URL,
                data=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/HiroshiOkada/security-incident-news",
                    "X-Title": "Security Incident Watch",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    payload = json.loads(resp.read())
                content = (payload["choices"][0]["message"].get("content") or "").strip()
                if not content:
                    raise json.JSONDecodeError("empty content", "", 0)
                return parse_json(content)
            except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
                last_err = f"{model}: {type(exc).__name__} {exc}"
                print(f"[warn] {last_err}", file=sys.stderr)
                time.sleep(3 + attempt * 5)
    raise SystemExit(f"LLM 呼び出しに失敗しました: {last_err}")


SELECTION_SYSTEM = """あなたは日本語メディアのセキュリティ編集長です。
世界中の報道から「日本の読者に伝える価値のある重大インシデント」だけを選び、記事を書きます。

【採用するもの】
- 大規模な情報漏えい・不正アクセス（数万人以上、金融・通信・医療・政府・重要インフラ、大手企業の顧客情報など）
- 広く使われているソフトウェア・機器の重大な脆弱性（悪用済み、リモートから認証不要で実行、CVSS 高、大規模影響。例: PHP の CVE-2026-109619 級）
- ランサムウェアによる業務停止、サプライチェーン侵害、国家的背景のある攻撃で社会的影響が大きいもの

【採用しないもの】
- 個別製品の定例アップデート一覧、軽微な脆弱性の羅列、CVSS 低〜中
- 調査レポート/統計の紹介、意見記事、用語解説、イベント告知、販促、PoC 公開のみ
- 小規模なフィッシングや、被害規模が不明で影響が限定的なもの

【件数】通常は最大 1 件。同じ日に複数の重大事件が起きた場合（例: 大規模漏えいが別々に 2 件、悪用中の重大脆弱性が同時に判明）のみ最大 3 件まで出してよい。迷ったら少なくする。
同じ事件を複数媒体が報じている場合は 1 件にまとめ、source_urls に複数 URL を入れる。

【執筆ルール】
- 与えられた候補（タイトル・要約）に書かれていない事実を創作しない。数値が無ければ「不明」と書く。
- 推測を書く場合は「〜とみられる」と明示する。
- 日本語として自然で、専門用語には短い補足を付ける。
- lead は 2〜3 文（120〜220 字）。cause は原因・侵入経路・脆弱性の技術的性質。impact は被害規模・範囲・事業影響。ai_angle は、AI が事件に関与した（AI を使った攻撃・AI サービスへの影響・AI による検知）なら具体的に、関与が無いなら「AI の関与は確認されていない」と明記した上で、AI 時代の実務への示唆を 1 点だけ具体的に書く。一般論を並べない。
- severity は critical（社会全体に深刻）/ high（大規模・重大）/ medium（重要だが影響は限定的）。
- keywords は後日のフォローアップ記事を検出するための語（社名・製品名・CVE・攻撃グループ名など、日本語/英語混在可）。
- slug は英語のケバブケース 2〜4 語（例: php-cve-2026-109619）。

【出力】JSON のみ。余計な文章は書かない。
{"incidents": [{"title": "...", "slug": "...", "category": "breach|vulnerability", "region": "jp|world",
   "severity": "critical|high|medium", "event_date": "YYYY-MM-DD", "lead": "...", "cause": "...",
   "impact": "...", "ai_angle": "...", "tags": ["..."], "keywords": ["..."],
   "status": "ongoing|resolved", "source_urls": ["..."]}],
 "reason": "件数を絞った/出さなかった理由"}
該当が無ければ incidents は空配列。"""


FOLLOWUP_SYSTEM = """あなたはセキュリティニュースの編集者です。
過去に掲載した事件について、新しく出た関連報道を読み、フォローアップ（続報）を書きます。

【ルール】
- 新しい事実（被害規模の確定、原因の判明、犯人グループの特定、対応状況、規制の動き）だけを 1〜2 文（60〜140 字）で書く。
- 候補記事に書かれていないことは書かない。推測は「〜とみられる」。
- 進展が無い候補は無視してよい。無理に書かない。
- 事件が収束した（対応完了・原因確定・犯人逮捕など）なら status を resolved にする。
- 出力は JSON のみ:
{"updates": [{"url": "...", "date": "YYYY-MM-DD", "note": "..."}], "status": "ongoing|resolved"}"""


def build_candidate_block(items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            json.dumps(
                {
                    "no": i,
                    "title": it["title"],
                    "summary": it.get("summary", "")[:280],
                    "source": it["source"],
                    "published": it["published"][:16],
                    "url": it["url"],
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def make_id(event_date: str, slug: str, taken: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9\-]+", "-", slug.lower()).strip("-")[:48] or "incident"
    base = f"{event_date}-{slug}"
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def pick_candidates(raw_items: list[dict], processed: set[str]) -> list[dict]:
    cutoff = now_jst() - timedelta(hours=CANDIDATE_WINDOW_HOURS)
    pool = [
        it
        for it in raw_items
        if it["url"] not in processed and datetime.fromisoformat(it["published"]) >= cutoff
    ]
    pool.sort(key=lambda i: i["published"], reverse=True)
    direct = [it for it in pool if it.get("via") != "google"]
    google = [it for it in pool if it.get("via") == "google"]
    chosen = direct[:MAX_DIRECT] + google[: MAX_CANDIDATES - MAX_DIRECT]
    chosen.sort(key=lambda i: i["published"], reverse=True)
    return chosen


def build_incident(inc: dict, by_url: dict, taken: set[str]) -> dict | None:
    urls = [u for u in inc.get("source_urls", []) if u in by_url]
    if not urls:
        return None
    sources = []
    for url in urls[:5]:
        it = by_url[url]
        sources.append(
            {
                "title": it["title"],
                "url": url,
                "publisher": it["source"],
                "published": it["published"][:10],
            }
        )
    event_date = inc.get("event_date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date or ""):
        event_date = sources[0]["published"]
    title = (inc.get("title") or "").strip()
    lead = (inc.get("lead") or "").strip()
    if not title or not lead:
        return None
    return {
        "id": make_id(event_date, inc.get("slug") or hashlib.md5(title.encode()).hexdigest()[:8], taken),
        "event_date": event_date,
        "category": inc.get("category", "breach"),
        "region": inc.get("region", "world"),
        "severity": inc.get("severity", "high"),
        "title": title,
        "lead": lead,
        "cause": (inc.get("cause") or "").strip(),
        "impact": (inc.get("impact") or "").strip(),
        "ai_angle": (inc.get("ai_angle") or "").strip(),
        "tags": (inc.get("tags") or [])[:4],
        "keywords": (inc.get("keywords") or [])[:8],
        "status": inc.get("status", "ongoing"),
        "sources": sources,
        "timeline": [],
        "created_at": now_jst().isoformat(timespec="seconds"),
        "updated_at": now_jst().isoformat(timespec="seconds"),
    }


def curate_new(raw_items: list[dict], incidents: list[dict], skipped: dict) -> tuple[list[dict], dict]:
    processed = set()
    for inc in incidents:
        processed.update(s.get("url", "") for s in inc.get("sources", []))
        processed.update(u.get("url", "") for u in inc.get("timeline", []))
    processed.update(skipped.keys())

    candidates = pick_candidates(raw_items, processed)
    print(f"new candidates: {len(candidates)}")
    if not candidates:
        return [], {}

    prompt = (
        "以下は直近のセキュリティ関連記事の候補です。この中から掲載すべき重大インシデントを選び、"
        "日本語の記事を書いてください（通常は最大 1 件、同日に複数の重大事件がある場合のみ最大 3 件）。"
        "該当が無ければ incidents を空にしてください。\n\n" + build_candidate_block(candidates)
    )
    result = call_llm(
        [{"role": "system", "content": SELECTION_SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=4000,
    )

    rejected = {it["url"]: now_jst().isoformat() for it in candidates}
    by_url = {it["url"]: it for it in candidates}
    taken = {i["id"] for i in incidents}
    created: list[dict] = []
    for raw_inc in (result.get("incidents") or [])[:MAX_NEW_PER_RUN]:
        if not isinstance(raw_inc, dict):
            continue
        incident = build_incident(raw_inc, by_url, taken)
        if not incident:
            continue
        taken.add(incident["id"])
        created.append(incident)
        for url in [u for u in raw_inc.get("source_urls", []) if u in by_url]:
            rejected.pop(url, None)
        print(f"published: {incident['title']}")

    if not created:
        print(f"no publish: {result.get('reason', '')}")
    return created, rejected


def follow_up(raw_items: list[dict], incidents: list[dict]) -> list[str]:
    touched = []
    cutoff = now_jst() - timedelta(days=FOLLOWUP_WINDOW_DAYS)
    targets = [
        inc
        for inc in incidents
        if inc.get("status") != "resolved"
        and datetime.fromisoformat(inc["event_date"]).replace(tzinfo=JST) >= cutoff
    ]
    for inc in targets:
        known = {s["url"] for s in inc.get("sources", [])} | {u.get("url") for u in inc.get("timeline", [])}
        kws = [k.lower() for k in inc.get("keywords", []) if len(k) >= 2]
        if not kws:
            continue
        hits = []
        for it in raw_items:
            if it["url"] in known or it["published"][:10] < inc["event_date"]:
                continue
            hay = f"{it['title']} {it.get('summary', '')}".lower()
            if any(k in hay for k in kws):
                hits.append(it)
        hits = hits[:8]
        if not hits:
            continue

        prompt = (
            f"事件: {inc['title']}\n掲載日: {inc['event_date']}\n概要: {inc.get('lead', '')}\n"
            f"既知の経緯: {json.dumps([u.get('note') for u in inc.get('timeline', [])], ensure_ascii=False)}\n\n"
            "以下の新着関連記事から、フォローアップを書いてください。\n" + build_candidate_block(hits)
        )
        try:
            result = call_llm(
                [{"role": "system", "content": FOLLOWUP_SYSTEM}, {"role": "user", "content": prompt}],
                max_tokens=900,
                temperature=0.2,
            )
        except SystemExit as exc:
            print(f"[warn] follow-up skipped: {exc}", file=sys.stderr)
            continue

        valid = {it["url"] for it in hits}
        by_url = {it["url"]: it for it in hits}
        added = 0
        for upd in result.get("updates", [])[:3]:
            url = upd.get("url")
            if url not in valid or not upd.get("note"):
                continue
            inc.setdefault("timeline", []).append(
                {
                    "date": upd.get("date") or by_url[url]["published"][:10],
                    "note": upd["note"].strip()[:400],
                    "url": url,
                    "publisher": by_url[url]["source"],
                    "title": by_url[url]["title"],
                }
            )
            added += 1
        if added:
            inc["timeline"].sort(key=lambda u: u["date"])
            inc["updated_at"] = now_jst().isoformat(timespec="seconds")
            if result.get("status") == "resolved":
                inc["status"] = "resolved"
            touched.append(inc["id"])
            print(f"follow-up: {inc['id']} (+{added})")
    return touched


def main() -> int:
    raw = load_json(RAW, {"items": []})
    raw_items = raw.get("items", [])
    store = load_json(INCIDENTS, {"incidents": []})
    incidents = store.get("incidents", [])
    skipped = load_json(SKIPPED, {})

    ttl = now_jst() - timedelta(days=SKIP_TTL_DAYS)
    skipped = {u: ts for u, ts in skipped.items() if ts >= ttl.isoformat()}

    created, rejected = curate_new(raw_items, incidents, skipped)
    skipped.update(rejected)
    incidents.extend(created)

    touched = follow_up(raw_items, incidents)

    incidents.sort(key=lambda i: (i["event_date"], i["created_at"]), reverse=True)
    DATA.mkdir(parents=True, exist_ok=True)
    INCIDENTS.write_text(
        json.dumps(
            {"generated_at": now_jst().isoformat(timespec="seconds"), "incidents": incidents},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    SKIPPED.write_text(json.dumps(skipped, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"incidents total={len(incidents)} new={len(created)} followed_up={len(touched)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
