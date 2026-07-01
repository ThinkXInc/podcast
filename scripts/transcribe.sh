#!/usr/bin/env bash
# 文字起こし＋字幕の元データ生成（WhisperX large-v3, ローカル, 0円）。
#
# 出力（data/<ID>/）:
#   transcript.json  単語タイムスタンプ付き（render.py の字幕生成が読む。これが字幕の元データ）
#   transcript.txt   プレーン全文（suggest.py / GPT入力 / 校正用）
#   <ID>.srt / .vtt  フル音源の字幕（任意・確認用）
#
# 使い方:
#   bash scripts/transcribe.sh <ID> [メディアファイル]
#   メディアを省略すると data/<ID>/ 内の音源/動画を探す。
#
# 前提:
#   - venv はプロジェクト作業ディレクトリ内 $HERE/venv に置く（ホーム ~/venvs/... には置かない）。
#     場所は config/paths.conf の VENV で指定（環境変数 VENV でも上書き可）。
#   - Apple Silicon では arm64 の python で venv を作る（Intel 版はアーキ不一致でセグフォルト。
#     本スクリプトは arch を照合し、合わなければ実行前にエラーで止める）。
#   - cpu + int8 が安定。
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"

# paths.conf を読み込む（PODCAST_ROOT / VENV / WHISPER_* を一括で反映）。
# $HERE を展開してから source するので、VENV など全変数が確実に効く。
ROOT="$HERE/data"
if [ -f "$HERE/config/paths.conf" ]; then
  _tmp_conf="$(mktemp)"
  HERE="$HERE" envsubst < "$HERE/config/paths.conf" > "$_tmp_conf" 2>/dev/null \
    || sed "s|\$HERE|$HERE|g; s|\${HERE}|$HERE|g" "$HERE/config/paths.conf" > "$_tmp_conf"
  # shellcheck disable=SC1090
  source "$_tmp_conf"
  rm -f "$_tmp_conf"
  ROOT="${PODCAST_ROOT:-$HERE/data}"
fi

ID="${1:?usage: transcribe.sh <ID> [media]}"
OUT="$ROOT/$ID"
mkdir -p "$OUT"

# メディア特定
MEDIA="${2:-}"
if [ -z "$MEDIA" ]; then
  for ext in m4a mp3 wav aac mp4 mov m4v; do
    if [ -f "$OUT/$ID.$ext" ]; then MEDIA="$OUT/$ID.$ext"; break; fi
  done
  if [ -z "$MEDIA" ]; then
    MEDIA="$(find "$OUT" -maxdepth 1 -type f \( -iname '*.m4a' -o -iname '*.mp3' -o -iname '*.wav' -o -iname '*.aac' -o -iname '*.mp4' -o -iname '*.mov' \) ! -iname '*_orig*' ! -iname '*_trimmed*' | head -n1)"
  fi
fi
[ -n "$MEDIA" ] && [ -f "$MEDIA" ] || { echo "[transcribe] メディアが見つかりません（data/$ID/ に置くか引数で指定）"; exit 1; }

# venv 解決: paths.conf の VENV を最優先。未設定ならプロジェクト内 $HERE/venv を既定にする。
# 【規約】venv はプロジェクト作業ディレクトリ内に置く（ホーム ~/venvs/... には置かない）。
VENV="${VENV:-$HERE/venv}"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "[transcribe] venv が見つかりません: $VENV"
  echo "[transcribe] プロジェクト直下に venv を作ってください:"
  echo "    python3 -m venv \"$HERE/venv\" && source \"$HERE/venv/bin/activate\" && pip install -r \"$HERE/requirements.txt\""
  echo "  （config/paths.conf の VENV で場所を変えられますが、原則プロジェクト内に置きます）"
  exit 1
