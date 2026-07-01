#!/usr/bin/env python3
"""
最終処理その1: 無音（長すぎる空白）の検出。

ffmpeg の silencedetect で、ある長さ以上の無音区間をすべて拾い、
各区間の「前後で何を話しているか」を文字起こしから添えて出力する。
ここでは詰め幅は決めない。Claude Code が一覧と前後文脈を見て、
区間ごとに「いい感じ」の残し幅を判断するための材料を作るのが役目。

使い方:
   python detect_silence.py <ID> <メディアファイル>
       <メディアファイル> は data/<ID>/ 内の音源/動画（mp3/wav/mp4 など）
出力:
   data/<ID>/silences.json   検出した無音区間（前後発話つき）
   標準出力に一覧（Claude Code がそのままチャットに出せる形）

注意:
   - 検出のみ。実ファイルは一切変更しない。
   - 既定では 0.6 秒以上の無音を拾う（PODCAST_SILENCE_MIN で変更可）。
     これは「拾う閾値」であって「詰める閾値」ではない。詰め幅は後段で判断する。
"""
import os, sys, re, json, subprocess, pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
MIN_SIL = float(os.environ.get("PODCAST_SILENCE_MIN", "0.6"))   # これ以上の無音を拾う
NOISE = os.environ.get("PODCAST_SILENCE_NOISE", "-30dB")        # 無音とみなす音量閾値


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


def detect(media):
    """ffmpeg silencedetect を回して [(start,end,dur),...] を返す。"""
    cmd = ["ffmpeg", "-hide_banner", "-i", str(media),
           "-af", f"silencedetect=noise={NOISE}:d={MIN_SIL}", "-f", "null", "-"]
    p = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    log = p.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", log)]
    ends = re.findall(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", log)
    out = []
    for i, (e, d) in enumerate(ends):
        st = starts[i] if i < len(starts) else float(e) - float(d)
        out.append((float(st), float(e), float(d)))
    return out


def load_transcript_lines(outdir):
    """transcript.txt から (sec, speaker, text) を緩く拾う。HH:MM:SS Speaker N 形式想定。"""
    tp = outdir / "transcript.txt"
    if not tp.exists():
        return []
    lines = []
    cur = None
    for ln in tp.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(\d{1,2}):(\d{2}):(\d{2})\s+(Speaker\s*\d+|.+)$", ln)
        if m:
            sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if cur:
                lines.append(cur)
            cur = [sec, m.group(4).strip(), ""]
        elif cur is not None:
            cur[2] += ln.strip()
    if cur:
        lines.append(cur)
    return lines


def context_at(lines, sec):
    """その秒の前後で何を話しているかを短く返す。"""
    if not lines:
        return "", ""
    before = ""
    after = ""
    for i, (s, sp, tx) in enumerate(lines):
        if s <= sec:
            before = tx[-40:]
        if s >= sec and not after:
            after = tx[:40]
    return before, after


def main():
    if len(sys.argv) < 3:
        print("usage: python detect_silence.py <ID> <メディアファイル>")
        sys.exit(1)
    ID = sys.argv[1]
    paths = load_paths()
    root = paths.get("PODCAST_ROOT", str(HERE / "data"))
    outdir = pathlib.Path(root) / ID
    media = pathlib.Path(sys.argv[2])
    if not media.is_absolute():
        media = outdir / media
    if not media.exists():
        print(f"[detect] メディアが見つかりません: {media}")
        sys.exit(1)

    sils = detect(media)
    lines = load_transcript_lines(outdir)

    rows = []
    for st, en, dur in sils:
        b, a = context_at(lines, st)
        rows.append({
            "start_sec": round(st, 2), "end_sec": round(en, 2), "duration": round(dur, 2),
            "before": b, "after": a,
        })
    (outdir / "silences.json").write_text(
        json.dumps({"media": str(media), "noise": NOISE, "min": MIN_SIL, "silences": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # 一覧（Claude Code がそのままチャットに貼って、各区間の詰め幅を判断する材料）
    print("=" * 70)
    print(f"[detect] {media.name}: {MIN_SIL}秒以上の無音を {len(rows)} 件検出")
    print(f"[detect] silences.json に保存。次はこれを見て区間ごとに『いい感じ』の残し幅を決める。")
    print("=" * 70)
    for i, r in enumerate(rows, 1):
        print(f"{i:3}. {hms(r['start_sec'])}〜{hms(r['end_sec'])}  空白{r['duration']:.1f}秒")
        if r["before"]:
            print(f"      …直前: {r['before']}")
        if r["after"]:
            print(f"      直後…: {r['after']}")
    print("=" * 70)
    print("[detect] Claude Code への指示:")
    print("  各区間の『空白◯秒→何秒に詰めるか(keep)』を、前後の発話の意味を見て1件ずつ判断する。")
    print("  文の切れ目なら少し残す、言い淀み/考え込みの無駄な間ならしっかり詰める、等。")
    print("  機械的な一律閾値ではなく文脈で『いい感じ』に。各区間に reason も付ける。")
    print("  仕上げは確認を取らず一発で進める：判断結果を trim_plan.json に書き、そのまま")
    print("  apply_trim.py を実行する。適用後に、各区間を『◯◯だったので◯秒残した/詰めた』と")
    print("  自然言語でまとめて説明する（元ファイルは残るので後から直せる）。")
    print("  trim_plan.json 形式: {\"keeps\":[{\"start_sec\":..,\"end_sec\":..,\"keep\":0.4,\"reason\":\"…\"}, ...]}")


if __name__ == "__main__":
    main()
