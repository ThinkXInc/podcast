# Claude Code への作業指示書（web = 生成物チェック用サイト）

これは podcast の中にある**独立したサブコンポーネント**。
生成物（音源・動画）をブラウザで確認するための軽量サイト。音源(ID)ごとに1ページ。
Claude Code は処理完了後にこのサイトの**該当IDページのリンクを渡す**。

## 位置づけ（重要）
- このサイトは色々なプロジェクトで使い回す汎用ツール。だから **web/ 内で自己完結**させる。
- **venv・requirements.txt・CLAUDE.md はこの web/ 配下の専用のものを使う**
  （podcast 本体の venv とは別。CLAUDE_GENERAL.md の「1コンポーネント1venv」例外に該当）。
- 本体のスクリプト（transcribe/suggest/render 等）とは依存を混ぜない。

## 設計方針（シンプル最優先）
- **既存の `data/<ID>/contents/` の成果物をそのままサイトのリソースにする**。コピー・複製しない。
  data を唯一の正とし、サイトはそれを参照して並べるだけ。
- ページの中身は「音源・動画がラベル付きで並んでいるだけ」。凝った機能は足さない。
- **見た目は会社共通の `general/base.html` を継承する**（templates/page.html がその型）。
  ただし **less は使わない**。スタイルは不要か、必要なら `views/css/` に直書きの CSS、
  または最小限の style で済ませる（less のビルド工程は持たない）。
- 複雑にするとメンテが大変なので、最小構成を保つ。DB やビルド工程は持たない。

## nginx（nginx-root と連携。ただし単独でもホスト可）
- このサイトの server 設定は `nginx/conf.d/podcast_web.conf`。**本番は nginx-root がこれを
  絶対パスで include** する（nginx 基盤は別リポジトリ nginx-root）。
- **nginx-root 無しでも単独ホストできる**: `nginx/nginx.conf`（＋同梱の mime.types / uwsgi_params）
  があるので `sudo nginx -c /src/podcast/web/nginx/nginx.conf` で単体起動できる。root に依存しない。
- 専用ポート 8010・専用 socket `/tmp/uwsgi_podcast_web.sock`（他サイトと衝突しない値）。
- 音源・動画は `/media/` として data/<ID>/contents/ を nginx が直接配信（アプリを通さない）。
- 運用コマンド（uWSGI 再起動・ログ・nginx 検証）は `OPS_GENERAL.md` と
  `docs/運用コマンド_原本.md` に従う。nginx は変更後に `nginx -t` してから reload。

## いまの状態
- **枠だけ**。サイトの実装（app 本体）はユーザーが後で渡す。
- ここにあるのは: ディレクトリ構成 / 専用 venv 用の requirements.txt(空に近い) /
  uWSGI・nginx の雛形 / この指示書。
- 実装が来たら: `web/venv` を作り `web/requirements.txt` で再現、uwsgi.ini の module を実装に合わせ、
  nginx 経由で表示確認、までを行う。

## やること（実装が来てから）
- `python3 -m venv web/venv && web/venv/bin/pip install -r web/requirements.txt`
- data のパスは設定で渡す（ハードコードしない）。`config/site.conf` 等に置く。
- IDページの URL 規則を決め、Claude Code が処理後にそのURLを提示する。
- 音源・動画は data/<ID>/contents/ を参照（再エンコード・コピーをしない）。
