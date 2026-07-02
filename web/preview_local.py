#!/usr/bin/env python3
# web/preview_local.py — mac ローカルで生成物(contents/)を確認するスタンドアロン preview。
#
# 依存ゼロ（Python 標準ライブラリのみ）。本番の uWSGI / nginx / general/base.html には
# 一切依存しない。本番の雛形（templates/page.html, config/uwsgi.ini, nginx/*）は触らない。
#
# 動画がメイン。各動画の下に「切り出し全文」を出し、校正用PDFに近い配色で
# カット済み(確定)/カット推奨(未決)/事実確認/候補外/詰め候補(無音)/象徴的セリフ を
# すべて全文中にインライン表示する。
#
# 起動:  python3 web/preview_local.py        → http://127.0.0.1:8010/
# data:  既定は web/ の1つ上の data/。 環境変数 SITE_DATA_DIR で上書き可。

import os
import re
import json
import html
import mimetypes
import urllib.parse
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.realpath(
    os.environ.get("SITE_DATA_DIR") or os.path.join(os.path.dirname(HERE), "data")
)
PORT = int(os.environ.get("PORT", "8010"))

MEDIA_FILES = [
    ("final.mp4", "字幕あり (final.mp4)"),
    ("video_nosub.mp4", "字幕なし (video_nosub.mp4)"),
    ("audio.m4a", "音声 (audio.m4a)"),
    ("segment.ass", "字幕データ (.ass)"),
]

PAGE_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, "Hiragino Sans", sans-serif; margin: 1.5rem auto;
       max-width: 960px; padding: 0 1rem; line-height: 1.6; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin: 0 0 .2rem; }
