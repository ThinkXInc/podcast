#!/usr/bin/env python3
"""
最終処理その1: 無音（長すぎる空白）の検出 —— 文字起こしタイムスタンプ方式。

【方針】ffmpeg の音響解析(silencedetect)は使わない（環境音・ホット録音で誤作動するため）。
WhisperX の単語タイムスタンプ(transcript.json)の「単語と単語のあいだの空き」を無音候補に拾う。

【詰め方の基本（重要）】
  基本は詰めない。通しで喋っている自然な感じを保つ。小〜中の間は“味”なので残す。
  **視聴者が離脱するほど長い空白だけ**を詰める対象にする。しかも:
  - 長いギャップでも **内容が続いていれば文字起こしの取りこぼし**（喋っているのに単語が落ちた）
    なので **触らない**（詰めると実発話を削る）。
  - **どうしても迷う箇所は、その文字起こしを出してユーザーに聞く**
    （ユーザーが「そこは席を立ったから詰めていい」等、記憶で判断できる）。

flag（Claude の判断補助。最終判断は内容を読んで上書きしてよい）:
  - "keep_natural"   : 通しの自然な間。原則そのまま残す（既定 4 秒未満は全部これ）。
  - "likely_dropped" : 長い＋内容が続いている＝取りこぼし疑い。原則 **触らない**。
  - "review"         : 長い＋内容が一旦切れている＝真の長い無音かもしれない。
                       **詰める候補だが、迷うなら文字起こしを出してユーザーに確認**。

使い方:
   python detect_silence.py <ID>
出力:
   data/<ID>/silences.json  セグメントごとのギャップ（final.mp4基準の時刻・前後の内容・flag）
env:
   PODCAST_GAP_MIN   拾う下限（既定 0.6 秒。一覧可視化用）
   PODCAST_GAP_LONG  これ未満は自然な間として残す（既定 4.0 秒）。以上だけ詰め候補に回す。
"""
import os, sys, json, pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
GAP_MIN = float(os.environ.get("PODCAST_GAP_MIN", "0.6"))
GAP_LONG = float(os.environ.get("PODCAST_GAP_LONG", "4.0"))

# 文末っぽい終わり（内容が一旦切れているサイン）。日本語文字起こしに句点が無いための近似。
SENT_END = ("よ", "ね", "な", "か", "た", "だ", "です", "ます", "でしょ", "ました",
            "ません", "けど", "から", "よね", "んです", "ですよ", "ますよ", "ますね", "ですね")


def load_paths():
    paths = {}
    os.environ["HERE"] = str(HERE)
    conf = HERE / "config/paths.conf"
    if conf.exists():
        for line in conf.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                paths[k] = os.path.expandvars(v.strip().strip('"'))
    return paths


def hms(s):
    s = max(0, float(s))
    return f"{int(s)//3600:02d}:{(int(s)%3600)//60:02d}:{int(s)%60:02d}.{int((s*10)%10)}"


def shift(t, seg_start, drops):
    """元音源時間 t を drops を詰めた後の final.mp4 時間へ。drop 中なら None。"""
    off = 0.0
    for a, b in sorted(drops):
        if t >= b:
            off += (b - a)
        elif a <= t < b:
            return None
    return t - seg_start - off


