#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_cp5.py — CP5 动作脚本（Blocking）门禁校验器（v4 · M1）。

用法
----
    python3 src/gate/validate_cp5.py <artifact.json> [--thresholds PATH] [--schema PATH]

    （默认相对本文件定位：<vpipe>/eval/thresholds.yaml 与
      <vpipe>/contracts/v2/checkpoint.schema.json，从任意 cwd 运行均可。）

退出码
------
    0 = pass   全部校验项通过（warn 不否决，只标注）
    1 = fail   门禁不过（任一校验项 fail；拒绝是数据，verdict JSON 里逐条给 reason）
    2 = error  用法/环境/工件不是本 CP：文件缺失、JSON 不可解析、cp_id≠cp5、
               thresholds/schema 缺失或缺键（含布尔强制键被改 false —— 拒绝旁路门禁）

stdout 恒输出一个 JSON verdict（含 pass/fail/error 三态）；人读过程信息走 stderr。

校验项（编号承接任务书；数值一律从 eval/thresholds.yaml checkpoints.cp5.gate.* 读，
结构词表一律从 contracts/v2/checkpoint.schema.json 读，模块内不出现第二套数值——
checkpoint.schema.json 红线① / thresholds.yaml v4 段头注释）：

  s0 schema_structure      CP5 分支契约符合性（结构兜底层：required/additionalProperties/
                           enum/const/pattern/min-max 逐层走查；不替代 JSON Schema 全量校验器，
                           但足以让 ①-⑥ 安全运行）
  ①  joint_names_legal     关节名合法：joint_names 必须恰为 schema 16 关节穷举（集合相等、
                           无重复）；track.joint ∈ 同一词表或 null（根轨道）。
                           词表来源：checkpoint.schema.json definitions.blocking（ToonFlow
                           director3dNode mannequin schema，cheap-draft-and-programmatic-tools.md:57-59）
  ②  frame_time_monotonic  每个 track 的 frames[].time 严格递增（阈值键
                           checkpoints.cp5.gate.frame_time_monotonic，布尔强制键）
  ③  pose_frame_max        每序列 frame_count ≤ 上限（checkpoints.cp5.gate.pose_frame_max，
                           MimicMotion 72 帧 @576×1024 口径，cheap-draft-and-programmatic-tools.md:219）。
                           白皮书 CP5 失败回退行：72 帧装不下 → 分段 + progressive latent fusion，
                           拼接缝登记 known_cuts——故 F>L 且切点登记充分（⑥ 判可分）时 ③ 放行并注明；
                           F>L 且无切点/切点不足 → ③⑥ 双 fail
  ④  bone_length_constant  rotation-only 骨长恒定：bone_length_constant 必须 true（schema const），
                           帧对象只许 {time, rotation}，出现 scale/translation/position/location
                           任一通道字段即 fail（mannequin 动画轨道「帧只填写 rotation，保留固定骨长」）
  ⑤  speech_fullbody_lip_layer
                           对白与全身动作关系（checkpoints.cp5.gate.speech_fullbody_lip_layer，
                           布尔强制键）。speech_mode 词表三值到判定的映射（词表唯一来源 schema）：
                             none                  → 无对白，pass
                             independent_lip_layer → 已声明独立口型层路径，pass
                             requires_split_shot   → full-body 对白镜无口型层 → fail，提示按
                               白皮书 §3 CP5 / AI视频生产流水线方案.md §3.3 降级拆镜为
                               「无对白行走镜 + 近景对白镜」（分镜层规避，退回 CP3 改分镜；
                               禁止质检环节自动改景别）
  ⑥  known_cuts_registered >帧数上限需分段时，段间切点必须登记：切点须为 ≥0 数值且严格递增；
                           F>L 时切点数 ≥ ceil(F/L)-1（每段 ≤L 的必要条件）；切点落在最后一个
                           关键帧之后 → warn（尾帧保持区间，人工确认，不否决）；F≤L 却登记切点
                           → warn。下游 CP11 汇入合成层 known_cuts 白名单
                           （容差沿 judges.J6_detectors_v2.rule_params.known_cuts_tol_s，非本器职责）
  s1 params_ref_resolvable 工件 gate/aux_gates 的 params_ref 必须解析到 thresholds.yaml 真实键
                           （schema 红线①：cp5.gate.* → checkpoints.cp5.gate.*，其余前缀按
                           thresholds.yaml v4 段头「解析口径」走文件根；悬空引用 fail）

