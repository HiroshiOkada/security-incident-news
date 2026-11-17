# Security Incident Watch

国内外の**重大なセキュリティ事故**（大規模な情報漏えい・侵害、悪用中の重大脆弱性）だけを選んで記録するアーカイブサイトです。GitHub Pages で公開し、GitHub Actions が毎朝 7:30 (JST) に収集・選定・執筆・フォローアップを行います。

公開 URL: https://hiroshiokada.github.io/security-incident-news/

## 編集方針

- **量より重要度**: 通常は 1 日 0〜1 件。大きな事件が無い日は何も追加しません。
- **複数可**: 同日に複数の重大事件（例: 大規模漏えいが別々に発生、悪用中の重大脆弱性が判明）があれば最大 3 件まで記録します。
- **詳細ページ**: 1 事件につき 1 ページ。原因・影響・AI との関係・出典リンクをまとめます。
- **フォローアップ**: 掲載済みの事件に新しい関連報道が出れば「その後の展開」として追記し、収束したものは `resolved` にします。

## 仕組み

```
RSS / Google News (19 クエリ)
   │  scripts/collect.py   … 候補プール data/raw.json（直近10日）
   ▼
scripts/curate.py           … OpenRouter の LLM が選定・執筆・続報生成
   │                          → data/incidents.json（掲載記事）, data/skipped.json
   ▼
scripts/build.py            … index.html と incidents/<id>.html を生成
   ▼
GitHub Pages (Actions でデプロイ)
```

- 選定は LLM（既定: `deepseek/deepseek-v4.1-flash-1017`、失敗時 `deepseek/deepseek-v4-flash`）。`CURATOR_MODELS` で変更可。
- 選ばれなかった候補は 5 日間スキップ（その後、成長した事件として再評価されます）。
- 生成 HTML もリポジトリにコミットするので、ローカルで開けばそのまま読めます。

## ローカルでの実行

```bash
python3 scripts/collect.py     # 候補収集
OPENROUTER_API_KEY=... python3 scripts/curate.py   # 選定・執筆（鍵は環境変数 or /workspace/mail-pipeline/.env）
python3 scripts/build.py       # HTML 生成
python3 -m http.server 8000
```

Python 3.9+ のみ（外部パッケージ不要）。

## 運用

- 定期実行: 毎日 22:30 UTC（07:30 JST）。手動実行は Actions の `Curate & deploy` → Run workflow。
- 必要な Secret: `OPENROUTER_API_KEY`（リポジトリ Secrets に登録済み）。
- 情報源の追加は `scripts/collect.py` の `FEEDS` / `GOOGLE_FEEDS`。
- 選定基準の調整は `scripts/curate.py` の `SELECTION_SYSTEM` プロンプト。

## ファイル構成

```
index.html                  一覧（自動生成）
incidents/<id>.html         事件の詳細ページ（自動生成）
assets/site.css             スタイル（ライト/ダーク自動切替）
data/incidents.json         掲載記事データ
data/skipped.json           選外にした候補（再評価用）
scripts/collect.py          候補収集
scripts/curate.py           AI 選定・執筆・フォローアップ
scripts/build.py            HTML 生成
.github/workflows/pages.yml 毎日の収集 + デプロイ
```
