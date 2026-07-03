#!/usr/bin/env python3
"""
2. 切り出し候補生成（GPT-5.5 Pro / Responses API・1回呼び出し）

   統合プロンプト prompt_all.txt を【1回だけ】投げ、本命候補・補助候補・候補外ゾーン・
   事実チェックをまとめて取得する。文字起こし全文を毎回送ると高額なので、4回→1回に統合。
   gpt-5.5-pro は最大出力128kトークンあるため、1回で全観点を出し切れる。

   モデル: 既定で gpt-5.5-pro（ブラウザのChatGPT GPT-5.5 Proに最も近い高精度版）。
   - GPT-5.5 Pro は **Responses API でのみ** 利用可能。Chat Completions では呼べない。
   - reasoning.effort は high（既定）。さらに上げたいなら xhigh。
   - Pro は1リクエストに数分かかることがある（仕様）。タイムアウトに注意。
   - 安く・速くしたい場合は環境変数 PODCAST_MODEL=gpt-5.5 で無印（Thinking相当）に切替可。

   ★ 料金ゼロの手動モード:
   data/<ID>/gptout.txt（または gptout.md / gpt_pro.txt）があれば、APIを呼ばずそれを使う。
   prompts/prompt_all.txt と transcript.txt をブラウザのGPT Proに貼って実行し、その応答全文
   （末尾の ```json ブロックごと）を gptout.txt に保存しておけばよい。再実行でもAPIを呼ばない。
   この場合 openai ライブラリ未インストール・APIキー無しでも動く。

使い方:
   python suggest.py <ID>
出力:
   outputs/<ID>/suggestions_1.md   (統合結果・全文。人が読む用)
   outputs/<ID>/exclude_zones.json (候補外ゾーン＋事実チェック。PDF生成が読む)
   outputs/<ID>/candidates_raw.json (全candidatesを統合した生データ)
"""
import os, sys, json, re, pathlib

# 注: openai ライブラリは APIモードのときだけ遅延importする（下のAPIモード分岐内）。
# こうしておくと、手動モード（gptout.txt使用）では openai 未インストール・APIキー無しでも動く。

MODEL = os.environ.get("PODCAST_MODEL", "gpt-5.5-pro")  # 高精度。安く速くしたいなら gpt-5.5
EFFORT = os.environ.get("PODCAST_REASONING_EFFORT", "high")  # high / xhigh / medium
HERE = pathlib.Path(__file__).resolve().parents[1]

def load_prompt(name):
    return (HERE / "prompts" / name).read_text(encoding="utf-8")

def extract_json_block(text):
    """応答末尾の ```json ... ``` を取り出してパース。失敗時は None。"""
    m = re.findall(r"```json\s*(.*?)```", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m[-1])
    except json.JSONDecodeError:
        return None

