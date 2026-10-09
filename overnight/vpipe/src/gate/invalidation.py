#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""invalidation.py — CP 工件指纹图的失效传播计划器（plan=干跑，只读工件，零改写）。

语义（与 src/gate/fingerprint.py docstring、checkpoint.schema definitions.fingerprint、
SPEC_v2.md §3「缓存/失效语义」、白皮书 §5.4「缓存/失效重写为槽位级指纹图」逐字对齐）：
    某工件 payload 变更 → 其 fingerprint 变 → 所有 upstream_refs 指向其旧指纹的
    下游工件失效；失效工件重跑后又产生新指纹 → 它的下游同样失效（沿 upstream_refs
    图 BFS 闭包）。被判定失效的工件必须重跑；不在闭包内的工件不许重跑（防伪失效）。

指纹口径沿用 fingerprint.py（唯一口径）：fingerprint = sha256(canonical_json(payload))，
canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)。**数组序参与哈希** → 跨镜重排必改指纹（顺序是 payload 内容），
故重排产生的下游失效是真失效（装配序改变），本工具如实报告而不特判豁免。

主路径 / 增强路径：
    主路径 = upstream_refs 指纹匹配（契约 upstream_refs 条目仅 {cp_id, fingerprint}
    两键，additionalProperties:false——contracts/v2/checkpoint.schema.json）；
    增强路径 = --slot 槽位级失效：仅当下游工件存在携带 slot 字段的槽位级引用
    （{cp_id, fingerprint, slot}，超出现行 v2 契约的前瞻形态）时，闭包才可收窄到
    「引用了被改槽位的下游」；否则如实降级为工件级闭包并在输出中说明（不虚报细粒度）。

CLI：
    python3 src/gate/invalidation.py plan --dir <工件目录> --changed <工件路径> [--slot <slot名>]

输出（stdout，单份 JSON）：
    {changed, invalidated:[{path, reason, via}], invalidated_count,
     unaffected, unaffected_count, ...}
退出码：0=计划生成；2=用法或图错误（--changed 不在图内 / 槽位不存在 / 断链 / 环，
errors 字段如实列出全部断链与环）。

红线：本工具只读（不写任何工件、不改 fingerprint/upstream_refs 字段）；目录内无
payload 的 *.json（prompts/run_report/l0 等）视为非 CP 工件，跳过并如实列出。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path

if __package__ in (None, ""):  # 直接脚本运行：python3 src/gate/invalidation.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fingerprint import compute_fingerprint
else:  # 包内导入（tests / 其他 gate 模块）
    from .fingerprint import compute_fingerprint

FP_RE = re.compile(r"^[0-9a-f]{64}$")


def short(fp: str) -> str:
    return (fp or "")[:12] + "…"


class Artifact:
    """目录内的一个 CP 工件节点（路径相对 --dir，POSIX 词形）。"""

    __slots__ = ("path", "cp_id", "declared_fp", "computed_fp", "refs", "payload")

    def __init__(self, path: str, art: dict):
        self.path = path
        self.cp_id = art.get("cp_id")
        self.declared_fp = art.get("fingerprint")
        self.payload = art.get("payload")
        self.computed_fp = compute_fingerprint(art)
        self.refs = [r for r in (art.get("upstream_refs") or []) if isinstance(r, dict)]


def load_graph(root: Path) -> tuple[dict[str, Artifact], list[str]]:
    """递归载入 root 下全部含 payload 的 *.json 为图节点；其余跳过并列出。"""
    artifacts: dict[str, Artifact] = {}
    skipped: list[str] = []
    for f in sorted(root.rglob("*.json")):
        rel = f.relative_to(root).as_posix()
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            skipped.append(rel)
            continue
        if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
            skipped.append(rel)  # 非 CP 工件（prompts/run_report/l0 等）
            continue
        artifacts[rel] = Artifact(rel, data)
    return artifacts, skipped


def resolve_slot(payload: dict, slot: str) -> str | None:
    """在 payload 内定位槽位：顶层键名、key[序号]、列表内 *_id 字段值均可。

    返回槽位坐标词形（如 payload.narration_segments[segment_id=seg_02]），
    找不到返回 None。
    """
    if slot in payload:
        return f"payload.{slot}"
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]", slot)
    if m and isinstance(payload.get(m.group(1)), list):
        idx = int(m.group(2))
        if 0 <= idx < len(payload[m.group(1)]):
            return f"payload.{slot}"
    for key, val in payload.items():
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    for ik, iv in item.items():
                        if ik.endswith("_id") and iv == slot:
                            return f"payload.{key}[{ik}={slot}]"
    return None


