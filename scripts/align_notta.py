#!/usr/bin/env python3
# Notta の正確なテキストを WhisperX の強制アラインで音声に整列し、
# transcript.json を「Notta文字 × 単語時刻 × 話者」に作り直す。
#   python align_notta.py <ID> [--limit N] [--out PATH]
# --limit N: 先頭 N ブロックだけ処理（実現性テスト用）
import os, sys, re, json, subprocess, pathlib

ROOT = pathlib.Path("/Users/K00TSUKA/Sources/podcast")
ID = sys.argv[1]
LIMIT = None
OUT = None
for i, a in enumerate(sys.argv):
    if a == "--limit": LIMIT = int(sys.argv[i+1])
    if a == "--out": OUT = sys.argv[i+1]
base = ROOT / "data" / ID

# 1) Notta txt を話者ブロックに
cands=sorted(base.glob("*transcript*.txt"))
def _sc(q):
    try: return len(re.findall(r"Speaker\s+\d+", q.read_text(encoding="utf-8")))
    except Exception: return 0
txt_path=max(cands,key=_sc)
print("[align] Notta txt =", txt_path.name)
txt = txt_path.read_text(encoding="utf-8")
pat = re.compile(r'(\d{2}):(\d{2}):(\d{2})\s+Speaker\s+(\d+)\s*\n(.*?)(?=\n\d{2}:\d{2}:\d{2}\s+Speaker|\Z)', re.S)
blocks = []
for m in pat.finditer(txt):
    h, mm, ss, spk, body = m.groups()
    t = int(h)*3600 + int(mm)*60 + int(ss)
    body = re.sub(r'\s+', '', body).strip()
    if body:
        blocks.append({"start": float(t), "spk": int(spk), "text": body})
# 音源尺
media = None
for ext in (".m4a", ".mp4", ".mov", ".wav", ".mp3"):
    for f in base.glob(f"*{ext}"):
        media = f; break
    if media: break
dur = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
      "-of","csv=p=0",str(media)],capture_output=True,text=True).stdout.strip())
for i, b in enumerate(blocks):
    b["end"] = blocks[i+1]["start"] if i+1 < len(blocks) else dur
if LIMIT:
    blocks = blocks[:LIMIT]
print(f"[align] Notta {len(blocks)} ブロック / 音源 {dur:.0f}s / media={media.name}")

# 2) 16k mono wav を用意
wav = base / ".align_audio.wav"
if not wav.exists():
    print("[align] 16k mono wav 抽出中…")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",str(media),
                    "-ac","1","-ar","16000",str(wav)], check=True)

# 3) WhisperX 強制アライン
import whisperx
device = "cpu"
audio = whisperx.load_audio(str(wav))
print("[align] ja アラインモデル読込中（初回はDLあり）…")
model_a, metadata = whisperx.load_align_model(language_code="ja", device=device)
segs_in = [{"start": b["start"], "end": b["end"], "text": b["text"]} for b in blocks]
print("[align] 整列中…")
res = whisperx.align(segs_in, model_a, metadata, audio, device,
                     return_char_alignments=False, print_progress=True)

# 4) 話者を戻して transcript.json 形式に
out_segments = []
word_segments = []
for b, s in zip(blocks, res["segments"]):
    spk = f"SPEAKER_{b['spk']:02d}"
    words = s.get("words", [])
    for w in words:
        w["speaker"] = spk
        if "start" in w:
            word_segments.append(w)
    out_segments.append({"start": s.get("start"), "end": s.get("end"),
                         "text": s.get("text", b["text"]), "words": words, "speaker": spk})
word_segments.sort(key=lambda w: w.get("start", 0))
out = {"segments": out_segments, "word_segments": word_segments, "language": "ja"}

out_path = pathlib.Path(OUT) if OUT else (base / "transcript.json")
out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print(f"[align] 完了 -> {out_path}  ({len(out_segments)} seg / {len(word_segments)} word)")
# サンプル出力（検証）
for s in out_segments[:3]:
    ws = "".join(w.get("word","") for w in s["words"][:20])
    print(f"  {s['start']:.1f}-{s['end']:.1f} [{s['speaker']}] {ws}…")
