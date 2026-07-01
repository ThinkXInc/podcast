# Podcast 切り出し自動化パイプライン

音源を置く → 自動で文字起こし・字幕生成・切り出し候補生成 → チャットで確認・修正 →
確定したセグメントごとに字幕付き動画を書き出す、までを自動化する。

After Effects は使わない。ただし **後から人がAE等で再編集できる素材を必ず残す**。

---

## 全体の流れ

```
[data/{ID}/ に音源を入れる]   ← プロジェクト内。IDフォルダが起点
        │
        ▼
 ┌─────────────────────────────┐
 │ 1. transcribe.sh <ID>       │  WhisperX large-v3（M1 Maxローカル, 0円）
 │   フォルダ内の音源を探して:    │
 │   - 全文文字起こし(json/txt) │
 │   - 同期字幕(srt/ass)        │
 └─────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────┐
 │ 2. suggest.py               │  GPT-5.5 API（〜300円/本）
 │   プロンプト1-1 / 1-2 / 2-1  │  切り出し候補を Markdown で生成
 └─────────────────────────────┘
        │
        ▼
   ★ ここで Claude Code がチャットに候補を提示 ★
   あなた:「②と③つなげて」「⑤の政治発言カット」「OK」… 何往復でも
        │
        ▼ (確定した segments.json をあなたが承認)
 ┌─────────────────────────────┐
 │ 3. render.py                │  ffmpeg
 │   セグメントごとに:           │
 │   - 音声切り出し(.m4a)        │
 │   - 字幕なし黒背景動画(.mp4)   │
 │   - 字幕焼き込み動画(.mp4)←最終│
 │   - 区間字幕(.ass) 単体       │
 └─────────────────────────────┘
        │
        ▼
 [data/{ID}/contents/ に完成物 + 再編集用素材]
 (サムネ/表紙は後付け。YouTubeアップは手動 or 後で自動化)
```

---

## セットアップ（初回のみ）

**まず、このプロジェクトフォルダを `~/Sources/podcast-pipeline/` に置く**
（解凍してこの場所に移動。Claude Desktop の Code タブで「Select folder...」から開く）。

Claude Code に「README のセットアップを実行して」と言えば、以下を自動でやってくれる。
手動でやる場合の手順も載せておく。

### 1. Homebrew で ffmpeg

```bash
brew install ffmpeg
```

### 2. Python 環境（WhisperX + OpenAI SDK）

M1 Max は Apple Silicon なので、CPU/MPS で動かす。

```bash
# 【規約】venv はプロジェクト内 <project>/venv に作る（~/venvs には作らない）。
# Apple Silicon では arm64 の python3.11 で作ること（Intel版はセグフォルトの原因）。
python3.11 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt   # 固定版一式（whisperx / torch 2.5.1 など）
# ※ 候補生成(suggest.py)用の OpenAI SDK は別 venv .venv-openai を使用（任意）。
```

> WhisperX は内部で faster-whisper を使う。Apple Silicon では
> `--compute_type int8 --device cpu` で安定動作する（large-v3 が 64GB に余裕で乗る）。
> 2時間音源で概ね 15〜40分。

### 3. 日本語フォント（字幕用）

macOS 標準の **ヒラギノ角ゴ** をそのまま使える。
より「YouTube字幕らしい」太ゴシックにしたいなら Noto Sans JP を入れる:

```bash
brew install --cask font-noto-sans-cjk-jp
```

`config/style.conf` の `FONT` を切り替えれば反映される。

### 4. OpenAI API キー

```bash
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.zshrc
source ~/.zshrc
```

> キーは https://platform.openai.com/api-keys で発行。
> 1本あたりの実費は GPT-5.5 でも 〜300円程度（README末尾の試算参照）。

### 5. 置き場所（重要・このプロジェクトの安全設計）

**このプロジェクトは `~/Sources/podcast-pipeline/` に置く。** 音源も成果物もすべて
プロジェクト内の `data/{ID}/` に入れる。Google Drive は直接触らない。

```
~/Sources/podcast-pipeline/      ← Claude が触れるのはここだけ
├─ .claude/settings.json         ← 権限の壁（外への読み書きを deny）
├─ scripts/ prompts/ config/     ← コード
└─ data/{ID}/                    ← 音源と成果物はすべてここ
```

`config/paths.conf` の `PODCAST_ROOT` は `$HERE/data`（＝プロジェクト内の data/）に
設定済み。**編集不要。** `$HERE` はスクリプトが自動でプロジェクトルートに解決する。

> **なぜこの設計か**: Claude Code はデフォルトで作業ディレクトリの外に出られない。
> さらに `.claude/settings.json` で、ホーム配下・他フォルダ・Google Drive 同期領域への
> 書き込み/読み取りを明示的に deny している。事故が起きても被害はこの箱の中だけ。
> 詳細は末尾「権限の壁」参照。

