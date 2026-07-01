#!/usr/bin/env python3
"""
確定セグメントごとに書き出し（ffmpeg, AE不要）。

segments.json（チャットで確定した切り出し定義）を読み、各セグメントを
区間で切り出し、drops（カット確定・無音などの小区間）を除いて 1 本に繋ぎ、
WhisperX の transcript.json（単語タイムスタンプ）から その区間の字幕(.ass)を作って
焼き込む。後から人が再編集できるよう、字幕なし動画・字幕単体・音声も残す。

各セグメントの出力（data/<ID>/contents/NN_title/）:
   - audio.m4a        切り出し音源（再編集用）
   - video_nosub.mp4  字幕なし背景動画（AE/DaVinci等で字幕入れ直す用）
   - segment.ass      この区間の字幕単体（再編集用）
   - final.mp4        字幕焼き込み済み 完成動画

入力:
   data/<ID>/segments.json   ← 確定セグメント
       {"segments":[{"index":1,"title":"…","start_sec":752,"end_sec":2022,
                     "drops":[[900,930]]}, ...]}
   data/<ID>/transcript.json ← WhisperX の単語タイムスタンプ（字幕用）
       無ければ字幕なしで書き出す（video_nosub.mp4 を final.mp4 として扱う）
   メディア本体（data/<ID>/ 直下の音源/動画、または <ID>.<ext>）

使い方:
   python render.py <ID> [メディアファイル]
   メディアを省略すると data/<ID>/ 内の音源/動画を自動で探す。

字幕の見た目は config/style.conf で調整。
"""
import os, sys, json, subprocess, pathlib, re, glob

HERE = pathlib.Path(__file__).resolve().parents[1]
MEDIA_EXT = (".m4a", ".mp3", ".wav", ".aac", ".mp4", ".mov", ".m4v")


def load_conf(path):
    d = {}
    os.environ["HERE"] = str(HERE)
    p = HERE / path
    if not p.exists():
        return d
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = os.path.expandvars(v.strip().strip('"'))
    return d


def sec_to_ass_time(s):
    s = max(0.0, s)
    h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"


def safe_name(t):
    t = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff－ー]+", "_", t or "").strip("_")
    return t[:40] if t else "untitled"


def find_media(outdir, ID, arg):
    if arg:
        p = pathlib.Path(arg)
        return p if p.is_absolute() else (outdir / arg)
    # <ID>.<ext> 優先、無ければフォルダ内の最初のメディア（_orig/_trimmed と contents 配下は除く）
    for ext in MEDIA_EXT:
        cand = outdir / f"{ID}{ext}"
        if cand.exists():
            return cand
    for f in sorted(outdir.glob("*")):
        if f.suffix.lower() in MEDIA_EXT and "_orig" not in f.stem and "_trimmed" not in f.stem:
            return f
    return None


def find_subtitles_ffmpeg():
    """字幕(libass)フィルタが使える ffmpeg を探して返す。
    既定の ffmpeg が libass 無しでビルドされていること（homebrew等）があるため、
    候補を順に試し、subtitles フィルタを持つ最初のものを使う。無ければ None。"""
    import shutil as _sh
    candidates = []
    env = os.environ.get("PODCAST_FFMPEG_SUBS")
    if env:
        candidates.append(env)
    default = _sh.which("ffmpeg")
    if default:
        candidates.append(default)
    # よくある別ビルドの場所も候補に
    candidates += ["/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/bin/ffmpeg"]
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        if not pathlib.Path(c).exists() and not _sh.which(c):
            continue
        try:
            out = subprocess.run([c, "-hide_banner", "-filters"],
                                 capture_output=True, text=True).stdout
            if re.search(r"^\s*\S*\s+subtitles\s", out, re.M) or " subtitles " in out:
                return c
        except Exception:
            continue
    return None


def has_video(media):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(media)],
        capture_output=True, text=True).stdout.strip()
    return "video" in out


