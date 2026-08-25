#!/usr/bin/env python3
"""data/<ID>/ を新しい配置へ移す（D-002 改定・2026-08-05）。

  python scripts/reorganize_id.py <ID> [--dry-run]

直下にはオーナーが入れたものだけを残し、判断データは edit/、機械生成物は generated/ へ。
どのファイルがどこへ行くかは scripts/idpaths.py が唯一の定義。
"""

import os
import sys
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import idpaths  # noqa: E402

# 直下に残すもの（オーナーが入れた入力・記録）
KEEP_TOP_SUFFIX = (".m4a", ".mp3", ".wav", ".mp4", ".mov")
KEEP_TOP_NAMES = {"編集メモ.md"}
# Notta 由来（元入力）。生成物の PDF と紛れないよう名前で判定する
KEEP_TOP_CONTAINS = ("-transcript", "-要約")

# 作業用の一時ファイル。消してよい（必要なら作り直される）
TEMP_NAMES = {".DS_Store", ".align_audio.wav"}
TEMP_TO_GEN = {".vad_audio.wav", ".source_path"}


def classify(name):
    if name in TEMP_NAMES:
        return "delete"
    if name in TEMP_TO_GEN:
        return idpaths.GEN_DIR
    if name in KEEP_TOP_NAMES:
        return ""
    if name.lower().endswith(KEEP_TOP_SUFFIX) and not name.startswith("preview_audio"):
        return ""
    if any(k in name for k in KEEP_TOP_CONTAINS) and "_校正用" not in name:
        return ""
    return idpaths.subdir_for(name)


def main():
    if len(sys.argv) < 2:
        print("usage: reorganize_id.py <ID> [--dry-run]")
        return 1
    idv = sys.argv[1]
    dry = "--dry-run" in sys.argv
    base = os.path.join(HERE, "data", idv)
    if not os.path.isdir(base):
        print(f"[整理] data/{idv} がありません")
        return 1

    moves, dels, stays = [], [], []
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if os.path.isdir(path):
            continue
        c = classify(name)
        if c == "delete":
            dels.append(name)
        elif c:
            moves.append((name, c))
        else:
            stays.append(name)

    # 中間生成物/ の中身は generated/ に寄せる（フォルダが2つあると迷う）
    legacy = os.path.join(base, "中間生成物")
    legacy_moves = []
    if os.path.isdir(legacy):
        for name in sorted(os.listdir(legacy)):
            legacy_moves.append(name)

    print(f"[整理] data/{idv}")
    print(f"\n  直下に残す（{len(stays)}）")
    for n in stays:
        print(f"    {n}")
    print(f"\n  移動（{len(moves) + len(legacy_moves)}）")
    for n, c in moves:
        print(f"    {n}  ->  {c}/")
    for n in legacy_moves:
        print(f"    中間生成物/{n}  ->  {idpaths.GEN_DIR}/")
    print(f"\n  削除（{len(dels)}）")
    for n in dels:
        print(f"    {n}")

    if dry:
        print("\n[整理] --dry-run のため何もしていません")
        return 0

    for n in dels:
        os.remove(os.path.join(base, n))
    for n, c in moves:
        d = os.path.join(base, c)
        os.makedirs(d, exist_ok=True)
        shutil.move(os.path.join(base, n), os.path.join(d, n))
    if legacy_moves:
        gd = idpaths.gen_dir(base)
        for n in legacy_moves:
            dst = os.path.join(gd, n)
            if os.path.exists(dst):
                os.remove(os.path.join(legacy, n))
            else:
                shutil.move(os.path.join(legacy, n), dst)
        if not os.listdir(legacy):
            os.rmdir(legacy)
    # preview/（PDFの画像）も generated/ へ
    pv = os.path.join(base, "preview")
    if os.path.isdir(pv):
        dst = os.path.join(base, idpaths.GEN_DIR, "preview")
        if not os.path.exists(dst):
            shutil.move(pv, dst)
    print("\n[整理] 完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
