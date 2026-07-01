#!/usr/bin/env python3
"""
最終処理その2: 判断した詰め幅で無音を縮める（前後比較できるよう元は必ず残す）。

detect_silence.py が出した無音区間を、Claude Code が前後の文脈を見て
区間ごとに「keep 秒だけ残す」と判断した結果（trim_plan.json）を読み、
ffmpeg で実際にその区間を keep 秒へ縮めた版を書き出す。

重要:
   - 元ファイルは絶対に上書きしない。<名前>_orig.<拡張子> として必ず残す
     （前後比較できるように、処理前・処理後の両方を残すのがこの段取りの目的）。
   - 出力は <名前>_trimmed.<拡張子>。
   - 機械的な一律処理ではなく、keep は区間ごとに違ってよい（Claude が判断した値をそのまま使う）。

使い方:
   python apply_trim.py <ID> <メディアファイル>
       trim_plan.json は data/<ID>/trim_plan.json を読む
trim_plan.json 形式:
   {"keeps":[{"start_sec":1647.0,"end_sec":1695.0,"keep":0.4,"reason":"言い淀みの無駄な間"}, ...]}
   keep は「その無音区間に残す秒数」。0 ならほぼ無音を消す。
   reason は任意。なぜその残し幅にしたか（適用後の説明に使う）。
"""
import os, sys, json, shutil, subprocess, pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]


def load_paths():
    paths = {}
    os.environ["HERE"] = str(HERE)
    conf = HERE / "config/paths.conf"
    if conf.exists():
        for line in conf.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                paths[k] = os.path.expandvars(v.strip().strip('"'))
    return paths


def duration_of(media):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media)],
        capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


def build_keep_segments(total, silences):
    """無音区間を keep 秒に縮める = 残す区間のリストを作る。
    各無音 [s,e] について、先頭 keep 秒だけ残し、s+keep..e を捨てる。
    結果として「保持する [from,to] の並び」を返す。"""
    # 捨てる区間 [drop_from, drop_to]
    drops = []
    for sil in silences:
        s = float(sil["start_sec"]); e = float(sil["end_sec"])
        keep = max(0.0, float(sil.get("keep", 0.0)))
        drop_from = min(e, s + keep)
        if e - drop_from > 0.02:   # 残すべきものが無ければスキップ
            drops.append((drop_from, e))
    drops.sort()
    # 保持区間 = 全体から drops を引く
    keeps = []
    cur = 0.0
    for df, dt in drops:
        if df > cur:
            keeps.append((cur, df))
        cur = max(cur, dt)
    if cur < total:
        keeps.append((cur, total))
    return [(round(a, 3), round(b, 3)) for a, b in keeps if b - a > 0.02]


def has_video(media):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(media)],
        capture_output=True, text=True).stdout.strip()
    return "video" in out


def main():
    if len(sys.argv) < 3:
        print("usage: python apply_trim.py <ID> <メディアファイル>")
        sys.exit(1)
    ID = sys.argv[1]
    paths = load_paths()
    root = paths.get("PODCAST_ROOT", str(HERE / "data"))
    outdir = pathlib.Path(root) / ID
    media = pathlib.Path(sys.argv[2])
    if not media.is_absolute():
        media = outdir / media
    if not media.exists():
        print(f"[trim] メディアが見つかりません: {media}")
        sys.exit(1)

    plan_p = outdir / "trim_plan.json"
    if not plan_p.exists():
        print(f"[trim] {plan_p} が無い。detect_silence.py の結果を見て Claude が判断・作成すること。")
        sys.exit(1)
    plan = json.loads(plan_p.read_text(encoding="utf-8"))
    keeps_in = plan.get("keeps", [])
    if not keeps_in:
        print("[trim] trim_plan.json の keeps が空。詰める区間がないので終了。")
        sys.exit(0)

    total = duration_of(media)
    if total is None:
        print("[trim] 長さを取得できませんでした。")
        sys.exit(1)

    keep_segs = build_keep_segments(total, keeps_in)
    if not keep_segs:
        print("[trim] 保持区間を計算できませんでした。")
        sys.exit(1)

    ext = media.suffix
    orig = media.with_name(media.stem + "_orig" + ext)
    trimmed = media.with_name(media.stem + "_trimmed" + ext)

    # 元を必ず残す（前後比較用）。既にあれば壊さない。
    if not orig.exists():
        shutil.copy2(media, orig)
        print(f"[trim] 元ファイルを保存（処理前）: {orig.name}")
    else:
        print(f"[trim] 元ファイルは既に保存済み: {orig.name}")

    vid = has_video(media)
    # filter_complex で保持区間を concat
    parts = []
    n = len(keep_segs)
    for i, (a, b) in enumerate(keep_segs):
        parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}];")
        if vid:
            parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}];")
    if vid:
        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        concat_inputs = "".join(f"[a{i}]" for i in range(n))
        parts.append(f"{concat_inputs}concat=n={n}:v=0:a=1[a]")
        maps = ["-map", "[a]"]
    filt = "".join(parts)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(media),
           "-filter_complex", filt, *maps, str(trimmed)]
    print(f"[trim] 無音を {len(keeps_in)} 区間ぶん詰めて書き出し中… → {trimmed.name}")
    r = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        print("[trim] ffmpeg 失敗:")
        print(r.stderr[-1500:])
        sys.exit(1)

    new_total = duration_of(trimmed)
    saved = (total - new_total) if new_total else 0
    print("=" * 60)
    print(f"[trim] 完了。前後比較できるよう両方残しています:")
    print(f"   処理前: {orig.name}   ({total:.1f}秒)")
    print(f"   処理後: {trimmed.name} ({new_total:.1f}秒)  −{saved:.1f}秒短縮")
    print("=" * 60)
    # 区間ごとの「なぜそう詰めたか」を自然言語で出す材料（plan の reason をそのまま使う）
    def hms(s):
        s = max(0, float(s)); return f"{int(s)//3600:02d}:{int(s)%3600//60:02d}:{int(s)%60:02d}"
    print("[trim] 各区間の処理内容（説明用）:")
    for k in keeps_in:
        st = k.get("start_sec"); en = k.get("end_sec"); keep = k.get("keep", 0)
        dur = (en - st) if (st is not None and en is not None) else 0
        why = k.get("reason", "")
        print(f"   {hms(st)} 空白{dur:.1f}秒 → {keep:.1f}秒に詰めた" + (f"／理由: {why}" if why else ""))
    print("=" * 60)
    print("[trim] Claude Code への指示: 仕上げは確認を取らず一発で実行済み。")
    print("   適用後に、上の各区間について『◯◯だったので◯秒残した/詰めた』と")
    print("   自然言語でまとめてユーザーに説明する。元ファイルは残してあるので、")
    print("   気になる区間は keep を直して再実行できることも一言添える。")


if __name__ == "__main__":
    main()
