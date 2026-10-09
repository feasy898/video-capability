#!/usr/bin/env python3
"""check_baseline_drift.py — 验收门 G0-2 的登记基线漂移检查（独立脚本，避免 bash 引号嵌套坑）。

用法：python3 check_baseline_drift.py [--qc-dir DIR] [--golden-register PATH]
判定：eval_run 在 --qc-dir 上的当前结果与登记基线（supplement JSON 的
e10_exp57_metrics）位级一致 → exit 0；有漂移 → exit 1；无登记基线且当前 ACCEPT → exit 0。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VPIPE = HERE.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qc-dir", default=str(VPIPE / "out" / "qc_reports_v3post"))
    ap.add_argument("--register", default=str(VPIPE / "eval" / "eval_results_exp57_supplement.json"))
    ap.add_argument("--results", default=str(VPIPE / "eval" / "eval_results.json"))
    args = ap.parse_args()

    # 1. 跑 eval_run（结果写 --results）
    r = subprocess.run([sys.executable, str(VPIPE / "eval" / "eval_run.py"),
                        "--qc-dir", args.qc_dir, "--out", args.results],
                       capture_output=True, text=True)
    if "验收结论: ACCEPT" in r.stdout:
        print("G0-2: ACCEPT（未扩样或扩样后仍达标）")
        return 0

    # 2. REJECT：与登记基线比对（零未声明偏差纪律）
    reg = Path(args.register)
    if not reg.is_file():
        print("G0-2: REJECT 且无登记基线文件——按未登记偏差处理", file=sys.stderr)
        return 1
    base = json.loads(reg.read_text(encoding="utf-8"))["e10_exp57_metrics"]
    cur = json.loads(Path(args.results).read_text(encoding="utf-8"))["main"]
    drift = {k: (cur.get(k), base.get(k)) for k in ("recall", "fpr", "f1") if cur.get(k) != base.get(k)}
    if drift:
        print(f"G0-2: 未声明偏差 {drift}", file=sys.stderr)
        return 1
    print(f"G0-2: 位级等于登记基线（R={cur['recall']}/FPR={cur['fpr']}/F1={cur['f1']}）"
          "——57 条扩样金标 REJECT 为已登记诚实状态，质量门未达已上抛 owner")
    return 0


if __name__ == "__main__":
    sys.exit(main())
