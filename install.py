#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スッとAI編集 のスキルを、Claude Code のスキル置き場に入れる。

    python3 install.py              … ~/.claude/skills/ に入れる（同じ名前の「sutto-」スキルは新しいもので置き換える）
    python3 install.py --check      … 必要なもの（ffmpeg・Python・Node.js）がそろっているか調べるだけ
    python3 install.py --dest 場所  … 別の場所に入れる（プロジェクトの .claude/skills など）
    python3 install.py --remove     … 入れたスキルを取り除く（「sutto-」で始まるフォルダだけ）

ほかのスキルや設定には触りません。インターネットには接続しません。
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "skills"


def which(name):
    p = shutil.which(name)
    if p:
        return p
    for d in ("/opt/homebrew/bin", "/usr/local/bin"):
        if (Path(d) / name).exists():
            return str(Path(d) / name)
    return None


def version(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (r.stdout or r.stderr).strip().splitlines()[0][:60]
    except Exception:  # noqa: BLE001
        return None


def check():
    items = []
    ff = which("ffmpeg")
    items.append({"name": "ffmpeg", "ok": bool(ff), "detail": version([ff, "-version"]) if ff else None,
                  "need": "必須", "how": "Mac: brew install ffmpeg ／ Windows: winget install Gyan.FFmpeg"})
    fp = which("ffprobe")
    items.append({"name": "ffprobe", "ok": bool(fp), "detail": "あり" if fp else None, "need": "必須", "how": "ffmpeg と一緒に入ります"})
    ok_py = sys.version_info >= (3, 9)
    items.append({"name": "Python", "ok": ok_py, "detail": sys.version.split()[0], "need": "必須（3.9 以降）", "how": "https://www.python.org/ から入れる"})
    node = which("node")
    items.append({"name": "Node.js", "ok": bool(node), "detail": version([node, "-v"]) if node else None,
                  "need": "「動くテロップ」を使うときだけ（18 以降）", "how": "https://nodejs.org/ から LTS 版を入れる"})
    return items


def main():
    ap = argparse.ArgumentParser(description="スッとAI編集 の導入")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dest")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()
    dest = Path(a.dest).expanduser() if a.dest else Path.home() / ".claude" / "skills"
    result = {"ok": True, "dest": str(dest), "requirements": check()}

    if a.remove:
        removed = []
        if dest.exists():
            for d in sorted(dest.iterdir()):
                if d.is_dir() and d.name.startswith("sutto-") and (d / "SKILL.md").exists():
                    shutil.rmtree(d)
                    removed.append(d.name)
        result["removed"] = removed
        result["note"] = "ライブラリの置き場（~/.sutto-ai-edit）は残っています。不要ならフォルダごと削除してください。"
    elif not a.check:
        if not SRC.exists():
            print("エラー: skills フォルダが見つかりません。zip を解凍したフォルダの中で実行してください。", file=sys.stderr)
            print("RESULT_JSON: " + json.dumps({"ok": False, "error": "skills フォルダが見つかりません"}, ensure_ascii=False))
            sys.exit(1)
        dest.mkdir(parents=True, exist_ok=True)
        installed = []
        for d in sorted(SRC.iterdir()):
            if not (d.is_dir() and d.name.startswith("sutto-") and (d / "SKILL.md").exists()):
                continue
            target = dest / d.name
            if target.exists():
                shutil.rmtree(target)   # 前の版の「sutto-」スキルだけを置き換える
            shutil.copytree(d, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", ".DS_Store"))
            installed.append(d.name)
        result["installed"] = installed
        result["next"] = "Claude Code を開き直す（または新しい会話を始める）と、スキルが使えます。「無音カットして」のように頼んでください。"

    missing = [r for r in result["requirements"] if not r["ok"] and r["need"].startswith("必須")]
    print("")
    for r in result["requirements"]:
        print("  %s %-8s %s%s" % ("○" if r["ok"] else "×", r["name"], r["detail"] or "見つかりません", "" if r["ok"] else "  → " + r["how"] + "（" + r["need"] + "）"))
    print("")
    if a.remove:
        print("取り除いたスキル: %s" % ("、".join(result["removed"]) or "なし"))
    elif not a.check:
        print("入れたスキル（%d 本）: %s" % (len(result["installed"]), "、".join(result["installed"])))
        print("置き場: %s" % dest)
        print(result["next"])
    if missing:
        print("足りないもの: " + "、".join(m["name"] for m in missing) + "。上の「→」の方法で入れてから、お使いください。")
    print("RESULT_JSON: " + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
