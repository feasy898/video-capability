#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledger.py —— video-capability v4 每 CP 成本台账（M2-W9 交付物，TASK_v4 §3.1 cost 行）。

定位（白皮书 §5.4「成本记账重写」）：
    三钱包（MiniMax 积分 / Vidu 积分 / StepFun ¥）+ 本地墙钟，四套货币**不可换算**
    → 统一为每 CP 的成本台账：{cp_id, 通道, 墙钟, 币种, 金额, 折算口径}。
    折算口径显式声明；跨币种只允许同体系比较，不许给出无依据的 ¥ 汇总。

存储：append-only JSONL（repo_root/out/cost/ledger.jsonl；out/ 是运行产物域）。
    每行一条 JSON，字段（顺序固定）：
        ts                 记账时刻（UTC ISO8601）
        cp_id              cp1..cp12（白皮书 §3 十二检查点谱）
        channel            通道 id，必须存在于 contracts/v2/model_tiers.yaml 的
                           tiers[].channels[].channel_id 或 excluded_channels[].channel_id
                           （SPEC_v2 §0 纪律 4：通道枚举单点；否则拒收）
        wall_clock_s       本次调用墙钟（秒，必填）
        currency           币种 ∈ {minimax_credit, vidu_credit, stepfun_cny, local_wall_s}；
                           未核价通道（amount=null）可为 null
        amount             金额（同 currency 单位）；unverified/excluded 通道一律 null，
                           **不进任何预算基线**（白皮书 §4 成本可信度分层：未确证不许写成确定值）
        conversion_basis   折算口径（显式声明，白皮书 §5.4 红线；不许空）
        episode_id         集 id（可空）
        note               备注（可空）
        thresholds_sha256  记账时 eval/thresholds.yaml 的 sha256（与 src/gate、eval_run 同口径）
        cost_confidence    记账时该通道在 tier 表的档位快照 measured/reported/unverified
                           （append-only 审计口径：tier 表事后改档不回写历史行）
        channel_excluded   该通道是否属 excluded_channels（true=出局通道，恒不进预算基线）

币种绑定：四套货币各自绑定 provider 体系（minimax_credit↔minimax、vidu_credit↔vidu、
    stepfun_cny↔stepfun、local_wall_s↔local），跨体系混填即拒收（exit 2）——
    「两钱包不可直接换算，只能取同体系内比较」（白皮书 §5.4 / model_tiers.yaml
    api_vidu_avatar notes）。kling/volcengine 等未核价 provider 无默认币种。

report（同 currency 求和；跨币种只列分布不给总额，违反即 exit 3）：
    1. 每 CP 墙钟合计        2. 每通道调用次数
    3. 每 episode MiniMax 积分合计（同币种内）
    4. 单集成本 vs 标准档对照行（TASK_v4 §4 M2 验收④）：
       上限 = checkpoints.cost.episode_budget.standard_episode_shots(24)
            × checkpoints.cp9.gate.credit_cap_per_shot(280)
            × checkpoints.cost.episode_budget.budget_multiplier(1.2)
       —— 三键乘积实算自 thresholds.yaml（判定数值单点，SPEC_v2 §0 纪律 3；
       主控 2026-10-08 批准新增，不落总额字面量），代码内零硬编码。

用法：
    python3 src/cost/ledger.py record --cp-id cp7 --channel local_ltx_2b \
        --wall-clock-s 76.7 [--currency local_wall_s --amount 76.7] \
        [--episode-id X] [--note "..."] [--conversion-basis "..."]
    python3 src/cost/ledger.py report [--episode-id X] [--format json|md]
    路径覆盖（测试/异地运行用）：--ledger / --tiers / --thresholds

退出码（沿 vpipe 惯例：0=成 / 2=读取或校验拒收 / 3=预算·跨币种红线）：
    0  成功
    2  用法/输入/数据错误：未知通道、币种词表外、unverified 带 amount、
       台账缺失或行损坏（append-only 只许整行追加）
    3  跨币种汇总企图（CrossCurrencySumError；report 永不主动跨币种求和，
       --emit-grand-total 隐藏 tripwire 位是唯一触发路径，供红线回归测试）

