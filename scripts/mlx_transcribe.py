#!/usr/bin/env python3
# mlx-whisper を Python API で呼ぶ薄いドライバ。transcribe.sh から使う。
#
#   python scripts/mlx_transcribe.py <audio> <out.json> [--model M] [--lang ja] [--prompt FILE]
#
# なぜ CLI (mlx_whisper コマンド) を使わないか【重要】:
#   mlx_whisper.transcribe() の既定は
#       temperature = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
#   で、compression_ratio_threshold(2.4) や logprob_threshold(-1.0) に引っかかった
#   ウィンドウを、温度を上げながら再デコードし直す。これが Whisper 標準の
#   「繰り返し(幻覚)ループ」対策である。
#   ところが CLI は --temperature が type=float, default=0 の単一値なので、
#   この梯子が丸ごと無効になる。実測で、6分の音源を CLI で一括処理したところ
#   「そういう意味があったわけですよね。」を70秒ぶん繰り返して内容が全消失した。
#   Python API 経由なら同じ音源で再現しない。だから CLI は使わない。
#
# 出力は openai-whisper 互換の JSON（segments[].words に word/start/end）。
# transcribe.sh のマージ側は word_segments が無ければ segments[].words を拾うので互換。

import sys
import json
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--model", default="mlx-community/whisper-large-v3-mlx")
    ap.add_argument("--lang", default="ja")
    ap.add_argument("--prompt", default=None,
                    help="語彙バイアス用の initial_prompt を書いたテキストファイル")
    args = ap.parse_args()

    initial_prompt = None
    if args.prompt:
        try:
            initial_prompt = open(args.prompt, encoding="utf-8").read().strip() or None
        except OSError:
            initial_prompt = None

    import mlx_whisper

    res = mlx_whisper.transcribe(
        args.audio,
        path_or_hf_repo=args.model,
        language=args.lang,
        task="transcribe",
        word_timestamps=True,
        initial_prompt=initial_prompt,
        # 以下はいずれも mlx_whisper の既定値だが、この4つが揃って初めて
        # 幻覚ループ対策が働くので、意図を明示するために書いておく。
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        compression_ratio_threshold=2.4,
        logprob_threshold=-1.0,
        no_speech_threshold=0.6,
        condition_on_previous_text=True,
        verbose=None,
    )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)

    nseg = len(res.get("segments", []))
    nw = sum(len(s.get("words", []) or []) for s in res.get("segments", []))
    print(f"[mlx] {nseg} セグメント / {nw} 単語 -> {args.out}"
          + (f" (prompt {len(initial_prompt)}字)" if initial_prompt else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
