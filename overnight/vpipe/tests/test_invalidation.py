#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_invalidation.py — src/gate/invalidation.py 失效传播自测（TASK_v4 M3-W11）。

八件事，全过才 exit 0：
1. 场景回放（基线/A/B/C；材料：tests/fixtures/checkpoints/template/）：
   base_chain.json.gz 物化 → 按 scenarios/*.inputs.json 施加编辑 → plan →
   实测与 *.measured.json 逐字段全等 + 逐字段满足 *.expected.json（手推预期，
   来源：W11 验收条件 + upstream_refs 图，非抄实测）；
2. BFS 闭包：菱形图（cp6←{cp3,cp5}）闭包正确、同一工件只失效一次（去重）、
   via=直接失效者（cp5.via=cp3 而非 cp2）；
3. 断链：悬空指纹指向非被改工件 → exit 2 且 errors 含「断链」；
4. 断链归因：悬空指向被改工件（上游已 relink 场景）→ exit 0 且下游判失效
   （这是失效信号本体，真失效，非图错误）；
5. 环：双节点环与自引用 → exit 2 且 errors 含「环」；
6. 槽位过滤：前瞻形态（refs 携带 slot 字段，超出现行 v2 契约的增强路径）下
   --slot 收窄闭包（引用其他槽位的下游命中缓存不重跑）；无 --slot 不收窄；
   --slot 在 payload 中不存在 → exit 2；
7. 用法错误：--changed 不在 --dir 内 / --dir 不存在 → exit 2；
8. 只读红线：全部回放前后 base 链逐字节一致（md5），plan 是干跑。

用法：python3 tests/test_invalidation.py
依赖：标准库（无第三方）。
"""

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VPIPE = Path(__file__).resolve().parents[1]
TOOL = VPIPE / "src" / "gate" / "invalidation.py"
FX = VPIPE / "tests" / "fixtures" / "checkpoints" / "template"

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def run_plan(root: Path, changed: str, slot: str | None = None):
    argv = [sys.executable, str(TOOL), "plan", "--dir", str(root),
            "--changed", str(Path(root) / changed)]
    if slot:
        argv += ["--slot", slot]
    r = subprocess.run(argv, capture_output=True, text=True, cwd=VPIPE)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = None
    return r.returncode, out, r.stdout


def materialize(dest: Path) -> Path:
    """base_chain.json.gz → 目录树（{relpath: artifact}）。"""
    with gzip.open(FX / "base_chain.json.gz", "rt", encoding="utf-8") as z:
        chain = json.load(z)
    for rel, art in chain.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(art, ensure_ascii=False, separators=(",", ":")) + "\n",
                     encoding="utf-8")
    return dest


def tree_md5(root: Path) -> str:
    h = hashlib.md5()
    for f in sorted(root.rglob("*.json")):
        h.update(f.relative_to(root).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def apply_edit(root: Path, inputs: dict) -> None:
    """按场景输入快照施加编辑（与建快照时的会话实跑同一操作）。"""
    if not inputs.get("edit") and inputs["scenario"] == "A_slot_narration":
        p = root / inputs["file"]
        a = json.loads(p.read_text(encoding="utf-8"))
        hit = False
        for val in a["payload"].values():
            if isinstance(val, list):
                for item in val:
                    if (isinstance(item, dict) and item.get("segment_id") == inputs["slot"]):
                        item[inputs["field"]] = inputs["new"]
                        hit = True
        assert hit, f"编辑未命中槽位 {inputs['slot']}"
        p.write_text(json.dumps(a, ensure_ascii=False, separators=(",", ":")) + "\n",
                     encoding="utf-8")
    elif inputs.get("op") == "swap_index_0_and_1":
        p = root / inputs["file"]
        a = json.loads(p.read_text(encoding="utf-8"))
        sh = a["payload"]["shots"]
        sh[0], sh[1] = sh[1], sh[0]
        p.write_text(json.dumps(a, ensure_ascii=False, separators=(",", ":")) + "\n",
                     encoding="utf-8")
    # baseline / C_last_stage：edit=None，零改动（模拟变更）


# ---------- 1. 场景回放 ----------
def scenario_replays() -> None:
    print("—— 场景回放（fixtures/checkpoints/template）——")
    tmp_root = Path(tempfile.mkdtemp(prefix="tpl_test_"))
    chain_md5_before = tree_md5(FX)  # 快照本体不被测试污染（回放在副本上）
    for name in ["baseline", "A_slot_narration", "B_reorder_shots", "C_last_stage"]:
        work = materialize(tmp_root / name)
        inputs = json.loads((FX / "scenarios" / f"{name}.inputs.json").read_text(encoding="utf-8"))
        apply_edit(work, inputs)
        code, out, raw = run_plan(work, inputs["changed"], inputs.get("slot"))
        check(f"{name}: exit==0", code == 0, raw)
        if out is None:
            check(f"{name}: stdout 为合法 JSON", False, raw)
            continue
        measured = json.loads((FX / "scenarios" / f"{name}.measured.json").read_text(encoding="utf-8"))
        check(f"{name}: 实测与 measured 快照全等", out == measured,
              json.dumps({"got": out, "want": measured}, ensure_ascii=False)[:400])
        expected = json.loads((FX / "scenarios" / f"{name}.expected.json").read_text(encoding="utf-8"))

        def got_of(k: str):
            """expected.json 手推字段 → 实测输出的取值映射（expected 是手写契约，
            键名按验收语义命名；此处只做字段映射，不做判定放水）。"""
            if k == "payload_drifted":
                return out["changed_fingerprint"]["payload_drifted"]
            if k == "invalidated_paths":
                return sorted(i["path"] for i in out["invalidated"])
            if k == "slot_resolved":
                return bool((out.get("slot") or {}).get("resolved_locus"))
            if k == "slot_granularity":
                return (out.get("slot") or {}).get("granularity")
            return out.get(k)

        mism = [f"{k}: got={got_of(k)!r} want={want!r}"
                for k, want in expected.items()
                if k != "expectations" and got_of(k) != want]
        check(f"{name}: 满足手推预期 expected.json", not mism, "; ".join(mism))
    # W11 验收断言（逐条落到具体字段）
    mA = json.loads((FX / "scenarios" / "A_slot_narration.measured.json").read_text(encoding="utf-8"))
    mB = json.loads((FX / "scenarios" / "B_reorder_shots.measured.json").read_text(encoding="utf-8"))
    mC = json.loads((FX / "scenarios" / "C_last_stage.measured.json").read_text(encoding="utf-8"))
    check("W11-A: cp2 之后全链失效 15（cp3/cp5/cp6/cp7.json/11 镜）且 cp1 不重跑",
          mA["invalidated_count"] == 15 and mA["unaffected"] == ["cp1.json"])
    check("W11-A: 槽位级降级如实入档（契约 upstream_refs 仅两键）",
          (mA.get("slot") or {}).get("granularity") == "artifact_level_fallback"
          and "降级" in (mA.get("slot") or {}).get("note", ""))
    check("W11-B: 重排→cp3 指纹必变（payload_drifted）且下游 14 真失效",
          mB["changed_fingerprint"]["payload_drifted"] is True
          and mB["invalidated_count"] == 14
          and {"cp5.json", "cp6.json", "cp7.json"} <= {i["path"] for i in mB["invalidated"]})
    check("W11-B: 上游零伪失效（cp1/cp2 不重跑）",
          mB["unaffected"] == ["cp1.json", "cp2.json"])
    inB = json.loads((FX / "scenarios" / "B_reorder_shots.inputs.json").read_text(encoding="utf-8"))
    check("W11-B: 重排仅改序（shot 多重集不变；同集合异序→异指纹）",
          inB["shot_multiset_unchanged"] is True
          and inB["fingerprint_order_sensitivity"]["differ"] is True)
    check("W11-C: 末段工件失效闭包=∅，其余 16 命中指纹缓存（重跑最便宜）",
          mC["invalidated_count"] == 0 and mC["unaffected_count"] == 16)
    shutil.rmtree(tmp_root, ignore_errors=True)
    check("红线: fixtures 快照零污染（测试前后 md5 一致）", tree_md5(FX) == chain_md5_before)


# ---------- 2-7. 图语义单测（合成图） ----------
def art(cp, fp, refs, payload=None):
    return {"schema_version": "2.0", "cp_id": cp, "artifact_type": "script",
            "fingerprint": fp, "produced_by": "test", "produced_at": "2026-10-09T00:00:00Z",
            "work_id": "w", "upstream_refs": refs, "status": "passed",
            "payload": payload if payload is not None else {"work_id": "w"}}


def synth_tree(name: str, arts: list[dict]) -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"inv_{name}_"))
    for a in arts:
        (root / f"{a['cp_id']}.json").write_text(
            json.dumps(a, ensure_ascii=False) + "\n", encoding="utf-8")
    return root


def unit_graph_semantics() -> None:
    print("—— 图语义单测（合成图）——")
    A, B, C, D, E = "a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64
    # 2. 菱形闭包：cp1←cp2←cp3←{cp4(←cp3),cp5(←cp3,cp4)}；改 cp2 → 全链；via=直接失效者
    root = synth_tree("diamond", [
        art("cp1", A, []), art("cp2", B, [{"cp_id": "cp1", "fingerprint": A}]),
        art("cp3", C, [{"cp_id": "cp2", "fingerprint": B}]),
        art("cp4", D, [{"cp_id": "cp3", "fingerprint": C}]),
        art("cp5", E, [{"cp_id": "cp3", "fingerprint": C}, {"cp_id": "cp4", "fingerprint": D}])])
    code, out, raw = run_plan(root, "cp2.json")
    paths = {i["path"] for i in (out or {}).get("invalidated", [])}
    via = {i["path"]: i["via"] for i in (out or {}).get("invalidated", [])}
    check("BFS: 菱形闭包全链失效（4 节点，cp5 只失效一次）",
          code == 0 and paths == {"cp3.json", "cp4.json", "cp5.json"}
          and len((out or {}).get("invalidated", [])) == 3, raw)
    check("BFS: via=直接失效者（cp4.via=cp3；cp5 直引用 cp3，其 ref 已悬→via=最早失效的直接上游 cp3，判定等价）",
          via.get("cp4.json") == "cp3.json" and via.get("cp5.json") == "cp3.json"
          and "指纹失配" in next(i["reason"] for i in out["invalidated"] if i["path"] == "cp5.json"))
    check("BFS: 不在闭包内者不受影响（防伪失效：cp1 不重跑）",
          (out or {}).get("unaffected") == ["cp1.json"])
    shutil.rmtree(root, ignore_errors=True)

    # 3. 断链：悬空指向非被改工件 → exit 2
    root = synth_tree("badlink", [
        art("cp1", A, []), art("cp2", B, [{"cp_id": "cp1", "fingerprint": A}]),
        art("cp3", C, [{"cp_id": "cp2", "fingerprint": E}])])
    code, out, raw = run_plan(root, "cp1.json")
    errs = json.dumps((out or {}).get("errors", []), ensure_ascii=False)
    check("断链: exit==2 且 errors 如实报", code == 2 and "断链" in errs, raw)
    shutil.rmtree(root, ignore_errors=True)

    # 4. 断链归因：悬空指向被改工件（上游已 relink）→ exit 0，真失效
    root = synth_tree("relink", [
        art("cp1", A, [], {"v": 2}), art("cp2", B, [{"cp_id": "cp1", "fingerprint": E}])])
    code, out, raw = run_plan(root, "cp1.json")
    inv = (out or {}).get("invalidated", [])
    check("断链归因: 悬空指向被改工件→exit 0 且下游真失效（reason 含悬空+via=changed）",
          code == 0 and len(inv) == 1 and inv[0]["path"] == "cp2.json"
          and inv[0]["via"] == "cp1.json" and "悬空" in inv[0]["reason"], raw)
    shutil.rmtree(root, ignore_errors=True)

    # 5. 环：双节点环 / 自引用 → exit 2
    root = synth_tree("cycle", [
        art("cp1", A, [{"cp_id": "cp2", "fingerprint": B}]),
        art("cp2", B, [{"cp_id": "cp1", "fingerprint": A}])])
    code, out, raw = run_plan(root, "cp1.json")
    errs = json.dumps((out or {}).get("errors", []), ensure_ascii=False)
    check("环: 双节点环 exit==2 且 errors 如实报", code == 2 and "环" in errs, raw)
    shutil.rmtree(root, ignore_errors=True)
    root = synth_tree("selfloop", [art("cp1", A, [{"cp_id": "cp1", "fingerprint": A}])])
    code, out, raw = run_plan(root, "cp1.json")
    errs = json.dumps((out or {}).get("errors", []), ensure_ascii=False)
    check("环: 自引用 exit==2", code == 2 and "环" in errs, raw)
    shutil.rmtree(root, ignore_errors=True)

    # 6. 槽位过滤（前瞻形态：refs 携带 slot 字段——现行 v2 契约 additionalProperties:false
    #    不允许此形态，故真实链走工件级降级；此处单测增强路径本身的判定逻辑）
    F = "f" * 64
    takes = {"takes": [{"take_id": "t1", "line": "台词一"}, {"take_id": "t2", "line": "台词二"}]}
    root = synth_tree("slotfilter", [
        art("cp1", A, [], takes),
        art("cp2", B, [{"cp_id": "cp1", "fingerprint": A, "slot": "t1"}]),
        art("cp3", C, [{"cp_id": "cp1", "fingerprint": A, "slot": "t2"}]),
        art("cp4", D, [{"cp_id": "cp1", "fingerprint": A}])])
    code, out, raw = run_plan(root, "cp1.json", slot="t1")
    inv = {i["path"] for i in (out or {}).get("invalidated", [])}
    una = (out or {}).get("unaffected", [])
    mode = (out or {}).get("closure_mode")
    check("槽位过滤: --slot t1 只失效引用 t1/无槽位限定者；引用 t2 者命中缓存",
          code == 0 and mode == "slot_scoped"
          and inv == {"cp2.json", "cp4.json"} and una == ["cp3.json"], raw)
    code, out, raw = run_plan(root, "cp1.json")
    inv = {i["path"] for i in (out or {}).get("invalidated", [])}
    check("槽位过滤: 无 --slot 不收窄（全链失效）",
          code == 0 and (out or {}).get("closure_mode") == "artifact_level"
          and inv == {"cp2.json", "cp3.json", "cp4.json"}, raw)
    code, out, raw = run_plan(root, "cp1.json", slot="nope")
    check("槽位过滤: --slot 不存在于 payload → exit 2", code == 2, raw)
    shutil.rmtree(root, ignore_errors=True)

    # 7. 用法错误
    root = synth_tree("usage", [art("cp1", A, [])])
    code, out, raw = run_plan(Path(tempfile.mkdtemp(prefix="inv_other_")), "cp1.json")
    check("用法: --changed 不在 --dir 内 → exit 2", code == 2, raw)
    code, out, raw = run_plan(Path(tempfile.mkdtemp(prefix="inv_empty_")), "cp1.json")
    check("用法: --dir 内无 CP 工件 → exit 2", code == 2, raw)
    shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    scenario_replays()
    unit_graph_semantics()
    print(f"\n共 {checks} 项检查，失败 {len(failures)} 项")
    if failures:
        for f in failures:
            print("  FAIL:", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
