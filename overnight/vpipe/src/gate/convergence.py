#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convergence.py — CP 级修复收敛曲线（vpipe v4，M3-W11）。

规范出处：
- 白皮书 research/2026-10-08/工业化视频流水线-白皮书.md:381（M3 关键交付物 2）：
  每 CP 的 residual_count / fixed_count / new_failures 逐轮记录，让「修复循环
  是否收敛」成为可测数字。
- TASK_v4.md:301（M3-W11 验收行）：DramaClaw-style convergence_log.py 在仓，
  每 CP residual_count/fixed_count/new_failures 逐轮记录。
- 思想来源 research/2026-10-08/dramaclaw-deepdive.md:503（A2 借鉴项）：
  DramaClaw verification/convergence_log.py:L29-L61 的
  (episode, phase, round_num, residual_count, fixed_count, new_failures)
  五元组；本工具把 episode/phase 换成 owner 的 cp_id（工序层而非剧集层）。

收敛判据（三态，逐 CP 独立判定；判定对象 = 该 CP 按轮号升序的 residual 序列）：
  converged   末轮（最新一轮）residual_count == 0 —— 残余缺陷清零。
              这是结构性条件（零缺陷），不是可调阈，无需外部传参。
  diverging   最后 stall_rounds 个「轮间差」（residual[i] - residual[i-1]）
              全部 >= 0，即连续 stall_rounds 轮 residual 不降（含不升的横盘
              与回升）。stall_rounds 必须经 --stall-rounds 显式传入。
              需要至少 stall_rounds+1 轮数据，不足则本判据不触发。
  in_progress 其余情形：仍在下降、或轮数不足以判定横盘。

阈值不硬编码（红线）：stall_rounds 不写死在代码里。截至 thresholds.yaml v5
（2026-10-08）无 convergence 段；按其头部「修改规程」加键 = 改判定行为，须
主控批准并重跑 eval，故本版不走 yaml，用 CLI 显式传参并在每次 report 输出里
原样记录（criteria.stall_rounds）。--stall-rounds 未传入时 diverging 判据
不启用（verdict 只会在 converged/in_progress 二态，report 里明示「判据未
启用」）。主控若要收编进 thresholds.yaml，建议新键 convergence.stall_rounds，
按修改规程批准后本工具再加读取（在那之前无第二套数值）。

存储：append-only JSONL，缺省 overnight/vpipe/out/convergence.jsonl（与
成本台账 out/cost/ledger.jsonl 同级运行域 out/，本卡 M3-W11 指定位置）。
只追加、不改写不删除；同 (cp_id, round) 只许记一笔（重复 = 调用方 bug，
拒绝追加，防曲线出叉）。存储约定沿用 src/cost/ledger.py（M2-W9 交付物，
本任务进行中落仓 2026-10-08 23:34，实测已就绪）：append-only 只许整行追加、
坏行/字段非法读时即拒（exit 2）、cp_id 词表 cp1..cp12（白皮书 §3 十二检查点
谱，strip().lower 归一后须匹配 ^cp([1-9]|1[0-2])$，同 ledger.py CP_ID_RE）、
0/2/3 退出码口径。文件位置不并入 ledger.jsonl——收敛曲线是缺陷维台账，
成本台账是费用维，各自单文件（本卡指定 out/convergence.jsonl）。

用法（仓根或 overnight/vpipe/ 下均可；--data 缺省自动定位到 vpipe/out/）：
    python3 src/gate/convergence.py log --cp-id cp11 --round 1 \
        --residual 5 --fixed 3 --new-failures 1 [--note "..."] [--data FILE]
    python3 src/gate/convergence.py report [--cp-id cp11] \
        [--format json|md] [--stall-rounds N] [--data FILE]

退出码：log：0=已追加；2=用法/参数非法/文件不可写/(cp_id,round) 重复。
report：0=正常（无论 verdict 是什么）；3=任一 CP 判为 diverging（给外部
编排器的非零信号，沿 DramaClaw run_gate「有 failed → exit 3」的口径，
dramaclaw-deepdive.md:504 A3 行）；2=数据文件缺失/不可读/行损坏/同
(cp_id,round) 出现多笔（宁可 exit 2 不带病出曲线）。

