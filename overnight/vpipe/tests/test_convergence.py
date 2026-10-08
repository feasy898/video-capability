#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_convergence.py — CP 收敛曲线工具自测（CLI 级，确定性，零模型调用）。

运行：
    cd overnight/vpipe && python3 tests/test_convergence.py     # 独立运行
    python3 -m pytest tests/test_convergence.py -q              # pytest 亦可

覆盖：
  A. log/report 往返：3 轮逐笔 log → report json 的逐轮 residual/fixed/
     new_failures 与输入逐值一致；md 格式含表格与 verdict
  B. append-only：每次 log 后既有字节是前缀、逐行未被改写，文件只增不改
  C. 收敛判据三态（stall_rounds=2 经 CLI 显式传入，不硬编码）：
     C1 [5,2,0] → converged（末轮 residual=0）
     C2 [3,3,4] → diverging（连续 2 轮 residual 不降；report exit 3）
     C3 [5,2]   → in_progress（仅 1 个轮间差，不足 stall_rounds+1 轮）
     C4 [5,2,2] → in_progress（轮间差 [-3,0]，最后 2 个不全 >=0）
  D. 判据不硬编码：[3,3,4] 不传 --stall-rounds → 不判 diverging
     （in_progress + criteria.stall_rounds=null + 明示判据未启用）
  E. 同 (cp_id, round) 重复 log → exit 2，数据文件字节不变（append-only 不改写）
  F. --cp-id 过滤：双 CP 数据只返回一个
  G. 参数与数据校验 exit 2 通道：residual<0 / round=0 / stall-rounds<1 /
     数据文件缺失 / 空文件 / 手工注入重复轮
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
TOOL = VPIPE / "src" / "gate" / "convergence.py"


def run(*argv):
    return subprocess.run([sys.executable, str(TOOL), *[str(a) for a in argv]],
                          capture_output=True, text=True)


def log(data, cp, rnd, residual, fixed, new_failures, note=None):
    argv = ["log", "--data", data, "--cp-id", cp, "--round", rnd,
            "--residual", residual, "--fixed", fixed, "--new-failures", new_failures]
    if note:
        argv += ["--note", note]
    return run(*argv)


def report(data, *extra):
    return run("report", "--data", data, *extra)


class T:
    def __init__(self):
        self.fails = []

    def check(self, name, ok, detail=""):
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               (" :: " + detail) if detail else ""))
        if not ok:
            self.fails.append((name, detail))


def _series(t, data, cp, residuals, base_fixed=3, base_new=0):
    """按残量序列逐笔 log（fixed/new_failures 用固定底值，判据只看 residual）。"""
    for i, r in enumerate(residuals, 1):
        p = log(data, cp, i, r, base_fixed, base_new)
        t.check(f"log {cp} round {i} (residual={r}) exit 0", p.returncode == 0, p.stderr)


# ---------------------------------------------------------------- A 往返

def _case_roundtrip(t: T):
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "conv.jsonl"
        rows = [(1, 5, 3, 1, "首修"), (2, 2, 4, 1, None), (3, 0, 2, 0, "清零")]
        for rnd, res, fix, new, note in rows:
            p = log(data, "cp11", rnd, res, fix, new, note)
            t.check("A log round %d exit 0" % rnd, p.returncode == 0, p.stderr)

        p = report(data, "--stall-rounds", 2)
        t.check("A report json exit 0", p.returncode == 0, p.stderr + p.stdout[:200])
        rep = json.loads(p.stdout)
        cp = rep["checkpoints"][0]
        t.check("A cp_id", cp["cp_id"] == "cp11", cp["cp_id"])
        got = [(r["round"], r["residual_count"], r["fixed_count"], r["new_failures"])
               for r in cp["rounds"]]
        want = [(1, 5, 3, 1), (2, 2, 4, 1), (3, 0, 2, 0)]
        t.check("A 逐轮往返一致", got == want,
                "" if got == want else f"{got} != {want}")
        t.check("A note 往返", cp["rounds"][0].get("note") == "首修",
                repr(cp["rounds"][0].get("note")))
        t.check("A verdict converged", cp["verdict"] == "converged", cp["verdict"])
        t.check("A final_residual", cp["final_residual"] == 0, str(cp["final_residual"]))
        t.check("A 汇总 Σfixed=9", cp["total_fixed"] == 9, str(cp["total_fixed"]))
        t.check("A 判据记录 stall_rounds=2",
                rep["criteria"]["stall_rounds"] == 2, str(rep["criteria"]))
        t.check("A summary diverging=0", rep["summary"]["diverging"] == 0,
                str(rep["summary"]))

        p = report(data, "--format", "md", "--stall-rounds", 2)
        t.check("A report md exit 0", p.returncode == 0, p.stderr)
        for needle in ("## cp11", "| round | residual | fixed | new_failures |",
                       "| 3 | 0 | 2 | 0 |", "converged", "首修"):
            t.check(f"A md 含 {needle!r}", needle in p.stdout)


