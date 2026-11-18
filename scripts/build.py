#!/usr/bin/env python3
"""data/incidents.json から静的サイト (index.html と incidents/<id>.html) を生成する。"""

from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
BUILT_AT = datetime.now(JST)
BUILT_STR = BUILT_AT.strftime("%Y-%m-%d %H:%M")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "incidents.json"
OUT = ROOT
DETAIL_DIR = OUT / "incidents"

CATEGORY_LABEL = {"breach": "情報漏えい・侵害", "vulnerability": "重大な脆弱性"}
CATEGORY_SHORT = {"breach": "漏えい", "vulnerability": "脆弱性"}
CATEGORY_CLASS = {"breach": "c-breach", "vulnerability": "c-vuln"}
REGION_LABEL = {"jp": "国内", "world": "海外"}
SEVERITY_LABEL = {"critical": "重大", "high": "重要", "medium": "注目"}
SEVERITY_CLASS = {"critical": "s-critical", "high": "s-high", "medium": "s-medium"}

SITE_NAME = "Security Incident Watch"
SITE_DESC = "国内外の大規模な情報漏えいと重大な脆弱性だけを、1日1件選んで記録するセキュリティ事故アーカイブ。"


def esc(text: str | None) -> str:
    return html.escape(text or "", quote=True)


def jp_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.year}年{d.month}月{d.day}日"


def jp_date_short(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.month}/{d.day}"


