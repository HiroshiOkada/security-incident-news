# Security Incident Watch

日本と世界のセキュリティ事故（インシデント）・脆弱性・情報漏えいニュースを、主要メディア／公的機関の RSS・Atom から自動収集して一覧化する静的サイトです。GitHub Pages で公開し、GitHub Actions が 1 時間ごとにデータを更新します。

公開 URL: https://hiroshiokada.github.io/security-incident-news/

## 仕組み

```
RSS/Atom (14 sources)
      │  scripts/fetch_news.py  (Python 標準ライブラリのみ)
      ▼
data/news.json   ← GitHub Actions が毎時生成・コミット
      │
      ▼
index.html + assets/  ← 素の HTML/CSS/JS。ビルド不要
      │
      ▼
GitHub Pages (Actions デプロイ)
```

- **収集**: `scripts/fetch_news.py` が各フィードを取得し、HTML タグ除去・日付正規化（JST）・URL/タイトルによる重複排除・タグ付け（ランサムウェア、情報漏えい、脆弱性など）を行う。
- **保持**: 直近 120 日・最大 900 件。過去分は `data/news.json` に残るため、フィードから流れてしまった記事も保持される。
- **表示**: `assets/app.js` が JSON を読み込み、地域（国内／海外）・期間・タグ・キーワードで絞り込んで日付ごとに表示。条件は URL クエリに反映されるので共有可能。

## 情報源

| 地域 | ソース |
|---|---|
| 国内 | Security NEXT / ScanNetSecurity / JPCERT/CC 注意喚起 / JVN 脆弱性情報 / ITmedia エンタープライズ（セキュリティ関連のみ） |
| 海外 | The Hacker News / BleepingComputer / Krebs on Security / The Record / Dark Reading / SecurityWeek / CISA Advisories / JPCERT/CC (EN) / Unit 42 |

## ローカルでの実行

```bash
python3 scripts/fetch_news.py          # data/news.json を更新
python3 -m http.server 8000            # http://localhost:8000 で確認
```

Python 3.9+ のみ必要（外部パッケージなし）。

## 情報源の追加・変更

`scripts/fetch_news.py` の `FEEDS` に 1 行追加するだけです。

```python
{"name": "Example Security", "url": "https://example.com/feed", "region": "world", "lang": "en"},
# ITmedia のように全ジャンルを配信するフィードは require_keywords で絞り込む
```

`region` は `jp` か `world`。取得に失敗したソースはサイト下部の「情報源」に NG として表示され、既存データは保持されます。

## ファイル構成

```
index.html                  サイト本体
assets/style.css            スタイル
assets/app.js               表示・絞り込みロジック
data/news.json              収集結果（自動生成）
scripts/fetch_news.py       収集スクリプト
.github/workflows/pages.yml 毎時更新 + Pages デプロイ
```