def find_media(outdir, idx):
    contents = outdir / "contents"
    if not contents.exists():
        return None
    for d in sorted(contents.glob(f"{idx:02d}_*")):
        f = d / "final.mp4"
        if f.exists():
            return f"contents/{d.name}/final.mp4"
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: python detect_silence.py <ID>")
        sys.exit(1)
    ID = sys.argv[1]
    paths = load_paths()
    root = paths.get("PODCAST_ROOT", str(HERE / "data"))
    outdir = pathlib.Path(root) / ID

    tj = outdir / "transcript.json"
    sj = outdir / "segments.json"
    if not tj.exists():
        print(f"[detect] transcript.json が無い: {tj}"); sys.exit(1)
    if not sj.exists():
        print(f"[detect] segments.json が無い（確定してから実行）: {sj}"); sys.exit(1)

    words = json.loads(tj.read_text(encoding="utf-8")).get("word_segments", [])
    words = [w for w in words if w.get("start") is not None and w.get("end") is not None]
    words.sort(key=lambda w: w["start"])
    segs = json.loads(sj.read_text(encoding="utf-8")).get("segments", [])

    out_segments = []
    print("=" * 74)
    print(f"[detect] 文字起こしギャップ方式（音響解析なし）。基本は詰めない／"
          f"{GAP_LONG}s 以上だけ詰め候補")
    print("=" * 74)
    for s in sorted(segs, key=lambda x: x.get("index", 0)):
        idx = s.get("index")
        st = float(s["start_sec"]); en = float(s["end_sec"])
        drops = [tuple(map(float, d)) for d in s.get("drops", [])]
        media = find_media(outdir, idx)
        inside = [w for w in words if w["start"] >= st and w["end"] <= en]
        gaps = []
        for i in range(len(inside) - 1):
            ge = inside[i]["end"]; ns = inside[i + 1]["start"]
            g = ns - ge
            if g < GAP_MIN:
                continue
            fs = shift(ge, st, drops); fe = shift(ns, st, drops)
            if fs is None or fe is None or fe - fs < 0.02:
                continue
            before = "".join(x.get("word", "") for x in inside[max(0, i - 10):i + 1])[-24:]
            after = "".join(x.get("word", "") for x in inside[i + 1:i + 11])[:24]
            sent_end = before.endswith(SENT_END)
            if g < GAP_LONG:
                flag = "keep_natural"
            elif not sent_end:
                flag = "likely_dropped"
            else:
                flag = "review"
            gaps.append({
                "start_sec": round(fs, 2), "end_sec": round(fe, 2), "duration": round(g, 2),
                "before": before, "after": after, "flag": flag,
            })
        out_segments.append({"index": idx, "title": s.get("title", ""), "media": media, "gaps": gaps})
        review = [x for x in gaps if x["flag"] == "review"]
        dropped = [x for x in gaps if x["flag"] == "likely_dropped"]
        print(f"\n#{idx} {s.get('title','')[:26]}  media={media}")
        print(f"    尺{int(en-st)}s / drops{len(drops)} / ギャップ計{len(gaps)}"
              f" → 詰め候補(review){len(review)} 件 / 取りこぼし疑い{len(dropped)} 件"
              f" / 自然な間{len(gaps)-len(review)-len(dropped)} 件は残す")
        for x in review + dropped:
            mark = "◎詰め候補(要確認かも)" if x["flag"] == "review" else "⚠取りこぼし疑い(触らない)"
            print(f"    {hms(x['start_sec'])} {mark} {x['duration']:.1f}s   …{x['before']}／{x['after']}…")

    (outdir / "silences.json").write_text(
        json.dumps({"method": "transcript_gap", "gap_min": GAP_MIN, "gap_long": GAP_LONG,
                    "segments": out_segments}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 74)
    print("[detect] silences.json 保存。Claude Code への指示:")
    print("  ・基本は詰めない（通しで喋る自然さを優先）。keep_natural は全部残す。")
    print("  ・likely_dropped（内容が続く長い空白）は取りこぼしなので触らない。")
    print("  ・review（内容が切れている長い空白）だけ詰め候補。ただし本当に無音か迷うなら、")
    print("    その箇所の前後の文字起こしを出してユーザーに聞く（記憶で『席を立った→詰めてOK』等）。")
    print("  ・詰めると決めたものだけ trim_plan.json に keep 秒(0.4前後)と reason を書き、")
    print("    apply_trim.py をセグメントごとに実行。元(_orig)は必ず残る。")


if __name__ == "__main__":
    main()
