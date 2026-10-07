#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_fixtures.py — 检测器回归夹具确定性注入生成器（seeded，零模型调用）
=====================================================================
背景：j6_v2 合成验证片（syn_*）与 dh/avatar 片（bu*/vidu*/*dh*）原片灭失
（g01-gpu-rerun.json:25,30,55-59「全域核实」），而基线判定锁在仓内
out/j6v2_syn_v3base / out/j6v2_dh_v3base（*.qc2.json 的判定级五元组）。
本生成器按确定性种子重建"检测器回归夹具"：伪影按声明参数精确注入，
使 src/qc_detectors_v2.py（CPU 帧序列规则）对本夹具的判定与基线逐条一致。

夹具性质（诚实声明）：
  * 本目录产物是重建物，不是 Vidu/StepFun/MiniMax 原物。原片灭失，
    fresh 再生成（Vidu avatar 通道）无法对上基线——基线判定是内容指纹
    的函数（g01 实测：替代素材 clean conf 1.0 vs 原片 ghosting 0.766）。
  * 基座内容为 seeded 正弦场画布匀速平移（确定性 numpy 合成），原因是：
    仓内真实素材（golden ~5-10s / g9a 61s 单条）无法提供 9-120s 无切点
    连续单镜头，而循环/拼接真实素材必然产生硬切+后向重入=结构性
    temporal_swap 误报，与"干净片零候选"基线矛盾（160px 缩略图判定，
    内容不敏感，判定只依赖时序统计结构）。
  * 注入机理与原误报机理一一对应（工程方案v3.1.md §3.4）：
      ghosting  → 时间重映射慢速窗（帧差矩形凹窗，in_med<2.0 落低运动
                  平台口径；laplacian 不塌，不触发 lap 支/冻结长跑）
      freeze    → 采样位置定格 49 帧（48 对帧差 <0.8）
      flicker   → 亮度 ±amp 逐帧符号交替（全通道等量，饱和度不变）
      swap      → 硬切回放（切点后回放片头内容 + 空间亚像素偏移 δ0
                  压后向相似度，复现「同人物 A/B 拼接回放」误报结构）

用法：
  python gen_fixtures.py --spec spec.json --clip NAME --out X.mp4
  spec.json: {NAME: {kind, seed, w, h, n_frames, v, ...注入参数}}
参数含义见 build_spec()/README.md。输出帧级确定（numpy 种子 + x264 同版本）。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

# 画布场参数（相位/频率/幅度由 seed 决定；波长上限 120px 全分辨率，
# 保证平移 200px+ 后自相关 <0.35——回放段前置窗与匹配区可分离，margin 充裕）
FIELD_N = 48
FIELD_FMIN = 2.0 * np.pi / 120.0   # rad/px（λ∈[40,120]px：80px 缩略图 16× 采样 Nyquist 安全，
FIELD_FMAX = 2.0 * np.pi / 40.0    #  梯度标度 G≈1-2.5 MAD/px；平移≥1.5λ 自相关<0.35）
FIELD_AMP_SUM = 200.0              # Σa_k（画布值域 128±~120 不削幅）
CANVAS_PAD = 96                    # 画布上下加垫：回放段 y 向偏移 d0 的行程
PAN_MAX = 8192                     # 画布横向长度上限（与 v 无关，v 调参不改内容）


def build_canvas(seed, w, h, fmin=None, fmax=None):
    """seeded 正弦场画布：C(x,y)=128+Σ a_k sin(fx_k·x+fy_k·y+φ_k)，float32 单通道。
    fmin/fmax 可按片覆盖（dh_final 用长波长画布容忍回放段慢速漂移）。"""
    rng = np.random.RandomState(seed)
    fx = rng.uniform(fmin or FIELD_FMIN, fmax or FIELD_FMAX, FIELD_N)
    fy = rng.uniform(-(fmax or FIELD_FMAX), fmax or FIELD_FMAX, FIELD_N)
    ang = rng.uniform(0, 2 * np.pi, FIELD_N)
    a = rng.dirichlet(np.ones(FIELD_N) * 2.0) * FIELD_AMP_SUM
    X, Y = np.meshgrid(np.arange(w + PAN_MAX, dtype=np.float32),
                       np.arange(h + CANVAS_PAD, dtype=np.float32))
    C = np.full(X.shape, 128.0, dtype=np.float32)
    for k in range(FIELD_N):
        C += a[k] * np.sin(fx[k] * X + fy[k] * Y + ang[k])
    return np.clip(C, 0, 255).astype(np.uint8)


def positions(kn, n_frames):
    """逐帧采样位置 P(t)（画布 px，可为亚像素/跳变）。

    kind=clean/flicker/ghost : 匀速 v，ghost 在 [f1, f1+win] 帧区间内速度×r
                               （kink 连续，凹窗两端帧差阶跃=矩形性）
    kind=freeze              : 匀速至 F，F..F+48 帧定格（48 对帧差≈0），
                               F+49 帧起回放（跳切 → cut@pair F+48）
    kind=swap                : 匀速至 Fc-1，Fc 帧起以速度 s 回放自 t_r，
                               叠加空间偏移 δ0（压后向相似度）
    """
    k, v = kn["kind"], kn["v"]
    t = np.arange(n_frames, dtype=np.float64)
    P = v * t
    if k == "ghost":
        # 慢速窗：窗内速度 r·v（h=1 全速）。默认锐利矩形（tp=0）：dur=(win+6)/24
        # 帧级确定、dip 对 r 线性可析；tp>0 为梯形边（备用，实测深窗更易检出）。
        f1, win, r, tp = kn["f1"], kn["win"], kn["r"], kn.get("taper", 0)
        u = np.clip(t - f1, 0.0, float(win))
        if tp <= 0:
            H = u
        else:
            H = np.where(u <= tp, u * u / (2 * tp),
                         np.where(u <= win - tp, u - tp / 2.0,
                                  win - tp - (win - u) ** 2 / (2 * tp)))
        P = P - v * (1 - r) * H
    elif k == "freeze":
        F, tr, s, d0 = kn["F"], kn["t_r"], kn.get("s", 1.0), kn["d0"]
        P = np.where(t <= F + 48, v * np.minimum(t, F),
                     v * (tr + s * (t - (F + 49))) + d0)
    elif k == "swap":
        Fc, tr, s, d0 = kn["Fc"], kn["t_r"], kn.get("s", 1.0), kn["d0"]
        g = kn.get("_ghost")                      # 基段叠加 ghost 慢速窗（dh_final）
        lag = np.zeros_like(t)
        if g:
            lag = v * (1 - g["r"]) * np.clip(t - g["f1"], 0, g["win"])
        # 回放段用绝对位置（滞后只属于基段——若减进回放段，回放内容会整体
        # 平移 ~16px，后向相似度被毁：round-17/19 back 0.24-0.43 的根因）
        P = np.where(t < Fc, v * t - lag, v * (tr + s * (t - Fc)) + d0)
    return P


def dy(kn, t):
    """回放段 y 向偏移（freeze/swap 用）：d0 只压后向相似度，不改跳切帧差。
    d0_axis="x"（默认 y）时返回 0——长波长画布上 y 移位会命中主导 fy 分量的
    反相位带（corr 变负且非单调），x 移位则单调可控。"""
    if kn.get("d0_axis", "y") == "x":
        return 0.0
    if kn.get("kind") == "freeze" and t >= kn["F"] + 49:
        return kn["d0"]
    if kn.get("kind") == "swap" and t >= kn["Fc"]:
        return kn["d0"]
    return 0.0


def render(kn, out_path):
    """渲染+编码：gray8 rawvideo → libx264 yuv420p crf18，精确 n_frames 帧。"""
    w, h, n = kn["w"], kn["h"], kn["n_frames"]
    canvas = build_canvas(kn["seed"], w, h)
    P = positions(kn, n)
    flick = kn.get("kind") == "flicker"
    fa, ff1, ff2 = kn.get("amp", 0), kn.get("ff1", 0), kn.get("ff2", -1)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
           "-s", f"{w}x{h}", "-r", "24", "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(kn.get("crf", 18)),
           "-pix_fmt", "yuv420p", "-r", "24", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    M = np.float32([[1, 0, 0], [0, 1, 0]])
    for t in range(n):
        tx = -float(P[t])
        M[0, 2] = tx
        frame = cv2.warpAffine(canvas, M, (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)
        if flick and ff1 <= t <= ff2:
            frame = np.clip(frame.astype(np.int16) + (fa if t % 2 == 0 else -fa),
                            0, 255).astype(np.uint8)
        M[1, 2] = -dy(kn, t)                  # 回放段 y 向偏移 d0：压后向相似度，
        proc.stdin.write(frame.tobytes())     #  与跳切距离解耦（x 向跳距恒 v·(切点−源)）
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed: {out_path}")
    return str(out_path)


def build_spec():
    """19 片夹具规格 = spec_matched.json（各片实测命中参数的唯一事实源，
    由 calibrate.py 的 manifest final_knobs 收敛而来；dh_final 另含 _ghost）。
    旧解析预解版保留为 build_spec_legacy()。"""
    p = Path(__file__).resolve().parent / "spec_matched.json"
    return json.loads(p.read_text(encoding="utf-8"))


def build_spec_legacy():
    """19 片夹具规格（18 生成 + g9a 免做）。conf 目标与基线五元组一致。

    (win, r) 按当前 thresholds.yaml（ghost_min_s=1.5）在**可检出域**内预解：
      conf = 0.55 + 0.25·min(1,(dur−1.5)/1.5) + 0.15·(0.65−dip)/0.65
    可检出域：rect_dip 滑窗（W=1s 步 0.25s）对全包窗的"外侧"样本被窗内值稀释，
    dip_ratio ≳ 0.48 的长矩形凹窗会整体躲开搜索（om≈wm 恒不成立）——故解约束
    dip ≤ 0.48 且 in_med = dip·out ∈ [0.9, 1.9]（≥0.9 防冻结长跑；dh 三片另受
    <2.0 低运动平台上限）。滑窗 run 起点前伸 ~18-21 帧造成的 dur 膨胀由
    calibrate.tune_ghost 的 win 校正吸收。v 初值按 G≈3.8 估，逐片实测收敛。"""
    G = lambda f1, win, r: {"f1": f1, "win": win, "r": r}
    return {
        # ---- 合成验证 4 片（基线 j6v2_syn_v3base）----
        "syn_flicker":  {"kind": "flicker", "seed": 901, "w": 1280, "h": 720,
                         "n_frames": 124, "v": 1.20, "amp": 8, "ff1": 35, "ff2": 84},
        "syn_freeze":   {"kind": "freeze", "seed": 902, "w": 1280, "h": 720,
                         "n_frames": 188, "v": 1.40, "F": 123, "t_r": 12,
                         "s": 1.0, "d0": 6.0},
        "syn_ghost":    {"kind": "ghost", "seed": 903, "w": 1280, "h": 720,
                         "n_frames": 136, "v": 2.89, **G(36, 45, 0.40)},
        "syn_swap":     {"kind": "swap", "seed": 904, "w": 1280, "h": 720,
                         "n_frames": 124, "v": 0.60, "Fc": 60, "t_r": 6,
                         "s": 1.0, "d0": 0.35, "crf": 14},   # v=0.5: thr 落 15 地板而跳距 18.6；
                                                             # crf14: 抬 80px 缩略图 back 天花板过 0.9348
        # ---- dh 3 片（基线 j6v2_dh_v3base；兼 B/C profile 检查：in_med<2.0）----
        "dh_stepfun_720p": {"kind": "ghost", "seed": 801, "w": 826, "h": 1114,
                            "n_frames": 360, "v": 0.83, **G(42, 46, 0.39)},
        "dh_design_720p":  {"kind": "ghost", "seed": 802, "w": 826, "h": 1114,
                            "n_frames": 408, "v": 1.40, **G(96, 20, 0.42)},
        "dh_final_30s":    {"kind": "swap", "seed": 803, "w": 826, "h": 1114,
                            "fmin": 0.026180, "fmax": 0.052360, "d0_axis": "x", "crf": 14,
                         "n_frames": 721, "v": 1.50, "Fc": 334, "t_r": 1,
                            "s": 0.85, "d0": 0.1, "_ghost": G(42, 48, 0.184)},
        # ---- bu 8 片 ----
        "buA_120s":  {"kind": "ghost", "seed": 711, "w": 1280, "h": 720,
                      "n_frames": 2880, "v": 0.84, **G(2592, 46, 0.37)},
        "buA_30s":   {"kind": "ghost", "seed": 712, "w": 1280, "h": 720,
                      "n_frames": 720, "v": 0.66, **G(192, 26, 0.37)},
        "buA_60s":   {"kind": "ghost", "seed": 713, "w": 1280, "h": 720,
                      "n_frames": 1440, "v": 1.60, "crf": 12, **G(690, 63, 0.09)},
        "buB_turn":  {"kind": "clean", "seed": 714, "w": 1280, "h": 720,
                      "n_frames": 288, "v": 0.85},
        "buB_walk":  {"kind": "clean", "seed": 715, "w": 1280, "h": 720,
                      "n_frames": 288, "v": 0.80},
        "buC_id1":   {"kind": "clean", "seed": 716, "w": 1280, "h": 720,
                      "n_frames": 288, "v": 0.90},
        "buC_id2":   {"kind": "ghost", "seed": 717, "w": 1280, "h": 720,
                      "n_frames": 288, "v": 0.90, **G(132, 70, 0.27)},
        "buD_clone": {"kind": "clean", "seed": 718, "w": 1280, "h": 720,
                      "n_frames": 216, "v": 0.85},
        # ---- vidu 4 片 ----
        "vidu_a_talk_540p":     {"kind": "clean", "seed": 721, "w": 960, "h": 540,
                                 "n_frames": 504, "v": 0.85},
        "vidu_b2_text_novoice": {"kind": "clean", "seed": 722, "w": 960, "h": 540,
                                 "n_frames": 144, "v": 0.80},
        "vidu_b_timeline_720p": {"kind": "ghost", "seed": 723, "w": 1280, "h": 720,
                                 "n_frames": 624, "v": 0.79, **G(192, 50, 0.32)},
        "vidu_c_walk_object_540p": {"kind": "ghost", "seed": 724, "w": 960, "h": 540,
                                    "n_frames": 528, "v": 1.21, **G(84, 69, 0.19)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", help="spec JSON（缺省打印内置 spec）")
    ap.add_argument("--clip", help="夹具名")
    ap.add_argument("--out", help="输出 mp4 路径")
    ap.add_argument("--set", action="append", default=[],
                    help="参数覆盖 k=v（可点路径 a.b=c），校准器使用")
    args = ap.parse_args()
    spec = build_spec()
    if args.spec:
        spec.update(json.loads(Path(args.spec).read_text(encoding="utf-8")))
    if not args.clip:
        print(json.dumps(spec, ensure_ascii=False, indent=1))
        return 0
    kn = json.loads(json.dumps(spec[args.clip]))          # deep copy
    for kv in args.set:
        key, _, val = kv.partition("=")
        val = float(val) if "." in val or val.isdigit() else val
        node = kn
        parts = key.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = val
    out = render(kn, args.out)
    print(f"WROTE {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
