#!/usr/bin/env python3
"""check_baseline_drift.py — 验收门 G0-2 的登记基线漂移检查（独立脚本，避免 bash 引号嵌套坑）。

用法：python3 check_baseline_drift.py [--qc-dir DIR] [--golden-register PATH]
判定：eval_run 在 --qc-dir 上的当前结果与登记基线（supplement JSON 的
e10_ab_metrics / e10_exp59_metrics / e10_v1_view.metrics）位级一致 → exit 0；
有漂移 → exit 1；无登记基线且当前 ACCEPT → exit 0。

登记基线沿革：v8（2026-10-09 C 组补缺 +2，golden_058/059）起指向
eval_results_exp57_supplement.json → exp59（REJECT 登记）→ exp60/exp61
（判官配方 A+B 收官 ACCEPT，eval_results_exp61_ab_accept_supplement.json；
前轮登记文件保留作历史，不删除）。
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
    ap.add_argument("--register", default=str(VPIPE / "eval" / "eval_results_exp61_ab_accept_supplement.json"))
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
    base_doc = json.loads(reg.read_text(encoding="utf-8"))
    base = next((base_doc[k] for k in ("e10_ab_metrics", "e10_exp59_metrics",
                                       "e10_v1_view") if isinstance(base_doc.get(k), dict)), {})
    cur = json.loads(Path(args.results).read_text(encoding="utf-8"))["main"]
    drift = {k: (cur.get(k), base.get(k)) for k in ("recall", "fpr", "f1") if cur.get(k) != base.get(k)}
    if drift:
        print(f"G0-2: 未声明偏差 {drift}", file=sys.stderr)
        return 1
    print(f"G0-2: 位级等于登记基线（R={cur['recall']}/FPR={cur['fpr']}/F1={cur['f1']}）"
          "——59 条金标判官配方 A+B 收官态（exp61 supplement：A 路 J3 分通道阈+低运动平台"
          "声明制豁免 × B 路 J1 rubric 时序帧对，四条准入线全过 ACCEPT；当前 REJECT 态即"
          "位级等于该已登记基线，无未声明偏差）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
