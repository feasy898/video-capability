#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_cp12.py — CP12 质检与成片（qc_master）composite 门禁校验器（v4 · M2）。

用法
----
    python3 src/gate/validate_cp12.py <artifact.json> [--thresholds PATH]

    （--thresholds 缺省相对本文件定位 <vpipe>/eval/thresholds.yaml，仓根/vpipe
      两种 CWD 均可运行，与兄弟 validate_cp11 同口径。）

退出码
------
    0 = pass   全部硬门通过（warn-only 维只标注不否决，与 validate_cp6 rhythm /
               validate_cp11 声明差口径一致：warn 不翻转 verdict）
    1 = fail   成片门不过（任一校验项 fail；驳回/拒收是数据，stdout JSON 逐条给因；
               喂入非 cp12 工件也是数据级拒绝走 1——与 validate_cp11 口径一致）
    2 = error  用法/环境错误：文件缺失、JSON 不可解析、thresholds 缺失或缺键
               （宁可 exit 2 不放行，判不了就不是门禁——白皮书 §3 谱使用规则 3）

stdout 恒输出一个 JSON verdict；人读过程信息走 stderr。

校验项（编号承接任务书；判定数值一律从 eval/thresholds.yaml checkpoints.cp12.gate.*
读（:328-352，v4 段），结构词表/常量来自 contracts/v2/checkpoint.schema.json，模块内
不出现第二套数值——checkpoint.schema.json 红线① / SPEC_v2.md §0 纪律 3）：

  s0  artifact_shape        cp12 分支识别 + payload 必备键（definitions.qc_master
                            required：work_id/master_fingerprint/episode_verdict/
                            gate_groups/human_escalation_rate/retry_round/
                            shot_qc_refs；gate.type 枚举限 composite）
  upstream_master_mount     upstream_refs 须含 cp11——schema master_fingerprint 行
                            「被检成片指纹（= CP11 master_asset.fingerprint）」：
                            无合成上游则成片门无被检对象（同 validate_cp11 的
                            cp10 字幕道挂载检查口径）
  ①   episode_score_formula episode_verdict 公式核验：formula 必须 const
                            "0.7*mean+0.3*worst"（schema :1522-1526 固化防漂移），
                            且 score == 0.7×mean_shot_score + 0.3×worst_shot_score
                            （短板惩罚，AI视频生产流水线方案.md:162；白皮书 §3 CP12）。
                            容差：yaml 无 score 容差键（cp12.gate 十键盘点见
                            thresholds.yaml:328-352），公式是 schema const 恒等式
                            非判定阈，等值判定用浮点 epsilon EPS_R=1e-9（同
                            validate_cp11 EPS_R 口径：只用于等值判定不放宽任何阈；
                            若需舍入容差须按 thresholds.yaml 头部修改规程增键，
                            本器不许私立第二数值）；另核 worst_shot_score ≤
                            mean_shot_score（「最差镜头分」语义）。
  ②   gate_groups_{a,b,c}   A/B/C 组召回/误报阈按 yaml：a≥0.99/≤0.01、b≥0.95/≤0.15、
                            c≥0.80/≤0.15（checkpoints.cp12.gate.{a,b,c}_group_*，
                            白皮书 §3 CP12 原文）。组内 verdict 必须与召回/误报实测
                            按 yaml 阈推出的判定一致（声明 pass 而指标未达阈 =
                            数据撒谎，fail）。
      veto_groups_gate      yaml veto_groups（:344-348，现值 [a_group, b_group]）
                            内任一组 verdict=fail → 成片门直接不通过（白皮书 §3
                            CP12「任一镜头存在 A/B 组否决缺陷 → 成片门直接不通过」；
                            与 cp8.gate.veto_defects 同源防两套）。C 组 fail 不进
                            否决——judge 缺陷不允许自动否决（白皮书 CP12 C 组行），
                            只标注 warn 上升人工（白皮书 §7 非目标 3 warn 语义）。
                            红线守护：yaml veto_groups 若出现 d_group → exit 2
                            （D 组 warn-only 是 schema d_group.warn_only const:true
                            固化，配置层出现自动否决口子即拒绝运行）。
      gate_groups_d_warn_only
                            D 组 warn_only 必须 is True（schema :1643-1647 const
                            true——物理类 ROC-AUC≈53≈随机、时序类人类 96.7–100 vs
                            视频 LLM 27–41，白皮书 §3 CP12 D 组行 / §7 非目标 3；
                            本器复核是纵深防御，防 schema 外通道出现自动否决形态）；
                            d_group.verdict 值域只有 "warn"（schema :1653-1659 enum），
                            出现自动否决形态即 fail；flagged_count>0 只登记 warn
                            （人工只看程序标出的时间窗，白皮书 §2 原则 3）。
  ③   human_escalation_rate ≤ human_escalation_rate_max（yaml :349-350，现值 0.20；
                            白皮书 §3 CP12「人工上升率 ≤20%」原文 + §6 M2 验收③）。
                            yaml 实际结构无按 episode 类型参数化的分档键（无「短剧
                            0.25」键）——按任务书「以 yaml 实际结构为准」单键判定；
                            边界等值按 EPS_R 放行（恰在上限不是超限）。
  ④   routed_reworks_legal  每条路由 (defect_type → target_cp) 必须命中路由表：
                            身份→cp4 / 动作→cp5 / 节奏→cp6 / 字幕→cp10（白皮书 §3
                            CP12 失败回退行原文；schema qc_master.routed_reworks
                            target_cp 行同文；映射外 defect_type 或 target_cp 不符
                            即 fail——不允许成片级重抽，cp9 不是合法路由目标）。
                            路由表是结构词表非判定数值（同 cp5 的 16 关节词表待遇，
                            schema 自身以 description 收编四路由）；表内含
                            identity_drift（qc_report_v2.schema.json defects.type
                            扩展词自注「J6 ArcFace 跨人」＝身份类）。
  s1  params_ref_resolvable 工件 gate/aux_gates 的 params_ref 必须解析到
                            thresholds.yaml 真实键（schema 红线①执行面，同
                            validate_cp5 s1 口径：cpN.gate.* → checkpoints.cpN.gate.*，
                            其余前缀按 thresholds.yaml v4 段头「解析口径」走文件根；
                            悬空引用 fail）。本器自身判定键缺失另走 exit 2。
  ⑥   master_score_warn_only
                            master_score_min（yaml :330-334，现值 70）只作 warn 阈
                            与人工队列排序依据：score < 70 → warnings 标注，绝不
                            fail 也绝不因 score 达标自动放行（白皮书 §7 非目标 8：
                            70 分人评锚定——120 片段 12 周内不做——完成前 score
                            只排序；SPEC_v2.md §5 边界 3）。键存在性归 load_thresholds
                            （缺失 → exit 2）。
  retry_round_max           payload.retry_round ≤ retry_round_max（yaml :351-352，
                            白皮书 §3 CP12 失败回退行「重试 ≤2 轮仍不过 → 人工工单
                            + 标记结构性困难」；qc_master 必备字段的 yaml 背书门）。
  episode_verdict.verdict   verdict="reject" → 本门放行判定为 fail（签字或驳回是
                            CP12 人工三件事之三，驳回是数据不静默：exit 1 并把
                            路由记录列进 reasons）；声明 pass 时按上述①-⑥全量复核。