依据（本器只做序列结构与规则校验；Blender 连通性验证不在范围，W4 另做）：
  - contracts/v2/checkpoint.schema.json definitions.cp5_blocking / definitions.blocking
  - eval/thresholds.yaml:247-255 checkpoints.cp5.gate（v4）
  - research/2026-10-08/工业化视频流水线-白皮书.md §3 CP5（:104-111）
  - research/2026-10-08/cheap-draft-and-programmatic-tools.md:57-59（mannequin 16 关节）、:219（72 帧）
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent            # src/gate/
VPIPE = HERE.parent.parent                        # overnight/vpipe/
DEFAULT_THRESHOLDS = VPIPE / "eval" / "thresholds.yaml"
DEFAULT_SCHEMA = VPIPE / "contracts" / "v2" / "checkpoint.schema.json"

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2

# ④ rotation-only：帧级禁入通道字段（出现即骨长恒定违例；mannequin「帧只填写 rotation」）
TRANSFORM_CHANNELS = ("scale", "translation", "position", "location")

CP5_GATE_PREFIX_RE = re.compile(r"^cp([1-9]|1[0-2])\.gate\.")


# ---------------------------------------------------------------- ----------
# 小工具
# ---------------------------------------------------------------- ----------
def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_LEAF_INDEX_RE = re.compile(r"\[\d+\]+$")


def _base_leaf(path: str) -> str:
    """'a.b[3]' -> 'b'：数组下标剥离后的末级键名。"""
    return _LEAF_INDEX_RE.sub("", path.rsplit(".", 1)[-1])


def _schema_at(root: dict, keys: list, what: str):
    """按固定指针从 schema 取词表；schema 结构变更 → 报错（调用方转 exit 2）。"""
    node = root
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            raise KeyError(f"schema 指针走不到 {what}：{'/'.join(map(str, keys))}（缺 {k!r}）")
        node = node[k]
    return node


def _deref(spec, root: dict, depth: int = 0):
    """就地解引用 #/definitions/...（仅本地 $ref，带环保护）。"""
    seen = 0
    while isinstance(spec, dict) and "$ref" in spec and seen < 16:
        ref = spec["$ref"]
        if not ref.startswith("#/"):
            raise KeyError(f"不支持的非本地 $ref：{ref}")
        spec = _schema_at(root, ref[2:].split("/"), ref)
        seen += 1
    if depth > 16:
        raise KeyError("schema $ref 解引用过深")
    return spec


class Problems:
    """结构层问题收集器：每条 = (path, message)。"""

    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def add(self, path: str, msg: str) -> None:
        self.items.append((path, msg))

    def take(self, pred) -> list[tuple[str, str]]:
        """取走满足 pred(path,msg) 的条目（check 间归属去重用）。"""
        kept, moved = [], []
        for it in self.items:
            (moved if pred(*it) else kept).append(it)
        self.items = kept
        return moved


# ---------------------------------------------------------------- ----------
# s0：契约结构兜底层（对 cp5 分支做逐层 required/additionalProperties/
#     enum/const/pattern/min-max 走查；词表全部来自 schema 本体）
# ---------------------------------------------------------------- ----------
def _check_type(v, t, path, prob: Problems) -> bool:
    types = t if isinstance(t, list) else [t]
    for name in types:
        if name == "object" and isinstance(v, dict):
            return True
        if name == "array" and isinstance(v, list):
            return True
        if name == "string" and isinstance(v, str):
            return True
        if name == "boolean" and isinstance(v, bool):
            return True
        if name == "integer" and isinstance(v, int) and not isinstance(v, bool):
            return True
        if name == "number" and _is_num(v):
            return True
        if name == "null" and v is None:
            return True
    prob.add(path, f"类型应为 {t}，实为 {type(v).__name__}")
    return False


