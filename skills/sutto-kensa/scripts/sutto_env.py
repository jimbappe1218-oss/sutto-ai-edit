# -*- coding: utf-8 -*-
"""スッとAI編集 共通部品（各スキルの scripts/ に同じものが入っています）。

- ensure(): 必要な Python ライブラリが無ければ、専用の置き場（~/.sutto-ai-edit/venv）に入れてから
  同じスクリプトをそこで動かし直す。お使いの Python 本体には何も入れません。
- ffmpeg / ffprobe を探して実行する。動画の情報を読む。日本語フォントを探す。
- 最後に RESULT_JSON: {...} を 1 行で出す（AI が結果を読むため）。

Python 3.9 以降。標準ライブラリだけで動きます。
"""
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

HOME = Path(os.environ.get("SUTTO_AI_EDIT_HOME") or (Path.home() / ".sutto-ai-edit"))
VENV = HOME / "venv"
IS_WIN = os.name == "nt"


class SuttoError(Exception):
    """利用者に見せるエラー（日本語の説明つき）。"""


def fail(message, hint=None):
    out = {"ok": False, "error": message}
    if hint:
        out["hint"] = hint
    print("エラー: " + message, file=sys.stderr)
    if hint:
        print("対処: " + hint, file=sys.stderr)
    print("RESULT_JSON: " + json.dumps(out, ensure_ascii=False))
    sys.exit(1)


def result(data):
    data = dict(data)
    data.setdefault("ok", True)
    print("RESULT_JSON: " + json.dumps(data, ensure_ascii=False))


def main_guard(fn):
    """main() を包んで、エラーを日本語の 1 行と RESULT_JSON にする。"""
    try:
        fn()
    except SuttoError as e:
        args = e.args
        fail(args[0], args[1] if len(args) > 1 else None)
    except KeyboardInterrupt:
        fail("中断されました")


# ---------------------------------------------------------------- ライブラリ

def _venv_python():
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python3")


def _can_import(names):
    import importlib
    for n in names:
        try:
            importlib.import_module(n)
        except Exception:
            return False
    return True


def ensure(packages):
    """packages: {import 名: pip 名}。無ければ専用の置き場に入れて、そこで動かし直す。"""
    if _can_import(packages.keys()):
        return
    py = _venv_python()
    here = Path(sys.executable).resolve() if sys.executable else None
    in_venv = py.exists() and here == py.resolve()
    if os.environ.get("SUTTO_REEXEC") == "1" and in_venv:
        # 置き場の Python で動いているのに足りない → その場で入れる
        _pip_install(py, packages.values())
        if _can_import(packages.keys()):
            return
        raise SuttoError("必要なライブラリを入れられませんでした: " + ", ".join(packages.values()),
                         "インターネットにつながっているか確かめて、もう一度実行してください。")
    if not py.exists():
        print("初回の準備: 専用の置き場を作ります（%s）" % VENV, file=sys.stderr)
        HOME.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, "-m", "venv", str(VENV)], capture_output=True, text=True)
        if r.returncode != 0 or not py.exists():
            raise SuttoError("Python の置き場（venv）を作れませんでした。", (r.stderr or "").strip()[-300:])
    check = subprocess.run([str(py), "-c", "import " + ", ".join(packages.keys())], capture_output=True)
    if check.returncode != 0:
        _pip_install(py, packages.values())
    env = dict(os.environ, SUTTO_REEXEC="1")
    r = subprocess.run([str(py)] + sys.argv, env=env)
    sys.exit(r.returncode)


def _pip_install(py, names):
    names = list(names)
    print("初回の準備: ライブラリを入れます（%s）。1〜数分かかります" % ", ".join(names), file=sys.stderr)
    r = subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"] + names,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SuttoError("ライブラリを入れられませんでした: " + ", ".join(names),
                         (r.stderr or "").strip()[-400:] or "インターネット接続を確かめてください。")


# ---------------------------------------------------------------- ffmpeg

_EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
_cache = {}


