#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_validate_cp5.py — CP5 门禁校验器自测（CLI 级，确定性，零模型调用）。

运行：
    cd overnight/vpipe && python3 tests/test_validate_cp5.py     # 独立运行
    python3 -m pytest tests/test_validate_cp5.py -q              # pytest 亦可

覆盖：
  A. 契约示例 contracts/v2/examples/cp5.json 必须 pass（exit 0，无 fail 检查项）
  B. tests/fixtures/checkpoints/cp5/pass/ 全部 exit 0（example 副本 / 分段长镜 / 已声明口型层）
  C. tests/fixtures/checkpoints/cp5/fail/ 全部 exit 1，且 fail 的检查项 id 与预期精确一致
     （非法关节 / 时间乱序 / 超帧数无切点 / 含 scale / full-body 无口型层 / 切点不足 / 骨长恒定关掉）
  D. 阈值覆写反硬编码检验：--thresholds 换 pose_frame_max=10 后 example 必须转 fail——
     证明 72 来自 checkpoints.cp5.gate.pose_frame_max 而非代码内第二套数值（schema 红线①）
  E. exit 2 通道：文件缺失 / JSON 不可解析 / 非 CP5 工件 / thresholds 缺失 /
     布尔强制键被改 false（拒绝旁路门禁）
  F. 确定性：同输入两次运行 verdict JSON 逐字节一致
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent            # overnight/vpipe/tests
VPIPE = HERE.parent                               # overnight/vpipe
VALIDATOR = VPIPE / "src" / "gate" / "validate_cp5.py"
EXAMPLE = VPIPE / "contracts" / "v2" / "examples" / "cp5.json"
NOT_CP5 = VPIPE / "contracts" / "v2" / "examples" / "cp3.json"
THRESHOLDS = VPIPE / "eval" / "thresholds.yaml"
FIX = HERE / "fixtures" / "checkpoints" / "cp5"

EXPECT_FAIL_CHECKS = {                             # 负例 → 必须 fail 的检查项 id（精确集合）
    "fail_01_illegal_joint.json": {"joint_names_legal"},
    "fail_02_time_disorder.json": {"frame_time_monotonic"},
    "fail_03_frame_overflow_no_cuts.json": {"pose_frame_max", "known_cuts_registered"},
    "fail_04_scale_in_frame.json": {"bone_length_constant"},
    "fail_05_fullbody_no_lip_layer.json": {"speech_fullbody_lip_layer"},
    "fail_06_insufficient_cuts.json": {"pose_frame_max", "known_cuts_registered"},
    "fail_07_bone_length_false.json": {"schema_structure", "bone_length_constant"},
}


def run(artifact, thresholds=None):
    cmd = [sys.executable, str(VALIDATOR), str(artifact)]
    if thresholds is not None:
        cmd += ["--thresholds", str(thresholds)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        verdict = json.loads(proc.stdout)
    except json.JSONDecodeError:
        verdict = None
    return proc.returncode, verdict, proc.stderr


class _T:
    """极简用例记账（独立运行时打印 PASS/FAIL 明细并给退出码；pytest 下自动收敛为 test_*）。"""

    def __init__(self):
        self.fails = []

    def check(self, name, ok, detail=""):
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" :: " + detail) if detail else ""))
        if not ok:
            self.fails.append((name, detail))


def _failed_ids(verdict):
    return {c["id"] for c in verdict["checks"] if c["result"] == "fail"}


def _case_example(t):
    code, v, _ = run(EXAMPLE)
    t.check("A 示例工件 pass(exit 0)", code == 0 and v and v["verdict"] == "pass",
            f"exit={code} verdict={v and v['verdict']}")
    if v:
        t.check("A 无任何 fail 检查项", not _failed_ids(v), str(sorted(_failed_ids(v))))


def _case_pass_fixtures(t):
    for f in sorted((FIX / "pass").glob("*.json")):
        code, v, _ = run(f)
        t.check(f"B pass 夹具 {f.name}", code == 0 and v and v["verdict"] == "pass",
                f"exit={code} fails={v and sorted(_failed_ids(v))}")


