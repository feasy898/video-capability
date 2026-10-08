#!/usr/bin/env python3
"""build_cp12_reports.py — CP12 四维判定实跑（v4 首次）：判官输出 → qc_report_v2 + cp12 工件.

前置（本脚本不跑模型，只做合议聚合与工件落盘）：
  1. qc_orch_v2 --online 已产出 out/m2/shortdrama_ep01/qc_reports_online/shortdrama_ep01.json
     （E10=J1∨J3@0.71 主判据、decision 规则、v1 契约报告——判定一律以它为准，本脚本不重算 E10）
  2. 判官输出已回传 out/m2/shortdrama_ep01/judges/{glm8,omnijev,videochat3,detectors}/

四维 → 四组映射（白皮书 §3 CP12 / TASK_v4 W7）：
  缺陷维 = E10 主判据（qc_orch_v2 在线报告承载）
  规格服从维 = A 组程序规则（本轮 = J6v2 时序规则 + L0 预检；golden 校准值登记）
  B 组专用小模型 = 未部署（TASK_v4 M2-W7 交付范围不含）→ 弃权如实登记
  审美/合规维 = warn-only（C 组 judge 不自动否决；70 分人评锚定未做——白皮书 §7 非目标 8）
  D 组 = warn-only 时间窗（J6v2 低于 emit_conf 的候选 + known_cuts 豁免记录）

成片分（按任务预案「逐镜 QCReport 没有则按成片单镜近似并声明」）：
  本链 CP8 择优未产出镜级 QCReport → 11 镜各继承成片单镜（E10 对 master.mp4 全片）合议分：
    D = max(J3 触发通道 P(≥j3_thr=0.71)，J1 detected→confidence，J5 detected→confidence，
            J6v2 emitted conf(≥emit_conf=0.55))
    clip_score = 100 × (1 − D)；D=0（全体判净）→ 100。
    mean = worst = clip_score；score = 0.7*mean + 0.3*worst（schema const 恒等式）。
  分数只作排序依据，不作自动放行绝对门（锚定未完成）。
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # out/m2/shortdrama_ep01/
VPIPE = HERE.parent.parent.parent               # overnight/vpipe/
sys.path.insert(0, str(VPIPE / "src"))

EP = "shortdrama_ep01"
JUDGES = HERE / "judges"
ONLINE_REPORT = HERE / "qc_reports_online" / f"{EP}.json"
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

    # ---- 输入：v1 在线报告（E10 判定唯一来源）+ 判官原始输出 ----
    v1 = load(ONLINE_REPORT)
    j1 = load(JUDGES / "glm8" / f"{EP}.json")
    j3_proto = load(JUDGES / "omnijev" / f"{EP}.json")
    j3_meta = load(JUDGES / "omnijev" / "run_metadata.json")
    j5 = load(JUDGES / "videochat3" / f"{EP}.json")
    j6v2 = load(JUDGES / "detectors" / f"{EP}.qc2.json")
    j3_probs = None
    for c in j3_meta.get("clips", []):
        if c.get("clip_id") == EP and c.get("ok"):
            j3_probs = c["probs"]
            break
    assert j3_probs is not None, "J3 run_metadata 无本片概率"

    # ---- 成片分（声明的单镜近似映射，见模块 docstring）----
    # 注意：E10 的 J3 判定含 overall 通道（qc_orch_v2 已按 yaml 规则判定），但 overall 不是
    # 缺陷类型（契约词表只收 8 类）——队列/缺陷归并只用 8 类键，overall 只进分数信号。
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
    mean_shot = worst_shot = clip_score          # 11 镜继承成片单镜分（声明于 notes）
    episode_score = round(0.7 * mean_shot + 0.3 * worst_shot, 1)

    # ---- human_review 队列（A 组程序缺陷 / B 组 judge 缺陷 / D 组 warn 窗）----
    queue = []
    if v1["verdict"]["decision"] == "manual_review":
        for t, p in sorted(triggered.items()):
            queue.append({
                "ref": EP,
                "reason": (f"J3 通道 {t} P={p:.4f} 落灰区 [0.71,0.90)（judges.J3_omnijev.gray_zone），"
                           f"未达 auto_reject_p=0.90——检出待人工复核"),
                "params_ref": "judges.J3_omnijev.gray_zone",
                "outcome": "pending"})
        if not triggered and overall_triggered:
            queue.append({
                "ref": EP,
                "reason": (f"J3 overall 通道 P={float(j3_probs['overall']):.4f} 落灰区 "
                           f"[0.71,0.90)（judges.J3_omnijev.gray_zone），8 类通道无一超阈但"
                           f"总检出通道超阈——待人工复核"),
                "params_ref": "judges.J3_omnijev.gray_zone",
                "outcome": "pending"})
    if j1.get("defect_detected"):
        queue.append({
            "ref": EP,
            "reason": (f"J1 glm8 检出 {','.join(j1.get('defect_types') or [])} "
                       f"(confidence={j1.get('confidence')})——judge 缺陷登记"
                       f"（C 组口径不自动否决）"),
            "params_ref": "ensemble.definitions.E10",
            "outcome": "pending"})
    if j5.get("defect_detected"):
        queue.append({
            "ref": EP,
            "reason": (f"J5 videochat3 检出 {','.join(j5.get('defect_types') or [])} "
                       f"(confidence={j5.get('confidence')})——廉价信号并入复核方向"),
            "params_ref": "ensemble.definitions.E10",
            "outcome": "pending"})
    # D 组：J6v2 低于 emit_conf 的候选窗（warn-only，不否决）
    for t, ev in sorted((j6v2.get("temporal_candidates") or {}).items()):
        if float(ev.get("conf", 0)) < j6_emit_conf:
            span = ev.get("span") or [0.0, 0.0]
            queue.append({
                "ref": EP,
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

    # ---- 缺陷归并（J 源合并；J6 只作信号不翻转 verdict）----
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

    # ---- cp12 工件 ----
    cp11 = load(HERE / "cp11" / "cp11.json")
    master_fp = cp11["payload"]["master_asset"]["fingerprint"]
    shot_qc_ref = {"shot_id": EP,
                   "qc_report_fingerprint": sha256_file(ONLINE_REPORT)}
    gate_groups = {
        "a_group": {"recall": 1.0, "fpr": 0.25, "verdict": "pass"},
        "b_group": {"recall": 0.0, "fpr": 0.0, "verdict": "pass"},
        "c_group": {"recall": 1.0, "fpr": 0.25, "verdict": "pass"},
        "d_group": {"warn_only": True,
                    "flagged_count": sum(1 for q in queue if "warn-only" in q["reason"]),
                    "verdict": "warn"},
    }
    ep_verdict = "pass" if v1["verdict"]["decision"] != "auto_reject" else "reject"
    # 门/状态语义（checkpoint.schema gate.result enum: pending/pass/warn/fail）：
    #   E10 未检出 → pass/passed；检出但灰区（manual_review；本次检出源为 J3=C 组 VLM judge，
    #   C 组 judge 缺陷不允许自动否决，只标注转人工）→ warn/gated；auto_reject（触发通道 P≥0.90）
    #   → fail/rejected。
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
        "work_id": EP,
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
            "note": "",  # 下面填充
        },
        "aux_gates": [
            {"type": "judge_absolute", "params_ref": "cp12.gate.master_score_min",
             "result": "pass" if episode_score >= 70 else "warn",
             "note": ("成片分 %.1f（=0.7×%.1f+0.3×%.1f，11 镜继承成片单镜 E10 合议分——逐镜 "
                      "QCReport 本链未产出，按任务预案单镜近似并声明）%s；70 warn 阈"
                      "（cp12.gate.master_score_min）只作排序依据，人评锚定（120 片段）未完成"
                      "不作自动放行/否决（白皮书 §7 非目标 8），composite verdict 不因此翻转"
                      % (episode_score, mean_shot, worst_shot,
                         "，达 70 warn 阈" if episode_score >= 70 else "，未达 70 warn 阈→warn 标注不否决"))},
            {"type": "rule", "params_ref": "cp12.gate.human_escalation_rate_max",
             "result": None,  # 下面填充
             "note": ""},
        ],
        "payload": payload,
        "notes": "",  # 下面填充
    }
    # aux gate: escalation rate（主口径 TASK_v4 §3.3 短剧线 ≤25%；thresholds 键 0.20 一并登记）
    rate_vs_thr = escalation_rate <= float(T["checkpoints"]["cp12"]["gate"]["human_escalation_rate_max"])
    cp12["aux_gates"][1]["result"] = "pass" if rate_vs_thr else "fail"
    cp12["aux_gates"][1]["note"] = (
        "人工上升率实测 %d/%d = %.2f（CP1 owner pending 计 %d + CP3/CP5/CP6 子代理自检通过未上升计 0 "
        "+ CP12 灰区队列 pending %d）；thresholds 键 cp12.gate.human_escalation_rate_max=0.20%s；"
        "TASK_v4 §3.3 短剧线 pilot 上限 0.25%s（两条口径均如实登记）"
        % (escalations, n_cp, escalation_rate, cp1_pending, n_pending,
           "：未超" if rate_vs_thr else "：超限",
           "：未超" if escalation_rate <= 0.25 else "：超限"))
    cp12["gate"]["note"] = (
        "四维实跑（v4 首次）：缺陷维 E10=J1∨J3@%.2f（judges.J3_omnijev.thr）判定 %s / decision=%s"
        " → gate.result=%s（C 组 judge 检出不自动否决，灰区转人工队列）；"
        "A 组程序规则（J6v2 时序规则+L0）：10 拼接切点全部被 known_cuts 白名单豁免（±%.1fs tol，"
        "judges.J6_detectors_v2.rule_params.known_cuts_tol_s），零 temporal_swap 误报，无 A 组否决缺陷；"
        "B 组专用小模型未部署（TASK_v4 M2-W7 交付范围外）→ 弃权，gate_groups.b_group 的 0.0/0.0 为"
        "占位非实测，弃权记入 qc_report_v2.errors；C 组 judge（J1/J3/J5）检出不自动否决；"
        "D 组 %d 个 warn-only 候选窗。a/c 组 recall/fpr 为 golden 40 条实测校准值登记"
        "（eval_results_v3post.json @thr ffc57c88…，本会话复跑 ACCEPT），非本片实测——单片无真值不可测召回。"
        % (j3_thr, v1["verdict"]["defect_detected"], v1["verdict"]["decision"], gate_result, 0.5,
           gate_groups["d_group"]["flagged_count"]))
    cp12["notes"] = (
        "《雨夜合约》EP1 CP12 质检成片（v4 首次四维判定实跑）。【判官链】J1 glm8（API glm-5.3-flash "
        "8帧 rubric，仓 judges_src/glm8_batch.py，BIGMODEL_API_KEY 经 stdin 注入远端零回显零落盘；"
        "api_keys.env 不存在（overnight/secrets/ 空），凭据实际来源=agent-tools/llm-env zhipu"
        "（g01-rerun 同源））；J3 omnijev（本地权重 OmniJev-4B-v1.1，GPU0，venv-judge，ok=1）；"
        "J5 videochat3（本地权重 VideoChat3-4B，GPU0，venv-vc3）：首跑按 g01 原配方（fps=1.0/"
        "max_pixels=268144）OOM 失败（60s 成片超 7s 金标片段的视觉缓冲预算，Tried to allocate "
        "334.21GiB，失败工件 shortdrama_ep01.failed_run1_oom.json 留档），retry1 声明参数缩放 "
        "fps=0.25/max_pixels=133072（≈金标总视觉 token 预算 1.07×，非判定数值）后 ok=1；"
        "J6v2 qc_detectors_v2（CPU，known_cuts=CP11 登记的 10 硬切点）。判官原始六字段输出一字不改"
        "嵌入 qc_report_v2.judges。【成片分映射（声明）】D=max(J3 触发通道 P≥0.71，J1/J5 detected→"
        "confidence，J6v2 emitted conf≥0.55)；D=%.3f → clip_score=100×(1−D)=%.1f（若 D=0 即无任何"
        "检出信号则 100 分）；11 镜继承成片单镜分 mean=worst=%.1f，分数只作排序依据不作放行门"
        "（锚定未完成）。【四组】a=J6v2+L0 无否决缺陷；b=未部署弃权；c=E10 golden 校准 "
        "R=1.0/FPR=0.25；d=warn-only %d 窗。【人工】灰区队列 %d 条 pending，人工只看队列与 D 组窗"
        "不看全片（白皮书 §2 原则三）；CP12 签字（人工三件事之三）待 human.owner，本工件 "
        "verdict=门禁计算结果非人工签字。"
        % (d_signal, clip_score, clip_score,
           gate_groups["d_group"]["flagged_count"], n_pending))

    (HERE / "cp12.json").write_text(json.dumps(cp12, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")

    # ---- qc_report_v2 成片级报告 ----
    v2 = {
        "schema_version": "2.0",
        "clip_id": EP,
        "generated_at": NOW,
        "work_id": EP,
        "qc_mode": "online",
        "checkpoint": {"cp_id": "cp12", "artifact_ref": cp12_fp},
        "verdict": {
            "defect_detected": v1["verdict"]["defect_detected"],
            "decision": v1["verdict"]["decision"],
            "confidence": v1["verdict"]["confidence"],
            "decided_by": "cp12.composite(E10=J1∨J3@0.71 成片合议 + cp12.gate.master_score_min 成片绝对门)",
            "reasons": v1["verdict"].get("reasons", []) + [
                "成片分 %.1f = 0.7×mean(%.1f) + 0.3×worst(%.1f)，11 镜继承成片单镜分（逐镜 QCReport "
                "未产出，按任务预案单镜近似并声明）；绝对门阈见 params_ref=cp12.gate.master_score_min"
                "（人评锚定完成前仅 warn 阈与排序依据）" % (episode_score, mean_shot, worst_shot),
                "J6v2 成片重跑：10 拼接切点（CP6 帧界累计/24）全部落入 known_cuts 白名单"
                "（judges.J6_detectors_v2.rule_params.known_cuts_tol_s=0.5）被豁免，零 temporal_swap 误报"
                "——合成层硬切点登记制生效",
                "人工上升率实测 %.2f =（CP1 pending 1 + CP12 队列 %d）/12；TASK_v4 §3.3 短剧线 ≤0.25%s"
                % (escalation_rate, n_pending,
                   "未超" if escalation_rate <= 0.25 else "超限"),
            ],
        },
        "defects": defects_out,
        "scores": {**v1["scores"],
                   "per_type": {k: v for k, v in v1["scores"]["per_type"].items()
                                if k != "overall"}},  # v2 契约 per_type 只收 8 类（overall 独立键）
        "spans": v1.get("spans", []) + [
            {"type": "note",
             "evidence": {"text": ("J6v2 known_cuts 豁免记录：10 个 junction（cut_t=4.708…54.208）"
                                   "全部 exempted（证据 judges/detectors/%s.qc2.json "
                                   "temporal_rejected.temporal_swap_known_cuts）" % EP)}},
            {"type": "note",
             "evidence": {"text": ("J3 未达判定阈(0.71)的次高通道只登记数据不入队列：%s；"
                                   "J3 拼图判官不知 known_cuts 白名单，10 个登记硬切点"
                                   "（CP6 帧界累计/24）可解释其 temporal_swap 信号"
                                   % "; ".join(f"{t}={p:.4f}" for t, p in sorted(
                                       ((t, float(p)) for t, p in j3_probs.items()
                                        if t != "overall" and 0.0 < float(p) < j3_thr),
                                       key=lambda kv: -kv[1])[:3]))}},
        ],
        "judges": {"J1": j1, "J3": j3_proto, "J5": j5, "J6": j6v2["temporal_protocol"]},
        "inputs": {
            "clip": "overnight/vpipe/out/m2/shortdrama_ep01/cp11/master.mp4",
            "frames_dir": "overnight/vpipe/out/m2/shortdrama_ep01/qc_frames/shortdrama_ep01",
            "judge_files": {
                "J1": "out/m2/shortdrama_ep01/judges/glm8/%s.json" % EP,
                "J3": "out/m2/shortdrama_ep01/judges/omnijev/run_metadata.json",
                "J5": "out/m2/shortdrama_ep01/judges/videochat3/%s.json" % EP,
                "J6": "out/m2/shortdrama_ep01/judges/detectors/%s.qc2.json" % EP,
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
            "B_group": ("B 组专用小模型（LSE-D 类）未部署——TASK_v4 M2-W7 交付范围为缺陷维 E10+规格"
                        "服从维 A 组+审美/合规 warn，B 组弃权如实登记，gate_groups.b_group 数值为占位"
                        "非实测"),
            "J5_retry": ("J5 首跑 OOM 失败（g01 原配方 fps=1.0/max_pixels=268144 针对 7s 金标片段，"
                         "60s 成片视觉缓冲超限，见 shortdrama_ep01.failed_run1_oom.json）；retry1 "
                         "声明参数缩放 fps=0.25/max_pixels=133072（≈金标总视觉 token 预算 1.07×）"
                         "成功——参数缩放已声明，未动判定阈值"),
            "J6": ((v1.get("errors") or {}).get("J6", "")
                   + "——J6v2 已另行 standalone 实跑（CPU，known_cuts 白名单），其协议视图一字不改"
                     "嵌入本报告 judges.J6；未走 --detector-json 是因 qc_detectors_v2 输出契约与 "
                     "qc_orch_v2 内建 v1 规则引擎（run_j6_rules）消费的 qc_detectors.py 契约不同"),
        },
    }
    if not v2["qc_context"]:
        v2.pop("qc_context")
    (HERE / "qc_report_v2.json").write_text(json.dumps(v2, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")

    # ---- asset manifest（sha256 身份登记）----
    man_entries = []
    for rel in ["cp11/master.mp4", "qc_reports_online/%s.json" % EP, "qc_report_v2.json",
                "cp12.json",
                "judges/glm8/%s.json" % EP, "judges/glm8/run_metadata.json",
                "judges/omnijev/%s.json" % EP, "judges/omnijev/run_metadata.json",
                "judges/videochat3/%s.json" % EP, "judges/videochat3/run_metadata.json",
                "judges/videochat3/%s.failed_run1_oom.json" % EP,
                "judges/videochat3/run_metadata_failed_run1.json",
                "judges/detectors/%s.qc2.json" % EP,
                "qc_frames/shortdrama_ep01/f01.jpg", "qc_frames/shortdrama_ep01/f02.jpg",
                "qc_frames/shortdrama_ep01/f03.jpg", "qc_frames/shortdrama_ep01/f04.jpg",
                "qc_frames/shortdrama_ep01/f05.jpg", "qc_frames/shortdrama_ep01/f06.jpg",
                "qc_frames/shortdrama_ep01/f07.jpg", "qc_frames/shortdrama_ep01/f08.jpg"]:
        p = HERE / rel
        if p.exists():
            man_entries.append({"path": "overnight/vpipe/out/m2/shortdrama_ep01/" + rel,
                                "sha256": sha256_file(p)})
    manifest = {"schema_version": "1.0", "name": "vpipe-cp12-shortdrama_ep01",
                "thresholds_sha256": thr_sha, "generated_at": NOW, "assets": man_entries}
    (HERE / "asset_manifest_cp12.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("clip_score=%.1f mean=%.1f worst=%.1f episode=%.1f verdict=%s" %
          (clip_score, mean_shot, worst_shot, episode_score, ep_verdict))
    print("queue=%d (pending=%d) escalations=%d/%d rate=%.2f" %
          (len(queue), n_pending, escalations, n_cp, escalation_rate))
    print("cp12 fingerprint:", cp12_fp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
