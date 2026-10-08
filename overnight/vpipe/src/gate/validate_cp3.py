#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_cp3.py — CP3 分镜表（storyboard）门禁校验器：校验器七条。

规范出处（只读引用，本器不复制任何判定数值）：
- overnight/vpipe/SPEC_v2.md §1 CP3 行：gate=rule（五要素齐全 / 单段上限 / 词锚定 /
  循环引用 / 镜头数一致；params_ref 例 cp3.gate.max_shot_duration_s）。
- research/2026-10-08/工业化视频流水线-白皮书.md §3 CP3「客观验收门禁」行：
  五要素齐全、duration_s ≤ 引擎单段上限（H3 实测 4–15s，VDL_v2_草案 R3）、词锚定合法
  （@{} 引用必须存在于本镜台词内）、跨镜 during 同场景且编译序在前、循环引用检测、
  镜头数与 CP2 台词条数一致；任何校验失败退回 CP2/CP3 重生成该镜。
- AI视频生产流水线方案.md §3.2 校验器七条（引用完整 / 词锚定 / 跨镜 during / 循环引用）。
- contracts/v2/checkpoint.schema.json definitions.cp3_storyboard：结构层归 schema
  （本器不做 JSON Schema 复核，那不是 rule 门职责）；gate 描述列出同组七条。
- 判定数值单点：eval/thresholds.yaml checkpoints.cp3.gate.*（SPEC_v2 §0 纪律 3；
  缺键即 exit 2 拒判，绝不内置第二套数值）。

七条校验（名称与 thresholds 键对齐处直接用键名）：
  ① five_elements_complete   每镜 shot_scale/move/duration_s/action/refs 非空
  ② max_shot_duration_s      单镜 duration_s ≤ cp3.gate.max_shot_duration_s
  ③ word_anchor_valid        词锚 @{} 引用存在于本镜台词内（cp3.gate.word_anchor_valid）；
                             「本镜台词」= --script 中 anchor.segment_id 对应 narration_text；
                             无 --script 时：词锚/镜头数/引用三项 fail-closed 拒（主控验收修订 2026-10-08，
                             不冒充通过判定）
  ④ during_reference_valid   跨镜 during="@<shot_id>.line[n]"（或 @<shot_id> 整镜引用）
                             指向的 shot 必须已定义、与本体同场景、编译序在前（数组序更早）；
                             场景约定：shot_id 首个 -/_/. 分隔符前的段（如 s01-03 → s01）
  ⑤ no_circular_reference    shots 间 during 引用图成环即拒（A→B→A）
  ⑥ shot_line_count_match    镜头数 == CP2 台词条数（cp3.gate.shot_line_count_match；需 --script）
  ⑦ reference_integrity      refs 中的角色/道具 ID 必须解析到工件 payload.cast/props 或
                             --script payload.cast/props（悬空拒）；两侧都无注册表时 SKIP 并明示

用法：
  python3 validate_cp3.py <artifact.json> [--script <cp2.json>] [--thresholds eval/thresholds.yaml]

退出码：0 = 判定 pass（SKIP 不算失败，但逐条在 detail/`skipped` 明示）；
        1 = 判定 fail（至少一条校验不过，任何失败退回 CP2/CP3 重生成该镜）；
        2 = 用法 / IO / JSON 解析 / 工件身份（schema_version、cp_id）错误或 thresholds 缺键
            ——未出规则判定，与 fail 严格区分。

红线：单文件；仅标准库 + PyYAML；不 import 任何其他校验器（校验器互不 import）；
      判定数值只读 thresholds.yaml checkpoints.cp3.gate.*。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------- 常量与词形

# 词锚 @{} 形式：anchor 字段允许 "@{词}" 或裸词两种写法（SVML 词锚定词形）。
ANCHOR_BRACE_RE = re.compile(r"^\s*@\{(?P<inner>.+?)\}\s*$", re.S)

# during 引用词形：@<shot_id> 或 @<shot_id>.line[n]（AI视频生产流水线方案.md §3.1/§3.2）。
# 注意：shot_id 词形含 .- _ 时与 ".line[n]" 后缀存在理论歧义，解析按非贪婪收缩到
# ".line[n]" 后缀优先；无后缀则整串视为目标 shot_id。
DURING_RE = re.compile(
    r"^\s*@?(?P<tid>[A-Za-z0-9][A-Za-z0-9_.-]{0,63}?)(?:\.line\[(?P<n>\d+)\])?\s*$"
)

