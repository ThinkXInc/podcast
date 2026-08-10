#!/usr/bin/env python3
"""編集データ（data/<ID>/edit/）を backup/edit_<日時>/ へ丸ごと退避する。

編集データに触るあらゆる変更（手動修正・統合スクリプト・移行）の前に必ず実行する
（GUIDELINES 25・2026-08-08）。

usage: python scripts/backup_edit.py <ID>
"""
import sys
import shutil
import pathlib
import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main(idv):
    base = ROOT / "data" / idv
    edit = base / "edit"
    if not edit.is_dir():
        sys.exit(f"[backup_edit] {edit} がありません")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = base / "backup" / f"edit_{stamp}"
    dst.parent.mkdir(exist_ok=True)
    shutil.copytree(edit, dst)
    n = sum(1 for _ in dst.rglob("*") if _.is_file())
    print(f"[backup_edit] {edit} -> {dst}（{n}ファイル）")


def main_all():
    data = ROOT / "data"
    for edit in sorted(data.glob("*/edit")):
        main(edit.parent.name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python scripts/backup_edit.py <ID> | --all")
    if sys.argv[1] == "--all":
        main_all()
    else:
        main(sys.argv[1])
