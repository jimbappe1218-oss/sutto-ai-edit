#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""無音カット（ジェットカット）。話していない部分を詰めた動画を作る。

    python3 muon_cut.py 入力.mp4                     … 既定の設定でカット
    python3 muon_cut.py 入力.mp4 --dry-run           … 何秒減るかだけ調べる（書き出さない）
    python3 muon_cut.py 入力.mp4 --min-silence 0.8 --keep 0.15

しくみ
  1. 音の大きさを 20 ミリ秒ごとに測る（ffmpeg astats）
  2. 「声の大きさ」と「静かなときの大きさ」から境目を自動で決める（--threshold で手動指定も可）
  3. 境目より静かな時間が --min-silence 秒以上続いたら無言とみなし、前後 --keep 秒を残して詰める
  4. 映像はフレーム単位、音声はサンプル単位で同じ位置を切るので、音ズレしない
  5. つなぎ目の音に 8 ミリ秒のフェードを入れて、プチッというノイズを防ぐ
"""
import argparse
import array
import json
import math
import subprocess
import sys
import wave
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sutto_env as E  # noqa: E402

WIN = E.LEVEL_WIN


def find_keep(levels, th, min_silence, keep, min_clip, duration):
    """残す区間（秒）のリストを返す。"""
    loud = [lv > th for lv in levels]
    # 20〜60ms の一瞬の物音は声とみなさない / 一瞬の谷は埋める
    n = len(loud)
    sil, i = [], 0
    while i < n:
        if not loud[i]:
            j = i
            while j < n and not loud[j]:
                j += 1
            sil.append([i * WIN, j * WIN])
            i = j
        else:
            i += 1
    # 60ms 未満の音は無言の一部として扱う（クリック音・リップノイズ対策）
    merged = []
    for s in sil:
        if merged and s[0] - merged[-1][1] < 0.06:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    cuts = []
    for s, e in merged:
        e = min(e, duration)
        if e - s < min_silence:
            continue
        cs = s + (0.0 if s <= 0.001 else keep)          # 冒頭の無言は頭から切る
        ce = e - (0.0 if e >= duration - 0.021 else keep)  # 末尾の無言は最後まで切る
        if ce - cs >= 0.05:
            cuts.append((cs, ce))
    keeps, pos = [], 0.0
    for cs, ce in cuts:
        if cs - pos >= min_clip:
            keeps.append((pos, cs))
        elif keeps and cs > pos:
            # 短すぎる断片は捨てる
            pass
        pos = ce
    if duration - pos >= min_clip:
        keeps.append((pos, duration))
    return keeps, cuts


def balanced_sum(terms):
    """a+b+c+… を ((a+b)+(c+d)) の形にまとめる。ffmpeg は 100 個を超える足し算を 1 列に並べると式を読めないため。"""
    if len(terms) == 1:
        return terms[0]
    m = len(terms) // 2
    return "(%s+%s)" % (balanced_sum(terms[:m]), balanced_sum(terms[m:]))


def snap_frames(keeps, fps, total_frames):
    """フレーム番号にそろえる。[(開始フレーム, 終了フレーム（含まない）)]"""
    out = []
    for s, e in keeps:
        a = max(0, int(math.floor(s * fps + 1e-6)))
        b = min(total_frames, int(math.ceil(e * fps - 1e-6)))
        if out and a <= out[-1][1]:
            a = out[-1][1]
        if b - a >= 1:
            if out and a == out[-1][1]:
                out[-1] = (out[-1][0], b)
            else:
                out.append((a, b))
    return out


def cut_audio(src, segs, fps, sr, channels, wav_out, tmp):
    """音声を PCM にして、フレームと同じ位置で切ってつなぐ。つなぎ目に短いフェード。"""
    raw = tmp / "audio_full.wav"
    E.ff(["-v", "error", "-i", str(src), "-vn", "-map", "0:a:0", "-ar", str(sr), "-ac", str(channels),
          "-c:a", "pcm_s16le", str(raw)], "音声の取り出し")
    fade = int(sr * 0.008)
    with wave.open(str(raw), "rb") as r, wave.open(str(wav_out), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        total = r.getnframes()
        written = 0
        frames_done = 0
        for a, b in segs:
            s0 = int(round(Fraction(a) / fps * sr))
            frames_done += b - a
            want_end = int(round(Fraction(frames_done) / fps * sr))  # 出力側の通算サンプル数に合わせる（誤差をためない）
            n = want_end - written
            r.setpos(min(s0, total))
            data = array.array("h")
            data.frombytes(r.readframes(max(0, min(n, total - s0))))
            if len(data) < n * channels:
                data.extend([0] * (n * channels - len(data)))
            k = min(fade, n // 2)
            for i in range(k):
                g = i / float(k)
                for c in range(channels):
                    data[i * channels + c] = int(data[i * channels + c] * g)
                    j = (n - 1 - i) * channels + c
                    data[j] = int(data[j] * g)
            w.writeframes(data.tobytes())
            written += n
    return written


def main():
    ap = argparse.ArgumentParser(description="無音カット")
    ap.add_argument("input")
    ap.add_argument("--min-silence", type=float, default=0.5, help="これ以上続く無言を詰める（秒）")
    ap.add_argument("--keep", type=float, default=0.12, help="声の前後に残す間（秒）")
    ap.add_argument("--threshold", default="auto", help="境目の音量（dB）。例 -35。auto で自動")
    ap.add_argument("--min-clip", type=float, default=0.25, help="これより短い断片は残さない（秒）")
    ap.add_argument("--dry-run", action="store_true", help="調べるだけで書き出さない")
    ap.add_argument("--out", help="出力ファイル（省略時: 元の名前_無音カット.mp4）")
    ap.add_argument("--quality", type=int, default=18, help="画質（小さいほど高画質。既定 18）")
    a = ap.parse_args()

    src = Path(a.input).expanduser()
    info = E.probe(src)
    if not info["has_audio"]:
        raise E.SuttoError("音声トラックがありません。無音カットは音を手がかりにするため、処理できません。")
    if a.keep * 2 >= a.min_silence:
        raise E.SuttoError("--keep の 2 倍が --min-silence 以上になっています。",
                           "例: --min-silence 0.5 なら --keep は 0.2 未満にしてください。")
    levels = E.measure_levels(src)
    duration = info["duration"] or len(levels) * WIN
    if a.threshold == "auto":
        th, floor, speech, clear = E.speech_threshold(levels)
    else:
        th = float(a.threshold)
        s = sorted(levels)
        floor, speech, clear = E.percentile(s, 0.10), E.percentile(s, 0.90), True

    keeps, cuts = find_keep(levels, th, a.min_silence, a.keep, a.min_clip, duration)
    has_video = info["has_video"]
    fps = info.get("fps_fraction", Fraction(30))
    total_frames = int(math.floor(duration * fps + 0.5)) if has_video else int(duration * 100)
    segs = snap_frames(keeps, fps if has_video else Fraction(100), total_frames)
    unit = fps if has_video else Fraction(100)
    kept = float(sum(b - a for a, b in segs) / unit)
    rep = {
        "input": str(src), "duration_before": round(duration, 2), "duration_after": round(kept, 2),
        "removed_seconds": round(duration - kept, 2), "removed_percent": round((duration - kept) / duration * 100, 1) if duration else 0,
        "cuts": len(cuts), "threshold_db": round(th, 1), "noise_floor_db": round(floor, 1), "speech_level_db": round(speech, 1),
        "min_silence": a.min_silence, "keep": a.keep,
        "longest_removed": round(max([e - s for s, e in cuts] or [0]), 2),
        "segments": [{"start": round(float(x / unit), 3), "end": round(float(y / unit), 3)} for x, y in segs],
    }
    warnings = []
    if not clear:
        warnings.append("声と無言の音量差が小さく、境目を自動で決めにくい素材です（BGM 入り・雑音が大きいなど）。--threshold を手で指定すると安定します。")
    if not cuts:
        warnings.append("詰める無言が見つかりませんでした。--min-silence を小さくするか、--threshold を上げてください。")
    if duration and (duration - kept) / duration > 0.6:
        warnings.append("6 割以上が無言と判定されました。境目（threshold_db）が高すぎないか確かめてください。")
    rep["warnings"] = warnings

    if a.dry_run or not cuts:
        rep["dry_run"] = True
        E.result(rep)
        return

    out = E.out_path(src, "無音カット", ".mp4" if has_video else ".wav", a.out)
    tmp = E.work_dir("cut")
    sr = 48000
    ch = min(2, info.get("channels", 2))
    wav = tmp / "audio_cut.wav"
    cut_audio(src, segs, unit, sr, ch, wav, tmp)
    if has_video:
        expr = balanced_sum(["between(n,%d,%d)" % (x, y - 1) for x, y in segs])
        graph = "[0:v:0]fps=%s,select='%s',setpts=N/(%s)/TB[v]" % (E.fps_str(fps), expr, E.fps_str(fps))
        E.ff(["-v", "error", "-i", str(src), "-i", str(wav)] + E.filter_script_args(graph, tmp) +
             ["-map", "[v]", "-map", "1:a:0", "-r", E.fps_str(fps)] + E.video_encode_args(a.quality) + E.AUDIO_ENCODE +
             ["-shortest", str(out)], "無音カットの書き出し")
    else:
        Path(out).write_bytes(wav.read_bytes())
    after = E.probe(out)
    rep["output"] = str(out)
    rep["duration_output"] = round(after["duration"], 2)
    cuts_json = Path(str(out) + ".cuts.json")
    cuts_json.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    rep["cuts_json"] = str(cuts_json)
    if abs(after["duration"] - kept) > 0.12:
        rep["warnings"].append("書き出した長さ（%.2f 秒）が計算（%.2f 秒）と合いません。" % (after["duration"], kept))
    short = dict(rep)
    if len(short["segments"]) > 12:
        short["segments"] = short["segments"][:12] + ["…（全件は cuts_json に）"]
    E.result(short)


if __name__ == "__main__":
    E.main_guard(main)