依赖：纯标准库，零外部模型，零第三方包。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent            # src/gate/
VPIPE = HERE.parent.parent                        # overnight/vpipe/
DEFAULT_DATA = VPIPE / "out" / "convergence.jsonl"

SCHEMA_VERSION = 1                                # 记录结构版本（convergence_log.v1），非判定数值
# 与 src/cost/ledger.py 同一词表：cp1..cp12（白皮书 §3 十二检查点谱）
CP_ID_RE = re.compile(r"^cp([1-9]|1[0-2])$")

VERDICT_CONVERGED = "converged"
VERDICT_DIVERGING = "diverging"
VERDICT_IN_PROGRESS = "in_progress"


# ---------------------------------------------------------------- records

def make_record(cp_id: str, round_num: int, residual: int, fixed: int,
                new_failures: int, note: str | None) -> dict:
    """一条逐轮记录（字段名沿白皮书 :381 的 residual_count/fixed_count/new_failures）。"""
    rec = {
        "schema_version": SCHEMA_VERSION,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cp_id": cp_id,
        "round": round_num,
        "residual_count": residual,
        "fixed_count": fixed,
        "new_failures": new_failures,
    }
    if note:
        rec["note"] = note
    return rec


def load_curves(data_file: Path) -> dict:
    """读全量 JSONL → {cp_id: [按轮号升序的记录]}。

    容错口径（宁可 exit 2 不带病出曲线）：空行跳过；非 JSON / 非 mapping /
    缺必备键 / 类型不对 / 同 (cp_id, round) 多笔 → ValueError（调用方转 exit 2）。
    """
    if not data_file.exists():
        raise ValueError(f"数据文件不存在：{data_file}")
    curves: dict[str, list[dict]] = {}
    seen: set[tuple[str, int]] = set()
    with data_file.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{data_file}:{lineno} 非 JSON 行：{e}") from e
            if not isinstance(rec, dict):
                raise ValueError(f"{data_file}:{lineno} 记录不是 JSON mapping")
            for key in ("cp_id", "round", "residual_count", "fixed_count", "new_failures"):
                if key not in rec:
                    raise ValueError(f"{data_file}:{lineno} 缺必备键 {key}")
            if not CP_ID_RE.match(str(rec.get("cp_id", ""))):
                raise ValueError(f"{data_file}:{lineno} cp_id 非法："
                                 f"{rec.get('cp_id')!r}（须 cp1..cp12）")
            if not isinstance(rec["round"], int) or rec["round"] < 1:
                raise ValueError(f"{data_file}:{lineno} round 非法：{rec['round']!r}")
            for key in ("residual_count", "fixed_count", "new_failures"):
                if not isinstance(rec[key], int) or rec[key] < 0:
                    raise ValueError(f"{data_file}:{lineno} {key} 非法：{rec[key]!r}")
            key2 = (rec["cp_id"], rec["round"])
            if key2 in seen:
                raise ValueError(f"{data_file}:{lineno} (cp_id, round)={key2} 重复——"
                                 "同一轮只许记一笔，曲线出叉即数据损坏")
            seen.add(key2)
            curves.setdefault(rec["cp_id"], []).append(rec)
    for cp_id in curves:
        curves[cp_id].sort(key=lambda r: r["round"])
    return curves


# ---------------------------------------------------------------- verdict

