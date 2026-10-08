#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blocking_to_gltf.py — CP5 blocking → glTF 2.0 armature 往返导出器（v4 · M1-W4）。

任务出处
----
    TASK_v4 §7 W4（TASK_v4.md:197）「CP5 blocking schema + glTF 2.0 armature 端到端连通」；
    §8 决策记录 2026-10-08-b（TASK_v4.md:525）：原定 Blender 连通性验证改为 glTF 2.0 往返
    （双机均无 Blender；glTF 是 mannequin schema 的标准交换格式、纯 Python 可写可验）。
    验收等价物：往返后关节层级 + 关键帧时间/弧度零丢失——本器写盘后重新读回自检，
    零丢失才 exit 0。只做 JSON .gltf（.glb 二进制不做，任务红线）；只用标准库
    （json/struct/math/base64，不依赖 pygltflib 等）。

用法
----
    python3 src/gate/blocking_to_gltf.py <cp5.json> --out <file.gltf>
                                        [--report <check.json>] [--lip-layer <jaw_track.json>]

    （schema 词表默认相对本文件定位 <vpipe>/contracts/v2/checkpoint.schema.json，
      从任意 cwd 运行均可——与 validate_cp5.py 同一定位口径。）

退出码（沿用 validate_cp5.py 三态风格）
----
    0 = pass   转换 + 写出 + 重新读回往返校验全部通过（零丢失）
    1 = fail   数据拒绝（verdict JSON 里逐条给 reason）：
               track 引用不存在的关节 / joint_names 非 16 关节全集 / 帧时间非严格递增 /
               帧含 rotation 以外通道字段（无法无损表示）/ 往返校验不齐。
               输出 .gltf 不落盘：先写 <out>.tmp，往返通过才原子改名——保证磁盘上
               存在的 .gltf 一定是自检通过的。
    2 = error  用法/环境：文件缺失、JSON 不可解析、非 cp5/blocking 工件、schema 缺失或
               16 关节词表不可取、--out/--report 目录不可写、--lip-layer 缺失或不可解析

stdout 恒输出一个 JSON verdict（与 validate_cp5 同构：verdict/exit_code/checks/problems/
warnings）；人读过程信息走 stderr。

映射规则（CP5 → glTF 2.0，全部无虚构数据）
----
  - nodes：每序列一棵 armature 树 = 1 个根节点 {shot}:root + 16 关节节点（命名
    {shot}:{joint}）。父子拓扑：schema joint 枚举只有名字没有父子字段，故按 mannequin
    常规拓扑在模块内唯一定义为 JOINT_PARENT（出处 cheap-draft-and-programmatic-tools.md:57-59
    原文「hips → spine → neck → head；spine 下有左右肩 → 肘 → 腕，hips 下有左右髋 → 膝 → 踝」）。
  - track.joint=null / 省略（根轨道，控制整体移动/旋转）→ 动画 {shot}:root 臂架根节点，
    与 hips 关节轨道分属两个节点，可并存不冲突。
  - 每 track → 一个 animation sampler（LINEAR 插值）+ 一条 rotation channel：
    input = 关键帧时间（秒，FLOAT SCALAR），output = 单位四元数（FLOAT VEC4，[x,y,z,w]）。
    欧拉角 XYZ 弧度按「x then y then z」内蕴序转四元数：q = qx⊗qy⊗qz（与 three.js
    Euler 'XYZ'、glTF 工具链口径一致；等价于外蕴 z→y→x）。
  - 口型层（白皮书 §3 CP5：motion.speech=full-body 必须存在独立口型层路径）：
    speech_mode=independent_lip_layer 且给 --lip-layer（ToonFlow track 形状
    {"joint":"jaw"|"mouth","frames":[{time,rotation{x,y,z}}]}）→ 额外写 {shot}:jaw 节点
    （head 之下）+ jaw 轨道；否则如实记 skipped + 原因：none=本镜无对白；independent
    无 keyframe=blocking payload 装不下口型层（schema additionalProperties:false，
    口型层 keyframe 属 CP10 字幕/音频域），须以 --lip-layer 提供文件；requires_split_shot
    =须先在分镜层拆镜（AI视频生产流水线方案.md §3.3，禁止质检环节自动改景别）。
  - buffer：data URI（base64 内嵌），保持纯 JSON .gltf。不写 skin/mesh——W4 范围是
    armature 层级 + 动画通道的往返（TASK_v4.md:197），网格绑定是 CP7 渲染层职责；
    关节平移（骨长）不在 CP5 词表/帧内（rotation-only，骨长恒定但不给数值），本器不虚构。
  - 结构兜底（s0 全量契约走查）不是本器职责——那是 validate_cp5.py 的事；本器只做
    「能否无损转换」的最低限度前置校验 + 往返自检。

自检（写盘后重新读回，四项全过才算零丢失 → exit 0）
----
  input_blocking_valid   转换前置：cp5/blocking 工件、joint_names 恰为 schema 16 关节全集、
                         track.joint ∈ 本序列词表或 null、帧时间 ≥0 且严格递增、
                         帧只含 {time,rotation} 且 rotation 只含 {x,y,z}（rotation-only）
  c1 gltf_structure      asset 2.0；scene 根 = 各序列臂架根；nodes 总数 = (16+1(+jaw))×序列数；
                         逐节点父子关系与 mannequin 拓扑一致、无环无孤儿；最大深度 6
                         （root→hips→spine→肩→肘→腕）
  c2 animations_samplers animation 数 = 序列数；channel 数 = track 数(+jaw)；每 sampler
                         input/output 访问器等长、input 时间严格递增、input 带 min/max；
                         accessor/bufferView/buffer 字节数对账（base64 解码长度 = buffer.byteLength）
  c3 keyframe_lossless   逐关键帧：读回时间与源一致（float32 容差 1e-6+1e-6·|t|）；
                         四元数单位范数（‖q‖-1 ≤ 1e-6）；四元数→欧拉（同内蕴序）与源弧度
                         逐轴差 ≤ 1e-5 rad，且同旋转判定 dot(q, q(euler)) ≥ 1-1e-6
  c4 lip_layer           jaw 轨道 written（通道实存）/ skipped（原因入 verdict）

依据：
  - contracts/v2/checkpoint.schema.json definitions.blocking / cp5_blocking（16 关节词表唯一来源）
  - research/2026-10-08/工业化视频流水线-白皮书.md §3 CP5（:104-111）
  - research/2026-10-08/cheap-draft-and-programmatic-tools.md:57-59（mannequin 16 关节与层级）
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import struct
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent            # src/gate/
VPIPE = HERE.parent.parent                        # overnight/vpipe/
DEFAULT_SCHEMA = VPIPE / "contracts" / "v2" / "checkpoint.schema.json"

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2