单测：tests/test_cost_ledger.py（标准库 unittest，零第三方；实跑全过）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import yaml

# ---------------------------------------------------------------------
# 路径（repo_root = overnight/vpipe/src/cost/ 的第 4 层父目录）
# ---------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LEDGER = _REPO_ROOT / "out" / "cost" / "ledger.jsonl"
DEFAULT_TIERS = Path(__file__).resolve().parents[2] / "contracts" / "v2" / "model_tiers.yaml"
DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[2] / "eval" / "thresholds.yaml"

# ---------------------------------------------------------------------
# 四套货币词表（白皮书 §5.4：不可换算；跨币种禁止汇总）
# ---------------------------------------------------------------------
CURRENCIES = ("minimax_credit", "vidu_credit", "stepfun_cny", "local_wall_s")

# 币种↔provider 体系绑定（同体系内才许比较/求和）
PROVIDER_CURRENCY = {
    "local": "local_wall_s",
    "minimax": "minimax_credit",
    "vidu": "vidu_credit",
    "stepfun": "stepfun_cny",
}
# kling / volcengine 等未核价 provider 不进映射：须显式 --currency，
# 且这些通道在 tier 表均 unverified/null 价 → amount 恒 null。

# 折算口径默认值（显式声明红线：每行必有非空 conversion_basis）
DEFAULT_CONVERSION_BASIS = {
    "local_wall_s": "amount=wall_clock_s 原值直记（本地墙钟即货币，零折算）",
    "minimax_credit": "钱包实扣直记（MiniMax 积分体系内，零折算）",
    "vidu_credit": "任务 credits 实读直记（Vidu 积分体系内，零折算）",
    "stepfun_cny": "账单实扣直记（StepFun ¥ 体系内，零折算）",
}
NO_CURRENCY_BASIS = "amount=null（未核价/出局通道，无可折算金额；币种待核价后回填）"

CP_ID_RE = re.compile(r"^cp([1-9]|1[0-2])$")

# 每行固定键序（append-only 审计可读性）
ENTRY_KEYS = (
    "ts", "cp_id", "channel", "wall_clock_s", "currency", "amount",
    "conversion_basis", "episode_id", "note", "thresholds_sha256",
    "cost_confidence", "channel_excluded",
)


class LedgerError(Exception):
    """拒收级错误。exit_code=2（读取/校验拒收）。"""

    exit_code = 2


class CrossCurrencySumError(LedgerError):
    """跨币种汇总企图——红线（白皮书 §5.4：跨币种禁止汇总）。exit_code=3。"""

    exit_code = 3


# ---------------------------------------------------------------------
# 通道词表（model_tiers.yaml = 通道枚举唯一来源，SPEC_v2 §0 纪律 4）
# ---------------------------------------------------------------------
def load_channels(tiers_path: Path) -> dict:
    """解析 model_tiers.yaml → {channel_id: {provider, cost_confidence, excluded}}。

    channels[].channel_id 取其 cost_confidence（measured/reported/unverified）；
    excluded_channels[].channel_id 无档位字段 → 恒 unverified + excluded=True
    （cost_confidence_semantics.unverified：「不得进任何预算基线」——出局通道
    是更强的不进，语义向下兼容）。文件缺失/结构坏 → LedgerError（fail-fast）。
    """
    try:
        raw = tiers_path.read_bytes()
    except OSError as e:
        raise LedgerError(f"无法读取通道词表 {tiers_path}: {e}")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise LedgerError(f"通道词表 YAML 解析失败 {tiers_path}: {e}")
    if not isinstance(data, dict):
        raise LedgerError(f"通道词表顶层不是映射: {tiers_path}")

    channels: dict = {}
    for tier in data.get("tiers") or []:
        for ch in (tier or {}).get("channels") or []:
            cid = (ch or {}).get("channel_id")
            if not cid:
                continue
            if cid in channels:
                raise LedgerError(f"通道词表 channel_id 重复: {cid}")
            conf = (ch or {}).get("cost_confidence")
            if conf not in ("measured", "reported", "unverified"):
                raise LedgerError(
                    f"通道 {cid} cost_confidence 非法（须 measured/reported/unverified）: {conf!r}"
                )
            channels[cid] = {
                "provider": (ch or {}).get("provider"),
                "cost_confidence": conf,
                "excluded": False,
            }
    for ch in data.get("excluded_channels") or []:
        cid = (ch or {}).get("channel_id")
        if not cid:
            continue
        if cid in channels:
            raise LedgerError(f"通道 {cid} 同时出现在 channels 与 excluded_channels")
        channels[cid] = {"provider": (ch or {}).get("provider"), "cost_confidence": "unverified",
                         "excluded": True}
    if not channels:
        raise LedgerError(f"通道词表为空（无 channels/excluded_channels）: {tiers_path}")
    return channels