def tool(name):
    if name in _cache:
        return _cache[name]
    p = shutil.which(name)
    if not p:
        for d in _EXTRA_PATHS:
            c = Path(d) / name
            if c.exists():
                p = str(c)
                break
    if not p:
        raise SuttoError("%s が見つかりません。" % name,
                         "Mac: ターミナルで brew install ffmpeg ／ Windows: winget install Gyan.FFmpeg を実行してから、やり直してください。")
    _cache[name] = p
    return p


def run(cmd, what="ffmpeg", capture=True, input_bytes=None):
    """コマンドを実行。失敗したら末尾のメッセージを付けて SuttoError。"""
    r = subprocess.run([str(c) for c in cmd], capture_output=capture, input=input_bytes)
    if r.returncode != 0:
        tail = ""
        if capture and r.stderr:
            tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
            tail = " / ".join(t.strip() for t in tail)
        raise SuttoError("%s の実行に失敗しました。" % what, tail[-600:])
    return r


def ff(args, what="ffmpeg"):
    return run([tool("ffmpeg"), "-hide_banner", "-nostdin", "-y"] + list(args), what)


def has_filter(name):
    key = "filters"
    if key not in _cache:
        r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True)
        names = set()
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and "->" in parts[2]:
                names.add(parts[1])
        _cache[key] = names
    return name in _cache[key]


def has_encoder(name):
    key = "encoders"
    if key not in _cache:
        r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True)
        _cache[key] = set(l.split()[1] for l in r.stdout.splitlines() if len(l.split()) >= 2)
    return name in _cache[key]


def ffmpeg_major():
    if "major" not in _cache:
        r = subprocess.run([tool("ffmpeg"), "-version"], capture_output=True, text=True)
        try:
            v = r.stdout.split()[2]
            _cache["major"] = int(v.lstrip("n").split(".")[0])
        except Exception:
            _cache["major"] = 0
    return _cache["major"]


def filter_script_args(graph, workdir, name="graph.txt"):
    """長いフィルタをファイルで渡す（Windows のコマンド長制限を避ける）。"""
    p = Path(workdir) / name
    p.write_text(graph, encoding="utf-8")
    if ffmpeg_major() >= 7:
        return ["-/filter_complex", str(p)]
    return ["-filter_complex_script", str(p)]


def video_encode_args(quality=18):
    """書き出しの設定（H.264 / yuv420p / どの再生環境でも開ける形）。"""
    if has_encoder("libx264"):
        v = ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality), "-pix_fmt", "yuv420p"]
    elif has_encoder("h264_videotoolbox"):
        v = ["-c:v", "h264_videotoolbox", "-b:v", "12M", "-pix_fmt", "yuv420p"]
    else:
        raise SuttoError("H.264 で書き出せる ffmpeg ではありません。", "libx264 入りの ffmpeg を入れてください。")
    return v + ["-movflags", "+faststart"]


AUDIO_ENCODE = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]


def probe(path):
    """動画・音声ファイルの情報。"""
    path = Path(path)
    if not path.exists():
        raise SuttoError("ファイルがありません: %s" % path)
    r = run([tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], "ffprobe")
    d = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    info = {"path": str(path), "duration": 0.0, "has_video": False, "has_audio": False}
    fmt = d.get("format", {})
    try:
        info["duration"] = float(fmt.get("duration", 0) or 0)
    except ValueError:
        pass
    info["size_bytes"] = int(fmt.get("size", 0) or 0)
    info["bit_rate"] = int(fmt.get("bit_rate", 0) or 0)
    for s in d.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"]:
            if s.get("disposition", {}).get("attached_pic"):
                continue
            info["has_video"] = True
            w, h = int(s.get("width", 0)), int(s.get("height", 0))
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    try:
                        rot = int(sd["rotation"])
                    except (TypeError, ValueError):
                        rot = 0
            if abs(rot) in (90, 270):
                w, h = h, w
            info["width"], info["height"] = w, h
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "30/1"
            rr = s.get("r_frame_rate") or fr
            try:
                f = Fraction(fr) if Fraction(fr) > 0 else Fraction(rr)
            except (ZeroDivisionError, ValueError):
                f = Fraction(30)
            info["fps_fraction"] = snap_fps(f)
            info["fps"] = float(info["fps_fraction"])
            info["fps_raw"] = fr
            info["vcodec"] = s.get("codec_name")
            info["pix_fmt"] = s.get("pix_fmt")
            if not info["duration"]:
                try:
                    info["duration"] = float(s.get("duration", 0) or 0)
                except ValueError:
                    pass
        elif s.get("codec_type") == "audio" and not info["has_audio"]:
            info["has_audio"] = True
            info["acodec"] = s.get("codec_name")
            info["sample_rate"] = int(s.get("sample_rate", 48000) or 48000)
            info["channels"] = int(s.get("channels", 2) or 2)
    return info