def _check_value(v, spec, root, path, prob: Problems, skip_enum_paths=frozenset()) -> None:
    spec = _deref(spec, root)
    if not isinstance(spec, dict):
        return
    for sub in spec.get("allOf", []):
        _check_value(v, sub, root, path, prob, skip_enum_paths)
    if "type" in spec:
        if not _check_type(v, spec["type"], path, prob):
            return
    if "const" in spec:
        want = spec["const"]
        same_type = (isinstance(want, bool) and isinstance(v, bool)) or (
            not isinstance(want, bool) and not isinstance(v, bool))
        if not (same_type and v == want):
            prob.add(path, f"const 应为 {want!r}，实为 {v!r}")
    if "enum" in spec:
        if _base_leaf(path) not in skip_enum_paths:   # joint_names 枚举归 ①（含去重语义）
            if not any((v is e) or (type(v) is type(e) and v == e) for e in spec["enum"]):
                prob.add(path, f"值 {v!r} 不在词表 {spec['enum']!r} 内")
    if _is_num(v) and "minimum" in spec and v < spec["minimum"]:
        prob.add(path, f"{v!r} < minimum {spec['minimum']!r}")
    if _is_num(v) and "maximum" in spec and v > spec["maximum"]:
        prob.add(path, f"{v!r} > maximum {spec['maximum']!r}")
    if isinstance(v, str):
        if "pattern" in spec and not re.search(spec["pattern"], v):
            prob.add(path, f"不匹配 pattern {spec['pattern']!r}: {v!r}")
        if "minLength" in spec and len(v) < spec["minLength"]:
            prob.add(path, f"长度 {len(v)} < minLength {spec['minLength']}")
        if "maxLength" in spec and len(v) > spec["maxLength"]:
            prob.add(path, f"长度 {len(v)} > maxLength {spec['maxLength']}")
    if isinstance(v, list):
        if "minItems" in spec and len(v) < spec["minItems"]:
            prob.add(path, f"条目数 {len(v)} < minItems {spec['minItems']}")
        if "maxItems" in spec and len(v) > spec["maxItems"]:
            prob.add(path, f"条目数 {len(v)} > maxItems {spec['maxItems']}")
        if isinstance(spec.get("items"), dict):
            for i, item in enumerate(v):
                _check_value(item, spec["items"], root, f"{path}[{i}]", prob, skip_enum_paths)
    if isinstance(v, dict) and "properties" in spec:
        _check_level(v, spec, root, path, prob, skip_enum_paths)


def _check_level(obj: dict, spec_raw, root, path, prob: Problems, skip_enum_paths=frozenset()) -> None:
    """对象层：合并 allOf，查 required / additionalProperties:false / 逐属性递归。"""
    spec = _deref(spec_raw, root)
    required, properties, additional = [], {}, None
    for sub in [spec] + list(spec.get("allOf", [])):
        sub = _deref(sub, root)
        if not isinstance(sub, dict):
            continue
        required.extend(sub.get("required", []))
        properties.update(sub.get("properties", {}))
        if "additionalProperties" in sub:
            additional = sub["additionalProperties"]
    for key in dict.fromkeys(required):
        if key not in obj:
            prob.add(f"{path}.{key}" if path else key, "required 字段缺失")
    if additional is False:
        for key in obj:
            if key not in properties:
                prob.add(f"{path}.{key}" if path else key, f"契约外字段（additionalProperties:false）: {key!r}")
    for key, val in obj.items():
        if key in properties:
            child = f"{path}.{key}" if path else key
            _check_value(val, properties[key], root, child, prob, skip_enum_paths)