依据：
  - contracts/v2/checkpoint.schema.json definitions.qc_master（:1475-1722）+
    definitions.cp12_qc_master（:2495-2564，gate.type 枚举限 composite）
  - eval/thresholds.yaml:328-352 checkpoints.cp12.gate（v4 段十键）
  - research/2026-10-08/工业化视频流水线-白皮书.md §3 CP12（:175-192）+ §7 非目标 3/8
  - SPEC_v2.md §1 CP12 行（:79）+ §5 已知边界 2/3（:201-202）
  - contracts/v2/qc_report_v2.schema.json episode_verdict/human_review（同构同值口径）
  - evidence/thresholds/v3-to-v4-migration.md §2 解析口径（params_ref 根定位）
  - tests/fixtures/checkpoints/FIXTURES-LAYERING.md（结构层/规则层双层覆盖口径）

依赖：标准库 + PyYAML；零外部模型、零 ffprobe（CP12 判定吃上游登记实测值，
复测归 CP11 --probe 与各镜 QCReport——白皮书 §5.3「单镜头判官合议不作顶层」）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

CP_ID = "cp12"
SCHEMA_VERSION = "2.0"
ARTIFACT_TYPE = "qc_master"
GATE_TYPE = "composite"
DEFAULT_THRESHOLDS = "eval/thresholds.yaml"
THR_KEYROOT = f"checkpoints.{CP_ID}.gate"
GATE_PREFIX_RE = re.compile(r"^cp([1-9]|1[0-2])\.gate\.")

# definitions.qc_master required（checkpoint.schema.json:1478-1486）
PAYLOAD_REQUIRED = (
    "work_id",
    "master_fingerprint",
    "episode_verdict",
    "gate_groups",
    "human_escalation_rate",
    "retry_round",
    "shot_qc_refs",
)

FORMULA_CONST = "0.7*mean+0.3*worst"   # schema episode_verdict.formula const（:1524）
FORMULA_WEIGHTS = (0.7, 0.3)           # 恒等式的代数展开，非判定数值

# 浮点等值比较容差（只用于「恰落在阈上/恒等式复算」的等值判定，不放宽任何阈本身；
# 同 validate_cp11 EPS_R 口径。yaml 无 score 容差键，公式是 const 恒等式——见模块 docstring ①）
EPS_R = 1e-9

