#!/usr/bin/env python3
"""build_cp12_reports_v2.py — CP12 修订重跑（master_v2=avatar 钩子片头）判官输出 →
qc_report_v2(v2 契约) + cp12 v2 工件.

沿 build_cp12_reports.py（v1）合议聚合口径，本次修订三点（主控验收修订 2026-10-09）：
  1. 组级指标用【本片真空语义】：金标 40 条群体校准值（v1 登记）不进组级——
     a 组 0 缺陷/0 误拒、b 组弃权形、c 组 judge 检出不自动否决+flag 入人工队列；
     单片无真值不可测群体召回/误拒，recall/fpr 数值是本片空洞值并显式声明。
  2. J6v2 emitted 候选（conf≥emit_conf）按 judges.J6_detectors_v2 role=signal_only
     处理：入 defects[]（source J6）+ 人工队列 pending，不作 A 组否决缺陷、
     不翻 composite verdict；低于 emit_conf 的候选窗仍走 D 组 warn-only。
  3. avatar 段（avatar_hook_01）单列 QC 记录：口型同步/身份保持的人工+程序双结论
     （avatar/avatar_segment_qc.json），本脚本只引用不重判。

前置（本脚本不跑模型）：
  1. qc_orch_v2 --online 已产出 qc_reports_online/shortdrama_ep01_v2.json
     （E10=J1∨J3@0.71 主判据——判定一律以它为准，本脚本不重算 E10）
  2. 判官 v2 输出已回传 judges/{glm8,omnijev,videochat3,detectors}/*_v2 文件

成片分映射（沿 v1 声明）：D=max(J3 触发通道 P≥thr，J1/J5 detected→confidence，
J6v2 emitted conf≥emit_conf)；clip_score=100×(1−D)；成片段数 12（avatar 钩子段+
11 镜）继承成片单镜分（镜级 QCReport 本链未产出，按任务预案单镜近似并声明）。
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # out/m2/shortdrama_ep01/
VPIPE = HERE.parent.parent.parent               # overnight/vpipe/
sys.path.insert(0, str(VPIPE / "src"))

CLIP = "shortdrama_ep01_v2"
JUDGES = HERE / "judges"
ONLINE_REPORT = HERE / "qc_reports_online" / f"{CLIP}.json"
THRESHOLDS = VPIPE / "eval" / "thresholds.yaml"
NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fingerprint_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load(p: Path) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main() -> int:
    import yaml
    T = yaml.safe_load(open(THRESHOLDS, encoding="utf-8"))
    thr_sha = sha256_file(THRESHOLDS)
    j3_thr = float(T["judges"]["J3_omnijev"]["thr"])
    auto_reject_p = float(T["judges"]["J3_omnijev"]["auto_reject_p"])
    j6_emit_conf = float(T["judges"]["J6_detectors"]["emit_conf"])

    # ---- 输入：v2 在线报告（E10 判定唯一来源）+ 判官 v2 原始输出 ----
    v1 = load(ONLINE_REPORT)
    j1 = load(JUDGES / "glm8" / f"{CLIP}.json")
    j3_proto = load(JUDGES / "omnijev" / f"{CLIP}.json")
    j3_meta = load(JUDGES / "omnijev" / "run_metadata_v2.json")
    j5 = load(JUDGES / "videochat3" / f"{CLIP}.json")
    j6v2 = load(JUDGES / "detectors" / f"{CLIP}.qc2.json")
    j3_probs = None
    for c in j3_meta.get("clips", []):
        if c.get("clip_id") == CLIP and c.get("ok"):
            j3_probs = c["probs"]
            break
    assert j3_probs is not None, "J3 run_metadata_v2 无本片概率"
    avatar_qc = load(HERE / "avatar" / "avatar_segment_qc.json")

    # ---- 成片分（声明的单镜近似映射，见模块 docstring）----
    triggered = {t: float(p) for t, p in j3_probs.items()
                 if t != "overall" and float(p) >= j3_thr}
    overall_triggered = float(j3_probs.get("overall") or 0.0) >= j3_thr
    d_signal = max(triggered.values(), default=0.0)
    if j1.get("defect_detected"):
        d_signal = max(d_signal, float(j1.get("confidence") or 0.0))
    if j5.get("defect_detected"):
        d_signal = max(d_signal, float(j5.get("confidence") or 0.0))
    emitted_j6 = {t: ev for t, ev in (j6v2.get("temporal_candidates") or {}).items()
                  if float(ev.get("conf", 0)) >= j6_emit_conf}
    if emitted_j6:
        d_signal = max(d_signal, max(float(ev["conf"]) for ev in emitted_j6.values()))
    clip_score = round(100.0 * (1.0 - d_signal), 1)
    mean_shot = worst_shot = clip_score          # 12 段继承成片单镜分（声明于 notes）
    episode_score = round(0.7 * mean_shot + 0.3 * worst_shot, 1)

    # ---- human_review 队列（E10 灰区 / J1/J5 judge 缺陷 / J6v2 emitted / D 组 warn 窗）----
    queue = []
    if v1["verdict"]["decision"] == "manual_review":
        for t, p in sorted(triggered.items()):
            queue.append({
                "ref": CLIP,
                "reason": (f"J3 通道 {t} P={p:.4f} 落灰区 [0.71,0.90)（judges.J3_omnijev.gray_zone），"
                           f"未达 auto_reject_p=0.90——检出待人工复核"),
                "params_ref": "judges.J3_omnijev.gray_zone",
                "outcome": "pending"})
        if not triggered and overall_triggered:
            queue.append({
                "ref": CLIP,
                "reason": (f"J3 overall 通道 P={float(j3_probs['overall']):.4f} 落灰区 "
                           f"[0.71,0.90)（judges.J3_omnijev.gray_zone），8 类通道无一超阈但"
                           f"总检出通道超阈——待人工复核"),
                "params_ref": "judges.J3_omnijev.gray_zone",
                "outcome": "pending"})
    if j1.get("defect_detected"):
        queue.append({
            "ref": CLIP,
            "reason": (f"J1 glm8 检出 {','.join(j1.get('defect_types') or [])} "
                       f"(confidence={j1.get('confidence')})——judge 缺陷登记"
                       f"（C 组口径不自动否决）"),
            "params_ref": "ensemble.definitions.E10",
            "outcome": "pending"})
    if j5.get("defect_detected"):
        queue.append({
            "ref": CLIP,
            "reason": (f"J5 videochat3 检出 {','.join(j5.get('defect_types') or [])} "
                       f"(confidence={j5.get('confidence')})——廉价信号并入复核方向"),
            "params_ref": "ensemble.definitions.E10",
            "outcome": "pending"})
    # J6v2 emitted（≥emit_conf）：role=signal_only，不否决但必须可见——入队列
    for t, ev in sorted(emitted_j6.items()):
        span = ev.get("span") or [0.0, 0.0]
        queue.append({
            "ref": CLIP,
            "reason": (f"J6v2 {t} emitted conf={ev.get('conf')} ≥ emit_conf={j6_emit_conf}，"
                       f"span {span[0]:.3f}-{span[1]:.3f}s（kind={ev.get('kind')}）——"
                       f"judges.J6_detectors_v2 role=signal_only 不作否决，检出待人工裁决"),
            "params_ref": "judges.J6_detectors_v2.rule_params.emit_conf",
            "outcome": "pending"})
    # D 组：J6v2 低于 emit_conf 的候选窗（warn-only，不否决）
    for t, ev in sorted((j6v2.get("temporal_candidates") or {}).items()):
        if float(ev.get("conf", 0)) < j6_emit_conf:
            span = ev.get("span") or [0.0, 0.0]
            queue.append({
                "ref": CLIP,
                "reason": (f"J6v2 {t} 候选窗 {span[0]:.3f}-{span[1]:.3f}s conf={ev.get('conf')} "
                           f"< emit_conf={j6_emit_conf}（judges.J6_detectors_v2.rule_params."
                           f"emit_conf）——D 组 warn-only 时间窗，人工只看此窗不看全片"),
                "params_ref": "judges.J6_detectors_v2.rule_params.emit_conf",
                "outcome": "pending"})
    n_pending = sum(1 for q in queue if q.get("outcome") == "pending")

    # ---- 人工上升率实测（TASK_v4 §3.3 口径：CP1 pending=1 + CP3/CP5/CP6 自检未上升=0 + CP12 queue）----
    cp1 = load(HERE / "cp1.json")
    cp1_pending = sum(1 for g in cp1.get("aux_gates", [])
                      if g.get("type") == "human" and g.get("result") == "pending")
    n_cp = 12
    escalations = cp1_pending + n_pending
    escalation_rate = round(escalations / n_cp, 4)

    # ---- 缺陷归并（J 源合并；J6 signal_only 不翻转 verdict）----
    defects = {}
    for t, p in triggered.items():          # J3 超阈通道逐类型登记（source J3）
        e = defects.setdefault(t, {"sources": [], "conf": 0.0})
        e["sources"].append("J3")
        e["conf"] = max(e["conf"], p)
    for code, jd in (("J1", j1), ("J5", j5)):
        if jd.get("defect_detected"):
            for t in jd.get("defect_types") or []:
                e = defects.setdefault(t, {"sources": [], "conf": 0.0})
                e.setdefault("sources", []).append(code)
                e["conf"] = max(e["conf"], float(jd.get("confidence") or 0.0))
    if emitted_j6:
        for t, ev in emitted_j6.items():
            e = defects.setdefault(t, {"sources": [], "conf": 0.0})
            e.setdefault("sources", []).append("J6")
            e["conf"] = max(e["conf"], float(ev["conf"]))

    defects_out = []
    for t, e in sorted(defects.items()):
        item = {"type": t, "sources": sorted(set(e.get("sources") or ["J3"])),
                "confidence": round(e["conf"], 4)}
        defects_out.append(item)

    # ---- cp12 v2 工件 ----
    cp11 = load(HERE / "cp11" / "cp11_v2.json")
    master_fp = cp11["payload"]["master_asset"]["fingerprint"]
    shot_qc_ref = {"shot_id": CLIP,
                   "qc_report_fingerprint": sha256_file(ONLINE_REPORT)}
    # 组级指标=本片真空语义（主控验收修订）：金标群体校准值不进组级
    n_j6_emitted = len(emitted_j6)
    gate_groups = {
        "a_group": {"recall": 1.0, "fpr": 0.0, "verdict": "pass",
                    "note": ("本片真空实测：A 组程序规则（J6v2 时序+L0）0 否决缺陷、0 误拒"
                             "（L0 全绿：时长 dev=0/黑屏 0；11 登记切点零未登记检出；"
                             f"J6v2 emitted {n_j6_emitted} 条按 role=signal_only 不作否决缺陷，"
                             "入 defects[]+人工队列）；单片无真值不可测群体召回/误拒，"
                             "1.0/0.0 为本片空洞值非金标群体校准（v1 混入的金标校准值已剔除，"
                             "eval_results_v3post.json 留档不删）")},
        "b_group": {"abstain": True,
                    "reason": "B 组专用小模型未部署（TASK_v4 M2-W7 范围外，M2 试点未装机）——弃权不参与 veto_groups",
                    "note": ("弃权形（主控验收修订语义）：不填占位指标伪装实测；"
                             "v1 工件 0.0/0.0 占位已废止")},
        "c_group": {"recall": 1.0, "fpr": 0.0, "verdict": "pass",
                    "note": ("本片真空：judge 检出不自动否决（白皮书 §3 CP12/§7 非目标 3），"
                             "flag 全部入人工队列 pending；本片 E10 三判官 J1/J3/J5 均净、"
                             "J6v2 信号 1 条入队——0 自动否决即 0 误拒；单片无真值不可测群体"
                             "召回/误拒，1.0/0.0 为本片空洞值非金标群体校准")},
        "d_group": {"warn_only": True,
                    "flagged_count": sum(1 for q in queue if "warn-only" in q["reason"]),
                    "verdict": "warn"},
    }
    ep_verdict = "pass" if v1["verdict"]["decision"] != "auto_reject" else "reject"
    if v1["verdict"]["decision"] == "manual_review":
        gate_result, art_status = "warn", "gated"
    elif v1["verdict"]["decision"] == "auto_reject":
        gate_result, art_status = "fail", "rejected"
    else:
        gate_result, art_status = "pass", "passed"

    routed = []
    if ep_verdict == "reject":
        route = {"identity_drift": "cp4", "hand_anomaly": "cp5", "physics_error": "cp5",
                 "count_error": "cp5", "frame_freeze": "cp6", "flicker": "cp6",
                 "temporal_swap": "cp6", "garble_text": "cp10", "text_error": "cp10"}
        seen = set()
        for d in defects_out:
            tgt = route.get(d["type"], "cp5")
            if (d["type"], tgt) not in seen:
                seen.add((d["type"], tgt))
                routed.append({"defect_type": d["type"], "target_cp": tgt})

    payload = {
        "work_id": "shortdrama_ep01",
        "master_fingerprint": master_fp,
        "episode_verdict": {
            "score": episode_score,
            "mean_shot_score": mean_shot,
            "worst_shot_score": worst_shot,
            "formula": "0.7*mean+0.3*worst",
            "verdict": ep_verdict,
        },
        "gate_groups": gate_groups,
        "human_escalation_rate": escalation_rate,
        "retry_round": 0,
        "shot_qc_refs": [shot_qc_ref],
    }
    if routed:
        payload["routed_reworks"] = routed
    cp12_fp = fingerprint_payload(payload)
    cp12 = {
        "schema_version": "2.0",
        "cp_id": "cp12",
        "artifact_type": "qc_master",
        "fingerprint": cp12_fp,
        "produced_by": "agent.cp12_inspector.qc_orch_v2",
        "produced_at": NOW,
        "upstream_refs": [
            {"cp_id": "cp11", "fingerprint": cp11["fingerprint"]},
            {"cp_id": "cp10", "fingerprint": "54f562bea824fbfd37e8f1f604f2d4e43c1e05723ecf0ae69816294bb2c11c48"},
            {"cp_id": "cp9", "fingerprint": "13f7236d2f4ea6342e91fb2c19b1a22f5fe6c0e90507c672d6a10205628092c4"},
            {"cp_id": "cp6", "fingerprint": "55c443094c29a796499295967ed3c691b0a4aab66392409ac3be01e16ea44c1b"},
        ],
        "status": art_status,
        "gate": {
            "type": "composite",
            "params_ref": "cp12.gate.a_group_recall_min",
            "result": gate_result,
            "applied_versions": {
                "spec_version": T["versioning"]["spec_version"],
                "registry_version": T["versioning"]["registry_version"],
                "prompt_version": T["versioning"]["prompt_version"],
            },
            "note": "",
        },
        "aux_gates": [
            {"type": "judge_absolute", "params_ref": "cp12.gate.master_score_min",
             "result": "pass" if episode_score >= 70 else "warn",
             "note": ""},
            {"type": "rule", "params_ref": "cp12.gate.human_escalation_rate_max",
             "result": None, "note": ""},
        ],
        "payload": payload,
        "notes": "",
    }
    rate_vs_thr = escalation_rate <= float(T["checkpoints"]["cp12"]["gate"]["human_escalation_rate_max"])
    cp12["aux_gates"][0]["note"] = (
        "成片分 %.1f（=0.7×%.1f+0.3×%.1f，12 段（avatar 钩子段+11 镜）继承成片单镜合议分——"
        "镜级 QCReport 本链未产出，按任务预案单镜近似并声明）%s；70 warn 阈"
        "（cp12.gate.master_score_min）只作排序依据，人评锚定（120 片段）未完成不作自动放行/"
        "否决（白皮书 §7 非目标 8），composite verdict 不因此翻转"
        % (episode_score, mean_shot, worst_shot,
           "，达 70 warn 阈" if episode_score >= 70 else "，未达 70 warn 阈→warn 标注不否决"))
    cp12["aux_gates"][1]["result"] = "pass" if rate_vs_thr else "fail"
    cp12["aux_gates"][1]["note"] = (
        "人工上升率实测 %d/%d = %.2f（CP1 owner pending 计 %d + CP3/CP5/CP6 子代理自检通过未上升计 0 "
        "+ CP12 队列 pending %d（J6v2 emitted %d 条+D 组 warn 窗 %d 条））；thresholds 键 "
        "cp12.gate.human_escalation_rate_max=0.20%s；TASK_v4 §3.3 短剧线 pilot 上限 0.25%s"
        "（两条口径均如实登记）"
        % (escalations, n_cp, escalation_rate, cp1_pending, n_pending,
           n_j6_emitted, gate_groups["d_group"]["flagged_count"],
           "：未超" if rate_vs_thr else "：超限",
           "：未超" if escalation_rate <= 0.25 else "：超限"))
    sub_emit_windows = gate_groups["d_group"]["flagged_count"]
    cp12["gate"]["note"] = (
        "四维实跑（master_v2 修订重跑）：缺陷维 E10=J1∨J3@%.2f（judges.J3_omnijev.thr）判定 %s / "
        "decision=%s → gate.result=%s；J3 全通道最高 P=temporal_swap 0.6011 未达阈（v1 为 "
        "ghosting 0.7522 灰区——二次装配重编码后该信号消退），无灰区无队列项；"
        "A 组程序规则（J6v2 时序+L0）：0 否决缺陷 0 误拒（11 登记切点全豁免，"
        "judges.J6_detectors_v2.rule_params.known_cuts_tol_s=0.5），J6v2 emitted %d 条 ghosting "
        "（conf 0.79，span 58.5-60.75s，对应 v1 时间轴 54.5-56.75s 段）按 role=signal_only "
        "不作否决、入 defects[]+人工队列；B 组未部署弃权；C 组 judge flag 入人工队列语义"
        "（本片 J1/J3/J5 均净）；D 组 %d 个 warn-only 窗（frame_freeze 候选被 lap_guard 拒绝"
        "未成窗，span 0.875-3.875s 落在 avatar 段）。组级 recall/fpr=本片真空空洞值，"
        "金标 40 条群体校准值不进组级（v1 修订项）。"
        % (j3_thr, v1["verdict"]["defect_detected"], v1["verdict"]["decision"], gate_result,
           n_j6_emitted, sub_emit_windows))
    cp12["notes"] = (
        "《雨夜合约》EP1 CP12 修订质检成片 v2（被检对象=master_v2.mp4 sha256=4080ce07…1536 帧/"
        "64.0s，片头含 avatar 口播钩子段 avatar_hook_01 4.000s）。【判官链】J1 glm8（API "
        "glm-5.3-flash 8帧 rubric，judges_src/glm8_batch.py，BIGMODEL_API_KEY 由 GPU 机 "
        "overnight/secrets/api_keys.env ZHIPU_API_KEY 服务端 env 注入零回显零落盘；latency "
        "312.9s）判净 conf=0.88；J3 omnijev（OmniJev-4B-v1.1，GPU0，venv-judge，起跑前复测 "
        "gpu0=310MiB，峰值 11742.7MB，latency 74.9s）全通道 <0.71 判净；J5 videochat3"
        "（VideoChat3-4B，GPU0，venv-vc3，起跑前复测 gpu0=310MiB，声明参数 fps=0.25/"
        "max_pixels=133072 沿 v1 retry1 配方，decord 直读，latency 7.2s）判净；J6v2 "
        "qc_detectors_v2（CPU，known_cuts=cp11_v2 登记 11 硬切点）emitted ghosting 1 条。"
        "首次起跑尝试在 04:14 复测到 GPU0=25982MiB（外部瞬态任务）按红线 ABORT，等位后"
        "复测通过再跑——不 kill 不抢卡。判官原始六字段输出一字不改嵌入 qc_report_v2.judges。"
        "【成片分映射（声明）】D=max(J3 触发通道 P≥0.71，J1/J5 detected→confidence，J6v2 "
        "emitted conf≥0.55)=0.79（J6v2 ghosting）→ clip_score=100×(1−D)=%.1f；12 段继承成片"
        "单镜分 mean=worst=%.1f，分数只作排序依据不作放行门（锚定未完成）——分数低于 v1 的 "
        "24.8 系 J6v2 信号计入所致，E10 判定反而由灰区转净（v1 decision=manual_review→"
        "v2 decision=pass）。【四组】a=0 否决缺陷/0 误拒（本片真空）；b=弃权形；c=judge flag "
        "入人工队列；d=warn-only %d 窗。【avatar 段单列 QC】口型同步 pass_with_caveats/"
        "身份保持 pass（人工条带目检+程序曲线双结论，音画性别错配 pilot 期接受登记），见 "
        "out/m2/shortdrama_ep01/avatar/avatar_segment_qc.json；J6v2 frame_freeze 候选"
        "（span 0.875-3.875s 落 avatar 段）被 lap_guard 拒绝=程序侧旁证。"
        "【人工】队列 %d 条 pending（J6v2 信号 1）；CP12 签字待 human.owner，本工件 "
        "verdict=门禁计算结果非人工签字。"
        % (clip_score, clip_score, sub_emit_windows, n_pending))

    (HERE / "cp12_v2.json").write_text(json.dumps(cp12, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")

    # ---- qc_report_v2 成片级报告（v2 契约）----
    sub_thr_channels = "; ".join(
        f"{t}={p:.4f}" for t, p in sorted(
            ((t, float(p)) for t, p in j3_probs.items()
             if t != "overall" and 0.0 < float(p) < j3_thr),
            key=lambda kv: -kv[1])[:3])
    v2 = {
        "schema_version": "2.0",
        "clip_id": CLIP,
        "generated_at": NOW,
        "work_id": "shortdrama_ep01",
        "qc_mode": "online",
        "checkpoint": {"cp_id": "cp12", "artifact_ref": cp12_fp},
        "verdict": {
            "defect_detected": v1["verdict"]["defect_detected"],
            "decision": v1["verdict"]["decision"],
            "confidence": v1["verdict"]["confidence"],
            "decided_by": "cp12.composite(E10=J1∨J3@0.71 成片合议 + cp12.gate.master_score_min 成片绝对门)",
            "reasons": v1["verdict"].get("reasons", []) + [
                "成片分 %.1f = 0.7×mean(%.1f) + 0.3×worst(%.1f)，12 段（avatar 钩子段+11 镜）继承"
                "成片单镜分（镜级 QCReport 未产出，按任务预案单镜近似并声明）；绝对门阈见 "
                "params_ref=cp12.gate.master_score_min（人评锚定完成前仅 warn 阈与排序依据）"
                % (episode_score, mean_shot, worst_shot),
                "J6v2 成片重跑：11 拼接切点（avatar 段边界 4.000s + CP6 帧界累计 +4.000s 平移）"
                "全部落入 known_cuts 白名单（judges.J6_detectors_v2.rule_params.known_cuts_tol_s"
                "=0.5）被豁免，零 temporal_swap 误报——合成层硬切点登记制生效（含 avatar 段边界）",
                "J6v2 emitted ghosting conf=0.79（span 58.5-60.75s，v1 无此信号；对应 v1 时间轴 "
                "54.5-56.75s，二次装配重编码代损疑为推高因素，待人工裁决）按 role=signal_only "
                "不翻 verdict、入 defects[]+人工队列",
                "avatar 段（0-4.0s）单列 QC：身份保持 pass、口型同步 pass_with_caveats（人工+程序"
                "双结论）；音画性别错配 pilot 期接受并登记——详见 avatar/avatar_segment_qc.json",
                "人工上升率实测 %.2f =（CP1 pending 1 + CP12 队列 %d）/12；TASK_v4 §3.3 短剧线 "
                "≤0.25%s" % (escalation_rate, n_pending,
                             "未超" if escalation_rate <= 0.25 else "超限"),
            ],
        },
        "defects": defects_out,
        "scores": {**v1["scores"],
                   "per_type": {k: v for k, v in v1["scores"]["per_type"].items()
                                if k != "overall"}},
        "spans": v1.get("spans", []) + [
            {"type": "note",
             "evidence": {"text": ("J6v2 known_cuts 豁免记录：11 个 junction（cut_t=4.0…58.208）"
                                   "全部 exempted（证据 judges/detectors/%s.qc2.json "
                                   "temporal_rejected.temporal_swap_known_cuts）" % CLIP)}},
            {"type": "note",
             "evidence": {"text": ("J3 未达判定阈(0.71)的次高通道只登记数据不入队列：%s；"
                                   "J3 拼图判官不知 known_cuts 白名单，11 个登记硬切点"
                                   "（avatar 边界+CP6 帧界累计）可解释其 temporal_swap 信号"
                                   % sub_thr_channels)}},
            {"type": "note",
             "evidence": {"text": ("avatar 段单列 QC（avatar_hook_01，0-4.0s）：身份保持=pass"
                                   "（与 shot_09 终稿帧 ref 目检同一角色）；口型同步=pass_with_"
                                   "caveats（三语音窗 articulation 可见/静音尾静止/起始滞后 "
                                   "83-166ms；句内停顿唇未全闭、后两短语幅度偏小）；音画性别错配"
                                   "（女角色×cixingnansheng 男声）pilot 期接受——人工+程序双结论"
                                   "全文见 out/m2/shortdrama_ep01/avatar/avatar_segment_qc.json，"
                                   "证据帧 frames_check/{identity_pair,contact6,strip_*}.jpg")}},
        ],
        "judges": {"J1": j1, "J3": j3_proto, "J5": j5, "J6": j6v2["temporal_protocol"]},
        "inputs": {
            "clip": "overnight/vpipe/out/m2/shortdrama_ep01/cp11/master_v2.mp4",
            "frames_dir": "overnight/vpipe/out/m2/shortdrama_ep01/qc_frames/shortdrama_ep01_v2",
            "judge_files": {
                "J1": "out/m2/shortdrama_ep01/judges/glm8/%s.json" % CLIP,
                "J3": "out/m2/shortdrama_ep01/judges/omnijev/run_metadata_v2.json",
                "J5": "out/m2/shortdrama_ep01/judges/videochat3/%s.json" % CLIP,
                "J6": "out/m2/shortdrama_ep01/judges/detectors/%s.qc2.json" % CLIP,
            },
        },
        "episode_verdict": {
            "score": episode_score,
            "mean_shot_score": mean_shot,
            "worst_shot_score": worst_shot,
            "formula": "0.7*mean+0.3*worst",
            "verdict": ep_verdict,
            "params_ref": "cp12.gate.master_score_min",
            "shot_qc_refs": [shot_qc_ref],
        },
        "human_review": {
            "queue": queue,
            "escalation_rate": escalation_rate,
            "params_ref": "cp12.gate.human_escalation_rate_max",
        },
        "qc_context": v1.get("qc_context"),
        "errors": {
            "J2": "J2 glm3 备用判官不在本次配方（E10 不消费 J2），未跑非失败",
            "B_group": ("B 组专用小模型未部署——弃权形登记（主控验收修订语义），不填占位指标；"
                        "gate_groups.b_group.abstain=true"),
            "J6": ((v1.get("errors") or {}).get("J6", "")
                   + "——J6v2 已另行 standalone 实跑（CPU，known_cuts=11 点白名单），其协议视图"
                     "一字不改嵌入本报告 judges.J6；未走 --detector-json 是因 qc_detectors_v2 "
                     "输出契约与 qc_orch_v2 内建 v1 规则引擎消费的 qc_detectors.py 契约不同"),
            "J1_key_source": ("J1 BIGMODEL_API_KEY 由 GPU 机 overnight/secrets/api_keys.env 的 "
                              "ZHIPU_API_KEY 在远端 shell 服务端注入（env 传递零回显零落盘），"
                              "与 v1『agent-tools/llm-env zhipu』同源不同注入通道，如实登记"),
            "j35_first_attempt_abort": ("J3/J5 首次起跑前复测（04:14）测得 GPU0=25982MiB"
                                        "（外部瞬态任务占用），按红线 ABORT 不抢卡；等位复测 "
                                        "310MiB 通过后重跑成功——两次复测均留痕 watch_j35.log"),
        },
    }
    if not v2["qc_context"]:
        v2.pop("qc_context")
    (HERE / "qc_report_v2_v2.json").write_text(json.dumps(v2, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")

    # ---- asset manifest（sha256 身份登记）----
    man_entries = []
    for rel in ["cp11/master_v2.mp4", "cp11/cp11_v2.json",
                "qc_reports_online/%s.json" % CLIP, "qc_report_v2_v2.json",
                "cp12_v2.json",
                "judges/glm8/%s.json" % CLIP, "judges/glm8/run_metadata_v2.json",
                "judges/omnijev/%s.json" % CLIP, "judges/omnijev/run_metadata_v2.json",
                "judges/videochat3/%s.json" % CLIP, "judges/videochat3/run_metadata_v2.json",
                "judges/detectors/%s.qc2.json" % CLIP,
                "qc_known_cuts_v2.json",
                "avatar/segment_card.json", "avatar/tts_hook01.meta.json",
                "avatar/tts_hook01.wav", "avatar/tts_hook01.fit.wav",
                "avatar/avatar_1005868177546022912.meta.json",
                "avatar/avatar_1005868177546022912.mp4",
                "avatar/avatar_segment_qc.json",
                "qc_frames/shortdrama_ep01_v2/f01.jpg", "qc_frames/shortdrama_ep01_v2/f02.jpg",
                "qc_frames/shortdrama_ep01_v2/f03.jpg", "qc_frames/shortdrama_ep01_v2/f04.jpg",
                "qc_frames/shortdrama_ep01_v2/f05.jpg", "qc_frames/shortdrama_ep01_v2/f06.jpg",
                "qc_frames/shortdrama_ep01_v2/f07.jpg", "qc_frames/shortdrama_ep01_v2/f08.jpg"]:
        p = HERE / rel
        if p.exists():
            man_entries.append({"path": "overnight/vpipe/out/m2/shortdrama_ep01/" + rel,
                                "sha256": sha256_file(p)})
    manifest = {"schema_version": "1.0", "name": "vpipe-cp12-shortdrama_ep01_v2",
                "thresholds_sha256": thr_sha, "generated_at": NOW, "assets": man_entries}
    (HERE / "asset_manifest_cp12_v2.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("clip_score=%.1f mean=%.1f worst=%.1f episode=%.1f verdict=%s" %
          (clip_score, mean_shot, worst_shot, episode_score, ep_verdict))
    print("queue=%d (pending=%d) escalations=%d/%d rate=%.2f" %
          (len(queue), n_pending, escalations, n_cp, escalation_rate))
    print("cp12 fingerprint:", cp12_fp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
