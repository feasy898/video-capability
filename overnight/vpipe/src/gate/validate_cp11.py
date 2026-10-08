#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_cp11.py — CP11（合成）hard_verify 门禁校验器（vpipe v4，M1-W5）。

规范出处：
- contracts/v2/checkpoint.schema.json definitions.cp11_composite：payload 必备
  master_asset/container/video_codec/audio_codec/width/height/duration_s/
  master_shot_segments/storyboard_shot_count/known_cuts/all_cuts_registered；
  gate.type 枚举限 hard_verify；known_cuts=「全部硬切点登记（秒）」，
  all_cuts_registered=「无登记硬切点 → exit 非 0（TASK_v4 M1-W5 known_cuts
  强制登记）」。
- eval/thresholds.yaml checkpoints.cp11.gate.*（v4 段）+ 既有段两键：
    cp11.gate.duration_tol_s = 1.0    成片总时长 ±1s（白皮书 §3 CP11 原文）
    cp11.gate.shot_count_match = true 切镜数==分镜表镜头数（布尔强制键）
    l0_preflight.black_frame_ratio_max = 0.50  黑场占比（schema CP11 门禁行
                                      「黑场占比」沿既有段，不立新值防第二套数值）
    judges.J6_detectors_v2.rule_params.known_cuts_tol_s = 0.5  切点白名单容差
                                      （不登记则同人物同构图硬切后向重入相似度
                                      0.9784 > swap_single_back_min=0.85 必误报
                                      temporal_swap，工程方案v3.1.md:170）
- 白皮书 §3 CP11 + §4 T0：CRADLE 六道硬校验挂载点（分辨率/帧率/时长/黑场/
  字幕≠台词/切镜数）；同输入二遍编码 md5 一致（工程方案v3.1.md:218 实测口径）。

用法（仓根或 overnight/vpipe/ 下均可，--thresholds 缺省自动定位）：
    python3 src/gate/validate_cp11.py <artifact.json> \
        [--probe [MP4]] [--deliverable CP1.json] [--thresholds eval/thresholds.yaml] \
        [--scene-threshold F] [--self-check]

退出码：0=pass；1=fail（stdout JSON checks 逐项列因；无登记硬切点必 exit 1；
喂入非 cp11 工件也是数据级拒绝走 1——与兄弟 validate_cpN 口径一致）；
2=用法或读取错误（工件不可读/非 JSON 映射、阈值键缺失、--probe 定位失败或
ffprobe 失败——宁可 exit 2 不放行，判不了就不是门禁）。

六道 CRADLE 硬校验与本实现的对应（诚实边界）：
    分辨率  ffprobe 实测 vs payload（提供 --deliverable 时再对 CP1 pixel_map）
    帧率    ffprobe 实测入证据（cp11 契约 payload 无 fps 声明侧字段
            ——additionalProperties=false 不许加；声明比对 M2 经 aux_gates 挂 CP6
            timeline.fps，本版不做无锚的等值判定）
    时长    ffprobe 实测 vs payload.duration_s ≤ cp11.gate.duration_tol_s
    黑场    ffmpeg blackdetect 滤器实测（区间解析），
            占比 ≤ l0_preflight.black_frame_ratio_max
    字幕≠台词  声明道挂载：upstream_refs 须含 cp10（逐字硬校验在 CP10 门内，
            本校验器零 VLM 不做像素 OCR——像素级「字幕≠台词」归 CP12 D 组/人工；
            缺 cp10 上游 = 字幕道无挂载点 = fail）
    切镜数  ffmpeg select 场景变化滤器实测，段数（实测切点数+1）对
            master_shot_segments == storyboard_shot_count（shot_count_match）

known_cuts 铁律（TASK_v4 M1-W5）：--probe 实测的每个硬切点必须在 payload.
known_cuts 白名单容差 known_cuts_tol_s 内登记，未登记 = fail exit 1；
payload.all_cuts_registered=false 亦直接 fail（登记声明自认未齐）。

判定数值零硬编码：上列四键只从 thresholds.yaml 读，键缺失/类型不对 → exit 2。
--scene-threshold（缺省 0.3）是 select 场景滤器的检测器工作点（operating
point），不是判定阈：本门禁的判定只依赖「实测切点 ⊆ known_cuts±tol」与
「段数等式」，实测证据（切点时刻+场景分）全量入 stdout JSON 供审计。依赖：
标准库 + PyYAML + 本机 ffmpeg/ffprobe（--probe/--self-check 时；零外部模型）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

CP_ID = "cp11"
SCHEMA_VERSION = "2.0"
ARTIFACT_TYPE = "composite"
GATE_TYPE = "hard_verify"
DEFAULT_THRESHOLDS = "eval/thresholds.yaml"
THR_KEYROOT = f"checkpoints.{CP_ID}.gate"

# thresholds.yaml 既有段两键（v4 cp11 段注记原文：沿既有段，不立新值防第二套数值）
THR_KEY_BLACK = "l0_preflight.black_frame_ratio_max"
THR_KEY_CUTS_TOL = "judges.J6_detectors_v2.rule_params.known_cuts_tol_s"