# 场景词形：shot_id 首个分隔符（-/_/.）前的段为场景段（s01-03 → s01；无分隔符自成一段）。
SCENE_SPLIT_RE = re.compile(r"[-_.]")

CHECK_NAMES = [
    "five_elements_complete",   # ①
    "max_shot_duration_s",      # ②
    "word_anchor_valid",        # ③
    "during_reference_valid",   # ④
    "no_circular_reference",    # ⑤
    "shot_line_count_match",    # ⑥
    "reference_integrity",      # ⑦
]

FIVE_ELEMENTS = ("shot_scale", "move", "duration_s", "action", "refs")


# ---------------------------------------------------------------- 基础工具

def sha256_file(p: Path) -> str:
    """与 eval/eval_run.py sha256_file 同口径：文件字节 sha256 十六进制。"""
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def scene_of(shot_id: str) -> str:
    parts = SCENE_SPLIT_RE.split(shot_id, maxsplit=1)
    return parts[0] if parts and parts[0] else shot_id


def anchor_inner(text: str) -> str:
    """词锚文本：剥掉 @{} 外壳（裸词原样返回），供词面存在性比对。"""
    m = ANCHOR_BRACE_RE.match(text or "")
    return (m.group("inner") if m else text or "").strip()


def parse_during(ref):
    """解析 during 引用；不可解析返回 None。返回 (target_id, line_idx|None)。"""
    if not isinstance(ref, str) or not ref.strip():
        return None
    m = DURING_RE.match(ref.strip())
    if not m or not m.group("tid"):
        return None
    idx = int(m.group("n")) if m.group("n") is not None else None
    return m.group("tid"), idx


def _load_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail_error(f"{label} 文件不存在: {path}")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        fail_error(f"{label} 不是合法 JSON: {path} ({e})")


def fail_error(msg: str):
    """exit 2 通道：未出规则判定（用法/IO/解析/身份/缺键）。JSON 到 stdout + 摘要到 stderr。"""
    sys.stdout.write(json.dumps({
        "verdict": "error",
        "exit_code": 2,
        "error": msg,
        "checks": [],
        "thresholds_sha256": None,
    }, ensure_ascii=False) + "\n")
    sys.stderr.write(f"[validate_cp3] ERROR: {msg}\n")
    sys.exit(2)


def default_thresholds_path() -> Path:
    # 优先仓内定位：<vpipe>/eval/thresholds.yaml（本文件在 <vpipe>/src/gate/ 下）；
    # 否则回退 CWD 相对 eval/thresholds.yaml（CLI 文档口径）。
    beside_repo = Path(__file__).resolve().parents[2] / "eval" / "thresholds.yaml"
    if beside_repo.exists():
        return beside_repo
    return Path("eval") / "thresholds.yaml"


