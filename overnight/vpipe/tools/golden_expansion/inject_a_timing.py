#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inject_a_timing.py — 金标扩样 A 组时序四类注入（v2 builders + 帧级签名自检）
=================================================================================
背景：evidence/golden-expansion-plan.md §2.1 A 组（freeze/swap/ghosting/flicker 各+3）。
配方从现行 golden/manifest.json 的 A 类时序条目复刻（2026-09-29 注入参数 + 2026-09-30
勘误重建的 v2 builder 形态），seed 换新；每条输出过【注入签名帧级自检】，
签名不生效 exit 4（该样本作废重建，不入 manifest——纪律同 19 片夹具重建）。

v2 builder 说明（依据 manifest 现行条目的 rebuilt.builder 字段 + v1 失效根因实测）：
  frame_freeze  v2_twopass_framepng_loop  两遍：先抽窗首帧 PNG，再 pre+PNG循环+post concat
                （v1 tpad=clone 在 trim 链上未生效——017/028 勘误）
  flicker       v2_eq_eval_frame          eq=brightness/saturation 逐帧交替
                （v1 根因：eq 默认 eval=init，n 表达式只求值一次 → 恒定偏移无交替；
                 v2 显式 eval=frame，本机 ffmpeg -h filter=eq 实证支持）
  temporal_swap swap_two_1s_segments      两段 1s 互换（v1 配方本就生效，原样复刻）
  ghosting      v2_segconcat_tmix6        窗段 tpad(clone 5帧)+tmix=6+select 去垫帧后 concat
                （等效「连续6帧平均滑动窗」全长不变；022 勘误同款——宿主须有运动承载）

签名判据（帧级，解码后 160px 灰度中位绝对差 MAD 口径，对齐 qc_detectors_v2 特征缩放）：
  freeze:  窗内最长平坦 run(diff<0.8) ≥1.6s 且 窗首帧==注入PNG（MAD<2）且
           宿主对照在窗内无 ≥1.6s 自然平坦 run（否则注入不可证伪→换宿主重建）
  flicker: 窗内相邻帧亮度差符号交替率 alt_frac ≥0.90 且 amp_median ≥6 且
           events_per_s ≥6 且宿主对照窗内无交替
  swap:    输出 [a,b) 帧逐帧最佳匹配宿主 [b,c)、输出 [b,c) 匹配宿主 [a,b)
           （匹配偏移=±1.0s±2帧，匹配残差 MAD<6）且 A→post 接缝存在帧差尖峰
  ghosting: 窗内中位帧差/窗外中位帧差 dip_ratio ≤0.72 且窗外 med ≥2.0（宿主运动下限，
           022 先例：近静止宿主任何混叠注入低于编码噪声底不可证伪）且
           窗内 Laplacian 清晰度显著下降（blend 后变糊，比值 ≤0.9）

用法：
  python3 inject_a_timing.py --host H.mp4 --dst D.mp4 --defect frame_freeze \
      [--win 2.0] [--seed N] --json OUT.sign.json