# ④ 缺陷类型 → 回退 CP 路由表（结构词表非判定数值）。出处：
#   白皮书 §3 CP12 失败回退行「身份→CP4，动作→CP5，节奏→CP6，字幕→CP10」；
#   checkpoint.schema.json qc_master.routed_reworks.target_cp description 同文；
#   identity_drift 为 qc_report_v2.schema.json defects.type 扩展词（自注 J6 ArcFace
#   跨人＝身份类）。映射外类型拒（任务书④；cp9 不是合法路由目标——不允许成片级重抽）。
ROUTE_TABLE = {
    "身份": "cp4",
    "identity": "cp4",
    "identity_drift": "cp4",
    "动作": "cp5",
    "action": "cp5",
    "节奏": "cp6",
    "rhythm": "cp6",
    "字幕": "cp10",
    "subtitle": "cp10",
}

GROUP_IDS = ("a_group", "b_group", "c_group")
VETO_LEGAL = {"a_group", "b_group", "c_group", "d_group"}  # veto_groups 词形域


class ReadError(Exception):
    """用法/读取/环境类错误 → exit 2（宁可 exit 2 不放行）。"""


# ---------------------------------------------------------------- 基础工具

def _num(x) -> bool:
    """数字（排除 bool——bool 是 int 子类，不能当召回率/上限用）。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt(x) -> str:
    return f"{float(x):g}"


def _walk(node, keys):
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def _resolve_thresholds_path(p: str) -> Path:
    """先按给定路径（CWD 相对）找；找不到且是缺省值时回退脚本相对定位
    （<vpipe>/eval/thresholds.yaml），仓根/vpipe 两种 CWD 都能跑（同 cp11）。"""
    path = Path(p)
    if path.is_file():
        return path
    fallback = Path(__file__).resolve().parents[2] / "eval" / "thresholds.yaml"
    if p == DEFAULT_THRESHOLDS and fallback.is_file():
        return fallback
    raise ReadError(f"thresholds 文件不存在或不是文件: {path}")


def load_thresholds(path: Path) -> tuple[dict, str]:
    """读本门禁全部判定数值（checkpoints.cp12.gate 十键，一个不少）。
    返回 (thr dict, thresholds.yaml sha256)。键缺失/类型不对 → ReadError（exit 2）。
    本器自身判定键缺失走 exit 2；工件 params_ref 悬空走 s1 fail——两者分层，
    与 validate_cp5「布尔强制键被改 false → 拒绝旁路门禁」同精神。"""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ReadError(f"无法读取 thresholds 文件 {path}: {e}")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ReadError(f"thresholds YAML 解析失败 {path}: {e}")
    if not isinstance(data, dict):
        raise ReadError("thresholds 顶层不是映射")

    cps = data.get("checkpoints")
    cp12 = cps.get(CP_ID) if isinstance(cps, dict) else None
    gate = cp12.get("gate") if isinstance(cp12, dict) else None
    if not isinstance(gate, dict):
        raise ReadError(f"thresholds 缺 {THR_KEYROOT} 段")

    def _ratio_num(key: str, lo: float, hi: float) -> float:
        v = gate.get(key)
        if not _num(v) or not (lo <= v <= hi):
            raise ReadError(f"{THR_KEYROOT}.{key} 缺失或不在 [{lo}, {hi}]（实得 {v!r}）")
        return float(v)

    thr = {
        "master_score_min": _ratio_num("master_score_min", 0.0, 100.0),
        "a_group_recall_min": _ratio_num("a_group_recall_min", 0.0, 1.0),
        "a_group_fpr_max": _ratio_num("a_group_fpr_max", 0.0, 1.0),
        "b_group_recall_min": _ratio_num("b_group_recall_min", 0.0, 1.0),
        "b_group_fpr_max": _ratio_num("b_group_fpr_max", 0.0, 1.0),
        "c_group_recall_min": _ratio_num("c_group_recall_min", 0.0, 1.0),
        "c_group_fpr_max": _ratio_num("c_group_fpr_max", 0.0, 1.0),
        "human_escalation_rate_max": _ratio_num("human_escalation_rate_max", 0.0, 1.0),
    }

    rr_max = gate.get("retry_round_max")
    if not _num(rr_max) or rr_max < 0 or float(rr_max) != int(rr_max):
        raise ReadError(f"{THR_KEYROOT}.retry_round_max 缺失或非非负整数（实得 {rr_max!r}）")
    thr["retry_round_max"] = int(rr_max)

    veto = gate.get("veto_groups")
    if not isinstance(veto, list) or not veto or not all(isinstance(g, str) for g in veto):
        raise ReadError(f"{THR_KEYROOT}.veto_groups 缺失或非非空字符串数组（实得 {veto!r}）")
    unknown = [g for g in veto if g not in VETO_LEGAL]
    if unknown:
        raise ReadError(f"{THR_KEYROOT}.veto_groups 含非法组名 {unknown}（合法词形域 {sorted(VETO_LEGAL)}）")
    # 红线守护：D 组 warn-only 是 schema d_group.warn_only const:true 的机判固化
    # （白皮书 §7 非目标 3），配置层不许为 D 开自动否决口子——出现即拒绝运行本器。
    if "d_group" in veto:
        raise ReadError(
            f"{THR_KEYROOT}.veto_groups 含 d_group：D 组 warn-only 由 checkpoint.schema.json "
            "definitions.qc_master d_group.warn_only const:true 固化（白皮书 §7 非目标 3），"
            "veto 配置不许为 D 组开自动否决口子——本器拒绝在该配置下运行（宁可 exit 2 不放行）")
    thr["veto_groups"] = list(veto)

    thr["_keys_used"] = [
        f"{THR_KEYROOT}.{k}" for k in (
            "master_score_min", "a_group_recall_min", "a_group_fpr_max",
            "b_group_recall_min", "b_group_fpr_max", "c_group_recall_min",
            "c_group_fpr_max", "veto_groups", "human_escalation_rate_max",
            "retry_round_max",
        )
    ]
    sha = hashlib.sha256(raw).hexdigest()
    thr["_sha256"] = sha
    return thr, sha


def resolve_params_ref(ref: str, th_raw: dict) -> bool:
    """thresholds.yaml v4 段头「解析口径」（evidence/thresholds/v3-to-v4-migration.md §2）：
    cpN.gate.* → checkpoints.cpN.gate.*；其余前缀（l0_preflight.* / judges.* /
    ensemble.* / eval_admission.*）走文件根。同 validate_cp5.resolve_params_ref。"""
    keys = ref.split(".")
    if GATE_PREFIX_RE.match(ref):
        keys = ["checkpoints"] + keys
    return _walk(th_raw, keys) is not None


# ---------------------------------------------------------------- 校验项

def check_shape(art: dict) -> dict:
    """s0 cp12 分支识别 + payload 必备键（分支识别；完整 schema 校验归结构层，
    FIXTURES-LAYERING.md 两层定位）。非 cp12 工件=数据级拒绝（fail，同 cp11 口径）。"""
    problems = []
    if art.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version 须为 {SCHEMA_VERSION!r}（实得 {art.get('schema_version')!r}）")
    if art.get("cp_id") != CP_ID:
        problems.append(f"cp_id 须为 {CP_ID!r}（实得 {art.get('cp_id')!r}）")
    if art.get("artifact_type") != ARTIFACT_TYPE:
        problems.append(f"artifact_type 须为 {ARTIFACT_TYPE!r}（实得 {art.get('artifact_type')!r}）")
    gt = art.get("gate") or {}
    if isinstance(gt, dict) and gt.get("type") not in (None, GATE_TYPE):
        problems.append(f"gate.type 须为 {GATE_TYPE!r}（实得 {gt.get('type')!r}）")
    payload = art.get("payload")
    if not isinstance(payload, dict):
        problems.append("payload 缺失或非映射")
    else:
        for k in PAYLOAD_REQUIRED:
            if k not in payload:
                problems.append(f"payload 缺必备键 {k}")
    ok = not problems
    return {
        "name": "artifact_shape",
        "ok": ok,
        "detail": ("cp12 分支识别成立，payload 必备键齐" if ok else "；".join(problems)),
    }


def check_upstream_master_mount(art: dict) -> dict:
    """成片道挂载：upstream_refs 须含 cp11——master_fingerprint=CP11 master_asset.
    fingerprint（schema qc_master.master_fingerprint 行），无合成上游即无被检对象。"""
    ups = art.get("upstream_refs") or []
    cp_ids = sorted({u.get("cp_id") for u in ups if isinstance(u, dict)})
    ok = "cp11" in cp_ids
    return {
        "name": "upstream_master_mount",
        "ok": ok,
        "detail": (f"upstream_refs 含 cp11（master_fingerprint 挂载 CP11 master_asset，"
                   f"upstream={cp_ids}）" if ok else
                   f"upstream_refs 缺 cp11（实得 {cp_ids}）：master_fingerprint 无合成产物锚点，"
                   "成片门没有被检对象 → fail（schema：master_fingerprint = CP11 "
                   "master_asset.fingerprint）"),
    }


def check_episode_formula(payload: dict) -> dict:
    """① 成片分公式核验（短板惩罚恒等式；容差口径见模块 docstring）。"""
    ev = payload.get("episode_verdict")
    name = "episode_score_formula"
    if not isinstance(ev, dict):
        return {"name": name, "ok": False, "detail": f"episode_verdict 缺失或非映射（实得 {type(ev).__name__}）"}
    problems = []
    score, mean, worst = ev.get("score"), ev.get("mean_shot_score"), ev.get("worst_shot_score")
    formula = ev.get("formula")
    if formula != FORMULA_CONST:
        problems.append(f"formula 须为 const {FORMULA_CONST!r}（实得 {formula!r}；schema 固化防实现漂移）")
    if not (_num(score) and _num(mean) and _num(worst)):
        problems.append(f"score/mean_shot_score/worst_shot_score 须全为数值"
                        f"（实得 {score!r}/{mean!r}/{worst!r}）")
    else:
        recomputed = FORMULA_WEIGHTS[0] * float(mean) + FORMULA_WEIGHTS[1] * float(worst)
        dev = abs(float(score) - recomputed)
        if dev > EPS_R:
            problems.append(
                f"score {_fmt(score)} != 0.7×mean {_fmt(mean)} + 0.3×worst {_fmt(worst)}"
                f"（复算 {_fmt(recomputed)}，偏差 {dev:g} > EPS {EPS_R:g}）——"
                "成片分公式被改（短板惩罚，AI视频生产流水线方案.md:162）")
        if float(worst) > float(mean) + EPS_R:
            problems.append(f"worst_shot_score {_fmt(worst)} > mean_shot_score {_fmt(mean)}"
                            "（「最差镜头分」不可能大于均值——数据自相矛盾）")
    verdict = ev.get("verdict")
    if verdict not in ("pass", "reject"):
        problems.append(f"episode_verdict.verdict 须为 pass|reject（实得 {verdict!r}）")
    ok = not problems
    detail = (f"score {_fmt(score)} = 0.7×mean {_fmt(mean)} + 0.3×worst {_fmt(worst)}"
              f"（复算一致，短板惩罚恒等式；verdict={verdict!r}）" if ok else "；".join(problems))
    return {"name": name, "ok": ok, "detail": detail}


def _group_metric_verdict(gid: str, g: dict, thr: dict) -> tuple[bool | None, str]:
    """按 yaml 阈推出组判定：pass ⟺ recall ≥ *_recall_min 且 fpr ≤ *_fpr_max。
    返回 (implied|None(指标非法), 说明)。"""
    r_min = thr[f"{gid}_recall_min"]
    f_max = thr[f"{gid}_fpr_max"]
    recall, fpr = g.get("recall"), g.get("fpr")
    if not _num(recall) or not (0 <= float(recall) <= 1) or not _num(fpr) or not (0 <= float(fpr) <= 1):
        return None, f"recall/fpr 须为 [0,1] 数值（实得 {recall!r}/{fpr!r}）"
    implied = (float(recall) >= r_min - EPS_R) and (float(fpr) <= f_max + EPS_R)
    return implied, (f"recall {_fmt(recall)} vs ≥{_fmt(r_min)}，fpr {_fmt(fpr)} vs ≤{_fmt(f_max)}"
                     f"（cp12.gate.{gid}_recall_min / {gid}_fpr_max）")


def check_gate_groups(payload: dict, thr: dict) -> tuple[list[dict], list[str]]:
    """② 四组门禁：a/b/c 组阈值一致性 + veto_groups 否决 + c 组 warn-only + D 组
    warn_only const 复核。返回 (checks, warnings)。"""
    checks: list[dict] = []
    warnings: list[str] = []
    groups = payload.get("gate_groups")
    if not isinstance(groups, dict):
        checks.append({"name": "gate_groups_present", "ok": False,
                       "detail": f"gate_groups 缺失或非映射（实得 {type(groups).__name__}）"})
        return checks, warnings

    declared_fail = []
    for gid in GROUP_IDS:
        g = groups.get(gid)
        if not isinstance(g, dict):
            checks.append({"name": f"gate_groups_{gid}", "ok": False,
                           "detail": f"gate_groups.{gid} 缺失或非映射（实得 {type(g).__name__}）"})
            continue
        # 弃权形态（abstain=true+reason）：qc_orch §2.3 判官弃权语义的组级化
        # （主控验收修订 2026-10-09：B 组专用小模型未部署等场景须可诚实表达，
        # 填占位指标伪装 pass/fail 是第二套判定）——弃权不参与 veto_groups。
        if g.get("abstain") is True:
            reason = g.get("reason") or "（未注明弃权原因）"
            checks.append({"name": f"gate_groups_{gid}", "ok": True,
                           "detail": f"gate_groups.{gid} 弃权：{reason}——合议弃权语义"
                                     "（SPEC §2.3：判官弃权后用剩余通道继续），不参与 veto_groups"})
            continue
        implied, why = _group_metric_verdict(gid, g, thr)
        verdict = g.get("verdict")
        problems = []
        if implied is None:
            problems.append(f"gate_groups.{gid} 指标非法：{why}")
        elif verdict not in ("pass", "fail"):
            problems.append(f"gate_groups.{gid}.verdict 须为 pass|fail（实得 {verdict!r}）")
        elif verdict != ("pass" if implied else "fail"):
            problems.append(f"gate_groups.{gid}.verdict 声明 {verdict!r} 与指标推出判定 "
                            f"{'pass' if implied else 'fail'} 不符（{why}）——组判定必须可复算")
        ok = not problems
        if not ok:
            checks.append({"name": f"gate_groups_{gid}", "ok": False, "detail": "；".join(problems)})
            continue
        if verdict == "fail":
            declared_fail.append(gid)
        note = (f"gate_groups.{gid} 判定 {verdict}（{why}）"
                + ("——judge 缺陷不允许自动否决，只标注上升人工"
                   "（白皮书 §3 CP12 C 组行 / §7 非目标 3）" if gid == "c_group" and verdict == "fail" else ""))
        checks.append({"name": f"gate_groups_{gid}", "ok": True, "detail": note})
        if gid == "c_group" and verdict == "fail":
            warnings.append(f"C 组召回/误报未达 yaml 阈（{why}）：judge 缺陷不允许自动否决"
                            "（白皮书 §3 CP12），本门不因此翻转——转人工标注复核")

    # veto_groups（yaml 读，非硬编码）：组内任一 verdict=fail → 成片门直接不通过
    veto = thr["veto_groups"]
    vetoed = [g for g in declared_fail if g in veto]
    checks.append({
        "name": "veto_groups_gate",
        "ok": not vetoed,
        "detail": (f"否决组 {veto}（cp12.gate.veto_groups）无 fail 组"
                   f"（a/b/c 声明判定：{ {g: (groups.get(g) or {}).get('verdict') for g in GROUP_IDS} }）"
                   if not vetoed else
                   f"否决组 {veto} 中 {vetoed} verdict=fail：任一镜头存在 A/B 组否决缺陷 → "
                   "成片门直接不通过（白皮书 §3 CP12；cp12.gate.veto_groups 与 cp8.veto_defects 同源）"),
    })

    # D 组：warn_only const 复核（纵深防御）+ verdict 值域只有 warn + flagged 只登记
    d = groups.get("d_group")
    if not isinstance(d, dict):
        checks.append({"name": "gate_groups_d_warn_only", "ok": False,
                       "detail": f"gate_groups.d_group 缺失或非映射（实得 {type(d).__name__}）"})
    else:
        problems = []
        wo = d.get("warn_only")
        if wo is not True:
            problems.append(f"d_group.warn_only 须为 true（schema const 固化，实得 {wo!r}）——"
                            "D 组默认 warn-only 不做自动否决（物理类 ROC-AUC≈53≈随机、时序类 "
                            "TempCompass 人类 96.7–100 vs 视频 LLM 27–41，白皮书 §7 非目标 3）；"
                            "出现自动否决形态即拒")
        verdict = d.get("verdict")
        if verdict != "warn":
            problems.append(f"d_group.verdict 值域只有 'warn'（schema enum，实得 {verdict!r}）——"
                            "D 组不许出现自动否决判定形态")
        flagged = d.get("flagged_count")
        if not _num(flagged) or float(flagged) < 0 or float(flagged) != int(flagged):
            problems.append(f"d_group.flagged_count 须为非负整数（实得 {flagged!r}）")
        ok = not problems
        checks.append({"name": "gate_groups_d_warn_only", "ok": ok,
                       "detail": ("；".join(problems) if not ok else
                                  f"d_group.warn_only=true（const 复核通过）、verdict=warn、"
                                  f"flagged_count={_fmt(flagged)}"
                                  + ("——flag 时间窗转人工灰区队列，只标注不否决"
                                     "（白皮书 §2 原则 3：人工只看程序标出的时间窗）"
                                     if _num(flagged) and int(flagged) > 0 else ""))})
        if ok and _num(flagged) and int(flagged) > 0:
            warnings.append(f"D 组 flag {int(flagged)} 个候选时间窗：warn-only 维只登记不否决，"
                            "转人工（白皮书 §3 CP12 人类三件事之二）")
    return checks, warnings


def check_human_escalation(payload: dict, thr: dict) -> dict:
    """③ 人工上升率 ≤ 上限（yaml 单键，无按 episode 类型分档——以 yaml 实际结构为准）。"""
    rate = payload.get("human_escalation_rate")
    cap = thr["human_escalation_rate_max"]
    ok = _num(rate) and 0 <= float(rate) <= 1 and float(rate) <= cap + EPS_R
    return {
        "name": "human_escalation_rate_max",
        "ok": ok,
        "detail": (f"human_escalation_rate {_fmt(rate)} ≤ cp12.gate.human_escalation_rate_max="
                   f"{_fmt(cap)}（白皮书 §3 CP12：人工上升率 ≤20%；yaml 无按 episode 类型"
                   "分档键，单键口径）" + ("——恰在上限，等值按 EPS 放行" if _num(rate) and abs(float(rate) - cap) <= EPS_R else "")
                   if ok else
                   f"human_escalation_rate {_fmt(rate) if _num(rate) else rate!r} > "
                   f"cp12.gate.human_escalation_rate_max={_fmt(cap)}"
                   "（或非 [0,1] 数值）：人工上升超限——周复核误杀/漏放并回滚权重"
                   "（白皮书 §3 CP12 / §6 M2 验收③）"),
    }


def check_routed_reworks(payload: dict) -> dict:
    """④ 路由合法性：每条 (defect_type → target_cp) 必须命中路由表且 CP 相符；
    映射外类型拒（cp9 不是合法路由目标——不允许成片级重抽）。"""
    routes = payload.get("routed_reworks")
    name = "routed_reworks_legal"
    if routes is None:
        return {"name": name, "ok": True,
                "detail": "routed_reworks 未随工件登记（schema 非必备字段）——无驳回即无路由记录"}
    if not isinstance(routes, list):
        return {"name": name, "ok": False,
                "detail": f"routed_reworks 须为数组（实得 {type(routes).__name__}）"}
    problems = []
    for i, r in enumerate(routes):
        tag = f"routed_reworks[{i}]"
        if not isinstance(r, dict):
            problems.append(f"{tag} 非映射（实得 {type(r).__name__}）")
            continue
        dt, tcp = r.get("defect_type"), r.get("target_cp")
        want = ROUTE_TABLE.get(dt) if isinstance(dt, str) else None
        if want is None:
            problems.append(
                f"{tag} defect_type {dt!r} 不在路由表（合法词表 "
                f"{sorted(ROUTE_TABLE)}）——白皮书 §3 CP12 失败回退行只有 "
                "身份→cp4/动作→cp5/节奏→cp6/字幕→cp10 四路由，映射外类型拒")
        elif tcp != want:
            problems.append(
                f"{tag} 路由 {dt!r}→{tcp!r} 与路由表不符（应为 {dt!r}→{want}）——"
                f"cp{tcp[2:] if isinstance(tcp, str) and tcp.startswith('cp') else tcp} "
                "不是该缺陷类型的回退目标（不允许成片级重抽，白皮书 §3 CP12 失败回退行）")
    ok = not problems
    summary = ("；".join(f"{r.get('defect_type')}→{r.get('target_cp')}" for r in routes
                        if isinstance(r, dict)) or "空")
    return {"name": name, "ok": ok,
            "detail": (f"路由记录 {len(routes)} 条全部合法（{summary}）" if ok
                       else f"路由记录 {len(routes)} 条存在非法项（{summary}）："
                            + "；".join(problems))}


def check_retry_round(payload: dict, thr: dict) -> dict:
    """retry_round ≤ retry_round_max（yaml 背书门；超限应转人工工单而非继续重试）。"""
    rr = payload.get("retry_round")
    cap = thr["retry_round_max"]
    ok = _num(rr) and float(rr) >= 0 and float(rr) == int(rr) and int(rr) <= cap
    return {
        "name": "retry_round_max",
        "ok": ok,
        "detail": (f"retry_round {_fmt(rr)} ≤ cp12.gate.retry_round_max={cap}"
                   "（白皮书 §3 CP12：重试 ≤2 轮仍不过 → 人工工单+标记结构性困难+进金标扩样队列）"
                   if ok else
                   f"retry_round {rr!r} > cp12.gate.retry_round_max={cap}（或非非负整数）："
                   "重试超限须转人工工单，不允许第 3 轮继续自动重试"),
    }


def check_params_refs(art: dict, th_raw: dict) -> dict:
    """s1 gate/aux_gates 的 params_ref 全解析（schema 红线①执行面，同 validate_cp5 s1）。"""
    gates = ([art["gate"]] if isinstance(art.get("gate"), dict) else []) + \
            [g for g in art.get("aux_gates") or [] if isinstance(g, dict)]
    problems = []
    seen = []
    for g in gates:
        ref = g.get("params_ref")
        if not isinstance(ref, str):
            continue
        seen.append(ref)
        if not resolve_params_ref(ref, th_raw):
            problems.append(
                f"params_ref {ref!r} 解析不到 thresholds.yaml 真实键"
                "（cpN.gate.* → checkpoints.cpN.gate.*，其余前缀走文件根；悬空引用拒收）")
    ok = not problems
    return {"name": "params_ref_resolvable", "ok": ok,
            "detail": (f"gate/aux_gates params_ref 全部解析到真实键（{sorted(set(seen))}）"
                       if ok else "；".join(problems))}


def check_score_warn_only(payload: dict, thr: dict) -> tuple[dict, list[str]]:
    """⑥ master_score_min 只作 warn 阈与人工队列排序依据：score < 阈 → warning 标注，
    绝不 fail、也绝不因达标自动放行（白皮书 §7 非目标 8）。"""
    ev = payload.get("episode_verdict") or {}
    score = ev.get("score") if isinstance(ev, dict) else None
    thr_min = thr["master_score_min"]
    warnings = []
    if _num(score) and float(score) < thr_min - EPS_R:
        warnings.append(
            f"成片分 {_fmt(score)} < cp12.gate.master_score_min={_fmt(thr_min)}："
            "70 分人评锚定（120 片段）未完成前只作 warn 阈与人工队列排序依据，"
            "不作自动放行/否决门（白皮书 §7 非目标 8；SPEC_v2 §5 边界 3）——本件照常按"
            "①-⑤/s1 判定，warn 已登记灰区排序")
    score_txt = _fmt(score) if _num(score) else repr(score)
    above = _num(score) and float(score) >= thr_min
    check = {
        "name": "master_score_warn_only",
        "ok": True,
        "detail": (f"master_score_min={_fmt(thr_min)} 仅作 warn 阈（本件 score "
                   f"{score_txt}{'≥' if above else '<'}阈）——不作自动放行门，"
                   "键存在性已由 load_thresholds 保证（缺失 exit 2）"),
    }
    return check, warnings


def check_episode_reject(payload: dict) -> dict:
    """工件自录驳回（episode_verdict.verdict=reject）→ 本门放行判定 fail（驳回是数据
    不静默；签字或驳回是 CP12 人工三件事之三）。声明 pass 时不由此项产生 fail。"""
    ev = payload.get("episode_verdict") or {}
    verdict = ev.get("verdict") if isinstance(ev, dict) else None
    routes = payload.get("routed_reworks") or []
    route_summary = "；".join(f"{r.get('defect_type')}→{r.get('target_cp')}"
                              for r in routes if isinstance(r, dict)) or "（无路由记录）"
    ok = verdict != "reject"
    return {
        "name": "episode_reject_is_data",
        "ok": ok,
        "detail": (f"episode_verdict.verdict=pass（无自录驳回）" if ok else
                   f"episode_verdict.verdict=reject：成片门驳回（签字/驳回是 CP12 人工三件事之三）；"
                   f"路由记录 {len(routes)} 条 {route_summary}——驳回是数据不静默，按缺陷类型"
                   "路由回具体 CP，不允许成片级重抽（白皮书 §3 CP12 失败回退行）"),
    }


# ---------------------------------------------------------------- 主流程

def validate(art: dict, thr: dict, th_raw: dict) -> dict:
    """判定核心（可导入复用）。返回 verdict dict；exit 码由调用方按 verdict 定。
    工件顶层不是 JSON 映射时 raise ReadError（exit 2，不可判定）。"""
    if not isinstance(art, dict):
        raise ReadError("工件顶层不是 JSON 映射")
    shape = check_shape(art)
    checks = [shape]
    warnings: list[str] = []
    evidence: dict = {}
    payload = art.get("payload") if isinstance(art.get("payload"), dict) else {}

    if shape["ok"]:
        checks.append(check_upstream_master_mount(art))
        checks.append(check_episode_formula(payload))
        g_checks, g_warnings = check_gate_groups(payload, thr)
        checks.extend(g_checks)
        warnings.extend(g_warnings)
        checks.append(check_human_escalation(payload, thr))
        checks.append(check_routed_reworks(payload))
        checks.append(check_retry_round(payload, thr))
        checks.append(check_params_refs(art, th_raw))
        score_check, score_warnings = check_score_warn_only(payload, thr)
        checks.append(score_check)
        warnings.extend(score_warnings)
        checks.append(check_episode_reject(payload))
    else:
        evidence["skipped"] = ("工件未过 artifact_shape：分支不识别或必备键缺，"
                               "后续规则项不运行（判 fail）")

    fails = [c for c in checks if not c["ok"]]
    verdict = "fail" if fails else "pass"
    out = {
        "validator": "validate_cp12",
        "cp_id": CP_ID,
        "gate": GATE_TYPE,
        "verdict": verdict,
        "checks": checks,
        "warnings": warnings,
        "warn_only_count": len(warnings),
        "evidence": evidence,
        "work_id": payload.get("work_id"),
        "thresholds_keys_used": thr["_keys_used"],
        "thresholds_sha256": thr["_sha256"],
        "veto_groups": thr["veto_groups"],
    }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CP12（质检与成片）composite 门禁校验器：判定数值全部来自 "
                    f"{THR_KEYROOT}.*（thresholds v4 十键），"
                    "exit 0=pass（含 warn-only 标注）/ 1=fail / 2=用法或读取错误")
    ap.add_argument("artifact", help="CP12 qc_master 工件 JSON 路径")
    ap.add_argument("--thresholds", default=DEFAULT_THRESHOLDS,
                    help=f"阈值表路径（缺省 {DEFAULT_THRESHOLDS}，自动回退脚本相对定位）")
    args = ap.parse_args(argv)

    try:
        art = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "verdict": "error",
                          "error": f"工件读取失败 {args.artifact}: {e}"},
                         ensure_ascii=False, indent=2))
        print(f"ERROR: 工件读取失败 {args.artifact}: {e}", file=sys.stderr)
        return 2

    try:
        thr, _ = load_thresholds(_resolve_thresholds_path(args.thresholds))
        th_raw = yaml.safe_load(Path(_resolve_thresholds_path(args.thresholds)).read_text(encoding="utf-8"))
    except ReadError as e:
        print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "verdict": "error",
                          "error": str(e)}, ensure_ascii=False, indent=2))
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        result = validate(art, thr, th_raw)
    except ReadError as e:
        print(json.dumps({"cp_id": CP_ID, "gate": GATE_TYPE, "verdict": "error",
                          "error": str(e)}, ensure_ascii=False, indent=2))
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    result["artifact"] = args.artifact
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
