# web — 生成物チェック用サイト（podcast 内の独立コンポーネント）

生成物（音源・動画）をブラウザで確認するための軽量サイト。音源(ID)ごとに1ページ。
Claude Code は処理後に該当IDページのリンクを渡す。**data/<ID>/contents/ の成果物を
そのまま参照**し、コピーしない。詳細な作業方針は `CLAUDE.md` を参照。

## 位置づけ
- podcast 内の独立サブコンポーネント。**専用の venv / requirements.txt / CLAUDE.md** を持つ
  （本体とは別。CLAUDE_GENERAL.md「1コンポーネント1venv」例外）。色々な場所で使い回す前提。

## 本番構成
```
uWSGI 起動 → supercom2 の nginx がホスト → LB がアクセス
```
- `config/uwsgi.ini` … uWSGI 起動設定（雛形）
- `config/nginx.conf.example` … nginx 設定例（動的は uWSGI へ、音源/動画は data/ を静的配信）

## いまの状態
枠のみ。**サイトの実装（app 本体）は後で渡す**。実装が来たら:
```
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/uwsgi --ini config/uwsgi.ini
# nginx に config/nginx.conf.example を反映し、LB を nginx に向ける
```
