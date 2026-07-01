#!/usr/bin/env python3
"""
校正用PDF生成（手順書「切り出す境界を決める」の再現）

Notta が出した「全文PDF（ファイル名に transcript を含む）」を土台にし、
その上にペンで描き込むように注釈を重ねる:
  - 赤  … AIが出した切り出し案（本命候補）。区間を縦帯でハイライトし、
          開始行に「▼N位「タイトル」尺」、終了行に「▲N位「タイトル」(END)」、
          各案のセリフ(highlight_quotes)は開始マーカー直下に赤の箇条書き＋本文中を「」で直接マーク。目次ページにはGPT出力を黒字で掲載
  - 橙  … AIが出した補助候補（細かい/短尺/番外）。同様だが控えめ
  - 青  … チャットでの人間の確定・修正（segments.json があれば反映）。
          確定区間と、除外（✂）箇所を青で重ねる

要約PDF（ファイル名に 要約 を含む）はそのまま参照用。書き込みは全文PDF側に行う。

位置決めは秒ではなくテキストで行う:
  候補の start_sec / end_sec を HH:MM:SS に変換し、
  全文PDF中の「HH:MM:SS Speaker N」というタイムスタンプ行を検索して、
  その行の座標に注釈を重ねる。タイムスタンプの細かなズレは最近傍の行に丸める。

入力（data/<ID>/）:
  - *transcript*.pdf      Notta全文PDF（必須・土台）
  - candidates_raw.json   AI候補（赤・橙）。suggest.py が出す
  - segments.json         （任意）チャット確定分（青）

出力:
  - data/<ID>/<ID>_校正用.pdf

使い方:
  python scripts/make_review_pdf.py <ID>
"""
import os, sys, json, re, pathlib

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


def hms(s):
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def find_transcript_pdf(outdir):
    cands = [p for p in outdir.glob("*.pdf")
             if "transcript" in p.name.lower() and "校正" not in p.name]
    if not cands:
        raise FileNotFoundError(
            f"{outdir} に全文PDF（ファイル名に 'transcript' を含む .pdf）が見つかりません")
    return sorted(cands, key=lambda p: -p.stat().st_size)[0]


def build_ts_index(doc):
    """全ページから 'HH:MM:SS Speaker N' のタイムスタンプ行を集め、
    [(sec, page_no, fitz.Rect), ...] を返す。"""
    import fitz
    ts_re = re.compile(r'^(\d{1,2}):(\d{2}):(\d{2})\s+Speaker')
    index = []
    for pno in range(doc.page_count):
        for b in doc[pno].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                txt = "".join(s["text"] for s in l["spans"]).strip()
                m = ts_re.match(txt)
                if m:
                    sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                    index.append((sec, pno, fitz.Rect(l["bbox"])))
    index.sort(key=lambda r: r[0])
    return index


def nearest(index, sec):
    return min(index, key=lambda r: abs(r[0] - sec))