_STD_FPS = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
            Fraction(50), Fraction(60000, 1001), Fraction(60)]


def snap_fps(f):
    """29.97 などの標準値に近ければ、その値にそろえる（スマホ撮影の 29.98 などへの対策）。"""
    best = min(_STD_FPS, key=lambda x: abs(float(x) - float(f)))
    if abs(float(best) - float(f)) < 0.05:
        return best
    return Fraction(f).limit_denominator(1001)


def fps_str(fr):
    return "%d/%d" % (fr.numerator, fr.denominator)


def json_info(info):
    """probe() の結果から JSON に書ける部分だけ取り出す。"""
    return {k: v for k, v in info.items() if k != "fps_fraction"}


# ---------------------------------------------------------------- 出力先・作業場所

def out_path(src, suffix, ext=None, out=None):
    """出力ファイル名。指定が無ければ「元の名前_◯◯.mp4」を同じフォルダに作る。元のファイルは上書きしない。"""
    src = Path(src)
    if out:
        p = Path(out).expanduser()
        if p.is_dir():
            p = p / (src.stem + "_" + suffix + (ext or ".mp4"))
    else:
        p = src.with_name(src.stem + "_" + suffix + (ext or ".mp4"))
    if p.resolve() == src.resolve():
        raise SuttoError("出力先が元のファイルと同じです。別の名前を指定してください。")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def work_dir(name):
    """作業用の一時フォルダ。実行ごとに別の場所を使い（同時に 2 つ動かしても混ざらない）、終わったら自分で片付ける。"""
    import atexit
    d = HOME / "work" / ("%s-%d" % (name, os.getpid()))
    d.mkdir(parents=True, exist_ok=True)
    if os.environ.get("SUTTO_KEEP_WORK") != "1":
        atexit.register(shutil.rmtree, str(d), True)
    return d


# ---------------------------------------------------------------- フォント

def _listdir_nfc(d):
    try:
        return [(unicodedata.normalize("NFC", n), n) for n in os.listdir(d)]
    except OSError:
        return []


def find_font(weight="bold", explicit=None):
    """日本語フォントを探す。weight: bold / heavy / regular。explicit: ファイルのパスまたは名前の一部。"""
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
    dirs = []
    if sys.platform == "darwin":
        dirs = [str(Path.home() / "Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts", "/System/Library/Fonts/Supplemental"]
        prefer = {
            "heavy": ["ヒラギノ角ゴシック W8", "ヒラギノ角ゴシック W7", "ヒラギノ角ゴシック W6"],
            "bold": ["ヒラギノ角ゴシック W6", "ヒラギノ角ゴシック W7", "ヒラギノ角ゴシック W5"],
            "regular": ["ヒラギノ角ゴシック W4", "ヒラギノ角ゴシック W3", "ヒラギノ角ゴシック W5"],
        }[weight if weight in ("heavy", "bold", "regular") else "bold"]
        prefer += ["ヒラギノ角ゴシック W6", "ヒラギノ角ゴシック W3", "Hiragino Sans GB", "Arial Unicode"]
    elif IS_WIN:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs = [os.path.join(windir, "Fonts"), str(Path.home() / "AppData/Local/Microsoft/Windows/Fonts")]
        prefer = {"regular": ["YuGothM", "meiryo.", "msgothic"]}.get(weight, ["YuGothB", "meiryob", "YuGothM", "meiryo.", "msgothic"])
    else:
        dirs = ["/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"), str(Path.home() / ".local/share/fonts")]
        prefer = ["NotoSansCJK-Bold", "NotoSansCJKjp-Bold", "NotoSansJP-Bold", "NotoSansCJK", "NotoSansJP", "IPAexGothic", "ipaexg", "TakaoGothic"]
    files = []
    for d in dirs:
        if sys.platform.startswith("linux"):
            for root, _, names in os.walk(d):
                files += [(unicodedata.normalize("NFC", n), os.path.join(root, n)) for n in names]
        else:
            files += [(nfc, os.path.join(d, raw)) for nfc, raw in _listdir_nfc(d)]
    files = [(n, p) for n, p in files if n.lower().endswith((".ttc", ".ttf", ".otf"))]
    if explicit:
        key = unicodedata.normalize("NFC", explicit).lower()
        for n, p in files:
            if key in n.lower():
                return p
        raise SuttoError("指定のフォントが見つかりません: %s" % explicit, "フォントファイルのパス（.ttf / .otf / .ttc）を指定してください。")
    for want in prefer:
        for n, p in files:
            if want.lower() in n.lower():
                return p
    raise SuttoError("日本語フォントが見つかりません。", "--font にフォントファイル（.ttf / .otf / .ttc）のパスを指定してください。")