# ---------------------------------------------------------------- ----------
# 阈值 / 词表装载（exit 2 通道）
# ---------------------------------------------------------------- ----------
def load_gate_inputs(thresholds_path: Path, schema_path: Path) -> dict:
    try:
        import yaml  # noqa: 与 qc_orch 系列同一依赖口径（PyYAML）
    except ImportError:
        raise RuntimeError("缺少 PyYAML（pip install pyyaml）；qc_orch 系列同依赖，环境应已具备")

    if not thresholds_path.is_file():
        raise RuntimeError(f"thresholds 文件不存在：{thresholds_path}")
    try:
        th = yaml.safe_load(thresholds_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"thresholds 解析失败（{thresholds_path}）：{exc}")
    if not isinstance(th, dict):
        raise RuntimeError(f"thresholds 顶层应为映射：{thresholds_path}")

    gate = _walk(th, ["checkpoints", "cp5", "gate"])
    if gate is None:
        raise RuntimeError(
            "thresholds v4 缺段 checkpoints.cp5.gate（eval/thresholds.yaml 末段，"
            "v4 根命名空间 cpN.gate.* 的落点）")
    if not isinstance(gate, dict):
        raise RuntimeError("checkpoints.cp5.gate 应为映射")

    pose_frame_max = gate.get("pose_frame_max")
    if not _is_num(pose_frame_max) or pose_frame_max <= 0:
        raise RuntimeError(
            f"checkpoints.cp5.gate.pose_frame_max 必须为正数，实为 {pose_frame_max!r}"
            "（MimicMotion 72 帧口径，v4 初值见 evidence/thresholds/v3-to-v4-migration.md:80）")
    force_keys = {}
    for key in ("frame_time_monotonic", "speech_fullbody_lip_layer"):
        val = gate.get(key)
        if val is not True:
            raise RuntimeError(
                f"checkpoints.cp5.gate.{key} 是布尔强制键，必须为 true（实为 {val!r}）；"
                "false=旁路门禁，校验器拒绝在此配置下运行（thresholds v4 段头口径）")
        force_keys[key] = True

    if not schema_path.is_file():
        raise RuntimeError(f"schema 文件不存在：{schema_path}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"schema 解析失败（{schema_path}）：{exc}")

    blocking = _walk(schema, ["definitions", "blocking"])
    if blocking is None:
        raise RuntimeError("schema 缺 definitions.blocking（cp5 payload 分支）")
    vocab = {
        "joint_names_enum": _schema_at(schema, [
            "definitions", "blocking", "properties", "sequences", "items",
            "properties", "joint_names", "items", "enum"], "joint_names 枚举"),
        "track_joint_enum": _schema_at(schema, [
            "definitions", "blocking", "properties", "sequences", "items",
            "properties", "tracks", "items", "properties", "joint", "enum"], "track.joint 枚举"),
        "cp5_branch": _walk(schema, ["definitions", "cp5_blocking"]),
    }
    if vocab["cp5_branch"] is None:
        raise RuntimeError("schema 缺 definitions.cp5_blocking（CP5 工件分支）")
    joint_set = set(vocab["joint_names_enum"])
    if joint_set - {j for j in vocab["track_joint_enum"] if j is not None}:
        raise RuntimeError("schema 内部不一致：joint_names 枚举与 track.joint 枚举不同源")
    if len(joint_set) != 16:
        raise RuntimeError(f"schema joint_names 枚举应为 16 关节，实为 {len(joint_set)}")

    return {
        "pose_frame_max": pose_frame_max,
        "force_keys": force_keys,
        "schema": schema,
        "vocab": vocab,
        "thresholds_raw": th,
    }


def _walk(node, keys):
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def resolve_params_ref(ref: str, th: dict) -> bool:
    """thresholds.yaml v4 段头「解析口径」：cpN.gate.* → checkpoints.cpN.gate.*；
    其余前缀（l0_preflight.* / judges.* / ensemble.* / eval_admission.*）走文件根。"""
    keys = ref.split(".")
    if CP5_GATE_PREFIX_RE.match(ref):
        keys = ["checkpoints"] + keys
    return _walk(th, keys) is not None


# ---------------------------------------------------------------- ----------
# ①-⑥ 规则校验
# ---------------------------------------------------------------- ----------
def check_joint_names(seq: dict, idx: int, vocab: dict):
    """① 关节名合法：恰为 schema 16 关节穷举（集合相等 + 无重复）。"""
    problems, tag = [], f"sequences[{idx}]({seq.get('shot_id', '?')})"
    names = seq.get("joint_names")
    enum = vocab["joint_names_enum"]
    if not isinstance(names, list):
        return [f"{tag}: joint_names 缺失或非数组（见结构层）"]
    seen, illegal = set(), []
    for n in names:
        if n not in enum:
            illegal.append(repr(n))
        if n in seen:
            problems.append(f"{tag}: 关节名重复 {n!r}（16 关节穷举要求集合相等，不许重复）")
        seen.add(n)
    if illegal:
        problems.append(f"{tag}: 非法关节名 {', '.join(illegal)}——16 关节穷举词表 "
                        f"（ToonFlow mannequin schema，cheap-draft-and-programmatic-tools.md:57-59）：{enum}")
    missing = sorted(set(enum) - seen)
    if not illegal and not problems and missing:
        problems.append(f"{tag}: 缺关节 {missing}（joint_names 须恰为 16 关节全集）")
    # 轨道关节 ∈ 本序列词表 或 null（根轨道）
    for t_idx, track in enumerate(seq.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        joint = track.get("joint")
        if joint is not None and joint not in seen:
            problems.append(f"{tag}: tracks[{t_idx}].joint={joint!r} 不在 joint_names 词表内")
    return problems


def check_frame_time(seq: dict, idx: int, prob: Problems):
    """② 每个 track 的 frames[].time 严格递增（且 ≥0；≥0 的结构面归 s0）。"""
    problems, tag = [], f"sequences[{idx}]({seq.get('shot_id', '?')})"
    for t_idx, track in enumerate(seq.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        frames = track.get("frames")
        if not isinstance(frames, list):
            continue
        label = f"{tag}: tracks[{t_idx}]" + (f"[joint={track['joint']}]" if track.get("joint") else "[root]")
        prev = None
        for f_idx, frame in enumerate(frames):
            if not isinstance(frame, dict) or not _is_num(frame.get("time")):
                continue
            t = frame["time"]
            if prev is not None and t <= prev:
                problems.append(
                    f"{label}: frames[{f_idx}].time={t} 未严格大于前一帧 {prev}"
                    "（帧时间必须单调递增；重复时间戳=重复关键帧，拒）")
            prev = t
    return problems


def seq_frame_stats(seq: dict):
    """返回 (frame_count 或 None, max_keyframe_time 或 None)。"""
    fc = seq.get("frame_count")
    if not _is_num(fc) or isinstance(fc, bool):
        fc = None
    t_max = None
    for track in seq.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        for frame in track.get("frames") or []:
            if isinstance(frame, dict) and _is_num(frame.get("time")):
                t_max = frame["time"] if t_max is None else max(t_max, frame["time"])
    return fc, t_max


def check_pose_frame_max_and_cuts(seq: dict, idx: int, frame_limit):
    """③ pose_frame_max 与 ⑥ known_cuts（同源数值联动，见模块 docstring ③ 条）。"""
    tag = f"sequences[{idx}]({seq.get('shot_id', '?')})"
    fc, t_max = seq_frame_stats(seq)
    cuts = seq.get("known_cuts") or []

    # ---- ⑥ 切点登记质量（先算，③ 依赖其“是否足以分段”结论）----
    cut_problems, cut_warnings = [], []
    prev = None
    for c_idx, c in enumerate(cuts):
        if not _is_num(c):
            cut_problems.append(f"{tag}: known_cuts[{c_idx}]={c!r} 非数值（见结构层）")
            continue
        if c < 0:
            cut_problems.append(f"{tag}: known_cuts[{c_idx}]={c} < 0")
        if prev is not None and c <= prev:
            cut_problems.append(
                f"{tag}: known_cuts[{c_idx}]={c} 未严格大于前一切点 {prev}（切点须严格递增、不重复）")
        prev = c
        if t_max is not None and c > t_max:
            cut_warnings.append(
                f"{tag}: known_cuts[{c_idx}]={c} 在最后一个关键帧时间 {t_max} 之后"
                "（尾帧保持区间拼接？）——warn 不否决，请人工确认该拼接必要")
    split_needed = fc is not None and fc > frame_limit
    if split_needed:
        need = math.ceil(fc / frame_limit) - 1
        if len(cuts) < need:
            cut_problems.append(
                f"{tag}: 帧数 {fc} > 上限 {frame_limit}（MimicMotion 72 帧口径）需分段 ≥{need + 1} 段"
                f"（每段 ≤{frame_limit}），段间切点必须登记：known_cuts 仅 {len(cuts)} 个 < 需要 {need} 个"
                "（白皮书 §3 CP5 失败回退行：分段 + progressive latent fusion，拼接缝必须登记 known_cuts）")
        registered_ok = len(cuts) >= need and not cut_problems
    else:
        registered_ok = False
        if cuts:
            cut_warnings.append(
                f"{tag}: 帧数 {fc} ≤ 上限 {frame_limit} 无需分段，却登记了 {len(cuts)} 个拼接缝"
                "——若为分段产物合并段请保留并在 notes 说明，否则删除登记")

    # ---- ③ 帧数上限 ----
    pose_problems = []
    if fc is None:
        pose_problems.append(f"{tag}: frame_count 缺失或非整数（见结构层），无法判帧数上限")
    elif fc > frame_limit and not registered_ok:
        pose_problems.append(
            f"{tag}: 帧数 {fc} > 上限 {frame_limit}（checkpoints.cp5.gate.pose_frame_max，"
            "MimicMotion 72 帧 @576×1024 口径，cheap-draft-and-programmatic-tools.md:219）"
            "且分段切点登记不充分——超限必须分段并在 known_cuts 登记"
            "（白皮书 §3 CP5 失败回退行），或退回 CP3 拆镜改 action")
    pose_detail = (
        f"frame_count={fc} ≤ 上限 {frame_limit}，单段直过" if fc is not None and fc <= frame_limit
        else (f"frame_count={fc} > 上限 {frame_limit}，已登记 {len(cuts)} 个切点"
              f"（≥{int(math.ceil(fc / frame_limit) - 1)}，可分 {len(cuts) + 1} 段每段 ≤{frame_limit}）"
              if fc is not None else "frame_count 不可判"))
    return pose_problems, pose_detail, cut_problems, cut_warnings


def check_bone_length(seq: dict, idx: int, frame_channel_hits: list):
    """④ rotation-only 骨长恒定：bone_length_constant=true + 帧无 scale/translation 通道字段。

    frame_channel_hits：[(path, msg)]，来自结构层的帧级通道字段问题（归属挪到本检查）。"""
    problems, tag = [], f"sequences[{idx}]({seq.get('shot_id', '?')})"
    if seq.get("bone_length_constant") is not True:
        problems.append(f"{tag}: bone_length_constant 必须 true（schema const；rotation-only 是"
                        "mannequin 动画轨道「帧只填写 rotation，保留固定骨长」的结构不变量）")
    if frame_channel_hits:
        paths = [p for p, _ in frame_channel_hits]
        problems.append(
            f"{tag}: 帧对象出现 rotation 以外的变换通道字段——rotation-only 骨长恒定违例"
            f"（禁 scale/translation/position/location）：{paths}")
    return problems


def check_speech_lip_layer(seq: dict, idx: int):
    """⑤ full-body 对白镜必须有独立口型层路径声明；否则 fail 并提示拆镜。"""
    tag = f"sequences[{idx}]({seq.get('shot_id', '?')})"
    mode = seq.get("speech_mode")
    if mode == "requires_split_shot":
        return (False,
                [f"{tag}: speech_mode=requires_split_shot——full-body 对白镜无独立口型层路径 → 判 fail。"
                 "处置（白皮书 §3 CP5 / AI视频生产流水线方案.md §3.3）：降级拆镜为「无对白行走镜 + "
                 "近景对白镜」，在分镜层规避（退回 CP3 改分镜）；禁止质检环节自动改景别"], [])
    if mode == "independent_lip_layer":
        return (True, [], [f"{tag}: 已声明独立口型层路径（speech_mode=independent_lip_layer）"])
    if mode == "none":
        return (True, [], [f"{tag}: 本镜无对白（speech_mode=none），无需口型层"])
    return (True, [], [f"{tag}: speech_mode={mode!r} 不可判（缺失/非法，见结构层）；⑤ 本序列跳判，"
                       "由结构层否决兜底"])


# ---------------------------------------------------------------- ----------
# 主流程
# ---------------------------------------------------------------- ----------
def _error_out(msg: str, artifact_path: Path | None = None) -> dict:
    """exit 2 通道的 verdict 形状（与 pass/fail 同构：恒含 verdict/exit_code）。"""
    return {
        "validator": "validate_cp5",
        "artifact": str(artifact_path) if artifact_path is not None else None,
        "verdict": "error",
        "exit_code": EXIT_ERROR,
        "error": msg,
    }


def validate(artifact_path: Path, thresholds_path: Path, schema_path: Path) -> tuple[int, dict]:
    # ---- exit 2 通道：文件与配置 ----
    if not artifact_path.is_file():
        return EXIT_ERROR, _error_out(f"工件文件不存在：{artifact_path}", artifact_path)
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return EXIT_ERROR, _error_out(f"工件 JSON 解析失败（{artifact_path}）：{exc}", artifact_path)
    if not isinstance(artifact, dict):
        return EXIT_ERROR, _error_out("工件顶层应为 JSON 对象", artifact_path)
    if artifact.get("cp_id") != "cp5" or artifact.get("artifact_type") != "blocking":
        return EXIT_ERROR, _error_out(
            f"非 CP5 工件：cp_id={artifact.get('cp_id')!r} artifact_type="
            f"{artifact.get('artifact_type')!r}（本器只判 cp5/blocking，请改用对应 CP 校验器）",
            artifact_path)

    try:
        gi = load_gate_inputs(thresholds_path, schema_path)
    except RuntimeError as exc:
        return EXIT_ERROR, _error_out(str(exc), artifact_path)

    vocab, schema, th = gi["vocab"], gi["schema"], gi["thresholds_raw"]
    frame_limit = gi["pose_frame_max"]

    # ---- s0 结构兜底 ----
    prob = Problems()
    _check_level(artifact, vocab["cp5_branch"], schema, "", prob,
                 skip_enum_paths={"joint_names"})
    problems_all = list(prob.items)

    # ④ 专属归属：帧级变换通道字段从结构层挪给 ④（消息更有指向性）
    def _is_frame_channel(path, _msg):
        leaf = path.rsplit(".", 1)[-1].split("[")[0]
        return leaf in TRANSFORM_CHANNELS and ".frames[" in path

    # 逐序列分派 ①-⑥（结构层问题按 path 前缀以外的部分留给 s0 汇总）
    payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
    sequences = payload.get("sequences") if isinstance(payload.get("sequences"), list) else []

    joint_p, mono_p, pose_p, bone_p, speech_p, cuts_p, cuts_w = [], [], [], [], [], [], []
    speech_notes = []
    for idx, seq in enumerate(sequences):
        if not isinstance(seq, dict):
            continue
        joint_p += check_joint_names(seq, idx, vocab)
        mono_p += check_frame_time(seq, idx, prob)
        pp, _pd, cp, cw = check_pose_frame_max_and_cuts(seq, idx, frame_limit)
        pose_p += pp
        cuts_p += cp
        cuts_w += cw
        # ④：本序列帧级通道字段
        prefix = f"payload.sequences[{idx}]."
        hits = [(p, m) for p, m in problems_all
                if p.startswith(prefix) and _is_frame_channel(p, m)]
        bone_p += check_bone_length(seq, idx, hits)
        ok, sp, sw = check_speech_lip_layer(seq, idx)
        if ok:
            speech_notes += sw
        else:
            speech_p += sp

    # s0 汇总（剔除已归 ④ 的帧级通道字段）
    structural = [(p, m) for p, m in problems_all if not _is_frame_channel(p, m)]

    # ---- s1 params_ref 可解析性（schema 红线①的执行面）----
    ref_problems = []
    gates = ([artifact["gate"]] if isinstance(artifact.get("gate"), dict) else []) + \
            [g for g in artifact.get("aux_gates") or [] if isinstance(g, dict)]
    for g in gates:
        ref = g.get("params_ref")
        if not isinstance(ref, str):
            continue
        if not resolve_params_ref(ref, th):
            ref_problems.append(f"params_ref {ref!r} 解析不到 thresholds.yaml 真实键"
                                f"（cp5.gate.* → checkpoints.cp5.gate.*，其余前缀走文件根；悬空引用拒收）")

    # ---- 汇总 verdict ----
    def mk(cid, title, source_ref, problems, detail, warnings=None):
        return {
            "id": cid, "title": title, "source_ref": source_ref,
            "result": "fail" if problems else "pass",
            "detail": detail,
            "problems": problems, "warnings": warnings or [],
        }

    checks = [
        mk("schema_structure", "s0 CP5 分支契约结构符合性",
           "contracts/v2/checkpoint.schema.json#definitions/cp5_blocking",
           [f"{p}: {m}" for p, m in structural],
           f"逐层 required/additionalProperties/enum/const/pattern/min-max 走查 "
           f"（{len(sequences)} 个序列，{sum(len(s.get('tracks') or []) for s in sequences if isinstance(s, dict))} 条轨道）"),
        mk("joint_names_legal", "① 关节名合法（16 关节穷举）",
           "schema definitions.blocking joint_names 枚举（ToonFlow mannequin，cheap-draft-and-programmatic-tools.md:57-59）",
           joint_p, f"词表={vocab['joint_names_enum']}"),
        mk("frame_time_monotonic", "② 帧时间单调递增",
           "checkpoints.cp5.gate.frame_time_monotonic（布尔强制键）",
           mono_p, "每条轨道 frames[].time 严格递增"),
        mk("pose_frame_max", "③ 每序列帧数 ≤ 上限",
           "checkpoints.cp5.gate.pose_frame_max",
           pose_p, f"上限={frame_limit}（MimicMotion 72 帧 @576×1024；超限分段+known_cuts 见 ⑥）"),
        mk("bone_length_constant", "④ rotation-only 骨长恒定",
           "schema definitions.blocking bone_length_constant const:true + 帧级 additionalProperties:false",
           bone_p, "帧只许 {time, rotation}；禁 scale/translation/position/location"),
        mk("speech_fullbody_lip_layer", "⑤ full-body 对白镜必须有独立口型层路径",
           "checkpoints.cp5.gate.speech_fullbody_lip_layer（布尔强制键）",
           speech_p, "none→pass；independent_lip_layer→pass；requires_split_shot→fail+提示拆镜",
           speech_notes),
        mk("known_cuts_registered", "⑥ 超上限分段切点必须登记",
           "checkpoints.cp5.gate.pose_frame_max（切点数必要条件 ceil(F/L)-1 同源推导，不立第二数值）",
           cuts_p, "切点 ≥0、严格递增；F>L 时须登记充分；下游 CP11 汇入 known_cuts 白名单",
           cuts_w),
        mk("params_ref_resolvable", "s1 gate/aux_gates params_ref 解析到 thresholds 真实键",
           "checkpoint.schema.json 红线①（params_ref 必须可解析）",
           ref_problems, "解析口径：cp5.gate.* → checkpoints.cp5.gate.*；其余前缀走文件根"),
    ]

    all_problems = [p for c in checks for p in c["problems"]]
    all_warnings = [w for c in checks for w in c["warnings"]]
    verdict = "fail" if all_problems else "pass"
    out = {
        "validator": "validate_cp5",
        "contract": "vpipe/contracts/v2/checkpoint.schema.json#cp5_blocking",
        "thresholds": str(thresholds_path),
        "schema": str(schema_path),
        "thresholds_ref_scope": "checkpoints.cp5.gate.*（eval/thresholds.yaml v4）",
        "artifact": str(artifact_path),
        "cp_id": "cp5",
        "work_id": payload.get("work_id"),
        "gate_input": {
            "pose_frame_max": frame_limit,
            "pose_frame_max_ref": "checkpoints.cp5.gate.pose_frame_max",
            "frame_time_monotonic": True,
            "speech_fullbody_lip_layer": True,
        },
        "verdict": verdict,
        "exit_code": EXIT_PASS if verdict == "pass" else EXIT_FAIL,
        "checks": checks,
        "problems": all_problems,
        "warnings": all_warnings,
    }
    return out["exit_code"], out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_cp5.py",
        description="CP5 动作脚本（Blocking）门禁校验器：exit 0=pass / 1=fail / 2=error；"
                    "verdict JSON 恒走 stdout")
    parser.add_argument("artifact", help="CP5 工件 JSON 路径")
    parser.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS),
                        help=f"thresholds.yaml 路径（默认 {DEFAULT_THRESHOLDS}）")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA),
                        help=f"checkpoint.schema.json 路径（默认 {DEFAULT_SCHEMA}）")
    args = parser.parse_args(argv)

    code, out = validate(Path(args.artifact), Path(args.thresholds), Path(args.schema))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if code == EXIT_FAIL:
        print(f"[validate_cp5] FAIL：{len(out['problems'])} 条问题（详见 stdout verdict JSON）",
              file=sys.stderr)
    elif code == EXIT_ERROR:
        print(f"[validate_cp5] ERROR：{out.get('error', '?')}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
