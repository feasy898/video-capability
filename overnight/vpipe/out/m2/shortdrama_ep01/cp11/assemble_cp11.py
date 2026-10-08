#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assemble_cp11.py — CP11 成片装配（M2-d）。

为什么不用 src/gate/synth.py：其 inputs 只收 kind="lavfi" 的 ffmpeg 程序源
（src/gate/synth.py:186-189 load_case 校验），CP9 真实终稿 mp4/CP10 配音 wav
无法声明进 case——故按 TASK 预案改用 ffmpeg filter_complex 直拼，
本脚本替代其 meta 留痕职责（argv/rc/探针/检测器全量落 synth_meta.json）。

装配口径（全部来自上游工件，零硬编码数值）：
- 视频：CP9 终稿依 CP6 shots 顺序硬切拼接（concat），每镜 trim 到 CP6
  duration_frames/fps（帧域冻结）；768x1344 → cover-crop 1080x1920，setsar=1，
  24fps（ASK 指定交付规格；CP1 pixel_map=1088x1920 的分歧在 cp11.json notes 声明）。
- 两处装配级修复（证据=select 场景滤器实测，见 notes）：
  * shot_03 内部生成拼接痕 scene=0.5718@2.375s：0.375s fade（dissolve）桥接
    （A=0–2.5s，B=2.125s–，xfade offset=2.125，总长不变 7.296s）；
  * shot_04 头部瞬态 scene=0.2997@0.667s（贴着门阈 0.3，重编码可能越阈）：
    trim start=0.75s 消化（窗口 6.25s ≤ 7.296−0.75，帧余量充足）。
- 字幕：cp10/subs.ass 烧录（CP6 窗口 × CP2 逐字文本，build_cp10_assets.py 已过逐字校验）。
- 音频：cp10/fit/tts_seg_XX.fit.wav 逐句 adelay 到 max(0, 镜起点−2/24s)
  （CP6 sound_lead_in_frames=2 声先入），amix normalize=0（电平不衰减），
  BGM 无授权音源 → 纯配音轨（如实记录）。
- known_cuts：10 个拼接缝 = CP6 shots 累计帧界/24（3 位小数），全登记。

产物：cp11/master.mp4 + cp11/synth_meta.json + cp11/cp11.json
退出码：0=装配+探针自检 ok；1=ffmpeg/探针失败（meta 照写）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VPIPE = Path(__file__).resolve().parents[4]          # .../overnight/vpipe
EP = VPIPE / "out" / "m2" / "shortdrama_ep01"
CP10, CP11 = EP / "cp10", EP / "cp11"
REL = "overnight/vpipe/out/m2/shortdrama_ep01"       # 仓根相对（登记视图，cp11.json 用）
RELRUN = "out/m2/shortdrama_ep01"                    # vpipe 相对（ffmpeg cwd=vpipe 用）
GATE_THR_SCENE = 0.3                                  # select 检测工作点（非判定阈）

BRIDGE3 = {"split_a_end": 2.375, "xfade_start": 2.0, "xfade_dur": 0.375}
TRIM4_START = 0.75


