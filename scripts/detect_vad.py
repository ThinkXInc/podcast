#!/usr/bin/env python3
# 音源から「発話区間」を検出して data/<ID>/vad.json に出す。
#
#   python scripts/detect_vad.py <ID> [--model auto|seg3|whisperx|silero]
#
# 用途（D-019）: タイムライン編集UIの表示専用。
#   タイムライン上で文字が無い箇所を、無音なのか「喋っているのに文字起こしが落とした」のかを
#   見分けるために使う。文字の有無だけでは区別できないので、発話の有無を音から直接測る。
#   docs/無音詰め方針.md の大原則3（音響解析を使わない）は「詰めるかどうかの判断」に対する
#   規定であり、ここは表示のための計測なので別扱いとする（オーナー判断・2026-08-05）。
#   なお同方針が禁じているのは ffmpeg silencedetect の音量しきい値であり、
#   本スクリプトが使うのは学習済みの発話検出モデルで、禁止理由である
#   「ノイズフロアが高いと誤判定する」という失敗モードを解決する側の手段である。
#
# モデルは精度順に試す。処理時間は問わない（リアルタイム性が不要なため）。
#   1) pyannote/segmentation-3.0  … 2023年版。重なり発話も扱う。最も精度が高い。
#                                    HF の gated モデルなので、
#                                    https://hf.co/pyannote/segmentation-3.0 で
#                                    利用条件に同意しておく必要がある。
#   2) whisperx 同梱 (S3)         … pyannote segmentation の2022年版。HF認証不要。
#   3) silero-vad                 … 軽量。上2つが使えないときの最後の手段。

import os
import sys
import json
import argparse
import warnings

warnings.filterwarnings("ignore")
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import idpaths  # data/<ID>/ のファイル配置は idpaths が唯一の定義（D-002 改定）
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 発話区間の後処理。VAD の生出力は細切れになるので、実用的な粒度に均す。
MERGE_GAP = 0.20        # これ未満の隙間は同じ発話としてつなぐ（秒）
MIN_SPEECH = 0.15       # これ未満の発話は誤検出として落とす（秒）
MIN_SILENCE = 0.30      # これ未満の無音は無音として扱わない（秒）


def find_media(base):
    for ext in (".m4a", ".mp3", ".wav", ".mp4", ".mov"):
        for n in sorted(os.listdir(base)):
            if n.lower().endswith(ext) and "_orig" not in n and "_trimmed" not in n:
                return os.path.join(base, n)
    return None


def to_wav(media, dst):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", media,
                    "-ac", "1", "-ar", "16000", dst], check=True)
    return dst


def run_pyannote(wav, which):
    """pyannote の segmentation モデルで発話区間を得る。which = 'seg3' | 'whisperx'"""
    import torch
    from pyannote.audio import Model
    from pyannote.audio.pipelines import VoiceActivityDetection

    if which == "seg3":
        model = Model.from_pretrained("pyannote/segmentation-3.0")
        if model is None:
            raise RuntimeError(
                "pyannote/segmentation-3.0 を取得できませんでした。"
                " https://hf.co/pyannote/segmentation-3.0 で利用条件に同意してください")
        # segmentation-3.0 は powerset 出力なので専用のハイパーパラメータを使う
        params = {"min_duration_on": MIN_SPEECH, "min_duration_off": MIN_SILENCE}
    else:
        import whisperx.vad as V
        model = V.load_vad_model(torch.device("cpu"))
        params = {"onset": 0.500, "offset": 0.363,
                  "min_duration_on": MIN_SPEECH, "min_duration_off": MIN_SILENCE}

    pipe = VoiceActivityDetection(segmentation=model)
    pipe.instantiate(params)
    ann = pipe(wav)
    return [(float(s.start), float(s.end)) for s in ann.get_timeline().support()]


def run_silero(wav):
    import torch
    m, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
    get_ts, _, read_audio, *_ = utils
    audio = read_audio(wav, sampling_rate=16000)
    ts = get_ts(audio, m, sampling_rate=16000,
                min_speech_duration_ms=int(MIN_SPEECH * 1000),
                min_silence_duration_ms=int(MIN_SILENCE * 1000))
    return [(t["start"] / 16000.0, t["end"] / 16000.0) for t in ts]


def merge(spans):
    """近接する発話をつなぎ、短すぎるものを落とす。"""
    spans = sorted(spans)
    out = []
    for s, e in spans:
        if out and s - out[-1][1] <= MERGE_GAP:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in out if e - s >= MIN_SPEECH]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--model", default="auto", choices=["auto", "seg3", "whisperx", "silero"])
    args = ap.parse_args()

    base = os.path.join(HERE, "data", args.id)
    if not os.path.isdir(base):
        print(f"[vad] data/{args.id} がありません")
        return 1
    media = find_media(base)
    if not media:
        print(f"[vad] data/{args.id} に音源が見つかりません")
        return 1

    wav = idpaths.save(base, ".vad_audio.wav")
    if not os.path.exists(wav):
        print("[vad] 16k mono wav を抽出中…")
        to_wav(media, wav)

    order = ["seg3", "whisperx", "silero"] if args.model == "auto" else [args.model]
    spans, used, errors = None, None, []
    for which in order:
        try:
            print(f"[vad] {which} を試行中…")
            spans = run_silero(wav) if which == "silero" else run_pyannote(wav, which)
            used = which
            break
        except Exception as e:
            errors.append(f"{which}: {type(e).__name__} {str(e)[:120]}")
            print(f"[vad]   使えません: {errors[-1]}")
    if spans is None:
        print("[vad] どのモデルも使えませんでした:")
        for e in errors:
            print("   -", e)
        return 1

    spans = merge(spans)
    import subprocess
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", media],
                               capture_output=True, text=True).stdout.strip())
    speech = sum(e - s for s, e in spans)

    # 無音区間＝発話区間の補集合のうち、MIN_SILENCE 以上のもの
    sil, t = [], 0.0
    for s, e in spans:
        if s - t >= MIN_SILENCE:
            sil.append((round(t, 3), round(s, 3)))
        t = max(t, e)
    if dur - t >= MIN_SILENCE:
        sil.append((round(t, 3), round(dur, 3)))

    out = {"model": used, "media": os.path.basename(media), "duration": round(dur, 3),
           "params": {"merge_gap": MERGE_GAP, "min_speech": MIN_SPEECH,
                      "min_silence": MIN_SILENCE},
           "speech": [list(x) for x in spans], "silence": [list(x) for x in sil]}
    dst = idpaths.save(base, "vad.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[vad] モデル={used} / 全長{dur:.0f}s")
    print(f"[vad] 発話 {len(spans)} 区間 / 計 {speech:.0f}s ({100*speech/dur:.1f}%)")
    print(f"[vad] 無音 {len(sil)} 区間 / 計 {dur-speech:.0f}s ({100*(dur-speech)/dur:.1f}%)")
    longest = sorted(sil, key=lambda x: -(x[1] - x[0]))[:5]
    if longest:
        print("[vad] 長い無音 上位5件: " +
              " / ".join(f"{a:.0f}-{b:.0f}s({b-a:.1f}s)" for a, b in longest))
    print(f"[vad] -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
