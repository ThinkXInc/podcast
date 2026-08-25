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
    ap.add_argument("--sid", default=None)
    ap.add_argument("--spec", default=None,
                    help="ブラウザの表示状態(JSON)で書き出す。segments.json は参照しない")
    ap.add_argument("--denoise", action="store_true",
                    help="最終版: MossFormer2_SE_48K でノイズ除去してからエンコード（数分余計にかかる）")
    args = ap.parse_args()
    ID = args.id

    paths = load_conf("config/paths.conf")
    root = paths.get("PODCAST_ROOT") or str(HERE / "data")
    outdir = pathlib.Path(root) / ID

    denoise = args.denoise
    if args.spec:
        # ブラウザが表示していた状態そのものを書き出す（見ているもの＝書き出されるもの）
        spec = json.loads(pathlib.Path(args.spec).read_text(encoding="utf-8"))
        denoise = denoise or bool(spec.get("denoise"))
        title = ""
        seg_path = P(outdir, "segments.json")
        if seg_path.exists():
            for s in json.loads(seg_path.read_text(encoding="utf-8")).get("segments", []):
                if s.get("sid") == spec.get("sid"):
                    title = s.get("title") or ""
        segs = [{"index": spec.get("index"), "title": title or f"seg{spec.get('index')}",
                 "start_sec": spec["segStart"], "end_sec": spec["segEnd"],
                 "drops": spec.get("drops") or []}]
    else:
        seg_path = P(outdir, "segments.json")
        if not seg_path.exists():
            sys.exit(f"[audio] {seg_path} が無い。先にセグメントを確定してください。")
        segs = json.loads(seg_path.read_text(encoding="utf-8")).get("segments", [])
        only = args.index
        if only is None and os.environ.get("RENDER_ONLY", "").strip().isdigit():
            only = int(os.environ["RENDER_ONLY"])
        if only is not None:
            segs = [s for s in segs if s.get("index") == only]
        if args.sid:
            segs = [s for s in segs if s.get("sid") == args.sid]
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
        # ファイル名に正味尺と書き出し時刻を含める（バージョン識別・オーナー指示 2026-08-08）
        # 例: {ID}_6_{TITLE}39分41秒2608081506.m4a
        net_sec = int(round(sum(b - a for a, b in keeps)))
        import datetime
        stamp = datetime.datetime.now().strftime("%y%m%d%H%M")
        # 処理パラメータをファイル名に記録する（オーナー指示 2026-08-10）。
        # 例: …_最終_NR-MossFormer2_SE_48K_aac_at-256k_25分48秒2608101012.m4a
        nr_mix = float(os.environ.get("PODCAST_NR_MIX", "0.3"))   # 除去のブレンド比
        # パラメータ表記は試聴サンプルと同じ形式（例: MossFormer2_amix0.30）
        params = (f"MossFormer2_amix{nr_mix:.2f}_" if denoise else "") + f"{enc}-256k"
        out = contents / (f"{ID}_{idx}_{safe_name(seg.get('title'))}_{params}_"
                          f"{net_sec//60}分{net_sec%60:02d}秒{stamp}.m4a")

        # 切り出しは「区間ごとに抽出 → 無劣化連結」。区間数に上限がない
        # （aselect 単一式は約100区間で式パーサが破綻する実害があった 2026-08-10。
        #   並列atrim+concatも数十区間で黙って途中終了する実害があった）
        prog_txt = prog_json = None
        if args.spec:
            sp = pathlib.Path(args.spec)
            prog_txt = sp.with_name(sp.name.replace("export_spec_", "export_progress_")
                                    .replace(".json", ".txt"))
            prog_json = sp.with_name(sp.name.replace("export_spec_", "export_progress_"))
        net_total = sum(b - a for a, b in keeps)

        def _stage(n):
            if prog_json:
                prog_json.write_text(json.dumps({"stage": n, "net": net_total}))

        def _tick(done_sec):
            if prog_txt:
                with open(prog_txt, "a") as f:
                    f.write(f"out_time_us={int(done_sec * 1e6)}\n")

        def _prog_args():
            return ["-progress", str(prog_txt), "-stats_period", "0.5"] if prog_txt else []

        tmp = out.with_name(out.name + ".part.m4a")
        pcm = out.with_name(out.name + ".part.wav")
        dn = None
        import tempfile
        with tempfile.TemporaryDirectory(dir=str(contents)) as td:
            tdp = pathlib.Path(td)
            _stage(1)
            listf = tdp / "list.txt"
            done = 0.0
            with open(listf, "w") as lf:
                for i, (a, b) in enumerate(keeps):
                    part = tdp / f"p{i:04d}.wav"
                    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                                    "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(media),
                                    "-c:a", "pcm_s16le", str(part)], check=True)
                    lf.write(f"file '{part.name}'\n")
                    done += b - a
                    _tick(done)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "concat", "-safe", "0", "-i", str(listf),
                            "-c", "copy", str(pcm)], check=True)
        try:
            enc_src = pcm
            if denoise:
                # ノイズ除去（MossFormer2_SE_48K）→ 元と nr_mix でブレンド
                _stage(2)
                dnr = out.with_name(out.name + ".dn.wav")
                enh_py = HERE / "venv_enhance" / "bin" / "python"
                code = (
                    "import sys\n"
                    "from clearvoice import ClearVoice\n"
                    "cv = ClearVoice(task='speech_enhancement', model_names=['MossFormer2_SE_48K'])\n"
                    "o = cv(input_path=sys.argv[1], online_write=False)\n"
                    "cv.write(o, output_path=sys.argv[2])\n")
                subprocess.run([str(enh_py), "-c", code, str(pcm), str(dnr)], check=True)
                mixed = out.with_name(out.name + ".mix.wav")
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                                "-i", str(pcm), "-i", str(dnr), "-filter_complex",
                                f"[0:a]volume={1-nr_mix:.2f}[a];[1:a]volume={nr_mix:.2f}[b];"
                                f"[a][b]amix=inputs=2:normalize=0",
                                "-c:a", "pcm_s16le", str(mixed)], check=True)
                dnr.unlink(missing_ok=True)
                dn = mixed
                enc_src = dn
            _stage(3)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
                           + _prog_args() +
                           ["-i", str(enc_src),
                            "-c:a", enc, "-b:a", "256k", str(tmp)], check=True)
        finally:
            pcm.unlink(missing_ok=True)
            if dn is not None:
                dn.unlink(missing_ok=True)
            if prog_txt:
                prog_txt.unlink(missing_ok=True)
            if prog_json:
                prog_json.unlink(missing_ok=True)
        # 書き出し後に実尺を検証する。指定と2秒以上ズレたら失敗として扱う
        # （「完了と言いながら短いファイルが出る」を二度と起こさないため）
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=noprint_wrappers=1:nokey=1", str(tmp)],
                               capture_output=True, text=True)
        actual = float(probe.stdout.strip() or 0)
        expected = sum(b - a for a, b in keeps)
        if abs(actual - expected) > 2.0:
            tmp.unlink(missing_ok=True)
            sys.exit(f"[audio] index {idx}: 書き出し尺が不一致（指定{expected:.1f}s / 実際{actual:.1f}s）。"
                     f" ファイルは出力しません")
        tmp.replace(out)
        net = sum(b - a for a, b in keeps)
        print(f"[audio] index {idx}: {len(keeps)}区間 / 正味 {int(net//60)}分{int(net%60):02d}秒"
              f" / AAC 256kbps ({enc}) -> {out}")

    print("[audio] 完了")


if __name__ == "__main__":
    main()