def thresholds_sha256(thresholds_path: Path) -> str:
    """thresholds.yaml 字节 sha256（与 src/gate/validate_cp*.py、eval_run.py 同口径）。"""
    try:
        return hashlib.sha256(thresholds_path.read_bytes()).hexdigest()
    except OSError as e:
        raise LedgerError(f"无法读取 thresholds {thresholds_path}: {e}")


def load_budget(thresholds_path: Path) -> dict:
    """读单集预算对照行的全部判定数值（判定数值单点，SPEC_v2 §0 纪律 3）。

    上限 = checkpoints.cost.episode_budget.standard_episode_shots
         × checkpoints.cp9.gate.credit_cap_per_shot
         × checkpoints.cost.episode_budget.budget_multiplier
    任一键缺失 → LedgerError（宁 exit 2 不放行，不内置默认值）。
    """
    try:
        data = yaml.safe_load(thresholds_path.read_bytes())
    except OSError as e:
        raise LedgerError(f"无法读取 thresholds {thresholds_path}: {e}")
    except yaml.YAMLError as e:
        raise LedgerError(f"thresholds YAML 解析失败 {thresholds_path}: {e}")
    cps = data.get("checkpoints") if isinstance(data, dict) else None
    cost = (cps or {}).get("cost") if isinstance(cps, dict) else None
    budget = (cost or {}).get("episode_budget") if isinstance(cost, dict) else None
    cp9_gate = ((cps or {}).get("cp9") or {}).get("gate") if isinstance(cps, dict) else None

    shots = (budget or {}).get("standard_episode_shots")
    mult = (budget or {}).get("budget_multiplier")
    cap_shot = (cp9_gate or {}).get("credit_cap_per_shot")
    for name, val in (("checkpoints.cost.episode_budget.standard_episode_shots", shots),
                      ("checkpoints.cost.episode_budget.budget_multiplier", mult),
                      ("checkpoints.cp9.gate.credit_cap_per_shot", cap_shot)):
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
            raise LedgerError(f"thresholds 缺判定数值键或非法: {name}（实得 {val!r}）"
                              "——单集对照行不许硬编码，请先按 G0-3 规程补键")
    cap = round(shots * cap_shot * mult, 6)
    if float(cap).is_integer():
        cap = int(cap)
    return {
        "standard_episode_shots": shots,
        "credit_cap_per_shot": cap_shot,
        "budget_multiplier": mult,
        "episode_cap": cap,
        "derivation": (f"{shots} × {cap_shot} × {mult}"
                       "（standard_episode_shots × cp9.gate.credit_cap_per_shot"
                       " × budget_multiplier，thresholds.yaml 三键乘积实算）"),
        "currency": "minimax_credit",
    }


