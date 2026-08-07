#!/usr/bin/env python3
"""カット推奨に、音源をまたいでユニークな番号 (C<音源No>-<連番>) を振る。

- data/sources.json           : ID → 音源No の台帳（未登録IDは追番で自動登録）
- data/<ID>/cut_decisions.json: 各カット推奨の番号・区間・理由・判断状況
  status: pending(未判断) / cut(カットする) / keep(カットしない)

再実行しても既存の番号・判断は変えない（新しいカット推奨にだけ次番号を振る）。
同一区間 (start,end) に複数の理由が付いている場合は1件に統合し理由を「／」で連結。
初回生成時、segments.json の drops に既に適用済みの区間は status=cut で初期化する。

usage: python scripts/assign_cut_ids.py <ID>
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import idpaths  # data/<ID>/ のファイル配置は idpaths が唯一の定義（D-002 改定）

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def P(outdir, name):
    """読み書き両用のパス解決。読むときは新旧どちらでも見つかる。"""
    return pathlib.Path(idpaths.find(str(outdir), name))


def PW(outdir, name):
    return pathlib.Path(idpaths.save(str(outdir), name))


def _load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _dump(obj, p):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _key(st, en):
    return (round(float(st), 1), round(float(en), 1))


def main(idv):
    base = DATA / idv
    if not base.is_dir():
        sys.exit(f"[cut_ids] data/{idv} がありません")

    sources_p = DATA / "sources.json"
    sources = _load(sources_p, {})
    if idv not in sources:
        sources[idv] = (max(sources.values()) + 1) if sources else 1
        _dump(sources, sources_p)
    src_no = sources[idv]

    # 候補のカット推奨を (start,end) で統合。
    # 候補外ゾーン(exclude_zones.json)も「候補外」という分類は持たず、カット推奨として扱う。
    merged = {}

    def add(st, en, reason, quote=""):
        if st is None or en is None:
            return
        m = merged.setdefault(_key(st, en), {
            "start_sec": float(st), "end_sec": float(en),
            "reasons": [], "quote": (quote or "").strip()})
        r = (reason or "").strip()
        if r and r not in m["reasons"]:
            m["reasons"].append(r)

    for c in _load(P(base, "candidates_raw.json"), []):
        for cut in c.get("cuts") or []:
            add(cut.get("start_sec"), cut.get("end_sec"),
                cut.get("reason"), cut.get("quote"))
    for ez in _load(P(base, "exclude_zones.json"), {}).get("exclude_zones", []):
        add(ez.get("start_sec"), ez.get("end_sec"), ez.get("reason"))

    dec_p = PW(base, "cut_decisions.json")
    dec = _load(dec_p, {"source_no": src_no, "cuts": []})
    dec["source_no"] = src_no
    known = {_key(c["start_sec"], c["end_sec"]): c for c in dec["cuts"]}
    nxt = max((int(c["cid"].rsplit("-", 1)[1]) for c in dec["cuts"]), default=0) + 1

    segments = _load(P(base, "segments.json"), {}).get("segments", [])

    # 初期状態は全件オープン（勝手にカットしない・D-013）。オーナーがサイトのボタンか
    # チャットで cut/keep を確定するまで pending のまま。
    added = 0
    for key in sorted(merged):
        m = merged[key]
        if key in known:
            known[key]["reason"] = "／".join(m["reasons"])  # 理由だけ最新化
            continue
        dec["cuts"].append({
            "cid": f"C{src_no}-{nxt}",
            "start_sec": m["start_sec"], "end_sec": m["end_sec"],
            "reason": "／".join(m["reasons"]), "quote": m["quote"],
            "status": "pending", "decided": None, "note": "", "category": "gpt"})
        nxt += 1
        added += 1

    # 会話相手（メイン話者 SPEAKER_01 以外）の発言ブロックも未決候補として追加する。
    # 判定は間違うことがあるため、勝手にカットせずオーナーの確定を待つ。
    tr = _load(P(base, "transcript.json"), {})
    spk_added = 0
    for ts in tr.get("segments", []):
        spk = str(ts.get("speaker") or "")
        t0, t1 = ts.get("start"), ts.get("end")
        if t0 is None or t1 is None or not spk or spk.endswith("01"):
            continue
        if segments and not any(sg["start_sec"] <= t0 < sg["end_sec"] for sg in segments):
            continue  # 確定セグメント外は対象にしない
        covered = False
        for sg in segments:
            for d0, d1 in sg.get("drops") or []:
                ov = max(0.0, min(t1, d1) - max(t0, d0))
                if ov >= 0.5 * max(0.1, t1 - t0):
                    covered = True  # 既に確定カット内 → 候補にしない
        if covered:
            continue
        key = _key(t0, t1)
        if key in known or any(_key(c["start_sec"], c["end_sec"]) == key for c in dec["cuts"]):
            continue
        n = spk.split("_")[-1].lstrip("0") or "?"
        dec["cuts"].append({
            "cid": f"C{src_no}-{nxt}",
            "start_sec": float(t0), "end_sec": float(t1),
            "reason": f"会話相手(Sp{n})の発言", "quote": "",
            "status": "pending", "decided": None, "note": "", "category": "speaker"})
        nxt += 1
        spk_added += 1
    added += spk_added

    dec["cuts"].sort(key=lambda c: (c["start_sec"], c["end_sec"]))
    _dump(dec, dec_p)
    n_pend = sum(1 for c in dec["cuts"] if c["status"] == "pending")
    print(f"[cut_ids] {idv} = 音源{src_no}: 全{len(dec['cuts'])}件 (新規{added} / 未判断{n_pend})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
