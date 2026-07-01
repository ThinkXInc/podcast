#!/usr/bin/env python3
"""校正用PDFを1ページずつPNG画像に書き出す。

リモートのマシンで動かしていてユーザーが手元でPDFを直接開けない場合に、
Claude Code がこの画像をチャットに貼って見せるためのもの。

出力:
  data/<ID>/preview/p001.png, p002.png, ...

使い方:
  python scripts/preview_pdf.py <ID> [--dpi 130] [--pages 1-5,8] [--only-cover]

Claude Code への想定運用:
  1) suggest.py 実行後にこれを走らせる
  2) まず表紙(p001)＋本命の各ページをチャットに貼る
  3) 「続き（補助/カット/候補外）も出す?」と聞いて、必要なら残りも貼る
"""
import os, sys, json, pathlib, argparse

HERE = pathlib.Path(__file__).resolve().parents[1]


def load_conf(path):
    os.environ["HERE"] = str(HERE)
    d = {}
    for line in (HERE / path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = os.path.expandvars(v.strip().strip('"'))
    return d


def parse_pages(spec, total):
    """'1-5,8,10-' のような指定を 0始まりページ番号の集合に。Noneなら全ページ。"""
    if not spec:
        return list(range(total))
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a else 1
            b = int(b) if b else total
            for n in range(a, b + 1):
                if 1 <= n <= total:
                    out.add(n - 1)
        else:
            n = int(part)
            if 1 <= n <= total:
                out.add(n - 1)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--dpi", type=int, default=130)
    ap.add_argument("--pages", default="", help="例: 1-5,8  （1始まり。未指定で全ページ）")
    ap.add_argument("--only-cover", action="store_true", help="表紙(1ページ目)だけ")
    args = ap.parse_args()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("PyMuPDF が必要です: pip install PyMuPDF")

    paths = load_conf("config/paths.conf")
    outdir = pathlib.Path(paths["PODCAST_ROOT"]) / args.id
    pdf = outdir / f"{args.id}_校正用.pdf"
    if not pdf.exists():
        sys.exit(f"{pdf} がありません。先に make_review_pdf.py を実行してください。")

    doc = fitz.open(pdf)
    total = doc.page_count
    if args.only_cover:
        pages = [0]
    else:
        pages = parse_pages(args.pages, total)

    preview = outdir / "preview"
    preview.mkdir(exist_ok=True)
    # 既存PNGは消してから（古い結果が混ざらないように）
    for old in preview.glob("p*.png"):
        old.unlink()

    written = []
    for pno in pages:
        pix = doc[pno].get_pixmap(dpi=args.dpi)
        fp = preview / f"p{pno + 1:03d}.png"
        pix.save(fp)
        written.append(str(fp))

    print(json.dumps({
        "pdf": str(pdf),
        "total_pages": total,
        "written": written,
        "dir": str(preview),
    }, ensure_ascii=False, indent=2))
    print(f"\n[preview] {len(written)}枚を {preview} に書き出しました。"
          f" Claude Code はこの画像をチャットに貼ってください。")


if __name__ == "__main__":
    main()
