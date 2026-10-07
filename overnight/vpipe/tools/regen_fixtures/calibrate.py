#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate.py — 夹具注入参数校准驱动（对每片迭代至检测器判定==基线五元组）
==========================================================================
对 tools/regen_fixtures/gen_fixtures.py 的规格逐片闭环：
  渲染 → qc_detectors_v2.analyze_clip（与 CLI 同一代码路径，CPU 秒级）
  → 读 temporal_candidates 证据（out_med/in_med/dur_s/back_score/…）
  → 解析修正注入参数（v=平移速度, r=慢速窗率, win=窗帧数, d0=回放偏移）
  → 直至判定级视图（clip_id/detected/types/confidence/rejected_keys）
    与 out/j6v2_{syn,dh}_v3base 基线完全一致。
产物：mp4 落 数据/{j6_v2/synthetic,avatar_out,digital_human}（gitignore 域，
run_v3_checks.py D/B/C 断言路径）；manifest.json 记录每片最终参数与校准轨迹。

用法：  .venv/bin/python calibrate.py [--only NAME...] [--iters 6]
"""
import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
VPIPE = HERE.parent.parent                       # overnight/vpipe/
sys.path.insert(0, str(VPIPE / "src"))
sys.path.insert(0, str(HERE))

import gen_fixtures                              # noqa: E402
from qc_detectors_v2 import analyze_clip, load_params  # noqa: E402

DATA = VPIPE.parent / "数据"
THR = VPIPE / "eval" / "thresholds.yaml"
PARAMS = load_params(THR)
BASE = Path("/tmp/regen_fixtures_work")
G9A_SRC = VPIPE / "out" / "avatar_demo" / "g9a_intro_60s@vidu-s1.mp4"

# ---- 基线判定五元组（抄自 out/j6v2_*_v3base/*.qc2.json，2026-10-01T03:3x 生成）----
TARGETS = {
    "syn_flicker":  {"dst": DATA / "j6_v2" / "synthetic", "types": ["flicker"], "conf": 0.95},
    "syn_freeze":   {"dst": DATA / "j6_v2" / "synthetic", "types": ["frame_freeze", "temporal_swap"], "conf": 0.7},
    "syn_ghost":    {"dst": DATA / "j6_v2" / "synthetic", "types": ["ghosting"], "conf": 0.802, "out_s": 6.1, "dur_s": 2.125},
    "syn_swap":     {"dst": DATA / "j6_v2" / "synthetic", "types": ["temporal_swap"], "conf": 0.663},
    "dh_stepfun_720p": {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.766, "in_med_lt": 2.0, "out_s": 3.2, "dur_s": 1.917},
    "dh_design_720p":  {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.643, "in_med_lt": 2.0, "out_s": 3.25, "dur_s": 1.5},
    "dh_final_30s":    {"dst": DATA / "avatar_out", "types": ["ghosting", "temporal_swap"], "conf": 0.821,
                        "in_med_lt": 2.0, "cut_t": 13.917, "out_s": 1.35, "dur_s": 2.25},
    "buA_120s":  {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.771, "out_s": 3.2, "dur_s": 2.0},
    "buA_30s":   {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.685, "out_s": 2.6, "dur_s": 1.75},
    "buA_60s":   {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.911, "out_s": 9.5, "dur_s": 2.9167},
    "buB_turn":  {"dst": DATA / "avatar_out", "types": []},
    "buB_walk":  {"dst": DATA / "avatar_out", "types": []},
    "buC_id1":   {"dst": DATA / "avatar_out", "types": []},
    "buC_id2":   {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.846, "out_s": 3.4, "dur_s": 3.0417},
    "buD_clone": {"dst": DATA / "avatar_out", "types": []},
    "vidu_a_talk_540p":     {"dst": DATA / "avatar_out", "types": []},
    "vidu_b2_text_novoice": {"dst": DATA / "avatar_out", "types": []},
    "vidu_b_timeline_720p": {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.837, "out_s": 3.0, "dur_s": 2.25},
    "vidu_c_walk_object_540p": {"dst": DATA / "avatar_out", "types": ["ghosting"], "conf": 0.87, "out_s": 4.6, "dur_s": 3.125},
}
# 单切点回放：仅 syn_swap 的整体 conf 就是 swap conf，须严格卡 back_score；
# freeze/dh_final 的整体 conf 由另一候选决定，swap 只须被 emit（0.55-0.85 即可）。
BACK_WIN = {"syn_swap": (0.9344, 0.9351)}
GRID_R = {
    "syn_ghost":   [0.585, 0.60, 0.615, 0.50, 0.53],
    "dh_design_720p": [0.42, 0.44, 0.46, 0.48, 0.50, 0.52],
    "buA_120s":    [0.400, 0.415, 0.430, 0.445, 0.460],
    "buA_60s":     [0.04, 0.06, 0.08, 0.10, 0.12],
    "buC_id2":     [0.435, 0.437, 0.439, 0.42, 0.45],
    "dh_final_30s:d0": [0.3, 0.6, 1.0, 1.5, 2.2, 3.0],
    "vidu_b_timeline_720p": [0.30, 0.34, 0.38, 0.42, 0.46],
}

_CANVAS_CACHE = {}


def render(kn, out_path):
    """带画布缓存的渲染（canvas 只依赖 seed/w/h，调参不重建）。"""
    key = (kn["seed"], kn["w"], kn["h"], kn.get("fmin"), kn.get("fmax"))
    if key not in _CANVAS_CACHE:
        _CANVAS_CACHE[key] = gen_fixtures.build_canvas(kn["seed"], kn["w"], kn["h"],
                                                       kn.get("fmin"), kn.get("fmax"))
    import cv2
    w, h, n = kn["w"], kn["h"], kn["n_frames"]
    canvas = _CANVAS_CACHE[key]
    P = gen_fixtures.positions(kn, n)
    flick = kn.get("kind") == "flicker"
    fa, ff1, ff2 = kn.get("amp", 0), kn.get("ff1", 0), kn.get("ff2", -1)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
           "-s", f"{w}x{h}", "-r", "24", "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-r", "24", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    M = np.float32([[1, 0, 0], [0, 1, 0]])
    for t in range(n):
        M[0, 2] = -float(P[t])
        M[1, 2] = -float(gen_fixtures.dy(kn, t))     # 回放段 y 向偏移 d0
        f = cv2.warpAffine(canvas, M, (w, h), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE)
        if flick and ff1 <= t <= ff2:
            f = np.clip(f.astype(np.int16) + (fa if t % 2 == 0 else -fa), 0, 255).astype(np.uint8)
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg encode failed: %s" % out_path)
    return str(out_path)


def feats(clip):
    from qc_detectors_v2 import read_features
    return read_features(clip, PARAMS)


def judge(clip):
    d = analyze_clip(clip, PARAMS)
    p = d["temporal_protocol"]
    return d, {"clip_id": p["clip_id"], "detected": p["defect_detected"],
               "types": p["defect_types"], "conf": p["confidence"],
               "rej": sorted((d.get("temporal_rejected") or {}).keys())}


def match_target(name, j, d, relax=False):
    t = TARGETS[name]
    if relax:                                    # dh_final ghost 阶段：只锁 ghost 字段
        ev = d["temporal_candidates"].get("ghosting") or {}
        return (j["types"] and "ghosting" in j["types"]
                and abs(j["conf"] - t["conf"]) < 1e-9
                and not (set(j["rej"]) & {"ghosting", "frame_freeze", "flicker"})
                and bool(ev) and float(ev["in_med"]) < 2.0)
    ok = (j["types"] == t["types"] and j["rej"] == []
          and (t["types"] == [] or (j["detected"] and abs(j["conf"] - t["conf"]) < 1e-9))
          and (t["types"] != [] or (not j["detected"] and j["conf"] == 1.0)))
    ev = d["temporal_candidates"].get("ghosting") or {}
    if t.get("in_med_lt") is not None and ev:
        ok = ok and float(ev["in_med"]) < t["in_med_lt"]
    if t.get("cut_t") is not None:
        jn = (d["temporal_candidates"].get("temporal_swap") or {}).get("junctions") or [{}]
        ok = ok and abs(float(jn[0].get("cut_t", -99)) - t["cut_t"]) <= 0.5
    if name == "syn_freeze":                            # 双候选：定格 0.7 + 回放 0.614
        ok = ok and abs(float((d["temporal_candidates"].get("frame_freeze") or {}).get("conf", -1)) - 0.7) < 1e-9
    return ok


def conf_needed_dip(t_conf, dur_s):
    """ghost conf 公式反解：给定 dur_s，求 dip_ratio 使 conf 命中；不可达返回 None。
    （有效参数=DEFAULT_PARAMS：ghost_min_s=1.2——load_params 对 yaml 零覆盖。）"""
    a = 0.25 * min(1.0, (dur_s - 1.2) / 1.2)
    b = t_conf - 0.55 - a
    if b < 0 or b > 0.15:
        return None
    return 0.65 - b / 0.15 * 0.65


def tune_ghost(name, kn, log, relax=False):
    """经验闭环：v → 基底帧差；r →(割线) conf；win 只在候选缺失/不可达时伸缩。
    relax=True：swap 复合片（dh_final）的 ghost 阶段——swap 未命中不拦截，
    只锁 ghost conf/in_med（swap 命中交 tune_back 的 d0 阶段）。
    dur 不锁计划值——conf 是唯一锁定量，(dur, dip) 在约束线上浮动即可。
    注意有效参数是 DEFAULT_PARAMS（load_params 只读 judges 段平铺键，yaml
    rule_params 为文档注记不生效），ghost_min_s=1.2。"""
    t = TARGETS[name]
    t_conf = t["conf"]
    f1, win = kn["f1"], kn["win"]
    dur_max = min(2.4, 1.2 + 1.2 * max(0.0, t_conf - 0.55) / 0.25)   # b=0 上界
    dur_min = 1.2 + 1.2 * max(0.0, t_conf - 0.70) / 0.25             # b=0.15 下界
    iters = int(sys.argv[sys.argv.index("--iters") + 1]) if "--iters" in sys.argv else 16
    sec = {}                                          # 割线法状态 (r, conf)
    for it in range(iters):
        clip = BASE / (name + ".mp4")
        render(kn, clip)
        X = feats(clip)
        d, j = judge(clip)
        ev = d["temporal_candidates"].get("ghosting") or {}
        dur_s, dip, in_med = ev.get("dur_s"), ev.get("dip_ratio"), ev.get("in_med")
        outside = np.concatenate([X["diff"][:max(1, f1 - 12)],
                                  X["diff"][min(len(X["diff"]), f1 + win + 12):]])
        out_med = float(np.median(outside))
        log.append({"iter": it, "v": kn["v"], "r": kn["r"], "win": kn["win"],
                    "out_med": round(out_med, 3), "in_med": in_med, "dur_s": dur_s,
                    "dip_ratio": dip, "judg": j})
        print("  [%s#%d] out=%.3f in=%s dur=%s dip=%s -> %s %s" %
              (name, it, out_med, in_med, dur_s, dip, j["types"], j["conf"]), flush=True)
        if match_target(name, j, d, relax=relax):
            return copy.deepcopy(kn)
        out_s = t.get("out_s", 2.6)                   # v 安全带（<cut_free 15；flat 中位 ≥0.9 防冻结）
        if dur_s is None:                             # 无候选：r 消歧（与二分同规则）+ v 回带 + win 有界增长
            bl = kn.get("_bl") or {"lo": 0.03, "hi": 0.9}
            ldr = kn.get("_ldr")
            if ldr is not None and kn["r"] < ldr:     # 深侧（dur 塌缩）
                bl["lo"] = kn["r"]
            else:                                     # 浅侧（越可检出墙）
                bl["hi"] = kn["r"]
            kn["_bl"] = bl
            if abs(out_med - out_s) > 0.30 * out_s and out_med > 0.1:
                kn["v"] = kn["v"] * (out_s / out_med)
            kn["win"] = min(win + 3, 60)
            win = kn["win"]
            sec = {}
            continue
        # --- win 不动点：把 dur 持在 dur_s（分支稳定 → want 稳定 → 割线可收敛）---
        tgt_f = t.get("dur_s")
        if tgt_f and abs(dur_s - tgt_f) > 0.042:
            kn["win"] = max(16, int(round(win + round((tgt_f - dur_s) * 24))))
            win = kn["win"]
        want_dip = conf_needed_dip(t_conf, tgt_f or dur_s)
        if want_dip is None:                          # b<0: dur 过长；b>0.15: dur 过短
            if (t_conf - 0.55 - 0.25 * min(1.0, (dur_s - 1.2) / 1.2)) < 0:
                kn["win"] = max(16, win - int(round((dur_s - dur_max) * 24)) - 2)
            else:
                kn["win"] = win + int(round((dur_min - dur_s) * 24)) + 2
            win = kn["win"]
            sec = {}
            continue
        if abs(out_med - out_s) > 0.06 * out_s and it < 4:
            kn["v"] = kn["v"] * (out_s / out_med) if out_med > 0.1 else kn["v"]
        # --- r 二分 → dip_ratio 命中（dip(r) 单调）。None 有两义：过浅（越可检出墙）
        #         或过深（短窗 dur<ghost_min_s 被拒）——用最近一次检出的 r 消歧方向 ---
        if want_dip is not None and it >= 4:
            bl = kn.get("_bl") or {"lo": 0.03, "hi": 0.9}
            if dip is None:
                ldr = kn.get("_ldr")
                if ldr is not None and kn["r"] < ldr:
                    bl["lo"] = kn["r"]
                else:
                    bl["hi"] = kn["r"]
            elif dip > want_dip:
                bl["hi"] = kn["r"]
                kn["_ldr"] = kn["r"]
            else:
                bl["lo"] = kn["r"]
                kn["_ldr"] = kn["r"]
            kn["_bl"] = bl
            kn["r"] = round((bl["lo"] + bl["hi"]) / 2, 4)
        if "_ghost" in kn:                            # 复合片：同步 _ghost，渲染才吃到新 win/r
            kn["_ghost"]["win"] = kn["win"]
            kn["_ghost"]["r"] = kn["r"]
            kn["_ghost"]["f1"] = kn["f1"]
    return None


def brute_ghost(name, kn, log, relax=False):
    """(win, r) 暴力网格：dur 尾部不可解析（双峰摆动），直接对候选组合逐点渲染，
    返回第一个判定精确命中的组合。"""
    t = TARGETS[name]
    dur_t = t.get("dur_s")
    wins = []
    if dur_t:
        base = dur_t * 24.0
        for ttail in (0, 3, 6, 9, 12, 15, 16, 18, 21, -3, -6, -9):
            w = int(round(base - ttail))
            if w >= 16 and w not in wins:
                wins.append(w)
    if not wins:
        wins = [kn["win"]]
    r0 = kn["r"]
    rlist = [round(r0 + d, 3) for d in (-0.09, -0.06, -0.03, 0.0, 0.03, 0.06, 0.09)]
    n = 0
    for w in wins:
        kn["win"] = w
        if "_ghost" in kn:
            kn["_ghost"]["win"] = w
        for r in rlist:
            kn["r"] = r
            if "_ghost" in kn:
                kn["_ghost"]["r"] = r
            clip = BASE / (name + ".mp4")
            render(kn, clip)
            d, j = judge(clip)
            n += 1
            log.append({"iter": "brute", "win": w, "r": r, "judg": j})
            print("  [%s brute win=%d r=%.3f] -> %s %s" % (name, w, r, j["types"], j["conf"]), flush=True)
            if match_target(name, j, d, relax=relax):
                print("  [%s brute HIT win=%d r=%.3f]" % (name, w, r), flush=True)
                return copy.deepcopy(kn)
    print("  [%s brute exhausted (%d renders)]" % (name, n), flush=True)
    return None


def grid_ghost(name, kn, log):
    """二分不满 16 步的兜底：r 网格逐点渲染，返回第一个判定精确命中的点。"""
    t = TARGETS[name]
    grid = GRID_R.get(name)
    if not grid:
        return None
    for r in grid:
        kn["r"] = r
        clip = BASE / (name + ".mp4")
        render(kn, clip)
        d, j = judge(clip)
        log.append({"iter": "grid", "r": r, "judg": j})
        print("  [%s grid r=%.3f] -> %s %s" % (name, r, j["types"], j["conf"]), flush=True)
        if match_target(name, j, d):
            return copy.deepcopy(kn)
    return None


def grid_back(name, kn, log):
    """tune_back 的网格兜底（同 GRID_R，逐 d0）。"""
    grid = GRID_R.get(name + ":d0")
    if not grid:
        return None
    for d0 in grid:
        kn["d0"] = d0
        clip = BASE / (name + ".mp4")
        render(kn, clip)
        d, j = judge(clip)
        log.append({"iter": "grid_d0", "d0": d0, "judg": j})
        print("  [%s grid d0=%.3f] -> %s %s" % (name, d0, j["types"], j["conf"]), flush=True)
        if match_target(name, j, d):
            return copy.deepcopy(kn)
    return None


def tune_back(name, kn, log, lo, hi, strict=False, lo_d=0.3, hi_d=48.0):
    """d0 二分：回放后向相似度 back_score → conf。strict=True 时 back 须落
    [lo,hi]（conf 恰为目标）；否则接受任意 match（conf 由另一候选决定）。
    lo_d/hi_d 为 d0 搜索域：80px 缩略图对高频分量混叠，亚像素 d0 即显著改变
    back；竖屏 826 宽因子 0.194，域按片缩放。被拒 swap 的 junctions 落在
    temporal_rejected，读数须回退。"""
    best = None
    mid = (lo + hi) / 2
    for it in range(10):
        kn["d0"] = round((lo_d + hi_d) / 2, 3)
        clip = BASE / (name + ".mp4")
        render(kn, clip)
        d, j = judge(clip)
        jn = (d["temporal_candidates"].get("temporal_swap")
              or (d.get("temporal_rejected") or {}).get("temporal_swap") or {})
        backs = [e.get("back_score") for e in jn.get("junctions", jn.get("evidence", []))
                 if e.get("back_score") is not None]
        back = max(backs) if backs else 0.0
        log.append({"iter": it, "d0": kn["d0"], "back": back, "conf": j["conf"], "judg": j})
        print("  [%s#%d] d0=%.2f back=%s -> %s %s" % (name, it, kn["d0"], back, j["types"], j["conf"]), flush=True)
        if match_target(name, j, d) and (not strict or lo <= back <= hi):
            return copy.deepcopy(kn)
        if back > mid:
            lo_d = kn["d0"]
        else:
            hi_d = kn["d0"]
    return None


def tune_clean(name, kn, log):
    for it in range(4):
        clip = BASE / (name + ".mp4")
        render(kn, clip)
        d, j = judge(clip)
        X = feats(clip)
        log.append({"iter": it, "v": kn["v"], "out_med": round(float(np.median(X["diff"])), 3),
                    "judg": j})
        print("  [%s#%d] v=%.3f out=%.3f -> %s %s" %
              (name, it, kn["v"], np.median(X["diff"]), j["types"], j["conf"]), flush=True)
        if match_target(name, j, d):
            return copy.deepcopy(kn)
        kn["v"] = min(kn["v"] * 1.25, 3.0)                 # 提高运动量，压制噪声级伪凹窗
    return copy.deepcopy(kn)


def calibrate(name, spec, manifest):
    t0 = time.time()
    kn = copy.deepcopy(spec[name])
    log = []
    kind = kn["kind"]
    if kind == "flicker":
        clip = BASE / (name + ".mp4")
        render(kn, clip)
        d, j = judge(clip)
        log.append({"iter": 0, "judg": j})
        ok = match_target(name, j, d)
        final = copy.deepcopy(kn) if ok else None
        print("  [%s] %s %s" % (name, j, "OK" if ok else "FAIL"), flush=True)
    elif kind == "ghost":
        final = tune_ghost(name, kn, log) or grid_ghost(name, kn, log) \
            or brute_ghost(name, kn, log) or kn
    elif kind == "clean":
        final = tune_clean(name, kn, log)
    elif name in ("syn_freeze", "syn_swap"):
        strict = name == "syn_swap"
        lo, hi = BACK_WIN["syn_swap"] if strict else (0.86, 0.96)
        lo_d, hi_d = (0.05, 24.0) if name == "syn_swap" else (0.3, 48.0)
        final = tune_back(name, kn, log, lo, hi, strict=strict, lo_d=lo_d, hi_d=hi_d)
    elif name == "dh_final_30s":
        # ghost v/r/win 直接在整片（kind=swap+回放）上校：回放段改变 x264 码率分配，
        # 分阶段校准会漂移（实测 dip 0.559→0.473）。relaxed match 只锁 ghost 字段。
        kn2 = copy.deepcopy(kn)
        kn2.update(kn["_ghost"])                     # 顶层 f1/win/r 供 tune_ghost 逻辑
        if not tune_ghost(name, kn2, log, relax=True):
            gh = brute_ghost(name, kn2, log, relax=True)
            final = tune_back(name, gh or kn2, log, 0.1, 3.0) or grid_back(name, gh or kn2, log) or (gh or kn2)
        else:
            final = tune_back(name, kn2, log, 0.1, 3.0) or grid_back(name, kn2, log) or kn2
    else:
        raise SystemExit("unknown kind %s" % kind)
    # ---- 终渲染 + 终验证 ----
    if final is None:
        manifest.setdefault("_failed", []).append(name)
        print("  [%s] CALIBRATION FAILED" % name, flush=True)
        return
    dst = TARGETS[name]["dst"]
    dst.mkdir(parents=True, exist_ok=True)
    out = dst / (name + ".mp4")
    if Path(final.get("last_tmp", "")) != out:
        render(final, out)
    d, j = judge(out)
    ok = match_target(name, j, d)
    entry = {"kind": kind, "final_knobs": {k: v for k, v in final.items() if not k.startswith("_")},
             "baseline_target": {k: v for k, v in TARGETS[name].items() if k != "dst"},
             "final_judgment": j, "match": ok, "calibration_log": log, "sec": round(time.time() - t0, 1)}
    if name == "dh_final_30s":
        dcopy = DATA / "digital_human" / "dh_final_30s.mp4"
        dcopy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dcopy)
        entry["also_copied_to"] = str(dcopy)
    manifest["clips"][name] = entry
    print("  [%s] FINAL %s :: %s" % (name, "MATCH" if ok else "MISMATCH", j), flush=True)


def main():
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    BASE.mkdir(parents=True, exist_ok=True)
    mpath = HERE / "manifest.json"
    manifest = {"_note": "regenerated fixtures — 原片灭失，检测器回归夹具（详见 README.md）",
                "generator": "tools/regen_fixtures/gen_fixtures.py",
                "detector": "src/qc_detectors_v2.py @ thresholds.yaml judges.J6_detectors_v2",
                "params_snapshot": {k: PARAMS[k] for k in sorted(PARAMS) if not k.startswith("_")},
                "clips": {}}
    if mpath.exists():
        old = json.loads(mpath.read_text(encoding="utf-8"))
        keep = old.get("clips", {})
        manifest["clips"] = {k: v for k, v in keep.items() if not only or k not in only}
    spec = gen_fixtures.build_spec()
    names = only or list(TARGETS)
    for name in names:
        print("== %s ==" % name, flush=True)
        calibrate(name, spec, manifest)
    # g9a：原物已在仓（out/avatar_demo/g9a_intro_60s@vidu-s1.mp4，本会话实测复现基线 0.623）
    g9a_dst = DATA / "avatar_out" / "g9a_intro_60s_vidu.mp4"
    g9a_dst.parent.mkdir(parents=True, exist_ok=True)
    if not g9a_dst.exists():
        shutil.copyfile(G9A_SRC, g9a_dst)
        d, j = judge(g9a_dst)
        manifest["clips"]["g9a_intro_60s_vidu"] = {
            "kind": "original_copy", "source": str(G9A_SRC), "note": "原物在仓，免重建（判定实测复现基线）",
            "final_judgment": j, "match": j["conf"] == 0.623 and j["types"] == ["ghosting"]}
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [k for k, v in manifest["clips"].items() if not v.get("match")]
    print("== done; %d clips, mismatches: %s" % (len(manifest["clips"]), bad or "none"), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
