# Claude Code 共通規約（プロジェクトは作業ディレクトリ内で完結させる）

これはこのプロジェクト専用ではなく、**Claude Code で作業する全プロジェクトに適用する普遍ルール**。
新しいプロジェクトを始めるときは、この規約を各プロジェクトの CLAUDE.md からリンク／コピーして使い回す。

## 原則
プロジェクトに関わるファイルは、すべてそのプロジェクトの作業ディレクトリの中に置く。
ホームディレクトリや共有の場所（`~/venvs`, `~/.cache` を要求する置き方, `/usr/local` など）に
プロジェクト固有のものを散らさない。作業ディレクトリごと移動・複製・削除すれば完結する状態を保つ。

## 具体ルール
1. **Python 仮想環境はプロジェクト直下に置く／作ったら必ず requirements.txt を同梱する**
   - `<project>/venv` に作る。`~/venvs/...` には作らない。
   - 作成: `python3 -m venv <project>/venv && source <project>/venv/bin/activate`
   - **venv を作った（またはコピー／依存を更新した）ら、必ず `<project>/requirements.txt`
     を書き出す**。venv 実体（1GB超になりがち）ではなく requirements.txt を「正」とし、
     いつでも `python3 -m venv venv && venv/bin/pip install -r requirements.txt` で
     再現できる状態を保つ。venv を作って requirements.txt が無い状態を残さない。
   - 生成: `venv/bin/pip freeze > requirements.txt`。バージョンは固定（`==`）で残す。
   - Apple Silicon では arm64 の python で作る（Intel 版だとアーキ不一致でセグフォルトする）。
     複数アーキの venv を作らない。ひとつだけ、プロジェクト内に。

2. **パスは設定ファイルで、プロジェクトルート基準で解決する**
   - スクリプトは自分の位置からプロジェクトルート（`$HERE`）を求め、
     `config/paths.conf` などに `VENV="$HERE/venv"`、`DATA="$HERE/data"` のように
     ルート相対で書く。絶対パスやホーム直書きをスクリプトに埋めない。

3. **生成物・中間ファイルもプロジェクト内**
   - データ、キャッシュ、一時ファイル、モデル出力などは `<project>/data` や
     `<project>/.cache` などプロジェクト内に置く。掃除もプロジェクト内で完結させる。

4. **既定値もプロジェクト内を指す**
   - スクリプトの「未設定時のデフォルト」も `$HERE/...` にする。
     うっかりホームを掴む事故（例: 古い `~/venvs/podcast` を掴んでセグフォルト）を防ぐ。

5. **環境の健全性チェックを入れる**
   - venv が無ければ「プロジェクト内に作れ」と案内して止める。
   - アーキ不一致など、黙って落ちると原因が分かりにくいものは、実行前に照合してエラーで止める。

## なぜ
- 作業ディレクトリを消せば環境ごと消える＝後片付けと再現が確実。
- 別マシンや別パスへ移しても、ルート相対なのでそのまま動く。
- ホーム共有の壊れた環境を誤って掴む事故が起きない。
- 複数プロジェクトが互いの環境を汚さない。

## このプロジェクトでの適用状況
- `config/paths.conf`: `VENV="$HERE/venv"`（プロジェクト内）
- `scripts/transcribe.sh`: 既定 venv = `$HERE/venv`。無ければ作成コマンドを案内。
  arm64 照合あり。
- venv: `<project>/venv`（arm64 python3.11 / whisperx・torch2.5.1）。`requirements.txt` に固定版を同梱。
  再現は `python3.11 -m venv venv && venv/bin/pip install -r requirements.txt`。
- データ: `config/paths.conf` の `PODCAST_ROOT`（既定 `$HERE/data`）。
