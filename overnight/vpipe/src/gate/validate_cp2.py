#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_cp2.py — CP2（剧本与台词本）rule 门禁校验器（vpipe v4，M1）。

规范出处：
- SPEC_v2.md §1 CP2 行：工件=script，门禁类型=rule；一切判定数值经 gate.params_ref
  引用 eval/thresholds.yaml 的 checkpoints.cp2.gate.*（纪律 3：判定数值单点）。
- 白皮书 §3 CP2「客观验收门禁」：Σ estimated_duration 与目标集时长偏差 ≤阈；
  台词条数/预计镜头数比值在区间（台词过少或过碎都拒）；每条台词不含无法 TTS 的
  字符集；人名/道具名全部在 cast/props 表中已定义（悬空引用拒绝）。
- contracts/v2/checkpoint.schema.json definitions.cp2_script / definitions.script。

用法（仓根或 overnight/vpipe/ 下均可，--thresholds 缺省自动定位）：
    python3 src/gate/validate_cp2.py <artifact.json> [--thresholds eval/thresholds.yaml]

退出码：0=pass；1=fail（stdout JSON 的 checks 逐项列因）；2=用法或读取错误
（stderr 说明；argparse 用法错误本身即 exit 2）。

判定数值零硬编码：duration_dev_max 与 line_shot_ratio 区间只从
checkpoints.cp2.gate.* 读；阈值键缺失/类型不对 → exit 2（读取错误，不放行）。
依赖：标准库 + PyYAML（红线上限，本文件未用 jsonschema）。

「预计镜头数」口径：CP2 契约 payload 无镜头数字段（additionalProperties=false），
白皮书 §3 CP2 注明采用 DramaClaw「逐行一拍一镜」节拍结构，故缺省取
预计镜头数 = 台词条数（比值恒 1.0，是否在区间内仍由 thresholds 裁决）；
若 payload 显式携带 expected_shot_count（≥1 整数）则优先采用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import unicodedata
from pathlib import Path

import yaml

CP_ID = "cp2"
SCHEMA_VERSION = "2.0"
ARTIFACT_TYPE = "script"
GATE_TYPE = "rule"
DEFAULT_THRESHOLDS = "eval/thresholds.yaml"
THR_KEYROOT = f"checkpoints.{CP_ID}.gate"

# narration_text 中视为 TTS 无害的空白类控制符（等同空格）；其余 Cc/Cf 类
# 控制符/不可见符一律计为「无法 TTS 的字符集」（schema script.tts_safe：
# 「声明 + 校验器复核」）。这是字符类目判定，不含任何数值阈。
TTS_BENIGN_CONTROLS = "\t\n\r\f\v"

PAYLOAD_REQUIRED = (
    "work_id",
    "target_duration_s",
    "estimated_total_duration_s",
    "narration_segments",
    "cast",
    "props",
)

# 浮点比较容差：只用于「实测恰落在阈上」时的等值判定，不放宽任何阈本身。
EPS_R = 1e-9
EPS_A = 1e-12


class ReadError(Exception):
    """用法/读取类错误 → exit 2。"""


# ---------------------------------------------------------------- 基础工具

