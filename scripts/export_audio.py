#!/usr/bin/env python3
"""確定セグメントを音声で書き出す（確認サイトの「この編集で書き出す」ボタン用）。

segments.json のセグメントから drops を除いた keep 区間を繋ぎ、
data/<ID>/contents/{ID}_{INDEX}_{TITLE}.m4a に書き出す。

フォーマットは AAC 256kbps（.m4a）。Podcast 配信の標準で、同ビットレートなら
mp3 より高音質、この元音源（モノラル収録）なら聴感上は無劣化と同等。
完全ロスレス（WAV/FLAC）は40分で数百MBになるうえ配信側で再エンコードされるので使わない。
エンコーダは macOS の AudioToolbox（aac_at）を優先し、無ければ ffmpeg 内蔵 aac。
動画・字幕が要るときは従来どおり render.py を使う。

usage: python scripts/export_audio.py <ID> [--index N]
       （--index 省略時は全セグメント。環境変数 RENDER_ONLY="6" でも絞れる）
"""
import os
import sys
import json
import pathlib
import argparse
import subprocess

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))
import idpaths
from render import find_media, keep_ranges, safe_name, load_conf, P


def aac_encoder():
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True).stdout
        if " aac_at " in out:
            return "aac_at"
    except OSError:
        pass
    return "aac"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--index", type=int, default=None)
    args = ap.parse_args()
    ID = args.id

    paths = load_conf("config/paths.conf")
    root = paths.get("PODCAST_ROOT") or str(HERE / "data")
    outdir = pathlib.Path(root) / ID

    seg_path = P(outdir, "segments.json")
    if not seg_path.exists():
        sys.exit(f"[audio] {seg_path} が無い。先にセグメントを確定してください。")
    segs = json.loads(seg_path.read_text(encoding="utf-8")).get("segments", [])

    only = args.index
    if only is None and os.environ.get("RENDER_ONLY", "").strip().isdigit():
        only = int(os.environ["RENDER_ONLY"])
    if only is not None:
        segs = [s for s in segs if s.get("index") == only]
    if not segs:
        sys.exit("[audio] 対象セグメントがありません。")

    media = find_media(outdir, ID, None)
    if not media or not media.exists():
        sys.exit(f"[audio] メディアが見つかりません（data/{ID}/）。")
    # 元の m4a が ALAC で途中に壊れたフレームがある事例（D-021 周辺）があるので、
    # 同名の wav があればそちらを優先する
    wav = media.with_suffix(".wav")
    if wav.exists():
        media = wav

    contents = outdir / "contents"
    contents.mkdir(exist_ok=True)
    enc = aac_encoder()

    for seg in segs:
        idx = seg.get("index")
        start = float(seg["start_sec"]); end = float(seg["end_sec"])
        drops = [tuple(map(float, d)) for d in seg.get("drops", [])]
        keeps = keep_ranges(start, end, drops)
        if not keeps:
            print(f"[audio] index {idx}: 有効区間なしスキップ"); continue
        out = contents / f"{ID}_{idx}_{safe_name(seg.get('title'))}.m4a"

        chains, labels = [], []
        for i, (a, b) in enumerate(keeps):
            chains.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[s{i}]")
            labels.append(f"[s{i}]")
        fc = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(keeps)}:v=0:a=1[out]"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(media), "-filter_complex", fc, "-map", "[out]",
               "-c:a", enc, "-b:a", "256k", str(out)]
        subprocess.run(cmd, check=True)
        net = sum(b - a for a, b in keeps)
        print(f"[audio] index {idx}: {len(keeps)}区間 / 正味 {int(net//60)}分{int(net%60):02d}秒"
              f" / AAC 256kbps ({enc}) -> {out}")

    print("[audio] 完了")


if __name__ == "__main__":
    main()