# ---------------------------------------------------------------------
# record
# ---------------------------------------------------------------------
def build_entry(cp_id: str, channel: str, wall_clock_s: float, *,
                currency: str | None, amount: float | None,
                episode_id: str | None, note: str | None,
                conversion_basis: str | None,
                channels: dict, thr_sha: str) -> dict:
    """构造一条台账行；全部拒收判定集中在此（fail-fast，不落半截数据）。"""
    cp_norm = cp_id.strip().lower()
    if not CP_ID_RE.match(cp_norm):
        raise LedgerError(
            f"cp_id 非法: {cp_id!r}（须 cp1..cp12，白皮书 §3 十二检查点谱）")
    channel = channel.strip()
    info = channels.get(channel)
    if info is None:
        raise LedgerError(
            f"未知通道: {channel!r} —— channel 必须存在于 "
            f"contracts/v2/model_tiers.yaml 的 tiers[].channels[].channel_id 或 "
            f"excluded_channels（SPEC_v2 §0 纪律 4 通道枚举单点）。"
            f"已知通道 {len(channels)} 个，如需新增请走「模型分层重扫」改表（TASK_v4 §2.5）")
    if not isinstance(wall_clock_s, (int, float)) or isinstance(wall_clock_s, bool) \
            or not math.isfinite(wall_clock_s) or wall_clock_s < 0:
        raise LedgerError(f"wall_clock_s 须为非负有限数（实得 {wall_clock_s!r}）")

    unbaseline = info["cost_confidence"] == "unverified" or info["excluded"]
    if unbaseline and amount is not None:
        tag = "excluded_channels 出局通道" if info["excluded"] else "cost_confidence=unverified 未确证通道"
        raise LedgerError(
            f"{tag} {channel} 不进任何预算基线（白皮书 §4 成本可信度分层），"
            f"amount 一律记 null、不许带 --amount={amount!r}；"
            "如需记成本先在 tier 表核价（小额测试片 + evidence/pricing 落痕）并走模型分层重扫")

    # 币种：显式 > provider 推断；四套货币与 provider 体系绑定，混填即拒
    if currency is not None:
        currency = currency.strip()
        if currency not in CURRENCIES:
            raise LedgerError(
                f"currency 非法: {currency!r}（词表={('|'.join(CURRENCIES))}，"
                "四套货币不可换算，白皮书 §5.4）")
        bound = PROVIDER_CURRENCY.get(info["provider"])
        if bound is not None and bound != currency:
            raise LedgerError(
                f"币种 {currency} 与通道 {channel} 的 provider={info['provider']} "
                f"体系绑定不符（应为 {bound}）；两钱包不可直接换算，只许同体系内比较")
    else:
        currency = PROVIDER_CURRENCY.get(info["provider"])
        if currency is None and amount is not None:
            raise LedgerError(
                f"通道 {channel}（provider={info['provider']}）无默认币种映射，"
                f"带 --amount 时必须显式 --currency ∈ {('|'.join(CURRENCIES))}")

    if amount is not None:
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) \
                or not math.isfinite(amount) or amount < 0:
            raise LedgerError(f"amount 须为非负有限数（实得 {amount!r}）")
        if currency is None:
            raise LedgerError("内部一致性错误：有 amount 必有 currency")
        basis = conversion_basis or DEFAULT_CONVERSION_BASIS[currency]
    else:
        # 金额缺省：local_wall_s 墙钟即金额（白皮书 §4「本地 LTX-2B 0 积分，76.7s/条」口径）；
        # 其余币种必须显式给 amount——钱包/法币支出不许默认值（防拍脑袋数字进台账）
        if currency == "local_wall_s":
            amount = wall_clock_s
            basis = conversion_basis or DEFAULT_CONVERSION_BASIS["local_wall_s"]
        elif currency is None:
            basis = conversion_basis or NO_CURRENCY_BASIS
        else:
            raise LedgerError(
                f"币种 {currency} 为钱包/法币货币，必须显式 --amount "
                "（单价×数量或实扣直记，不给默认值）")

    if not (conversion_basis or basis) or not str(basis).strip():
        raise LedgerError("conversion_basis（折算口径）不许为空（白皮书 §5.4 显式声明红线）")

    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cp_id": cp_norm,
        "channel": channel,
        "wall_clock_s": float(wall_clock_s),
        "currency": currency,
        "amount": (float(amount) if amount is not None else None),
        "conversion_basis": str(basis).strip(),
        "episode_id": (episode_id or None),
        "note": (note or None),
        "thresholds_sha256": thr_sha,
        "cost_confidence": info["cost_confidence"],
        "channel_excluded": info["excluded"],
    }