# ---------------------------------------------------------------- 時刻

def fmt_time(t):
    t = max(0.0, float(t))
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return "%d:%02d:%05.2f" % (h, m, s) if h else "%d:%05.2f" % (m, s)


def parse_time(s):
    """秒（12.5）または 時:分:秒（1:02:03.5 / 2:03）を秒にする。"""
    if s is None:
        return None
    s = str(s).strip()
    if ":" not in s:
        return float(s)
    parts = [float(x) for x in s.split(":")]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


# ---------------------------------------------------------------- 音の測定

LEVEL_WIN = 0.02  # 音量を測る刻み（秒）


def measure_levels(src, what="音量の測定"):
    """20 ミリ秒ごとの音の大きさ（RMS、dB）の列。"""
    import math
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-i", str(src), "-vn", "-map", "0:a:0",
           "-af", "aresample=16000,aformat=channel_layouts=mono,asetnsamples=n=320:p=0,"
                  "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
                  "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
           "-f", "null", "-"]
    r = run(cmd, what)
    levels = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            try:
                x = float(line.split("=", 1)[1].strip())
            except ValueError:
                x = -120.0
            levels.append(-120.0 if (math.isnan(x) or math.isinf(x)) else max(-120.0, x))
    if not levels:
        raise SuttoError("音声を読めませんでした。", "音声トラックのあるファイルか確かめてください。")
    return levels


def percentile(sorted_vals, p):
    i = min(len(sorted_vals) - 1, max(0, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def speech_threshold(levels):
    """声と無言の境目（dB）。戻り値: (境目, 静かなときの大きさ, 声の大きさ, はっきり分かれているか)"""
    s = sorted(levels)
    floor = percentile(s, 0.10)
    speech = percentile(s, 0.90)
    if speech - floor < 12:
        return max(-60.0, speech - 25), floor, speech, False
    th = floor + (speech - floor) * 0.35
    th = max(min(th, speech - 12), -60.0)
    return th, floor, speech, True


def mean_db(values):
    """dB の列の平均（エネルギーで平均する）。"""
    import math
    vals = [10 ** (v / 10.0) for v in values if v > -119]
    if not vals:
        return -120.0
    return 10 * math.log10(sum(vals) / len(vals))


def loudness(src, what="ラウドネスの測定"):
    """全体のラウドネス（LUFS）、トゥルーピーク（dBTP）、ラウドネスレンジ（LU）。"""
    r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(src), "-vn", "-map", "0:a:0",
                        "-af", "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True)
    if r.returncode != 0:
        raise SuttoError("%s に失敗しました。" % what, r.stderr.decode("utf-8", "replace").strip()[-300:])
    text = r.stderr.decode("utf-8", "replace")
    i = text.rfind("{")
    j = text.rfind("}")
    try:
        d = json.loads(text[i:j + 1])
        f = lambda k: float(d[k]) if d[k] not in ("-inf", "inf") else -99.0  # noqa: E731
        return {"lufs": f("input_i"), "true_peak": f("input_tp"), "lra": f("input_lra")}
    except Exception:  # noqa: BLE001
        raise SuttoError("%s の結果を読めませんでした。" % what)