def load_cp3_gate(thr_path: Path) -> dict:
    """读 checkpoints.cp3.gate 段；三个判定键缺任一即 exit 2（判定数值单点，不内置默认）。"""
    data = _load_json(thr_path, "thresholds") if thr_path.suffix == ".json" else None
    if data is None:
        try:
            data = yaml.safe_load(thr_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            fail_error(f"thresholds 文件不存在: {thr_path}")
        except yaml.YAMLError as e:
            fail_error(f"thresholds 不是合法 YAML: {thr_path} ({e})")
    node = (data or {}).get("checkpoints", {}).get("cp3", {}).get("gate")
    if not isinstance(node, dict):
        fail_error(f"thresholds 缺 checkpoints.cp3.gate 段: {thr_path}")
    for key in ("max_shot_duration_s", "word_anchor_valid", "shot_line_count_match"):
        if key not in node:
            fail_error(f"thresholds 缺键 checkpoints.cp3.gate.{key}: {thr_path}")
    if not isinstance(node["max_shot_duration_s"], (int, float)) or isinstance(node["max_shot_duration_s"], bool):
        fail_error(f"checkpoints.cp3.gate.max_shot_duration_s 非数值: {node['max_shot_duration_s']!r}")
    return node


# ---------------------------------------------------------------- 工件预检（exit 2 层）

def precheck_artifact(art) -> dict:
    """身份与可判结构预检：不是 CP3 2.0 工件或 shots 不可迭代 → exit 2（未出规则判定）。
    逐镜字段级问题不属于此处（那是七条校验与 schema 的职责）。"""
    if not isinstance(art, dict):
        fail_error("artifact 顶层不是 JSON object")
    if art.get("schema_version") != "2.0":
        fail_error(f"schema_version 必须=2.0（v2 校验器拒收 v1/其他版本）: {art.get('schema_version')!r}")
    if art.get("cp_id") != "cp3":
        fail_error(f"cp_id 必须=cp3: {art.get('cp_id')!r}（喂错工件）")
    if art.get("artifact_type") != "storyboard":
        fail_error(f"artifact_type 必须=storyboard: {art.get('artifact_type')!r}")
    payload = art.get("payload")
    if not isinstance(payload, dict):
        fail_error("payload 不是 object（结构层归 schema，本器拒判）")
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        fail_error("payload.shots 非空数组缺失（结构层归 schema，本器拒判）")
    for i, s in enumerate(shots):
        if not isinstance(s, dict):
            fail_error(f"payload.shots[{i}] 不是 object（结构层归 schema，本器拒判）")
    return payload


def precheck_script(script) -> dict:
    """CP2 侧只取判定所需形状；喂错工件（cp_id 非 cp2）→ exit 2。"""
    if not isinstance(script, dict):
        fail_error("script 顶层不是 JSON object")
    if script.get("cp_id") != "cp2" or script.get("artifact_type") != "script":
        fail_error(f"--script 必须是 CP2 剧本工件: cp_id={script.get('cp_id')!r} "
                   f"artifact_type={script.get('artifact_type')!r}")
    payload = script.get("payload")
    if not isinstance(payload, dict):
        fail_error("--script payload 不是 object")
    segs = payload.get("narration_segments")
    if not isinstance(segs, list):
        fail_error("--script payload.narration_segments 不是数组")
    return payload


# ---------------------------------------------------------------- 七条校验

def check_five_elements(shots):
    """① 五要素齐全：shot_scale/move/duration_s/action/refs 非空（白皮书 §3 CP3）。"""
    problems = []
    for i, s in enumerate(shots):
        sid = s.get("shot_id", f"#{i}")
        for key in FIVE_ELEMENTS:
            if key not in s or s[key] is None:
                problems.append(f"{sid} 缺 {key}")
                continue
            v = s[key]
            if key == "duration_s":
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                    problems.append(f"{sid} duration_s 非正数值: {v!r}")
            elif key == "refs":
                if not isinstance(v, list) or len(v) == 0:
                    problems.append(f"{sid} refs 空")
            else:
                if not isinstance(v, str) or not v.strip():
                    problems.append(f"{sid} {key} 空")
    if problems:
        return False, "；".join(problems[:8]) + ("…" if len(problems) > 8 else "")
    return True, f"{len(shots)} 镜五要素齐全（shot_scale/move/duration_s/action/refs 非空）"


def check_max_duration(shots, limit):
    """② 单镜时长 ≤ cp3.gate.max_shot_duration_s（H3 实测 4–15s 口径，白皮书 §3 CP3）。"""
    numeric = [
        (s.get("shot_id", f"#{i}"), s["duration_s"])
        for i, s in enumerate(shots)
        if isinstance(s.get("duration_s"), (int, float)) and not isinstance(s.get("duration_s"), bool)
    ]
    if not numeric:
        return True, "无数值时长可判（①已报类型问题），本条不重复否决"
    worst_id, worst_v = max(numeric, key=lambda t: t[1])
    if worst_v > limit:
        overs = [f"{sid}={v}s" for sid, v in numeric if v > limit]
        return False, (f"单镜时长超引擎单段上限 {limit}s（cp3.gate.max_shot_duration_s）："
                       + "；".join(overs[:8]) + ("…" if len(overs) > 8 else ""))
    return True, f"{len(numeric)} 镜最长 {worst_id}={worst_v}s ≤ {limit}s（cp3.gate.max_shot_duration_s）"


def check_word_anchors(shots, segments, enabled):
    """③ 词锚定合法：@{} 引用存在于本镜台词内（cp3.gate.word_anchor_valid）。
    segments=None 表示未传 --script：只做形式校验并明示词面未验。"""
    if not enabled:
        return True, "SKIP：cp3.gate.word_anchor_valid=false（阈关闭）", True
    if segments is None:
        # fail-closed（主控验收修订 2026-10-08）：CP3 工件按契约不带 cast/props 注册表
        # （storyboard additionalProperties=false），词锚的 segment_id 与词面存在性
        # 只能经 --script 解析。有锚而无源 = 不可判定 = 拒，不提供 SKIP 旁路。
        n_anchors_declared = sum(
            len(s.get("word_anchors") or []) for s in shots if isinstance(s.get("word_anchors"), list)
        )
        if n_anchors_declared > 0:
            return False, (f"工件声明 {n_anchors_declared} 处词锚但未传 --script：词锚存在性"
                           "判定无源（CP3 契约不带注册表），fail-closed 拒——编排器必须透传上游 CP2"), False
        return True, "无词锚声明，无需 --script", False
    if True:
        # 形式校验：锚非空、segment_id 非空；词面存在性由下方 segments 比对。
        problems = []
        n_anchors = 0
        for i, s in enumerate(shots):
            sid = s.get("shot_id", f"#{i}")
            was = s.get("word_anchors", [])
            if not isinstance(was, list):
                problems.append(f"{sid} word_anchors 不是数组")
                continue
            for wa in was:
                n_anchors += 1
                if not isinstance(wa, dict):
                    problems.append(f"{sid} 词锚条目不是 object")
                    continue
                inner = anchor_inner(str(wa.get("anchor", "")))
                seg = wa.get("segment_id")
                if not inner:
                    problems.append(f"{sid} 词锚文本空")
                if not isinstance(seg, str) or not seg.strip():
                    problems.append(f"{sid} 词锚 segment_id 空")
        if problems:
            return False, "；".join(problems[:8]), False
        # 形式校验过 + 有 script：继续走下方词面存在性比对（本函数尾部）

    # 有 --script：segment_id 必须可解析，锚面（剥 @{}）必须是该段 narration_text 子串。
    seg_text = {}
    for seg in segments:
        if isinstance(seg, dict) and isinstance(seg.get("segment_id"), str):
            seg_text[seg["segment_id"]] = seg.get("narration_text", "")
    problems = []
    n_anchors = 0
    for i, s in enumerate(shots):
        sid = s.get("shot_id", f"#{i}")
        was = s.get("word_anchors", [])
        if not isinstance(was, list):
            problems.append(f"{sid} word_anchors 不是数组")
            continue
        for wa in was:
            n_anchors += 1
            if not isinstance(wa, dict):
                problems.append(f"{sid} 词锚条目不是 object")
                continue
            inner = anchor_inner(str(wa.get("anchor", "")))
            seg_id = wa.get("segment_id")
            if not inner:
                problems.append(f"{sid} 词锚文本空")
                continue
            if seg_id not in seg_text:
                problems.append(f"{sid} 词锚 @{inner} 的 segment_id={seg_id!r} 悬空（不在 CP2）")
                continue
            if inner not in str(seg_text[seg_id]):
                problems.append(
                    f"{sid} 词锚 @{inner} 不在本镜台词内（{seg_id}: "
                    f"{str(seg_text[seg_id])[:24]}…）")
    if problems:
        return False, "；".join(problems[:8]) + ("…" if len(problems) > 8 else ""), False
    return True, f"{n_anchors} 处词锚 @{{}} 引用均存在于对应台词段内", False


def check_during(shots):
    """④ 跨镜 during：指向的 shot 必须已定义、同场景、编译序在前。
    返回 (ok, detail, edges)；edges=[(src_idx, dst_idx)] 供 ⑤ 成环检测。"""
    ids = [s.get("shot_id") for s in shots]
    id_to_idx = {}
    dup = sorted({sid for sid in ids if ids.count(sid) > 1 and isinstance(sid, str)})
    for i, sid in enumerate(ids):
        if isinstance(sid, str) and sid not in id_to_idx:
            id_to_idx[sid] = i
    problems = []
    edges = []
    n_refs = 0
    for i, s in enumerate(shots):
        sid = s.get("shot_id", f"#{i}")
        d = s.get("during")
        if d is None:
            continue
        refs = d if isinstance(d, list) else [d]
        for ref in refs:
            n_refs += 1
            parsed = parse_during(ref)
            if parsed is None:
                problems.append(f"{sid} during={ref!r} 不可解析（应为 @<shot_id>[.line[n]]）")
                continue
            tid, _n = parsed
            j = id_to_idx.get(tid)
            if j is None:
                problems.append(f"{sid} during 指向 {tid!r} 未定义")
                continue
            edges.append((i, j))
            if scene_of(str(tid)) != scene_of(str(sid)):
                problems.append(f"{sid}（场景 {scene_of(str(sid))}）during 跨场景引用 {tid}"
                                f"（场景 {scene_of(str(tid))}）")
                continue
            if j >= i:
                problems.append(f"{sid} during 指向 {tid}，编译序不在本镜之前（idx {j} ≥ {i}）")
    if dup:
        problems.append("shot_id 重复，编译序歧义: " + ",".join(dup[:8]))
    if problems:
        return False, "；".join(problems[:8]) + ("…" if len(problems) > 8 else ""), edges
    if n_refs == 0:
        return True, "无 during 跨镜引用（无可判项）", edges
    return True, f"{n_refs} 处 during 引用均已定义、同场景、编译序在前", edges


def check_cycles(shots, edges):
    """⑤ 循环引用：during 引用图（仅含已定义目标）成环即拒。DFS 三色。"""
    if not edges:
        return True, "无 during 引用边，无环可成"
    n = len(shots)
    adj = {i: [] for i in range(n)}
    for a, b in edges:
        adj[a].append(b)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = [WHITE] * n
    parent = [None] * n
    cycle = None

    def dfs(root):
        stack = [(root, iter(adj[root]))]
        color[root] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color[nxt] == GRAY:
                    # 找到环：回溯 node→…→nxt
                    path = [node]
                    p = parent[node]
                    while p is not None and p != nxt:
                        path.append(p)
                        p = parent[p]
                    path.append(nxt)
                    return list(reversed(path))
                if color[nxt] == WHITE:
                    parent[nxt] = node
                    color[nxt] = GRAY
                    stack.append((nxt, iter(adj[nxt])))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
        return None

    for i in range(n):
        if color[i] == WHITE:
            cycle = dfs(i)
            if cycle:
                break
    if cycle:
        names = [shots[k].get("shot_id", f"#{k}") for k in cycle]
        return False, "during 引用图成环: " + " → ".join(names + [names[0]])
    return True, f"{len(edges)} 条 during 引用边无环"


def check_shot_line_count(shots, segments, enabled):
    """⑥ 镜头数 == CP2 台词条数（cp3.gate.shot_line_count_match）。"""
    if not enabled:
        return True, "SKIP：cp3.gate.shot_line_count_match=false（阈关闭）", True
    if segments is None:
        # fail-closed（主控验收修订）：source_script_fingerprint 是 CP3 必填字段，
        # 工件结构上依赖 CP2；无源即不可判定，拒。
        return False, ("未传 --script：镜头数/台词条数一致性无源判定（CP3 必填 "
                       "source_script_fingerprint，结构上依赖 CP2），fail-closed 拒"), False
    n_shots, n_lines = len(shots), len(segments)
    if n_shots != n_lines:
        return False, f"镜头数 {n_shots} != CP2 台词条数 {n_lines}（cp3.gate.shot_line_count_match）", False
    return True, f"镜头数 {n_shots} == CP2 台词条数 {n_lines}", False


def _collect_ids(entries, id_key):
    out = []
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, str):
                out.append(e)
            elif isinstance(e, dict) and isinstance(e.get(id_key), str):
                out.append(e[id_key])
    return out


