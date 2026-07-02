# Git 運用ルール（Claude Code 共通）

これは Claude Code が守る運用方針だけを書く。**具体的なコマンド手順はユーザー原本
`docs/git_手順_原本.md` を参照する**（初期セットアップ・SSH鍵・keychain・alias・LFS・submodule）。
ここでは原本のコマンドを言い換えず、いつ・何に注意して使うかだけを定める。

## 参照
- セットアップ / SSH / keychain / alias / LFS / submodule のコマンド → `docs/git_手順_原本.md`
- ファイル配置・venv・requirements の規約 → `CLAUDE_GENERAL.md`

## ブランチ運用
- `master` = 本番（メインブランチ）。`develop` = 開発用。
- ただし**ステージング環境が無いプロジェクトでは、原則 `master` だけをほぼ使う**
  （今回の podcast もこれに該当）。開発用ブランチを分けても回す先が無いので、
  小さく直して master に直接コミットしていく運用でよい。
- ステージング環境があるプロジェクトでは、develop で開発 → ステージングで確認 → master へ、
  という流れにする。
- 補足: `git init` 直後のデフォルト枝名が `main` のことがある。`master` 運用なら
  `git branch -M master` で名前を合わせてから push する。初回は上流を張る:
  `git push -u origin master`（以降は `git push` だけでよい）。

## push モード（プロジェクトごとに切り替える）
プロジェクトによって、master へ直接 push する運用と、PR 経由にする運用を切り替える。
**どちらのモードかは各プロジェクトの「このプロジェクトの状態」に明記する。** 迷ったら直 push。

### A. 直 push モード（小規模・一人・ステージング無し向け。今回の podcast）
- 変更 → `add` → `commit` → `git push`（master へ直接）まで自動でよい。
- settings.json: allow に `Bash(git push)` `Bash(git push origin:*)`。
  deny に force push / reset --hard / ブランチ削除（破壊的操作のみ禁止）。

### B. PR モード（レビューを挟む・複数人・本番が重い向け）
- master へ直接 push しない。作業ブランチを切って push し、Pull Request を出す:
  ```
  git switch -c <prefix>/<topic>      # 例: claude/fix-render
  ... commit ...
  git push -u origin HEAD
  gh pr create --base master --fill   # GitHub CLI で PR 作成
  ```
- master へのマージは人がレビューして行う（Claude は勝手にマージしない）。
- settings.json: deny に master/main への直 push
  （`Bash(git push origin master:*)` `Bash(git push origin main:*)` など）。
  allow に作業ブランチ push（`Bash(git push -u origin:*)` `Bash(git push origin HEAD:*)`）と
  `Bash(gh pr create:*)`。
- ブランチ接頭辞は Claude Code の Pull requests 設定の Branch prefix（既定 `claude`）に合わせる。

### 切り替え方（まとめ）
- 直 push にする → settings.json の allow に通常 push を入れ、master 直 push の deny を外す。
- PR にする → settings.json の deny に master/main 直 push を入れ、allow をブランチ push＋
  `gh pr create` に替える。GIT_GENERAL のルール本文は共通のまま、settings.json とプロジェクト
  状態欄でモードを表す。

## Claude Code が守ること
0. **commit / push は許可されていれば自動で行う（push 先はモードに従う）**
   ユーザーが許可している環境では、変更 → `git add` → `git commit` まで自分で実行してよい
   （毎回の許可待ちをしない）。push 先は「push モード」に従う:
   直 push モードなら `git push` で master へ、PR モードなら作業ブランチへ push して
   `gh pr create` で PR を出す（master へ直接 push しない）。
   ただし次の破壊的操作は自動化の対象外で、ルール1のとおり必ず事前確認する:
   `push --force`、`reset --hard`、ブランチ削除、履歴書き換え。
   コミットメッセージは「何を・なぜ」を簡潔に。
   push が環境の権限で弾かれる場合は、ユーザーに `! git push`（PR モードなら `! gh pr create`）の
   実行を依頼する。Claude Code は settings.json を書き換えない（モード変更はユーザーが行う）。

1. **破壊的操作は必ず事前確認**
   `push --force` / `reset --hard` / ブランチ削除 / 履歴書き換え / `git rm -rf` /
   submodule の削除は、実行前にユーザーへ確認を取る。原本にある削除手順
   （submodule の remove 等）も、勝手に走らせず確認してから。

2. **秘密情報をコミットしない**
   SSH 秘密鍵（`id_*`）、`.env`、トークン、パスワードは追跡しない。`.gitignore` で除外。
   原本の SSH 手順で作る鍵はローカルに置くだけで、リポジトリには入れない。

3. **巨大バイナリは LFS**
   数十MB超のバイナリ（モデル `.pth`/`.ckpt`、音源 wav/m4a、動画 mp4、大きい画像）を
   普通にコミットしない。原本「Git LFS」に従い **track と add の両方**を行い、
   `git lfs ls-files` で管理下に入ったか確認する。ソース・テキスト・設定は通常の git。
   巨大ファイルを見つけたら「LFS にしますか」と確認してから track する。

4. **コミットは小さく意味のある単位で**
   1コミット=1つの論理変更。メッセージは「何を・なぜ」が分かる簡潔な文。

5. **生成物・環境は追跡しない**
   venv/ data/ 出力メディア等は `.gitignore`。依存の再現は `requirements.txt`
   （CLAUDE_GENERAL.md）で行うので venv 本体はコミットしない。

6. **submodule を扱うとき**
   移動・削除は原本「submodule」の手順に従う（`git mv` → `.gitmodules` と `.git/config`
   を直す → `git submodule sync`）。`.git/config` は自動で書き変わらない点に注意。
   これらは確認を取ってから実行する。

## このプロジェクトの状態
- `git init` 済み。user.name=kazukiotsuka / user.email=otsuka.kazuki@googlemail.com。
- リモート: `git@github.com:ThinkXInc/podcast.git`。`master` を push 済み。
- **ステージング環境なし → `master` だけで運用**（develop は作っていない）。
- **push モード = A（直 push）**。master へ直接 push する。PR は使わない。
- `.gitignore`: venv/ .venv-openai/ data/ 生成メディア/ 鍵(.env, id_*, *.pem) を除外。
- `.claude/settings.json`: git の `add`/`commit`/`push`/`push origin` は allow（自動）、
  `push --force`/`reset --hard`/ブランチ削除は deny（自動化しない）。
  push が環境のサンドボックスで弾かれる場合はユーザーに `! git push` を依頼する。