def append_entry(ledger_path: Path, entry: dict) -> int:
    """append-only 追加一行；返回行号（1 起）。绝不读改写既有内容。"""
    prior_lines = 0
    if ledger_path.exists():
        prior_lines = sum(1 for ln in ledger_path.read_text(encoding="utf-8").splitlines()
                          if ln.strip())
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({k: entry[k] for k in ENTRY_KEYS}, ensure_ascii=False)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return prior_lines + 1


# ---------------------------------------------------------------------
# read / 求和守卫
# ---------------------------------------------------------------------
def read_entries(ledger_path: Path) -> list[dict]:
    """全量读台账；缺文件/坏行/字段非法 → LedgerError（append-only 只许整行追加，
    出现坏行即视为被篡改，fail-fast 不静默跳过）。"""
    if not ledger_path.is_file():
        raise LedgerError(f"台账不存在: {ledger_path} —— 先 record（"
                          "python3 src/cost/ledger.py record --cp-id ... --channel ...）")
    entries = []
    text = ledger_path.read_text(encoding="utf-8")
    for i, ln in enumerate(text.splitlines(), start=1):
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"台账第 {i} 行不是合法 JSON（append-only 只许整行追加，"
                              f"坏行=被篡改，须人工裁决）: {exc}")
        if not isinstance(e, dict):
            raise LedgerError(f"台账第 {i} 行不是 JSON 映射")
        missing = [k for k in ENTRY_KEYS if k not in e]
        if missing:
            raise LedgerError(f"台账第 {i} 行缺字段: {missing}")
        if e.get("currency") is not None and e.get("currency") not in CURRENCIES:
            raise LedgerError(f"台账第 {i} 行 currency 非法: {e.get('currency')!r}")
        if not CP_ID_RE.match(str(e.get("cp_id", ""))):
            raise LedgerError(f"台账第 {i} 行 cp_id 非法: {e.get('cp_id')!r}")
        if e.get("amount") is not None:
            if e.get("currency") is None:
                raise LedgerError(f"台账第 {i} 行有 amount 无 currency（被篡改）")
            if e.get("cost_confidence") == "unverified" or e.get("channel_excluded"):
                raise LedgerError(
                    f"台账第 {i} 行 unverified/excluded 通道带 amount，违反"
                    "「不进任何预算基线」红线（白皮书 §4），须人工裁决")
        if not str(e.get("conversion_basis") or "").strip():
            raise LedgerError(f"台账第 {i} 行 conversion_basis 为空"
                              "（折算口径显式声明红线，白皮书 §5.4）")
        entries.append(e)
    return entries


def total_amount(entries: list[dict], *, currency: str | None = None) -> float:
    """同 currency 求和（白皮书 §5.4 红线唯一合法的求和形态）。

    currency 给定时先过滤该币种；不给定时若入参跨币种 → CrossCurrencySumError
    （report 退出码 3）。amount=None（unverified/未核价）天然不入和。
    """
    usable = [e for e in entries if e.get("amount") is not None]
    if currency is not None:
        usable = [e for e in usable if e.get("currency") == currency]
    kinds = {e.get("currency") for e in usable}
    if len(kinds) > 1:
        raise CrossCurrencySumError(
            f"跨币种汇总企图: {sorted(str(k) for k in kinds)} —— 四套货币不可换算，"
            "跨币种只列分布不给总额（白皮书 §5.4 成本记账重写；TASK_v4 红线：违反即 exit 3）")
    return round(sum(float(e["amount"]) for e in usable), 6)


