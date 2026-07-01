# Git 運用ルール（Claude Code 共通）

これは Claude Code が守る運用方針だけを書く。**具体的なコマンド手順はユーザー原本
`docs/git_手順_原本.md` を参照する**（初期セットアップ・SSH鍵・keychain・alias・LFS・submodule）。
ここでは原本のコマンドを言い換えず、いつ・何に注意して使うかだけを定める。

## 参照
- セットアップ / SSH / keychain / alias / LFS / submodule のコマンド → `docs/git_手順_原本.md`
- ファイル配置・venv・requirements の規約 → `CLAUDE_GENERAL.md`

## ブランチ運用（PR ベース。master へ直接 push しない）
- `master` = 本番（メインブランチ・保護対象）。**master へは直接コミット／直接 push しない。**
- 変更は必ず**フィーチャーブランチ**を切って行い、**Pull Request 経由で master にマージ**する。
  - ブランチ名: `docs/...`（文書）`feat/...`（機能）`fix/...`（修正）`chore/...`（雑務）など用途プレフィックス。
  - 流れ: `git switch -c <branch>` → 変更 → コミット → `git push -u origin <branch>` → PR 作成 → レビュー/マージ。
  - PR は小さく。1PR=1つのまとまった変更。タイトルとサマリに「何を・なぜ」を書く。
- PR 作成は `gh pr create` を使う（未インストールなら push 後に表示される
  `https://github.com/<org>/<repo>/compare/master...<branch>?expand=1` をユーザーに案内する）。
- マージ後はブランチを削除してよい（削除は破壊的操作扱い＝確認を取る。§Claude Code が守ること 1)。
- ステージング環境があるプロジェクトでは develop を挟む（develop→ステージング確認→master）。
  無い場合は上記の「フィーチャーブランチ→PR→master」だけでよい。
- 補足: `git init` 直後の枝名が `main` のことがある。`master` 運用なら `git branch -M master`。
  初回の上流張りは `git push -u origin <branch>`（以降その枝は `git push` だけでよい）。

## Claude Code が守ること
0. **master へ直接 push しない（PR 経由）**
   Claude Code は master に直接コミット／push しない。必ずフィーチャーブランチ＋PR で出す
   （§ブランチ運用）。push できるのは自分が切った作業ブランチのみ。master への反映は
   PR マージでユーザーが行う（または明示依頼があったときだけ）。

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
- **ステージング環境なし → `master`（保護）＋フィーチャーブランチ＋PR で運用**（develop は作っていない）。
  master への直接 push はしない。変更は PR にする。
- GitHub 側で master のブランチ保護（直接 push 禁止・PR 必須）を設定推奨。
  `gh` があれば API から、無ければ GitHub の Settings→Branches で設定する。
- `.gitignore`: venv/ .venv-openai/ data/ 生成メディア/ 鍵(.env, id_*, *.pem) を除外。