def judge(residuals: list[int], stall_rounds: int | None) -> tuple[str, str]:
    """三态收敛判定。返回 (verdict, reason)。判据见模块 docstring。"""
    if not residuals:
        raise ValueError("无轮次数据，无法判定")
    final = residuals[-1]
    if final == 0:
        return VERDICT_CONVERGED, f"末轮 residual_count=0（共 {len(residuals)} 轮）"
    if stall_rounds is None:
        return (VERDICT_IN_PROGRESS,
                f"末轮 residual_count={final}；diverging 判据未启用"
                "（--stall-rounds 未传入，阈值不硬编码）")
    if len(residuals) < stall_rounds + 1:
        return (VERDICT_IN_PROGRESS,
                f"末轮 residual_count={final}；仅 {len(residuals)} 轮，"
                f"不足 stall_rounds+1={stall_rounds + 1} 轮，横盘判据未触发")
    deltas = [b - a for a, b in zip(residuals, residuals[1:])]
    tail = deltas[-stall_rounds:]
    if all(d >= 0 for d in tail):
        return (VERDICT_DIVERGING,
                f"末轮 residual_count={final}；最后 {stall_rounds} 轮轮间差 "
                f"{tail} 全部 >=0（连续 {stall_rounds} 轮 residual 不降）")
    return (VERDICT_IN_PROGRESS,
            f"末轮 residual_count={final}；最后 {stall_rounds} 轮轮间差 "
            f"{tail} 存在下降，仍在收敛")


def summarize(cp_id: str, rounds: list[dict], stall_rounds: int | None) -> dict:
    residuals = [r["residual_count"] for r in rounds]
    verdict, reason = judge(residuals, stall_rounds)
    return {
        "cp_id": cp_id,
        "rounds_logged": len(rounds),
        "rounds": [{k: r[k] for k in
                    ("round", "residual_count", "fixed_count", "new_failures",
                     "ts", "note") if k in r} for r in rounds],
        "final_residual": residuals[-1],
        "total_fixed": sum(r["fixed_count"] for r in rounds),
        "total_new_failures": sum(r["new_failures"] for r in rounds),
        "verdict": verdict,
        "reason": reason,
    }


# ---------------------------------------------------------------- CLI cmd