fi
# アーキ不一致のセグフォルトを未然に防ぐ: マシンの arch と venv python の arch を照合
MACH_ARCH="$(uname -m)"                                   # arm64 など
VENV_ARCH="$("$VENV/bin/python3" -c 'import platform;print(platform.machine())' 2>/dev/null || echo unknown)"
if [ "$MACH_ARCH" = "arm64" ] && [ "$VENV_ARCH" != "arm64" ]; then
  echo "[transcribe] venv のアーキ($VENV_ARCH)がマシン($MACH_ARCH)と不一致です: $VENV"
  echo "[transcribe] Intel 用の壊れた venv の可能性が高く、セグフォルトの原因です。"
  echo "[transcribe] arm64 で作り直してください（プロジェクト内 $HERE/venv に）。"
  exit 1
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

MODEL="${WHISPER_MODEL:-large-v3}"
DEVICE="${WHISPER_DEVICE:-cpu}"
COMPUTE="${WHISPER_COMPUTE:-int8}"
LANG="${WHISPER_LANG:-ja}"

CHUNK_SEC="${WHISPER_CHUNK_SEC:-720}"
CHUNK_OVERLAP="${WHISPER_CHUNK_OVERLAP:-6}"

# 音源全体の長さ(秒)
DUR="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$MEDIA" | cut -d. -f1)"
[ -n "$DUR" ] || { echo "[transcribe] 長さ取得に失敗"; exit 1; }

WORK="$OUT/.chunks"
rm -rf "$WORK"; mkdir -p "$WORK"

echo "[transcribe] WhisperX $MODEL ($DEVICE/$COMPUTE) 分割文字起こし: 全長 ${DUR}s / チャンク ${CHUNK_SEC}s（重なり ${CHUNK_OVERLAP}s）"

# チャンク境界を作る（オーバーラップ付き）。各行: index start_sec end_sec
# ※ mapfile は bash4+ 専用で macOS の bash 3.2 に無いため使わない。while read で回す。
_chunks_file="$(mktemp)"
python3 - "$DUR" "$CHUNK_SEC" "$CHUNK_OVERLAP" > "$_chunks_file" <<'PY'
import sys
dur=int(sys.argv[1]); size=int(sys.argv[2]); ov=int(sys.argv[3])
i=0; s=0
while s < dur:
    e=min(dur, s+size)
    a=max(0, s-ov) if i>0 else 0   # 前側だけ少し食い込ませる
    print(f"{i} {a} {e}")
    s=e; i+=1
PY

n=$(grep -c . "$_chunks_file")
echo "[transcribe] ${n} チャンクに分割。逐次で処理します（各チャンクが時間上限内に収まる）。"

while read -r ci cstart cend; do
  [ -n "$ci" ] || continue
  clen=$(( cend - cstart ))
  cfile="$WORK/chunk_${ci}.wav"
  echo "[transcribe] [chunk $((ci+1))/${n}] ${cstart}s〜${cend}s (${clen}s) 抽出＋文字起こし…"
  # 抽出（wav 16k mono が whisperx に無難）。</dev/null で while read の stdin を奪わせない
  ffmpeg -y -loglevel error -ss "$cstart" -t "$clen" -i "$MEDIA" \
         -ac 1 -ar 16000 "$cfile" </dev/null
  # 文字起こし（このチャンク専用の出力先）
  cdir="$WORK/out_${ci}"; mkdir -p "$cdir"
  whisperx "$cfile" \
    --model "$MODEL" --device "$DEVICE" --compute_type "$COMPUTE" \
    --language "$LANG" --output_dir "$cdir" --output_format json </dev/null
  # このチャンクの絶対開始秒を記録（マージ時のオフセット）
  echo "$cstart" > "$cdir/.offset"
done < "$_chunks_file"
rm -f "$_chunks_file"

# 全チャンクJSONをオフセット補正してマージ → transcript.json
python3 - "$WORK" "$OUT/transcript.json" "$CHUNK_OVERLAP" <<'PY'
import json, sys, pathlib, glob
work=pathlib.Path(sys.argv[1]); dst=sys.argv[2]; ov=float(sys.argv[3])

