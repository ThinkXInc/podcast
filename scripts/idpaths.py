#!/usr/bin/env python3
"""data/<ID>/ の中のファイル配置を一箇所で決める（D-002 改定）。

方針:
  直下      … オーナーが入れたもの（元音源・元動画・Notta の PDF/txt・要約・編集メモ）
  edit/     … 人の判断が入ったデータ（切り出し区間・カット判断・評価）
  generated/… 機械が作ったもの。消しても作り直せる
  contents/ … 最終書き出し（動画・音声）
  backup/   … 退避

なぜ一箇所に集めるか:
  ファイルを移すと、参照している全スクリプトを直さないと壊れる。ここを直せば済むようにする。
  移行中は **旧い場所（直下）にあるファイルもそのまま読める** ようにしてある（find が両方見る）。
  書き込みは常に新しい場所（save）。
"""

import os

# 人の判断が入るもの。消したら手作業がやり直しになる。
EDIT_FILES = {
    "segments.json",        # 切り出し区間と drops（タイムラインが書く）
    "cut_decisions.json",   # C番号ごとのカット/残す判断
    "ratings.json",         # オーナー評価（★）
    "cutlist.json",         # 手動のカット指定
    "trim_plan.json",       # 無音詰めの計画
}

# 機械が作るもの。消しても作り直せる。
GENERATED_FILES = {
    "transcript.json", "transcript.txt",
    "vad.json", "silences.json",
    "candidates_raw.json", "candidates_claude.json",
    "exclude_zones.json", "exclude_zones_claude.json",
    "transcript_pdf_map.json",
    "preview_audio.m4a",
    "suggestions_1.md", "suggestions_2.md", "suggestions_3.md",
    "asr_prompt.txt",
}
# 接尾辞で generated 行きにするもの（ID 名を含むファイル名になるため）
GENERATED_SUFFIX = ("_全文.pdf", "_校正用.pdf")
GENERATED_CONTAINS = ("_校正用",)

EDIT_DIR = "edit"
GEN_DIR = "generated"
# experiments/ … 試行の産物（A/B試聴サンプル等）。generated を散らかさないための置き場
#                （オーナー指示 2026-08-10）。パイプラインは読まない
EXP_DIR = "experiments"


def subdir_for(name):
    """そのファイルが入るべきサブディレクトリ名を返す。直下なら空文字。"""
    if name in EDIT_FILES:
        return EDIT_DIR
    if name in GENERATED_FILES:
        return GEN_DIR
    if name.endswith(GENERATED_SUFFIX) or any(k in name for k in GENERATED_CONTAINS):
        return GEN_DIR
    return ""


def find(base, name):
    """読むときのパス。新しい場所を優先し、無ければ旧い場所（直下）も見る。
    どちらにも無ければ「新しい場所のパス」を返す（存在チェックは呼び出し側で）。"""
    sub = subdir_for(name)
    if sub:
        newp = os.path.join(base, sub, name)
        if os.path.exists(newp):
            return newp
        oldp = os.path.join(base, name)
        if os.path.exists(oldp):
            return oldp
        return newp
    return os.path.join(base, name)


def save(base, name):
    """書くときのパス。常に新しい場所。親ディレクトリを作ってから返す。"""
    sub = subdir_for(name)
    d = os.path.join(base, sub) if sub else base
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def gen_dir(base):
    d = os.path.join(base, GEN_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def edit_dir(base):
    d = os.path.join(base, EDIT_DIR)
    os.makedirs(d, exist_ok=True)
    return d