---

## 使い方

**`data/` の中に IDフォルダを作り、音源を入れて、Claude Code に一声かける。**

```
1) data/ の中に IDフォルダを作る（例: data/民主主義の会2-5/）
2) そのフォルダに音源（.m4a 等）を入れる
3) Claude Code（Code タブでこのプロジェクトを開いた状態）にこう言う:
      「民主主義の会2-5 を処理して」
```

Claude Code が transcribe → suggest を実行し、切り出し候補をチャットに出す。
あなたが「②と③つなげて」「⑤の政治発言カット」などと指示し、「OK」と言えば
render が走り、`data/民主主義の会2-5/contents/` に字幕付き動画が完成する。

完成物を Google Drive に上げたいときは、自分で（または Claude にコピーコマンドを
提案させて承認して）コピーする。Claude が Drive に直接書き込むことはない。

### オプション: フォルダ監視で半自動

```bash
brew install fswatch
bash scripts/watch.sh
```

各IDフォルダに音源が置かれたら自動で 1→2 まで走る。

---

## 出力物（1本ぶん） data/{ID}/

```
{ID}/
├─ transcript.json        全文文字起こし（単語タイムスタンプ付き）
├─ transcript.txt         全文（プレーン、AIに渡す用 & 校正用）
├─ full.srt / full.ass    フル音源の字幕
├─ suggestions_1.md       切り出し候補（プロンプト1-1, 1-2 の結果）
├─ suggestions_2.md       追加候補・除外案（プロンプト2-1 の結果）
├─ segments.json          ★確定したセグメント定義（チャットで編集される）
└─ contents/
   ├─ 01_{title}/
   │  ├─ audio.m4a            切り出し音源（再編集用）
   │  ├─ video_nosub.mp4      字幕なし黒背景動画（AE等で字幕入れ直す用）
   │  ├─ segment.ass          この区間の字幕単体（再編集用）
   │  └─ final.mp4            ★字幕焼き込み済み 完成動画
   ├─ 02_{title}/ ...
```

> **「後で人が編集する」要件**: `video_nosub.mp4` + `segment.ass` + `audio.m4a` が
> 残っているので、AE/Premiere/DaVinci に取り込んで字幕の作り直し・テロップ追加・
> 表紙差し込みが自由にできる。final.mp4 はそのまま公開できる完成品。

---

## コスト試算（2時間音源1本）

| 工程 | 手段 | 実費 |
|---|---|---|
| 文字起こし＋字幕 | WhisperX large-v3（ローカル） | 0円 |
| 切り出し生成 | GPT-5.5 API（入力キャッシュ活用） | 〜300円 |
| 動画書き出し | ffmpeg | 0円 |
| **合計** | | **〜300円** |

予算1000円/本に対して余裕。性能優先で GPT-5.5 を使ってこの金額。

---

## 権限の壁（Claude が触れる範囲の制限）

`.claude/settings.json` で、Claude Code が触れる範囲をこのプロジェクト内に閉じている。

**deny（禁止・最優先で効く）**
- プロジェクト外への書き込み・編集（`~/**`, 他の `/Users/**`）
- Google Drive 同期領域（`~/Library/CloudStorage/**`）の読み書き
- 秘密情報の読み取り（`.ssh`, `.aws`, `.env` など）
- 危険コマンド（`rm -rf`, `sudo`, `curl`, `wget`）

**ask（毎回確認）**
- すべての書き込み・編集（プロジェクト内でも一応確認が出る）
- `brew install` / `pip install`

**allow（自動）**
- プロジェクト内の読み取り、パイプラインの各スクリプト実行

> ルールは deny → ask → allow の順で評価され、deny が最優先。
> deny に当たる操作は、たとえ allow があっても実行されない。

### さらに堅くしたい場合（OSレベル Sandbox）

Claude Code 内で `/sandbox` を実行すると、macOS の Seatbelt で Bash の
ファイル/ネットワークアクセスを OS レベルで制限できる（サブプロセスごと隔離）。
deny ルールだけだと、python/whisperx 等のサブプロセスが直接ファイルを開く動作までは
止められないため、最大限に固めたいときは Sandbox を併用する。
まずは deny ルール＋毎回の手動承認で運用し、必要を感じたら足せばよい。

### 注意
- Claude Desktop 版では settings.json の自動承認が効かず、毎回手動承認になる場合がある。
  その場合はむしろ「毎回あなたが確認できる」状態なので、安全側に倒れている。
- このパイプラインのスクリプトは設計上 `data/` 配下にしか書き込まないので、
  deny ルールと二重で守られている。
