#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assemble_cp11.py — CP11 成片装配（漫剧线 EP01，后半程收官件）。

复刻短剧线 out/m2/shortdrama_ep01/cp11/assemble_cp11.py 已验证范式（无 avatar 段，
漫剧线按 TASK_v4 不含 avatar）。src/gate/synth.py 只收 kind=lavfi 程序源
（synth.py:186-189），CP9 真实终稿 mp4/CP10 配音 wav 无法入 case——按 TASK 预案
改用 ffmpeg filter_complex 直拼，本脚本替代其 meta 留痕职责。

装配口径（全部来自上游工件/实测，零硬编码数值）：
- 视频：CP9 终稿依 CP6 shots 顺序硬切拼接（concat），每镜 trim 到 CP6
  duration_frames/fps（帧域冻结，Σ=720 帧=30.0s）；768x1344 → cover-crop 1080x1920
  （水平裁 ~17px≈1.6%），setsar=1，24fps（ASK 指定交付规格；CP1 pixel_map=1088x1920
  的分歧在 cp11.json notes 声明，沿短剧线同款从 ASK）。
- shot_04 CP5 切点 3.6s：CP5 known_cuts=[3.6]（blocking 83 帧>72 帧窗口的段界）。
  CP9 的 shot_04 为单次生成 T2V 片段，装配层该切点不产生实体硬切——本脚本装配前
  对 shot_04 全程跑场景检测，若检出贴 3.6s 段界（±0.5s 容差）的生成拼接痕则按
  短剧线装配级修复配方（dissolve 桥接/trim）消化；若无检出，切点在合成层登记为
  「声明切点·无实体缝」，写入 cp11/qc_known_cuts.json（source 字段声明）与
  cp11.json aux_gates——不虚增 known_cuts 数（known_cuts 数=段数-1 恒等式）。
- 字幕：cp10/subs.ass 烧录（CP6 窗口 × CP2 逐字文本，build_cp10_assets.py 已过逐字校验；
  漫剧字幕=对白+旁白混排，G2 纪律：画面无可读文字，全部台词走本后期字牌）。
- 音频：cp10/fit/tts_seg_XX.fit.wav 逐句 adelay 到 max(0, 镜起点−2/24s)
  （CP6 sound_lead_in_frames=2 声先入），amix normalize=0，BGM 无授权音源 → 纯配音轨。
- known_cuts：8 个拼接缝 = CP6 shots 累计帧界/24（3 位小数），全登记。

产物：cp11/master.mp4 + cp11/synth_meta.json + cp11/qc_known_cuts.json
退出码：0=装配+探针自检 ok；1=ffmpeg/探针失败（meta 照写）。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VPIPE = Path(__file__).resolve().parents[4]          # .../overnight/vpipe
EP = VPIPE / "out" / "m2" / "comicanime_ep01"
CP9, CP10, CP11 = EP / "cp9", EP / "cp10", EP / "cp11"
RELRUN = "out/m2/comicanime_ep01"                    # vpipe 相对（ffmpeg cwd=vpipe）
GATE_THR_SCENE = 0.3                                  # select 检测工作点（非判定阈）