# ---- mannequin 常规拓扑（模块内唯一定义；词表来自 schema，父子出处见 docstring）----
JOINT_PARENT = {
    "spine": "hips", "neck": "spine", "head": "neck",
    "leftShoulder": "spine", "leftElbow": "leftShoulder", "leftWrist": "leftElbow",
    "rightShoulder": "spine", "rightElbow": "rightShoulder", "rightWrist": "rightElbow",
    "leftHip": "hips", "leftKnee": "leftHip", "leftAnkle": "leftKnee",
    "rightHip": "hips", "rightKnee": "rightHip", "rightAnkle": "rightKnee",
}   # hips 为臂架根（{shot}:root）之子；16 关节中唯一无父关节者
ROOT_TRACK = "root"      # track.joint=null → 臂架根节点
LIP_JOINT = "jaw"        # 口型层关节（节点名 {shot}:jaw，head 之子）

# ---- 往返容差（float32 存储的数值量级；不是业务阈值，不进 thresholds.yaml）----
TIME_TOL = lambda t: 1e-6 + 1e-6 * abs(t)   # noqa: E731  float32 时间相对误差
EULER_TOL = 1e-5                            # rad，四元数 float32 往返的弧度保真线
QUAT_NORM_TOL = 1e-6
QUAT_DOT_TOL = 1e-6

N_COMPONENTS = {"SCALAR": 1, "VEC4": 4}


# ---------------------------------------------------------------- ----------
# 欧拉(XYZ 弧度, 内蕴 x→y→z) ↔ 四元数 [x,y,z,w]
# ---------------------------------------------------------------- ----------
def euler_xyz_to_quat(x: float, y: float, z: float) -> tuple:
    """内蕴 x then y then z：q = qx ⊗ qy ⊗ qz（= three.js Euler 'XYZ'）。

    展开（cx=cos(x/2)…，Hamilton 乘法手算，与 three.js setFromEuler('XYZ') 逐项一致）：
      qx⊗qy = (cx·cy, cy·sx, cx·sy, sx·sy) → 再 ⊗ qz 得下式。
    """
    cx, sx = math.cos(x * 0.5), math.sin(x * 0.5)
    cy, sy = math.cos(y * 0.5), math.sin(y * 0.5)
    cz, sz = math.cos(z * 0.5), math.sin(z * 0.5)
    return (
        sx * cy * cz + cx * sy * sz,
        cx * sy * cz - sx * cy * sz,
        cx * cy * sz + sx * sy * cz,
        cx * cy * cz - sx * sy * sz,
    )


def quat_normalize(q: tuple) -> tuple:
    n = math.sqrt(sum(c * c for c in q))
    if n <= 0.0:
        raise ValueError("零向量不能归一化为四元数")
    return tuple(c / n for c in q)


def quat_dot(a: tuple, b: tuple) -> float:
    return sum(x * y for x, y in zip(a, b))


def quat_to_euler_xyz(x: float, y: float, z: float, w: float) -> tuple:
    """四元数 → 内蕴 XYZ 欧拉角（R = Rx·Ry·Rz 的矩阵元反解，与上面正向互逆）。

    R[0][2]=sin(y) → y=asin；y=atan2(-R[1][2],R[2][2])；z=atan2(-R[0][1],R[0][0])。
    万向锁（|sin y|≈1）取 z=0、x=atan2(R[1][0],R[1][1])（对称约定，与正向严格互逆的
    局限在此注明：CP5 帧弧度远离 ±π/2 gimbal 面，往返实测不触）。
    """
    sin_y = 2.0 * (x * z + w * y)
    sin_y = max(-1.0, min(1.0, sin_y))
    y_ang = math.asin(sin_y)
    if abs(sin_y) < 1.0 - 1e-9:
        x_ang = math.atan2(2.0 * (w * x - y * z), 1.0 - 2.0 * (x * x + y * y))
        z_ang = math.atan2(2.0 * (w * z - x * y), 1.0 - 2.0 * (y * y + z * z))
    else:
        z_ang = 0.0
        x_ang = math.atan2(2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z))
        if sin_y < 0.0:
            x_ang = -x_ang
    return (x_ang, y_ang, z_ang)


def angle_diff(a: float, b: float) -> float:
    """两角最小绝对差（按 2π 卷绕）。"""
    d = abs(a - b) % (2.0 * math.pi)
    return min(d, 2.0 * math.pi - d)


