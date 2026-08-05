#!/usr/bin/env python3
# Whisper の transcript.json に、Notta のブロックから話者ラベルを付与する。
#
#   python scripts/assign_speakers.py <ID> [--dry-run]
#
# 位置づけ（D-015）:
#   本文と単語時刻は Whisper large-v3 単体を正とする。Notta の文字は本文に使わない。
#   ただし話者の帰属（誰が喋っているか）は Notta が持っているので、それだけを借りる。
#
# なぜ時刻の重なりで足りるか:
#   Notta のブロック境界は秒単位で粗いが、話者は数秒〜数十秒単位でしか変わらない
#   遅い変化の属性なので、ミリ秒精度を必要としない。本文を音声へ強制アラインする
#   （＝単語の22.5%が壊れた。docs/findings.md 4章）必要はまったくない。
#
# 入力:
#   data/<ID>/transcript.json          Whisper の出力（transcribe.sh が作る）
#   data/<ID>/*transcript*.txt         Notta のテキスト（"HH:MM:SS Speaker N" 形式）
# 出力:
#   data/<ID>/transcript.json          segments[].speaker と words[].speaker を付けて上書き
#   （上書き前に data/<ID>/backup/transcript_nospeaker.json へ退避する）

import os
import re
import sys
import json
import glob
import shutil
import collections

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import idpaths  # data/<ID>/ のファイル配置は idpaths が唯一の定義（D-002 改定）
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\s+Speaker\s+(\d+)\s*\n(.*?)(?=\n\d{2}:\d{2}:\d{2}\s+Speaker|\Z)",
    re.S,
)


def load_notta_blocks(base):
    """Notta txt から [(start_sec, speaker_no)] を読む。Speaker 表記が最も多い txt を選ぶ。"""
    cands = sorted(glob.glob(os.path.join(base, "*transcript*.txt")))
    if not cands:
        return None, None

    def score(p):
        try:
            return len(re.findall(r"Speaker\s+\d+", open(p, encoding="utf-8").read()))
        except OSError:
            return 0

    path = max(cands, key=score)
    if score(path) == 0:
        return None, None
    text = open(path, encoding="utf-8").read()
    blocks = []
    for m in BLOCK_RE.finditer(text):
        h, mm, ss, spk, _body = m.groups()
        blocks.append((int(h) * 3600 + int(mm) * 60 + int(ss), int(spk)))
    blocks.sort()
    return os.path.basename(path), blocks


def speaker_at(blocks, t):
    """時刻 t を含む Notta ブロックの話者を返す。ブロックは開始時刻の昇順。"""
    lo, hi = 0, len(blocks) - 1
    found = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if blocks[mid][0] <= t:
            found = blocks[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return found


def main():
    if len(sys.argv) < 2:
        print("usage: assign_speakers.py <ID> [--dry-run]")
        return 1
    idv = sys.argv[1]
    dry = "--dry-run" in sys.argv
    base = os.path.join(HERE, "data", idv)
    tpath = idpaths.find(base, "transcript.json")
    if not os.path.isfile(tpath):
        print(f"[speaker] {tpath} がありません。先に transcribe.sh を実行してください。")
        return 1

    name, blocks = load_notta_blocks(base)
    if not blocks:
        print(f"[speaker] data/{idv}/ に Notta の話者付き txt が見つかりません。"
              " 話者ラベルなしのまま続行します（本文と時刻は Whisper のままで問題ありません）。")
        return 0
    print(f"[speaker] Notta 話者ブロック: {name} / {len(blocks)} ブロック"
          f" / 話者 {sorted(set(s for _, s in blocks))}")

    data = json.load(open(tpath, encoding="utf-8"))
    counts = collections.Counter()
    nword = 0
    for seg in data.get("segments", []):
        words = seg.get("words") or []
        for w in words:
            st = w.get("start")
            if st is None:
                continue
            spk = speaker_at(blocks, st)
            if spk is None:
                continue
            w["speaker"] = f"SPEAKER_{spk:02d}"
            counts[w["speaker"]] += 1
            nword += 1
        # セグメントの話者は、含まれる単語の多数決で決める（境界をまたぐ場合の揺れを抑える）
        votes = collections.Counter(w["speaker"] for w in words if w.get("speaker"))
        if votes:
            seg["speaker"] = votes.most_common(1)[0][0]
        else:
            st = seg.get("start")
            spk = speaker_at(blocks, st) if st is not None else None
            if spk is not None:
                seg["speaker"] = f"SPEAKER_{spk:02d}"

    # word_segments（時刻順の全単語リスト）も作り直す。preview / render が読む。
    ws = [w for s in data.get("segments", []) for w in (s.get("words") or [])
          if w.get("start") is not None]
    ws.sort(key=lambda w: w["start"])
    data["word_segments"] = ws
    data["language"] = data.get("language") or "ja"

    print(f"[speaker] 話者を付けた単語: {nword} / {len(ws)}")
    for spk, c in sorted(counts.items()):
        print(f"           {spk}: {c} 語 ({100 * c / max(nword, 1):.1f}%)")
    if dry:
        print("[speaker] --dry-run のため書き込みませんでした。")
        return 0

    bdir = os.path.join(base, "backup")
    os.makedirs(bdir, exist_ok=True)
    bpath = os.path.join(bdir, "transcript_nospeaker.json")
    if not os.path.exists(bpath):
        shutil.copy2(tpath, bpath)
        print(f"[speaker] 退避: backup/transcript_nospeaker.json")
    with open(idpaths.save(base, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"[speaker] 完了 -> {tpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