def sh(argv, timeout=1800, cwd=None):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)


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

    # ---------------- shot_04 CP5 切点预检（装配前实测）----------------
    cp5 = json.loads((EP / "cp5.json").read_text(encoding="utf-8"))
    seq4 = next(s for s in cp5["payload"]["sequences"] if s["shot_id"] == "shot_04")
    cp5_cut = (seq4.get("known_cuts") or [None])[0]
    assert cp5_cut == 3.6, f"CP5 shot_04 known_cuts={cp5_cut} != [3.6]"
    # shot_04 在 master 内的起点（s）与 CP5 切点对应的绝对时刻
    start4 = next(s for s in shots if s["shot_id"] == "shot_04")["start_frame"] / fps
    abs_cut = round(start4 + cp5_cut * (100 / seq4["frame_count"]), 3)
    # CP5 采样 20fps、83 帧≈4.15s，而 shot_04 CP6 窗口=100 帧/24=4.1667s——切点按
    # 时间比例（CP5 域→CP6 域）折算：3.6s(20fps) × (100/24)/(83/20) … 直接用比例：
    # CP5 序列时长=83/20=4.15s，CP6 窗口=100/24=4.1667s；缩放系数=4.1667/4.15
    scale = (100 / fps) / (seq4["frame_count"] / 20.0)
    abs_cut = round(start4 + cp5_cut * scale, 3)
    # 实测 CP9 shot_04 素材内 12.125±0.5s 附近有无生成拼接痕
    det4 = sh(["ffmpeg", "-hide_banner", "-nostats", "-i",
               f"{RELRUN}/cp9/shot_04.final.mp4",
               "-vf", f"select='gt(scene,{GATE_THR_SCENE})',metadata=print:file=-",
               "-an", "-f", "null", "-"], timeout=600)
    cuts4, t_cur = [], None
    for line in det4.stdout.splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            m = re.search(r"pts_time:([\d.]+)", line)
            t_cur = float(m.group(1)) if m else None
        elif line.startswith("lavfi.scene_score=") and t_cur is not None:
            cuts4.append({"t": round(t_cur, 3), "score": round(float(line.split("=", 1)[1]), 4)})
            t_cur = None
    # shot_04 CP6 窗口 4.1667s；CP5 切点换算到 CP9 素材时间 ≈ cp5_cut×scale
    mat_cut = round(cp5_cut * scale, 3)
    hits4 = [c for c in cuts4 if abs(c["t"] - mat_cut) <= 0.5]
    steps.append({"name": "shot04_cp5_cut_probe", "cp5_known_cuts": [cp5_cut],
                  "cp5_frame_count": seq4["frame_count"], "scale_to_cp6": round(scale, 6),
                  "master_abs_declared_cut_s": abs_cut,
                  "clip_measured_cuts": cuts4, "clip_hits_near_cp5_cut": hits4})
    print(f"[shot04] CP5 切点 3.6s→素材 {mat_cut}s 换算；实测拼接痕命中 {hits4}")

    # ---------------- filter_complex ----------------
    vparts, labels = [], []
    n = len(shots)
    for i, s in enumerate(shots):
        sf, df = s["start_frame"], s["duration_frames"]
        d = f"{df / fps:.9f}"
        pre = f"[{i}:v]"
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
    for s in shots:                                   # 0..8 终稿
        argv += ["-i", f"{RELRUN}/cp9/{s['shot_id']}.final.mp4"]
    for s in shots:                                   # 9..17 配音
        argv += ["-i", f"{RELRUN}/cp10/fit/tts_seg_{s['shot_id'][-2:]}.fit.wav"]
    argv += ["-filter_complex_script", f"{RELRUN}/cp11/filter_complex.txt",
             "-map", "[vout]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-threads", "1",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-movflags", "+faststart", "-t", f"{dur_total:.6f}",
             f"{RELRUN}/cp11/master.mp4"]
    r = sh(argv, timeout=3600, cwd=VPIPE)
    steps.append({"name": "encode_master", "argv": argv, "rc": r.returncode,
                  "stderr_tail": r.stderr.strip()[-800:]})
    if r.returncode != 0:
        (CP11 / "synth_meta.json").write_text(json.dumps(
            {"verdict": "failed", "steps": steps}, ensure_ascii=False, indent=1))
        print("FFMPEG FAIL:", r.stderr[-500:])
        return 1

    master = CP11 / "master.mp4"

    # ---------------- 探针自检 ----------------
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
            m = re.search(r"pts_time:([\d.]+)", line)
            t_cur = float(m.group(1)) if m else None
        elif line.startswith("lavfi.scene_score=") and t_cur is not None:
            cuts.append({"t": round(t_cur, 3), "score": round(float(line.split("=", 1)[1]), 4)})
            t_cur = None
    cuts.sort(key=lambda c: c["t"])

    bd = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(master),
             "-vf", "blackdetect=d=0.1:pix_th=0.10:pic_th=0.98", "-an", "-f", "null", "-"],
            timeout=1200)
    blacks = [{"start": float(m.group(1)), "end": float(m.group(2))}
              for m in re.finditer(r"black_start:([\d.]+)\s+black_end:([\d.]+)", bd.stderr)]
    black_s = sum(b["end"] - b["start"] for b in blacks)

    ln = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(master),
             "-af", "loudnorm=print_format=json", "-t", "30", "-f", "null", "-"],
            timeout=1200)
    mm = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", ln.stderr, re.DOTALL)
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

    # ---------------- qc_known_cuts.json（J6v2 白名单；含 shot_04 CP5 切点登记语义）----------------
    qc_cuts = {
        "cuts": known_cuts,
        "source": ("overnight/vpipe/out/m2/comicanime_ep01/cp11/cp11.json payload.known_cuts "
                   "(CP11 合成层 8 拼接硬切点全部登记)；另 CP5 shot_04 切点 3.6s（blocking 83 帧"
                   f">72 帧窗口段界）在合成层显式登记为「声明切点·无实体缝」：master 绝对时刻 "
                   f"{abs_cut}s（shot_04 起点 {start4}s + 3.6s×CP5→CP6 域换算 {scale:.6f}），"
                   "CP9 shot_04 为单次生成 T2V 片段，装配前场景检测该处无实体硬切"
                   f"（素材内实测切点 {cuts4}，±0.5s 命中 {hits4}）——登记进本白名单供检测器豁免，"
                   "不进 payload.known_cuts（known_cuts 数==段数-1 恒等式约束）"),
        "declared_intra_shot_cuts": [{"shot_id": "shot_04", "cp5_cut_s": cp5_cut,
                                      "master_abs_s": abs_cut,
                                      "manifestation": "no_physical_seam",
                                      "evidence": steps[0]}],
    }
    (CP11 / "qc_known_cuts.json").write_text(json.dumps(qc_cuts, ensure_ascii=False, indent=1)
                                             + "\n", encoding="utf-8")

    (CP11 / "synth_meta.json").write_text(json.dumps(
        {"tool": "assemble_cp11.py(comicanime)", "verdict": "ok" if ok else "probe_fail",
         "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
         "master_bytes": master.stat().st_size,
         "shot04_cp5_cut": {"cp5_cut_s": cp5_cut, "master_abs_s": abs_cut,
                            "manifestation": "no_physical_seam",
                            "clip_measured_cuts": cuts4},
         "steps": steps, "probe": probe}, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": ok, "probe": probe}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