PAYLOAD_REQUIRED = (
    "work_id",
    "master_asset",
    "container",
    "video_codec",
    "audio_codec",
    "width",
    "height",
    "duration_s",
    "master_shot_segments",
    "storyboard_shot_count",
    "known_cuts",
    "all_cuts_registered",
)

# select 场景滤器缺省工作点（检测器旋钮非判定阈；实测本机 ffmpeg 6.1.1 下
# 真硬切场景分 ≥0.62、编码噪声峰 ≤0.03，0.3 两侧余量 ≥2 倍，见 fixtures 实测）
DEFAULT_SCENE_THRESHOLD = 0.3

# blackdetect 滤器工作参数（滤器旋钮非判定阈；判定阈只有 black_frame_ratio_max）。
# d: 最短黑场区间报告时长（秒）；pix_th/pic_th: 滤器内建像素/画面占比判黑阈。
BLACKDETECT_D = 0.1
BLACKDETECT_PIX_TH = 0.10
BLACKDETECT_PIC_TH = 0.98

# 声明 vs 实测黑场占比的口径差提示界（blackdetect 区间法 vs 上游采样法，
# 仅 warn 不否决——warn 不翻转 verdict，与白皮书 §7 非目标 3 的 warn 语义一致）
BLACK_DECLARED_WARN_GAP = 0.05

# 浮点等值比较容差（只用于「实测恰落在阈上」的等值判定，不放宽任何阈本身）
EPS_R = 1e-9

# --self-check：3s 测试片二遍编码命令（确定性层自证；testsrc2/sine 均为
# ffmpeg 内建源，零外部依赖、零模型调用。工程方案v3.1.md:218 口径：
# ffmpeg 合成层同参数二遍编码 md5 一致）
SELF_CHECK_CMD = [
    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24",
    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
    "-t", "3", "-map", "0:v", "-map", "1:a",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
]


class ReadError(Exception):
    """用法/读取类错误 → exit 2。"""


# ---------------------------------------------------------------- 基础工具

