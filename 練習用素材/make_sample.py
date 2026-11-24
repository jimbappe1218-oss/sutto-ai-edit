#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""練習用の素材を、お使いの PC の中で作ります（配布物に他人の映像・音声は入っていません）。

    python3 make_sample.py                 … 練習用素材.mp4 と 練習用BGM.wav を作る
    python3 make_sample.py --voice say     … Mac の読み上げ音声（say コマンド）で話させる
    python3 make_sample.py --voice noise   … 声の代わりに「声に似せた雑音」を使う（どの PC でも動く）

できるもの（このフォルダの中）:
  練習用素材.mp4   … 1920×1080・30fps・約 40 秒。話している間だけ口が動く人形の映像。途中に長い無言あり
  練習用BGM.wav    … 20 秒の自作 BGM（ループして使える）
  練習用原稿.txt   … 話している内容（文字起こしの答え合わせ用）

Mac の読み上げ音声は、ご自身の練習の範囲でお使いください（公開する動画には使わないでください）。
"""
import argparse
import math
import random
import struct
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sutto_env as E  # noqa: E402

HERE = Path(__file__).resolve().parent
SR = 48000
FPS = 30
W, H = 1920, 1080

# (文, そのあとの無言の秒数)
LINES = [
    ("こんにちは。今日は、動画編集を楽にする方法を紹介します。", 0.9),
    ("まず、無言の部分を自動でカットします。", 2.6),
    ("えーっと、次に、話した内容をテロップにします。", 0.35),
    ("テロップは、文節の切れ目で改行すると読みやすくなります。", 1.6),
    ("最後に、音楽を小さく重ねて、声の大きさをそろえます。", 0.5),
    ("これで完成です。ご視聴ありがとうございました。", 1.2),
]
HEAD_SILENCE = 1.4


def synth_say(text, path, voice):
    r = subprocess.run(["say", "-v", voice, "-r", "185", "-o", str(path), "--data-format=LEI16@%d" % SR, text],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise E.SuttoError("say コマンドで音声を作れませんでした。", (r.stderr or "").strip()[-200:] + " ／ --voice noise をお試しください。")
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        data = struct.unpack("<%dh" % (n * w.getnchannels()), w.readframes(n))
        if w.getnchannels() == 2:
            data = data[::2]
    return [x / 32768.0 for x in data]


def synth_noise(text, rng):
    """声に似せた雑音（音節ごとに大きさが揺れる、こもった雑音）。"""
    dur = 0.16 * len(text.replace("。", "").replace("、", "")) + 0.2
    n = int(dur * SR)
    out, lp, lp2 = [], 0.0, 0.0
    for i in range(n):
        t = i / SR
        syl = 0.55 + 0.45 * math.sin(2 * math.pi * 5.2 * t + 0.6 * math.sin(2 * math.pi * 0.7 * t))
        edge = min(1.0, t / 0.04, (dur - t) / 0.06)
        x = rng.uniform(-1, 1) + 0.6 * math.sin(2 * math.pi * (140 + 30 * math.sin(2 * math.pi * 1.3 * t)) * t)
        lp += 0.12 * (x - lp)
        lp2 += 0.12 * (lp - lp2)
        out.append(max(0.0, syl) ** 2 * max(0.0, edge) * lp2 * 1.6)
    return out


def build_voice(mode, voice, rng, tmp):
    track = [0.0] * int(HEAD_SILENCE * SR)
    spans = []
    for i, (text, gap) in enumerate(LINES):
        if mode == "say":
            s = synth_say(text, tmp / ("line%d.wav" % i), voice)
        else:
            s = synth_noise(text, rng)
        peak = max(1e-6, max(abs(x) for x in s))
        s = [x / peak * 0.5 for x in s]
        start = len(track) / SR
        track += s
        spans.append((round(start, 3), round(len(track) / SR, 3), text))
        track += [0.0] * int(gap * SR)
    # うすい環境音（完全な無音にしない。実際の収録に近づける）
    lp = 0.0
    for i in range(len(track)):
        lp += 0.05 * (rng.uniform(-1, 1) - lp)
        track[i] += lp * 0.006
    return track, spans


def write_wav(path, samples, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(struct.pack("<%dh" % len(samples), *[max(-32767, min(32767, int(x * 32767))) for x in samples]))


def build_bgm(seconds=20.0):
    """自作の BGM。4 小節のコード進行を、やわらかい音色で鳴らす（ループできる長さ）。"""
    chords = [[261.63, 329.63, 392.00], [220.00, 261.63, 329.63], [174.61, 220.00, 261.63], [196.00, 246.94, 293.66]]
    bar = seconds / 8
    n = int(seconds * SR)
    out = [0.0] * n
    for b in range(8):
        notes = chords[b % 4]
        for k in range(8):  # 8 分音符のアルペジオ
            f = notes[k % 3] * (2 if k % 4 == 3 else 1)
            t0 = b * bar + k * bar / 8
            length = bar / 8 * 1.8
            i0 = int(t0 * SR)
            for i in range(int(length * SR)):
                j = i0 + i
                if j >= n:
                    j -= n  # 末尾の余韻は頭に回す → 継ぎ目なくループできる
                t = i / SR
                env = min(1.0, t / 0.01) * math.exp(-t * 3.2)
                out[j] += 0.16 * env * (math.sin(2 * math.pi * f * t) + 0.3 * math.sin(4 * math.pi * f * t))
        # ベース
        f = notes[0] / 2
        i0 = int(b * bar * SR)
        for i in range(int(bar * SR)):
            t = i / SR
            env = min(1.0, t / 0.02) * min(1.0, (bar - t) / 0.05)
            out[i0 + i] += 0.12 * env * math.sin(2 * math.pi * f * t)
    peak = max(abs(x) for x in out)
    return [x / peak * 0.7 for x in out]


def envelope(track):
    """フレームごとの声の大きさ（0〜1）。口の開き具合に使う。"""
    step = SR // FPS
    env = []
    for i in range(0, len(track), step):
        chunk = track[i:i + step]
        env.append(math.sqrt(sum(x * x for x in chunk) / max(1, len(chunk))))
    top = max(env) or 1.0
    return [min(1.0, e / top * 2.2) if e / top > 0.06 else 0.0 for e in env]


def render_video(track, out_mp4, wav_path):
    from PIL import Image, ImageDraw
    env = envelope(track)
    frames = len(env)
    # 背景（動かない部分）を 1 回だけ描く
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(238 - 26 * k), int(232 - 30 * k), int(220 - 34 * k)))
    d.rounded_rectangle([1180, 110, 1760, 560], 24, fill=(176, 212, 238), outline=(250, 250, 248), width=18)   # 窓
    d.rectangle([0, 800, W, H], fill=(150, 108, 78))                                                           # 机
    d.rectangle([0, 800, W, 822], fill=(170, 126, 92))
    d.rounded_rectangle([250, 560, 330, 800], 12, fill=(196, 120, 86))                                         # 鉢
    for dx, dy, r in [(-70, -120, 74), (40, -150, 84), (0, -230, 70), (-40, -60, 60), (60, -70, 56)]:
        d.ellipse([290 + dx - r, 560 + dy - r, 290 + dx + r, 560 + dy + r], fill=(92, 150, 104))
    d.rounded_rectangle([720, 600, 1200, 1000], 120, fill=(64, 110, 190))                                      # 体
    d.ellipse([760, 250, 1160, 650], fill=(246, 214, 186))                                                     # 顔
    d.pieslice([750, 230, 1170, 560], 180, 360, fill=(70, 54, 46))                                             # 髪
    d.rounded_rectangle([1320, 700, 1660, 800], 10, fill=(60, 64, 72))                                         # ノート PC
    d.rounded_rectangle([1350, 520, 1630, 706], 10, fill=(84, 90, 100))

    ff = subprocess.Popen([E.tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
                           "-i", str(wav_path)] + E.video_encode_args(20) + E.AUDIO_ENCODE + ["-shortest", str(out_mp4)],
                          stdin=subprocess.PIPE)
    mouth = 0.0
    for n in range(frames):
        t = n / FPS
        im = bg.copy()
        d = ImageDraw.Draw(im)
        # 雲（ゆっくり流れる）
        for k, (base, y, s) in enumerate([(0, 210, 1.0), (300, 330, 0.7)]):
            x = 1200 + ((base + t * 14 * (1 + k * 0.4)) % 640) - 60
            for dx, r in [(0, 34), (40, 46), (86, 36)]:
                cx, r2 = x + dx * s, r * s
                if 1210 < cx - r2 and cx + r2 < 1740:
                    d.ellipse([cx - r2, y - r2, cx + r2, y + r2], fill=(250, 252, 255))
        # 目（ときどき瞬き）
        blink = (n % 96) in (0, 1, 2)
        for ex in (880, 1040):
            if blink:
                d.line([(ex - 22, 430), (ex + 22, 430)], fill=(50, 40, 36), width=8)
            else:
                d.ellipse([ex - 18, 406, ex + 18, 454], fill=(50, 40, 36))
        # 口（声の大きさで開く。少しなめらかに追従）
        mouth += 0.55 * (env[n] - mouth)
        oh = int(6 + 62 * mouth)
        d.ellipse([960 - 46, 540 - oh // 2, 960 + 46, 540 + oh // 2], fill=(150, 60, 60))
        # 体の小さな揺れ（静止画に見えないように）
        sway = int(4 * math.sin(2 * math.pi * 0.25 * t))
        d.ellipse([930 + sway, 700, 990 + sway, 760], fill=(250, 250, 250))
        ff.stdin.write(im.tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise E.SuttoError("練習用の動画を書き出せませんでした。")


def main():
    ap = argparse.ArgumentParser(description="練習用の素材を作る")
    ap.add_argument("--voice", choices=["auto", "say", "noise"], default="auto")
    ap.add_argument("--say-voice", default="Kyoko")
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    E.ensure({"PIL": "pillow"})
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    tmp = E.work_dir("sample")
    mode = a.voice
    if mode == "auto":
        mode = "say" if sys.platform == "darwin" else "noise"
    rng = random.Random(7)
    track, spans = build_voice(mode, a.say_voice, rng, tmp)
    wav = tmp / "voice.wav"
    write_wav(wav, track)
    mp4 = out / "練習用素材.mp4"
    render_video(track, mp4, wav)
    bgm = out / "練習用BGM.wav"
    write_wav(bgm, build_bgm())
    (out / "練習用原稿.txt").write_text("\n".join("%.2f〜%.2f  %s" % s for s in spans) + "\n", encoding="utf-8")
    E.result({"video": str(mp4), "bgm": str(bgm), "voice": mode, "duration": round(len(track) / SR, 2),
              "speech": [{"start": s, "end": e, "text": t} for s, e, t in spans]})


if __name__ == "__main__":
    E.main_guard(main)