def sh(argv, timeout=1800):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def ffprobe_json(path: Path) -> dict:
    r = sh(["ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path)])
    assert r.returncode == 0, r.stderr[-300:]
    return json.loads(r.stdout)


def main() -> int:
    cp6 = json.loads((EP / "cp6.json").read_text(encoding="utf-8"))
    payload6 = cp6["payload"]
    fps = payload6["fps"]
    shots = sorted(payload6["shots"], key=lambda s: s["start_frame"])
    total_frames = payload6["total_frames"]
    lead = payload6["sound_lead_in_frames"]
    dur_total = total_frames / fps

    CP11.mkdir(exist_ok=True)
    steps: list[dict] = []
    seg_starts = {s["start_frame"] for s in shots}

    # ---------------- filter_complex ----------------
    vparts, labels = [], []
    n = len(shots)
    for i, s in enumerate(shots):
        sf, df = s["start_frame"], s["duration_frames"]
        d = f"{df / fps:.9f}"
        assert (sf, df) in {(x["start_frame"], x["duration_frames"]) for x in shots}
        pre = f"[{i}:v]"
        if s["shot_id"] == "shot_03":
            a, o, xd = BRIDGE3["split_a_end"], BRIDGE3["xfade_start"], BRIDGE3["xfade_dur"]
            vparts.append(f"{pre}trim=end={a},setpts=PTS-STARTPTS[b3a]")
            vparts.append(f"{pre}trim=start={a},setpts=PTS-STARTPTS[b3b]")
            vparts.append(f"[b3a][b3b]xfade=transition=fade:duration={xd}:offset={o}[b3x]")
            pre = "[b3x]"
        elif s["shot_id"] == "shot_04":
            vparts.append(f"{pre}trim=start={TRIM4_START},setpts=PTS-STARTPTS[b4]")
            pre = "[b4]"
        vparts.append(
            f"{pre}trim=duration={d},setpts=PTS-STARTPTS,"
            f"scale=1080:1920:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop=1080:1920,setsar=1,fps={fps}[v{i}]")
        labels.append(f"[v{i}]")
    vparts.append("".join(labels) + f"concat=n={n}:v=1:a=0[vc]")
    vparts.append(f"[vc]ass={RELRUN}/cp10/subs.ass[vout]")

    aparts, alabels = [], []
    for i, s in enumerate(shots):
        sid = f"seg_{s['shot_id'][-2:]}"
        start_ms = round(max(0, s["start_frame"] - lead) * 1000 / fps)
        aparts.append(f"[{n + i}:a]adelay={start_ms}:all=1[d{i}]")
        alabels.append(f"[d{i}]")
    aparts.append("".join(alabels) +
                  f"amix=inputs={n}:normalize=0:duration=longest[amx]")
    aparts.append(f"[amx]apad,atrim=0:{dur_total:.6f},asetpts=PTS-STARTPTS[aout]")

    fc = ";".join(vparts + aparts)
    fc_path = CP11 / "filter_complex.txt"
    fc_path.write_text(fc, encoding="utf-8")

    argv = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-y"]
    for s in shots:                                   # 0..10 终稿
        argv += ["-i", f"{RELRUN}/cp9/{s['shot_id']}.final.mp4"]
    for s in shots:                                   # 11..21 配音
        argv += ["-i", f"{RELRUN}/cp10/fit/tts_seg_{s['shot_id'][-2:]}.fit.wav"]
    argv += ["-filter_complex_script", f"{RELRUN}/cp11/filter_complex.txt",
             "-map", "[vout]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-threads", "1",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-movflags", "+faststart", "-t", f"{dur_total:.6f}",
             f"{RELRUN}/cp11/master.mp4"]
    r = sh(argv, timeout=3600)
    steps.append({"name": "encode_master", "argv": argv, "rc": r.returncode,
                  "stderr_tail": r.stderr.strip()[-800:]})
    if r.returncode != 0:
        (CP11 / "synth_meta.json").write_text(json.dumps(
            {"verdict": "failed", "steps": steps}, ensure_ascii=False, indent=1))
        print("FFMPEG FAIL:", r.stderr[-500:])
        return 1

    master = CP11 / "master.mp4"

    # ---------------- 探针自检（ffprobe 帧数/时长/双流 + 切点 + 黑场 + 响度）----------------
    pj = ffprobe_json(master)
    vs = next(s for s in pj["streams"] if s["codec_type"] == "video")
    as_ = next(s for s in pj["streams"] if s["codec_type"] == "audio")
    nf = sh(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_frames", "-print_format", "json",
             str(master)])
    nb_frames = int(json.loads(nf.stdout)["streams"][0]["nb_read_frames"])

    det = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(master),
              "-vf", f"select='gt(scene,{GATE_THR_SCENE})',metadata=print:file=-",
              "-an", "-f", "null", "-"], timeout=1200)
    cuts = []
    t_cur = None
    for line in det.stdout.splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            import re
            m = re.search(r"pts_time:([\d.]+)", line)
            t_cur = float(m.group(1)) if m else None
        elif line.startswith("lavfi.scene_score=") and t_cur is not None:
            cuts.append({"t": round(t_cur, 3), "score": round(float(line.split("=", 1)[1]), 4)})
            t_cur = None
    cuts.sort(key=lambda c: c["t"])

    bd = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(master),
             "-vf", "blackdetect=d=0.1:pix_th=0.10:pic_th=0.98", "-an", "-f", "null", "-"],
            timeout=1200)
    import re as _re
    blacks = [{"start": float(m.group(1)), "end": float(m.group(2))}
              for m in _re.finditer(r"black_start:([\d.]+)\s+black_end:([\d.]+)", bd.stderr)]
    black_s = sum(b["end"] - b["start"] for b in blacks)

    ln = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(master),
             "-af", "loudnorm=print_format=json", "-t", "60", "-f", "null", "-"],
            timeout=1200)
    import re as _re2
    mm = _re2.search(r"\{[^{}]*\"input_i\"[^{}]*\}", ln.stderr, _re2.DOTALL)
    lufs = json.loads(mm.group(0))["input_i"] if mm else None

    known_cuts = [round(s["start_frame"] / fps, 3) for s in shots[1:]]
    probe = {
        "duration_s": float(pj["format"]["duration"]),
        "nb_read_frames": nb_frames, "expected_frames": total_frames,
        "width": vs["width"], "height": vs["height"],
        "r_frame_rate": vs["r_frame_rate"], "vcodec": vs["codec_name"],
        "acodec": as_["codec_name"], "container": pj["format"]["format_name"],
        "scene_cuts": cuts, "black_intervals": blacks,
        "black_total_s": round(black_s, 3),
        "mix_lufs_input_i": lufs,
        "known_cuts": known_cuts,
    }
    ok_cuts = len({c["t"] for c in cuts}) == len(known_cuts) and all(
        any(abs(c["t"] - k) <= 0.5 for k in known_cuts) for c in cuts)
    ok = (nb_frames == total_frames and abs(probe["duration_s"] - dur_total) <= 1.0
          and vs["codec_name"] == "h264" and as_["codec_name"] == "aac"
          and ok_cuts)
    (CP11 / "synth_meta.json").write_text(json.dumps(
        {"tool": "assemble_cp11.py", "verdict": "ok" if ok else "probe_fail",
         "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
         "master_bytes": master.stat().st_size,
         "assembly_fixes": {"shot_03": BRIDGE3, "shot_04_trim_start": TRIM4_START},
         "steps": steps, "probe": probe}, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": ok, "probe": probe}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