def plan(root: Path, changed_path: Path, slot: str | None) -> tuple[dict, list[str], int]:
    """生成失效传播计划。返回 (输出 JSON, errors, exit_code)。只读，零改写。"""
    errors: list[str] = []
    if not root.is_dir():
        return {"errors": [f"--dir 不存在或不是目录: {root}"]}, [f"--dir 不存在或不是目录: {root}"], 2

    artifacts, skipped = load_graph(root)
    if not artifacts:
        msg = f"--dir 内没有任何含 payload 的 CP 工件: {root}"
        return {"errors": [msg]}, [msg], 2

    # ---- 定位 changed 工件（用法错误 → exit 2） ----
    try:
        changed_rel = changed_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        msg = f"--changed 不在 --dir 内: {changed_path}"
        return {"errors": [msg]}, [msg], 2
    changed = artifacts.get(changed_rel)
    if changed is None:
        msg = (f"--changed 不是图内 CP 工件（不存在或无 payload）: {changed_rel}")
        return {"errors": [msg]}, [msg], 2

    # ---- 槽位解析（找不到 → 用法错误 exit 2） ----
    slot_info: dict = {"requested": slot}
    if slot is not None:
        locus = resolve_slot(changed.payload, slot)
        if locus is None:
            msg = f"--slot 在 {changed_rel} 的 payload 中不存在: {slot}"
            return {"errors": [msg], "slot": slot_info}, [msg], 2
        slot_info["resolved_locus"] = locus

    # ---- 声明指纹一致性（缺字段/坏词形 → 图错误） ----
    for a in sorted(artifacts.values(), key=lambda x: x.path):
        if not a.declared_fp or not FP_RE.fullmatch(a.declared_fp):
            errors.append(f"工件缺少合法 fingerprint 字段（断链无法评估）: {a.path}")
    # 指纹声明索引：declared_fp → {path,…}；同一 declared_fp 指向不同内容 = 冲突
    declared_index: dict[str, set[str]] = {}
    by_path = {a.path: a for a in artifacts.values()}
    for a in artifacts.values():
        if a.declared_fp and FP_RE.fullmatch(a.declared_fp):
            declared_index.setdefault(a.declared_fp, set()).add(a.path)
    for fp, paths in sorted(declared_index.items()):
        computed_set = {by_path[p].computed_fp for p in paths}
        if len(computed_set) > 1:
            errors.append(
                f"指纹声明冲突：declared {short(fp)} 被内容不同的多个工件声明: {sorted(paths)}")

    # ---- 建边：ref.fingerprint 精确匹配图内声明指纹（主路径） ----
    # dependents[upstream_path] = [(downstream_path, ref), …]
    # dangling_warnings（主控修订 2026-10-09）：指向图外指纹的 ref（如 CP11/CP12 引
    # 用的 cp10 交付物清单 sha256——非 CP 工件、按设计不在指纹图内）是**已知合法
    # 模式**，报 warnings 不阻断闭包计算；只有环（循环依赖）必须阻断（BFS 无法进行）。
    dangling_warnings: list[str] = []
    dependents: dict[str, list[tuple[str, dict]]] = {}
    for a in artifacts.values():
        for r in a.refs:
            hits = declared_index.get(r.get("fingerprint", ""), set())
            if not hits:
                # 悬空指纹：若指向被改工件的 cp_id，说明上游已改/relink——这是
                # 失效信号本体，归因于 changed；否则是断链（图外引用）。
                if r.get("cp_id") == changed.cp_id:
                    dependents.setdefault(changed_rel, []).append((a.path, r))
                else:
                    dangling_warnings.append(
                        f"图外引用：{a.path} 的 upstream_refs 指向图内不存在的指纹 "
                        f"{short(r.get('fingerprint', ''))} (cp_id={r.get('cp_id')})"
                        "——非 CP 工件（交付物清单等）的已知合法模式，不阻断闭包")
                continue
            for up in hits:
                if up == a.path:
                    errors.append(f"环（自引用）：{a.path} 的 upstream_refs 指向自己的指纹")
                    continue
                dependents.setdefault(up, []).append((a.path, r))

    # ---- 环检测（依赖图 DFS 三色标记） ----
    adj: dict[str, set[str]] = {}
    for up, edges in dependents.items():
        for dn, _ in edges:
            adj.setdefault(up, set()).add(dn)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {p: WHITE for p in artifacts}
    stack_path: list[str] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        stack_path.append(u)
        for v in sorted(adj.get(u, ())):
            if color.get(v) == GRAY:
                cycle = stack_path[stack_path.index(v):] + [v]
                errors.append("环（upstream_refs 依赖图存在循环）: " + " → ".join(cycle))
            elif color.get(v) == WHITE:
                dfs(v)
        stack_path.pop()
        color[u] = BLACK

    for p in sorted(artifacts):
        if color[p] == WHITE:
            dfs(p)

    if errors:
        out = {
            "changed": changed_rel,
            "errors": sorted(set(errors)),
            "graph": {"artifacts": len(artifacts), "skipped_non_artifact": skipped},
        }
        return out, sorted(set(errors)), 2

    # ---- 槽位级收窄判断（增强路径）：下游是否存在指向 changed 的槽位级引用 ----
    # 收窄按边逐条判定：带 slot 字段（前瞻形态）的引用只在命中被改槽位时失效；
    # 不带 slot 的工件级引用只要存在（对该下游），changed 一改它即失效（整件指纹已变）。
    downstream_edges = dependents.get(changed_rel, [])
    any_slot_scoped = any("slot" in r for _, r in downstream_edges)
    if slot is not None and downstream_edges and any_slot_scoped:
        # 存在槽位级引用 → 闭包可收窄（工件级引用的下游仍按边失效）
        closure_mode = "slot_scoped"
        slot_info["granularity"] = "slot_scoped"
        slot_info["note"] = ("下游存在槽位级引用：仅失效引用该槽位"
                             "（或含工件级引用）的下游，引用其他槽位者命中缓存不重跑")
    else:
        closure_mode = "artifact_level"
        if slot is not None:
            slot_info["granularity"] = "artifact_level_fallback"
            if downstream_edges:
                slot_info["note"] = (
                    "契约 upstream_refs 条目仅 {cp_id, fingerprint} 两键"
                    "（additionalProperties:false），下游无槽位级引用可匹配 → "
                    "如实降级为工件级失效闭包（整件指纹已变，下游必须重跑）")
            else:
                slot_info["note"] = "被改工件无任何下游，失效闭包为空（末段工件，重跑最便宜）"

    # ---- BFS 失效闭包 ----
    invalidated: dict[str, dict] = {}

    def invalidate(y: str, via: str, reason: str) -> None:
        invalidated[y] = {"path": y, "reason": reason, "via": via}

    # 种子 1：ref 指纹悬空但 cp_id 指向 changed（上游已 relink 的场景）
    for a in artifacts.values():
        if a.path == changed_rel:
            continue
        for r in a.refs:
            if r.get("cp_id") == changed.cp_id and r.get("fingerprint") not in declared_index:
                invalidate(a.path, changed_rel,
                           f"upstream_ref 悬空：指向 {changed.cp_id} 的指纹 "
                           f"{short(r.get('fingerprint', ''))} 在图内无匹配"
                           f"（{changed.cp_id} payload 已变更/已 relink）→ 必须重跑")
                break

    queue: deque[str] = deque([changed_rel])
    while queue:
        x = queue.popleft()
        xa = by_path[x]
        for y_rel, r in dependents.get(x, ()):
            if y_rel == changed_rel or y_rel in invalidated:
                continue
            if closure_mode == "slot_scoped" and x == changed_rel:
                rs = r.get("slot")
                if rs is not None and rs != slot:
                    continue  # 槽位级引用且不是被改槽位 → 缓存命中，不失效
            invalidate(
                y_rel, x,
                f"upstream_ref 指纹失配：引用 {xa.cp_id}({x}) 的 "
                f"{short(r.get('fingerprint', ''))}，但该工件 payload 变更"
                f"（重排/改写）指纹已变 → 必须重跑")
            queue.append(y_rel)

    all_paths = sorted(artifacts)
    unaffected = [p for p in all_paths if p != changed_rel and p not in invalidated]
    drifted = changed.declared_fp != changed.computed_fp
    out = {
        "changed": changed_rel,
        "changed_fingerprint": {
            "declared": changed.declared_fp,
            "computed_from_payload": changed.computed_fp,
            "payload_drifted": drifted,
            "note": ("payload 与声明指纹不一致：变更已发生，指纹待 relink"
                     if drifted else
                     "payload 与声明指纹一致：plan 视为模拟变更（该工件重跑后指纹必变）"),
        },
        "invalidated": [invalidated[p] for p in all_paths if p in invalidated],
        "invalidated_count": len(invalidated),
        "unaffected": unaffected,
        "unaffected_count": len(unaffected),
        "slot": slot_info if slot is not None else None,
        "closure_mode": closure_mode,
        "graph": {
            "artifacts": len(artifacts),
            "edges": sum(len(v) for v in dependents.values()),
            "skipped_non_artifact": skipped,
        },
        "warnings": sorted(set(dangling_warnings)),
    }
    return out, [], 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="invalidation.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p_plan = sub.add_parser("plan", help="生成失效传播计划（干跑，只读）")
    p_plan.add_argument("--dir", required=True, help="CP 工件目录（递归扫描 *.json）")
    p_plan.add_argument("--changed", required=True, help="被改工件路径（须在 --dir 内）")
    p_plan.add_argument("--slot", default=None, help="槽位名（增强路径，找不到即降级/报错）")
    args = ap.parse_args(argv[1:])
    if args.cmd != "plan":
        ap.print_usage()
        return 2
    out, _errors, code = plan(Path(args.dir), Path(args.changed), args.slot)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
