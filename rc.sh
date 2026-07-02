#!/usr/bin/env bash
# rc.sh — このプロジェクトの Claude Code を screen 内で起動し、Remote Control を有効化する。
# 手元ターミナルでも操作でき、同時に Claude app / claude.ai/code からも同じセッションに話せる。
#
# 使い方: プロジェクトのトップで  . ./rc.sh   または  bash rc.sh
#   - 既に同名 screen セッションがあれば、それに再アタッチ（二重起動しない）
#   - 無ければ screen を作って claude --remote-control を起動
#
# 前提: screen と claude(v2.1.51+) が入っていること。Max/Pro プランでログイン済み。
# 注意: サーバー再起動で screen セッションは消える。その時は再度これを実行する。

# プロジェクト名をディレクトリ名から決める（セッション名・表示名に使う）
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
NAME="$(basename "$HERE")"          # 例: podcast
SCREEN_NAME="cc_${NAME}"            # screen セッション名（例: cc_podcast）

# 既存セッションがあれば再アタッチ
if screen -ls 2>/dev/null | grep -q "\.${SCREEN_NAME}[[:space:]]"; then
  echo "[rc] 既存セッション ${SCREEN_NAME} に再アタッチします"
  exec screen -r "${SCREEN_NAME}"
fi

# 無ければ新規作成して claude を Remote Control 付きで起動
echo "[rc] screen ${SCREEN_NAME} を作成し、claude --remote-control を起動します"
echo "[rc] デタッチは Ctrl+A → D / 後で戻るには: screen -r ${SCREEN_NAME}"
cd "$HERE" || exit 1
exec screen -S "${SCREEN_NAME}" claude --remote-control --name "${NAME}"
