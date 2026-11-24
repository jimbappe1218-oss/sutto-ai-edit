# スッとAI編集（無料版）

Claude Code に「無音カットして」「できた動画を検査して」と頼めるようにする、動画編集用のスキル 2 本です。

![スッとAI編集 無料版](docs/hero.png)

AI に動画編集を頼むと、「できました」と言うのに音ズレしている、確かめずに終わる、ということが起きます。このスキルは、AI に渡す手順書（SKILL.md）と、実際に処理をするプログラムをセットにして、頼むだけで同じ結果が出るようにしたものです。

| スキル | できること |
|---|---|
| `sutto-cut`（無音カット） | 話していない部分を詰める。先に「何秒減るか」だけ調べられる。映像はフレーム単位、音声はサンプル単位で同じ位置を切るので音ズレしない。つなぎ目に 8 ミリ秒のフェードを入れてプチ音を防ぐ |
| `sutto-kensa`（仕上げ検査） | 解像度・フレームレート・音の大きさ（LUFS）・ピーク・黒コマ・長い無言・映像の静止を測り、コマ一覧の画像を作る。AI がその画像を開いて、自分の目で確かめる |

## 必要なもの

- Claude Code
- ffmpeg と ffprobe（Homebrew の標準版で動きます）
- Python 3.9 以降（Mac には最初から入っています）

無音カットは追加のダウンロードなしで動きます。仕上げ検査は、初回に Pillow（約 20MB）を専用の置き場 `~/.sutto-ai-edit/venv` に入れます。お使いの Python 本体には何も入れません。

## 入れ方

```bash
git clone https://github.com/jimbappe1218-oss/sutto-ai-edit.git
cd sutto-ai-edit
python3 install.py
```

`~/.claude/skills/` に `sutto-cut` と `sutto-kensa` を写します。ほかのスキルや設定には触りません。Claude Code を開き直す（または新しい会話を始める）と使えます。

このフォルダを Claude Code で開いて「スッとAI編集を入れて」と送っても、同じことをします。取り除くときは `python3 install.py --remove`。

## 頼み方

動画のあるフォルダを Claude Code で開いて、そのまま送れます。元の動画は変更されず、`元の名前_無音カット.mp4` ができます。

| # | 頼み方 | 技法名・起きること |
|---|---|---|
| 1 | この動画の無音をカットしたい。先に、何秒減るかだけ教えて。 | 下調べ（書き出さずに、減る秒数とカット数だけ出す） |
| 2 | 無音カットして。0.5 秒以上の無言を詰めて、声の前後は 0.12 秒残して。 | 無音カットの基本形。境目の音量は自動で決まる |
| 3 | ジェットカットにして。0.3 秒以上の間は全部詰めて、前後は 0.06 秒だけ残して。 | ジェットカット（テンポ重視。間をほぼ残さない） |
| 4 | 自然な間は残したい。0.9 秒以上の無言だけ詰めて、前後 0.2 秒残して。 | ゆるめのカット（対談・落ち着いた解説向け） |
| 5 | 2 秒以上の長い沈黙だけ消して。ほかの間は触らないで。 | デッドエア（長い沈黙）だけの除去 |
| 6 | 語尾が切れてる。声の前後に残す間を 0.18 秒にしてやり直して。 | のりしろ（パディング）を広げる |
| 7 | 息つぎの音が残ってる。無言の境目を −35dB にしてカットし直して。 | しきい値（スレッショルド）を手で決める |
| 8 | この音声ファイル（wav）の無音を詰めて。 | 音声だけのファイルの無音カット（ラジオ・Podcast） |
| 9 | できた動画を検査して。コマ一覧を見て、おかしな所がないか確かめて。 | 仕上げ検査（数値＋コマ一覧の目視） |
| 10 | 編集前と比べて、何秒短くなったか、音量がどう変わったか教えて。 | 編集前後の比較 |
| 11 | コマ一覧を 24 枚にして、細かく見せて。 | コンタクトシート（コマ一覧）の枚数 |
| 12 | −16 LUFS を目標にして検査して。 | 検査の目標ラウドネス |

練習用の素材が要るときは `python3 練習用素材/make_sample.py`。約 33 秒の動画（話している間だけ口が動く人形）が、あなたの PC の中で作られます。

## しくみ（無音カット）

1. 音の大きさを 20 ミリ秒ごとに測る（ffmpeg の astats）
2. 声の大きさ（上位 10%）と静かなときの大きさ（下位 10%）から、境目を自動で決める（`--threshold` で手動指定も可）
3. 境目より静かな時間が `--min-silence` 秒以上続いたら無言とみなし、前後 `--keep` 秒を残して詰める
4. 映像は一定のフレームレートにそろえてからフレーム番号で選び、音声は PCM にしてサンプル位置で切る。出力側の通算サンプル数に合わせるので、何百か所つないでも誤差がたまらない
5. ffmpeg は足し算を 100 個超 1 列に並べた式を読めないため、選ぶ式を二分木の形にまとめている

## 動作確認

macOS 26.3（Apple シリコン）、ffmpeg 8.1（Homebrew 標準版）、Python 3.9.6 で確かめています。**Windows と Linux は未確認です。** 動いた・動かなかったの報告を歓迎します。

- 無音カット 14 項目、仕上げ検査 11 項目を実行して合格（口の動きと声のずれを、カット前後でフレーム単位に照合。29.97fps、音声だけのファイル、設定の矛盾のエラーなど）
- 約 20 分の動画: 217 か所、19.8 分 → 15.2 分、処理 30 秒。口と声のずれは、冒頭・中間・最後とも 0 フレーム（カット前と同じ）
- 確認に使った素材は、付属のスクリプトで作った練習用の動画です。実際に撮影した素材での確認は行っていません

## もっとやりたいとき

文字起こし・日本語テロップ（縁取り・二重縁・座布団・影、文節での改行、あとで直せる形での出力）・BGM 合わせ・縦型変換・動くテロップ・通し編集を加えた 8 本のセットを、BOOTH で販売しています。

https://suttotools.booth.pm/items/9155765

## ライセンス

MIT License（[LICENSE](LICENSE)）。Claude、Claude Code は Anthropic, PBC の商標です。このリポジトリは Anthropic 社の製品ではありません。

---

## English summary

Two Agent Skills for Claude Code that edit real footage with ffmpeg:

- **sutto-cut** — silence removal (jump cut). Dry-run first to see how many seconds will be removed. Video is cut on frame boundaries and audio on sample positions, so A/V sync does not drift even after hundreds of cuts. 8 ms fades at each join.
- **sutto-kensa** — final check. Measures loudness (LUFS), true peak, black frames, long silences and frozen video, and builds a contact sheet that the agent opens and inspects.

Requires ffmpeg and Python 3.9+. Works with the slim Homebrew ffmpeg. Tested on macOS (Apple silicon) only; Windows and Linux are untested. Skill instructions (SKILL.md) are written in Japanese. Install with `python3 install.py`. MIT licensed.
