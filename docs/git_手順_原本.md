# Git 手順メモ（原本）

> このファイルはユーザー（チーム）の原本メモをそのまま残したもの。
> Claude Code 向けの運用ルールは `GIT_GENERAL.md` にあり、詳細手順としてこのファイルを参照する。
> 見出し（##）は参照しやすさのために付記。本文はユーザー原文のまま。

## セットアップ / SSH / keychain

```
supercom3: git
sudo apt install git
git config --global user.name "kazukiotsuka"
git config --global user.email otsuka.kazuki@googlemail.com
cd ~/.ssh
ssh-keygen -t ed25519 -C "otsuka.kazuki@googlemail.com"
Generating public/private ed25519 key pair.
Enter file in which to save the key (/root/.ssh/id_ed25519): id_github
Enter passphrase (empty for no passphrase):
Enter same passphrase again:
vim ~/.ssh/id_github.pub
(register to github)
sudo apt-get update
sudo apt-get install keychain
(keychain --eval --agents ssh id_github)
vim ~/.ssh/config
Host github.com
   IdentityFile ~/.ssh/id_github
   Port 22
ssh -T git@github.com
```

## alias

```
git config --global alias.co checkout
git config --global alias.br branch
git config --global alias.ci commit
git config --global alias.st status
git config --global alias.unstage 'reset HEAD --'
```

## lfs

```
sudo apt install git-lfs
```

----

## submodule（ディレクトリ移動・削除）

```
*下記の方法はmvで変更してからsubmoduleを設定調整する
submoduleを外してから再度add moduleした方がより確実
git mvで移動
cd /path/to/repogitory-root
git mv olddir newdir
* 手動でディレクトリ名を変えずにこのコマンドを打つ
自動でディレクトリは書き換わる
.gitmodulesも書き換わる (ただし.git/config内は書き変わらないので後でsyncが必要．)
git add .
git commit -m"olddir -> newdir"
自動的に変更されなかった.gitmodulesのパスを変更
vim .gitmodules
[submodule "www/old/scripts"]
  path = www/new/scripts
->
[submodule "www/new/scripts"]
  path = www/new/scripts
vim .git/config
[submodule "www/old/scripts"]
->
[submodule "www/new/scripts"]
% git submodule sync
Synchronizing submodule url for 'www/new/scripts'
Update the submodule to the latest commit (optional)
git submodule update --init --recursive
Remove submodule
vim .gitmodules  # remove submodule
vim .git/config  # remove submodule
git rm --cached path/to/submodule
rm -rf path/to/submodule
git commit -m"remove submodule"
```

## LFS（別途の詳細メモ・原本）

```
Git LFS
Prerequisite
cd /src/quantz/processing-server/tts4/pretrained_checkpoints
git lfs install
Push new file
*add と track両方必要
cd /src/quantz/processing-server/tts4/pretrained_checkpoints
git lfs track JP_moraspeech_182000_v2.pth
git add -f JP_moraspeech_182000_v2.pth
Pull
cd /src/quantz/processing-server/tts4/pretrained_checkpoints
git lfs pull
認識されているファイルの確認
*なければadd か trackがない?
cd /src/quantz/processing-server/tts4/pretrained_checkpoints
git lfs ls-files
```