def load_words(outdir):
    """WhisperX transcript.json から単語リスト [{word,start,end}] を取り出す。無ければ []。"""
    tp = outdir / "transcript.json"
    if not tp.exists():
        return []
    data = json.loads(tp.read_text(encoding="utf-8"))
    words = data.get("word_segments")
    if not words:
        words = [w for s in data.get("segments", []) for w in s.get("words", [])]
    return words or []


def keep_ranges(start, end, drops):
    """drops を除いた保持区間 [(a,b),...] を返す。"""
    keep = []
    cur = start
    for d0, d1 in sorted(drops):
        if d0 > cur:
            keep.append((cur, min(d0, end)))
        cur = max(cur, d1)
        if cur >= end:
            break
    if cur < end:
        keep.append((cur, end))
    return [(a, b) for a, b in keep if b - a > 0.02]


def build_segment_ass(words, seg_start, seg_end, drops, style, out_path):
    """その区間の字幕(.ass)を作る。drops 中の語は捨て、時間は切り出し後の動画基準に振り直す。"""
    S = style
    def g(k, d): return S.get(k, d)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {g('WIDTH','1920')}
PlayResY: {g('HEIGHT','1080')}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV
Style: Default,{g('FONT','Hiragino Sans')},{g('FONT_SIZE','54')},{g('PRIMARY_COLOUR','&H00FFFFFF')},{g('OUTLINE_COLOUR','&H00000000')},&H00000000,1,{g('OUTLINE','3')},{g('SHADOW','1')},{g('ALIGNMENT','2')},40,40,{g('MARGIN_V','70')}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def shift(t):
        # 元音源時間 t を drops を詰めた後の動画時間に変換。drop中なら None
        offset = 0.0
        for d0, d1 in sorted(drops):
            if t >= d1:
                offset += (d1 - d0)
            elif d0 <= t < d1:
                return None
        return t - seg_start - offset

    max_chars = int(g("MAX_CHARS_PER_LINE", "24"))
    lines = []
    buf, buf_start, buf_end = "", None, None

    def flush():
        nonlocal buf, buf_start, buf_end
        if buf and buf_start is not None and buf_end is not None and buf_end > buf_start:
            text = buf.strip()
            wrapped = "\\N".join(text[i:i+max_chars] for i in range(0, len(text), max_chars))
            lines.append(f"Dialogue: 0,{sec_to_ass_time(buf_start)},{sec_to_ass_time(buf_end)},Default,,0,0,0,,{wrapped}")
        buf, buf_start, buf_end = "", None, None

    for w in words:
        ws, we = w.get("start"), w.get("end")
        wt = w.get("word", "")
        if ws is None or we is None:
            continue
        if we <= seg_start or ws >= seg_end:
            continue
        s2, e2 = shift(ws), shift(we)
        if s2 is None or e2 is None:
            continue
        if buf_start is None:
            buf_start = max(0, s2)
        buf += wt
        buf_end = e2
        if any(p in wt for p in "。．！？!?") or len(buf) >= max_chars * 2:
            flush()
    flush()
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main():
    if len(sys.argv) < 2:
        print("usage: python render.py <ID> [メディアファイル]")
        sys.exit(1)
    ID = sys.argv[1]
    paths = load_conf("config/paths.conf")
    style = load_conf("config/style.conf")
    root = paths.get("PODCAST_ROOT") or paths.get("WORKROOT") or str(HERE / "data")
    outdir = pathlib.Path(root) / ID

    seg_path = outdir / "segments.json"
    if not seg_path.exists():
        print(f"[render] {seg_path} が無い。チャットで切り出しを確定し segments.json を書いてから実行する。")
        sys.exit(1)
    segs = json.loads(seg_path.read_text(encoding="utf-8")).get("segments", [])
    if not segs:
        print("[render] segments が空。"); sys.exit(1)

    media = find_media(outdir, ID, sys.argv[2] if len(sys.argv) > 2 else None)
    if not media or not media.exists():
        print(f"[render] メディアが見つからない（data/{ID}/ に音源/動画を置くか、引数で指定）。")
        sys.exit(1)

    words = load_words(outdir)
    if not words:
        print("[render] transcript.json（WhisperXの単語タイムスタンプ）が無いので字幕なしで書き出す。")
        print("         字幕を付けるには transcribe.sh で transcript.json を作ってから再実行。")

    bg = style.get("BG_COLOR", "black")
    W = style.get("WIDTH", "1920"); H = style.get("HEIGHT", "1080")
    src_has_video = has_video(media)
    contents = outdir / "contents"; contents.mkdir(exist_ok=True)

    # 字幕焼き込み用の ffmpeg（libass 対応版）を先に解決しておく
    subs_ffmpeg = find_subtitles_ffmpeg() if words else None
    if words and not subs_ffmpeg:
        print("[render] 警告: libass(subtitles)対応の ffmpeg が見つかりません。")
        print("         字幕は焼き込めないので video_nosub を final として出します。")
        print("         libass 付き ffmpeg を入れるか、環境変数 PODCAST_FFMPEG_SUBS でパス指定してください。")

    for seg in segs:
        idx = seg.get("index", segs.index(seg) + 1)
        start = float(seg["start_sec"]); end = float(seg["end_sec"])
        drops = [tuple(map(float, d)) for d in seg.get("drops", [])]
        name = f"{idx:02d}_{safe_name(seg.get('title'))}"
        d = contents / name; d.mkdir(exist_ok=True)
        keeps = keep_ranges(start, end, drops)
        if not keeps:
            print(f"[render] {name}: 有効区間なしスキップ"); continue

        # --- 音声: keep区間を切り出して連結 ---
        parts = []
        for i, (a, b) in enumerate(keeps):
            p = d / f".part{i}.m4a"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media),
                            "-ss", str(a), "-to", str(b), "-vn",
                            "-c:a", "aac", str(p)], check=True)
            parts.append(p)
        listfile = d / ".concat.txt"
        listfile.write_text("".join(f"file '{p.name}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", str(listfile), "-c", "copy",
                        str(d / "audio.m4a")], cwd=str(d), check=True)
        for p in parts:
            p.unlink(missing_ok=True)
        listfile.unlink(missing_ok=True)

        # --- 字幕(.ass): あれば作る ---
        n_sub = 0
        if words:
            n_sub = build_segment_ass(words, start, end, drops, style, d / "segment.ass")

        # --- video_nosub.mp4: 背景＋音声（字幕なし・再編集用）---
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"color=c={bg}:s={W}x{H}:r=30",
                        "-i", str(d / "audio.m4a"), "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(d / "video_nosub.mp4")], check=True)

        # --- final.mp4: 字幕焼き込み（字幕が無い/libass無しなら nosub をコピー）---
        if n_sub > 0 and subs_ffmpeg:
            # セグメントフォルダを cwd にして相対パス segment.ass を渡す
            # （絶対パスの引用でコケる問題を避ける。音声concatと同じ cwd 方式）
            r = subprocess.run([subs_ffmpeg, "-y", "-loglevel", "error",
                                "-i", "video_nosub.mp4",
                                "-vf", "subtitles=segment.ass",
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                                "final.mp4"], cwd=str(d))
            if r.returncode == 0:
                extra = f"字幕 {n_sub} 行"
            else:
                import shutil
                shutil.copy2(d / "video_nosub.mp4", d / "final.mp4")
                extra = "字幕焼込失敗→字幕なし"
        else:
            import shutil
            shutil.copy2(d / "video_nosub.mp4", d / "final.mp4")
            extra = "字幕なし"
        print(f"[render] {name} -> final.mp4 ({extra}) + video_nosub.mp4 / segment.ass / audio.m4a")

    print(f"[render] 全 {len(segs)} 本 完了 -> {contents}")
    print("[render] 各フォルダに final.mp4（完成）と再編集用素材を残しました。")


if __name__ == "__main__":
    main()
