#!/usr/bin/env python3
"""Notta の PDF から話者ブロックを抜き出し、<ID>-transcript.txt を作る。

Notta のテキストエクスポートが無い（PDFしか無い）音源用。
assign_speakers.py が読む "HH:MM:SS Speaker N" 形式の txt を data/<ID>/ 直下に書く。
ヘッダ行は「話者 N M:SS」と「話者 N H:MM:SS」の両方に対応（実測: 2026-08-07、全6ID共通）。

usage: python scripts/notta_pdf_to_txt.py <ID>
"""
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

HDR = re.compile(r"^話者 (\d+) (?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")


def main(idv):
    base = ROOT / "data" / idv
    pdfs = [p for p in base.glob("*.pdf")
            if "notta" in p.name.lower() and "校正" not in p.name]
    if not pdfs:
        sys.exit(f"[notta_pdf] {base} に Notta の PDF がありません")
    pdf = sorted(pdfs, key=lambda p: -p.stat().st_size)[0]

    import fitz
    doc = fitz.open(pdf)
    out, cur = [], None
    for i in range(doc.page_count):
        for line in doc[i].get_text().splitlines():
            line = line.strip()
            m = HDR.match(line)
            if m:
                if cur and cur["t"].strip():
                    out.append(cur["h"] + "\n" + cur["t"].strip())
                n, h, mm, ss = m.groups()
                sec = (int(h) if h else 0) * 3600 + int(mm) * 60 + int(ss)
                cur = {"h": f"{sec//3600:02d}:{sec%3600//60:02d}:{sec%60:02d} Speaker {n}",
                       "t": ""}
            elif cur is not None and line:
                cur["t"] += line
    if cur and cur["t"].strip():
        out.append(cur["h"] + "\n" + cur["t"].strip())
    if not out:
        sys.exit(f"[notta_pdf] {pdf.name} から話者ブロックを検出できませんでした")

    dst = base / f"{idv}-transcript.txt"
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    import collections
    c = collections.Counter(b.split(" Speaker ")[1].split("\n")[0] for b in out)
    print(f"[notta_pdf] {pdf.name} -> {dst.name}: {len(out)} ブロック / 話者 {dict(sorted(c.items()))}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python scripts/notta_pdf_to_txt.py <ID>")
    main(sys.argv[1])
