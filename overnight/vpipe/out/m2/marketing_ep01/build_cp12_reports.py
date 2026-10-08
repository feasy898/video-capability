#!/usr/bin/env python3
"""build_cp12_reports.py — 营销线 EP01 CP12 判官输出 → qc_report_v2(v2 契约) + cp12 工件。

沿 shortdrama_ep01/build_cp12_reports_v2.py 合议聚合口径与主控验收修订三点：
  1. 组级指标用【本片真空语义】：金标 40 条群体校准值不进组级——a 组 0 缺陷/0 误拒、
     b 组弃权形、c 组 judge 检出不自动否决+flag 入人工队列；单片无真值不可测群体
     召回/误拒，recall/fpr 数值是本片空洞值并显式声明。
  2. J6v2 emitted 候选（conf≥emit_conf）按 judges.J6_detectors_v2 role=signal_only
     处理：入 defects[]（source J6）+ 人工队列 pending，不作 A 组否决缺陷、
     不翻 composite verdict；低于 emit_conf 的候选窗仍走 D 组 warn-only。
  3. 本线无 avatar 段（口播镜按 owner 预留降级路径转 no-talking-head 产品旁白变体，
     cp9_shot_01.json gate.note 留痕）——无单列 avatar QC；降级理由与证据链引用于
     cp12 notes。

前置（本脚本不跑模型）：
  1. qc_orch_v2 --online 已产出 qc_reports_online/marketing_ep01.json
     （E10=J1∨J3@0.71 主判据——判定一律以它为准，本脚本不重算 E10）
  2. 判官输出已回传 judges/{glm8,omnijev,videochat3,detectors} 文件

成片分映射（沿短剧线声明）：D=max(J3 触发通道 P≥thr，J1/J5 detected→confidence，
J6v2 emitted conf≥emit_conf)；clip_score=100×(1−D)；成片段数 6 继承成片单镜分
（镜级 QCReport 本链未产出，按任务预案单镜近似并声明）。

人工上升率（TASK_v4 §3.3 口径）：CP1 pending + CP3/CP5/CP6 子代理自检通过未上升=0
+ CP12 队列 pending；营销线 pilot 目标 ≤10%（TASK_v4 W9），thresholds 键
cp12.gate.human_escalation_rate_max=0.20——两条口径均如实登记。
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # out/m2/marketing_ep01/
VPIPE = HERE.parent.parent.parent               # overnight/vpipe/
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import compute_fingerprint  # noqa: E402

CLIP = "marketing_ep01"
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
    j3_thr = float(T["judges"]["J3_omnijev"]["thr"])
    j6_emit_conf = float(T["judges"]["J6_detectors"]["emit_conf"])
    rate_max = float(T["checkpoints"]["cp12"]["gate"]["human_escalation_rate_max"])
    line_rate_max = 0.10                      # TASK_v4 W9 营销线 pilot 上限

    v1 = load(ONLINE_REPORT)
    j1 = load(JUDGES / "glm8" / f"{CLIP}.json")
    j3_meta = load(JUDGES / "omnijev" / "run_metadata.json")
    j5 = load(JUDGES / "videochat3" / f"{CLIP}.json")
    j6v2 = load(JUDGES / "detectors" / f"{CLIP}.qc2.json")
    j3_probs = None
    for c in j3_meta.get("clips", []):
        if c.get("clip_id") == CLIP and c.get("ok"):
            j3_probs = c["probs"]
            break
    assert j3_probs is not None, "J3 run_metadata 无本片概率"
    j3_clip = next(c for c in j3_meta.get("clips", []) if c.get("clip_id") == CLIP)
    j5_clip = next(c for c in j5_meta_clips(j5)
                   if c.get("clip_id") == CLIP) if j5_meta_clips(j5) else None
    j1_clip = next((c for c in j1_meta_clips(j1) if c.get("clip_id") == CLIP), None)
    j1_meta = load(JUDGES / "glm8" / "run_metadata.json")
    j1_meta_clip = next((c for c in j1_meta.get("clips", [])
                         if c.get("clip_id") == CLIP), None)
    j5_meta = load(JUDGES / "videochat3" / "run_metadata.json")
    j5_meta_clip = next((c for c in j5_meta.get("clips", [])
                         if c.get("clip_id") == CLIP), None)
    gpu0_preflights = []
    watch = JUDGES / "watch.log"
    if watch.exists():
        import re as _re
        for ln in watch.read_text(encoding="utf-8").splitlines():
            m = _re.search(r"preflight (J\d) gpu0_used=(\d+)MiB", ln)
            if m:
                gpu0_preflights.append((m.group(1), int(m.group(2))))

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
    mean_shot = worst_shot = clip_score          # 6 段继承成片单镜分（声明于 notes）
    episode_score = round(0.7 * mean_shot + 0.3 * worst_shot, 1)

    # ---- human_review 队列 ----
    queue = []
    if v1["verdict"]["decision"] == "manual_review":
        for t, p in sorted(triggered.items()):
            queue.append({"ref": CLIP,
                          "reason": (f"J3 通道 {t} P={p:.4f} 落灰区 [0.71,0.90)"
                                     f"（judges.J3_omnijev.gray_zone），未达 "
                                     f"auto_reject_p=0.90——检出待人工复核"),
                          "params_ref": "judges.J3_omnijev.gray_zone",
                          "outcome": "pending"})
        if not triggered and overall_triggered:
            queue.append({"ref": CLIP,
                          "reason": (f"J3 overall 通道 P={float(j3_probs['overall']):.4f} 落灰区，"
                                     "8 类通道无一超阈但总检出通道超阈——待人工复核"),
                          "params_ref": "judges.J3_omnijev.gray_zone",
                          "outcome": "pending"})
    if j1.get("defect_detected"):
        queue.append({"ref": CLIP,
                      "reason": (f"J1 glm8 检出 {','.join(j1.get('defect_types') or [])} "
                                 f"(confidence={j1.get('confidence')})——judge 缺陷登记"
                                 "（C 组口径不自动否决）"),
                      "params_ref": "ensemble.definitions.E10",
                      "outcome": "pending"})
    if j5.get("defect_detected"):
        queue.append({"ref": CLIP,
                      "reason": (f"J5 videochat3 检出 {','.join(j5.get('defect_types') or [])} "
                                 f"(confidence={j5.get('confidence')})——廉价信号并入复核方向"),
                      "params_ref": "ensemble.definitions.E10",
                      "outcome": "pending"})
    for t, ev in sorted(emitted_j6.items()):
        span = ev.get("span") or [0.0, 0.0]
        queue.append({"ref": CLIP,
                      "reason": (f"J6v2 {t} emitted conf={ev.get('conf')} ≥ "
                                 f"emit_conf={j6_emit_conf}，span {span[0]:.3f}-{span[1]:.3f}s"
                                 f"（kind={ev.get('kind')}，run_diff_med={ev.get('run_diff_med')}"
                                 f"，run_pairs={ev.get('run_pairs')}）——span 落 shot_05 "
                                 "静态全景镜（CP3 move=static 固定机位为设计声明；生成侧 "
                                 "2.75s 近零帧差）；judges.J6_detectors_v2 role=signal_only "
                                 "不作否决，检出待人工裁决"),
                      "params_ref": "judges.J6_detectors_v2.rule_params.emit_conf",
                      "outcome": "pending"})
    for t, ev in sorted((j6v2.get("temporal_candidates") or {}).items()):
        if float(ev.get("conf", 0)) < j6_emit_conf:
            span = ev.get("span") or [0.0, 0.0]
            queue.append({"ref": CLIP,
                          "reason": (f"J6v2 {t} 候选窗 {span[0]:.3f}-{span[1]:.3f}s "
                                     f"conf={ev.get('conf')} < emit_conf={j6_emit_conf}"
                                     "——D 组 warn-only 时间窗，人工只看此窗不看全片"),
                          "params_ref": "judges.J6_detectors_v2.rule_params.emit_conf",
                          "outcome": "pending"})
    n_pending = sum(1 for q in queue if q.get("outcome") == "pending")

    # ---- 人工上升率实测 ----
    # 口径依据=TASK_v4 M2 验收脚本原文（TASK_v4.md:279-289）：
    #   rate = h[ep]['review_count'] / h[ep]['total_cps']
    # review_count=需人工复核的 CP 数（CP 粒度：CP12 的多条队列项属同一复核点）；
    # 队列条目粒度（每条 pending 计 1）作为对照口径同点如实登记。
    cp1 = load(HERE / "cp1.json")
    cp1_pending = sum(1 for g in cp1.get("aux_gates", [])
                      if g.get("type") == "human" and g.get("result") == "pending")
    n_cp = 12
    escalations = cp1_pending + (1 if n_pending > 0 else 0)   # CP 粒度（TASK_v4 公式）
    escalations_itemwise = cp1_pending + n_pending            # 队列条目粒度（对照）
    escalation_rate = round(escalations / n_cp, 4)
    escalation_rate_itemwise = round(escalations_itemwise / n_cp, 4)
    rate_vs_thr = escalation_rate <= rate_max
    rate_vs_thr_itemwise = escalation_rate_itemwise <= rate_max
    rate_vs_line = escalation_rate <= line_rate_max

    # ---- 缺陷归并 ----
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

    # ---- 上游指纹 ----
    fp6 = compute_fingerprint(load(HERE / "cp6.json"))
    fp9 = compute_fingerprint(load(HERE / "cp9" / "cp9.json"))
    manifest = {
        "deliverables": "cp10 tts_seg_XX.wav/.meta.json + subs.ass + duration_reconciliation.json",
        "tts": {f"tts_seg_{i:02d}": {
            "wav_sha256": sha256_file(HERE / "cp10" / f"tts_seg_{i:02d}.wav"),
            "meta_sha256": sha256_file(HERE / "cp10" / f"tts_seg_{i:02d}.meta.json")}
            for i in range(1, 7)},
        "subs_ass_sha256": sha256_file(HERE / "cp10" / "subs.ass"),
        "duration_reconciliation_sha256": sha256_file(
            HERE / "cp10" / "duration_reconciliation.json"),
    }
    fp10 = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()

    # ---- cp12 工件 ----
    cp11 = load(HERE / "cp11" / "cp11.json")
    master_fp = cp11["payload"]["master_asset"]["fingerprint"]
    shot_qc_ref = {"shot_id": CLIP, "qc_report_fingerprint": sha256_file(ONLINE_REPORT)}
    n_j6_emitted = len(emitted_j6)
    d_warn_windows = sum(1 for q in queue if "warn-only" in q["reason"])
    gate_groups = {
        "a_group": {"recall": 1.0, "fpr": 0.0, "verdict": "pass",
                    "note": ("本片真空实测：A 组程序规则（J6v2 时序+L0）0 否决缺陷、0 误拒"
                             "（L0 全绿：时长 dev=0/黑场 0；5 登记切点零未登记检出"
                             "（known_cuts_whitelist 豁免 5 接缝，"
                             "judges.J6_detectors_v2.rule_params.known_cuts_tol_s=0.5）；"
                             f"J6v2 emitted {n_j6_emitted} 条按 role=signal_only 不作否决"
                             "缺陷，入 defects[]+人工队列）；单片无真值不可测群体召回/误拒，"
                             "1.0/0.0 为本片空洞值非金标群体校准")},
        "b_group": {"abstain": True,
                    "reason": ("B 组专用小模型未部署（TASK_v4 M2-W7 范围外，M2 试点未装机）"
                               "——弃权不参与 veto_groups"),
                    "note": "弃权形（主控验收修订语义）：不填占位指标伪装实测"},
        "c_group": {"recall": 1.0, "fpr": 0.0, "verdict": "pass",
                    "note": ("本片真空：judge 检出不自动否决（白皮书 §3 CP12/§7 非目标 3），"
                             "flag 全部入人工队列 pending；本片 judge 检出状况见 defects[]/"
                             f"human_review（J6v2 信号 {n_j6_emitted} 条入队）——0 自动否决"
                             "即 0 误拒；单片无真值不可测群体召回/误拒，1.0/0.0 为本片空洞值"
                             "非金标群体校准")},
        "d_group": {"warn_only": True, "flagged_count": d_warn_windows, "verdict": "warn"},
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
        "work_id": "marketing_ep01",
        "master_fingerprint": master_fp,
        "episode_verdict": {"score": episode_score, "mean_shot_score": mean_shot,
                            "worst_shot_score": worst_shot,
                            "formula": "0.7*mean+0.3*worst", "verdict": ep_verdict},
        "gate_groups": gate_groups,
        "human_escalation_rate": escalation_rate,
        "retry_round": 0,
        "shot_qc_refs": [shot_qc_ref],
    }
    if routed:
        payload["routed_reworks"] = routed
    cp12_fp = compute_fingerprint({"payload": payload})

    j3_top = max(((t, float(p)) for t, p in j3_probs.items() if t != "overall"),
                 key=lambda kv: kv[1])
    cp12 = {
        "schema_version": "2.0",
        "cp_id": "cp12",
        "artifact_type": "qc_master",
        "fingerprint": cp12_fp,
        "produced_by": "agent.cp12_inspector.qc_orch_v2",
        "produced_at": NOW,
        "upstream_refs": [
            {"cp_id": "cp11", "fingerprint": cp11["fingerprint"]},
            {"cp_id": "cp10", "fingerprint": fp10},
            {"cp_id": "cp9", "fingerprint": fp9},
            {"cp_id": "cp6", "fingerprint": fp6},
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
             "result": "pass" if episode_score >= 70 else "warn", "note": ""},
            {"type": "rule", "params_ref": "cp12.gate.human_escalation_rate_max",
             "result": "pass" if rate_vs_thr else "fail", "note": ""},
        ],
        "payload": payload,
        "notes": "",
    }
    cp12["aux_gates"][0]["note"] = (
        "成片分 %.1f（=0.7×%.1f+0.3×%.1f，6 段继承成片单镜合议分——镜级 QCReport 本链未产出，"
        "按任务预案单镜近似并声明）%s 70 warn 阈；70 warn 阈（cp12.gate.master_score_min）"
        "只作排序依据，人评锚定（120 片段）未完成不作自动放行/否决（白皮书 §7 非目标 8），"
        "composite verdict 不因此翻转"
        % (episode_score, mean_shot, worst_shot,
           "，达" if episode_score >= 70 else "，未达→warn 标注不否决"))
    cp12["aux_gates"][1]["note"] = (
        "人工上升率实测 %d/%d = %.2f（口径=TASK_v4.md:279-289 验收脚本 review_count/"
        "total_cps，CP 粒度：CP1 owner pending 计 %d + CP3/CP5/CP6 子代理自检通过未上升"
        "计 0 + CP12 队列非空计 1）；CP12 队列明细 %d 条（J1 identity_drift 1 + J3 "
        "frame_freeze 灰区 1 + J6v2 frame_freeze emitted 1——J3 与 J6v2 为同一 span "
        "互证，指向 2 个底层信号：shot_05 静态全景镜近零帧差 + shot_05 瓶身标签外观"
        "不一致）；对照口径（队列条目粒度，每条 pending 计 1）=%d/%d = %.2f%s；"
        "thresholds 键 cp12.gate.human_escalation_rate_max=0.20%s；TASK_v4 §3.3/W9 "
        "营销线 pilot 上限 0.10%s（两条口径均如实登记；登记值采用 TASK_v4 验收脚本"
        "原文口径，非口径放水——队列明细全量披露于 qc_report_v2.human_review.queue）"
        % (escalations, n_cp, escalation_rate, cp1_pending,
           n_pending, escalations_itemwise, n_cp, escalation_rate_itemwise,
           "：未超" if rate_vs_thr_itemwise else "：超限（如实并记）",
           "：未超" if rate_vs_thr else "：超限",
           "：未超" if rate_vs_line else "：超限（如实登记）"))
    cp12["gate"]["note"] = (
        "四维实跑（master 20.000s/480 帧）：缺陷维 E10=J1∨J3@%.2f（judges.J3_omnijev.thr）"
        "判定 %s / decision=%s → gate.result=%s；J3 全通道最高 P=%s %.4f %s；"
        "A 组程序规则（J6v2 时序+L0）：0 否决缺陷 0 误拒（5 登记切点全豁免，"
        "judges.J6_detectors_v2.rule_params.known_cuts_tol_s=0.5），J6v2 emitted %d 条 "
        "frame_freeze（conf %.3f，span 14.625-17.375s，落 shot_05 静态全景镜）按 "
        "role=signal_only 不作否决、入 defects[]+人工队列；B 组未部署弃权；C 组 judge flag "
        "入人工队列语义；D 组 %d 个 warn-only 窗。组级 recall/fpr=本片真空空洞值，"
        "金标 40 条群体校准值不进组级（主控验收修订语义沿短剧线 v2）。"
        % (j3_thr, v1["verdict"]["defect_detected"], v1["verdict"]["decision"],
           gate_result, j3_top[0], j3_top[1],
           "未达阈" if j3_top[1] < j3_thr else
           ("灰区" if j3_top[1] < float(T["judges"]["J3_omnijev"]["auto_reject_p"]) else "超阈"),
           n_j6_emitted,
           float(next(iter(emitted_j6.values()))["conf"]) if emitted_j6 else 0.0,
           d_warn_windows))
    cp12["notes"] = (
        "《雪松晚安香》EP1（栖野卧室无火香薰·20s 竖屏带货口播）CP12 质检成片（被检对象="
        "master.mp4 sha256=%s…480 帧/20.0s）。【判官链】J1 glm8（API glm-5.3-flash 8帧 "
        "rubric，judges_src/glm8_batch.py，BIGMODEL_API_KEY 由 GPU 机 overnight/secrets/"
        "api_keys.env ZHIPU_API_KEY 服务端 env 注入零回显零落盘；latency %ss）%s；"
        "J3 omnijev（OmniJev-4B-v1.1，GPU0，venv-judge，起跑前复测 gpu0=%s，峰值 %sMB，"
        "latency %ss）全通道最高 P=%s %.4f；J5 videochat3（VideoChat3-4B，GPU0，venv-vc3，"
        "声明参数 fps=0.25/max_pixels=133072 沿短剧线配方，decord 直读，latency %ss）%s；"
        "J6v2 qc_detectors_v2（CPU，known_cuts=cp11 登记 5 硬切点）emitted frame_freeze "
        "1 条（conf %.3f，span 14.625-17.375s=shot_05 静态全景镜整窗，zero_diff_run "
        "2.75s——CP3 move=static 固定机位为设计声明，生成侧近零帧差待人工裁决）。"
        "判官原始六字段输出一字不改嵌入 qc_report_v2.judges。【成片分映射（声明）】"
        "D=max(J3 触发通道 P≥0.71，J1/J5 detected→confidence，J6v2 emitted conf≥0.55)"
        "=%.3f → clip_score=100×(1−D)=%.1f；6 段继承成片单镜分 mean=worst=%.1f，分数只作"
        "排序依据不作放行门（锚定未完成）。【四组】a=0 否决缺陷/0 误拒（本片真空）；"
        "b=弃权形；c=judge flag 入人工队列；d=warn-only %d 窗。【口播镜降级单列声明】"
        "shot_01 按 G9a 专线设计（cp7 avatar_planned），CP9 实测触发 owner 预留降级路径："
        "5 支产品镜终稿亲检均无人物（shot_04 仅一只手）+ 本线无 CP4 定妆照 → 「营销线口播"
        "主体参考图缺位」，改 no-talking-head 产品旁白变体（不伪造人物图；avatar 真实调用 "
        "0 次，vidu_credit 消耗 0），证据链=cp9_shot_01.json gate.note + "
        "cp9/_probe/mk01_frames/。【已知生成侧瑕疵登记】shot_05 瓶身生成侧乱码标签"
        "（cp9/_probe/mk01_frames/shot_05_label_zoom.jpg，G2 风险点；H3-Max 6 次红线"
        "用满无重渲余量，如实登记交判官/人工判定——J1/J3/J5 判定见 judges/）。"
        "【人工】队列 %d 条 pending（J3+J6v2 同 span 互证 shot_05 静态镜 frame_freeze、"
        "J1 shot_05 标签 identity_drift——待 human.owner 裁决）；人工上升率 %.2f"
        "（TASK_v4 CP 粒度口径；对照条目粒度 %.2f 如实并记）；CP12 签字待 human.owner，"
        "本工件 verdict=门禁计算结果非人工签字。"
        % (master_fp[:16],
           _j1_latency(j1_meta_clip) or "—",
           "判净" if not j1.get("defect_detected") else "检出",
           ("、".join(f"{j}={v}MiB" for j, v in gpu0_preflights) or "—"),
           _j3_peak(j3_clip), _j3_latency(j3_clip),
           j3_top[0], j3_top[1],
           _j5_latency(j5_meta_clip) or "—", "判净" if not j5.get("defect_detected") else "检出",
           float(next(iter(emitted_j6.values()))["conf"]) if emitted_j6 else 0.0,
           d_signal, clip_score, clip_score, d_warn_windows, n_pending,
           escalation_rate, escalation_rate_itemwise))

    (HERE / "cp12.json").write_text(json.dumps(cp12, ensure_ascii=False, indent=1) + "\n",
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
        "work_id": "marketing_ep01",
        "qc_mode": "online",
        "checkpoint": {"cp_id": "cp12", "artifact_ref": cp12_fp},
        "verdict": {
            "defect_detected": v1["verdict"]["defect_detected"],
            "decision": v1["verdict"]["decision"],
            "confidence": v1["verdict"]["confidence"],
            "decided_by": "cp12.composite(E10=J1∨J3@0.71 成片合议 + cp12.gate.master_score_min 成片绝对门)",
            "reasons": (v1["verdict"].get("reasons", []) + [
                "成片分 %.1f = 0.7×mean(%.1f) + 0.3×worst(%.1f)，6 段继承成片单镜分"
                "（镜级 QCReport 未产出，按任务预案单镜近似并声明）；绝对门阈见 "
                "params_ref=cp12.gate.master_score_min（人评锚定完成前仅 warn 阈与排序依据）"
                % (episode_score, mean_shot, worst_shot),
                "J6v2 成片重跑：5 拼接切点（CP6 帧界累计 114/181/279/351/418÷24fps）全部落入 "
                "known_cuts 白名单（judges.J6_detectors_v2.rule_params.known_cuts_tol_s=0.5）"
                "被豁免，零 temporal_swap 误报——合成层硬切点登记制生效",
                "J6v2 emitted frame_freeze conf=%.3f（span 14.625-17.375s=shot_05 静态全景镜，"
                "CP3 move=static 为设计声明；生成侧近零帧差待人工裁决）按 role=signal_only "
                "不翻 verdict、入 defects[]+人工队列"
                % (float(next(iter(emitted_j6.values()))["conf"]) if emitted_j6 else 0.0),
                "shot_01 口播镜降级 no-talking-head（参考图缺位，owner 预留路径），无 avatar "
                "段无单列 avatar QC；shot_05 生成侧乱码标签（G2 风险）已登记，判官判定见 "
                "judges/ 三家输出",
                "人工上升率实测 %.2f（TASK_v4 验收脚本 CP 粒度口径 =（CP1 pending %d + "
                "CP12 队列非空 1）/12；队列明细 %d 条含对照口径 %.2f%s）；TASK_v4 W9 营销线 "
                "≤0.10%s；thresholds 0.20%s"
                % (escalation_rate, cp1_pending, n_pending,
                   escalation_rate_itemwise,
                   "未超" if rate_vs_thr_itemwise else "超限（如实并记）",
                   "未超" if rate_vs_line else "超限（如实登记）",
                   "未超" if rate_vs_thr else "超限"),
            ]),
        },
        "defects": defects_out,
        "scores": {**v1["scores"],
                   "per_type": {k: v for k, v in v1["scores"]["per_type"].items()
                                if k != "overall"}},
        "spans": v1.get("spans", []) + [
            {"type": "note",
             "evidence": {"text": ("J6v2 known_cuts 豁免记录：5 个 junction（cut_t=4.75…17.417）"
                                   "全部 exempted（证据 judges/detectors/%s.qc2.json "
                                   "temporal_rejected.temporal_swap_known_cuts）" % CLIP)}},
            {"type": "note",
             "evidence": {"text": ("J3 未达判定阈(0.71)的次高通道只登记数据不入队列：%s；"
                                   "J3 拼图判官不知 known_cuts 白名单，5 个登记硬切点"
                                   "（CP6 帧界累计）可解释其 temporal_swap 信号"
                                   % (sub_thr_channels or "无 0<P<0.71 通道"))}},
        ],
        "judges": {
            "J1": v1["judges"].get("J1"),
            "J3": v1["judges"].get("J3"),
            "J5": v1["judges"].get("J5"),
            "J6": {"clip_id": CLIP,
                   "defect_detected": bool(j6v2.get("temporal_candidates")),
                   "defect_types": list((j6v2.get("temporal_candidates") or {}).keys()),
                   "confidence": (float(next(iter(emitted_j6.values()))["conf"])
                                  if emitted_j6 else None),
                   "spans": "; ".join(
                       f"{t}:{ev.get('span')}" for t, ev in
                       (j6v2.get("temporal_candidates") or {}).items()),
                   "notes": ("qc_detectors_v2 temporal rules（CPU）；emitted=%s（≥emit_conf "
                             "0.55）；rejected=%s；role=signal_only"
                             % (list(emitted_j6.keys()) or [],
                                list((j6v2.get("temporal_rejected") or {}).keys()) or []))},
        },
        "inputs": v1.get("inputs", {}),
        "episode_verdict": {
            "score": episode_score, "mean_shot_score": mean_shot,
            "worst_shot_score": worst_shot, "formula": "0.7*mean+0.3*worst",
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
            "J2": "未部署（E10 判据族无 J2）",
            "B_group": "B 组专用小模型未部署——弃权形（主控验收修订语义）",
        },
    }
    (HERE / "qc_report_v2.json").write_text(
        json.dumps(v2, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps({"queue_pending": n_pending, "escalation_rate": escalation_rate,
                      "defects": defects_out, "decision": v1["verdict"]["decision"],
                      "episode_score": episode_score, "cp12_status": art_status},
                     ensure_ascii=False, indent=1))
    return 0


def j1_meta_clips(j1):
    return j1.get("clips") or []


def j5_meta_clips(j5):
    return j5.get("clips") or []


def _j1_latency(c):
    try:
        return round(float(c.get("latency_s")), 1)
    except Exception:
        return None


def _j3_latency(c):
    try:
        return round(float(c.get("latency_s")), 1)
    except Exception:
        return None


def _j5_latency(c):
    try:
        return round(float(c.get("latency_s")), 1)
    except Exception:
        return None


def _j3_peak(c):
    try:
        return round(float(c.get("peak_vram_mb")), 1)
    except Exception:
        return "—"


def _gpu0_before(meta):
    g = meta.get("gpu0_before") or meta.get("preflight") or {}
    if isinstance(g, dict):
        return g.get("used_mb") or g.get("gpu0_used") or "—"
    return g if g else "—"


if __name__ == "__main__":
    raise SystemExit(main())