def check_reference_integrity(shots, art_payload, script_payload):
    """⑦ 引用完整：refs 角色/道具 ID 必须解析到工件 payload.cast/props 或 --script
    payload.cast/props（悬空拒，AI视频生产流水线方案.md §3.2）。"""
    cast = _collect_ids(art_payload.get("cast"), "char_id")
    props = _collect_ids(art_payload.get("props"), "prop_id")
    src = ["artifact.payload"]
    if script_payload is not None:
        cast += _collect_ids(script_payload.get("cast"), "char_id")
        props += _collect_ids(script_payload.get("props"), "prop_id")
        src.append("--script.payload")
    registry = set(cast) | set(props)
    if not registry:
        # fail-closed（主控验收修订）：refs 存在但无任何注册表可解析 = 悬空即拒。
        n_refs_declared = sum(len(s.get("refs") or []) for s in shots if isinstance(s.get("refs"), list))
        if n_refs_declared > 0:
            return False, (f"工件声明 {n_refs_declared} 个 ref 但无 cast/props 注册表可解析"
                           "（CP3 契约不带注册表，必须 --script 透传 CP2），fail-closed 拒"), False
        return True, "无 refs 声明，无需注册表", False
    problems = []
    n_refs = 0
    for i, s in enumerate(shots):
        sid = s.get("shot_id", f"#{i}")
        refs = s.get("refs")
        if not isinstance(refs, list):
            continue  # ① 已报
        for r in refs:
            n_refs += 1
            if not isinstance(r, str) or r not in registry:
                problems.append(f"{sid} ref {r!r} 悬空（不在 {'/'.join(src)} 的 cast/props）")
    if problems:
        return False, "；".join(problems[:8]) + ("…" if len(problems) > 8 else ""), False
    return True, f"{n_refs} 个 ref 均解析到 {'+'.join(src)} 的 cast/props（{len(registry)} 项注册表）", False