# ---------------------------------------------------------------- ----------
# 词表装载（exit 2 通道；词表唯一来源 = checkpoint.schema.json，与 validate_cp5 同源）
# ---------------------------------------------------------------- ----------
def load_joint_vocab(schema_path: Path) -> list:
    if not schema_path.is_file():
        raise RuntimeError(f"schema 文件不存在：{schema_path}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"schema 解析失败（{schema_path}）：{exc}")
    node = schema
    for k in ("definitions", "blocking", "properties", "sequences", "items",
              "properties", "joint_names", "items", "enum"):
        if not isinstance(node, dict) or k not in node:
            raise RuntimeError("schema 指针走不到 definitions.blocking joint_names 枚举"
                               "（缺 %r）——16 关节词表不可取，拒绝运行" % k)
        node = node[k]
    if (not isinstance(node, list) or len(node) != 16
            or not all(isinstance(j, str) for j in node) or len(set(node)) != 16):
        raise RuntimeError(f"schema joint_names 枚举应为 16 个不重复关节名，实为 {node!r}")
    missing = [j for j in node if j != "hips" and j not in JOINT_PARENT]
    if missing:
        raise RuntimeError(f"schema 关节 {missing} 在 JOINT_PARENT 拓扑表中无父子定义")
    return list(node)


def _error_out(msg: str, artifact_path: Path | None = None, out_path: Path | None = None) -> dict:
    """exit 2 通道的 verdict 形状（与 pass/fail 同构：恒含 verdict/exit_code）。"""
    return {
        "converter": "blocking_to_gltf",
        "artifact": str(artifact_path) if artifact_path is not None else None,
        "output": str(out_path) if out_path is not None else None,
        "verdict": "error",
        "exit_code": EXIT_ERROR,
        "lossless": None,
        "error": msg,
        "problems": [], "warnings": [], "checks": [],
    }


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------- ----------
# 转换前置校验（只做「能否无损转换」的最低限度；全量契约走查归 validate_cp5.py）
# ---------------------------------------------------------------- ----------
def check_frames(frames, label: str):
    """帧级校验（时间 ≥0 且严格递增、帧只含 {time,rotation}、rotation 只含 {x,y,z} 数值）。

    返回 (problems, nframes)；nframes=[(t,x,y,z)]，problems 非空时不入规范结果。"""
    problems, nframes = [], []
    prev = None
    for f_idx, frame in enumerate(frames):
        flabel = f"{label}.frames[{f_idx}]"
        bad = False
        if not isinstance(frame, dict):
            problems.append(f"{flabel}: 非对象")
            continue
        extra = [k for k in frame if k not in ("time", "rotation")]
        if extra:
            problems.append(
                f"{flabel}: 帧含 rotation 以外通道字段 {extra}——rotation-only 骨长恒定，"
                "无法无损写成 glTF rotation 通道（禁 scale/translation/position/location）")
            bad = True
        t = frame.get("time")
        t_ok = False
        if not _is_num(t):
            problems.append(f"{flabel}.time 非数值")
            bad = True
        elif t < 0:
            problems.append(f"{flabel}.time={t} < 0（schema minimum 0）")
            bad = True
        elif prev is not None and t <= prev:
            problems.append(
                f"{flabel}.time={t} 未严格大于前一帧 {prev}（帧时间必须单调递增，"
                "glTF sampler input 亦要求严格递增）")
            bad = True
        else:
            prev = t
            t_ok = True
        rot = frame.get("rotation")
        if not isinstance(rot, dict):
            problems.append(f"{flabel}.rotation 缺失或非对象")
            bad = True
        else:
            rextra = [k for k in rot if k not in ("x", "y", "z")]
            if rextra:
                problems.append(f"{flabel}.rotation 契约外字段 {rextra}（只许 x/y/z 欧拉弧度）")
                bad = True
            comps = []
            for axis in ("x", "y", "z"):
                v = rot.get(axis)
                if not _is_num(v):
                    problems.append(f"{flabel}.rotation.{axis} 非数值")
                    bad = True
                else:
                    comps.append(float(v))
            if len(comps) == 3 and t_ok:
                nframes.append((float(t), *comps))
        if bad:
            return problems, []   # 一帧坏即轨道坏，问题已逐条登记
    return problems, nframes


def check_tracks(seq: dict, idx: int, vocab: list):
    """返回 (problems, norm_tracks)。norm_tracks=[{joint(None|str), frames:[(t,x,y,z)]}]。"""
    tag = f"sequences[{idx}]({seq.get('shot_id', '?')})"
    problems, norm = [], []
    names = seq.get("joint_names")
    if not isinstance(names, list):
        problems.append(f"{tag}: joint_names 缺失或非数组，无法建 16 关节层级")
        names = []
    seen = set()
    illegal = [n for n in names if not isinstance(n, str) or n not in vocab]
    missing = sorted(set(vocab) - {n for n in names if isinstance(n, str)})
    for n in names:
        if isinstance(n, str):
            if n in seen:
                problems.append(f"{tag}: 关节名重复 {n!r}（16 关节穷举要求集合相等）")
            seen.add(n)
    if illegal:
        problems.append(f"{tag}: 非法关节名 {illegal}——joint_names 须恰为 schema 16 关节全集：{vocab}")
    elif missing:
        problems.append(f"{tag}: 缺关节 {missing}——joint_names 须恰为 schema 16 关节全集：{vocab}")
    if not isinstance(seq.get("shot_id"), str) or not seq.get("shot_id"):
        problems.append(f"{tag}: shot_id 缺失或非字符串（节点命名需要）")

    tracks = seq.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        problems.append(f"{tag}: tracks 缺失或为空（schema minItems 1），无动画可写")
        return problems, norm
    for t_idx, track in enumerate(tracks):
        label = f"{tag}: tracks[{t_idx}]"
        if not isinstance(track, dict):
            problems.append(f"{label}: 非对象")
            continue
        joint = track.get("joint")
        if joint is not None and (not isinstance(joint, str) or joint not in seen or joint not in vocab):
            problems.append(
                f"{label}.joint={joint!r} 不在本序列 joint_names 词表内（track 引用不存在的关节；"
                f"schema 16 关节词表={vocab}）——无法建节点，拒绝转换")
            continue
        frames = track.get("frames")
        if not isinstance(frames, list) or not frames:
            problems.append(f"{label}.frames 缺失或为空（schema minItems 1）")
            continue
        fprobs, nframes = check_frames(frames, label)
        problems += fprobs
        if not fprobs:
            norm.append({"joint": joint, "frames": nframes})
    return problems, norm


# ---------------------------------------------------------------- ----------
# glTF 装配
# ---------------------------------------------------------------- ----------
class _BufferBuilder:
    """把 float 数据打包进单一 buffer（data URI base64），每 accessor 一个 bufferView。"""

    def __init__(self) -> None:
        self.blob = bytearray()
        self.buffer_views: list = []
        self.accessors: list = []

    def add(self, values: list, vtype: str) -> int:
        ncomp = N_COMPONENTS[vtype]
        data = struct.pack("<%df" % len(values), *values)
        offset = len(self.blob)
        self.blob.extend(data)
        self.buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        if ncomp == 1:
            mn, mx = [min(values)], [max(values)]
        else:
            mn = [min(values[i::ncomp]) for i in range(ncomp)]
            mx = [max(values[i::ncomp]) for i in range(ncomp)]
        self.accessors.append({
            "bufferView": len(self.buffer_views) - 1,
            "componentType": 5126,          # FLOAT
            "count": len(values) // ncomp,
            "type": vtype,
            "min": mn, "max": mx,
        })
        return len(self.accessors) - 1


def build_gltf(norm_seqs: list, lip_result: list, vocab: list, generator: str):
    """norm_seqs = [(seq, norm_tracks)]；lip_result = [{shot, status, reason}]。

    返回 (gltf_dict, plan)；plan 供往返自检独立核对（含源关键帧数据）。"""
    nodes: list = []
    builder = _BufferBuilder()
    scene_roots: list = []
    animations: list = []
    plan_seqs = []

    for (seq, tracks), lip in zip(norm_seqs, lip_result):
        shot = seq["shot_id"]
        with_jaw = lip["status"] == "written"
        root_name = f"{shot}:root"
        all_names = ([root_name] + [f"{shot}:{j}" for j in vocab]
                     + ([f"{shot}:{LIP_JOINT}"] if with_jaw else []))

        # 先按名建空节点占位（children 顺序 = schema 枚举序，确定性输出），再统一填索引
        idx_by_name: dict = {}
        for nm in all_names:
            nodes.append({"name": nm})
            idx_by_name[nm] = len(nodes) - 1
        kids_by_name: dict = {nm: [] for nm in all_names}
        kids_by_name[root_name].append(f"{shot}:hips")
        for j in vocab:
            if j != "hips":
                kids_by_name[f"{shot}:{JOINT_PARENT[j]}"].append(f"{shot}:{j}")
        if with_jaw:
            kids_by_name[f"{shot}:head"].append(f"{shot}:{LIP_JOINT}")
        for nm, kids in kids_by_name.items():
            if kids:
                nodes[idx_by_name[nm]]["children"] = [idx_by_name[k] for k in kids]
        scene_roots.append(idx_by_name[root_name])

        samplers, channels = [], []
        plan_channels = []
        for track in tracks:
            joint = track["joint"]
            node_name = f"{shot}:root" if joint is None else f"{shot}:{joint}"
            node_idx = idx_by_name[node_name]
            frames = track["frames"]
            times = [f[0] for f in frames]
            quats = []
            for _t, x, y, z in frames:
                quats.extend(quat_normalize(euler_xyz_to_quat(x, y, z)))
            ia = builder.add(times, "SCALAR")
            oa = builder.add(quats, "VEC4")
            samplers.append({"input": ia, "interpolation": "LINEAR", "output": oa})
            channels.append({"sampler": len(samplers) - 1,
                             "target": {"node": node_idx, "path": "rotation"}})
            plan_channels.append({
                "node_name": node_name, "kind": ROOT_TRACK if joint is None else joint,
                "times": times, "euler": [(x, y, z) for _t, x, y, z in frames],
            })
        if lip["status"] == "written":
            joint = lip["joint"]
            node_name = f"{shot}:{LIP_JOINT}"
            node_idx = idx_by_name[node_name]
            frames = lip["frames"]
            times = [f[0] for f in frames]
            quats = []
            for _t, x, y, z in frames:
                quats.extend(quat_normalize(euler_xyz_to_quat(x, y, z)))
            ia = builder.add(times, "SCALAR")
            oa = builder.add(quats, "VEC4")
            samplers.append({"input": ia, "interpolation": "LINEAR", "output": oa})
            channels.append({"sampler": len(samplers) - 1,
                             "target": {"node": node_idx, "path": "rotation"}})
            plan_channels.append({"node_name": node_name, "kind": LIP_JOINT,
                                  "times": times,
                                  "euler": [(x, y, z) for _t, x, y, z in frames]})

        animations.append({"name": f"{shot}:blocking", "channels": channels, "samplers": samplers})
        exp_depth = _expected_depth(vocab, lip["status"] == "written")
        plan_seqs.append({
            "shot": shot,
            "root_name": f"{shot}:root",
            "expected_nodes": len(idx_by_name),
            "expected_depth": exp_depth,
            "expected_parents": {
                f"{shot}:root": None,
                **{f"{shot}:{j}": (f"{shot}:root" if j == "hips" else f"{shot}:{JOINT_PARENT[j]}")
                   for j in vocab},
                **({f"{shot}:{LIP_JOINT}": f"{shot}:head"} if lip["status"] == "written" else {}),
            },
            "channels": plan_channels,
        })

    gltf = {
        "asset": {"version": "2.0", "generator": generator},
        "scene": 0,
        "scenes": [{"name": "vpipe_blocking", "nodes": scene_roots}],
        "nodes": nodes,
        "animations": animations,
        "accessors": builder.accessors,
        "bufferViews": builder.buffer_views,
        "buffers": [{
            "uri": "data:application/octet-stream;base64,"
                   + base64.b64encode(bytes(builder.blob)).decode("ascii"),
            "byteLength": len(builder.blob),
        }],
    }
    return gltf, {"sequences": plan_seqs}


def _expected_depth(vocab: list, with_jaw: bool) -> int:
    depth = {"hips": 2}          # root(1) → hips(2)
    def _d(j):
        if j not in depth:
            depth[j] = _d(JOINT_PARENT[j]) + 1
        return depth[j]
    m = max(_d(j) for j in vocab)             # 腕链最深：root→hips→spine→肩→肘→腕 = 6
    return max(m, _d("head") + 1) if with_jaw else m   # jaw 挂 head 之下，不深过腕


# ---------------------------------------------------------------- ----------
# 往返自检：重新读回写盘的 .gltf，逐项核对
# ---------------------------------------------------------------- ----------
def _read_accessor(gltf: dict, acc_idx: int, raw: bytes):
    acc = gltf["accessors"][acc_idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    ncomp = N_COMPONENTS[acc["type"]]
    span = acc["count"] * ncomp * 4
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if start + span > len(raw):
        raise IndexError(f"accessor[{acc_idx}] 数据越界：{start}+{span} > buffer {len(raw)}")
    vals = struct.unpack("<%df" % (acc["count"] * ncomp), raw[start:start + span])
    if ncomp == 1:
        return list(vals), 1
    return [tuple(vals[i * 4:i * 4 + 4]) for i in range(acc["count"])], 4


def verify_gltf(path: Path, plan: dict, vocab: list):
    """重新读回 .gltf（从磁盘 JSON），返回 (problems, warnings, stats, check_problems)。"""
    problems: list = []
    warnings: list = []
    cp = {cid: [] for cid in ("gltf_structure", "animations_samplers", "keyframe_lossless")}

    def add(cid, msg):
        cp[cid].append(msg)
        problems.append(msg)

    try:
        gltf = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"写出的 .gltf 不可解析：{exc}"], warnings, {}, cp

    seqs = plan["sequences"]
    exp_total = sum(s["expected_nodes"] for s in seqs)
    nodes = gltf.get("nodes")

    # ---- c1 结构 ----
    if gltf.get("asset", {}).get("version") != "2.0":
        add("gltf_structure", f"asset.version 应为 '2.0'，实为 "
            f"{gltf.get('asset', {}).get('version')!r}")
    if len(gltf.get("scenes", [])) != 1:
        add("gltf_structure", f"scenes 应恰为 1 个，实为 {len(gltf.get('scenes', []))}")
    if not isinstance(nodes, list) or len(nodes) != exp_total:
        add("gltf_structure", f"nodes 数应为 {exp_total}（每序列 16 关节+1 臂架根(+jaw)），"
            f"实为 {len(nodes) if isinstance(nodes, list) else type(nodes).__name__}")
        return problems, warnings, {}, cp

    name_to_idx = {}
    for i, n in enumerate(nodes):
        nm = n.get("name")
        if nm in name_to_idx:
            add("gltf_structure", f"节点名重复：{nm!r}（索引 {name_to_idx[nm]} 与 {i}）")
        name_to_idx[nm] = i

    roots = gltf.get("scenes", [{}])[0].get("nodes", [])
    exp_roots = [name_to_idx[s["root_name"]] for s in seqs if s["root_name"] in name_to_idx]
    if roots != exp_roots:
        add("gltf_structure", f"scenes[0].nodes 应为序列臂架根 {exp_roots}，实为 {roots}")

    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            if not isinstance(c, int) or c < 0 or c >= len(nodes):
                add("gltf_structure", f"nodes[{i}].children 含非法索引 {c!r}")
            elif c in parent:
                add("gltf_structure", f"节点 {nodes[c].get('name')!r} 有两个父节点"
                    f"（{nodes[parent[c]].get('name')!r} 与 {n.get('name')!r}）——层级断裂")
            else:
                parent[c] = i
    # 无环 + 全可达
    for nm, idx in name_to_idx.items():
        seen, cur = set(), idx
        while cur in parent and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
        if cur in seen:
            add("gltf_structure", f"层级成环：{nm!r} 所在链")
        elif cur not in roots:
            add("gltf_structure", f"节点 {nm!r} 不可达自任何序列臂架根（父链终点"
                f"={nodes[cur].get('name')!r} 不在 scene 根）")
    # 逐序列父子关系核对
    for s in seqs:
        for child_name, exp_parent in s["expected_parents"].items():
            if child_name not in name_to_idx:
                add("gltf_structure", f"缺节点 {child_name!r}")
                continue
            got = parent.get(name_to_idx[child_name])
            got_name = nodes[got].get("name") if got is not None else None
            if got_name != exp_parent:
                add("gltf_structure", f"节点 {child_name!r} 的父应为 {exp_parent!r}，实为 {got_name!r}")
        # 深度：沿父链自根（深度 1）下数，取本序列节点最大值
        def _depth(nm):
            d, cur = 1, nm
            while parent.get(name_to_idx[cur]) is not None:
                cur = nodes[parent[name_to_idx[cur]]].get("name")
                d += 1
            return d
        present = [nm for nm in s["expected_parents"] if nm in name_to_idx]
        if s["root_name"] in name_to_idx and present:
            got_depth = max(_depth(nm) for nm in present)
            if got_depth != s["expected_depth"]:
                add("gltf_structure", f"序列 {s['shot']} 最大层级深度应为 {s['expected_depth']}"
                    f"（root→hips→spine→肩→肘→腕），实为 {got_depth}")

    # ---- c2 动画/采样器 + 缓冲对账 ----
    uri = gltf.get("buffers", [{}])[0].get("uri", "")
    raw = b""
    if not uri.startswith("data:application/octet-stream;base64,"):
        add("animations_samplers", "buffers[0].uri 不是 data URI base64（纯 JSON .gltf 要求内嵌）")
    else:
        try:
            raw = base64.b64decode(uri.split(",", 1)[1], validate=True)
        except Exception as exc:
            add("animations_samplers", f"buffer base64 解码失败：{exc}")
        if raw and len(raw) != gltf["buffers"][0].get("byteLength"):
            add("animations_samplers",
                f"buffer 对账失败：base64 解码 {len(raw)}B ≠ byteLength "
                f"{gltf['buffers'][0].get('byteLength')}B")
    anims = gltf.get("animations", [])
    if len(anims) != len(seqs):
        add("animations_samplers", f"animation 数应为 {len(seqs)}（每序列 1 个），实为 {len(anims)}")

    max_time_err, max_euler_err = 0.0, 0.0
    n_channels = n_keyframes = 0
    for s_idx, (s, anim) in enumerate(zip(seqs, anims)):
        by_node = {}
        for ch in anim.get("channels", []):
            tgt = ch.get("target", {})
            nm = nodes[tgt["node"]].get("name") if isinstance(tgt.get("node"), int) \
                and 0 <= tgt["node"] < len(nodes) else None
            if nm is None:
                add("animations_samplers",
                    f"序列 {s['shot']} 存在 target.node 非法（{tgt.get('node')!r}）的 channel")
                continue
            by_node.setdefault(nm, []).append(ch)
        exp_channels = {pc["node_name"]: pc for pc in s["channels"]}
        if sorted(by_node) != sorted(exp_channels):
            add("animations_samplers",
                f"序列 {s['shot']} channel 目标节点应为 {sorted(exp_channels)}，实为 {sorted(by_node)}")
            continue
        for nm, pc in exp_channels.items():
            chs = by_node.get(nm, [])
            if len(chs) != 1:
                add("animations_samplers", f"节点 {nm!r} 应恰有 1 条 rotation channel，实为 {len(chs)}")
                continue
            ch = chs[0]
            n_channels += 1
            if ch.get("target", {}).get("path") != "rotation":
                add("animations_samplers", f"节点 {nm!r} channel path 应为 rotation，"
                    f"实为 {ch.get('target', {}).get('path')!r}")
            sp = anim.get("samplers", [])[ch.get("sampler", -1)] \
                if isinstance(ch.get("sampler"), int) and 0 <= ch.get("sampler", -1) < len(
                    anim.get("samplers", [])) else None
            if sp is None:
                add("animations_samplers", f"节点 {nm!r} channel 的 sampler 索引非法")
                continue
            if sp.get("interpolation") != "LINEAR":
                add("animations_samplers", f"节点 {nm!r} sampler 插值应为 LINEAR，"
                    f"实为 {sp.get('interpolation')!r}")
            ia, oa = sp.get("input"), sp.get("output")
            if not isinstance(ia, int) or not isinstance(oa, int) \
                    or ia >= len(gltf.get("accessors", [])) or oa >= len(gltf.get("accessors", [])):
                add("animations_samplers", f"节点 {nm!r} sampler input/output accessor 索引非法")
                continue
            ain, aout = gltf["accessors"][ia], gltf["accessors"][oa]
            if ain.get("type") != "SCALAR" or ain.get("componentType") != 5126:
                add("animations_samplers", f"节点 {nm!r} input 应为 FLOAT SCALAR，"
                    f"实为 {ain.get('componentType')}/{ain.get('type')}")
            if aout.get("type") != "VEC4" or aout.get("componentType") != 5126:
                add("animations_samplers", f"节点 {nm!r} output 应为 FLOAT VEC4，"
                    f"实为 {aout.get('componentType')}/{aout.get('type')}")
            if ain.get("count") != len(pc["times"]) or aout.get("count") != len(pc["times"]):
                add("animations_samplers",
                    f"节点 {nm!r} 关键帧数应为 {len(pc['times'])}，input={ain.get('count')} "
                    f"output={aout.get('count')}")
            if ain.get("count") != aout.get("count"):
                add("animations_samplers", f"节点 {nm!r} sampler input/output 长度不等"
                    f"（{ain.get('count')} vs {aout.get('count')}）")
            if "min" not in ain or "max" not in ain:
                add("animations_samplers", f"节点 {nm!r} input accessor 缺 min/max"
                    "（glTF 对动画 input 访问器要求提供）")
            # bufferView 对账
            for label, acc in (("input", ain), ("output", aout)):
                bv = gltf.get("bufferViews", [])[acc.get("bufferView", -1)] \
                    if isinstance(acc.get("bufferView"), int) and 0 <= acc.get("bufferView", -1) \
                    < len(gltf.get("bufferViews", [])) else None
                if bv is None:
                    add("animations_samplers", f"节点 {nm!r} {label} accessor 的 bufferView 索引非法")
                else:
                    ncomp = N_COMPONENTS.get(acc.get("type"), 1)
                    span = acc.get("count", 0) * ncomp * 4
                    if bv.get("byteLength") != span:
                        add("animations_samplers",
                            f"节点 {nm!r} {label} bufferView.byteLength 应为 {span}B，"
                            f"实为 {bv.get('byteLength')}B")
                    if bv.get("byteOffset", 0) % 4 != 0:
                        add("animations_samplers", f"节点 {nm!r} {label} bufferView.byteOffset 未按 4B 对齐")
            try:
                times, _ = _read_accessor(gltf, ia, raw)
                quats, _ = _read_accessor(gltf, oa, raw)
            except Exception as exc:
                add("animations_samplers", f"节点 {nm!r} 采样数据读取失败：{exc}")
                continue
            # input 单调
            prev = None
            for k, t in enumerate(times):
                if prev is not None and t <= prev:
                    add("animations_samplers",
                        f"节点 {nm!r} input[{k}]={t} 未严格大于前一值 {prev}（时间必须单调递增）")
                prev = t
            # ---- c3 逐关键帧零丢失 ----
            for k, ((t_src, (ex, ey, ez)), t_got, q) in enumerate(
                    zip(zip(pc["times"], pc["euler"]), times, quats)):
                n_keyframes += 1
                terr = abs(t_got - t_src)
                max_time_err = max(max_time_err, terr)
                if terr > TIME_TOL(t_src):
                    cp["keyframe_lossless"].append(
                        f"节点 {nm!r} 帧{k} 时间丢失：源 {t_src} 读回 {t_got}（差 {terr:.3g}s）")
                qn = math.sqrt(sum(c * c for c in q))
                if abs(qn - 1.0) > QUAT_NORM_TOL:
                    cp["keyframe_lossless"].append(
                        f"节点 {nm!r} 帧{k} 四元数非单位范数：‖q‖={qn:.9f}")
                    continue
                e_got = quat_to_euler_xyz(*q)
                axis_err = [angle_diff(e_got[i], (ex, ey, ez)[i]) for i in range(3)]
                eerr = max(axis_err)
                max_euler_err = max(max_euler_err, eerr)
                if eerr > EULER_TOL:
                    cp["keyframe_lossless"].append(
                        f"节点 {nm!r} 帧{k} 弧度丢失：源 ({ex:.6f},{ey:.6f},{ez:.6f}) 读回 "
                        f"({e_got[0]:.6f},{e_got[1]:.6f},{e_got[2]:.6f})，最大轴差 {eerr:.3g} rad")
                qsrc = euler_xyz_to_quat(ex, ey, ez)
                dot = abs(quat_dot(q, qsrc))
                if dot < 1.0 - QUAT_DOT_TOL:
                    cp["keyframe_lossless"].append(
                        f"节点 {nm!r} 帧{k} 同旋转判定失败：|dot(q_read, q_src)|={dot:.9f} < 1")

    for msg in cp["keyframe_lossless"]:
        problems.append(msg)

    # ---- c4 口型层核对（通道实存性归 c2 的 by_node 比对；这里只汇总）----
    stats = {
        "nodes": len(nodes), "max_depth": max((s["expected_depth"] for s in seqs), default=0),
        "animations": len(anims), "channels": n_channels, "keyframes": n_keyframes,
        "samplers": sum(len(a.get("samplers", [])) for a in anims),
        "max_time_abs_err": max_time_err, "max_euler_abs_err_rad": max_euler_err,
        "bytes": path.stat().st_size,
    }
    return problems, warnings, stats, cp


# ---------------------------------------------------------------- ----------
# 主流程
# ---------------------------------------------------------------- ----------
def convert(artifact_path: Path, schema_path: Path, out_path: Path,
            report_path: Path | None, lip_path: Path | None) -> tuple:
    warnings: list = []

    # ---- exit 2 通道：文件与工件身份 ----
    if not artifact_path.is_file():
        return EXIT_ERROR, _error_out(f"工件文件不存在：{artifact_path}", artifact_path, out_path)
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return EXIT_ERROR, _error_out(f"工件 JSON 解析失败（{artifact_path}）：{exc}",
                                      artifact_path, out_path)
    if not isinstance(artifact, dict):
        return EXIT_ERROR, _error_out("工件顶层应为 JSON 对象", artifact_path, out_path)
    if artifact.get("cp_id") != "cp5" or artifact.get("artifact_type") != "blocking":
        return EXIT_ERROR, _error_out(
            f"非 CP5 工件：cp_id={artifact.get('cp_id')!r} artifact_type="
            f"{artifact.get('artifact_type')!r}（本器只转 cp5/blocking，请改用对应工具）",
            artifact_path, out_path)
    try:
        vocab = load_joint_vocab(schema_path)
    except RuntimeError as exc:
        return EXIT_ERROR, _error_out(str(exc), artifact_path, out_path)

    payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
    sequences = payload.get("sequences") if isinstance(payload.get("sequences"), list) else []

    # ---- 转换前置校验（fail → exit 1，不落盘）----
    pre_problems: list = []
    norm_seqs = []
    shot_seen = set()
    for idx, seq in enumerate(sequences):
        if not isinstance(seq, dict):
            pre_problems.append(f"sequences[{idx}] 非对象")
            continue
        shot = seq.get("shot_id")
        if isinstance(shot, str) and shot:
            if shot in shot_seen:
                pre_problems.append(f"sequences[{idx}]: shot_id {shot!r} 重复（节点命名按"
                                    "「shot:joint」需全局唯一）")
            shot_seen.add(shot)
        probs, tracks = check_tracks(seq, idx, vocab)
        pre_problems += probs
        norm_seqs.append((seq, tracks))
    if not sequences:
        pre_problems.append("payload.sequences 为空（schema minItems 1），无序列可写")

    def _fail(problems, checks, note=None):
        out = {
            "converter": "blocking_to_gltf",
            "task": "M1-W4 CP5 blocking → glTF 2.0 armature 往返（TASK_v4.md:197,525 决策 2026-10-08-b）",
            "artifact": str(artifact_path), "schema": str(schema_path),
            "output": str(out_path), "report": str(report_path) if report_path else None,
            "verdict": "fail", "exit_code": EXIT_FAIL, "lossless": False,
            "problems": problems, "warnings": warnings, "checks": checks,
        }
        if note:
            out["note"] = note
        return EXIT_FAIL, out

    if pre_problems:
        checks = [{
            "id": "input_blocking_valid",
            "title": "转换前置：blocking 数据可无损表示（关节词表/轨道引用/帧时间/rotation-only）",
            "source_ref": "contracts/v2/checkpoint.schema.json#definitions/blocking + "
                          "cheap-draft-and-programmatic-tools.md:57-59",
            "result": "fail", "detail": "存在不可无损转换的数据，未写出任何 .gltf",
            "problems": pre_problems, "warnings": [],
        }]
        return _fail(pre_problems, checks)

    # ---- 口型层解析 ----
    lip_track = None
    if lip_path is not None:
        if not lip_path.is_file():
            return EXIT_ERROR, _error_out(f"--lip-layer 文件不存在：{lip_path}",
                                          artifact_path, out_path)
        try:
            lip_track = json.loads(lip_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return EXIT_ERROR, _error_out(f"--lip-layer JSON 解析失败（{lip_path}）：{exc}",
                                          artifact_path, out_path)
        if not isinstance(lip_track, dict) or not isinstance(lip_track.get("frames"), list) \
                or not lip_track["frames"]:
            return EXIT_ERROR, _error_out("--lip-layer 应为 ToonFlow track 形状 "
                                          '{"joint":"jaw"|"mouth","frames":[{time,rotation}]} 且 frames 非空',
                                          artifact_path, out_path)
        if lip_track.get("joint") not in ("jaw", "mouth"):
            return EXIT_ERROR, _error_out(
                f"--lip-layer joint 应为 'jaw' 或 'mouth'，实为 {lip_track.get('joint')!r}",
                artifact_path, out_path)
        # jaw/mouth 在 16 关节词表之外（口型层关节），只查帧数据，不做关节归属检查
        lip_probs, lip_frames = check_frames(lip_track["frames"], "--lip-layer")
        if lip_probs:
            return _fail(lip_probs, [{
                "id": "input_blocking_valid",
                "title": "转换前置：--lip-layer 口型层轨道可无损表示",
                "source_ref": "白皮书 §3 CP5 口型层；ToonFlow track 形状",
                "result": "fail", "detail": "口型层关键帧数据非法，未写出任何 .gltf",
                "problems": lip_probs, "warnings": [],
            }])
        lip_track = {"joint": LIP_JOINT, "frames": lip_frames}   # 节点名统一 {shot}:jaw

    lip_result = []
    matched = 0
    for seq, _tracks in norm_seqs:
        mode = seq.get("speech_mode")
        shot = seq["shot_id"]
        if mode == "independent_lip_layer":
            if lip_track is not None:
                matched += 1
                lip_result.append({"shot": shot, "status": "written", "joint": "jaw",
                                   "frames": lip_track["frames"],
                                   "reason": f"--lip-layer 提供的 {lip_track['joint']} 轨道"
                                             f"→ 写为 {shot}:jaw 节点（head 之下）"})
            else:
                lip_result.append({"shot": shot, "status": "skipped", "joint": None, "frames": [],
                                   "reason": "speech_mode=independent_lip_layer 声明了独立口型层，"
                                             "但 blocking payload 装不下口型层 keyframe（schema "
                                             "additionalProperties:false，口型层属 CP10 域）——"
                                             "用 --lip-layer 提供轨道文件后才会写 jaw 轨道"})
        elif mode == "none":
            lip_result.append({"shot": shot, "status": "skipped", "joint": None, "frames": [],
                               "reason": "本镜无对白（speech_mode=none），无需口型层"})
        elif mode == "requires_split_shot":
            lip_result.append({"shot": shot, "status": "skipped", "joint": None, "frames": [],
                               "reason": "speech_mode=requires_split_shot——须先在分镜层拆镜为"
                                         "「无对白行走镜 + 近景对白镜」（AI视频生产流水线方案.md §3.3，"
                                         "禁止质检环节自动改景别），不写 jaw 轨道"})
        else:
            warnings.append(f"序列 {shot}: speech_mode={mode!r} 不可判（缺失/非法，validate_cp5 s0 会"
                            "否决），口型层按无对白处理：skipped")
            lip_result.append({"shot": shot, "status": "skipped", "joint": None, "frames": [],
                               "reason": f"speech_mode={mode!r} 不可判，按无对白处理"})
    if lip_track is not None and matched == 0:
        warnings.append("--lip-layer 已提供但没有任何序列 speech_mode=independent_lip_layer，"
                        "jaw 轨道未写（无落点）")

    # ---- 装配 + 落盘（先 tmp，往返通过才改名）----
    if not out_path.parent.is_dir():
        return EXIT_ERROR, _error_out(f"--out 目录不可写（不存在）：{out_path.parent}",
                                      artifact_path, out_path)
    generator = ("vpipe blocking_to_gltf (CP5 M1-W4 glTF 2.0 armature roundtrip; "
                 "TASK_v4.md:197,525 decision 2026-10-08-b)")
    gltf, plan = build_gltf(norm_seqs, lip_result, vocab, generator)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    tmp_path.write_text(json.dumps(gltf, ensure_ascii=False, indent=1), encoding="utf-8")

    problems, rt_warnings, stats, cp = verify_gltf(tmp_path, plan, vocab)
    warnings += rt_warnings
    # verify 提前返回（.gltf 不可解析）时 stats 可能缺键——补默认值保证 detail 格式化安全
    stats = {"nodes": 0, "max_depth": 0, "animations": 0, "channels": 0, "keyframes": 0,
             "samplers": 0, "max_time_abs_err": float("nan"),
             "max_euler_abs_err_rad": float("nan"), "bytes": 0, **stats}

    checks = [
        {"id": "input_blocking_valid",
         "title": "转换前置：blocking 数据可无损表示（关节词表/轨道引用/帧时间/rotation-only）",
         "source_ref": "contracts/v2/checkpoint.schema.json#definitions/blocking + "
                       "cheap-draft-and-programmatic-tools.md:57-59",
         "result": "pass",
         "detail": f"{len(norm_seqs)} 个序列、{sum(len(t) for _s, t in norm_seqs)} 条轨道"
                   f"（+{sum(1 for r in lip_result if r['status'] == 'written')} 条 jaw）全部可无损映射",
         "problems": [], "warnings": []},
        {"id": "gltf_structure",
         "title": "c1 glTF 结构：asset 2.0 / 场景根 / 节点数 / 父子层级 / 深度（重新读回）",
         "source_ref": "glTF 2.0 spec + mannequin 拓扑（cheap-draft-and-programmatic-tools.md:57-59）",
         "result": "pass" if not cp["gltf_structure"] else "fail",
         "detail": f"nodes={stats.get('nodes')}（期望 {sum(s['expected_nodes'] for s in plan['sequences'])}），"
                   f"最大深度={stats.get('max_depth')}",
         "problems": cp["gltf_structure"], "warnings": []},
        {"id": "animations_samplers",
         "title": "c2 动画与采样器：数量 / input=output 等长 / 时间严格单调 / 缓冲字节对账",
         "source_ref": "glTF 2.0 spec §animations（LINEAR；input 需 min/max）",
         "result": "pass" if not cp["animations_samplers"] else "fail",
         "detail": f"animations={stats.get('animations')} samplers={stats.get('samplers')} "
                   f"channels={stats.get('channels')} keyframes={stats.get('keyframes')}",
         "problems": cp["animations_samplers"], "warnings": []},
        {"id": "keyframe_lossless",
         "title": "c3 关键帧零丢失：时间一致（float32 容差）+ 单位四元数 + 弧度往返 ≤1e-5 rad",
         "source_ref": "TASK_v4.md:525 决策 2026-10-08-b 验收等价物（往返零丢失）",
         "result": "pass" if not cp["keyframe_lossless"] else "fail",
         "detail": f"逐关键帧核对：max|Δt|={stats.get('max_time_abs_err'):.3g}s，"
                   f"max|Δ弧度|={stats.get('max_euler_abs_err_rad'):.3g}rad"
                   f"（容差 t≤1e-6+1e-6|t|，弧度≤{EULER_TOL}）",
         "problems": cp["keyframe_lossless"], "warnings": []},
        {"id": "lip_layer",
         "title": "c4 口型层 jaw 轨道：written / skipped 如实记录",
         "source_ref": "白皮书 §3 CP5（motion.speech=full-body 须有独立口型层路径）",
         "result": "pass",
         "detail": "；".join(f"{r['shot']}:{r['status']}"
                             + (f"（{r['reason']}）" if r["status"] == "skipped" else "")
                             for r in lip_result),
         "problems": [], "warnings": []},
    ]

    all_problems = [p for c in checks for p in c["problems"]]
    verdict = "pass" if not all_problems else "fail"

    if verdict == "fail":
        tmp_path.unlink(missing_ok=True)
        out = {
            "converter": "blocking_to_gltf",
            "task": "M1-W4 CP5 blocking → glTF 2.0 armature 往返（TASK_v4.md:197,525 决策 2026-10-08-b）",
            "artifact": str(artifact_path), "schema": str(schema_path),
            "output": str(out_path), "report": str(report_path) if report_path else None,
            "verdict": verdict, "exit_code": EXIT_FAIL, "lossless": False,
            "summary": stats, "lip_layer": lip_result,
            "checks": checks, "problems": all_problems, "warnings": warnings,
        }
        return EXIT_FAIL, out

    os.replace(tmp_path, out_path)
    stats["bytes"] = out_path.stat().st_size
    out = {
        "converter": "blocking_to_gltf",
        "task": "M1-W4 CP5 blocking → glTF 2.0 armature 往返（TASK_v4.md:197,525 决策 2026-10-08-b）",
        "artifact": str(artifact_path), "schema": str(schema_path),
        "output": str(out_path), "report": str(report_path) if report_path else None,
        "verdict": verdict, "exit_code": EXIT_PASS, "lossless": True,
        "summary": stats, "lip_layer": lip_result,
        "checks": checks, "problems": [], "warnings": warnings,
    }
    return EXIT_PASS, out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="blocking_to_gltf.py",
        description="CP5 blocking → glTF 2.0 armature 往返导出器（M1-W4）："
                    "exit 0=转换+往返零丢失 / 1=数据拒绝（不落盘）/ 2=用法环境错；"
                    "verdict JSON 恒走 stdout")
    parser.add_argument("artifact", help="CP5 工件 JSON 路径（cp_id=cp5, artifact_type=blocking）")
    parser.add_argument("--out", required=True, help="输出 .gltf 路径（JSON 格式，非 .glb）")
    parser.add_argument("--report", default=None, help="往返校验结果 JSON 路径（可选）")
    parser.add_argument("--lip-layer", default=None, dest="lip_layer",
                        help="口型层轨道 JSON（ToonFlow track 形状 {joint:'jaw'|'mouth',frames:[…]}，可选）")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA),
                        help=f"checkpoint.schema.json 路径（默认 {DEFAULT_SCHEMA}）")
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    report_path = Path(args.report) if args.report else None
    lip_path = Path(args.lip_layer) if args.lip_layer else None

    try:
        code, out = convert(Path(args.artifact), Path(args.schema), out_path, report_path, lip_path)
    except Exception as exc:    # 未预期异常也守「stdout 恒输出 verdict JSON」口径（exit 2 通道）
        import traceback
        traceback.print_exc(file=sys.stderr)
        code = EXIT_ERROR
        out = _error_out(f"转换器内部未预期异常：{type(exc).__name__}: {exc}",
                         Path(args.artifact), out_path)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if report_path is not None:
        if not report_path.parent.is_dir():
            print(f"[blocking_to_gltf] ERROR：--report 目录不可写（不存在）：{report_path.parent}",
                  file=sys.stderr)
            return EXIT_ERROR
        report_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if code == EXIT_FAIL:
        print(f"[blocking_to_gltf] FAIL：{len(out['problems'])} 条问题，未写出 .gltf"
              f"（{out_path}；详见 stdout verdict JSON）", file=sys.stderr)
    elif code == EXIT_ERROR:
        print(f"[blocking_to_gltf] ERROR：{out.get('error', '?')}", file=sys.stderr)
    else:
        s = out["summary"]
        print(f"[blocking_to_gltf] PASS：零丢失 → {out_path} "
              f"（{s['nodes']} 节点 / 深度 {s['max_depth']} / {s['animations']} animation / "
              f"{s['keyframes']} 关键帧 / {s['bytes']}B；max|Δ弧度|={s['max_euler_abs_err_rad']:.2g}rad）",
              file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
