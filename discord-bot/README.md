# stella-bot — Discord 質疑応答AIボット

指定した**複数チャンネルの発言を知識として取り込み**、その内容にもとづいて
質問に答える Discord ボットです。RAG（検索拡張生成）方式なので、
取り込んだ実際の発言だけを根拠に回答し、**ハルシネーション（でたらめ）を抑えます**。

管理はすべて **Discord のスラッシュコマンド**で行うため、
PC・iPhone・Android どの Discord アプリからでも操作できます。

---

## 特徴

- 🤖 **質疑応答特化**：指定チャンネルの内容にもとづいて回答。文脈に無い質問には正直に「見当たりません」と答える。
- 🔎 **RAG構成**：チャンネル履歴をベクトル化して保存 → 質問に近い発言だけをAIへ渡す → 安く・正確に回答。
- 💰 **低コスト**：生成・埋め込みとも Google Gemini を使用。無料枠が大きく、個人運用なら月数百円〜ほぼ無料。
- 🪶 **軽量**：ベクトルDBは SQLite + numpy だけ。重い外部DB不要で、無料ホスティングでも動く。
- 📱 **どの端末からも管理**：操作はスラッシュコマンドのみ。

---

## 仕組み（ざっくり）

```
[登録チャンネルの発言] --(埋め込み:Gemini)--> [ベクトルとしてSQLiteに保存]
                                                        |
ユーザーの質問 --(埋め込み)--> [類似する発言を検索] --> [上位だけAIに渡す] --> 回答
```

---

## セットアップ手順

### 1. Discord ボットを作る

1. <https://discord.com/developers/applications> にアクセスし「New Application」。
2. 左メニュー **Bot** → **Reset Token** でトークンを取得（`DISCORD_BOT_TOKEN` に使う）。
3. 同じ **Bot** ページの **Privileged Gateway Intents** で
   **MESSAGE CONTENT INTENT** を **ON** にする（← 必須。これが無いと発言を読めません）。
4. 左メニュー **OAuth2 → URL Generator** で
   - SCOPES: `bot`, `applications.commands`
   - BOT PERMISSIONS: `Read Messages/View Channels`, `Read Message History`, `Send Messages`
   を選び、生成されたURLでボットを自分のサーバーに招待。

### 2. Gemini API キーを取る

<https://aistudio.google.com/app/apikey> で無料取得 → `GEMINI_API_KEY` に使う。

### 3. 設定ファイルを用意

```bash
cp .env.example .env
# .env を開いて DISCORD_BOT_TOKEN と GEMINI_API_KEY を記入
```

### 4. 起動

**ローカル（PCで試す）:**
```bash
pip install -r requirements.txt
python bot.py
```

**Docker:**
```bash
docker build -t stella-bot .
docker run --env-file .env -v $(pwd)/data:/app/data stella-bot
```

---

## 24時間稼働させる（おすすめホスティング）

ボット本体はサーバーで常時稼働させ、操作はスマホ/PCのDiscordから行う形になります。
ブラウザだけで完結し管理が容易なサービス例:

| サービス | 特徴 |
|----------|------|
| **Railway** | GitHub連携でこのリポジトリを指定するだけ。`data/` をVolumeにすると取り込みデータが消えない。 |
| **Render** | Background Worker として常駐。無料枠あり。 |
| **Fly.io / VPS** | Dockerでそのまま動かせる。 |

> いずれも環境変数（`DISCORD_BOT_TOKEN`, `GEMINI_API_KEY`）をダッシュボードで設定します。
> `.env` ファイルはコミットしないでください（`.gitignore` 済み）。

---

## 使い方（スラッシュコマンド）

| コマンド | 説明 | 権限 |
|----------|------|------|
| `/source_add channel:#一般` | チャンネルを知識に登録し、過去ログを取り込む | サーバー管理 |
| `/source_remove channel:#一般` | 登録解除（取り込み内容も削除） | サーバー管理 |
| `/source_list` | 登録中のチャンネル一覧と件数 | 全員 |
| `/reindex` | 登録チャンネルを取り込み直す | サーバー管理 |
| `/status` | 取り込み状況・使用モデルの確認 | 全員 |
| `/ask question:〇〇は？` | 内容にもとづいて質問に回答 | 全員 |

- ボットを **@メンション**して質問してもOKです（例: `@stella-bot イベントの日程は？`）。
- 登録チャンネルの**新規発言は自動で索引に追加**されるため、基本 `/reindex` は不要です。

### 使い始めの流れ

1. ボットを招待して起動。
2. `/source_add` で統合したいチャンネルを1つずつ登録（複数可）。
3. `/ask` または @メンションで質問。

---

## 設定一覧（.env）

| 変数 | 既定値 | 説明 |
|------|--------|------|
| `DISCORD_BOT_TOKEN` | （必須） | Discordボットのトークン |
| `GEMINI_API_KEY` | （必須） | Gemini APIキー |
| `GEMINI_CHAT_MODEL` | `gemini-3.5-flash` | 回答生成モデル |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | 埋め込みモデル |
| `GEMINI_EMBED_DIM` | `768` | 埋め込み次元（小さいほど省メモリ） |
| `HISTORY_LIMIT` | `2000` | 1チャンネルあたり取り込む過去件数 |
| `TOP_K` | `8` | 質問時に参照する関連発言数 |
| `MIN_SCORE` | `0.55` | これ未満の類似度は無関係として除外 |
| `DB_PATH` | `data/stella_bot.sqlite3` | データ保存先 |

---

## よくある質問

**Q. お金はどれくらいかかる？**
Gemini Flash は非常に安価で、Q&A程度の利用なら無料枠内に収まることも多いです。
埋め込みも取り込み時の一度きり（＋新規発言分）なので低コストです。

**Q. でたらめな回答（ハルシネーション）が心配。**
「参考情報だけを根拠に答え、無ければ正直に分からないと言う」よう指示しており、
さらに `temperature` を低く設定しています。`MIN_SCORE` を上げるとより慎重になります。

**Q. 別のAI（OpenAI等）に変えたい。**
`llm.py` の `embed_texts` と `generate_answer` を差し替えるだけで他社APIに切替できます。