def cmd_log(args: argparse.Namespace) -> int:
    data_file: Path = getattr(args, "data", DEFAULT_DATA)
    cp_norm = args.cp_id.strip().lower()             # 归一口径同 src/cost/ledger.py
    if not CP_ID_RE.match(cp_norm):
        print(f"[convergence] 非法 --cp-id：{args.cp_id!r}（归一后须 cp1..cp12，"
              f"白皮书 §3 十二检查点谱）", file=sys.stderr)
        return 2

    rec = make_record(cp_norm, args.round, args.residual, args.fixed,
                      args.new_failures, args.note)

    if data_file.exists():
        # 同 (cp_id, round) 只许一笔：追加前扫描既有行（append-only 不改写既有字节）
        with data_file.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    old = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[convergence] {data_file}:{lineno} 非 JSON 行：{e}",
                          file=sys.stderr)
                    return 2
                if isinstance(old, dict) and old.get("cp_id") == rec["cp_id"] \
                        and old.get("round") == rec["round"]:
                    print(f"[convergence] 拒绝追加：{rec['cp_id']} 第 {rec['round']} 轮"
                          f"已记录于 {data_file}:{lineno}（append-only，同轮不重记）",
                          file=sys.stderr)
                    return 2

    data_file.parent.mkdir(parents=True, exist_ok=True)
    with data_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({"appended": True, "data_file": str(data_file), "record": rec},
                     ensure_ascii=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    data_file: Path = getattr(args, "data", DEFAULT_DATA)
    try:
        curves = load_curves(data_file)
    except ValueError as e:
        print(f"[convergence] {e}", file=sys.stderr)
        return 2
    if not curves:
        print(f"[convergence] {data_file} 无任何记录，不出空曲线", file=sys.stderr)
        return 2
    if args.cp_id is not None:
        curves = {k: v for k, v in curves.items() if k == args.cp_id}
        if not curves:
            print(f"[convergence] 数据文件中无 cp_id={args.cp_id} 的记录", file=sys.stderr)
            return 2

    cps = [summarize(cp_id, rounds, args.stall_rounds)
           for cp_id, rounds in sorted(curves.items())]
    criteria = {
        "converged": "末轮 residual_count == 0",
        "diverging": (f"最后 {args.stall_rounds} 轮轮间差全部 >=0"
                      if args.stall_rounds is not None else
                      "判据未启用（--stall-rounds 未传入，阈值不硬编码）"),
        "stall_rounds": args.stall_rounds,
    }
    n_diverging = sum(1 for cp in cps if cp["verdict"] == VERDICT_DIVERGING)

    if args.format == "json":
        print(json.dumps({
            "tool": "convergence.py",
            "data_file": str(data_file),
            "criteria": criteria,
            "checkpoints": cps,
            "summary": {"checkpoints": len(cps), "diverging": n_diverging},
        }, ensure_ascii=False, indent=2))
    else:
        print(render_md(data_file, criteria, cps, n_diverging))

    return 3 if n_diverging else 0


def render_md(data_file: Path, criteria: dict, cps: list[dict], n_diverging: int) -> str:
    lines = [
        "# CP 修复收敛曲线报告（convergence.py）",
        "",
        f"- 数据文件：`{data_file}`（append-only JSONL）",
        f"- 生成时刻：{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- 收敛判据：converged = {criteria['converged']}；"
        f"diverging = {criteria['diverging']}",
        f"- 汇总：{len(cps)} 个 CP，diverging {n_diverging} 个",
    ]
    for cp in cps:
        lines += [
            "",
            f"## {cp['cp_id']} — {cp['verdict']}",
            "",
            cp["reason"],
            "",
            "| round | residual | fixed | new_failures | note |",
            "|---:|---:|---:|---:|---|",
        ]
        for r in cp["rounds"]:
            note = (r.get("note") or "").replace("|", "\\|")
            lines.append(f"| {r['round']} | {r['residual_count']} | "
                         f"{r['fixed_count']} | {r['new_failures']} | {note} |")
        lines.append("")
        lines.append(f"rounds_logged={cp['rounds_logged']}  "
                     f"final_residual={cp['final_residual']}  "
                     f"Σfixed={cp['total_fixed']}  "
                     f"Σnew_failures={cp['total_new_failures']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- argparse

def build_parser() -> argparse.ArgumentParser:
    # --data 挂共享 parent：子命令前/后均可写（argparse 子解析器不继承主解析器
    # 在子命令名之后出现的旗标）；SUPPRESS 防止未提供时以 None 覆盖主解析器取值
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", type=Path, default=argparse.SUPPRESS,
                        help=f"append-only JSONL 数据文件（缺省 {DEFAULT_DATA}）")
    p = argparse.ArgumentParser(
        prog="convergence.py", parents=[common],
        description="CP 级修复收敛曲线：append-only 逐轮记录 + 三态收敛判定"
                    "（判据见模块 docstring；stall_rounds 经 --stall-rounds 显式传入）")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_log = sub.add_parser("log", parents=[common], help="追加一条逐轮记录")
    p_log.add_argument("--cp-id", required=True, help="工序 ID，如 cp11")
    p_log.add_argument("--round", type=int, required=True, help="修复轮次（>=1）")
    p_log.add_argument("--residual", type=int, required=True, help="本轮残余缺陷数（>=0）")
    p_log.add_argument("--fixed", type=int, required=True, help="本轮修复数（>=0）")
    p_log.add_argument("--new-failures", type=int, required=True,
                       help="本轮新引入失败数（>=0）")
    p_log.add_argument("--note", default=None, help="备注（可选）")

    p_rep = sub.add_parser("report", parents=[common], help="出收敛曲线报告（json|md）")
    p_rep.add_argument("--cp-id", default=None, help="只看一个 CP（缺省全部）")
    p_rep.add_argument("--format", choices=["json", "md"], default="json")
    p_rep.add_argument("--stall-rounds", type=int, default=None,
                       help="diverging 判据：连续 N 轮 residual 不降（须显式传入，"
                            "不硬编码；未传入则该判据不启用）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "log":
        for name in ("round", "residual", "fixed", "new_failures"):
            if getattr(args, name) < (1 if name == "round" else 0):
                print(f"[convergence] --{name.replace('_', '-')} 必须为 "
                      f"{'>=1' if name == 'round' else '>=0'}，得到 {getattr(args, name)}",
                      file=sys.stderr)
                return 2
        return cmd_log(args)
    if args.cmd == "report":
        if args.stall_rounds is not None and args.stall_rounds < 1:
            print(f"[convergence] --stall-rounds 必须 >=1，得到 {args.stall_rounds}",
                  file=sys.stderr)
            return 2
        return cmd_report(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
