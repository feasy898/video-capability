#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_regression.py — CP11 合成层像素级回归驱动（tests/fixtures/checkpoints/cp11_regression/）。

TASK_v4 M1-W5 验收：3 个用例同输入各跑两遍（synth.py），6 次全部 exit 0 且
master.mp4 md5 两两一致（比对载体 = md5.txt 逐字节 diff，TASK_v4 §4 M1 验收
脚本口径）；case 声明 cp11 块的，另跑 validate_cp11.py --probe 判 pass；
汇总写 evidence/synth-regression-20261008.json（用例×2 遍 md5 对照表 + ffmpeg
版本）。红线：素材全部 ffmpeg lavfi 程序生成，零模型、零下载；mp4 产物落
out/（.gitignore，不入 git）。

用法（仓根或本目录）：
    python3 run_regression.py [--out-dir DIR] [--evidence PATH] [--synth PATH]

退出码：0=全部通过；1=任一用例二遍 md5 不一致 / 合成失败 / 门禁 fail（stdout
逐项列因，如实报告差异定位——哪个文件、两遍 md5 各是什么）；2=环境错误
（synth/validator 缺失、ffmpeg 不在 PATH）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../checkpoints/cp11_regression
VPIPE = HERE.parents[3]                          # .../overnight/vpipe
REPO = HERE.parents[5]                           # 仓根（evidence/ 所在：cp11_regression
                                                 #  ↑checkpoints↑fixtures↑tests↑vpipe↑overnight↑仓根）

SYNTH_DEFAULT = VPIPE / "src" / "gate" / "synth.py"
VALIDATE_DEFAULT = VPIPE / "src" / "gate" / "validate_cp11.py"
EVIDENCE_DEFAULT = REPO / "evidence" / "synth-regression-20261008.json"
OUTDIR_DEFAULT = HERE / "out"

EVIDENCE_TITLE = ("TASK_v4 M1-W5：CP11 合成层像素级回归 ≥3 用例"
                  "（同输入二遍 md5 一致，白皮书 §3 CP11 + §4 T0）")


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _tool_version_line(binname: str) -> str:
    try:
        out = subprocess.run([binname, "-version"], capture_output=True,
                             text=True, timeout=30, check=True)
        return (out.stdout.splitlines() or [""])[0].strip() or "unknown"
    except Exception:                            # noqa: BLE001 —— 留痕 only
        return "unknown"


def _rel(p: Path) -> str:
    """尽量给仓根相对路径（可移植）；解析不出就给绝对路径（诚实）。"""
    try:
        return str(p.resolve().relative_to(REPO))
    except ValueError:
        return str(p.resolve())