chunks=[]
for cdir in sorted(work.glob("out_*"), key=lambda p:int(p.name.split("_")[1])):
    off_f=cdir/".offset"
    if not off_f.exists(): continue
    off=float(off_f.read_text().strip())
    js=list(cdir.glob("*.json"))
    if not js: continue
    data=json.load(open(js[0], encoding="utf-8"))
    # 単語（word_segments 優先、無ければ segments[].words）
    words=data.get("word_segments") or [w for s in data.get("segments",[]) for w in s.get("words",[])]
    segs=data.get("segments",[])
    chunks.append((off, words, segs))

def shift_words(words, off):
    out=[]
    for w in words:
        s=w.get("start"); e=w.get("end")
        if s is None or e is None: continue
        nw=dict(w); nw["start"]=s+off; nw["end"]=e+off
        out.append(nw)
    return out
def shift_segs(segs, off):
    out=[]
    for s in segs:
        st=s.get("start"); en=s.get("end")
        ns=dict(s)
        if st is not None: ns["start"]=st+off
        if en is not None: ns["end"]=en+off
        if "words" in ns:
            ns["words"]=shift_words(ns["words"], off)
        out.append(ns)
    return out

# 絶対時刻へ補正
abs_words=[]; abs_segs=[]
bounds=[]  # 各チャンクの絶対開始
for off, words, segs in chunks:
    abs_words.append((off, shift_words(words, off)))
    abs_segs.append((off, shift_segs(segs, off)))
    bounds.append(off)

# 隣接チャンクの重複排除: チャンクiとi+1の重なり領域は、中点より前はi、後はi+1を採用
merged_words=[]
for i,(off,words) in enumerate(abs_words):
    lo = -1e9
    hi = 1e9
    if i>0:
        prev_off=abs_words[i-1][0]
        # 重なり領域 [off, off+ov] のうち中点までは前チャンク担当 → 自分は中点以降
        lo = off + ov/2.0
    if i < len(abs_words)-1:
        next_off=abs_words[i+1][0]
        hi = next_off + ov/2.0   # 次チャンクは next_off から。中点=next_off+ov/2 まで自分が担当
    for w in words:
        c=(w["start"]+w["end"])/2.0
        if lo <= c < hi:
            merged_words.append(w)
merged_words.sort(key=lambda w:w["start"])

# segments も同様に中点ルールで
merged_segs=[]
for i,(off,segs) in enumerate(abs_segs):
    lo = (off + ov/2.0) if i>0 else -1e9
    hi = (abs_segs[i+1][0] + ov/2.0) if i<len(abs_segs)-1 else 1e9
    for s in segs:
        st=s.get("start")
        c = st if st is not None else lo
        if lo <= c < hi:
            merged_segs.append(s)
merged_segs.sort(key=lambda s:(s.get("start") or 0))

out={"segments":merged_segs, "word_segments":merged_words}
json.dump(out, open(dst,"w",encoding="utf-8"), ensure_ascii=False)
print(f"[transcribe] マージ完了: {len(merged_words)} 単語 / {len(merged_segs)} セグメント -> transcript.json")
PY

# 中間チャンクは掃除（残したいなら KEEP_CHUNKS=1）
if [ "${KEEP_CHUNKS:-0}" != "1" ]; then
  rm -rf "$WORK"
fi
# プレーン全文（segments のテキストを連結）
python3 - "$OUT/transcript.json" "$OUT/transcript.txt" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(src, encoding="utf-8"))
except Exception:
    open(dst, "w").write(""); sys.exit(0)
lines = []
for s in d.get("segments", []):
    t = (s.get("text") or "").strip()
    st = s.get("start")
    if t:
        if st is not None:
            h=int(st//3600); m=int((st%3600)//60); ss=int(st%60)
            lines.append(f"{h:02d}:{m:02d}:{ss:02d} {t}")
        else:
            lines.append(t)
open(dst,"w",encoding="utf-8").write("\n".join(lines)+"\n")
print(f"[transcribe] transcript.txt: {len(lines)} 行")
PY

echo "[transcribe] 完了 -> $OUT/transcript.json (字幕の元データ) , transcript.txt"
echo "[transcribe] 次: suggest.py で候補生成 → 確定 segments.json → render.py で字幕付き書き出し"
