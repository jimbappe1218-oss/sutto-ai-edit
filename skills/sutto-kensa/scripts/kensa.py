#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕上げ検査。書き出した動画を測って、コマ一覧の画像と検査結果を出す。

    python3 kensa.py 完成.mp4
    python3 kensa.py 完成.mp4 --target short
    python3 kensa.py 完成.mp4 --telop 完成.mp4.telop_report.json   … テロップが出ているコマを並べる
    python3 kensa.py 完成.mp4 --before 元の素材.mp4               … 編集前と比べる

調べること
  - 解像度・フレームレート・長さ・コーデック・色形式
  - ラウドネス（LUFS）・トゥルーピーク
  - 長い無言、真っ黒なコマ、止まったままの映像
  - 映像と音声の長さのずれ
出すもの: 元の名前_検査.png（コマ一覧。AI がこの画像を見て、テロップの切れ・はみ出しを確かめる）、元の名前_検査.json
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sutto_env as E  # noqa: E402


def stream_durations(path):
    r = E.run([E.tool("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)], "ffprobe")
    out = {}
    for s in json.loads(r.stdout.decode() or "{}").get("streams", []):
        try:
            out.setdefault(s["codec_type"], float(s["duration"]))
        except (KeyError, ValueError):
            pass
    return out


def detect_black_freeze(path, duration):
    """真っ黒なコマと、止まったままの映像を探す（縮小して速く調べる）。"""
    r = subprocess.run([E.tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(path), "-map", "0:v:0", "-an",
                        "-vf", "scale=640:-2,blackdetect=d=0.25:pix_th=0.10,freezedetect=n=0.0005:d=3", "-f", "null", "-"],
                       capture_output=True)
    text = r.stderr.decode("utf-8", "replace")
    black = [{"start": round(float(a), 2), "end": round(float(b), 2)}
             for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", text)]
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", text)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", text)]
    freeze = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        freeze.append({"start": round(s, 2), "end": round(e, 2)})
    return black, freeze


def silences(levels, min_len):
    th, floor, speech, clear = E.speech_threshold(levels)
    out, i, n = [], 0, len(levels)
    while i < n:
        if levels[i] <= th:
            j = i
            while j < n and levels[j] <= th:
                j += 1
            if (j - i) * E.LEVEL_WIN >= min_len:
                out.append({"start": round(i * E.LEVEL_WIN, 2), "end": round(j * E.LEVEL_WIN, 2)})
            i = j
        else:
            i += 1
    return out, clear


def contact_sheet(path, info, times, labels, out_png, tmp):
    from PIL import Image, ImageDraw, ImageFont
    vertical = info["height"] > info["width"]
    cell_w = 300 if vertical else 480
    cols = min(len(times), 6 if vertical else 4)
    cell_h = int(round(cell_w * info["height"] / info["width"] / 2) * 2)
    font = ImageFont.truetype(E.find_font("bold"), 22)
    rows = (len(times) + cols - 1) // cols
    pad, label_h = 8, 34
    sheet = Image.new("RGB", (cols * (cell_w + pad) + pad, rows * (cell_h + label_h + pad) + pad), (24, 26, 30))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(times):
        png = tmp / ("f%03d.png" % i)
        E.ff(["-v", "error", "-ss", "%.3f" % t, "-i", str(path), "-frames:v", "1", "-vf", "scale=%d:%d" % (cell_w, cell_h), str(png)],
             "コマの取り出し")
        x = pad + (i % cols) * (cell_w + pad)
        y = pad + (i // cols) * (cell_h + label_h + pad)
        if png.exists():
            sheet.paste(Image.open(png).convert("RGB"), (x, y + label_h))
        d.text((x + 4, y + 4), labels[i], font=font, fill=(235, 238, 242))
    sheet.save(out_png)
    return {"png": str(out_png), "frames": len(times), "size": "%dx%d" % sheet.size}


def main():
    ap = argparse.ArgumentParser(description="仕上げ検査")
    ap.add_argument("video")
    ap.add_argument("--target", choices=["youtube", "short", "none"], default="youtube")
    ap.add_argument("--lufs", type=float, default=-14.0, help="目標のラウドネス")
    ap.add_argument("--telop", help="telop.json または telop_report.json。テロップの出ているコマを並べる")
    ap.add_argument("--before", help="編集前の動画（比べる）")
    ap.add_argument("--frames", type=int, default=12, help="コマ一覧に並べる枚数")
    ap.add_argument("--silence", type=float, default=2.0, help="この秒数以上の無言を報告する")
    ap.add_argument("--out", help="出力先フォルダ")
    a = ap.parse_args()

    E.ensure({"PIL": "pillow"})
    src = Path(a.video).expanduser()
    info = E.probe(src)
    if not info["has_video"]:
        raise E.SuttoError("映像がありません: %s" % src)
    dur = info["duration"]
    tmp = E.work_dir("kensa")
    for old in tmp.glob("f*.png"):
        old.unlink()
    issues = []   # {"level": "要修正" | "注意", "what": ...}

    def issue(level, what):
        issues.append({"level": level, "what": what})

    rep = {"input": str(src), "target": a.target,
           "video": {"size": "%dx%d" % (info["width"], info["height"]), "fps": round(info["fps"], 3), "duration": round(dur, 2),
                     "codec": info.get("vcodec"), "pix_fmt": info.get("pix_fmt"), "bitrate_kbps": int(info.get("bit_rate", 0) / 1000)}}
    # ---- 形式
    if info.get("vcodec") != "h264":
        issue("注意", "映像コーデックが H.264 ではありません（%s）。再生できない環境があります。" % info.get("vcodec"))
    if info.get("pix_fmt") not in ("yuv420p", "yuvj420p"):
        issue("要修正", "色形式が yuv420p ではありません（%s）。QuickTime やスマホで再生できないことがあります。" % info.get("pix_fmt"))
    if abs(info["fps"] - float(E.snap_fps(info["fps_fraction"]))) > 0.01 or float(E.snap_fps(info["fps_fraction"])) not in (23.976023976023978, 24.0, 25.0, 29.97002997002997, 30.0, 50.0, 59.94005994005994, 60.0):
        issue("注意", "フレームレートが標準的な値ではありません（%.3f）。" % info["fps"])
    w, h = info["width"], info["height"]
    if a.target == "youtube":
        if min(w, h) < 1080:
            issue("注意", "解像度が 1080p 未満です（%d×%d）。" % (w, h))
        if h > w:
            issue("注意", "縦長の動画です。横長の本編なら向きを確かめてください。")
    elif a.target == "short":
        if abs(w / float(h) - 9 / 16.0) > 0.01:
            issue("要修正", "9:16 ではありません（%d×%d）。ショートは 1080×1920 が基本です。" % (w, h))
        elif h < 1920:
            issue("注意", "1080×1920 より小さい解像度です（%d×%d）。" % (w, h))
        if dur > 180:
            issue("要修正", "3 分を超えています（%.0f 秒）。YouTube ショートの上限は 3 分です。" % dur)
        elif dur > 60:
            issue("注意", "60 秒を超えています（%.0f 秒）。投稿先の上限を確かめてください。" % dur)
    # ---- 音
    if info["has_audio"]:
        loud = E.loudness(src)
        rep["audio"] = dict(loud, codec=info.get("acodec"), sample_rate=info.get("sample_rate"), channels=info.get("channels"))
        if a.target != "none":
            diff = loud["lufs"] - a.lufs
            if abs(diff) > 2.0:
                issue("要修正", "音の大きさが目標から %.1f LU ずれています（%.1f LUFS、目標 %.0f）。" % (diff, loud["lufs"], a.lufs))
            elif abs(diff) > 1.0:
                issue("注意", "音の大きさが目標から %.1f LU ずれています（%.1f LUFS、目標 %.0f）。" % (diff, loud["lufs"], a.lufs))
            if loud["true_peak"] > -0.3:
                issue("要修正", "ピークが高すぎます（%.1f dBTP）。音割れの恐れがあります。" % loud["true_peak"])
            elif loud["true_peak"] > -1.0:
                issue("注意", "ピークが高めです（%.1f dBTP）。−1 dBTP 以下が目安です。" % loud["true_peak"])
        levels = E.measure_levels(src)
        sil, clear = silences(levels, a.silence)
        rep["long_silences"] = sil[:20]
        if sil and clear:
            longest = max(sil, key=lambda s: s["end"] - s["start"])
            issue("注意", "%.1f 秒以上の無言が %d か所あります（最長 %s〜%s）。" % (a.silence, len(sil), E.fmt_time(longest["start"]), E.fmt_time(longest["end"])))
        sd = stream_durations(src)
        if "video" in sd and "audio" in sd and abs(sd["video"] - sd["audio"]) > 0.15:
            issue("注意", "映像と音声の長さが %.2f 秒ずれています（映像 %.2f / 音声 %.2f）。" % (sd["video"] - sd["audio"], sd["video"], sd["audio"]))
    else:
        rep["audio"] = None
        issue("要修正" if a.target != "none" else "注意", "音声トラックがありません。")
    # ---- 映像の異常
    black, freeze = detect_black_freeze(src, dur)
    rep["black_frames"] = black[:20]
    rep["frozen"] = freeze[:20]
    for b in black:
        where = "冒頭" if b["start"] < 0.1 else ("末尾" if b["end"] > dur - 0.2 else "途中")
        issue("注意" if where != "途中" else "要修正", "%sに真っ黒なコマがあります（%s〜%s）。" % (where, E.fmt_time(b["start"]), E.fmt_time(b["end"])))
    if freeze:
        issue("注意", "3 秒以上、映像が止まったままの区間が %d か所あります（最初は %s〜）。静止画を使っているなら問題ありません。" % (len(freeze), E.fmt_time(freeze[0]["start"])))
    # ---- 編集前との比較
    if a.before:
        b = E.probe(Path(a.before).expanduser())
        cmp_ = {"duration_before": round(b["duration"], 2), "duration_after": round(dur, 2),
                "shorter_by": round(b["duration"] - dur, 2)}
        if b["has_audio"]:
            bl = E.loudness(b["path"])
            cmp_["lufs_before"] = bl["lufs"]
            if info["has_audio"]:
                cmp_["lufs_after"] = rep["audio"]["lufs"]
        rep["compare"] = cmp_
    # ---- コマ一覧
    times, labels = [], []
    if a.telop:
        d = json.loads(Path(a.telop).expanduser().read_text(encoding="utf-8"))
        tl = d.get("telops", d) if isinstance(d, dict) else d
        tl = [t for t in tl if float(t["end"]) <= dur + 0.1]
        step = max(1, int(len(tl) / float(a.frames) + 0.999))
        for t in tl[::step][:a.frames]:
            mid = (float(t["start"]) + float(t["end"])) / 2
            times.append(mid)
            labels.append("#%s  %s" % (t.get("id", "?"), E.fmt_time(mid)))
        rep["sheet_note"] = "テロップ %d 枚のうち %d 枚の、表示中のコマを並べています。" % (len(tl), len(times))
    if not times:
        n = max(1, a.frames)
        times = [dur * (i + 0.5) / n for i in range(n)]
        labels = [E.fmt_time(t) for t in times]
    out_dir = Path(a.out).expanduser() if a.out else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = contact_sheet(src, info, times, labels, out_dir / (src.stem + "_検査.png"), tmp)
    rep["sheet"] = sheet
    rep["issues"] = issues
    rep["verdict"] = "要修正あり" if any(i["level"] == "要修正" for i in issues) else ("注意あり" if issues else "問題なし")
    rep["look_at"] = "コマ一覧の画像（sheet.png）を開いて、テロップが切れていないか・顔や大事な部分に重なっていないか・読みやすいかを目で確かめてください。数値では分からない部分です。"
    out_json = out_dir / (src.stem + "_検査.json")
    out_json.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    rep["report_json"] = str(out_json)
    E.result(rep)


if __name__ == "__main__":
    E.main_guard(main)
