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
  （今回の podcast-pipeline もこれに該当）。開発用ブランチを分けても回す先が無いので、
  小さく直して master に直接コミットしていく運用でよい。
- ステージング環境があるプロジェクトでは、develop で開発 → ステージングで確認 → master へ、
  という流れにする。
- どちらの運用かはプロジェクトの「このプロジェクトの状態」に明記する。
- 補足: `git init` 直後のデフォルト枝名が `main` のことがある。`master` 運用なら
  `git branch -M master` で名前を合わせてから push する。初回は上流を張る:
  `git push -u origin master`（以降は `git push` だけでよい）。

## Claude Code が守ること
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
- リモート: `git@github.com:ThinkXInc/podcast-pipeline.git`。`master` を push 済み。
- **ステージング環境なし → `master` だけで運用**（develop は作っていない）。
- `.gitignore`: venv/ .venv-openai/ data/ 生成メディア/ 鍵(.env, id_*, *.pem) を除外。