def page(title: str, description: str, body: str, root: str = "", extra_head: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%9B%A1%EF%B8%8F%3C/text%3E%3C/svg%3E">
<link rel="stylesheet" href="{root}assets/site.css">{extra_head}
</head>
<body>
{body}
</body>
</html>
"""


def masthead(root: str = "") -> str:
    return f"""<header class="masthead">
  <div class="wrap">
    <div class="masthead-top">
      <a class="brand" href="{root}index.html">
        <span class="brand-mark" aria-hidden="true">◈</span>
        <span class="brand-name">{SITE_NAME}</span>
      </a>
    </div>
    <h1><a href="{root}index.html">重大セキュリティ事故の記録</a></h1>
    <p class="tagline">国内外の大規模な情報漏えいと重大な脆弱性を、<br class="br-sp">一日一件だけ選んで記録します。</p>
  </div>
</header>"""


def footer(generated_at: str, root: str = "") -> str:
    return f"""<footer class="site-footer">
  <div class="wrap footer-inner">
    <div class="footer-col">
      <p class="footer-title">このサイトについて</p>
      <p>国内外の報道から、社会的影響の大きいセキュリティ事故と重大な脆弱性だけを選び、原因・影響・AIとの関係を整理して記録しています。記事本文は AI による要約・編集を含みます。正確な情報は各出典をご確認ください。</p>
    </div>
    <div class="footer-col">
      <p class="footer-title">アーカイブ</p>
      <p><a href="{root}index.html">記事一覧</a> ／ <a href="https://github.com/HiroshiOkada/security-incident-news" target="_blank" rel="noopener">GitHub</a></p>
      <p class="footer-meta">最終生成 {BUILT_STR} JST ／ 最終選定 {esc(generated_at.replace("T", " ")[:16])} JST</p>
    </div>
  </div>
</footer>"""


def render_index(data: dict) -> str:
    incidents = data.get("incidents", [])
    latest = incidents[0] if incidents else None
    rest = incidents[1:]
    total = len(incidents)
    this_month = sum(1 for i in incidents if i["event_date"][:7] == BUILT_AT.strftime("%Y-%m")) if incidents else 0
    today = BUILT_AT.strftime("%Y-%m-%d")
    today_count = sum(1 for i in incidents if i.get("created_at", "")[:10] == today)

    if latest:
        hero = f"""<article class="hero">
  <div class="hero-meta">
    <span class="badge {SEVERITY_CLASS.get(latest['severity'], '')}">{SEVERITY_LABEL.get(latest['severity'], '')}</span>
    <span class="badge {CATEGORY_CLASS.get(latest['category'], '')}">{CATEGORY_LABEL.get(latest['category'], '')}</span>
    <span class="meta-text">{jp_date(latest['event_date'])} ・ {REGION_LABEL.get(latest['region'], '')}</span>
  </div>
  <h2 class="hero-title"><a href="incidents/{esc(latest['id'])}.html">{esc(latest['title'])}</a></h2>
  <p class="hero-lead">{esc(latest['lead'])}</p>
  <a class="read-more" href="incidents/{esc(latest['id'])}.html">全文を読む<span aria-hidden="true"> →</span></a>
</article>"""
    else:
        hero = """<div class="empty-state">
  <p class="empty-title">現在、掲載すべき重大な事件はありません</p>
  <p>基準に該当する事故・脆弱性が確認された時点で、ここに追加されます。</p>
</div>"""

    rows = []
    for inc in rest:
        tag = "更新あり" if inc.get("updated_at", "") > inc.get("created_at", "") else ""
        rows.append(
            f"""<li class="row">
  <a href="incidents/{esc(inc['id'])}.html">
    <span class="row-date">{jp_date(inc['event_date'])}</span>
    <span class="row-badge {CATEGORY_CLASS.get(inc['category'], '')}">{CATEGORY_SHORT.get(inc['category'], '')}</span>
    <span class="row-title">{esc(inc['title'])}</span>
    <span class="row-region">{REGION_LABEL.get(inc['region'], '')}</span>
    {f'<span class="row-updated">{tag}</span>' if tag else ''}
  </a>
</li>"""
        )

    archive = (
        f"""<section class="archive">
  <div class="section-head">
    <h2>過去の事件</h2>
    <span class="section-count">{len(rest)} 件</span>
  </div>
  <ol class="rows">{''.join(rows)}</ol>
</section>"""
        if rest
        else ""
    )

    today_note = (
        """<p class="today-note">本日は基準に該当する新規の事件がありませんでした（毎朝 7:30 に自動で確認しています）。</p>"""
        if today_count == 0
        else ""
    )
    body = f"""{masthead()}
<main class="wrap">
  <div class="meta-bar">
    <span>収録 {total} 件</span>
    <span>今月 {this_month} 件</span>
    <span>本日 {today_count} 件</span>
    <span>最終更新 {BUILT_STR} JST</span>
  </div>
  {today_note}
  {hero}
  {archive}
</main>
{footer(data.get('generated_at', ''))}"""
    return page(f"{SITE_NAME}｜重大セキュリティ事故の記録", SITE_DESC, body)


def render_detail(inc: dict, data: dict) -> str:
    incidents = data.get("incidents", [])
    idx = next((i for i, x in enumerate(incidents) if x["id"] == inc["id"]), None)
    newer = incidents[idx - 1] if idx not in (None, 0) else None
    older = incidents[idx + 1] if idx is not None and idx + 1 < len(incidents) else None

    sections = []
    if inc.get("cause"):
        sections.append(("原因・侵入経路", inc["cause"]))
    if inc.get("impact"):
        sections.append(("影響・被害規模", inc["impact"]))
    if inc.get("ai_angle"):
        sections.append(("AI との関係", inc["ai_angle"]))
    body_sections = "".join(
        f"""<section class="article-section">
  <h2>{esc(title)}</h2>
  <p>{esc(text)}</p>
</section>"""
        for title, text in sections
    )

    timeline = ""
    if inc.get("timeline"):
        items = "".join(
            f"""<li>
  <span class="tl-date">{jp_date(u['date'])}</span>
  <span class="tl-note">{esc(u['note'])}</span>
  {f'<a class="tl-src" href="{esc(u["url"])}" target="_blank" rel="noopener">{esc(u.get("publisher", "出典"))}</a>' if u.get("url") else ''}
</li>"""
            for u in inc["timeline"]
        )
        timeline = f"""<section class="timeline">
  <h2>その後の展開</h2>
  <ol>{items}</ol>
</section>"""

    sources = "".join(
        f"""<li>
  <a href="{esc(s['url'])}" target="_blank" rel="noopener">{esc(s['title'])}</a>
  <span class="src-meta">{esc(s.get('publisher', ''))} ・ {esc(jp_date(s.get('published', '')))}</span>
</li>"""
        for s in inc.get("sources", [])
    )

    nav = ""
    if newer or older:
        parts = []
        if newer:
            parts.append(f'<a class="nav-link" href="{esc(newer["id"])}.html"><span>新しい記事</span>{esc(newer["title"])}</a>')
        if older:
            parts.append(f'<a class="nav-link" href="{esc(older["id"])}.html"><span>古い記事</span>{esc(older["title"])}</a>')
        nav = f'<nav class="article-nav">{"".join(parts)}</nav>'

    updated = ""
    if inc.get("updated_at", "") > inc.get("created_at", ""):
        updated = f'<p class="updated-note">最終更新 {esc(jp_date(inc["updated_at"]))}（続報を追記）</p>'

    body = f"""{masthead(root="../")}
<main class="wrap article">
  <p class="breadcrumb"><a href="../index.html">記事一覧</a><span aria-hidden="true"> / </span>{esc(CATEGORY_LABEL.get(inc['category'], ''))}</p>
  <header class="article-head">
    <div class="hero-meta">
      <span class="badge {SEVERITY_CLASS.get(inc['severity'], '')}">{SEVERITY_LABEL.get(inc['severity'], '')}</span>
      <span class="badge {CATEGORY_CLASS.get(inc['category'], '')}">{CATEGORY_LABEL.get(inc['category'], '')}</span>
      <span class="meta-text">{jp_date(inc['event_date'])} ・ {REGION_LABEL.get(inc['region'], '')}</span>
    </div>
    <h1>{esc(inc['title'])}</h1>
    <p class="lead">{esc(inc['lead'])}</p>
    {updated}
  </header>
  {body_sections}
  {timeline}
  <section class="sources">
    <h2>出典</h2>
    <ul>{sources}</ul>
  </section>
  {nav}
</main>
{footer(data.get('generated_at', ''), root='../')}"""

    return page(f"{inc['title']}｜{SITE_NAME}", inc.get("lead", SITE_DESC), body, root="../")


def main() -> int:
    if not DATA.exists():
        raise SystemExit("data/incidents.json がありません")
    data = json.loads(DATA.read_text(encoding="utf-8"))

    if DETAIL_DIR.exists():
        shutil.rmtree(DETAIL_DIR)
    DETAIL_DIR.mkdir(parents=True)

    for inc in data.get("incidents", []):
        (DETAIL_DIR / f"{inc['id']}.html").write_text(render_detail(inc, data), encoding="utf-8")

    (OUT / "index.html").write_text(render_index(data), encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"built index.html + {len(data.get('incidents', []))} detail pages at {BUILT_STR} JST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
