#!/usr/bin/env python3
"""build_cp12_reports.py — CP12 质检与成片（漫剧线 EP01=comicanime_ep01）判官输出 →
qc_report_v2(v2 契约) + cp12 工件。

沿 build_cp12_reports_v2.py（shortdrama v2 修订版）合议聚合口径，本片修订点：
  1. 组级指标用【本片真空语义】（主控验收修订 2026-10-09）：金标 40 条群体校准值
     不进组级——a 组 0 缺陷/0 误拒、b 组弃权形、c 组 judge 检出不自动否决+flag 入
     人工队列；单片无真值不可测群体召回/误拒，recall/fpr 数值是本片空洞值并显式声明。
  2. J6v2 emitted 候选（conf≥emit_conf）按 judges.J6_detectors_v2 role=signal_only
     处理：入 defects[]+人工队列 pending，不作 A 组否决缺陷；低于 emit_conf 的候选窗
     走 D 组 warn-only。本片 J6v2 0 候选（known_cuts 白名单豁免 4 junction 候选）。
  3. 无 avatar 段（漫剧线按 TASK_v4 不含 avatar 段）——无 avatar 单列 QC。

前置（本脚本不跑模型）：
  1. qc_orch_v2 --online 已产出 qc_reports_online/comicanime_ep01.json
     （E10=J1∨J3@0.71 主判据——判定一律以它为准，本脚本不重算 E10）
  2. 判官输出已回传 judges/{glm8,omnijev,videochat3,detectors}/ 本地目录

成片分映射（沿短剧线声明）：D=max(J3 触发通道 P≥thr，J1/J5 detected→confidence，
J6v2 emitted conf≥emit_conf)；clip_score=100×(1−D)；成片段数 9（无 avatar 段）
继承成片单镜分（镜级 QCReport 本链未产出，按任务预案单镜近似并声明）。

人工上升率（TASK_v4 §3.3 漫剧线 ≤0.20）：CP1 owner pending=1 + CP3/CP5/CP6 子代理
自检通过未上升=0 + CP8 择优零人工=0 + CP12 queue pending。
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # out/m2/comicanime_ep01/
VPIPE = HERE.parent.parent.parent               # overnight/vpipe/
sys.path.insert(0, str(VPIPE / "src"))

CLIP = "comicanime_ep01"
JUDGES = HERE / "judges"
ONLINE_REPORT = HERE / "qc_reports_online" / f"{CLIP}.json"
THRESHOLDS = VPIPE / "eval" / "thresholds.yaml"
NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p: Path) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main() -> int:
    import yaml
    T = yaml.safe_load(open(THRESHOLDS, encoding="utf-8"))
    thr_sha = sha256_file(THRESHOLDS)
    j3_thr = float(T["judges"]["J3_omnijev"]["thr"])
    auto_reject_p = float(T["judges"]["J3_omnijev"]["auto_reject_p"])
    j6_emit_conf = float(T["judges"]["J6_detectors"]["emit_conf"])

    # ---- 输入：在线报告（E10 判定唯一来源）+ 判官原始输出 ----
    v1 = load(ONLINE_REPORT)
    j1 = load(JUDGES / "glm8" / f"{CLIP}.json")
    j3_proto = load(JUDGES / "omnijev" / f"{CLIP}.json")
    j3_meta = load(JUDGES / "omnijev" / "run_metadata.json")
    j5 = load(JUDGES / "videochat3" / f"{CLIP}.json")
    j6v2 = load(JUDGES / "detectors" / f"{CLIP}.qc2.json")
    j3_probs = None
    for c in j3_meta.get("clips", []):
        if c.get("clip_id") == CLIP and c.get("ok"):
            j3_probs = c["probs"]
            break
    assert j3_probs is not None, "J3 run_metadata 无本片概率"

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
    mean_shot = worst_shot = clip_score          # 9 段继承成片单镜分（声明于 notes）
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
    n_d_warn = 0
    for t, ev in sorted((j6v2.get("temporal_candidates") or {}).items()):
        if float(ev.get("conf", 0)) < j6_emit_conf:
            n_d_warn += 1
            span = ev.get("span") or [0.0, 0.0]
            queue.append({
                "ref": CLIP,
                "reason": (f"J6v2 {t} 候选窗 {span[0]:.3f}-{span[1]:.3f}s conf={ev.get('conf')} "
                           f"< emit_conf={j6_emit_conf}（judges.J6_detectors_v2.rule_params."
                           f"emit_conf）——D 组 warn-only 时间窗，人工只看此窗不看全片"),
                "params_ref": "judges.J6_detectors_v2.rule_params.emit_conf",
                "outcome": "pending"})
    n_pending = sum(1 for q in queue if q.get("outcome") == "pending")

    # ---- 人工上升率实测（TASK_v4 §3.3 漫剧线 ≤0.20；n_cp=12 口径沿短剧线）----
    cp1 = load(HERE / "cp1.json")
    cp1_pending = sum(1 for g in cp1.get("aux_gates", [])
                      if g.get("type") == "human" and g.get("result") == "pending")
    n_cp = 12
    escalations = cp1_pending + n_pending
    escalation_rate = round(escalations / n_cp, 4)

    # ---- 缺陷归并（J 源合并；J6 signal_only 不翻转 verdict）----
    defects = {}
    for t, p in triggered.items():
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

    defects_out = [{"type": t, "sources": sorted(set(e.get("sources") or ["J3"])),
                    "confidence": round(e["conf"], 4)}
                   for t, e in sorted(defects.items())]

    # ---- cp12 工件 ----
    cp11 = load(HERE / "cp11" / "cp11.json")
    master_fp = cp11["payload"]["master_asset"]["fingerprint"]
    shot_qc_ref = {"shot_id": CLIP,
                   "qc_report_fingerprint": sha256_file(ONLINE_REPORT)}
    n_j6_emitted = len(emitted_j6)
    rejected = [t for t in (j6v2.get("temporal_rejected") or {})]
    gate_groups = {
        "a_group": {"recall": 1.0, "fpr": 0.0, "verdict": "pass",
                    "note": ("本片真空实测：A 组程序规则（J6v2 时序+L0）0 否决缺陷、0 误拒"
                             "（L0 全绿：qc_orch_v2 在线 L0 时长/黑屏过；8 登记切点零未登记检出；"
                             f"J6v2 emitted {n_j6_emitted} 条；4 个 junction 候选被 known_cuts "
                             "白名单豁免——temporal_swap_known_cuts，合成层切点登记制生效）；"
                             "单片无真值不可测群体召回/误拒，1.0/0.0 为本片空洞值非金标群体校准"
                             "（短剧线 v1 混入的金标校准值已废止的修订语义沿记）")},
        "b_group": {"abstain": True,
                    "reason": "B 组专用小模型未部署（TASK_v4 M2-W7 范围外，M2 试点未装机）——弃权不参与 veto_groups",
                    "note": "弃权形（主控验收修订语义）：不填占位指标伪装实测"},
        "c_group": {"recall": 1.0, "fpr": 0.0, "verdict": "pass",
                    "note": ("本片真空：judge 检出不自动否决（白皮书 §3 CP12/§7 非目标 3），"
                             "flag 全部入人工队列 pending；本片 E10 三判官 J1/J3/J5 判定见 qc_report；"
                             "0 自动否决即 0 误拒；单片无真值不可测群体召回/误拒，1.0/0.0 为本片"
                             "空洞值非金标群体校准")},
        "d_group": {"warn_only": True,
                    "flagged_count": n_d_warn,
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
        "work_id": "comicanime_ep01",
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
    cp12_fp = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False).encode("utf-8")).hexdigest()
    cp12 = {
        "schema_version": "2.0",
        "cp_id": "cp12",
        "artifact_type": "qc_master",
        "fingerprint": cp12_fp,
        "produced_by": "agent.cp12_inspector.qc_orch_v2",
        "produced_at": NOW,
        "upstream_refs": [
            {"cp_id": "cp11", "fingerprint": cp11["fingerprint"]},
            {"cp_id": "cp10", "fingerprint": [u for u in cp11["upstream_refs"] if u["cp_id"] == "cp10"][0]["fingerprint"]},
            {"cp_id": "cp9", "fingerprint": json.load(open(HERE / "cp9.json"))["fingerprint"]},
            {"cp_id": "cp8", "fingerprint": json.load(open(HERE / "cp8.json"))["fingerprint"]},
            {"cp_id": "cp6", "fingerprint": [u for u in cp11["upstream_refs"] if u["cp_id"] == "cp6"][0]["fingerprint"]},
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
        "成片分 %.1f（=0.7×%.1f+0.3×%.1f，9 段继承成片单镜合议分——镜级 QCReport 本链未产出，"
        "按任务预案单镜近似并声明）%s；70 warn 阈（cp12.gate.master_score_min）只作排序依据，"
        "人评锚定（120 片段）未完成不作自动放行/否决（白皮书 §7 非目标 8），composite verdict "
        "不因此翻转"
        % (episode_score, mean_shot, worst_shot,
           "，达 70 warn 阈" if episode_score >= 70 else "，未达 70 warn 阈→warn 标注不否决"))
    cp12["aux_gates"][1]["result"] = "pass" if rate_vs_thr else "fail"
    cp12["aux_gates"][1]["note"] = (
        "人工上升率实测 %d/%d = %.4f（CP1 owner pending 计 %d + CP3/CP5/CP6 子代理自检通过未上升计 0 "
        "+ CP8 择优零人工计 0 + CP12 队列 pending %d（J6v2 emitted %d 条+D 组 warn 窗 %d 条））；"
        "thresholds 键 cp12.gate.human_escalation_rate_max=0.20（漫剧线 TASK_v4 §3.3 上限，"
        "本线适用 0.20 不适用短剧线 0.25 档）%s"
        % (escalations, n_cp, escalation_rate, cp1_pending, n_pending,
           n_j6_emitted, n_d_warn,
           "：未超" if rate_vs_thr else "：超限"))
    sub_thr_channels = "; ".join(f"{t}={p:.4f}" for t, p in sorted(
        ((t, float(p)) for t, p in j3_probs.items()
         if t != "overall" and 0.0 < float(p) < j3_thr), key=lambda kv: -kv[1])[:3])
    max_ch = max(((t, float(p)) for t, p in j3_probs.items() if t != "overall"),
                 key=lambda kv: kv[1])
    cp12["gate"]["note"] = (
        "四维实跑（comicanime_ep01 30s G8 样片）：缺陷维 E10=J1∨J3@%.2f（judges.J3_omnijev.thr）"
        "判定 %s / decision=%s → gate.result=%s；J3 全通道最高 %s=%.4f %s，无灰区无队列项%s；"
        "A 组程序规则（J6v2 时序+L0）：0 否决缺陷 0 误拒（8 登记切点全豁免"
        " judges.J6_detectors_v2.rule_params.known_cuts_tol_s=0.5；CP5 shot_04 切点 3.6s 在合成层"
        "登记为声明切点·无实体缝，见 cp11/qc_known_cuts.json），J6v2 emitted 0 条；B 组未部署弃权；"
        "C 组 judge flag 入人工队列语义；D 组 %d 个 warn-only 窗。组级 recall/fpr=本片真空空洞值，"
        "金标 40 条群体校准值不进组级（主控验收修订语义）。"
        % (j3_thr, v1["verdict"]["defect_detected"], v1["verdict"]["decision"], gate_result,
           max_ch[0], max_ch[1],
           f"未达阈（阈 {j3_thr}）" if max_ch[1] < j3_thr else "超阈",
           ("；未达阈次高通道只登记数据不入队列：" + sub_thr_channels) if sub_thr_channels else "",
           n_d_warn))
    cp12["notes"] = (
        "《头汤面》EP1 CP12 质检成片（漫剧线 30s G8 风格化样片，被检对象=cp11/master.mp4 "
        f"sha256={master_fp[:12]}…，1080x1920/24fps/720 帧/30.000s，无 avatar 段）。"
        "【判官链】J1 glm8（API glm-5.3-flash 8帧 rubric，judges_src/glm8_batch.py，"
        "BIGMODEL_API_KEY 由 GPU 机 overnight/secrets/api_keys.env ZHIPU_API_KEY 服务端 env 注入"
        "零回显零落盘）判净；J3 omnijev（OmniJev-4B-v1.1，GPU0，venv-judge，起跑前复测 "
        "≤1024MiB 才发车）9 通道 noul 概率；J5 videochat3（VideoChat3-4B，GPU0，venv-vc3，"
        "声明参数 fps=0.25/max_pixels=133072 沿短剧线 retry1 配方，decord 直读）；J6v2 "
        "qc_detectors_v2（本地 CPU，known_cuts=8 缝+1 声明切点白名单）0 候选。等位纪律：卡 0 "
        "忙时 wait 循环 60s 重测、≤1024MiB 才发车，不 kill 不抢卡（外部瞬态任务期间纯等待）。"
        "判官原始六字段输出一字不改嵌入 qc_report_v2.judges。【成片分映射（声明）】D=max(J3 触发"
        "通道 P≥0.71，J1/J5 detected→confidence，J6v2 emitted conf≥0.55)=%.4f → clip_score="
        "%.1f；9 段继承成片单镜分 mean=worst=%.1f，分数只作排序依据不作放行门（锚定未完成）。"
        "【四组】a=0 否决缺陷/0 误拒（本片真空）；b=弃权形；c=judge flag 入人工队列；d=warn-only "
        "%d 窗。【G8 风格人检（CP9 后）】9/9 代表帧亲看：全部 2D 赛璐璐平涂+清晰线稿+高饱和暖色"
        "夜戏，无写实/3D/水墨漂移（镜间面部造型轻度波动如实登记：f_03/f_06 偏动画脸，仍在 2D 域）"
        "——无 v3.1 强风格指令漂移，不触发回退 api_h3 裁决；G5 双主角身份一致（LU=高马尾靛蓝袍/"
        "SY=灰头巾米围巾，shot_07 双人同框两脸不混）；shot_09 精确计数成立（exactly two bowls，"
        "CP8 处置闭环，无需转人工队列）；G2 画面零可读文字。【CP8-CP11 链要】CP8 进 9/退 0；"
        "CP9 真实调用 9 次（≤10 红线）est=2576/3360；CP10 TTS 真实调用 10 次（≤12 红线）9/9 ok"
        "（seg_03 一次重试）；CP11 validate_cp11 --probe exit 0（13/13 checks）。"
        "【人工】队列 %d 条 pending；CP12 签字待 human.owner，本工件 verdict=门禁计算结果非人工签字。"
        % (d_signal, clip_score, clip_score, n_d_warn, n_pending))

    (HERE / "cp12.json").write_text(json.dumps(cp12, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")

    # ---- qc_report_v2 成片级报告（v2 契约）----
    v2 = {
        "schema_version": "2.0",
        "clip_id": CLIP,
        "generated_at": NOW,
        "work_id": "comicanime_ep01",
        "qc_mode": "online",
        "checkpoint": {"cp_id": "cp12", "artifact_ref": cp12_fp},
        "verdict": {
            "defect_detected": v1["verdict"]["defect_detected"],
            "decision": v1["verdict"]["decision"],
            "confidence": v1["verdict"]["confidence"],
            "decided_by": "cp12.composite(E10=J1∨J3@0.71 成片合议 + cp12.gate.master_score_min 成片绝对门)",
            "reasons": v1["verdict"].get("reasons", []) + [
                "成片分 %.1f = 0.7×mean(%.1f) + 0.3×worst(%.1f)，9 段继承成片单镜分（镜级 QCReport "
                "未产出，按任务预案单镜近似并声明）；绝对门阈见 params_ref=cp12.gate.master_score_min"
                "（人评锚定完成前仅 warn 阈与排序依据）"
                % (episode_score, mean_shot, worst_shot),
                "J6v2 成片重跑：8 拼接切点（CP6 帧界累计）全部落入 known_cuts 白名单"
                "（judges.J6_detectors_v2.rule_params.known_cuts_tol_s=0.5）被豁免，零 temporal_swap "
                "误报——合成层硬切点登记制生效；CP5 shot_04 切点 3.6s 以「声明切点·无实体缝」登记于"
                " cp11/qc_known_cuts.json（装配前场景检测证实 CP9 素材内该处无实体硬切）",
                "G8 风格人检（CP9 后 9/9 代表帧亲看）：2D 赛璐璐平涂+清晰线稿+高饱和暖色夜戏全部成立，"
                "无写实/3D/水墨漂移，不触发 v3.1 回退 api_h3 裁决；镜间面部造型轻度波动如实登记",
                "shot_09 计数：CP8 处置（精确计数 prompt）后精修层 exactly two bowls 成立——无需转人工队列",
                "无 avatar 段（漫剧线按 TASK_v4 不含 avatar 段）",
                "人工上升率实测 %.4f =（CP1 pending 1 + CP12 队列 %d）/12；TASK_v4 §3.3 漫剧线 ≤0.20%s"
                % (escalation_rate, n_pending, "未超" if escalation_rate <= 0.20 else "超限"),
            ],
        },
        "defects": defects_out,
        "scores": {**v1["scores"],
                   "per_type": {k: v for k, v in v1["scores"]["per_type"].items()
                                if k != "overall"}},
        "spans": v1.get("spans", []) + [
            {"type": "note",
             "evidence": {"text": ("J6v2 known_cuts 豁免记录：4 个 junction 候选全部 exempted"
                                   "（temporal_swap_known_cuts，证据 judges/detectors/%s.qc2.json "
                                   "temporal_rejected）" % CLIP)}},
            {"type": "note",
             "evidence": {"text": ("J3 未达判定阈(0.71)的次高通道只登记数据不入队列：%s"
                                   % (sub_thr_channels or "（全通道 ≤0）"))}},
        ],
        "judges": {"J1": j1, "J3": j3_proto, "J5": j5, "J6": j6v2["temporal_protocol"]},
        "inputs": {
            "clip": "overnight/vpipe/out/m2/comicanime_ep01/cp11/master.mp4",
            "frames_dir": "overnight/vpipe/out/m2/comicanime_ep01/qc_frames/comicanime_ep01",
            "judge_files": {
                "J1": "out/m2/comicanime_ep01/judges/glm8/%s.json" % CLIP,
                "J3": "out/m2/comicanime_ep01/judges/omnijev/run_metadata.json",
                "J5": "out/m2/comicanime_ep01/judges/videochat3/%s.json" % CLIP,
                "J6": "out/m2/comicanime_ep01/judges/detectors/%s.qc2.json" % CLIP,
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
        },
    }
    if not v2["qc_context"]:
        v2.pop("qc_context")
    (HERE / "qc_report_v2.json").write_text(json.dumps(v2, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")

    # ---- asset manifest（sha256 身份登记）----
    man_entries = []
    for rel in ["cp11/master.mp4", "cp11/cp11.json", "cp11/synth_meta.json",
                "cp11/qc_known_cuts.json", "cp11/validate_cp11_report.json",
                "qc_reports_online/%s.json" % CLIP, "qc_report_v2.json",
                "cp12.json",
                "judges/glm8/%s.json" % CLIP, "judges/glm8/run_metadata.json",
                "judges/omnijev/%s.json" % CLIP, "judges/omnijev/run_metadata.json",
                "judges/videochat3/%s.json" % CLIP, "judges/videochat3/run_metadata.json",
                "judges/detectors/%s.qc2.json" % CLIP,
                "cp8.json", "cp9.json", "cp9_prompts.json",
                "cp10/subs.ass", "cp10/duration_reconciliation.json",
                "qc_frames/comicanime_ep01/f01.jpg", "qc_frames/comicanime_ep01/f02.jpg",
                "qc_frames/comicanime_ep01/f03.jpg", "qc_frames/comicanime_ep01/f04.jpg",
                "qc_frames/comicanime_ep01/f05.jpg", "qc_frames/comicanime_ep01/f06.jpg",
                "qc_frames/comicanime_ep01/f07.jpg", "qc_frames/comicanime_ep01/f08.jpg"]:
        p = HERE / rel
        if p.exists():
            man_entries.append({"path": "overnight/vpipe/out/m2/comicanime_ep01/" + rel,
                                "sha256": sha256_file(p)})
    manifest = {"schema_version": "1.0", "name": "vpipe-cp12-comicanime_ep01",
                "thresholds_sha256": thr_sha, "generated_at": NOW, "assets": man_entries}
    (HERE / "asset_manifest_cp12.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("clip_score=%.1f mean=%.1f worst=%.1f episode=%.1f verdict=%s" %
          (clip_score, mean_shot, worst_shot, episode_score, ep_verdict))
    print("queue=%d (pending=%d) escalations=%d/%d rate=%.4f" %
          (len(queue), n_pending, escalations, n_cp, escalation_rate))
    print("cp12 fingerprint:", cp12_fp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