# ---------------------------------------------------------------- B append-only

def _case_append_only(t: T):
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "conv.jsonl"
        p1 = log(data, "cp11", 1, 5, 3, 0)
        b1 = data.read_bytes()
        p2 = log(data, "cp11", 2, 2, 3, 0)
        b2 = data.read_bytes()
        p3 = log(data, "cp12", 1, 9, 1, 4)
        b3 = data.read_bytes()
        t.check("B 每次调用 exit 0",
                p1.returncode == p2.returncode == p3.returncode == 0)
        t.check("B b1 是 b2 前缀", b2.startswith(b1))
        t.check("B b2 是 b3 前缀", b3.startswith(b2))
        lines1 = b1.decode("utf-8").splitlines()
        lines3 = b3.decode("utf-8").splitlines()
        t.check("B 既有行逐字未改", lines3[:len(lines1)] == lines1)
        t.check("B 只增不改（3 行）", len(lines3) == 3, str(len(lines3)))


# ---------------------------------------------------------------- C 三态

def _case_states(t: T):
    cases = [
        ("C1", [5, 2, 0], "converged", 0),
        ("C2", [3, 3, 4], "diverging", 3),   # 有 diverging → report exit 3
        ("C3", [5, 2], "in_progress", 0),
        ("C4", [5, 2, 2], "in_progress", 0),
    ]
    for tag, residuals, want_verdict, want_exit in cases:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "conv.jsonl"
            _series(t, data, "cp11", residuals)
            p = report(data, "--stall-rounds", 2)
            rep = json.loads(p.stdout)
            verdict = rep["checkpoints"][0]["verdict"]
            t.check(f"{tag} verdict={want_verdict}", verdict == want_verdict, verdict)
            t.check(f"{tag} report exit={want_exit}", p.returncode == want_exit,
                    f"rc={p.returncode} stderr={p.stderr}")
            t.check(f"{tag} stall_rounds 记录=2",
                    rep["criteria"]["stall_rounds"] == 2, str(rep["criteria"]))


# ---------------------------------------------------------------- D 判据不硬编码

def _case_no_hardcode(t: T):
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "conv.jsonl"
        _series(t, data, "cp11", [3, 3, 4])
        p = report(data)                                   # 不传 --stall-rounds
        t.check("D 不传判据 exit 0", p.returncode == 0, f"rc={p.returncode}")
        rep = json.loads(p.stdout)
        cp = rep["checkpoints"][0]
        t.check("D 不判 diverging", cp["verdict"] == "in_progress", cp["verdict"])
        t.check("D criteria.stall_rounds=null",
                rep["criteria"]["stall_rounds"] is None, str(rep["criteria"]))
        t.check("D 明示判据未启用", "未启用" in rep["criteria"]["diverging"],
                rep["criteria"]["diverging"])
        # residual=0 的 converged 判定不依赖外部阈（结构性条件），无 stall_rounds 也可判
        with tempfile.TemporaryDirectory() as td2:
            data2 = Path(td2) / "conv.jsonl"
            _series(t, data2, "cp11", [1, 0])
            p2 = report(data2)
            rep2 = json.loads(p2.stdout)
            t.check("D converged 不依赖 stall_rounds",
                    rep2["checkpoints"][0]["verdict"] == "converged",
                    rep2["checkpoints"][0]["verdict"])


# ---------------------------------------------------------------- E 同轮重记拒绝

def _case_duplicate(t: T):
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "conv.jsonl"
        log(data, "cp11", 1, 5, 3, 0)
        before = data.read_bytes()
        p = log(data, "cp11", 1, 4, 2, 1)                  # 同 (cp, round) 再记
        t.check("E 重复轮 exit 2", p.returncode == 2, f"rc={p.returncode} {p.stderr}")
        t.check("E 字节不变", data.read_bytes() == before)
        t.check("E stderr 说明原因", "append-only" in p.stderr, p.stderr)


