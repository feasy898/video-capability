#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_cp6.py — CP6 时间线与节奏轨 门禁校验器（gate 包，TASK_v4 §3.1「五段流水线判定器」）

对 contracts/v2/checkpoint.schema.json #/definitions/cp6_timeline 分支的工件做 rule 门判定。
一切判定数值从 eval/thresholds.yaml checkpoints.cp6.gate.* 读取——本文件不出现第二套判定数值
（schema 红线①「一切判定数值不进契约，一律经 gate.params_ref 引用」；SPEC.md 铁律同源）。

六项校验（括号内为阈值键，全在 checkpoints.cp6.gate 段，thresholds.yaml v4）:
  ① duration_conservation : Σ shots.duration_frames vs total_frames（±容差帧，
       cp6.gate.duration_conservation_frames=1）；并核对工件登记值
       duration_conservation_dev_frames 与实算一致（schema：该字段「只登记实测值」）。
  ② subtitle_align_ms_max : 字幕段与音轨词级时间偏差 ≤ 阈（cp6.gate.subtitle_align_ms_max，
       whisperx SemanticTake 口径）。工件有 subtitle_align_max_dev_ms 登记值才比对；
       无登记（或无字幕段）→ skipped，不判 fail（按任务口径「有登记值就比对」）。
  ③ timeline_cycle_check  : shots 间 during/引用成环拒（白皮书 §3 CP6「无时间轴循环引用」）。
       during 为字符串或字符串列表；悬空引用同样拒（沿 v2 契约 R1 悬空引用拒绝纪律）。
       工件无任何 during 引用 → pass（线性帧域排布本就无环）。
  ④ rhythm_segment_s      : 节奏段 <warn_min 或 >warn_max 登记 warn（cp6.gate.rhythm_segment_s
       .warn_min/.warn_max）。warn-only 语义：计入 checks 但不判 fail，verdict 保持 pass、
       details 标注 warn——超限上升人类一次带三个候选方案，不自动改（白皮书 CP6 失败回退行）。
  ⑤ sound_lead_in_frames  : 音频先入引导帧数已声明且 ≥0（schema timeline 声明字段，
       符合性判定，无独立数值阈）。
  ⑥ shot_layout           : fps/total_frames 帧域排布一致性——total_frames == Σ(start_frame+
       duration_frames) 无重叠无缝隙：首镜 start_frame==0、逐镜首尾衔接、末镜 end==total_frames、
       episode_duration_s == total_frames/fps（容差 1/fps：由工件自身 fps 派生的一帧浮点余量，
       非第二套判定数值）。

另含 gate_params_ref_resolves：工件 gate/aux_gates 的 params_ref 必须能解析到 thresholds.yaml
真实存在的键（schema gate.params_ref 行原文「必须解析到 eval/thresholds.yaml 中真实存在的键」）。

CLI:
  python3 src/gate/validate_cp6.py <artifact.json> [--thresholds eval/thresholds.yaml]

exit: 0=pass（含 warn-only）｜1=fail（任一硬门不过）｜2=error（工件不可解析/非 cp6 工件/
      thresholds 文件缺失或缺 checkpoints.cp6.gate.* 键）
输出: JSON verdict 到 stdout（checks 逐项 + thresholds_applied 含 sha256 留痕，沿 qc_orch 口径）。

依据: research/2026-10-08/工业化视频流水线-白皮书.md §3 CP6（唯一收敛口：语义锚点只投影一次
      为帧域）；contracts/v2/checkpoint.schema.json cp6_timeline 分支；eval/thresholds.yaml
      checkpoints.cp6.gate 段；evidence/thresholds/v3-to-v4-migration.md §CP6。
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

VALIDATOR = "validate_cp6"
CONTRACT = "contracts/v2/checkpoint.schema.json#/definitions/cp6_timeline"
_GATE_SECTION = ("checkpoints", "cp6", "gate")

_MISSING = object()