退出码：0 签名生效 / 4 签名不生效（作废重建）/ 2 输入错误 / 1 ffmpeg 失败
输出 JSON：inject_pos（复刻口径）+ signature（实测帧级证据，留痕入 manifest）
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ENC = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an"]
THUMB = 160          # 特征缩放边（对齐 qc_detectors_v2 feat_width）
FREEZE_DIFF = 0.8    # 平坦 run 判定阈（对齐 thresholds freeze_diff_thr）
GHOST_DIP_MAX = 0.72 # 022 签名 require_ratio<=
GHOST_OUT_MIN = 2.0  # 宿主运动下限（022 教训：近静止宿主不可承载）


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60).stdout
    j = json.loads(out)
    st = j["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    fps = float(num) / float(den)
    return {"w": int(st["width"]), "h": int(st["height"]), "fps": fps,
            "dur": float(j["format"]["duration"])}


def run_ff(args):
    p = subprocess.run(["ffmpeg", "-v", "error", "-y"] + args,
                       capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + p.stderr[-1500:])


def frames(path, max_n=2000):
    """解码全部帧 → 160px 灰度 float32 列表 + 原生 fps。"""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fs = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(f, (THUMB, THUMB)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        fs.append(g)
        if len(fs) >= max_n:
            break
    cap.release()
    return fs, fps


def pair_diffs(fs):
    return np.array([float(np.median(np.abs(fs[i + 1] - fs[i]))) for i in range(len(fs) - 1)])


def longest_flat_run(diffs, idx_lo, idx_hi, thr=FREEZE_DIFF):
    """帧差序列 [idx_lo, idx_hi) 内最长连续 <thr 的 run 长度（秒）。"""
    best = cur = 0
    for i in range(idx_lo, idx_hi):
        if diffs[i] < thr:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best  # 帧


def lap_var(fs, lo, hi):
    return float(np.median([cv2.Laplacian(f, cv2.CV_32F).var() for f in fs[lo:hi]]))


# ---------------------------------------------------------------- builders
def win_bounds(dur, win):
    t0 = max(0.5, dur / 2 - win / 2)
    return round(t0, 3), round(t0 + win, 3)


def build_freeze(src, dst, win, meta):
    """v2_twopass_framepng_loop：抽窗首帧 PNG → pre + PNG 循环 + post。"""
    d = probe(src)
    t0, t1 = win_bounds(d["dur"], win)
    fps = d["fps"]
    png = dst + ".freeze.png"
    run_ff(["-ss", f"{t0:.4f}", "-i", src, "-frames:v", "1", png])
    fc = (f"[0:v]trim=end={t0:.4f},setpts=PTS-STARTPTS[pre];"
          f"[0:v]trim=start={t0:.4f},setpts=PTS-STARTPTS[post];"
          f"[1:v]scale={d['w']}:{d['h']},fps={fps},format=yuv420p[fz];"
          f"[pre][fz][post]concat=n=3:v=1:a=0[v]")
    run_ff(["-i", src, "-loop", "1", "-framerate", f"{fps}", "-t", f"{win:.4f}",
            "-i", png, "-filter_complex", fc, "-map", "[v]"] + ENC + [dst])
    pos = {"mode": "freeze_last_frame", "start_s": t0, "end_s": t1,
           "duration_s": win, "builder": "v2_twopass_framepng_loop",
           "freeze_png": Path(png).name}
    return pos, d, (t0, t1)


def build_flicker(src, dst, win, meta):
    """v2_eq_eval_frame：eq 逐帧亮度/饱和交替（eval=frame 为 v2 关键）。"""
    d = probe(src)
    t0, t1 = win_bounds(d["dur"], win)
    fc = (f"[0:v]eq=brightness='if(mod(n,2),0.09,-0.09)'"
          f":saturation='if(mod(n,2),1.35,0.7)'"
          f":eval=frame"
          f":enable='between(t,{t0:.3f},{t1:.3f})'[v]")
    run_ff(["-i", src, "-filter_complex", fc, "-map", "[v]"] + ENC + [dst])
    pos = {"mode": "per_frame_exposure_alternation", "start_s": t0, "end_s": t1,
           "delta_brightness": 0.09, "sat_alt": [1.35, 0.7],
           "builder": "v2_eq_eval_frame"}
    return pos, d, (t0, t1)


def build_swap(src, dst, win, meta):
    """swap_two_1s_segments（v1 生效配方原样复刻；win 固定 2.0=两段各 1s）。"""
    d = probe(src)
    a = max(0.5, d["dur"] / 2 - 1.0)
    b, c = a + 1.0, a + 2.0
    fc = (f"[0:v]trim=end={a:.4f},setpts=PTS-STARTPTS[pre];"
          f"[0:v]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS[sa];"
          f"[0:v]trim=start={b:.4f}:end={c:.4f},setpts=PTS-STARTPTS[sb];"
          f"[0:v]trim=start={c:.4f},setpts=PTS-STARTPTS[post];"
          f"[pre][sb][sa][post]concat=n=4:v=1:a=0[v]")
    run_ff(["-i", src, "-filter_complex", fc, "-map", "[v]"] + ENC + [dst])
    pos = {"mode": "swap_two_1s_segments",
           "segment_A_s": [round(a, 3), round(b, 3)],
           "segment_B_s": [round(b, 3), round(c, 3)],
           "note": "A 放到 B 后：播放顺序变为 pre,B,A,post",
           "builder": "swap_two_1s_segments"}
    return pos, d, (a, c)


def build_ghosting(src, dst, win, meta):
    """v2_segconcat_tmix6：窗段 tpad(clone 5 帧)+tmix=frames=6+select 去垫 → 全长不变的
    滑动 6 帧平均（拖影 5 帧），concat 回原片。"""
    d = probe(src)
    t0, t1 = win_bounds(d["dur"], win)
    fps = d["fps"]
    pad = 5.0 / fps  # 5 帧
    fc = (f"[0:v]split=3[pre][win][post];"
          f"[pre]trim=end={t0:.4f},setpts=PTS-STARTPTS[a];"
          f"[win]trim=start={t0:.4f}:end={t1:.4f},setpts=PTS-STARTPTS,"
          f"tpad=start_mode=clone:start_duration={pad:.6f},"
          f"tmix=frames=6,select='gte(n,5)',setpts=PTS-STARTPTS[b];"
          f"[post]trim=start={t1:.4f},setpts=PTS-STARTPTS[c];"
          f"[a][b][c]concat=n=3:v=1:a=0[v]")
    run_ff(["-i", src, "-filter_complex", fc, "-map", "[v]"] + ENC + [dst])
    pos = {"mode": "frame_blend_trail",
           "blend": "tmix 连续6帧平均(拖影5帧)",
           "start_s": t0, "end_s": t1,
           "builder": "v2_segconcat_tmix6"}
    return pos, d, (t0, t1)


BUILDERS = {"frame_freeze": build_freeze, "flicker": build_flicker,
            "temporal_swap": build_swap, "ghosting": build_ghosting}

# ---------------------------------------------------------------- 签名自检
def sign_freeze(dst, src, pos, d0):
    fs, fps = frames(dst)
    diffs = pair_diffs(fs)
    lo = int(round(pos["start_s"] * fps))
    hi = min(int(round(pos["end_s"] * fps)), len(diffs))
    flat = longest_flat_run(diffs, lo, hi)
    flat_s = flat / fps
    # 冻结帧一致性：输出窗首数帧 与 注入 PNG（-ss 抽帧与 trim 边界可差 1 帧，
    # 原修复留痕亦记 frozen_frame_match_t=1.562=窗内第 2 帧——取窗首 4 帧最小 MAD）
    png = cv2.cvtColor(cv2.resize(cv2.imread(str(Path(dst).parent / pos["freeze_png"])),
                                  (THUMB, THUMB)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    fmatch = min(float(np.median(np.abs(fs[i] - png)))
                 for i in range(lo, min(lo + 4, len(fs))))
    # 宿主对照：同窗是否本就平坦（不可证伪 → 换宿主）
    hs, hfps = frames(src)
    hd = pair_diffs(hs)
    hlo = int(round(pos["start_s"] * hfps))
    hhi = min(int(round(pos["end_s"] * hfps)), len(hd))
    host_flat = longest_flat_run(hd, hlo, hhi) / hfps
    sig = {"longest_flat_s_in_win": round(flat_s, 3), "required_s": 1.6,
           "frozen_frame_match_mad": round(fmatch, 3), "frozen_match_max": 2.0,
           "host_nat_flat_s_in_win": round(host_flat, 3), "fps": round(fps, 3),
           "out_dur": round(len(fs) / fps, 3), "expect_dur": round(d0["dur"] + pos["duration_s"], 3)}
    sig["ok"] = bool(flat_s >= 1.6 and fmatch < 2.0 and host_flat < 1.6)
    return sig


def sign_flicker(dst, src, pos, d0):
    fs, fps = frames(dst)
    n = len(fs)
    lo = int(round(pos["start_s"] * fps))
    hi = min(int(round(pos["end_s"] * fps)), n - 1)
    means = [float(f.mean()) for f in fs]
    dseq = np.diff(np.array(means[lo:hi + 1]))
    if len(dseq) < 4:
        return {"ok": False, "error": "window too short"}
    signs = np.sign(dseq)
    nz = signs != 0
    flips = sum(1 for i in range(len(signs) - 1) if signs[i] * signs[i + 1] < 0)
    alt_frac = flips / max(1, len(signs) - 1)
    amp = float(np.median(np.abs(dseq[nz]))) if nz.any() else 0.0
    ev_s = len(dseq) / max(1e-6, (hi - lo) / fps)
    # 宿主对照
    hs, hfps = frames(src)
    hm = [float(f.mean()) for f in hs]
    hlo = int(round(pos["start_s"] * hfps))
    hhi = min(int(round(pos["end_s"] * hfps)), len(hm) - 1)
    hd = np.diff(np.array(hm[hlo:hhi + 1]))
    hflip = sum(1 for i in range(len(hd) - 1) if hd[i] * hd[i + 1] < 0) / max(1, len(hd) - 1) if len(hd) > 2 else 0.0
    hamp = float(np.median(np.abs(hd))) if len(hd) else 0.0
    sig = {"alt_frac": round(alt_frac, 3), "amp_median": round(amp, 2),
           "events_per_s": round(ev_s, 2), "n_inwin": int(hi - lo),
           "host_alt_frac": round(hflip, 3), "host_amp_median": round(hamp, 2),
           "fps": round(fps, 3), "out_dur": round(n / fps, 3)}
    sig["ok"] = bool(alt_frac >= 0.90 and amp >= 6.0 and ev_s >= 6.0
                     and (hflip < 0.5 or hamp < 3.0))
    return sig


def sign_swap(dst, src, pos, d0):
    fo, ofps = frames(dst)
    fh, hfps = frames(src)
    a, c = pos["segment_A_s"][0], pos["segment_B_s"][1]
    # 输出窗内帧 → 宿主最佳匹配（期望滞后 ±1.0s）
    res, lags = [], []
    for seg, want in (((a, a + 1.0), +1.0), ((a + 1.0, c), -1.0)):
        lo = int(round(seg[0] * ofps)); hi = int(round(seg[1] * ofps))
        for i in range(lo, min(hi, len(fo))):
            t = i / ofps
            j_want = int(round((t + want) * hfps))
            best, bj = 1e9, None
            for j in range(max(0, j_want - 3), min(len(fh), j_want + 4)):
                m = float(np.median(np.abs(fo[i] - fh[j])))
                if m < best:
                    best, bj = m, j
            if bj is not None:
                lags.append((j / hfps - t) - want)
                res.append(best)
    resid = float(np.median(res)) if res else 1e9
    lag_ok = bool(lags) and float(np.median(np.abs(np.array(lags)))) <= 2.0 / ofps + 0.05
    # 接缝尖峰（A→post 边界，输出时间 c）
    do = pair_diffs(fo)
    jlo = max(0, int(round(c * ofps)) - 1)
    jhi = min(len(do), int(round(c * ofps)) + 1)
    seam = float(do[jlo:jhi].max()) if jhi > jlo else 0.0
    dh = pair_diffs(fh)
    hmed = float(np.median(dh))
    sig = {"match_residual_mad": round(resid, 3), "match_residual_max": 6.0,
           "lag_median_dev_s": round(float(np.median(np.abs(lags))) if lags else 9.9, 3),
           "seam_spike": round(seam, 2), "host_med_diff": round(hmed, 2),
           "n_matched": len(res), "fps": round(ofps, 3),
           "out_dur": round(len(fo) / ofps, 3)}
    sig["ok"] = bool(resid < 6.0 and lag_ok and len(res) >= 0.6 * (c - a) * ofps)
    return sig


def sign_ghosting(dst, src, pos, d0):
    fo, ofps = frames(dst)
    do = pair_diffs(fo)
    lo = int(round(pos["start_s"] * ofps))
    hi = min(int(round(pos["end_s"] * ofps)), len(do))
    out_lo = [i for i in range(len(do)) if i < lo - 2 or i >= hi + 2]
    med_in = float(np.median(do[lo:hi]))
    med_out = float(np.median(do[out_lo])) if out_lo else float(np.median(do))
    dip = med_in / med_out if med_out > 0 else 1.0
    lap_in = lap_var(fo, lo, min(hi + 1, len(fo)))
    fh, hfps = frames(src)
    lap_out = lap_var(fh, 0, len(fh))
    lap_ratio = lap_in / lap_out if lap_out > 0 else 1.0
    sig = {"med_in": round(med_in, 3), "med_out": round(med_out, 3),
           "dip_ratio": round(dip, 3), "require_ratio<=": GHOST_DIP_MAX,
           "host_med_out_min": GHOST_OUT_MIN,
           "lap_in": round(lap_in, 1), "lap_out_host": round(lap_out, 1),
           "lap_ratio": round(lap_ratio, 3), "fps": round(ofps, 3),
           "out_dur": round(len(fo) / ofps, 3)}
    sig["ok"] = bool(dip <= GHOST_DIP_MAX and med_out >= GHOST_OUT_MIN and lap_ratio <= 0.9)
    return sig


SIGNERS = {"frame_freeze": sign_freeze, "flicker": sign_flicker,
           "temporal_swap": sign_swap, "ghosting": sign_ghosting}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--defect", required=True, choices=sorted(BUILDERS))
    ap.add_argument("--win", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--json", required=True)
    a = ap.parse_args()

    rec = {"host": a.host, "dst": a.dst, "defect": a.defect, "seed": a.seed}
    try:
        pos, d0, _ = BUILDERS[a.defect](a.host, a.dst, a.win, rec)
    except RuntimeError as e:
        rec["error"] = str(e)
        Path(a.json).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[FAIL] ffmpeg:", e)
        return 1
    rec["inject_pos"] = pos
    try:
        sig = SIGNERS[a.defect](a.dst, a.host, pos, d0)
    except Exception as e:  # noqa: BLE001
        sig = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    rec["signature"] = sig
    d2 = probe(a.dst)
    rec["verify"] = {"dur_s": round(d2["dur"], 3), "wh": [d2["w"], d2["h"]],
                     "fps": round(d2["fps"], 3)}
    Path(a.json).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dst": a.dst, "ok": sig.get("ok"), "signature": sig}, ensure_ascii=False))
    return 0 if sig.get("ok") else 4


if __name__ == "__main__":
    sys.exit(main())