def grand_total(entries: list[dict]) -> float:
    """跨币种总额——**红线函数**：仅当全部可计金额同币种时才允许，否则 exit 3。

    report 永不主动调用本函数；--emit-grand-total 隐藏 tripwire 是唯一 CLI 触发路径。
    """
    return total_amount(entries)


# ---------------------------------------------------------------------
# report
# ---------------------------------------------------------------------
def build_report(entries: list[dict], budget: dict, *,
                 episode_filter: str | None, generated_at: str | None = None) -> dict:
    """聚合四类输出 + 跨币种分布。全部求和走 total_amount（同币种守卫）。"""
    if episode_filter is not None:
        entries = [e for e in entries if e.get("episode_id") == episode_filter]

    # 1. 每 CP 墙钟合计
    wall_by_cp: dict = {}
    for e in entries:
        slot = wall_by_cp.setdefault(e["cp_id"], {"calls": 0, "wall_clock_s_total": 0.0})
        slot["calls"] += 1
        slot["wall_clock_s_total"] = round(slot["wall_clock_s_total"] + float(e["wall_clock_s"]), 3)

    # 2. 每通道调用次数（附档位与是否进预算基线）
    calls_by_channel: dict = {}
    for e in entries:
        slot = calls_by_channel.setdefault(e["channel"], {"calls": 0})
        slot["calls"] += 1
        slot["cost_confidence"] = e.get("cost_confidence")
        slot["channel_excluded"] = bool(e.get("channel_excluded"))
        slot["enters_budget_baseline"] = (
            e.get("amount") is not None and not slot["channel_excluded"]
            and slot["cost_confidence"] != "unverified")

    # 3. 每 episode MiniMax 积分合计（同币种内：只挑 minimax_credit 行求和）
    eps = sorted({e.get("episode_id") for e in entries if e.get("episode_id") is not None})
    minimax_by_episode = {}
    for ep in eps:
        sub = [e for e in entries if e.get("episode_id") == ep]
        minimax_by_episode[ep] = total_amount(sub, currency="minimax_credit")

    # 4. 单集成本 vs 标准档对照行（TASK_v4 §4 M2 验收④；判定数值全自 thresholds 读）
    by_episode_budget = {}
    for ep in eps:
        sub = [e for e in entries if e.get("episode_id") == ep]
        spent = total_amount(sub, currency="minimax_credit")
        cap = budget["episode_cap"]
        ratio = round(spent / cap * 100.0, 1) if cap else None
        by_episode_budget[ep] = {
            "spent_minimax_credit": spent,
            "cap_minimax_credit": cap,
            "usage_pct": ratio,
            "within_budget": bool(spent <= cap),
        }

    # 跨币种分布：各币种各自同币种合计 + 条目数；跨币种总额恒 null（红线）
    dist = {}
    for cur in CURRENCIES:
        sub = [e for e in entries if e.get("currency") == cur]
        dist[cur] = {
            "sum": (total_amount(sub, currency=cur) if sub else 0.0),
            "entries": len(sub),
        }
    no_cur = [e for e in entries if e.get("currency") is None]
    if no_cur:
        dist["null_unverified"] = {"sum": None, "entries": len(no_cur),
                                   "note": "未核价/出局通道（amount=null，不进任何预算基线）"}

    baseline_excluded = {}
    for e in entries:
        if e.get("amount") is None:
            baseline_excluded[e["channel"]] = baseline_excluded.get(e["channel"], 0) + 1

    return {
        "schema": "cost-ledger-report/1.0",
        "generated_at": generated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "episode_filter": episode_filter,
        "entry_count": len(entries),
        "wall_clock_by_cp": wall_by_cp,
        "calls_by_channel": calls_by_channel,
        "minimax_credit_by_episode": minimax_by_episode,
        "episode_budget": {
            "currency": budget["currency"],
            "cap_per_episode": budget["episode_cap"],
            "derivation": budget["derivation"],
            "acceptance": "TASK_v4 §4 M2 验收④：单集成本 ≤ 标准档 ×1.2",
            "by_episode": by_episode_budget,
        },
        "currency_distribution": dist,
        "cross_currency_total": None,
        "cross_currency_note": "四套货币不可换算（minimax_credit/vidu_credit/stepfun_cny/"
                               "local_wall_s），跨币种只列分布不给总额；"
                               "跨币种汇总企图 → exit 3（白皮书 §5.4）",
        "excluded_from_budget_baseline": baseline_excluded,
    }


