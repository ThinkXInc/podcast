# 運用ルール（Claude Code 共通）

各サイト（web-server を持つリポジトリ）の運用を Claude Code が行うときの共通ルール。
**具体的なコマンドはユーザー原本 `docs/運用コマンド_原本.md` を参照する**（build watcher /
uWSGI log / uWSGI restart / nginx）。ここでは原本のコマンドを言い換えず、いつ・何に注意して
使うかだけを定める。全サイト共通なので、新しいサイトでもこのファイルを置いて使い回す。

## 参照
- build / uWSGI / log / nginx のコマンド → `docs/運用コマンド_原本.md`
- git 運用 → `GIT_GENERAL.md` / 配置規約 → `CLAUDE_GENERAL.md`

## 前提（構成）
- 1サイト = 1リポジトリ。各サイトは独立してビルド・uWSGI 再起動・ログ確認する
  （uWSGI サービスは `uwsgi_<site>.service` とサイト単位）。
- nginx 基盤は別リポジトリ **nginx-root** に集約。サイトの server 設定は各リポジトリ内
  `web-server/nginx/conf.d/`（podcast は `web/nginx/conf.d/`）に置き、nginx-root が include する。
- **各サイトは nginx-root 無しでも単独で nginx ホストできる**こと（root に依存しない。root は束ねるだけ）。

## Claude Code が守ること
1. **sudo を伴う操作は事前確認**
   uWSGI/nginx の restart・reload、`journalctl`、`systemctl` など sudo が要る操作は、
   実行前にユーザーへ一言確認してから。`.claude/settings.json` で sudo は deny のため、
   実際の実行はユーザー側になることも多い。その場合はコマンドを提示して依頼する。
2. **再起動より先に文法チェック**
   nginx 設定を変えたら、reload/restart の前に必ず `nginx -t`（原本参照）で検証する。
   壊れた設定で reload しない。
3. **サイト単位で完結させる**
   あるサイトの作業は、そのサイトのリポジトリ内で完結させる（他サイトや nginx-root を
   巻き込まない）。サイトを増やす時だけ nginx-root の include に1行足す（それはユーザー判断）。
4. **ログは追跡目的で使う**
   問題調査時は原本の `journalctl -fu uwsgi_<site>.service` でログを見る。
   ビルド反映が見えない時は build watcher（views の watchappviews.sh）が動いているか確認。
5. **サービス名・パスはサイト固有値を使う**
   原本の `<site>` を、このプロジェクトの実際の値（下記）に読み替える。
6. **再起動方式はサイトによる**
   uWSGI/nginx の再起動は、`systemctl` 直接と、サイトが持つ `etc/restart.sh` / `nginx/restart.sh`
   方式の2通りがある（原本参照）。そのサイトにスクリプトがあればそれを使い、無ければ systemctl。
7. **共通運用と固有運用を混ぜない**
   このドキュメント群（OPS_GENERAL + 運用コマンド原本）は**全サイト共通の運用**
   （build / uWSGI / log / nginx）だけを扱う。サイト独自機能（DB・Celery・VectorDB・課金等）の
   運用は、そのサイトのリポジトリ内の固有マニュアルに置く。ここには持ち込まない。

## 対話セッションの起動（Claude Code を screen + Remote Control で常駐）
「アプリからいつでも同じセッションに話しかけたい」場合の起動方法。各プロジェクトのトップに
`rc.sh` を置いてある。これを実行すると、screen 内で `claude --remote-control` が起動し、
手元ターミナルでも、Claude app / claude.ai/code からも同じセッションに指示できる。
```
cd /src/<site> && . ./rc.sh
```
- screen セッション名は `cc_<プロジェクト名>`。既にあれば再アタッチ（二重起動しない）。
- Remote Control のセッション表示名はプロジェクト名。Claude app の Code 一覧に出る。
- デタッチ: Ctrl+A → D。再アタッチ: `screen -r cc_<プロジェクト名>`。
- 制約: **サーバー再起動で screen セッションは消える**（再度 rc.sh を実行）。約10分の
  ネットワーク断や claude プロセス終了でも Remote Control は切れる。
- コンテキストが溜まったら一度終了して開き直す（プロジェクト文脈は CLAUDE.md 等が保持）。
- 権限承認は残る（Remote Control でも各操作の承認が必要。離席前は指示を厚めに。
  settings.json の allow を活用して承認を減らす）。

## このプロジェクトの固有値（podcast）
- サイト名 `<site>` = **podcast**
- リポジトリ配置: `/src/podcast`
- uWSGI サービス: `uwsgi_podcast.service`
- uWSGI socket: `/tmp/uwsgi_podcast_web.sock`（web/config/uwsgi.ini と一致）
- サイトの nginx 設定: `/src/podcast/web/nginx/conf.d/podcast_web.conf`（nginx-root が include）
- 確認用サイトのポート: 8010（LB がここへ）
- フロントのビルド監視: `web/` 側にビルド対象がある場合に使う（less は使わないので、
  ビルドが不要なら watcher も不要。CSS は直書き）。
