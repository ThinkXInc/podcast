#!/usr/bin/env python3
# 文字起こしの語彙バイアス用プロンプト(initial_prompt)を作る。
#
#   python scripts/make_asr_prompt.py <ID> [--show]
#   -> data/<ID>/asr_prompt.txt
#
# なぜ必要か:
#   Whisper は initial_prompt に出てきた語のトークン確率が上がる。番組の頻出語
#   （固有名詞・専門用語）を先に見せておくと、まさに large-v3 の弱点である
#   固有名詞・専門用語の取り違えが減る。
#
# なぜ要約をそのまま渡さないか:
#   Whisper のプロンプト上限は n_text_ctx//2-1 = 223 トークン。要約全文は
#   1万トークン近くあり、渡しても末尾だけが残って大半が捨てられる。
#   そこで要約から「語」を抽出し、頻度順に上限まで詰める。
#
# 入力（あるものを使う。無ければスキップ）:
#   data/<ID>/*要約*.txt        Notta 等の要約
#   data/<ID>/gptout.txt        GPT の候補出力（タイトル・引用に固有名詞が多い）
#   data/<ID>/asr_terms.txt     手で足したい語（1行1語）。最優先で入れる。

import os
import re
import sys
import glob
import collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT_TOKENS = 223          # Whisper のプロンプト上限
HEAD = "以下は日本語の対談の書き起こしです。"

# 抽出する語の形: カタカナ語 / 漢字熟語。
# 英字語は入れない。gptout.txt の JSON フィールド名（reason, quote, start …）を拾って
# しまい、英語トークンへのバイアスになって日本語の認識をむしろ悪くするため。
PATTERNS = [
    re.compile(r"[ァ-ヴー]{3,}"),                 # カタカナ
    re.compile(r"[一-龥々]{2,}"),                  # 漢字熟語
]
# 抽出しても意味の薄い一般語（バイアスをかける価値がない）。
# 番組の内容語ではなく、要約テンプレや我々のワークフロー由来の語も落とす。
STOP = {
    "会議", "議事", "議事録", "参加", "参加者", "日時", "概要", "以下", "内容", "場合",
    "自分", "今回", "本会", "本会議", "議論", "指摘", "説明", "話題", "発言", "全体",
    "重要", "必要", "可能", "問題", "課題", "状況", "関係", "結果", "現在", "存在",
    "話者", "冒頭", "最後", "部分", "一部", "非常", "特に", "また", "など", "こと",
    "本命", "候補", "補助", "見出し", "要約", "尺", "開始", "終了", "区間", "秒",
    "アクションアイテム", "ハイライト", "タイトル", "カット", "セグメント",
}
# gptout.txt の JSON ブロック（```json … ``` と素の {...}）は語彙の元にしない
JSON_BLOCK = re.compile(r"```.*?```|\{[^{}]*\"[^{}]*\}", re.S)


def read_sources(base):
    texts = []
    manual = os.path.join(base, "asr_terms.txt")
    manual_terms = []
    if os.path.isfile(manual):
        manual_terms = [ln.strip() for ln in open(manual, encoding="utf-8") if ln.strip()]
    for p in sorted(glob.glob(os.path.join(base, "*要約*.txt"))):
        texts.append(open(p, encoding="utf-8").read())
    g = os.path.join(base, "gptout.txt")
    if os.path.isfile(g):
        texts.append(open(g, encoding="utf-8").read())
    return manual_terms, "\n".join(texts)


def extract_terms(text):
    """頻度×長さでランク付けした語を返す。"""
    counts = collections.Counter()
    for pat in PATTERNS:
        for m in pat.finditer(text):
            w = m.group(0)
            if w in STOP or len(w) > 12:
                continue
            counts[w] += 1
    # 2回以上出た語を優先。1回でも長い固有名詞は拾う。
    ranked = sorted(counts.items(),
                    key=lambda kv: (-(kv[1] * min(len(kv[0]), 6)), -len(kv[0]), kv[0]))
    return [w for w, c in ranked if c >= 2 or len(w) >= 4]


def count_tokens(s):
    """Whisper のトークナイザで数える。無ければ文字数から概算する。"""
    try:
        from mlx_whisper.tokenizer import get_tokenizer
        tk = get_tokenizer(multilingual=True, language="ja", task="transcribe")
        return len(tk.encoding.encode(s))
    except Exception:
        return int(len(s) / 1.4) + 1


def build(manual_terms, terms):
    """上限トークンに収まるまで語を詰める。手入力の語は必ず入れる。"""
    picked, seen = [], set()
    for w in manual_terms + terms:
        if w in seen:
            continue
        seen.add(w)
        cand = picked + [w]
        if count_tokens(HEAD + "".join("、" + x for x in cand)) > LIMIT_TOKENS:
            if w in manual_terms:
                continue        # 手入力はスキップせず次を試す
            break
        picked.append(w)
    return HEAD + "".join("、" + x for x in picked), picked


def main():
    if len(sys.argv) < 2:
        print("usage: make_asr_prompt.py <ID> [--show]")
        return 1
    idv = sys.argv[1]
    base = os.path.join(HERE, "data", idv)
    if not os.path.isdir(base):
        print(f"[prompt] data/{idv} がありません")
        return 1
    manual_terms, text = read_sources(base)
    if not text.strip() and not manual_terms:
        print(f"[prompt] 語彙の元になる要約 / gptout.txt / asr_terms.txt がありません。スキップします。")
        return 0
    terms = extract_terms(text)
    prompt, picked = build(manual_terms, terms)
    out = os.path.join(base, "asr_prompt.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(prompt + "\n")
    print(f"[prompt] {len(picked)} 語 / {count_tokens(prompt)} トークン (上限 {LIMIT_TOKENS}) -> {out}")
    if "--show" in sys.argv:
        print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