def render_md(rep: dict) -> str:
    """report dict → 人读 markdown（台账周核形态，migration 文档 CP9 行「周核」口径）。"""
    L: list[str] = []
    L.append(f"# 成本台账 report（{rep['episode_filter'] or '全部 episode'}）")
    L.append("")
    L.append(f"- generated_at: `{rep['generated_at']}`  |  条目数: {rep['entry_count']}")
    L.append("")

    L.append("## 1. 每 CP 墙钟合计")
    L.append("")
    L.append("| cp_id | 调用次数 | 墙钟合计 s |")
    L.append("|---|---|---|")
    for cp in sorted(rep["wall_clock_by_cp"]):
        s = rep["wall_clock_by_cp"][cp]
        L.append(f"| {cp} | {s['calls']} | {s['wall_clock_s_total']} |")
    if not rep["wall_clock_by_cp"]:
        L.append("|（无条目）| 0 | 0 |")
    L.append("")

    L.append("## 2. 每通道调用次数")
    L.append("")
    L.append("| channel | 次数 | cost_confidence | 出局通道 | 进预算基线 |")
    L.append("|---|---|---|---|---|")
    for ch in sorted(rep["calls_by_channel"]):
        s = rep["calls_by_channel"][ch]
        L.append(f"| {ch} | {s['calls']} | {s.get('cost_confidence')} "
                 f"| {'是' if s.get('channel_excluded') else '否'} "
                 f"| {'是' if s.get('enters_budget_baseline') else '否'} |")
    if not rep["calls_by_channel"]:
        L.append("|（无条目）| 0 | - | - | - |")
    L.append("")

    L.append("## 3. 每 episode MiniMax 积分合计（同币种内求和）")
    L.append("")
    L.append("| episode_id | minimax_credit 合计 |")
    L.append("|---|---|")
    for ep, v in rep["minimax_credit_by_episode"].items():
        L.append(f"| {ep} | {v} |")
    if not rep["minimax_credit_by_episode"]:
        L.append("|（无 minimax_credit 条目）| 0 |")
    L.append("")

    b = rep["episode_budget"]
    L.append("## 4. 单集成本 vs 标准档对照行（TASK_v4 §4 M2 验收④）")
    L.append("")
    L.append(f"- 上限推导：{b['derivation']} = **{b['cap_per_episode']} {b['currency']}/集**")
    L.append("")
    L.append("| episode_id | 实耗 minimax_credit | 上限 | 占用率 | 判定 |")
    L.append("|---|---|---|---|---|")
    for ep, s in b["by_episode"].items():
        verdict = "OK 预算内" if s["within_budget"] else "超限（触发 CP9/验收④）"
        L.append(f"| {ep} | {s['spent_minimax_credit']} | {s['cap_minimax_credit']} "
                 f"| {s['usage_pct']}% | {verdict} |")
    if not b["by_episode"]:
        L.append("|（无 episode 条目）| 0 | {} | - | - |".format(b["cap_per_episode"]))
    L.append("")

    L.append("## 5. 跨币种分布（四套货币不可换算，不给总额）")
    L.append("")
    L.append("| currency | 同币种合计 | 条目数 |")
    L.append("|---|---|---|")
    for cur, s in rep["currency_distribution"].items():
        L.append(f"| {cur} | {s['sum'] if s['sum'] is not None else 'null（不进基线）'} "
                 f"| {s['entries']} |")
    L.append("")
    L.append(f"> 跨币种总额：**不提供**。{rep['cross_currency_note']}")
    if rep["excluded_from_budget_baseline"]:
        L.append("")
        L.append("> 不进预算基线的通道（amount=null）："
                 + "、".join(f"{k}×{v}" for k, v in sorted(rep["excluded_from_budget_baseline"].items())))
    return "\n".join(L)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def _add_path_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER), help=argparse.SUPPRESS)
    p.add_argument("--tiers", default=str(DEFAULT_TIERS), help=argparse.SUPPRESS)
    p.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS), help=argparse.SUPPRESS)


