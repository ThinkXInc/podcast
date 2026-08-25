#!/usr/bin/env python3
# Whisper の transcript.json から、Notta 全文PDF と同じ役割の「土台PDF」を組む。
#
#   python scripts/make_transcript_pdf.py <ID>
#   -> data/<ID>/<ID>_全文.pdf          校正用PDFの土台（Notta PDF の代替）
#      data/<ID>/transcript_pdf_map.json 単語 -> ページ・矩形・時刻 の対応表
#
# なぜ作るか（D-015 の帰結）:
#   本文は Whisper を正とするので、Notta の PDF を土台にすると本文が食い違う。
#   make_review_pdf.py は Notta PDF に対して `page.search_for(引用文)` の完全一致検索で
#   位置を探しており、1文字でも違えば見つからない。実際そのために
#   「先頭40字→28字→18字→12字」と4段のフォールバックを積む羽目になっていた。
#
# 自前で組む利点:
#   組版した本人なので、各単語がどのページのどの矩形に置かれたかを知っている。
#   だから文字列検索が要らず、**時刻で引ける**。カット区間・ハイライト・詰め位置は
#   すべて秒で持っているので、時刻で引けるほうがパイプライン全体と素直に噛み合う。

import os
import sys
import json

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import idpaths  # data/<ID>/ のファイル配置は idpaths が唯一の定義（D-002 改定）
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE_W, PAGE_H = 595.92, 841.92        # A4（Notta PDF と同じ）
ML, MR, MT, MB = 56.0, 56.0, 60.0, 56.0
FS = 10.5                               # 本文の級数
LH = 17.0                               # 行送り
HDR_FS = 9.0                            # 「00:03:39 Speaker 1」の級数
HDR_GAP = 6.0                           # ヘッダと本文のすき間
BLOCK_GAP = 9.0                         # ブロック間のあき

FONT_CANDIDATES = [
    os.environ.get("PODCAST_PDF_FONT", ""),
    "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    os.path.expanduser("~/Library/Fonts/NotoSansJP-Regular.otf"),
    "/Library/Fonts/ipaexg.ttf",
]


TURN_GAP = 2.5          # これ以上の無音で発言ブロックを切る（秒）
TURN_MAX = 45.0         # 1ブロックが長くなりすぎたら切る（秒）。頭出しの手がかりを保つため


def fmt_hms(t):
    t = int(t)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def group_into_turns(segments):
    """細かい Whisper セグメントを、話者の発言ターンにまとめる。
    返すのは {start, speaker, words} のリスト（words は時刻付きの単語だけ）。"""
    turns = []
    cur = None
    for seg in segments:
        words = [w for w in (seg.get("words") or []) if w.get("start") is not None]
        if not words:
            continue
        spk = seg.get("speaker")
        st = words[0]["start"]
        new_turn = (
            cur is None
            or spk != cur["speaker"]
            or st - cur["words"][-1].get("end", cur["words"][-1]["start"]) > TURN_GAP
            or st - cur["start"] > TURN_MAX
        )
        if new_turn:
            cur = {"start": st, "speaker": spk, "words": []}
            turns.append(cur)
        cur["words"].extend(words)
    return turns


def main():
    if len(sys.argv) < 2:
        print("usage: make_transcript_pdf.py <ID>")
        return 1
    idv = sys.argv[1]
    base = os.path.join(HERE, "data", idv)
    tpath = idpaths.find(base, "transcript.json")
    if not os.path.isfile(tpath):
        print(f"[全文PDF] {tpath} がありません。先に transcribe.sh を実行してください。")
        return 1

    import fitz

    font_file = next((p for p in FONT_CANDIDATES if p and os.path.exists(p)), None)
    if font_file is None:
        print("[全文PDF] 和文フォントが見つかりません。PODCAST_PDF_FONT で指定してください。")
        return 1
    font = fitz.Font(fontfile=font_file)
    print(f"[全文PDF] フォント: {os.path.basename(font_file)}")

    data = json.load(open(tpath, encoding="utf-8"))
    # Whisper のセグメントは平均2〜3秒と細かい。1つずつヘッダを付けると紙が4倍近くに
    # 膨らんで読めないので、Notta と同じく「話者の発言ターン」にまとめてから組む。
    # 区切りは、話者が変わったとき／無音が空いたとき／ブロックが長くなりすぎたとき。
    segments = group_into_turns(data.get("segments", []))
    print(f"[全文PDF] {len(data.get('segments', []))} セグメント -> {len(segments)} 発言ブロック")

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    tw = fitz.TextWriter(page.rect)
    y = MT
    wmap = []           # 単語 -> ページ・矩形・時刻
    right = PAGE_W - MR

    def flush_and_newpage():
        nonlocal page, tw, y
        tw.write_text(page)
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        tw = fitz.TextWriter(page.rect)
        y = MT

    for seg in segments:
        words = seg["words"]
        # ブロックが1行も入らないなら改ページ（ヘッダだけ置き去りにしない）
        if y + HDR_FS + HDR_GAP + LH > PAGE_H - MB:
            flush_and_newpage()

        spk = seg.get("speaker")
        spk_no = spk.split("_")[-1].lstrip("0") if spk else None
        head = fmt_hms(seg["start"]) + (f" Speaker {spk_no}" if spk_no else "")
        tw.append(fitz.Point(ML, y + HDR_FS), head, font=font, fontsize=HDR_FS)
        y += HDR_FS + HDR_GAP

        x = ML
        for w in words:
            tok = w.get("word", "")
            if not tok:
                continue
            adv = font.text_length(tok, fontsize=FS)
            if x + adv > right:                       # 行を折り返す
                y += LH
                x = ML
                if y + LH > PAGE_H - MB:              # ページを送る
                    flush_and_newpage()
            tw.append(fitz.Point(x, y + FS), tok, font=font, fontsize=FS)
            wmap.append({
                "start": round(float(w["start"]), 3),
                "end": round(float(w.get("end", w["start"])), 3),
                "word": tok,
                "page": doc.page_count - 1,
                "rect": [round(x, 2), round(y, 2), round(x + adv, 2), round(y + FS + 2, 2)],
            })
            x += adv
        y += LH + BLOCK_GAP
        if y + LH > PAGE_H - MB:
            flush_and_newpage()

    tw.write_text(page)

    out_pdf = idpaths.save(base, f"{idv}_全文.pdf")
    out_map = idpaths.save(base, "transcript_pdf_map.json")
    npages = doc.page_count
    doc.save(out_pdf, deflate=True)
    doc.close()
    with open(out_map, "w", encoding="utf-8") as f:
        json.dump({"page_w": PAGE_W, "page_h": PAGE_H, "words": wmap}, f, ensure_ascii=False)

    print(f"[全文PDF] {len(wmap)} 単語 / {npages} ページ -> {out_pdf}")
    print(f"[全文PDF] 座標表 -> {out_map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