def main():
    import fitz  # PyMuPDF

    RED        = (0.85, 0.10, 0.10)
    RED_FILL   = (1.0, 0.55, 0.55)
    ORANGE     = (0.90, 0.45, 0.00)
    ORANGE_FILL= (1.0, 0.80, 0.45)
    BLUE       = (0.10, 0.25, 0.85)
    CUT        = (0.80, 0.0, 0.30)   # カット推奨（濃い赤紫）

    # ---- 日本語フォント（実フォントファイルを読み込む。内蔵 'japan' は幅計算が壊れる）----
    FONT = "jpembed"
    font_candidates = [
        os.environ.get("PODCAST_PDF_FONT", ""),
        "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        os.path.expanduser("~/Library/Fonts/NotoSansCJKjp-Regular.otf"),
        "/Library/Fonts/NotoSansCJKjp-Regular.otf",
        os.path.expanduser("~/Library/Fonts/NotoSansJP-Regular.otf"),
        os.path.expanduser("~/Library/Fonts/NotoSansJP-Regular.ttf"),
        os.path.expanduser("~/Library/Fonts/ipaexg.ttf"),
        "/Library/Fonts/ipaexg.ttf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf",
    ]
    FONT_FILE = next((fp for fp in font_candidates if fp and os.path.exists(fp)), None)
    if FONT_FILE is None:
        FONT = "japan"
        print("[review_pdf] 注意: 実フォントが見つからず内蔵フォントで描画します。"
              "PODCAST_PDF_FONT に和文フォントのパスを指定すると見た目が安定します。")
    jpfont = fitz.Font(fontfile=FONT_FILE) if FONT_FILE else fitz.Font("japan")

    paths = load_conf("config/paths.conf")
    ID = sys.argv[1]
    outdir = pathlib.Path(paths["PODCAST_ROOT"]) / ID

    src_pdf = find_transcript_pdf(outdir)
    doc = fitz.open(src_pdf)
    index = build_ts_index(doc)
    if not index:
        raise RuntimeError("全文PDFからタイムスタンプ行を検出できませんでした。"
                           "形式が想定（HH:MM:SS Speaker N）と異なる可能性があります。")

    cand_path = outdir / "candidates_raw.json"
    candidates = json.loads(cand_path.read_text(encoding="utf-8")) if cand_path.exists() else []
    seg_path = outdir / "segments.json"
    segments = []
    if seg_path.exists():
        segments = json.loads(seg_path.read_text(encoding="utf-8")).get("segments", [])

    # 候補外ゾーン（グレーで伏せる）: suggest.py が exclude_zones.json に出す
    exclude_zones = []
    ez_path = outdir / "exclude_zones.json"
    if ez_path.exists():
        exclude_zones = json.loads(ez_path.read_text(encoding="utf-8")).get("exclude_zones", [])

    PAGE_W = doc[0].rect.width

    # ---- フォント登録 & 描画ヘルパ ----
    _font_pages = set()
    def ensure_font(page):
        if FONT_FILE and page.number not in _font_pages:
            page.insert_font(fontname=FONT, fontfile=FONT_FILE)
            _font_pages.add(page.number)

    def T(page, x, y, text, fs, color):
        ensure_font(page)
        page.insert_text(fitz.Point(x, y), text, fontsize=fs, fontname=FONT, color=color)

    def wrap_lines(text, fs, max_w):
        out, cur = [], ""
        for ch in text:
            if ch == "\n":
                out.append(cur); cur = ""; continue
            if jpfont.text_length(cur + ch, fs) > max_w:
                out.append(cur); cur = ch
            else:
                cur += ch
        if cur:
            out.append(cur)
        return out

    def block(page, x, top, max_w, text, fs, color, lh=1.32):
        """折り返して描画し、消費後の y を返す（baseline管理）。"""
        ensure_font(page)
        yy = top
        for ln in wrap_lines(text, fs, max_w):
            page.insert_text(fitz.Point(x, yy + fs), ln, fontsize=fs, fontname=FONT, color=color)
            yy += fs * lh
        return yy

    # ---- 帯・罫線・マーカー ----
    def draw_band(page, y0, y1, fill):
        page.draw_rect(fitz.Rect(46, y0, PAGE_W - 46, y1), color=None,
                       fill=fill, fill_opacity=0.10, width=0)

    def band_range(sp, srect, ep, erect, fill):
        if sp == ep:
            draw_band(doc[sp], srect.y0 - 2, erect.y1 + 2, fill)
        else:
            draw_band(doc[sp], srect.y0 - 2, doc[sp].rect.height - 38, fill)
            for mid in range(sp + 1, ep):
                draw_band(doc[mid], 48, doc[mid].rect.height - 38, fill)
            draw_band(doc[ep], 48, erect.y1 + 2, fill)

    def left_rule(sp, srect, ep, erect, color):
        def vline(page, y0, y1):
            page.draw_line(fitz.Point(44, y0), fitz.Point(44, y1), color=color, width=1.8)
        if sp == ep:
            vline(doc[sp], srect.y0 - 2, erect.y1 + 2)
        else:
            vline(doc[sp], srect.y0 - 2, doc[sp].rect.height - 38)
            for mid in range(sp + 1, ep):
                vline(doc[mid], 48, doc[mid].rect.height - 38)
            vline(doc[ep], 48, erect.y1 + 2)

    def marker_start(page, rect, text, color, fs=12):
        ensure_font(page)
        w = jpfont.text_length(text, fs)
        page.draw_rect(fitz.Rect(46, rect.y0 - fs - 5, 46 + w + 6, rect.y0 - 1),
                       color=None, fill=(1, 1, 1), fill_opacity=0.9, width=0)
        page.draw_line(fitz.Point(40, rect.y0), fitz.Point(46, rect.y0), color=color, width=2.2)
        page.insert_text(fitz.Point(47, rect.y0 - 4), text, fontsize=fs, fontname=FONT, color=color)

    def marker_end(page, rect, text, color, fs=11):
        ensure_font(page)
        w = jpfont.text_length(text, fs)
        # 終了行の上の余白に（本文に被らないよう不透明白下地）
        page.draw_rect(fitz.Rect(46, rect.y0 - fs - 5, 46 + w + 6, rect.y0 - 1),
                       color=None, fill=(1, 1, 1), fill_opacity=0.9, width=0)
        page.draw_line(fitz.Point(40, rect.y0), fitz.Point(46, rect.y0), color=color, width=2.2)
        page.insert_text(fitz.Point(47, rect.y0 - 4), text, fontsize=fs, fontname=FONT, color=color)

    def title_of(c):
        """統一スキーマ title を優先。旧 title_short/mid/theme や 2-1旧形式もフォールバック。"""
        t = (c.get("title") or c.get("title_short") or c.get("title_mid")
             or c.get("theme"))
        if t:
            return t
        tc = c.get("title_candidates")
        if isinstance(tc, list) and tc:
            return str(tc[0]).strip()
        s = c.get("summary") or ""
        return s[:24] if s else ""

    def dur_of(c):
        d = c.get("duration_label")
        if d:
            return d
        ds = c.get("duration_sec")
        if isinstance(ds, (int, float)) and ds > 0:
            return f"[{int(ds)//60}分{int(ds)%60}秒]"
        st, en = c.get("start_sec"), c.get("end_sec")
        if st is not None and en is not None:
            s = int(en) - int(st)
            return f"[{s//60}分{s%60}秒]"
        return ""

    def quotes_of(c):
        """セグメントを思い出すための象徴的セリフ（5個前後）。
        統一スキーマ highlight_quotes を優先。"""
        q = c.get("highlight_quotes")
        if isinstance(q, list) and q:
            return [str(x).strip() for x in q if str(x).strip()][:6]
        s = c.get("概要") or c.get("caution") or ""
        return [s] if s else []

    def review_of(c):
        """レビュー（旧 reason）。なぜ切り出したか・面白さ・公開評価。"""
        return (c.get("review") or c.get("reason") or "").strip()

    def summary_of(c):
        """要約（内容のまとめ）。"""
        return (c.get("summary") or c.get("概要") or "").strip()

    HILITE = (0.85, 0.10, 0.10)   # ハイライト＝はっきりした赤（カットの赤紫とは別）

    def highlight_quotes_in_body(sp_page_no, ep_page_no, quotes):
        """ハイライトとなるセリフを、本文中の該当箇所で直接「」で囲み赤の下線を引く。
        PDFの行折り返しで全文がヒットしないことがあるため、短い断片に切り詰めて再試行する。"""
        if not quotes:
            return
        lo = max(0, sp_page_no - 1)
        hi = min(doc.page_count - 1, ep_page_no + 1)
        for q in quotes:
            q = str(q).strip()
            if len(q) < 6:
                continue
            # 試す断片: 全体 → 先頭28 → 先頭18 → 先頭12（行跨ぎ対策）
            candidates_n = [q[:40], q[:28], q[:18], q[:12]]
            done = False
            for needle in candidates_n:
                if len(needle) < 6:
                    continue
                for pno in range(lo, hi + 1):
                    rects = doc[pno].search_for(needle)
                    if not rects:
                        continue
                    r = rects[0]
                    doc[pno].draw_line(fitz.Point(r.x0, r.y1 + 1.2),
                                       fitz.Point(r.x1, r.y1 + 1.2), color=HILITE, width=1.8)
                    T(doc[pno], r.x0 - 9, r.y1 - 1, "「", 11, HILITE)
                    T(doc[pno], r.x1 + 1, r.y1 - 1, "」", 11, HILITE)
                    done = True
                    break
                if done:
                    break

    GRAY = (0.5, 0.5, 0.5)
    GRAY_FILL = (0.6, 0.6, 0.6)

    def gray_zone(st, en, reason):
        """要件3: 候補外の区間をグレー半透明で伏せ、理由を大きく重ねる。"""
        ns = nearest(index, st); ne = nearest(index, en)
        sp, srect = ns[1], ns[2]; ep, erect = ne[1], ne[2]
        # グレー帯（やや濃いめ＝はっきり伏せる）
        def band(page, y0, y1):
            page.draw_rect(fitz.Rect(46, y0, PAGE_W - 46, y1), color=None,
                           fill=GRAY_FILL, fill_opacity=0.38, width=0)
        if sp == ep:
            band(doc[sp], srect.y0 - 2, erect.y1 + 2)
        else:
            band(doc[sp], srect.y0 - 2, doc[sp].rect.height - 38)
            for mid in range(sp + 1, ep):
                band(doc[mid], 48, doc[mid].rect.height - 38)
            band(doc[ep], 48, erect.y1 + 2)
        # ラベル（はっきり読めるよう白下地＋濃いグレー文字）
        lbl = f"⬛ 候補外（チェック不要）: {reason}"
        ls = wrap_lines(lbl, 10.5, PAGE_W - 110)
        yy = srect.y0 + 2
        for ln in ls:
            w = jpfont.text_length(ln, 10.5)
            doc[sp].draw_rect(fitz.Rect(50, yy - 1, 50 + w + 6, yy + 14),
                              color=None, fill=(1, 1, 1), fill_opacity=0.85, width=0)
            T(doc[sp], 53, yy + 10.5, ln, 10.5, (0.25, 0.25, 0.25))
            yy += 15

    def underline_cut(c_st, c_en, cut):
        """要件2: カット推奨区間を強く目立たせる。
        該当文に黄色ハイライト＋太い濃赤下線＋「」、直下に大きい理由ラベル。"""
        st = cut.get("start_sec", c_st)
        reason = cut.get("reason", "")
        quote = (cut.get("quote") or "").strip()
        ns = nearest(index, st)
        sp = ns[1]
        anchor = ns[2]
        page = doc[sp]
        if quote:
            q = quote[:40]
            for pg in [sp, min(sp + 1, doc.page_count - 1)]:
                rects = doc[pg].search_for(q)
                if rects:
                    for r in rects:
                        # 該当文に黄色ハイライト（薄帯の上でも目立つ）
                        doc[pg].draw_rect(fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1),
                                          color=None, fill=(1.0, 0.92, 0.0), fill_opacity=0.45, width=0)
                        # 太い濃赤の下線（二重線で強調）
                        doc[pg].draw_line(fitz.Point(r.x0, r.y1 + 1.2),
                                          fitz.Point(r.x1, r.y1 + 1.2), color=CUT, width=2.6)
                        doc[pg].draw_line(fitz.Point(r.x0, r.y1 + 3.4),
                                          fitz.Point(r.x1, r.y1 + 3.4), color=CUT, width=1.0)
                        # 「」を大きめに
                        T(doc[pg], r.x0 - 10, r.y1 - 1, "「", 12, CUT)
                        T(doc[pg], r.x1 + 1, r.y1 - 1, "」", 12, CUT)
                    page = doc[pg]; anchor = rects[-1]
                    break
        # 理由ラベル: 行間に収まるよう小さめ・縦パディング詰め・少し上げる
        lbl = f"✂ カット推奨: {reason}"
        fs = 8
        ls = wrap_lines(lbl, fs, PAGE_W - 130)
        yy = anchor.y1 + 1.5
        for ln in ls:
            w = jpfont.text_length(ln, fs)
            page.draw_rect(fitz.Rect(56, yy - 0.5, 56 + w + 8, yy + fs + 1.5),
                           color=CUT, fill=CUT, fill_opacity=1.0, width=0)
            T(page, 60, yy + fs - 0.3, ln, fs, (1, 1, 1))
            yy += fs + 2.5

    # ---- 候補の分類（rank 1〜5=本命、6以降=補助。スキーマは統一済み）----
    mains, helpers = [], []
    for c in candidates:
        if c.get("start_sec") is None or c.get("end_sec") is None:
            continue
        try:
            r = int(c.get("rank", 999))
        except (TypeError, ValueError):
            r = 999
        (mains if r <= 5 else helpers).append(c)

    # ---- 表紙ページ ----
    h = doc[0].rect.height
    cover = doc.new_page(0, width=PAGE_W, height=h)
    y = 56
    T(cover, 48, y, f"{ID}　校正用", 20, (0, 0, 0)); y += 30
    T(cover, 48, y, "Notta全文PDFの上に、AIの切り出し案を重ねた校正用です。", 10, (0, 0, 0)); y += 17
    for txt, col in [("赤＝AI本命候補（区間を薄い帯でハイライト＋▼▲マーカー）", RED),
                     ("橙＝AI補助候補（短尺・番外・細かいもの。左罫線＋▼▲）", ORANGE),
                     ("✂ 濃赤＝カット推奨（該当文に下線＋「」、理由を併記）", CUT),
                     ("⬛ グレー＝候補外（チェック不要。理由を併記）", (0.45, 0.45, 0.45)),
                     ("青＝チャットでの確定・修正（あれば反映）。除外は ✂", BLUE)]:
        T(cover, 48, y, txt, 9.5, col); y += 14
    y += 10
    BLACK = (0.12, 0.12, 0.12)
    GREYTX = (0.30, 0.30, 0.30)
    LINE = (0.6, 0.6, 0.6)

    # ---- GPT出力のMarkdown表をそのまま再現（順位/切り出し/尺/テーマ/推奨度）----
    T(cover, 48, y, "■ 切り出し候補（要約表）", 12, BLACK); y += 18
    cols = [("順位", 40), ("切り出し", 100), ("尺", 50), ("テーマ", 188), ("推奨度", 0)]
    x0 = 48
    right = PAGE_W - 46
    # 列のx座標を算出（最後の推奨度は残り幅）
    xs = [x0]
    for _, w in cols[:-1]:
        xs.append(xs[-1] + w)
    # cover はページオーバー時に2枚目以降へ続ける（順位表に6位以下も全部出す）
    cover_pages = [cover]
    PAGE_H = h
    def row(cells, yy, header=False, h=None):
        nonlocal cover
        fs = 8.5
        wrapped_cells = []
        for i, (txt, _) in enumerate(zip(cells, cols)):
            cw = (cols[i][1] if cols[i][1] else (right - xs[i])) - 6
            wrapped_cells.append(wrap_lines(str(cells[i]), fs, cw))
        rows_n = max(len(w) for w in wrapped_cells)
        rh = h or (rows_n * fs * 1.32 + 6)
        # ページ下端を超えるなら新ページへ
        if yy + rh > PAGE_H - 40:
            cover = doc.new_page(cover_pages[-1].number + 1, width=PAGE_W, height=PAGE_H)
            cover_pages.append(cover)
            yy = 48
            # 続きヘッダ
            cover.draw_rect(fitz.Rect(x0, yy, right, yy + (fs*1.32+6)), color=LINE,
                            fill=(0.95, 0.95, 0.95), width=0.6)
            for xx in xs[1:]:
                cover.draw_line(fitz.Point(xx, yy), fitz.Point(xx, yy + (fs*1.32+6)), color=LINE, width=0.5)
            for i, (hc, _) in enumerate(cols):
                T(cover, xs[i] + 3, yy + 4 + fs, hc, fs, BLACK)
            yy += fs*1.32 + 6
        cover.draw_rect(fitz.Rect(x0, yy, right, yy + rh), color=LINE,
                        fill=(0.95, 0.95, 0.95) if header else None, width=0.6)
        for xx in xs[1:]:
            cover.draw_line(fitz.Point(xx, yy), fitz.Point(xx, yy + rh), color=LINE, width=0.5)
        for i, lns in enumerate(wrapped_cells):
            ty = yy + 4
            for ln in lns:
                T(cover, xs[i] + 3, ty + fs, ln, fs, BLACK)
                ty += fs * 1.32
        return yy + rh
    # ヘッダ
    y = row([c[0] for c in cols], y, header=True)
    # 各案
    def recommend_of(c):
        return (c.get("推奨度") or c.get("recommend") or "").strip()
    # 順位表は本命5＋補助も全部出す（6位以下は必要なら次ページへ続く）
    for c in (mains + helpers):
        rk = f"{c.get('rank','?')}位"
        cut = f"{hms(c['start_sec'])}〜{hms(c['end_sec'])}"
        dur = dur_of(c)
        theme = title_of(c)
        rec = recommend_of(c)
        y = row([rk, cut, dur, theme, rec], y)
    y += 14
    # コメント類は1枚目に戻して書く（表が複数ページに渡った場合でも本命の解説は最終ページ続きに出す）

    # ---- コメント（各案の 要約＋レビュー を黒字で）----
    T(cover, 48, y, "■ 各案のコメント", 12, BLACK); y += 18
    for c in mains:
        rk = c.get("rank", "?")
        summ = summary_of(c)
        rev = review_of(c)
        if summ:
            y = block(cover, 50, y, PAGE_W - 50 - 46, f"{rk}位【要約】{summ}", 9, BLACK) + 3
        if rev:
            y = block(cover, 50, y, PAGE_W - 50 - 46,
                      ("　【レビュー】" if summ else f"{rk}位【レビュー】") + rev, 9, GREYTX) + 6
        if not summ and not rev:
            continue
    if helpers:
        y += 6
        T(cover, 48, y, "■ 補助候補（短尺・番外）", 11, BLACK); y += 17
        for c in helpers:
            ttl = title_of(c)
            dur = dur_of(c)
            line = f"{c.get('rank','?')}位　{ttl}　{hms(c['start_sec'])}〜{hms(c['end_sec'])} {dur}".rstrip()
            y = block(cover, 54, y, PAGE_W - 54 - 46, line, 9.5, BLACK) + 2
            rev = review_of(c) or summary_of(c)
            if rev:
                y = block(cover, 66, y, PAGE_W - 66 - 46, rev, 8.5, GREYTX) + 5
            else:
                y += 3
    if segments:
        y += 6
        T(cover, 48, y, "■ チャット確定セグメント", 11, BLUE); y += 16
        for s in segments:
            idx = s.get("index", "?")
            st, en = s.get("start_sec"), s.get("end_sec")
            rng = f"{hms(st)}–{hms(en)}" if (st is not None and en) else ""
            drops = s.get("drops", [])
            dtxt = ("　除外: " + ", ".join(f"{hms(a)}–{hms(b)}" for a, b in drops)) if drops else ""
            T(cover, 54, y, f"確定{idx}: {s.get('title','')}　{rng}{dtxt}", 9, BLUE); y += 13

    # 表紙を入れたので本文ページ番号を +1
    index = [(sec, pno + 1, rect) for (sec, pno, rect) in index]

    # ---- 本文へマーク ----
    def Tbold(page, x, y, text, fs, color):
        """疑似ボールド: 微小オフセットで二重描画して太く見せる（埋め込みフォントが単一ウェイトのため）。"""
        ensure_font(page)
        for dx, dy in ((0, 0), (0.35, 0), (0, 0.35), (0.35, 0.35)):
            page.insert_text(fitz.Point(x + dx, y + dy), text, fontsize=fs, fontname=FONT, color=color)

    def quotes_bullets(page, rect, quotes, color):
        """開始マーカーの『上』に、ハイライトのセリフを箇条書きで。
        本文ページではタイトル/マーカーとの重なりを抑えるため最大3個に絞る
        （全件は表紙・チャット・JSONにある）。"""
        if not quotes:
            return
        quotes = quotes[:3]
        fs = 10
        lh = fs * 1.32
        x0 = 70
        wrapped = []
        for q in quotes:
            q = str(q).strip()
            if not q:
                continue
            lns = wrap_lines("・" + q, fs, PAGE_W - x0 - 46)
            wrapped.append(lns[0])
            for extra in lns[1:]:
                wrapped.append("　" + extra)
        if not wrapped:
            return
        TOP_SAFE = 30          # ページ最上部の安全余白（ここまで上げてよい）
        gap_above_marker = 30  # マーカー直上に大きめの隙間。ハイライトを上へ浮かせ、タイトル/マーカーと被りにくく
        need = len(wrapped) * lh
        bottom = rect.y0 - gap_above_marker
        top = bottom - need
        if top < TOP_SAFE:
            top = TOP_SAFE
        yy = top
        for ln in wrapped:
            Tbold(page, x0, yy + fs, ln, fs, color)
            yy += lh

    def place(rank, title, dur, quotes, st, en, color, fill, mark, style, cuts=None):
        ns = nearest(index, st); ne = nearest(index, en)
        sp, srect = ns[1], ns[2]; ep, erect = ne[1], ne[2]
        if style == "band":
            band_range(sp, srect, ep, erect, fill)
        else:
            left_rule(sp, srect, ep, erect, color)
        if title:
            start_txt = f"▼{rank}位「{title}」 {dur}".rstrip()
            end_txt = f"▲{rank}位「{title}」(END)"
        else:
            start_txt = f"▼{rank}位 {dur}".rstrip()
            end_txt = f"▲{rank}位(END)"
        marker_start(doc[sp], srect, start_txt, color, fs=16 if style == "band" else 13)
        marker_end(doc[ep], erect, end_txt, color, fs=15 if style == "band" else 12)
        # 開始マーカー直下にハイライトを箇条書き（冒頭で掴める）
        if quotes:
            quotes_bullets(doc[sp], srect, quotes, (0.80, 0.10, 0.10))
        # さらに本文中の該当箇所も「」＋赤下線で直接マーク
        if quotes:
            highlight_quotes_in_body(sp, ep, quotes)
        # カット推奨区間（cuts に集約された情報をすべてマーキング）
        for cut in (cuts or []):
            underline_cut(st, en, cut)

    for c in mains:
        place(c.get("rank", "?"), title_of(c),
              dur_of(c), quotes_of(c),
              c["start_sec"], c["end_sec"], RED, RED_FILL, "案", "band",
              cuts=c.get("cuts") or [])
    for c in helpers:
        place(c.get("rank", "?"), title_of(c), dur_of(c), quotes_of(c),
              c["start_sec"], c["end_sec"], ORANGE, ORANGE_FILL, "補", "rule",
              cuts=c.get("cuts") or [])

    # 要件3: 候補外ゾーンをグレーで伏せる（最後に重ねて、はっきり見せる）
    for z in exclude_zones:
        st, en = z.get("start_sec"), z.get("end_sec")
        if st is None or en is None:
            continue
        gray_zone(st, en, z.get("reason", ""))

    for s in segments:
        st, en = s.get("start_sec"), s.get("end_sec")
        if st is None or en is None:
            continue
        ns = nearest(index, st); ne = nearest(index, en)
        idx = s.get("index", "?")
        marker_start(doc[ns[1]], ns[2], f"▼確定{idx}「{s.get('title','')}」", BLUE, fs=14)
        marker_end(doc[ne[1]], ne[2], f"▲確定{idx}「{s.get('title','')}」(END)", BLUE, fs=13)
        for a, b in s.get("drops", []):
            na = nearest(index, a)
            T(doc[na[1]], 47, na[2].y0 - 12, f"✂確定{idx} 除外 {hms(a)}–{hms(b)}", 8, BLUE)

    out_pdf = outdir / f"{ID}_校正用.pdf"
    doc.save(str(out_pdf), garbage=4, deflate=True)
    print(f"[review_pdf] 生成: {out_pdf}")
    print(f"[review_pdf] 土台: {src_pdf.name} / 本命{len(mains)} 補助{len(helpers)} 確定{len(segments)} / フォント: {os.path.basename(FONT_FILE) if FONT_FILE else 'builtin'}")


if __name__ == "__main__":
    main()