# ---------------------------------------------------------------- 主流程

def run(artifact_path: Path, script_path, thresholds_path: Path) -> int:
    thr_path = thresholds_path
    gate = load_cp3_gate(thr_path)
    art = _load_json(artifact_path, "artifact")
    payload = precheck_artifact(art)
    shots = payload["shots"]

    script_payload = None
    segments = None
    if script_path is not None:
        script_payload = precheck_script(_load_json(script_path, "--script"))
        segments = script_payload.get("narration_segments")

    checks = []
    skipped = []

    def add(name, ok, detail, is_skip=False):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if is_skip:
            skipped.append(name)

    # ① 五要素齐全
    ok, detail = check_five_elements(shots)
    add("five_elements_complete", ok, detail)
    # ② 单镜时长上限（数值从 thresholds 读）
    limit = gate["max_shot_duration_s"]
    ok, detail = check_max_duration(shots, limit)
    add("max_shot_duration_s", ok, detail)
    # ③ 词锚定合法
    enabled = bool(gate["word_anchor_valid"])
    ok, detail, is_skip = check_word_anchors(shots, segments, enabled)
    add("word_anchor_valid", ok, detail, is_skip)
    # ④ 跨镜 during
    ok, detail, edges = check_during(shots)
    add("during_reference_valid", ok, detail)
    # ⑤ 循环引用
    ok, detail = check_cycles(shots, edges)
    add("no_circular_reference", ok, detail)
    # ⑥ 镜头数 == 台词条数
    enabled = bool(gate["shot_line_count_match"])
    ok, detail, is_skip = check_shot_line_count(shots, segments, enabled)
    add("shot_line_count_match", ok, detail, is_skip)
    # ⑦ 引用完整性
    ok, detail, is_skip = check_reference_integrity(shots, payload, script_payload)
    add("reference_integrity", ok, detail, is_skip)

    failed = [c["name"] for c in checks if not c["ok"]]
    verdict = "fail" if failed else "pass"
    out = {
        "verdict": verdict,
        "exit_code": 1 if failed else 0,
        "artifact": str(artifact_path),
        "script": str(script_path) if script_path else None,
        "thresholds_path": str(thresholds_path),
        "thresholds_sha256": sha256_file(thr_path),
        "params_used": {
            "max_shot_duration_s": gate["max_shot_duration_s"],
            "word_anchor_valid": bool(gate["word_anchor_valid"]),
            "shot_line_count_match": bool(gate["shot_line_count_match"]),
        },
        "checks": checks,
        "failed": failed,
        "skipped": skipped,
        "shot_count": len(shots),
        "line_count": (len(segments) if segments is not None else None),
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0 if verdict == "pass" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="validate_cp3",
        description="CP3 分镜表门禁校验器（校验器七条；判定数值只读 thresholds.yaml checkpoints.cp3.gate.*）")
    ap.add_argument("artifact", help="CP3 storyboard 工件 JSON 路径")
    ap.add_argument("--script", default=None, help="CP2 script 工件 JSON 路径（可选；③⑥⑦ 的台词/注册表来源）")
    ap.add_argument("--thresholds", default=None, help="thresholds.yaml 路径（默认仓内 overnight/vpipe/eval/thresholds.yaml）")
    args = ap.parse_args(argv)

    artifact_path = Path(args.artifact)
    if not artifact_path.exists():
        fail_error(f"artifact 文件不存在: {artifact_path}")
    thr_path = Path(args.thresholds) if args.thresholds else default_thresholds_path()
    script_path = Path(args.script) if args.script else None
    if script_path is not None and not script_path.exists():
        fail_error(f"--script 文件不存在: {script_path}")
    if not thr_path.exists():
        fail_error(f"thresholds 文件不存在: {thr_path}")

    return run(artifact_path, script_path, thr_path)


if __name__ == "__main__":
    sys.exit(main())