a { color: #2563eb; text-decoration: none; } a:hover { text-decoration: underline; }
.crumb { font-size: .85rem; margin-bottom: 1rem; }
.meta { color: #888; font-size: .85rem; }
ul.ids { list-style: none; padding: 0; }
ul.ids li { padding: .55rem 0; border-bottom: 1px solid #ccc4; }

.seg { border: 1px solid #ccc4; border-radius: 12px; padding: 1rem 1.2rem 1.3rem;
       margin-bottom: 2.2rem; }
.seghd { border-left: 5px solid #1d4ed8; padding-left: .7rem; margin-bottom: .8rem; }
.seghd .rank { color:#1d4ed8; font-weight:700; }
video { width: 100%; max-width: 860px; display: block; border-radius: 6px;
        background: #000; margin: .3rem 0 .7rem; }
.dl { font-size: .82rem; margin-bottom: .8rem; } .dl a { margin-right: 1rem; }

/* 要約・レビュー：少し行間をつける */
.box.summary { background:#3b82f611; border-left:3px solid #3b82f6; border-radius:8px;
               padding:.7rem .9rem; margin:.6rem 0; font-size:.9rem; line-height:1.9; }
.box.summary p { margin:.55rem 0; }

/* 本文：行間を詰める */
.transcript { margin-top:1rem; border-top:1px dashed #ccc6; padding-top:.6rem; }
.transcript h3 { font-size:.9rem; margin:.2rem 0 .5rem; }
.tp { margin:.5rem 0; line-height:1.5; }
.ts { color:#94a3b8; font-size:.78rem; font-variant-numeric:tabular-nums;
      display:block; margin-bottom:.02rem; }

.chip { display:inline; font-size:.72rem; font-weight:700; padding:0 .3rem;
        border-radius:4px; margin:0 .2rem; white-space:normal; }
/* カット済み(確定) = 青・取り消し線 */
.r-done { text-decoration:line-through; color:#1d4ed8; background:#1d4ed812;
          text-decoration-thickness:2px; }
.chip-done { background:#1d4ed8; color:#fff; }
/* カット推奨(未決) = 黄ハイライト＋濃赤下線 */
.r-todo { background:#fde04788; border-bottom:2px solid #cc0044; }
.chip-todo { background:#cc0044; color:#fff; }
/* 事実確認 = 橙 */
.r-fact { background:#fed7aa88; border-bottom:2px dotted #ea580c; }
.chip-fact { background:#ea580c; color:#fff; }
/* 候補外 = グレー */
.r-exclude { background:#9ca3af44; color:#6b7280; font-style:italic;
             text-decoration:line-through; }
.chip-exclude { background:#6b7280; color:#fff; }
/* 会話相手の発言 = ティール（基本カット対象） */
.r-spk { background:#5eead444; border-bottom:2px dashed #0d9488; }
.chip-spk { background:#0d9488; color:#fff; }
/* カット例（蓄積リスト） = 濃い赤 */
.r-cutlist { background:#fca5a5aa; border-bottom:2px solid #b91c1c; }
.chip-cutlist { background:#b91c1c; color:#fff; }
/* 象徴的セリフ = ライトブルーのハイライト（下線なし） */
.r-quote { background:#7dd3fc88; border-radius:3px; }
/* 詰め候補(無音) = 紫の点マーカー（本文中に差し込む） */
.chip-trim { background:#7c3aed; color:#fff; font-size:.7rem; }
.chip-trim.muted { background:#a78bfa; }

.legend { font-size:.82rem; background:#8881; border-radius:8px; padding:.6rem .8rem;
          margin:.6rem 0 1.2rem; line-height:2; }
.legend span.sw { padding:0 .3rem; border-radius:4px; margin-right:.15rem; font-weight:700; }
.note { background:#f59e0b22; border-left:3px solid #f59e0b; padding:.5rem .8rem;
        border-radius:4px; font-size:.85rem; margin:.6rem 0; }
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


def fmt_time(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def page(title, body):
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title)}</title><style>{PAGE_CSS}</style></head>"
        f"<body>{body}</body></html>"
    ).encode("utf-8")


# ---------- データ読み込み ----------
def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def list_ids():
    out = []
    if not os.path.isdir(DATA_DIR):
        return out
    for name in sorted(os.listdir(DATA_DIR)):
        if os.path.isdir(os.path.join(DATA_DIR, name, "contents")):
            out.append(name)
    return out


def list_segments(idv):
    cdir = os.path.join(DATA_DIR, idv, "contents")
    if not os.path.isdir(cdir):
        return []
    return sorted(n for n in os.listdir(cdir) if os.path.isdir(os.path.join(cdir, n)))


def seg_dirname(idv, index, title):
    prefix = f"{index:02d}_"
    for n in list_segments(idv):
        if n.startswith(prefix):
            return n
    return None


def load_id_data(idv):
    base = os.path.join(DATA_DIR, idv)
    segments = _load_json(os.path.join(base, "segments.json"), {}).get("segments", [])
    cands = _load_json(os.path.join(base, "candidates_raw.json"), [])
    cand_by_title = {c.get("title"): c for c in cands}
    sil = _load_json(os.path.join(base, "silences.json"), {})
    sil_by_index = {s.get("index"): s for s in sil.get("segments", [])}
    ex = _load_json(os.path.join(base, "exclude_zones.json"), {})
    tr = _load_json(os.path.join(base, "transcript.json"), {})
    # カット候補リストは ID ごと（data/<ID>/cutlist.json）。CUTLIST 環境変数で上書き可。
    cutlist_path = os.environ.get("CUTLIST") or os.path.join(base, "cutlist.json")
    cutlist = _load_json(cutlist_path, {"speakers": [], "manual": []})
    return {
        "segments": segments,
        "cand_by_title": cand_by_title,
        "sil_by_index": sil_by_index,
        "sil_meta": sil,
        "exclude_zones": ex.get("exclude_zones", []),
        "fact_checks": ex.get("fact_checks", []),
        "tsegments": tr.get("segments", []),
        "cut_speakers": cutlist.get("speakers", []),
        "cut_manual": cutlist.get("manual", []),
    }


def media_url(idv, seg, fname):
    return "/media?p=" + urllib.parse.quote(f"{idv}/contents/{seg}/{fname}")


def trim_applied(idv, segments):
    base = os.path.join(DATA_DIR, idv)
    if os.path.isfile(os.path.join(base, "trim_plan.json")):
        return True
    for sg in segments:
        d = seg_dirname(idv, sg.get("index"), sg.get("title"))
        if d and os.path.isfile(os.path.join(base, "contents", d, "final_orig.mp4")):
            return True
    return False


# ---------- 区間(region)計算 ----------
def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def build_regions(sg, cand, fact_checks, exclude_zones, cut_speakers=None, cut_manual=None):
    """本文に重ねる時間区間を優先度付きで返す（元音源タイムライン）。
    優先度: done(7) > spk(6) > cutlist(6) > todo(4) > fact(3) > quote(2) > exclude(1)。"""
    s, e = sg["start_sec"], sg["end_sec"]
    idx = sg.get("index")
    drops = sg.get("drops") or []
    cand_cuts = (cand or {}).get("cuts") or []
    regions = []

    # 会話相手の発言（Notta話者。基本カット対象）
    spk_blocks = [b for b in (cut_speakers or []) if b.get("index") == idx]
    for b in spk_blocks:
        if _overlap(b["start"], b["end"], s, e) <= 0:
            continue
        regions.append({"s": max(b["start"], s), "e": min(b["end"], e), "kind": "spk",
                        "prio": 6, "label": f"🗣 会話相手(Sp{b.get('spk','?')}) カット対象",
                        "reason": ""})

    # 手動カット例（ユーザー指示で蓄積）
    man = [m for m in (cut_manual or []) if m.get("index") == idx]
    for m in man:
        if _overlap(m["start"], m["end"], s, e) <= 0:
            continue
        regions.append({"s": max(m["start"], s), "e": min(m["end"], e), "kind": "cutlist",
                        "prio": 6, "label": f"✂ カット例({m.get('category','')})",
                        "reason": m.get("reason", "")})

    for d0, d1 in drops:
        reason = ""
        for c in cand_cuts:
            if _overlap(d0, d1, c["start_sec"], c["end_sec"]) > 0:
                reason = c.get("reason", "")
                break
        regions.append({"s": max(d0, s), "e": min(d1, e), "kind": "done",
                        "prio": 7, "label": "✂ カット済み(確定)", "reason": reason})

    todo = []
    for c in cand_cuts:
        cs, ce = c["start_sec"], c["end_sec"]
        if _overlap(cs, ce, s, e) <= 0:
            continue
        if any(_overlap(cs, ce, d0, d1) >= 0.5 * (ce - cs) for d0, d1 in drops):
            continue
        regions.append({"s": max(cs, s), "e": min(ce, e), "kind": "todo", "prio": 4,
                        "label": "✂ カット推奨(未決)", "reason": c.get("reason", "")})
        todo.append(c)

    facts = []
    for fc in fact_checks:
        if _overlap(fc["start_sec"], fc["end_sec"], s, e) <= 0:
            continue
        regions.append({"s": max(fc["start_sec"], s), "e": min(fc["end_sec"], e),
                        "kind": "fact", "prio": 3, "label": "⚠ 事実確認",
                        "reason": fc.get("issue", "")})
        facts.append(fc)

    for ez in exclude_zones:
        if _overlap(ez["start_sec"], ez["end_sec"], s, e) <= 0:
            continue
        regions.append({"s": max(ez["start_sec"], s), "e": min(ez["end_sec"], e),
                        "kind": "exclude", "prio": 1, "label": "⬛ 候補外",
                        "reason": ez.get("reason", "")})

    return regions, todo, facts


def region_for(mid, regions):
    best = None
    for r in regions:
        if r["s"] <= mid < r["e"] and (best is None or r["prio"] > best["prio"]):
            best = r
    return best


# ---------- 単語モデル（インライン差し込みの土台） ----------
_PUNCT = set(" 　、。，．・…！？!?「」『』（）()［］[]〈〉《》\"'\n\t")


def _norm(s):
    """正規化文字列と、正規化index→元index の対応表。"""
    out, imap = [], []
    for i, ch in enumerate(s):
        if ch in _PUNCT:
            continue
        out.append(ch)
        imap.append(i)
    return "".join(out), imap


def build_word_model(tsegments, s, e):
    """[s,e] の単語を段落構造付きで集める。
    返り値: paras=[{ts, words:[gidx,...]}], toks[gidx], gmid[gidx](中点時刻),
            raw(全単語連結), char_gidx(各文字→gidx)"""
    paras, toks, gmid = [], [], []
    char_gidx, raw_parts = [], []
    for tseg in tsegments:
        ts0, ts1 = tseg.get("start"), tseg.get("end")
        if ts0 is None or ts1 is None or _overlap(ts0, ts1, s, e) <= 0:
            continue
        words = tseg.get("words") or []
        pw = []
        for w in words:
            wt = w.get("start")
            if wt is None or not (s <= wt < e):
                continue
            tok = w.get("word", "")
            gidx = len(toks)
            toks.append(tok)
            gmid.append((wt + w.get("end", wt)) / 2)
            for _ in tok:
                char_gidx.append(gidx)
            raw_parts.append(tok)
            pw.append(gidx)
        if not pw:
            txt = (tseg.get("text") or "").strip()
            if txt:
                paras.append({"ts": max(ts0, s), "words": None, "text": txt})
            continue
        paras.append({"ts": max(ts0, s), "words": pw, "text": None})
    return paras, toks, gmid, "".join(raw_parts), char_gidx


def assign_regions(toks, gmid, regions):
    """各 gidx に時間ベースの region を割り当て（無ければ None）。"""
    per = [None] * len(toks)
    for g in range(len(toks)):
        per[g] = region_for(gmid[g], regions)
    return per


def overlay_quotes(per, raw, char_gidx, quotes):
    """象徴的セリフを本文に重ねる。GPTのセリフはASRと表記が微妙に違うため、
    最長共通部分文字列をアンカーにして元文長ぶんを重ねる（一致率0.6以上のみ採用）。"""
    norm, imap = _norm(raw)
    quote_region = {"kind": "quote", "prio": 2, "label": "", "reason": ""}
    for q in quotes or []:
        qn, _ = _norm(q)
        if len(qn) < 6 or not norm:
            continue
        sm = SequenceMatcher(None, norm, qn, autojunk=False)
        a = sm.find_longest_match(0, len(norm), 0, len(qn))
        if a.size < 6:
            continue
        astart = max(0, a.a - a.b)
        aend = min(len(norm), astart + len(qn))
        if aend <= astart:
            continue
        if SequenceMatcher(None, norm[astart:aend], qn, autojunk=False).ratio() < 0.6:
            continue
        c0, c1 = imap[astart], imap[aend - 1]
        for c in range(c0, c1 + 1):
            if c < len(char_gidx):
                g = char_gidx[c]
                if per[g] is None:  # cut/fact/exclude を上書きしない
                    per[g] = quote_region


def locate_trims(raw, char_gidx, gaps):
    """詰め候補ギャップを before+after のマッチで単語境界に割り付ける。
    返り値: dict gidx -> [chip_html,...]（その単語の直前に差し込む）"""
    ins = {}
    for g in gaps:
        before = g.get("before", "")
        after = g.get("after", "")
        needle = before + after
        pos = -1
        if len(before) >= 3 and len(after) >= 3:
            pos = raw.find(needle)
        if pos < 0:
            continue
        boundary = pos + len(before)
        if boundary >= len(char_gidx):
            continue
        gidx = char_gidx[boundary]
        flag = g.get("flag", "")
        muted = " muted" if flag != "review" else ""
        lbl = "⏱ 詰め候補" if flag == "review" else "⏱ 空白(取りこぼし疑い)"
        chip = (f"<span class='chip chip-trim{muted}'>{lbl} "
                f"{g.get('duration', 0):.1f}秒</span>")
        ins.setdefault(gidx, []).append(chip)
    return ins


def render_transcript(tsegments, s, e, regions, quotes, gaps):
    paras, toks, gmid, raw, char_gidx = build_word_model(tsegments, s, e)
    per = assign_regions(toks, gmid, regions)
    overlay_quotes(per, raw, char_gidx, quotes)
    trim_ins = locate_trims(raw, char_gidx, gaps)

    emitted_chip = set()
    out = []
    for para in paras:
        if para["words"] is None:
            out.append(f"<div class='tp'><span class='ts'>{fmt_time(para['ts'])}</span>{esc(para['text'])}</div>")
            continue
        pieces = []
        cur = None
        buf = []

        def flush():
            if not buf:
                return
            text = esc("".join(toks[g] for g in buf))
            if cur is None:
                pieces.append(text)
            else:
                chip = ""
                if cur["kind"] != "quote" and id(cur) not in emitted_chip:
                    emitted_chip.add(id(cur))
                    rs = esc(cur.get("reason", ""))
                    chip = (f"<span class='chip chip-{cur['kind']}'>{esc(cur['label'])}"
                            + (f": {rs}" if rs else "") + "</span>")
                pieces.append(f"{chip}<span class='r-{cur['kind']}'>{text}</span>")
            buf.clear()

        for gidx in para["words"]:
            if gidx in trim_ins:
                flush()
                cur = None
                pieces.extend(trim_ins[gidx])
            r = per[gidx]
            if r is not cur:
                flush()
                cur = r
            buf.append(gidx)
        flush()
        body = "".join(pieces)
        if body.strip():
            out.append(f"<div class='tp'><span class='ts'>{fmt_time(para['ts'])}</span>{body}</div>")
    return "".join(out)


# ---------- ページ描画 ----------
def render_index():
    ids = list_ids()
    if ids:
        items = "".join(
            f"<li><a href='/id?id={urllib.parse.quote(i)}'>{esc(i)}</a> "
            f"<span class='meta'>{len(list_segments(i))} セグメント</span></li>"
            for i in ids
        )
        body = f"<h1>生成物チェック (ローカル preview)</h1><ul class='ids'>{items}</ul>"
    else:
        body = ("<h1>生成物チェック (ローカル preview)</h1>"
                f"<p class='meta'>contents/ を持つ ID が見つかりません。<br>data: {esc(DATA_DIR)}</p>")
    body += f"<p class='meta'>data: {esc(DATA_DIR)}</p>"
    return page("生成物チェック (ローカル preview)", body)


LEGEND = (
    "<div class='legend'><b>凡例（校正用PDF準拠・全文中に表示）</b>　"
    "<span class='sw r-done'>✂ カット済み(確定)</span>　"
    "<span class='sw r-spk'>🗣 会話相手(カット対象)</span>　"
    "<span class='sw r-cutlist'>✂ カット例</span>　"
    "<span class='sw r-todo'>✂ カット推奨(未決)</span>　"
    "<span class='sw r-fact'>⚠ 事実確認</span>　"
    "<span class='sw r-exclude'>⬛ 候補外</span>　"
    "<span class='sw r-quote'>象徴的セリフ</span>　"
    "<span class='sw chip-trim' style='color:#fff'>⏱ 詰め候補(無音)</span></div>"
)


def render_id(idv):
    if idv not in list_ids():
        return None
    d = load_id_data(idv)
    segments = d["segments"]
    parts = [
        "<div class='crumb'><a href='/'>← 一覧</a></div>",
        f"<h1>{esc(idv)}　生成物</h1>",
        LEGEND,
    ]
    if not trim_applied(idv, segments):
        parts.append("<div class='note'>⚠ 無音詰め(最終工程)は未適用です（字幕は焼込済み）。"
                     "全文中に<b>⏱ 詰め候補</b>を差し込んでいます。</div>")

    for sg in sorted(segments, key=lambda x: x.get("index", 0)):
        idx = sg.get("index")
        title = sg.get("title", "")
        cand = d["cand_by_title"].get(title)
        s, e = sg["start_sec"], sg["end_sec"]
        drops = sg.get("drops") or []
        drop_sec = sum(min(d1, e) - max(d0, s) for d0, d1 in drops)
        dur = (e - s) - drop_sec

        regions, todo, facts = build_regions(sg, cand, d["fact_checks"], d["exclude_zones"],
                                             d["cut_speakers"], d["cut_manual"])
        n_spk = len([b for b in d["cut_speakers"] if b.get("index") == idx])
        n_man = len([m for m in d["cut_manual"] if m.get("index") == idx])
        segfolder = seg_dirname(idv, idx, title)
        silseg = d["sil_by_index"].get(idx)
        gaps = [g for g in (silseg or {}).get("gaps", []) if g.get("flag") != "keep_natural"]

        parts.append("<div class='seg'>")
        rank = cand.get("rank") if cand else None
        parts.append(
            "<div class='seghd'>"
            f"<h2><span class='rank'>確定{idx}</span>　{esc(title)}</h2>"
            f"<div class='meta'>{fmt_time(s)}〜{fmt_time(e)}　尺 約{fmt_time(dur)}"
            + (f"　(AI {rank}位)" if rank else "")
            + f"　｜ カット済み {len(drops)}・会話相手 {n_spk}・カット例 {n_man}"
            + f"・未決 {len(todo)}・事実確認 {len(facts)}・詰め候補 {len(gaps)}</div></div>"
        )

        if segfolder and os.path.isfile(os.path.join(DATA_DIR, idv, "contents", segfolder, "final.mp4")):
            parts.append(f"<video src='{media_url(idv, segfolder, 'final.mp4')}' controls preload='metadata'></video>")
            links = [f"<a href='{media_url(idv, segfolder, fn)}'>{esc(lb)}</a>"
                     for fn, lb in MEDIA_FILES
                     if os.path.isfile(os.path.join(DATA_DIR, idv, "contents", segfolder, fn))]
            if links:
                parts.append("<div class='dl'>" + "".join(links) + "</div>")
        else:
            parts.append("<p class='meta'>final.mp4 なし</p>")

        # 無音詰めの3パターン比較（生成済みのバリアントがあれば並べる）
        variants = [("final_hard.mp4", "ハード（0.8秒→0.15秒／テンポ最速）"),
                    ("final_natural.mp4", "自然（1.5秒→0.4秒／バランス）"),
                    ("final_soft.mp4", "ほぼそのまま（3.5秒→0.8秒／最小）")]
        vparts = []
        for fn, lb in variants:
            if segfolder and os.path.isfile(os.path.join(DATA_DIR, idv, "contents", segfolder, fn)):
                vparts.append(f"<div style='margin:.5rem 0'><div class='meta'>▶ 詰め: {esc(lb)}</div>"
                              f"<video src='{media_url(idv, segfolder, fn)}' controls preload='metadata'></video></div>")
        if vparts:
            parts.append("<div style='background:#8b5cf618;border-left:3px solid #7c3aed;"
                         "border-radius:8px;padding:.6rem .8rem;margin:.6rem 0'>"
                         "<h3 style='font-size:.9rem;margin:0 0 .3rem'>🔊 無音詰め 比較（未確定・上の動画が元）</h3>"
                         + "".join(vparts) + "</div>")

        # 要約・レビュー（象徴的セリフのリストは廃止＝本文ハイライトへ）
        if cand:
            inner = ""
            if cand.get("summary"):
                inner += f"<p><b>要約:</b> {esc(cand['summary'])}</p>"
            if cand.get("review"):
                inner += f"<p><b>レビュー:</b> {esc(cand['review'])}</p>"
            if inner:
                parts.append(f"<div class='box summary'>{inner}</div>")

        # 切り出し全文（すべての注釈を本文中に）
        quotes = (cand or {}).get("highlight_quotes") or []
        tr_html = render_transcript(d["tsegments"], s, e, regions, quotes, gaps)
        parts.append("<div class='transcript'><h3>切り出し全文</h3>"
                     + (tr_html or "<p class='meta'>文字起こしなし</p>") + "</div>")
        parts.append("</div>")

    return page(f"{idv} 生成物", "".join(parts))


def safe_media_path(p):
    rel = urllib.parse.unquote(p or "")
    full = os.path.realpath(os.path.join(DATA_DIR, rel))
    if (full == DATA_DIR or full.startswith(DATA_DIR + os.sep)) and os.path.isfile(full):
        return full
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "podcast-preview/3.0"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if route == "/":
                self._send_html(render_index())
            elif route == "/id":
                content = render_id((qs.get("id") or [""])[0])
                if content is None:
                    self._send_html(page("404", "<h1>404</h1><a href='/'>一覧へ</a>"), 404)
                else:
                    self._send_html(content)
            elif route == "/media":
                full = safe_media_path((qs.get("p") or [""])[0])
                if full is None:
                    self.send_error(404)
                else:
                    self._send_file(full)
            else:
                self.send_error(404)
        except BrokenPipeError:
            pass
        except Exception as ex:
            try:
                self._send_html(page("500", f"<h1>500</h1><pre>{esc(ex)}</pre>"), 500)
            except Exception:
                pass

    def _send_html(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, fullpath):
        ctype = mimetypes.guess_type(fullpath)[0] or "application/octet-stream"
        fs = os.path.getsize(fullpath)
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            start = int(m.group(1)) if m and m.group(1) else 0
            end = int(m.group(2)) if m and m.group(2) else fs - 1
            end = min(end, fs - 1)
            if start > end or start >= fs:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{fs}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{fs}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self._stream(fullpath, start, end - start + 1)
        else:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(fs))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self._stream(fullpath, 0, fs)

    def _stream(self, fullpath, start, length):
        with open(fullpath, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main():
    mimetypes.add_type("video/mp4", ".mp4")
    mimetypes.add_type("audio/mp4", ".m4a")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[preview] http://127.0.0.1:{PORT}/  (data: {DATA_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[preview] 停止しました")


if __name__ == "__main__":
    main()
