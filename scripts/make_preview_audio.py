#!/usr/bin/env python3
# ブラウザで再生できるプレビュー用音源を作る。
#
#   python scripts/make_preview_audio.py <ID> [--force]
#   -> data/<ID>/preview_audio.m4a   （AAC 64kbps mono）
#
# なぜ要るか（2026-08-05 実測）:
#   民主主義の会2-5 の元音源は **ALAC（Apple Lossless）** の m4a で 300MB あった。
#   ALAC は Safari では鳴るが Chrome / Firefox は非対応で、
#   タイムラインの再生が audio.play() の reject で失敗していた。
#   元音源には手を触れず、再生用に AAC のコピーを別ファイルとして作る。
#   （元データを加工しない。GUIDELINES 項11「症状を隠さず正データの側を直す」の裏返しで、
#     ここは正データを保ったまま下流用の派生物を足すのが正しい）
#
# 元がすでに AAC/MP3 など広く再生できる形式なら、作らずにそのまま使う。

import os
import sys
import json
import subprocess

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import idpaths  # data/<ID>/ のファイル配置は idpaths が唯一の定義（D-002 改定）
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ブラウザが概ね再生できるコーデック。これ以外なら変換する。
BROWSER_OK = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le"}
OUT_NAME = "preview_audio.m4a"


def find_media(base):
    for ext in (".m4a", ".mp3", ".wav", ".mp4", ".mov", ".aac"):
        for n in sorted(os.listdir(base)):
            if n == OUT_NAME or "_orig" in n or "_trimmed" in n:
                continue
            if n.lower().endswith(ext):
                return os.path.join(base, n)
    return None


def probe_codec(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=codec_name", "-of", "json", path],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)["streams"][0]["codec_name"]
    except Exception:
        return None


def main():
    if len(sys.argv) < 2:
        print("usage: make_preview_audio.py <ID> [--force]")
        return 1
    idv = sys.argv[1]
    force = "--force" in sys.argv
    base = os.path.join(HERE, "data", idv)
    if not os.path.isdir(base):
        print(f"[preview音源] data/{idv} がありません")
        return 1
    media = find_media(base)
    if not media:
        print(f"[preview音源] data/{idv} に音源が見つかりません")
        return 1

    codec = probe_codec(media)
    print(f"[preview音源] 元: {os.path.basename(media)} / codec={codec}")
    if codec in BROWSER_OK:
        print("[preview音源] ブラウザで再生できる形式なので変換しません")
        return 0

    dst = idpaths.save(base, OUT_NAME)
    if os.path.exists(dst) and not force:
        print(f"[preview音源] 既にあります: {OUT_NAME}（作り直すなら --force）")
        return 0

    print(f"[preview音源] {codec} はブラウザ非対応。AAC 64kbps mono に変換します…")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", media,
                    "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k",
                    "-movflags", "+faststart", dst], check=True)
    a, b = os.path.getsize(media), os.path.getsize(dst)
    print(f"[preview音源] 完了 -> {OUT_NAME}  {a // 1048576}MB -> {b // 1048576}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
