#!/usr/bin/env python3
"""編集の操作履歴（edit/save_inbox.jsonl）から任意時点の状態を確認・復元する。

サイトは操作のたびに全カット状態を保存し、受信内容は成否に関わらず save_inbox.jsonl に
記録される（2026-08-08・オーナー指示「操作するたびに操作履歴を完全に書き込め」）。
このスクリプトはその履歴を一覧し、指定した時点の drops を segments.json に書き戻す。
書き戻す前に backup_edit.py 相当の退避を自動で行う。

usage:
  python scripts/restore_edit.py <ID> --list [--sid SID]        履歴を一覧
  python scripts/restore_edit.py <ID> --restore <行番号>         その時点の状態に復元
"""
import sys
import json
import shutil
import pathlib
import argparse
import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_inbox(base):
    p = base / "edit" / "save_inbox.jsonl"
    if not p.exists():
        sys.exit(f"[restore] {p} がまだありません（履歴はこれから貯まります）")
    out = []
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines()):
        try:
            out.append((i, json.loads(ln)))
        except json.JSONDecodeError:
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--sid", default=None)
    ap.add_argument("--restore", type=int, default=None, help="一覧の行番号")
    args = ap.parse_args()
    base = ROOT / "data" / args.id
    recs = load_inbox(base)

    if args.restore is None:
        for i, r in recs:
            pl = r.get("payload", {})
            if args.sid and pl.get("sid") != args.sid:
                continue
            drops = pl.get("drops") or []
            net = sum(b - a for a, b in drops)
            print(f"[{i}] {r.get('at')} sid={pl.get('sid','')[:6]} idx={pl.get('index')} "
                  f"op={pl.get('op','')} カット{len(drops)}箇所(計{int(net)}秒)")
        return

    rec = dict(recs)[args.restore]
    pl = rec["payload"]
    sid = pl.get("sid")
    segp = base / "edit" / "segments.json"
    # 復元前に必ず退避（GUIDELINES 25）
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = base / "backup" / f"edit_{stamp}_restore前"
    dst.parent.mkdir(exist_ok=True)
    shutil.copytree(base / "edit", dst)
    seg = json.load(open(segp))
    hit = False
    for sg in seg["segments"]:
        if (sid and sg.get("sid") == sid) or (not sid and sg.get("index") == pl.get("index")):
            sg["drops"] = pl.get("drops") or []
            hit = True
            print(f"[restore] index{sg['index']} ({sg.get('title','')[:20]}) を "
                  f"{rec.get('at')} 時点のカット{len(sg['drops'])}箇所に復元")
    if not hit:
        sys.exit("[restore] 対象セグメントが見つかりません")
    json.dump(seg, open(segp, "w"), ensure_ascii=False, indent=1)
    print(f"[restore] 退避: {dst}")


if __name__ == "__main__":
    main()