# ---------------------------------------------------------------- F 过滤

def _case_filter(t: T):
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "conv.jsonl"
        _series(t, data, "cp11", [5, 0])
        _series(t, data, "cp12", [9, 7])
        p = report(data, "--cp-id", "cp12", "--stall-rounds", 2)
        rep = json.loads(p.stdout)
        t.check("F 只含 cp12",
                [c["cp_id"] for c in rep["checkpoints"]] == ["cp12"],
                str([c["cp_id"] for c in rep["checkpoints"]]))
        t.check("F cp12 verdict in_progress",
                rep["checkpoints"][0]["verdict"] == "in_progress",
                rep["checkpoints"][0]["verdict"])
        p = report(data, "--cp-id", "cp99")
        t.check("F 未知 cp exit 2", p.returncode == 2, f"rc={p.returncode}")
        # cp_id 归一（同 src/cost/ledger.py 口径：strip().lower + cp1..cp12 词表）
        with tempfile.TemporaryDirectory() as td3:
            data3 = Path(td3) / "conv.jsonl"
            p3 = log(data3, "CP11", 1, 3, 2, 0)
            t.check("F 大写 CP11 接受", p3.returncode == 0, p3.stderr)
            rec = json.loads(data3.read_text(encoding="utf-8").splitlines()[0])
            t.check("F 归一存储为 cp11", rec["cp_id"] == "cp11", rec["cp_id"])
            p3 = report(data3, "--cp-id", "cp11")
            t.check("F 归一后可查", p3.returncode == 0, p3.stderr)


# ---------------------------------------------------------------- G exit 2 通道

def _case_exit2(t: T):
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "conv.jsonl"
        t.check("G residual<0 exit 2",
                log(data, "cp11", 1, -1, 0, 0).returncode == 2)
        t.check("G round=0 exit 2",
                log(data, "cp11", 0, 1, 0, 0).returncode == 2)
        t.check("G fixed<0 exit 2",
                log(data, "cp11", 1, 1, -2, 0).returncode == 2)
        t.check("G new-failures<0 exit 2",
                log(data, "cp11", 1, 1, 0, -3).returncode == 2)
        t.check("G stall-rounds=0 exit 2",
                report(data, "--stall-rounds", 0).returncode == 2)
        t.check("G cp99 须 cp1..cp12 exit 2",
                log(data, "cp99", 1, 1, 0, 0).returncode == 2)
        t.check("G 数据文件缺失 report exit 2",
                report(Path(td) / "nope.jsonl").returncode == 2)
        data.write_text("")                                # 空文件存在
        t.check("G 空文件 report exit 2", report(data).returncode == 2)
        data.write_text(json.dumps({"cp_id": "cp11", "round": 1,
                                    "residual_count": 5, "fixed_count": 3,
                                    "new_failures": 0}) + "\n"
                        + json.dumps({"cp_id": "cp11", "round": 1,
                                      "residual_count": 4, "fixed_count": 1,
                                      "new_failures": 0}) + "\n")
        t.check("G 手工注入重复轮 report exit 2", report(data).returncode == 2)
        data.write_text("not-json\n")
        t.check("G 损坏行 report exit 2", report(data).returncode == 2)


# ---------------------------------------------------------------- runner

def _t():
    return T()


def test_roundtrip():
    t = _t(); _case_roundtrip(t); assert not t.fails, t.fails

def test_append_only():
    t = _t(); _case_append_only(t); assert not t.fails, t.fails

def test_states():
    t = _t(); _case_states(t); assert not t.fails, t.fails

def test_no_hardcode():
    t = _t(); _case_no_hardcode(t); assert not t.fails, t.fails

def test_duplicate():
    t = _t(); _case_duplicate(t); assert not t.fails, t.fails

def test_filter():
    t = _t(); _case_filter(t); assert not t.fails, t.fails

def test_exit2():
    t = _t(); _case_exit2(t); assert not t.fails, t.fails


def main() -> int:
    print(f"convergence 自测（tool={TOOL}）")
    t = _t()
    _case_roundtrip(t)
    _case_append_only(t)
    _case_states(t)
    _case_no_hardcode(t)
    _case_duplicate(t)
    _case_filter(t)
    _case_exit2(t)
    n = len(t.fails)
    print(f"结论：{'ALL PASS' if n == 0 else f'{n} FAIL'}（{n} 条失败）")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