def cmd_record(args: argparse.Namespace) -> int:
    channels = load_channels(Path(args.tiers))
    thr_sha = thresholds_sha256(Path(args.thresholds))
    entry = build_entry(
        args.cp_id, args.channel, args.wall_clock_s,
        currency=args.currency, amount=args.amount,
        episode_id=args.episode_id, note=args.note,
        conversion_basis=args.conversion_basis,
        channels=channels, thr_sha=thr_sha)
    n = append_entry(Path(args.ledger), entry)
    cur = entry["currency"] or "null（未核价）"
    amt = entry["amount"] if entry["amount"] is not None else "null（不进预算基线）"
    print(f"OK record 行#{n} cp={entry['cp_id']} channel={entry['channel']} "
          f"wall_clock_s={entry['wall_clock_s']} currency={cur} amount={amt} "
          f"confidence={entry['cost_confidence']} → {args.ledger}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    entries = read_entries(Path(args.ledger))
    budget = load_budget(Path(args.thresholds))
    rep = build_report(entries, budget, episode_filter=args.episode_id)

    if args.emit_grand_total:  # 隐藏 tripwire：唯一合法触达 exit 3 的路径（红线回归用）
        total = grand_total([e for e in entries
                             if args.episode_id is None
                             or e.get("episode_id") == args.episode_id])
        rep["cross_currency_total"] = total  # 同币种全量时才会走到这里

    if args.format == "json":
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render_md(rep))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ledger.py",
        description="v4 每 CP 成本台账（append-only JSONL；四套货币不可换算，"
                    "report 只做同币种求和，跨币种只列分布——违反即 exit 3）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="追加一条成本记录（append-only）")
    p_rec.add_argument("--cp-id", required=True, help="cp1..cp12")
    p_rec.add_argument("--channel", required=True,
                       help="须在 contracts/v2/model_tiers.yaml channels/excluded_channels")
    p_rec.add_argument("--wall-clock-s", required=True, type=float, help="墙钟秒数")
    p_rec.add_argument("--currency", default=None,
                       help=f"缺省按 provider 推断；词表 {'|'.join(CURRENCIES)}")
    p_rec.add_argument("--amount", default=None, type=float,
                       help="金额；local_wall_s 缺省=墙钟；unverified 通道不许带（恒 null）")
    p_rec.add_argument("--episode-id", default=None, help="集 id，如 short-drama/episode01")
    p_rec.add_argument("--note", default=None, help="备注")
    p_rec.add_argument("--conversion-basis", default=None,
                       help="折算口径（显式声明红线；缺省按币种给标准口径）")
    _add_path_args(p_rec)
    p_rec.set_defaults(func=cmd_record)

    p_rep = sub.add_parser("report", help="聚合报表（每 CP 墙钟 / 每通道次数 / "
                                          "每集 MiniMax 积分 / 单集 vs 标准档对照）")
    p_rep.add_argument("--episode-id", default=None, help="只看某集")
    p_rep.add_argument("--format", default="md", choices=["json", "md"])
    p_rep.add_argument("--emit-grand-total", action="store_true",
                       help=argparse.SUPPRESS)  # 红线 tripwire：跨币种总额 → exit 3
    _add_path_args(p_rep)
    p_rep.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as e:
        print(f"FAIL({e.exit_code}): {e}", file=sys.stderr)
        return e.exit_code


if __name__ == "__main__":
    sys.exit(main())