def run_case(case_path: Path, synth: Path, out_dir: Path, runs: int = 2) -> dict:
    """单用例 ×N 遍：synth → exit 0 + md5.txt 逐字节一致 + master.mp4 md5 一致。"""
    rec: dict = {"case": case_path.name, "case_path": _rel(case_path),
                 "case_sha256": _sha256(case_path), "runs": [], "ok": True}
    for i in range(1, runs + 1):
        odir = out_dir / case_path.stem / f"run{i}"
        proc = subprocess.run(
            [sys.executable, str(synth), "--case", str(case_path), "--out", str(odir)],
            capture_output=True, text=True, timeout=1800)
        entry = {"run": i, "out_dir": _rel(odir), "exit": proc.returncode}
        try:
            summary = json.loads(proc.stdout)
            entry["master_md5"] = summary.get("master_md5")
            entry["master_bytes"] = summary.get("master_bytes")
        except json.JSONDecodeError:
            summary = {}
        if proc.returncode != 0:
            entry["error"] = (proc.stderr.strip() or proc.stdout.strip())[-600:]
            rec["ok"] = False
        md5f = odir / "md5.txt"
        if md5f.is_file():
            entry["md5_txt"] = md5f.read_text(encoding="utf-8")
        else:
            entry["md5_txt"] = None
            if proc.returncode == 0:
                rec["ok"] = False
                entry["error"] = "exit 0 但 md5.txt 缺失（合成器契约违背）"
        rec["runs"].append(entry)

    md5s = [r.get("master_md5") for r in rec["runs"]]
    rec["master_md5_all_equal"] = (len(set(md5s)) == 1 and None not in md5s)
    txts = [r.get("md5_txt") for r in rec["runs"]]
    rec["md5_txt_identical"] = (len(set(txts)) == 1 and txts[0] is not None)
    if rec["ok"] and not (rec["master_md5_all_equal"] and rec["md5_txt_identical"]):
        rec["ok"] = False
        rec["difference"] = (
            "md5 不一致（同输入两遍必须逐字节一致）："
            + "; ".join(f"run{r['run']} master_md5={r.get('master_md5')}" for r in rec["runs"])
            + f"; md5.txt run1={txts[0]!r} vs run2={txts[1]!r}"
            if len(txts) == 2 else "md5.txt 缺失或遍数不足")

    # ---- CP11 门禁挂载：case 声明 cp11 块 → validate_cp11.py --probe 判 pass ----
    c11 = json.loads(case_path.read_text(encoding="utf-8")).get("cp11")
    if c11 is None:
        rec["validator"] = {
            "applicable": False,
            "reason": ("本用例无硬切拼接缝（xfade 过渡≠硬切），CP11 known_cuts 登记铁律"
                       "与切镜数等式均针对硬切拼接语义；且校验器 known_cuts 须非空数组，"
                       "空登记册必 fail——故不产 cp11 工件、门禁不适用（合成确定性仍由"
                       "本驱动 md5 比对覆盖）。"),
        }
    else:
        rec["validator"] = {"applicable": True, "runs": []}
        for r in rec["runs"]:
            art = out_dir / case_path.stem / f"run{r['run']}" / "cp11_artifact.json"
            mp4 = out_dir / case_path.stem / f"run{r['run']}" / "master.mp4"
            v = subprocess.run(
                [sys.executable, str(VALIDATE_DEFAULT), str(art), "--probe", str(mp4)],
                capture_output=True, text=True, timeout=900)
            try:
                verdict = json.loads(v.stdout).get("verdict")
            except json.JSONDecodeError:
                verdict = None
            rec["validator"]["runs"].append(
                {"run": r["run"], "exit": v.returncode, "verdict": verdict,
                 "stderr_tail": (v.stderr.strip()[-300:] if v.returncode != 0 else "")})
            if v.returncode != 0:
                rec["ok"] = False
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CP11 合成层像素级回归驱动（M1-W5）")
    ap.add_argument("--out-dir", default=str(OUTDIR_DEFAULT),
                    help=f"产物根目录（缺省 {OUTDIR_DEFAULT}，.gitignore 不入 git）")
    ap.add_argument("--evidence", default=str(EVIDENCE_DEFAULT),
                    help=f"汇总 JSON 落点（缺省 {EVIDENCE_DEFAULT}）")
    ap.add_argument("--synth", default=str(SYNTH_DEFAULT), help="synth.py 路径")
    ap.add_argument("--runs", type=int, default=2, help="每用例遍数（验收口径=2）")
    args = ap.parse_args(argv)

    synth = Path(args.synth)
    validator = Path(VALIDATE_DEFAULT)
    for p, what in ((synth, "synth.py"), (validator, "validate_cp11.py")):
        if not p.is_file():
            print(f"ERROR: {what} 不存在: {p}", file=sys.stderr)
            return 2

    cases = sorted(HERE.glob("case*.json"))     # case1_…/case2_…/case3_…
    if len(cases) < 3:
        print(f"ERROR: 回归用例不足 3 个（实得 {len(cases)}）——M1-W5 验收口径 ≥3",
              file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[cp11_regression] {len(cases)} 用例 × {args.runs} 遍 → {out_dir}")

    results = []
    for cp in cases:
        print(f"  == {cp.name}")
        rec = run_case(cp, synth, out_dir, args.runs)
        results.append(rec)
        v = rec.get("validator") or {}
        vtxt = ("n/a（无硬切缝，门禁不适用）" if not v.get("applicable")
                else "pass" if all(r["exit"] == 0 for r in v["runs"]) else "FAIL")
        print(f"     md5 两遍一致={rec['md5_txt_identical'] and rec['master_md5_all_equal']}  "
              f"合成 exit 全 0={all(r['exit'] == 0 for r in rec['runs'])}  "
              f"validate_cp11={vtxt}  ok={rec['ok']}")

    evidence = {
        "evidence_type": "cp11_synth_pixel_regression",
        "task": EVIDENCE_TITLE,
        "spec_refs": ["白皮书 §3 CP11（合成：所有片段+字幕+音轨→成片）",
                      "白皮书 §4 T0（确定性层：像素级回归用例 ≥3）",
                      "TASK_v4 §3.1 M1-W5（3 个用例同输入同输出，md5 一致）",
                      "工程方案v3.1.md:218（合成层同参数二遍编码 md5 一致口径）"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"synth": _rel(synth), "synth_sha256": _sha256(synth),
                 "validator": _rel(validator), "validator_sha256": _sha256(validator),
                 "runs_per_case": args.runs},
        "ffmpeg": {"version": _tool_version_line("ffmpeg"),
                   "ffprobe": _tool_version_line("ffprobe")},
        "cases": results,
        "all_pass": all(r["ok"] for r in results),
    }
    ev = Path(args.evidence)
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                  encoding="utf-8")
    print(f"[cp11_regression] 汇总 → {ev}")
    print(f"[cp11_regression] all_pass={evidence['all_pass']}")
    return 0 if evidence["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