def _num(x) -> bool:
    """数字（排除 bool——bool 是 int 子类，不能当数值阈/时长用）。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt(x) -> str:
    return f"{float(x):g}"


def _seg_id(seg, i: int) -> str:
    if isinstance(seg, dict):
        sid = seg.get("segment_id")
        if isinstance(sid, str) and sid:
            return sid
    return f"segment[{i}]"


def _le_tol(a: float, b: float) -> bool:
    return a <= b or math.isclose(a, b, rel_tol=EPS_R, abs_tol=EPS_A)


# ---------------------------------------------------------------- 读取

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
    """读 checkpoints.cp2.gate.*。返回 ({duration_dev_max, ratio_min, ratio_max, ratio_exact}, sha256)。
    键缺失/类型不对 → ReadError（宁可 exit 2 不放行：判不了就不是门禁）。"""
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
    if not isinstance(cps, dict):
        raise ReadError(f"thresholds 缺 {THR_KEYROOT} 段（checkpoints 非映射）")
    cp2 = cps.get(CP_ID)
    if not isinstance(cp2, dict) or not isinstance(cp2.get("gate"), dict):
        raise ReadError(f"thresholds 缺 {THR_KEYROOT} 段")
    gate = cp2["gate"]

    ddm = gate.get("duration_dev_max")
    if not _num(ddm) or ddm <= 0:
        raise ReadError(
            f"{THR_KEYROOT}.duration_dev_max 缺失或非正数（实得 {ddm!r}）")

    lsr = gate.get("line_shot_ratio")
    ratio_min = ratio_max = ratio_exact = None
    if isinstance(lsr, dict):
        lo, hi = lsr.get("min"), lsr.get("max")
        if lo is None and hi is None:
            raise ReadError(
                f"{THR_KEYROOT}.line_shot_ratio 缺 min/max 上下界")
        for k, v in (("min", lo), ("max", hi)):
            if v is not None and (not _num(v) or v < 0):
                raise ReadError(
                    f"{THR_KEYROOT}.line_shot_ratio.{k} 非法（实得 {v!r}）")
        if lo is not None and hi is not None and lo > hi:
            raise ReadError(
                f"{THR_KEYROOT}.line_shot_ratio 区间反了: min={lo} > max={hi}")
        ratio_min = None if lo is None else float(lo)
        ratio_max = None if hi is None else float(hi)
    elif _num(lsr) and lsr > 0:
        ratio_exact = float(lsr)  # 标量=精确比值口径
    else:
        raise ReadError(
            f"{THR_KEYROOT}.line_shot_ratio 缺失或非法（需 min/max 映射或正标量，"
            f"实得 {lsr!r}）")

    thr = {
        "duration_dev_max": float(ddm),
        "ratio_min": ratio_min,
        "ratio_max": ratio_max,
        "ratio_exact": ratio_exact,
    }
    return thr, hashlib.sha256(raw).hexdigest()


def load_artifact(path: Path):
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ReadError(f"无法读取工件文件 {path}: {e}")
    try:
        art = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ReadError(f"工件不是合法 JSON {path}: {e}")
    if not isinstance(art, dict):
        raise ReadError(f"工件顶层不是 JSON 对象 {path}")
    return art


# ---------------------------------------------------------------- 检查项
# 每项返回 {"name", "ok", "detail"}；fail 时 detail 逐条列因。

def check_shape(art: dict) -> dict:
    """CP2 工件形状门（checkpoint.schema cp2_script 分支的最小机读复核）。"""
    name = "artifact_shape"
    problems = []
    if art.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version 需 {SCHEMA_VERSION!r}（实得 {art.get('schema_version')!r}）")
    if art.get("cp_id") != CP_ID:
        problems.append(f"cp_id 需 {CP_ID!r}（实得 {art.get('cp_id')!r}）——本门只判 CP2 工件")
    if art.get("artifact_type") != ARTIFACT_TYPE:
        problems.append(f"artifact_type 需 {ARTIFACT_TYPE!r}（实得 {art.get('artifact_type')!r}）")
    payload = art.get("payload")
    if not isinstance(payload, dict):
        problems.append(f"payload 缺失或非对象（实得 {type(payload).__name__}）")
    else:
        for k in PAYLOAD_REQUIRED:
            if k not in payload:
                problems.append(f"payload 缺必填键 {k}")
        segs = payload.get("narration_segments")
        if "narration_segments" in payload and not isinstance(segs, list):
            problems.append("payload.narration_segments 非数组")
        elif isinstance(segs, list) and not segs:
            problems.append("payload.narration_segments 为空（契约 minItems=1）")
    ok = not problems
    detail = (
        "schema_version=2.0 / cp_id=cp2 / artifact_type=script / payload 六必填键齐、"
        "narration_segments 非空数组"
        if ok else "；".join(problems)
    )
    return {"name": name, "ok": ok, "detail": detail}


def check_duration_dev(payload: dict, thr: dict) -> dict:
    """① Σ estimated_duration_s 与目标集时长偏差 ≤ duration_dev_max。"""
    name = "duration_dev_max"
    target = payload.get("target_duration_s")
    if not _num(target) or target <= 0:
        return {"name": name, "ok": False,
                "detail": f"target_duration_s 缺失/非正数（实得 {target!r}），无法计算偏差"}
    segs = payload.get("narration_segments")
    if not isinstance(segs, list):
        return {"name": name, "ok": False,
                "detail": "narration_segments 非数组（见 artifact_shape），无法计算 Σ"}
    total, bad = 0.0, []
    for i, seg in enumerate(segs):
        est = seg.get("estimated_duration_s") if isinstance(seg, dict) else None
        if not _num(est) or est <= 0:
            bad.append(f"{_seg_id(seg, i)}: estimated_duration_s 非正数，Σ 不可信")
        else:
            total += float(est)
    if bad:
        return {"name": name, "ok": False, "detail": "；".join(bad)}
    dev = abs(total - float(target)) / float(target)
    lim = thr["duration_dev_max"]
    ok = _le_tol(dev, lim)
    detail = (f"Σ estimated_duration_s={_fmt(total)}s vs 目标 {target!r}s，"
              f"偏差 {dev:.4%}，阈 {lim:.2%}（{THR_KEYROOT}.duration_dev_max）")
    declared = payload.get("estimated_total_duration_s")
    if _num(declared) and not math.isclose(float(declared), total,
                                           rel_tol=EPS_R, abs_tol=EPS_A):
        ok = False
        detail += (f"；声明 estimated_total_duration_s={_fmt(declared)}s "
                   f"与逐条 Σ={_fmt(total)}s 不一致")
    return {"name": name, "ok": ok, "detail": detail}


def check_line_shot_ratio(payload: dict, thr: dict) -> dict:
    """② 台词条数/预计镜头数 比值在 thresholds 区间（或标量精确值）内。"""
    name = "line_shot_ratio"
    segs = payload.get("narration_segments")
    if not isinstance(segs, list) or not segs:
        return {"name": name, "ok": False,
                "detail": "narration_segments 缺失/空（见 artifact_shape），无台词条数可算"}
    lines = len(segs)
    declared = payload.get("expected_shot_count")
    if declared is None:
        # 契约 payload 无镜头数字段：按白皮书 §3 CP2 注「逐行一拍一镜」节拍取台词条数
        shots, src = lines, "未声明 expected_shot_count，按逐行一拍一镜取=台词条数"
    elif _num(declared) and float(declared).is_integer() and declared >= 1:
        shots, src = int(declared), "取自 payload.expected_shot_count"
    else:
        return {"name": name, "ok": False,
                "detail": f"payload.expected_shot_count 非法（需 ≥1 整数，实得 {declared!r}）"}
    ratio = lines / shots
    lo, hi, exact = thr["ratio_min"], thr["ratio_max"], thr["ratio_exact"]
    if exact is not None:
        ok = math.isclose(ratio, exact, rel_tol=EPS_R, abs_tol=EPS_A)
        req = f"== {exact:g}"
    else:
        ok = True
        req_parts = []
        if lo is not None:
            req_parts.append(f">={lo:g}")
            ok = ok and _le_tol(lo, ratio)
        if hi is not None:
            req_parts.append(f"<={hi:g}")
            ok = ok and _le_tol(ratio, hi)
        req = " 且 ".join(req_parts)
    detail = (f"台词条数 {lines} / 预计镜头数 {shots} = {ratio:g}（{src}），"
              f"要求 {req}（{THR_KEYROOT}.line_shot_ratio）")
    return {"name": name, "ok": ok, "detail": detail}


def check_tts_safe(payload: dict) -> dict:
    """③ TTS 字符集安全：tts_safe=false 的 segment 拒；缺失/非布尔声明拒；
    并按 schema「校验器复核」复核 narration_text 无控制/不可见字符（Cc/Cf，
    空白类除外）。本项无数值阈。"""
    name = "tts_charset_safe"
    segs = payload.get("narration_segments")
    if not isinstance(segs, list):
        return {"name": name, "ok": False,
                "detail": "narration_segments 非数组（见 artifact_shape），无法逐段复核"}
    bad = []
    for i, seg in enumerate(segs):
        sid = _seg_id(seg, i)
        if not isinstance(seg, dict):
            bad.append(f"{sid}: 段非对象，无法复核")
            continue
        reasons = []
        flag = seg.get("tts_safe")
        if flag is not True:
            reasons.append(f"tts_safe 声明不为 true（实得 {flag!r}）"
                           + ("——tts_safe=false 的 segment 拒" if flag is False else ""))
        text = seg.get("narration_text")
        if isinstance(text, str):
            unsafe = [ch for ch in text
                      if unicodedata.category(ch) in ("Cc", "Cf")
                      and ch not in TTS_BENIGN_CONTROLS]
            if unsafe:
                shown = " ".join(f"U+{ord(c):04X}({unicodedata.category(c)})"
                                 for c in unsafe[:8])
                reasons.append(f"含无法 TTS 的控制/不可见字符 ×{len(unsafe)}: {shown}")
        else:
            reasons.append("narration_text 非字符串，字符集无法复核")
        if reasons:
            bad.append(f"{sid}: " + "；".join(r for r in reasons if r))
    ok = not bad
    detail = ("全部台词段 tts_safe=true 且 narration_text 无控制/不可见字符"
              if ok else "；".join(bad))
    return {"name": name, "ok": ok, "detail": detail}


def _registry(entries, id_key: str, table: str, problems: list) -> set:
    ids = set()
    if not isinstance(entries, list):
        problems.append(f"{table} 非数组，登记表不可用")
        return ids
    for i, e in enumerate(entries):
        if isinstance(e, dict) and isinstance(e.get(id_key), str) and e[id_key]:
            ids.add(e[id_key])
        else:
            problems.append(f"{table}[{i}] 缺合法 {id_key}，无法登记")
    return ids


def check_refs(payload: dict) -> dict:
    """④ cast/props 悬空引用：每段 cast_refs/props_refs 必须在本工件
    cast[]/props[] 已定义（白皮书 CP2：禁止下游「临时编一个」）。"""
    name = "refs_resolved"
    segs = payload.get("narration_segments")
    if not isinstance(segs, list):
        return {"name": name, "ok": False,
                "detail": "narration_segments 非数组（见 artifact_shape），无法核对引用"}
    problems: list = []
    cast_ids = _registry(payload.get("cast"), "char_id", "cast", problems)
    prop_ids = _registry(payload.get("props"), "prop_id", "props", problems)
    for i, seg in enumerate(segs):
        sid = _seg_id(seg, i)
        if not isinstance(seg, dict):
            continue
        for key, ids, table in (("cast_refs", cast_ids, "cast"),
                                ("props_refs", prop_ids, "props")):
            refs = seg.get(key)
            if refs is None:
                continue  # 缺键是 schema 必填门职责，此处不重复计
            if not isinstance(refs, list):
                problems.append(f"{sid}: {key} 非数组")
                continue
            for r in refs:
                if not isinstance(r, str):
                    problems.append(f"{sid}: {key} 含非字符串项 {r!r}")
                elif r not in ids:
                    problems.append(
                        f"{sid}: {key}[{r}] 悬空——未在本工件 {table}[] 中定义")
    ok = not problems
    detail = (f"cast_refs/props_refs 全部可解析（cast 登记 {len(cast_ids)} 项、"
              f"props 登记 {len(prop_ids)} 项）"
              if ok else "；".join(problems))
    return {"name": name, "ok": ok, "detail": detail}


def check_segments(payload: dict) -> dict:
    """⑤ 每段 estimated_duration_s >0，且 narration/visual 一对一绑定存在
    （两字段齐、非空；契约 minItems=1）。"""
    name = "segment_basics"
    segs = payload.get("narration_segments")
    if not isinstance(segs, list) or not segs:
        return {"name": name, "ok": False,
                "detail": "narration_segments 缺失或为空（契约 minItems=1），"
                          "narration/visual 一对一绑定不成立"}
    problems = []
    for i, seg in enumerate(segs):
        sid = _seg_id(seg, i)
        if not isinstance(seg, dict):
            problems.append(f"{sid}: 段非对象")
            continue
        for f in ("narration_text", "visual_description"):
            v = seg.get(f)
            if not isinstance(v, str) or len(v) == 0:
                problems.append(
                    f"{sid}: {f} 缺失或为空——narration/visual 一对一绑定不成立")
        est = seg.get("estimated_duration_s")
        if not _num(est) or est <= 0:
            problems.append(f"{sid}: estimated_duration_s 需 >0 的数（实得 {est!r}）")
    ok = not problems
    detail = (f"{len(segs)} 条台词段全部 estimated_duration_s>0 且 "
              f"narration_text/visual_description 一对一绑定成立"
              if ok else "；".join(problems))
    return {"name": name, "ok": ok, "detail": detail}


# ---------------------------------------------------------------- 主流程

def validate_artifact(art: dict, thr: dict) -> dict:
    """判定核心（可导入复用）。返回 verdict dict；exit 码由调用方按 verdict 定。"""
    checks = [
        check_shape(art),
        check_duration_dev(art.get("payload") or {}, thr),
        check_line_shot_ratio(art.get("payload") or {}, thr),
        check_tts_safe(art.get("payload") or {}),
        check_refs(art.get("payload") or {}),
        check_segments(art.get("payload") or {}),
    ]
    verdict = "pass" if all(c["ok"] for c in checks) else "fail"
    return {
        "cp_id": CP_ID,
        "gate": GATE_TYPE,
        "verdict": verdict,
        "checks": checks,
        "thresholds_sha256": thr.get("_sha256", ""),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="validate_cp2.py",
        description="CP2（剧本）rule 门禁校验器：数值全读 thresholds.yaml "
                    f"{THR_KEYROOT}.*，exit 0=pass / 1=fail / 2=用法或读取错误")
    ap.add_argument("artifact", help="CP2 剧本工件 JSON 路径")
    ap.add_argument("--thresholds", default=DEFAULT_THRESHOLDS,
                    help=f"阈值表路径（缺省 {DEFAULT_THRESHOLDS}，"
                         "仓根/vpipe 两种 CWD 均可）")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        thr_path = _resolve_thresholds_path(args.thresholds)
        thr, sha = load_thresholds(thr_path)
        art = load_artifact(Path(args.artifact))
    except ReadError as e:
        print(f"validate_cp2: {e}", file=sys.stderr)
        return 2

    thr["_sha256"] = sha
    verdict = validate_artifact(art, thr)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