def main():
    # paths.conf の PODCAST_ROOT を読む（$HERE はプロジェクトルートに解決）
    os.environ["HERE"] = str(HERE)
    paths = {}
    for line in (HERE / "config/paths.conf").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            paths[k] = os.path.expandvars(v.strip().strip('"'))
    podcast_root = paths["PODCAST_ROOT"]

    ID = sys.argv[1]
    outdir = pathlib.Path(podcast_root) / ID

    all_candidates = []
    exclude_zones = []
    fact_checks = []

    def absorb(text):
        """応答テキスト末尾のJSONを取り込む。"""
        data = extract_json_block(text)
        if data:
            if "candidates" in data:
                all_candidates.extend(data["candidates"])
            if "exclude_zones" in data and isinstance(data["exclude_zones"], list):
                exclude_zones.extend(data["exclude_zones"])
            if "fact_checks" in data and isinstance(data["fact_checks"], list):
                fact_checks.extend(data["fact_checks"])
        else:
            print("[suggest] 警告: 末尾の ```json ブロックが見つからない/壊れています。"
                  "候補が空になります。手動結果なら、GPTの応答末尾のJSONごと貼れているか確認を。")
        return text

    # --- 手動モード優先 ---
    # data/<ID>/ に手動でブラウザのGPT Proの結果を置いてあれば、APIを呼ばずそれを使う。
    # ファイル名は gptout.txt / gptout.md / gpt_pro.txt のいずれか（先に見つかったもの）。
    # これでAPI料金ゼロ＆再実行でも都度APIを呼ばない。
    manual = None
    for name in ("gptout.txt", "gptout.md", "gpt_pro.txt", "gpt_pro.md"):
        cand = outdir / name
        if cand.exists() and cand.read_text(encoding="utf-8").strip():
            manual = cand
            break

    if manual:
        print(f"[suggest] 手動モード: {manual.name} を使用（APIは呼びません・料金ゼロ）")
        full_text = absorb(manual.read_text(encoding="utf-8"))
    else:
        # --- APIモード ---
        from openai import OpenAI
        client = OpenAI()
        print(f"[suggest] APIモード: {MODEL} を1回呼び出します（effort={EFFORT}）。")
        print("[suggest]   ※ gpt-5.5-pro は応答に数分かかることがあります。")
        print("[suggest]   ※ 料金を避けたい場合は、prompts/prompt_all.txt と transcript.txt を")
        print(f"[suggest]      ブラウザのGPT Proに貼って実行し、結果を data/{ID}/gptout.txt に保存してください。")
        # APIモードでのみ文字起こしが必要。
        # GPTへは Notta精度の transcript.json（本文＋話者）を優先して送る。
        # 話者を [大塚]/[相手] で明示すると、会話相手カットの規則にGPTが沿いやすい。
        # transcript.json が話者を持たない旧形式なら transcript.txt にフォールバック。
        tj = outdir / "transcript.json"
        transcript = None
        if tj.exists():
            import json as _json
            _segs = _json.loads(tj.read_text(encoding="utf-8")).get("segments", [])
            if _segs and any(s.get("speaker") for s in _segs):
                _lines = []
                for s in _segs:
                    _who = "大塚" if str(s.get("speaker") or "").endswith("01") else "相手"
                    _t = (s.get("text") or "").strip()
                    if _t:
                        _lines.append(f"[{_who}] {_t}")
                transcript = "\n".join(_lines)
        if not transcript:
            transcript = (outdir / "transcript.txt").read_text(encoding="utf-8")
        prompt_body = load_prompt("prompt_all.txt")
        resp = client.responses.create(
            model=MODEL,
            instructions=("あなたはポッドキャスト編集のプロです。指示に厳密に従い、"
                          "中略せず全文を出し、最後に必ず指定のJSONブロックを付けてください。"),
            input=f"{prompt_body}\n\n=== 文字起こしここから ===\n{transcript}\n=== ここまで ===",
            reasoning={"effort": EFFORT},
        )
        full_text = absorb(resp.output_text)

    # 人が読む用に1ファイルへ（全文そのまま）。Claude Code はこれを丸めず全文チャットに貼る。
    (outdir / "suggestions_1.md").write_text(
        "# 切り出し候補・候補外ゾーン・事実チェック（統合）\n\n" + full_text, encoding="utf-8")
    # 後方互換: 旧名のファイルを参照する箇所があっても落ちないよう空ではなく同一内容を残す
    (outdir / "suggestions_2.md").write_text(
        "（統合プロンプトに移行。内容は suggestions_1.md を参照）\n", encoding="utf-8")
    (outdir / "suggestions_3.md").write_text(
        "（統合プロンプトに移行。候補外ゾーンは suggestions_1.md / exclude_zones.json を参照）\n",
        encoding="utf-8")

    # candidates 統合（rank順）
    all_candidates.sort(key=lambda c: c.get("rank", 999))
    (outdir / "candidates_raw.json").write_text(
        json.dumps(all_candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    # 候補外ゾーン（グレーで伏せる）＋事実チェックを別ファイルに保存（make_review_pdf が読む）
    (outdir / "exclude_zones.json").write_text(
        json.dumps({"exclude_zones": exclude_zones, "fact_checks": fact_checks},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[suggest] done. 候補 {len(all_candidates)} 件 / 候補外ゾーン {len(exclude_zones)} 件 "
          f"-> {outdir}/suggestions_1.md, suggestions_2.md")

    # 校正用PDF（赤=AI案）を自動生成。失敗してもパイプラインは止めない。
    pdf_ok = False
    try:
        import subprocess
        r = subprocess.run([sys.executable, str(HERE / "scripts" / "make_review_pdf.py"), ID],
                           check=False)
        pdf_ok = (r.returncode == 0)
    except Exception as e:
        print(f"[suggest] 校正用PDF生成はスキップ（後で make_review_pdf.py を実行可）: {e}")

    # 校正用PDFを画像化（リモート環境でチャットに貼って見せるため）
    if pdf_ok:
        try:
            import subprocess
            subprocess.run([sys.executable, str(HERE / "scripts" / "preview_pdf.py"), ID],
                           check=False)
        except Exception as e:
            print(f"[suggest] PDFプレビュー画像化はスキップ: {e}")

    print("\n" + "=" * 70)
    print("[suggest] Claude Code への指示:")
    print("  1) 各候補の 見出し/時刻/尺/ハイライト原文(5個前後・全件)/要約/レビュー をチャットに出す。")
    print("     ハイライトは全件出す（内容想起の主役）。切り出し全文(full_text)は最初と最後の約10行に省略可。")
    print("     カット(cuts)・事実チェック(fact_checks)・候補外ゾーンは【全件】列挙（件数を丸めない）。")
    print(f"  2) data/{ID}/preview/p*.png を【画像としてチャットに貼って】校正用PDFを見せること。")
    print("     ファイルパスの案内だけで済ませない（ユーザーはリモートで手元から開けない）。")
    print(f"  3) iPad校正用に PDF実体の場所も併記: data/{ID}/{ID}_校正用.pdf")
    print("=" * 70)

if __name__ == "__main__":
    main()