def _num(x) -> bool:
    """数字（排除 bool——bool 是 int 子类，不能当数值阈/时长用）。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt(x) -> str:
    return f"{float(x):g}"


def _resolve_thresholds_path(p: str) -> Path:
    """先按给定路径（CWD 相对）找；找不到且是缺省值时回退到脚本相对定位
    （<vpipe>/eval/thresholds.yaml），使仓根/vpipe 两种 CWD 都能跑。"""
    path = Path(p)
    if path.is_file():
        return path
    fallback = Path(__file__).resolve().parents[2] / "eval" / "thresholds.yaml"
    if p == DEFAULT_THRESHOLDS and fallback.is_file():
        return fallback
    raise ReadError(f"thresholds 文件不存在或不是文件: {path}")


def load_thresholds(path: Path) -> tuple[dict, str]:
    """读本门禁全部判定数值。返回 (thr dict, thresholds.yaml sha256)。
    键缺失/类型不对 → ReadError（宁可 exit 2 不放行）。"""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ReadError(f"无法读取 thresholds 文件 {path}: {e}")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ReadError(f"thresholds YAML 解析失败 {path}: {e}")
    if not isinstance(data, dict):
        raise ReadError("thresholds 顶层不是映射")

    cps = data.get("checkpoints")
    cp11 = cps.get(CP_ID) if isinstance(cps, dict) else None
    gate = cp11.get("gate") if isinstance(cp11, dict) else None
    if not isinstance(gate, dict):
        raise ReadError(f"thresholds 缺 {THR_KEYROOT} 段")

    tol = gate.get("duration_tol_s")
    if not _num(tol) or tol <= 0:
        raise ReadError(f"{THR_KEYROOT}.duration_tol_s 缺失或非正数（实得 {tol!r}）")
    scm = gate.get("shot_count_match")
    if not isinstance(scm, bool):
        raise ReadError(f"{THR_KEYROOT}.shot_count_match 缺失或非布尔（实得 {scm!r}）")

    node = data
    for k in THR_KEY_BLACK.split("."):
        node = node.get(k) if isinstance(node, dict) else None
    if not _num(node) or not (0 < node <= 1):
        raise ReadError(f"{THR_KEY_BLACK} 缺失或不在 (0,1]（实得 {node!r}）")
    black_max = float(node)

    node = data
    for k in THR_KEY_CUTS_TOL.split("."):
        node = node.get(k) if isinstance(node, dict) else None
    if not _num(node) or node < 0:
        raise ReadError(f"{THR_KEY_CUTS_TOL} 缺失或负数（实得 {node!r}）")
    cuts_tol = float(node)

    thr = {
        "duration_tol_s": float(tol),
        "shot_count_match": scm,
        "black_frame_ratio_max": black_max,
        "known_cuts_tol_s": cuts_tol,
        "_keys_used": [
            f"{THR_KEYROOT}.duration_tol_s",
            f"{THR_KEYROOT}.shot_count_match",
            THR_KEY_BLACK,
            THR_KEY_CUTS_TOL,
        ],
        "_sha256": hashlib.sha256(raw).hexdigest(),
    }
    return thr, thr["_sha256"]


def check_shape(art: dict) -> dict:
    """cp11 分支识别 + payload 必备键（分支识别；完整 schema 校验归 schema 门）。"""
    problems = []
    if not isinstance(art, dict):
        raise ReadError("工件顶层不是 JSON 映射")
    if art.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version 须为 {SCHEMA_VERSION!r}（实得 {art.get('schema_version')!r}）")
    if art.get("cp_id") != CP_ID:
        problems.append(f"cp_id 须为 {CP_ID!r}（实得 {art.get('cp_id')!r}）")
    if art.get("artifact_type") != ARTIFACT_TYPE:
        problems.append(f"artifact_type 须为 {ARTIFACT_TYPE!r}（实得 {art.get('artifact_type')!r}）")
    gt = art.get("gate") or {}
    if isinstance(gt, dict) and gt.get("type") not in (None, GATE_TYPE):
        problems.append(f"gate.type 须为 {GATE_TYPE!r}（实得 {gt.get('type')!r}）")
    payload = art.get("payload")
    if not isinstance(payload, dict):
        problems.append("payload 缺失或非映射")
    else:
        for k in PAYLOAD_REQUIRED:
            if k not in payload:
                problems.append(f"payload 缺必备键 {k}")
    ok = not problems
    return {
        "name": "artifact_shape",
        "ok": ok,
        "detail": ("cp11 分支识别成立，payload 必备键齐" if ok else "；".join(problems)),
    }


# ---------------------------------------------------------------- ffprobe / ffmpeg 实测

def probe_media(mp4: Path) -> dict:
    """ffprobe 全项（沿 cradle/src/gates/g1_tech.py build_ffprobe_argv 口径）。"""
    if shutil.which("ffprobe") is None:
        raise ReadError("ffprobe 不在 PATH（--probe 需本机 ffmpeg/ffprobe）")
    argv = ["ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(mp4)]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=True)
    except subprocess.CalledProcessError as e:
        raise ReadError(f"ffprobe 失败（rc={e.returncode}）: {e.stderr.strip()[:300]}")
    except subprocess.TimeoutExpired:
        raise ReadError(f"ffprobe 超时: {mp4}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise ReadError(f"ffprobe 输出非 JSON: {e}")


def parse_probe(probe_json: dict) -> dict:
    """从 ffprobe JSON 提取 {duration_s,width,height,fps,avg_fps,container,vcodec,acodec,n_streams}。"""
    fmt = probe_json.get("format") or {}
    v = a = None
    for s in probe_json.get("streams") or []:
        if s.get("codec_type") == "video" and v is None:
            v = s
        elif s.get("codec_type") == "audio" and a is None:
            a = s
    if v is None:
        raise ReadError("ffprobe 输出中无视频流（合成产物必须有视频流）")

    def _rate(txt):
        try:
            num, _, den = (txt or "0/1").partition("/")
            den = float(den) if den else 1.0
            return (float(num) / den) if den else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    try:
        dur = float(fmt.get("duration", "0"))
    except ValueError:
        dur = 0.0
    return {
        "duration_s": dur,
        "width": int(v.get("width", 0)),
        "height": int(v.get("height", 0)),
        "fps": _rate(v.get("r_frame_rate")),
        "avg_fps": _rate(v.get("avg_frame_rate")),
        "container": fmt.get("format_name", ""),
        "vcodec": v.get("codec_name", ""),
        "acodec": a.get("codec_name") if a else "",
        "has_audio": a is not None,
        "n_streams": len(probe_json.get("streams") or []),
    }


def detect_black_intervals(mp4: Path) -> tuple[list[dict], str]:
    """ffmpeg blackdetect 实测黑场区间（白皮书 §4 T0：黑场道实测）。
    返回 (区间列表 [{start,end,duration}], 滤器参数串)。区间行在 stderr。"""
    if shutil.which("ffmpeg") is None:
        raise ReadError("ffmpeg 不在 PATH（--probe 需本机 ffmpeg/ffprobe）")
    vf = (f"blackdetect=d={BLACKDETECT_D}:pix_th={BLACKDETECT_PIX_TH}"
          f":pic_th={BLACKDETECT_PIC_TH}")
    argv = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4),
            "-vf", vf, "-an", "-f", "null", "-"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise ReadError(f"blackdetect 超时: {mp4}")
    if proc.returncode != 0:
        raise ReadError(f"blackdetect 失败（rc={proc.returncode}）: {proc.stderr.strip()[:300]}")
    pat = re.compile(
        r"black_start:(?P<s>[\d.]+)\s+black_end:(?P<e>[\d.]+)"
        r"\s+black_duration:(?P<d>[\d.]+)")
    intervals = [
        {"start": round(float(m.group("s")), 3),
         "end": round(float(m.group("e")), 3),
         "duration": round(float(m.group("d")), 3)}
        for m in pat.finditer(proc.stderr)
    ]
    return intervals, vf


def detect_scene_cuts(mp4: Path, scene_thr: float) -> tuple[list[dict], str]:
    """ffmpeg select 场景变化滤器实测硬切点（TASK：scdet 或 select 二选一，取 select）。
    返回 (切点列表 [{t,score}]，滤器参数串)。selected 帧经 metadata=print 打到 stdout。"""
    if shutil.which("ffmpeg") is None:
        raise ReadError("ffmpeg 不在 PATH（--probe 需本机 ffmpeg/ffprobe）")
    vf = f"select='gt(scene,{scene_thr})',metadata=print:file=-"
    argv = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4),
            "-vf", vf, "-an", "-f", "null", "-"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise ReadError(f"select 场景检测超时: {mp4}")
    if proc.returncode != 0:
        raise ReadError(f"select 场景检测失败（rc={proc.returncode}）: {proc.stderr.strip()[:300]}")
    cuts: list[dict] = []
    t_cur = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            m = re.search(r"pts_time:([\d.]+)", line)
            t_cur = float(m.group(1)) if m else None
        elif line.startswith("lavfi.scene_score=") and t_cur is not None:
            try:
                cuts.append({"t": round(t_cur, 3), "score": round(float(line.split("=", 1)[1]), 4)})
            except ValueError:
                pass
            t_cur = None
    cuts.sort(key=lambda c: c["t"])
    return cuts, vf


def cluster_cuts(cut_ts: list[float], tol: float) -> list[float]:
    """把实测切点按容差聚类（间隔 ≤tol 视为同一切点的多帧响应），返回簇代表时刻。
    容差只用既有键 known_cuts_tol_s：白名单容差内不可分辨的两次触发是同一登记对象。"""
    reps: list[float] = []
    for t in sorted(cut_ts):
        if reps and (t - reps[-1]) <= tol:
            continue
        reps.append(t)
    return reps


# ---------------------------------------------------------------- 声明级检查

def check_upstream_subtitle_mount(art: dict) -> dict:
    """字幕≠台词道的挂载点：upstream_refs 须含 cp10（逐字硬校验在 CP10 门内；
    零 VLM 不做像素 OCR，像素级归 CP12 D 组/人工——白皮书 §4 T0 诚实边界）。"""
    ups = art.get("upstream_refs") or []
    cp_ids = {u.get("cp_id") for u in ups if isinstance(u, dict)}
    ok = "cp10" in cp_ids
    return {
        "name": "subtitle_dialogue_mount",
        "ok": ok,
        "detail": (f"upstream_refs 含 cp10（字幕逐字硬校验挂载于 CP10 门，upstream={sorted(cp_ids)}）"
                   if ok else
                   f"upstream_refs 缺 cp10（实得 {sorted(cp_ids)}）：字幕/台词道无挂载点，"
                   f"合成层吃不到 CP10 逐字硬校验结论 → fail（白皮书 §3 CP11：所有片段+字幕+音轨→成片）"),
    }


def check_known_cuts_registry(payload: dict) -> tuple[dict, list[float]]:
    """known_cuts 登记册形态：非空升序、去重、非负。返回 (check, 规范化列表)。"""
    name = "known_cuts_registry_shape"
    kc = payload.get("known_cuts")
    if not isinstance(kc, list) or not kc:
        return {"name": name, "ok": False,
                "detail": f"known_cuts 须为非空数组（实得 {kc!r}）；合成层硬切拼接缝必须全部登记"}, []
    bad = [x for x in kc if not _num(x) or x < 0]
    if bad:
        return {"name": name, "ok": False,
                "detail": f"known_cuts 含非数或负值条目: {bad!r}"}, []
    ts = [float(x) for x in kc]
    if ts != sorted(ts):
        return {"name": name, "ok": False,
                "detail": f"known_cuts 须升序（登记册须规范化；实得 {ts!r}）"}, []
    if len(set(ts)) != len(ts):
        return {"name": name, "ok": False,
                "detail": f"known_cuts 含重复条目（实得 {ts!r}）"}, []
    return {"name": name, "ok": True,
            "detail": f"known_cuts 登记册规范：{len(ts)} 点，升序无重非负 {_fmt_list(ts)}"}, ts


def _fmt_list(xs: list[float]) -> str:
    return "[" + ",".join(_fmt(x) for x in xs) + "]"


def check_declared_relations(payload: dict, thr: dict, known_cuts: list[float]) -> list[dict]:
    """声明级三查：all_cuts_registered 布尔、切点-段数恒等、shot_count_match。"""
    checks = []
    seg = payload.get("master_shot_segments")
    sb = payload.get("storyboard_shot_count")
    acr = payload.get("all_cuts_registered")

    ok_acr = acr is True
    checks.append({"name": "declared_all_cuts_registered", "ok": ok_acr,
                   "detail": ("all_cuts_registered=true（登记声明完备）" if ok_acr else
                              f"all_cuts_registered 须为 true（实得 {acr!r}）：声明自认存在未登记切点，"
                              f"按 TASK_v4 M1-W5 铁律拒收")})

    ok_coh = (_num(seg) and _num(sb) and seg >= 1 and len(known_cuts) == int(seg) - 1)
    checks.append({"name": "cuts_segments_coherence", "ok": ok_coh,
                   "detail": ("known_cuts 数 == master_shot_segments-1（硬切拼接语义下恒等）" if ok_coh else
                              f"known_cuts {len(known_cuts)} 点 != master_shot_segments-1 "
                              f"（{_fmt(seg) if _num(seg) else seg!r}-1）：硬切拼接语义下实测段数=切点数+1，"
                              f"声明集自相矛盾")})

    if thr["shot_count_match"]:
        ok_sc = _num(seg) and _num(sb) and seg == sb
        checks.append({"name": "shot_count_match_declared", "ok": ok_sc,
                       "detail": (f"master_shot_segments {_fmt(seg)} == storyboard_shot_count {_fmt(sb)}"
                                  "（cp11.gate.shot_count_match=true，白皮书 §3 CP11 门禁行）" if ok_sc else
                                  f"master_shot_segments {_fmt(seg) if _num(seg) else seg!r} != "
                                  f"storyboard_shot_count {_fmt(sb) if _num(sb) else sb!r}"
                                  "：切镜数≠分镜表镜头数，退回定位哪一镜多/少切"
                                  "（cp11.gate.shot_count_match=true）")})
    else:
        checks.append({"name": "shot_count_match_declared", "ok": True,
                       "detail": "cp11.gate.shot_count_match=false，本键声明等值不强制（阈值表口径）"})
    return checks


# ---------------------------------------------------------------- 实测检查（--probe）

def check_probe(payload: dict, thr: dict, mp4: Path, deliverable: dict | None,
                scene_thr: float) -> tuple[list[dict], dict]:
    """--probe 实测道：ffprobe 全项 + blackdetect + select 场景切 + known_cuts 铁律。
    返回 (checks, evidence)。"""
    checks: list[dict] = []
    evidence: dict = {"probe_path": str(mp4)}

    probe_json = probe_media(mp4)
    m = parse_probe(probe_json)
    evidence["ffprobe"] = m
    evidence["scene_threshold_op"] = scene_thr

    # ---- CRADLE 时长道：实测 vs payload.duration_s ≤ duration_tol_s ----
    dur = payload.get("duration_s")
    name = "duration_tol"
    if not _num(dur) or dur <= 0:
        checks.append({"name": name, "ok": False,
                       "detail": f"payload.duration_s 须 >0 数（实得 {dur!r}）"})
    else:
        dev = abs(m["duration_s"] - float(dur))
        ok = dev <= thr["duration_tol_s"] + EPS_R
        checks.append({"name": name, "ok": ok,
                       "detail": (f"ffprobe 实测 {m['duration_s']:.3f}s vs 声明 {_fmt(dur)}s，"
                                  f"偏差 {dev:.3f}s ≤ cp11.gate.duration_tol_s="
                                  f"{_fmt(thr['duration_tol_s'])}s" if ok else
                                  f"ffprobe 实测 {m['duration_s']:.3f}s vs 声明 {_fmt(dur)}s，"
                                  f"偏差 {dev:.3f}s > cp11.gate.duration_tol_s="
                                  f"{_fmt(thr['duration_tol_s'])}s（白皮书 §3 CP11：总时长 ±1s）")})

    # ---- CRADLE 分辨率道：实测 vs payload（+可选 CP1 deliverable）----
    w, h = payload.get("width"), payload.get("height")
    decl_ok = (w == m["width"] and h == m["height"])
    dl_map_fail = None
    if decl_ok and deliverable:
        pm = (deliverable.get("payload") or {}).get("deliverable", {}).get("pixel_map") or {}
        if m["width"] != pm.get("width") or m["height"] != pm.get("height"):
            dl_map_fail = (f"实测 {m['width']}x{m['height']} 不符 CP1 deliverable.pixel_map "
                           f"{pm.get('width')}x{pm.get('height')}（分辨率与交付规格不一致）")
    ok = decl_ok and not dl_map_fail
    detail = (f"ffprobe 实测 {m['width']}x{m['height']} == 声明 {w}x{h}"
              + (f"；且符 CP1 deliverable.pixel_map" if deliverable else ""))
    if not ok:
        detail = (dl_map_fail if dl_map_fail else
                  f"ffprobe 实测 {m['width']}x{m['height']} != 声明 {w!r}x{h!r}"
                  "（CRADLE 分辨率道；契约登记值与实测不符）")
    checks.append({"name": "resolution", "ok": ok, "detail": detail})

    # ---- CRADLE 帧率道：实测入证据（契约无声明侧字段，声明比对 M2 挂 CP6）----
    fps_ok = m["fps"] > 0
    vfr = (m["avg_fps"] > 0 and abs(m["fps"] - m["avg_fps"]) / m["fps"] > 0.01)
    checks.append({"name": "fps_cradle", "ok": fps_ok,
                   "detail": (f"ffprobe 实测 r_frame_rate={m['fps']:g} fps"
                              f"（avg={m['avg_fps']:g}{'，VFR 提示' if vfr else ''}）；"
                              "cp11 契约 payload 无 fps 声明侧字段（additionalProperties=false），"
                              "声明比对 M2 经 aux_gates 挂 CP6 timeline.fps"
                              if fps_ok else "ffprobe 帧率解析失败（r_frame_rate 非 >0）")})
    evidence["fps_vfr_hint"] = bool(vfr)

    # ---- h264+aac 容器道：实测 vs 声明（+可选 CP1 encode_contract）----
    name = "container_codecs"
    problems = []
    if m["vcodec"] != payload.get("video_codec"):
        problems.append(f"视频编码实测 {m['vcodec']!r} != 声明 {payload.get('video_codec')!r}")
    if not m["has_audio"]:
        problems.append("无音频流（合成产物须含音轨）")
    elif m["acodec"] != payload.get("audio_codec"):
        problems.append(f"音频编码实测 {m['acodec']!r} != 声明 {payload.get('audio_codec')!r}")
    if payload.get("container") and payload.get("container") not in (m["container"] or ""):
        problems.append(f"封装实测 {m['container']!r} 不含声明 {payload.get('container')!r}")
    if deliverable:
        ec = (deliverable.get("payload") or {}).get("deliverable", {}).get("encode_contract") or {}
        for field, measured in (("container", m["container"]), ("video_codec", m["vcodec"]),
                                ("audio_codec", m["acodec"])):
            want = ec.get(field)
            if want and want not in measured:
                problems.append(f"CP1 deliverable.encode_contract.{field}={want!r} vs 实测 {measured!r}")
    checks.append({"name": name, "ok": not problems,
                   "detail": (f"容器/双流编解码实测（v={m['vcodec']!r}, a={m['acodec']!r}, "
                              f"封装 {m['container']!r}）与声明一致"
                              f"（container={payload.get('container')!r}, "
                              f"video_codec={payload.get('video_codec')!r}, "
                              f"audio_codec={payload.get('audio_codec')!r}）" if not problems else
                              "；".join(problems) + "（CRADLE 容器道；编码不达标只重跑合成，零 API 成本）")})

    # ---- CRADLE 黑场道：blackdetect 实测占比 ≤ black_frame_ratio_max ----
    intervals, vf = detect_black_intervals(mp4)
    black_s = sum(iv["duration"] for iv in intervals)
    ratio = (black_s / m["duration_s"]) if m["duration_s"] > 0 else 0.0
    ratio = min(ratio, 1.0)
    ok = ratio <= thr["black_frame_ratio_max"] + EPS_R
    checks.append({"name": "black_ratio_cradle", "ok": ok,
                   "detail": (f"blackdetect 实测黑场 {black_s:.3f}s/{m['duration_s']:.3f}s="
                              f"{ratio:.4f} ≤ l0_preflight.black_frame_ratio_max="
                              f"{thr['black_frame_ratio_max']:g}（{len(intervals)} 个黑场区间）" if ok else
                              f"blackdetect 实测黑场占比 {ratio:.4f} > "
                              f"l0_preflight.black_frame_ratio_max={thr['black_frame_ratio_max']:g}"
                              f"（{len(intervals)} 个黑场区间）")})
    declared_black = payload.get("black_ratio")
    black_warn = None
    if _num(declared_black) and abs(float(declared_black) - ratio) > BLACK_DECLARED_WARN_GAP:
        black_warn = (f"payload.black_ratio 声明 {float(declared_black):.4f} vs blackdetect 实测 "
                      f"{ratio:.4f} 差距 >{BLACK_DECLARED_WARN_GAP:g}（声明口径=上游采样法 vs "
                      "blackdetect 区间法，仅提示不否决）")
    evidence["blackdetect"] = {"filter": vf, "intervals": intervals,
                               "black_total_s": round(black_s, 3),
                               "ratio": round(ratio, 4), "warn": black_warn}

    # ---- CRADLE 切镜数道 + known_cuts 铁律（TASK_v4 M1-W5）----
    cuts, scvf = detect_scene_cuts(mp4, scene_thr)
    tol = thr["known_cuts_tol_s"]
    kc = [float(x) for x in (payload.get("known_cuts") or [])]
    unregistered = [c["t"] for c in cuts if not any(abs(c["t"] - k) <= tol + EPS_R for k in kc)]
    ok = not unregistered
    checks.append({"name": "known_cuts_registered", "ok": ok,
                   "detail": (f"实测硬切点 {_fmt_list([c['t'] for c in cuts])} 全部在 known_cuts "
                              f"{_fmt_list(kc)} ±known_cuts_tol_s={_fmt(tol)}s 白名单内登记"
                              "（TASK_v4 M1-W5：无登记硬切点 = fail）" if ok else
                              f"实测硬切点 {_fmt_list(unregistered)} 未登记 known_cuts"
                              f"（白名单 {_fmt_list(kc)} ±{_fmt(tol)}s）：不登记则同人物同构图硬切"
                              "必误报 temporal_swap（后向重入相似度 0.9784 > 0.85，"
                              "工程方案v3.1.md:170）——TASK_v4 M1-W5 铁律 exit 非 0")})
    undetected = [k for k in kc if not any(abs(c["t"] - k) <= tol + EPS_R for c in cuts)]
    measured_shots = len(cluster_cuts([c["t"] for c in cuts], tol)) + 1
    seg = payload.get("master_shot_segments")
    sb = payload.get("storyboard_shot_count")
    if thr["shot_count_match"]:
        ok_sc = (_num(seg) and _num(sb) and measured_shots == int(seg) == int(sb))
        checks.append({"name": "shot_count_match_measured", "ok": ok_sc,
                       "detail": (f"实测切点数 {len(cluster_cuts([c['t'] for c in cuts], tol))}"
                                  f"（+1 段 = {measured_shots}）== master_shot_segments {_fmt(seg)} "
                                  f"== storyboard_shot_count {_fmt(sb)}（CRADLE 切镜数道）" if ok_sc else
                                  f"实测段数 {measured_shots}（实测切点 {_fmt_list([c['t'] for c in cuts])} "
                                  f"+1）!= 声明 master_shot_segments {_fmt(seg) if _num(seg) else seg!r} / "
                                  f"storyboard_shot_count {_fmt(sb) if _num(sb) else sb!r}："
                                  "切镜数≠分镜表镜头数，退回定位哪一镜多/少切")})
    else:
        checks.append({"name": "shot_count_match_measured", "ok": True,
                       "detail": "cp11.gate.shot_count_match=false，实测段数等值不强制"})
    if undetected:
        evidence.setdefault("warns", []).append(
            f"known_cuts 中 {_fmt_list(undetected)} 未被场景滤器复现（低于工作点 "
            f"{scene_thr:g} 或非硬切拼接）：仅提示不否决，登记完备性由 "
            "known_cuts_registered 单向裁决（漏检不制造 fail，多检才暴露漏登记）")
    evidence["scene_cuts"] = {"filter": scvf, "cuts": cuts,
                              "measured_shots": measured_shots,
                              "unregistered": unregistered,
                              "registered_not_redetected": undetected}
    return checks, evidence


# ---------------------------------------------------------------- --self-check

def run_self_check() -> tuple[list[dict], dict]:
    """合成层像素级确定性自证：同输入二遍编码 md5 一致（工程方案v3.1.md:218）。
    testsrc2+sine 内建源生成 3s 测试片，同参数独立编码两遍，比对 md5。"""
    if shutil.which("ffmpeg") is None:
        raise ReadError("ffmpeg 不在 PATH（--self-check 需本机 ffmpeg）")
    checks: list[dict] = []
    md5s = []
    ver = ""
    try:
        ver_out = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                                 text=True, timeout=30, check=True)
        ver = (ver_out.stdout.splitlines() or [""])[0].strip()
    except Exception:
        ver = "unknown"
    with tempfile.TemporaryDirectory(prefix="cp11_selfcheck_") as td:
        for i in (1, 2):
            out = str(Path(td) / f"det{i}.mp4")
            try:
                subprocess.run(SELF_CHECK_CMD + [out], capture_output=True,
                               text=True, timeout=300, check=True)
            except subprocess.CalledProcessError as e:
                raise ReadError(f"self-check 第 {i} 遍编码失败: {e.stderr.strip()[:300]}")
            except subprocess.TimeoutExpired:
                raise ReadError(f"self-check 第 {i} 遍编码超时")
            data = Path(out).read_bytes()
            md5s.append(hashlib.md5(data).hexdigest())
    match = len(set(md5s)) == 1
    checks.append({"name": "composite_determinism_md5", "ok": match,
                   "detail": (f"3s testsrc2+sine 同参数二遍编码 md5 一致（{md5s[0]}）："
                              "合成层字节级确定性成立（工程方案v3.1.md:218 口径）" if match else
                              f"二遍编码 md5 不一致（{md5s[0]} vs {md5s[1]}）：合成层确定性承诺"
                              "被本机环境打破——检查 ffmpeg 版本/线程设置后重试")})
    evidence = {"ffmpeg": ver, "cmd": " ".join(SELF_CHECK_CMD), "md5_run1": md5s[0],
                "md5_run2": md5s[1]}
    return checks, evidence


# ---------------------------------------------------------------- 主流程

def resolve_probe_path(art: dict, probe_arg: str | None) -> Path:
    """--probe 缺省取 payload.master_asset.path（登记视图），CWD 与仓根两处试解。"""
    if probe_arg and probe_arg != "auto":
        p = Path(probe_arg)
        if p.is_file():
            return p
        raise ReadError(f"--probe 路径不存在或不是文件: {p}")
    mp = (art.get("payload") or {}).get("master_asset") or {}
    rel = mp.get("path")
    if not rel:
        raise ReadError("--probe 未给路径且 payload.master_asset.path 缺失，无法定位成片")
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        cand = base / rel
        if cand.is_file():
            return cand
    raise ReadError(f"payload.master_asset.path={rel!r} 在 CWD 与仓根均不可解析"
                    "（登记视图非身份；--probe 显式传 mp4 路径）")


def load_deliverable(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise ReadError(f"--deliverable 文件不存在: {p}")
    try:
        art = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ReadError(f"--deliverable 读取失败 {p}: {e}")
    if not isinstance(art, dict) or art.get("cp_id") != "cp1":
        raise ReadError(f"--deliverable 须为 CP1 意图单工件（cp_id=cp1）：{p}")
    return art


def validate(art: dict, thr: dict, probe_path: Path | None, deliverable: dict | None,
             scene_thr: float) -> dict:
    """判定核心（可导入复用）。返回 verdict dict；exit 码由调用方按 verdict 定。
    工件不是 JSON 映射时 raise ReadError（exit 2，不可判定）。"""
    shape = check_shape(art)  # art 非 dict 时在此 raise ReadError → exit 2
    checks = [shape]
    evidence: dict = {}
    if shape["ok"]:
        payload = art["payload"]
        checks.append(check_upstream_subtitle_mount(art))
        kc_check, known_cuts = check_known_cuts_registry(payload)
        checks.append(kc_check)
        checks.extend(check_declared_relations(payload, thr, known_cuts))
        if probe_path is not None:
            probe_checks, ev = check_probe(payload, thr, probe_path, deliverable, scene_thr)
            checks.extend(probe_checks)
            evidence = ev
        else:
            evidence["probe"] = ("skipped（未给 --probe：只判声明道；实测切点/黑场/时长/"
                                 "分辨率/容器五道须 --probe 实测）")
    else:
        evidence["probe"] = "skipped（工件未过 artifact_shape：分支不识别或必备键缺，判 fail）"
    verdict = "pass" if all(c["ok"] for c in checks) else "fail"
    out = {
        "cp_id": CP_ID,
        "gate": GATE_TYPE,
        "verdict": verdict,
        "checks": checks,
        "evidence": evidence,
        "thresholds_keys_used": thr["_keys_used"],
        "thresholds_sha256": thr["_sha256"],
    }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CP11（合成）hard_verify 门禁校验器：判定数值全部来自 "
                    f"{THR_KEYROOT}.* + 既有段两键，exit 0=pass / 1=fail / 2=用法或读取错误")
    ap.add_argument("artifact", nargs="?", help="CP11 合成工件 JSON 路径（--self-check 时可省）")
    ap.add_argument("--probe", nargs="?", const="auto", default=None, metavar="MP4",
                    help="传入成片 mp4 路径做实测（缺省取 payload.master_asset.path）："
                         "ffprobe 全项 + blackdetect 黑场 + select 场景切 + known_cuts 铁律")
    ap.add_argument("--deliverable", default=None, metavar="CP1_JSON",
                    help="可选 CP1 意图单工件：分辨率/编码对照 deliverable.pixel_map + encode_contract")
    ap.add_argument("--thresholds", default=DEFAULT_THRESHOLDS,
                    help=f"阈值表路径（缺省 {DEFAULT_THRESHOLDS}，自动回退脚本相对定位）")
    ap.add_argument("--scene-threshold", type=float, default=DEFAULT_SCENE_THRESHOLD,
                    metavar="F",
                    help=f"select 场景滤器检测工作点（检测器旋钮非判定阈，缺省 "
                         f"{DEFAULT_SCENE_THRESHOLD:g}；实测证据全量入 JSON）")
    ap.add_argument("--self-check", action="store_true",
                    help="合成层确定性自证：3s testsrc2+sine 二遍编码 md5 比对"
                         "（工程方案v3.1.md:218 口径；不需工件）")
    args = ap.parse_args(argv)

    if args.self_check:
        try:
            checks, ev = run_self_check()
        except ReadError as e:
            print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "verdict": "error",
                              "error": str(e)}, ensure_ascii=False, indent=2))
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        verdict = "pass" if all(c["ok"] for c in checks) else "fail"
        print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "mode": "self-check",
                          "verdict": verdict, "checks": checks, "evidence": ev},
                         ensure_ascii=False, indent=2))
        return 0 if verdict == "pass" else 1

    if not args.artifact:
        ap.error("需要 <artifact.json>（或 --self-check）")  # argparse exit 2

    try:
        art = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "verdict": "error",
                          "error": f"工件读取失败 {args.artifact}: {e}"},
                         ensure_ascii=False, indent=2))
        print(f"ERROR: 工件读取失败 {args.artifact}: {e}", file=sys.stderr)
        return 2

    try:
        thr, _ = load_thresholds(_resolve_thresholds_path(args.thresholds))
        deliverable = load_deliverable(args.deliverable)
        probe_path = resolve_probe_path(art, args.probe) if args.probe else None
    except ReadError as e:
        print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "verdict": "error",
                          "error": str(e)}, ensure_ascii=False, indent=2))
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        result = validate(art, thr, probe_path, deliverable, args.scene_threshold)
    except ReadError as e:
        print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "verdict": "error",
                          "error": str(e)}, ensure_ascii=False, indent=2))
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    result["artifact"] = args.artifact
    result["probe"] = (str(probe_path) if probe_path else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