# --------------------------------------------------------------------------- utils
def _is_int(v):
    """严格整数（排除 bool——Python 中 bool 是 int 子类）。"""
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _dig(obj, dotted):
    """按 'a.b.c' 点路径下钻字典；任一层缺失返回 _MISSING。"""
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _emit(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_error(reasons, artifact=None, thresholds=None):
    _emit({
        "validator": VALIDATOR,
        "contract": CONTRACT,
        "artifact": str(artifact) if artifact else None,
        "thresholds": str(thresholds) if thresholds else None,
        "verdict": "error",
        "exit_code": 2,
        "reasons": reasons,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return 2


# --------------------------------------------------------------------------- thresholds
def load_thresholds(path: Path):
    """读 thresholds.yaml，返回 (yaml根对象, sha256)。文件/段落缺失由调用方判错。"""
    raw = path.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8"))
    return data, hashlib.sha256(raw).hexdigest()


def require_gate_keys(thr_root):
    """取 checkpoints.cp6.gate.* 判定数值；缺任一键 → None（调用方 exit 2）。

    本模块不出现第二套数值：六项校验的阈全部来自这里。
    """
    vals = {
        "duration_conservation_frames": _dig(thr_root, "checkpoints.cp6.gate.duration_conservation_frames"),
        "subtitle_align_ms_max": _dig(thr_root, "checkpoints.cp6.gate.subtitle_align_ms_max"),
        "rhythm_warn_min": _dig(thr_root, "checkpoints.cp6.gate.rhythm_segment_s.warn_min"),
        "rhythm_warn_max": _dig(thr_root, "checkpoints.cp6.gate.rhythm_segment_s.warn_max"),
    }
    missing = [k for k, v in vals.items() if v is _MISSING or v is None]
    if missing:
        return None, missing
    if not _is_num(vals["duration_conservation_frames"]) or not _is_num(vals["subtitle_align_ms_max"]):
        return None, ["duration_conservation_frames / subtitle_align_ms_max 须为数值"]
    for k in ("rhythm_warn_min", "rhythm_warn_max"):
        if not _is_num(vals[k]):
            return None, ["rhythm_segment_s.%s 须为数值" % ("warn_min" if k.endswith("min") else "warn_max")]
    return vals, None


# --------------------------------------------------------------------------- checks
def check_duration_conservation(payload, tol_frames):
    """① Σ shots.duration_frames == total_frames（±tol 帧）+ 登记值一致性。"""
    r = {
        "check": "duration_conservation",
        "params_ref": "cp6.gate.duration_conservation_frames",
        "threshold_frames": tol_frames,
        "status": "pass",
        "computed": None,
        "reasons": [],
    }
    total = payload.get("total_frames")
    shots = payload.get("shots")
    if not _is_int(total) or total < 0:
        r["status"] = "fail"
        r["reasons"].append("total_frames 缺失或非法（须 ≥0 整数），守恒无从判定")
        return r
    if not isinstance(shots, list) or not shots:
        r["status"] = "fail"
        r["reasons"].append("shots 缺失或为空（schema minItems 1），Σ duration_frames 无从判定")
        return r
    if not all(isinstance(s, dict) and _is_int(s.get("duration_frames")) and s["duration_frames"] >= 1
               for s in shots):
        r["status"] = "fail"
        r["reasons"].append("存在缺 duration_frames 或非 ≥1 整数的镜头，Σ duration_frames 无从判定")
        return r

    total_dur = sum(s["duration_frames"] for s in shots)
    dev = total_dur - total
    r["computed"] = {"sum_duration_frames": total_dur, "total_frames": total, "dev_frames": dev}
    if abs(dev) > float(tol_frames):
        r["status"] = "fail"
        r["reasons"].append(
            "Σ duration_frames=%d vs total_frames=%d，守恒偏差 %+d 帧超出 ±%s 帧"
            % (total_dur, total, dev, tol_frames))
    reg = payload.get("duration_conservation_dev_frames")
    if not _is_int(reg):
        r["status"] = "fail"
        r["reasons"].append("缺 duration_conservation_dev_frames 登记（schema required 字段），无法核对登记与实算一致")
    elif reg != dev:
        r["status"] = "fail"
        r["reasons"].append(
            "登记 duration_conservation_dev_frames=%s 与实算 %+d 不符（该字段只许登记实测值，不许谎报）" % (reg, dev))
    return r


def check_subtitle_align(payload, max_dev_ms):
    """② 字幕段与音轨词级时间偏差 ≤ 阈；工件有登记值才比对，无登记 → skipped。"""
    r = {
        "check": "subtitle_align_ms_max",
        "params_ref": "cp6.gate.subtitle_align_ms_max",
        "threshold_ms": max_dev_ms,
        "status": "pass",
        "registered_dev_ms": None,
        "reasons": [],
    }
    subs = payload.get("subtitle_segments")
    dev = payload.get("subtitle_align_max_dev_ms")
    if not isinstance(subs, list) or not subs:
        if dev is None:
            r["status"] = "skipped"
            r["reasons"].append("工件无字幕段且无偏差登记值，本项不适用")
            return r
    if dev is None:
        r["status"] = "skipped"
        r["reasons"].append("有字幕段但未登记 subtitle_align_max_dev_ms，按口径「有登记值才比对」本项跳过")
        return r
    if not _is_num(dev) or dev < 0:
        r["status"] = "fail"
        r["reasons"].append("subtitle_align_max_dev_ms 登记值非法（须 ≥0 数值）")
        return r
    r["registered_dev_ms"] = dev
    if float(dev) > float(max_dev_ms):
        r["status"] = "fail"
        r["reasons"].append(
            "字幕段与音轨词级时间最大偏差 %sms 超阈 %sms（whisperx SemanticTake 口径）" % (dev, max_dev_ms))
    if isinstance(subs, list):
        for seg in subs:
            if not isinstance(seg, dict):
                r["status"] = "fail"
                r["reasons"].append("subtitle_segments 存在非对象元素")
                continue
            s0, s1 = seg.get("start_s"), seg.get("end_s")
            if _is_num(s0) and _is_num(s1) and s1 < s0:
                r["status"] = "fail"
                r["reasons"].append(
                    "字幕段 %s 区间倒挂（start_s=%s > end_s=%s）" % (seg.get("segment_id", "?"), s0, s1))
    return r


def _shot_graph(shots):
    """从 shots 提取 during 引用边。返回 (edges{shot_id: set}, dangling[(id, target)], malformed)。"""
    edges, dangling, malformed = {}, [], []
    ids = set()
    for s in shots:
        if isinstance(s, dict) and isinstance(s.get("shot_id"), str):
            ids.add(s["shot_id"])
    for s in shots:
        if not isinstance(s, dict):
            malformed.append(s if not isinstance(s, dict) else s.get("shot_id"))
            continue
        sid = s.get("shot_id")
        during = s.get("during")
        if during is None:
            continue
        targets = [during] if isinstance(during, str) else during
        if not isinstance(targets, list) or any(not isinstance(t, str) for t in targets):
            malformed.append(sid)
            continue
        edges[sid] = set()
        for t in targets:
            if t not in ids:
                dangling.append((sid, t))
            else:
                edges[sid].add(t)
    return edges, dangling, malformed


def _find_cycle(edges):
    """DFS 找环，返回环节点链（如 [a, b, a]）或 None。"""
    color = {n: 0 for n in edges}

    def dfs(n, path):
        color[n] = 1
        path.append(n)
        for m in sorted(edges.get(n, ())):
            if m not in color:
                continue
            if color[m] == 1:
                return path[path.index(m):] + [m]
            if color[m] == 0:
                found = dfs(m, path)
                if found:
                    return found
        path.pop()
        color[n] = 2
        return None

    for n in sorted(edges):
        if color[n] == 0:
            found = dfs(n, [])
            if found:
                return found
    return None


def check_timeline_cycles(payload):
    """③ shots 间 during/引用成环拒；悬空引用同拒；无 during → pass。"""
    r = {
        "check": "timeline_cycle_check",
        "params_ref": None,
        "status": "pass",
        "during_edge_count": 0,
        "reasons": [],
    }
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        r["status"] = "skipped"
        r["reasons"].append("shots 缺失/为空，循环引用无从构建（结构问题由 ①⑥ 报）")
        return r
    edges, dangling, malformed = _shot_graph(shots)
    r["during_edge_count"] = sum(len(v) for v in edges.values())
    if malformed:
        r["status"] = "fail"
        r["reasons"].append("存在非法镜头元素或 during 词形非法（须为字符串或字符串列表）")
    if dangling:
        r["status"] = "fail"
        r["reasons"].extend(
            "镜头 %s during 引用悬空目标 %s（悬空引用拒绝）" % (sid, t) for sid, t in dangling)
    cycle = _find_cycle(edges) if edges else None
    if cycle:
        r["status"] = "fail"
        r["reasons"].append("时间轴循环引用：" + " → ".join(cycle) + "（白皮书 §3 CP6：无时间轴循环引用）")
    if r["status"] == "pass" and r["during_edge_count"] == 0:
        r["reasons"].append("shots 无 during 引用（线性帧域排布，无环可言）")
    elif r["status"] == "pass":
        r["reasons"].append("during 引用 %d 条，无环无悬空" % r["during_edge_count"])
    return r


def check_rhythm_segments(payload, warn_min, warn_max):
    """④ 节奏段长度 warn 带——warn-only：不判 fail，verdict 保持 pass，details 标注 warn。"""
    r = {
        "check": "rhythm_segment_s",
        "params_ref": "cp6.gate.rhythm_segment_s",
        "warn_band": [warn_min, warn_max],
        "warn_only": True,
        "status": "pass",
        "violations": [],
        "reasons": [],
    }
    rs = payload.get("rhythm_segments")
    if not isinstance(rs, list) or not rs:
        r["status"] = "skipped"
        r["reasons"].append("工件未登记节奏段，本项不适用")
        return r
    for seg in rs:
        if not isinstance(seg, dict) or not isinstance(seg.get("segment_id"), str) or not _is_num(seg.get("duration_s")) \
                or seg["duration_s"] <= 0:
            r["status"] = "warn"
            r["violations"].append({"segment_id": seg.get("segment_id") if isinstance(seg, dict) else None,
                                    "duration_s": seg.get("duration_s") if isinstance(seg, dict) else None,
                                    "band": "malformed"})
            r["reasons"].append("节奏段登记非法（须 {segment_id, duration_s>0}）——warn-only，上升人工核对")
            continue
        d = float(seg["duration_s"])
        if d < float(warn_min):
            r["violations"].append({"segment_id": seg["segment_id"], "duration_s": seg["duration_s"],
                                    "band": "below_warn_min"})
            r["reasons"].append(
                "节奏段 %s 时长 %ss < warn_min %ss（warn-only：计入 checks 不判 fail，"
                "上升人类一次带三个候选方案，不自动改）" % (seg["segment_id"], seg["duration_s"], warn_min))
        elif d > float(warn_max):
            r["violations"].append({"segment_id": seg["segment_id"], "duration_s": seg["duration_s"],
                                    "band": "above_warn_max"})
            r["reasons"].append(
                "节奏段 %s 时长 %ss > warn_max %ss（warn-only：计入 checks 不判 fail，"
                "上升人类一次带三个候选方案，不自动改）" % (seg["segment_id"], seg["duration_s"], warn_max))
    if r["violations"]:
        r["status"] = "warn"
    else:
        r["reasons"].append("节奏段 %d 条全部在 warn 带内 [%s, %s]s" % (len(rs), warn_min, warn_max))
    return r


def check_sound_lead_in(payload):
    """⑤ 音频先入引导帧数已声明且 ≥0。"""
    r = {"check": "sound_lead_in_frames", "params_ref": None, "status": "pass", "reasons": []}
    v = payload.get("sound_lead_in_frames")
    if v is None:
        r["status"] = "fail"
        r["reasons"].append("sound_lead_in_frames 未声明（音频先入引导为 CP6 门禁声明项，D3-8 声音先入）")
    elif not _is_int(v):
        r["status"] = "fail"
        r["reasons"].append("sound_lead_in_frames=%r 非整数帧数" % (v,))
    elif v < 0:
        r["status"] = "fail"
        r["reasons"].append("sound_lead_in_frames=%d 为负（先入引导帧数须 ≥0）" % v)
    else:
        r["reasons"].append("已声明 sound_lead_in_frames=%d（≥0）" % v)
    return r


def check_shot_layout(payload):
    """⑥ 帧域排布：无重叠无缝隙、首镜 start=0、末镜 end==total_frames、episode_duration_s==total_frames/fps。"""
    r = {
        "check": "shot_layout",
        "params_ref": None,
        "status": "pass",
        "computed": None,
        "reasons": [],
    }
    total = payload.get("total_frames")
    fps = payload.get("fps")
    ep_s = payload.get("episode_duration_s")
    shots = payload.get("shots")
    ok_struct = True
    if not _is_int(total) or total < 0:
        r["status"] = "fail"; r["reasons"].append("total_frames 缺失或非法"); ok_struct = False
    if not _is_int(fps) or fps < 1:
        r["status"] = "fail"; r["reasons"].append("fps 缺失或非法（须 ≥1 整数）"); ok_struct = False
    if not _is_num(ep_s) or ep_s < 0:
        r["status"] = "fail"; r["reasons"].append("episode_duration_s 缺失或非法"); ok_struct = False
    if not isinstance(shots, list) or not shots:
        r["status"] = "fail"; r["reasons"].append("shots 缺失或为空，帧域排布无从判定"); ok_struct = False
        return r
    if not all(isinstance(s, dict) and isinstance(s.get("shot_id"), str)
               and _is_int(s.get("start_frame")) and s["start_frame"] >= 0
               and _is_int(s.get("duration_frames")) and s["duration_frames"] >= 1 for s in shots):
        r["status"] = "fail"
        r["reasons"].append("存在缺 shot_id/start_frame/duration_frames 或取值非法的镜头")
        return r

    ids = [s["shot_id"] for s in shots]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        r["status"] = "fail"
        r["reasons"].append("shot_id 重复：%s" % ", ".join(dups))

    ordered = sorted(shots, key=lambda s: s["start_frame"])
    if ok_struct and ordered[0]["start_frame"] != 0:
        r["status"] = "fail"
        r["reasons"].append("首镜 %s start_frame=%d ≠ 0（前导缝隙 %d 帧）"
                            % (ordered[0]["shot_id"], ordered[0]["start_frame"], ordered[0]["start_frame"]))
    cursor_end = None
    for s in ordered:
        start, dur = s["start_frame"], s["duration_frames"]
        if cursor_end is not None:
            if start < cursor_end:
                r["status"] = "fail"
                r["reasons"].append("镜头 %s（start=%d）与前一镜末尾（%d）重叠 %d 帧"
                                    % (s["shot_id"], start, cursor_end, cursor_end - start))
            elif start > cursor_end:
                r["status"] = "fail"
                r["reasons"].append("镜头 %s（start=%d）与前一镜末尾（%d）之间存在缝隙 %d 帧"
                                    % (s["shot_id"], start, cursor_end, start - cursor_end))
        cursor_end = start + dur
    if ok_struct and cursor_end is not None and cursor_end != total:
        r["status"] = "fail"
        r["reasons"].append("末镜收尾帧 %d ≠ total_frames %d" % (cursor_end, total))
    if ok_struct:
        expected_s = total / fps
        if abs(float(ep_s) - expected_s) > 1.0 / fps + 1e-9:
            r["status"] = "fail"
            r["reasons"].append("episode_duration_s=%s 与 total_frames/fps=%s 不一致（容差一帧 %ss）"
                                % (ep_s, expected_s, 1.0 / fps))
    r["computed"] = {"shots": len(shots), "span_frames": [ordered[0]["start_frame"], cursor_end]}
    if r["status"] == "pass":
        r["reasons"].append("帧域排布无缝无重叠：0→%d 帧 == total_frames，episode_duration_s 一致" % (cursor_end or 0))
    return r


def _resolve_ref(thr_root, ref):
    """params_ref 解析：先按 yaml 根路径（既有段如 l0_preflight.*、judges.*），再按
    checkpoints.<ref>（thresholds v4 CP 级段命名 cpN.gate.*，schema gate.params_ref 行两式并存）。"""
    if _dig(thr_root, ref) is not _MISSING:
        return True
    return _dig(thr_root, "checkpoints." + ref) is not _MISSING


def check_gate_params_refs(artifact, thr_root):
    """附加：gate/aux_gates 的 params_ref 必须解析到 thresholds.yaml 真实存在的键。"""
    r = {"check": "gate_params_ref_resolves", "params_ref": None, "status": "pass", "reasons": []}
    refs = []
    gate = artifact.get("gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("params_ref"), str):
        r["status"] = "fail"
        r["reasons"].append("缺 gate.params_ref（schema required，门禁声明不可缺）")
    else:
        refs.append(("gate", gate["params_ref"]))
    aux = artifact.get("aux_gates")
    if isinstance(aux, list):
        for i, g in enumerate(aux):
            if isinstance(g, dict):
                if not isinstance(g.get("params_ref"), str):
                    r["status"] = "fail"
                    r["reasons"].append("aux_gates[%d] 缺 params_ref" % i)
                else:
                    refs.append(("aux_gates[%d]" % i, g["params_ref"]))
    for where, ref in refs:
        if not _resolve_ref(thr_root, ref):
            r["status"] = "fail"
            r["reasons"].append("%s params_ref=%s 无法解析到 thresholds.yaml 真实键（第二套数值防线）" % (where, ref))
    if r["status"] == "pass":
        r["reasons"].append("params_ref 全部可解析：" + "; ".join(ref for _, ref in refs))
    return r


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog=VALIDATOR,
        description="CP6 时间线与节奏轨门禁校验器（阈值全部来自 eval/thresholds.yaml checkpoints.cp6.gate.*）")
    ap.add_argument("artifact", help="CP6 工件 JSON（contracts/v2/checkpoint.schema.json cp6_timeline 分支）")
    ap.add_argument("--thresholds", default=None,
                    help="eval/thresholds.yaml（默认 <vpipe 根>/eval/thresholds.yaml）")
    args = ap.parse_args(argv)

    if yaml is None:
        return _emit_error(["PyYAML 不可用，无法读 thresholds.yaml"])
    thr_path = Path(args.thresholds) if args.thresholds else \
        Path(__file__).resolve().parent.parent.parent / "eval" / "thresholds.yaml"
    if not thr_path.is_file():
        return _emit_error(["thresholds 文件不存在：%s" % thr_path], args.artifact, thr_path)

    art_path = Path(args.artifact)
    if not art_path.is_file():
        return _emit_error(["工件文件不存在：%s" % art_path], args.artifact, thr_path)
    try:
        artifact = json.loads(art_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return _emit_error(["工件 JSON 解析失败：%s" % e], args.artifact, thr_path)
    if not isinstance(artifact, dict):
        return _emit_error(["工件顶层须为 JSON 对象"], args.artifact, thr_path)

    if artifact.get("cp_id") != "cp6" or artifact.get("artifact_type") != "timeline":
        return _emit_error(
            ["本校验器只吃 cp6/timeline 工件（收到 cp_id=%r artifact_type=%r），请分派到对应 validate_cpN"
             % (artifact.get("cp_id"), artifact.get("artifact_type"))],
            args.artifact, thr_path)

    try:
        thr_root, thr_sha = load_thresholds(thr_path)
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        return _emit_error(["thresholds.yaml 解析失败：%s" % e], args.artifact, thr_path)
    if not isinstance(thr_root, dict):
        return _emit_error(["thresholds.yaml 顶层须为映射"], args.artifact, thr_path)

    vals, missing = require_gate_keys(thr_root)
    if vals is None:
        return _emit_error(
            ["thresholds.yaml 缺 checkpoints.cp6.gate.* 键：%s（判定数值缺位即拒判，不许代码兜底第二套）"
             % ", ".join(missing)], args.artifact, thr_path)

    payload = artifact.get("payload")
    if not isinstance(payload, dict):
        return _emit_error(["工件缺 payload 对象（cp6_timeline 分支 required）"], args.artifact, thr_path)

    checks = [
        check_duration_conservation(payload, vals["duration_conservation_frames"]),
        check_subtitle_align(payload, vals["subtitle_align_ms_max"]),
        check_timeline_cycles(payload),
        check_rhythm_segments(payload, vals["rhythm_warn_min"], vals["rhythm_warn_max"]),
        check_sound_lead_in(payload),
        check_shot_layout(payload),
        check_gate_params_refs(artifact, thr_root),
    ]

    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    verdict = "fail" if fails else "pass"

    gate = artifact.get("gate") or {}
    out = {
        "validator": VALIDATOR,
        "contract": CONTRACT,
        "artifact": str(art_path),
        "cp_id": artifact.get("cp_id"),
        "work_id": payload.get("work_id"),
        "artifact_gate": {"type": gate.get("type"), "params_ref": gate.get("params_ref"),
                          "declared_result": gate.get("result")},
        "verdict": verdict,
        "exit_code": 1 if fails else 0,
        "fail_count": len(fails),
        "warn_only_count": len(warns),
        "warnings": [reason for c in warns for reason in c["reasons"]],
        "reasons": [reason for c in fails for reason in c["reasons"]] or
                   ["CP6 六项门禁全部通过" + ("（含 %d 项 warn-only 标注）" % len(warns) if warns else "")],
        "thresholds_applied": {
            "path": str(thr_path),
            "sha256": thr_sha,
            "values": {
                "cp6.gate.duration_conservation_frames": vals["duration_conservation_frames"],
                "cp6.gate.subtitle_align_ms_max": vals["subtitle_align_ms_max"],
                "cp6.gate.rhythm_segment_s.warn_min": vals["rhythm_warn_min"],
                "cp6.gate.rhythm_segment_s.warn_max": vals["rhythm_warn_max"],
            },
        },
        "checks": checks,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _emit(out)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