def _case_fail_fixtures(t):
    for f in sorted((FIX / "fail").glob("*.json")):
        code, v, _ = run(f)
        got = _failed_ids(v) if v else set()
        want = EXPECT_FAIL_CHECKS[f.name]
        t.check(f"C fail 夹具 {f.name} exit=1", code == 1 and v and v["verdict"] == "fail",
                f"exit={code}")
        t.check(f"C fail 夹具 {f.name} 归属精确", got == want,
                f"want={sorted(want)} got={sorted(got)}")


def _case_threshold_override(t):
    """反硬编码：把 pose_frame_max 覆写为 10，example（24 帧）必须由 pass 转 fail。"""
    with tempfile.TemporaryDirectory() as td:
        import yaml
        base = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
        base["checkpoints"]["cp5"]["gate"]["pose_frame_max"] = 10
        p = Path(td) / "thresholds_override.yaml"
        p.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
        code0, v0, _ = run(EXAMPLE)                # 未覆写：pass
        code1, v1, _ = run(EXAMPLE, thresholds=p)  # 覆写后：fail @pose_frame_max
        t.check("D 默认 thresholds 下 example pass", code0 == 0, f"exit={code0}")
        t.check("D 覆写 pose_frame_max=10 后 example fail",
                code1 == 1 and v1 and "pose_frame_max" in _failed_ids(v1),
                f"exit={code1} fails={v1 and sorted(_failed_ids(v1))}")


def _case_exit2(t):
    code, v, _ = run(VPIPE / "tests" / "no_such_artifact.json")
    t.check("E1 文件缺失 exit 2", code == 2 and v and v["verdict"] == "error", f"exit={code}")

    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        code, v, _ = run(bad)
        t.check("E2 JSON 不可解析 exit 2", code == 2 and v and v["verdict"] == "error", f"exit={code}")

    code, v, _ = run(NOT_CP5)
    t.check("E3 非 CP5 工件 exit 2", code == 2 and v and v["verdict"] == "error",
            f"exit={code} err={v and v.get('error', '')[:60]}")

    code, v, _ = run(EXAMPLE, thresholds=Path(td) / "absent.yaml")
    t.check("E4 thresholds 缺失 exit 2", code == 2 and v and v["verdict"] == "error", f"exit={code}")

    with tempfile.TemporaryDirectory() as td2:
        import yaml
        base = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
        base["checkpoints"]["cp5"]["gate"]["frame_time_monotonic"] = False   # 布尔强制键被关
        p = Path(td2) / "th_force_false.yaml"
        p.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
        code, v, _ = run(EXAMPLE, thresholds=p)
        t.check("E5 强制键=false 拒绝旁路 exit 2", code == 2 and v and v["verdict"] == "error",
                f"exit={code}")


def _case_determinism(t):
    a = subprocess.run([sys.executable, str(VALIDATOR), str(EXAMPLE)],
                       capture_output=True, text=True).stdout
    b = subprocess.run([sys.executable, str(VALIDATOR), str(EXAMPLE)],
                       capture_output=True, text=True).stdout
    t.check("F 同输入两次运行 verdict 一致", a == b and json.loads(a)["verdict"] == "pass",
            "deterministic" if a == b else "输出不一致")


# ---- pytest 入口 ----
def test_example_passes():
    t = _T(); _case_example(t); assert not t.fails, t.fails

def test_pass_fixtures():
    t = _T(); _case_pass_fixtures(t); assert not t.fails, t.fails

def test_fail_fixtures():
    t = _T(); _case_fail_fixtures(t); assert not t.fails, t.fails

def test_threshold_override():
    t = _T(); _case_threshold_override(t); assert not t.fails, t.fails

def test_exit2_channel():
    t = _T(); _case_exit2(t); assert not t.fails, t.fails

def test_determinism():
    t = _T(); _case_determinism(t); assert not t.fails, t.fails


def main() -> int:
    print(f"validate_cp5 自测（validator={VALIDATOR}）")
    t = _T()
    _case_example(t)
    _case_pass_fixtures(t)
    _case_fail_fixtures(t)
    _case_threshold_override(t)
    _case_exit2(t)
    _case_determinism(t)
    n = len(t.fails)
    print(f"结论：{'ALL PASS' if n == 0 else f'{n} FAIL'}（{n} 条失败）")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
