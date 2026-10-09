#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 eval_results_exp59_j3v10_supplement.json（v10 轮 eval 留痕，G0-2 双处登记之一）。"""
import json
import datetime
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # vpipe/


def sha(p):
    return hashlib.sha256((HERE / p).read_bytes()).hexdigest()


rep55 = json.loads((HERE / 'out/qc_reports_exp59_j3v10/golden_055.json').read_text(encoding='utf-8'))
ev = json.loads((HERE / 'eval/eval_results_exp59_j3v10.json').read_text(encoding='utf-8'))
im = json.loads(Path('/tmp/in_med_59.json').read_text(encoding='utf-8'))

in_med_avatar = {c: im[c]['in_med'] for c in ('golden_053', 'golden_054', 'golden_055', 'golden_056', 'golden_057')}
in_med_key_ab = {c: {'ff_P': p, 'in_med': im[c]['in_med']} for c, p in (
    ('golden_008', 0.8977), ('golden_017', 0.7315), ('golden_028', 0.8665),
    ('golden_031', 0.7140), ('golden_020', 0.7472), ('golden_051', 0.8109))}

supp = {
 "generated_at": datetime.datetime.now().isoformat(timespec='seconds'),
 "purpose": "判官配方迭代 A 线（J3 分通道阈 + 低运动平台豁免，声明制）落地轮 supplement："
            "v10 走表定值 + 豁免弃权留证 + 59 条金标 eval 复跑（vs exp59 基线位级对比）。"
            "G0-2 双处登记：本 JSON + thresholds.yaml v10 注记。",
 "pair_file": "eval/eval_results_exp59_j3v10.json（= canonical eval_results.json，59 条 REJECT：仅 recall_min 未过）",
 "thresholds_note": "thresholds.yaml version 8→10（v9=并行路径 B 的 J1 rubric 升版，本轮 A 线占 v10）。",
 "thresholds_sha256": sha('eval/thresholds.yaml'),
 "g0_3_reconciliation": "eval/eval_results.json thresholds_sha256 与 sha256(thresholds.yaml) 一致（G0-3）",
 "judge_inputs_pin": {
   "fingerprint_sha256": "34402064c503707cf8a6be3edabb197fab8cd212a57e49454b93dd228ce152df",
   "scope": "数据/judges/{omnijev,glm8,videochat3,detectors} 全树，回放前后两次实算一致",
   "note": "J3/J1/J5/J6 判官输出零重跑零变动（改的是判定逻辑不是模型）；与并行路径 B 的 "
           "judges_v1_round3 归档无竞态（其新 J1 输出当时未落入 judges/glm8/，golden_045/046/052/013 逐条与归档字节一致实测）"},
 "per_channel_thr_final": {
   "frame_freeze": 0.71,
   "others": "缺键回落 thr=0.71（8 类+overall 全部 0.71，数值与 v9 一致）",
   "rationale_walk": [
     {"thr": 0.85, "verdict": "不可行", "casualties": "golden_017(A,ff=0.7315,无兜底)转FN；golden_020/031(B,0.7472/0.7140,无兜底)失检出→b_flag 6/14<0.50；041(0.8470)失ff命中但face_blur=0.7831兜底"},
     {"thr": 0.84, "verdict": "不可行", "casualties": "041 阈下自保（相对 0.85 唯一收益），017/020/031 恒久损失不变"},
     {"thr": 0.73, "verdict": "不可行", "casualties": "031(0.7140)仍被杀→b_flag 7/14=0.50 恰压线零余量；对 C 误报零新增收益（057 同被豁免覆盖）"},
     {"thr": 0.72, "verdict": "不可行", "casualties": "同 0.73"},
     {"thr": 0.71, "verdict": "终值", "casualties": "无（A/B 无兜底 ff 检出最低值 golden_031=0.7140 之下唯一无风险档）"}],
   "data_conclusion": "ff 概率轴上 C 误报与 A/B 真检出全域交错（010 0.7384 vs 017 0.7315 差 0.0069；"
                      "058 0.8685 vs 028 0.8665、059 0.8004 vs 017 0.7315 倒挂），单靠提阈在本金标上不可行；"
                      "J3 侧 FP 压降由豁免承担。『recall 不变 0.8929』在走表终值下成立。"},
 "ff_exempt_design": {
   "声明制三键": {"frame_freeze_plateau_exempt": True,
                  "frame_freeze_plateau_exempt_profiles": ["avatar_talk"],
                  "frame_freeze_plateau_in_med_lt_ref": "judges.J6_detectors_v2.rule_params.ghost_plateau_in_max (=2.0，引用不复写防第二套数值)"},
   "触发条件": "profile 已声明∈名单 且 qc_detectors_v2 同款帧差中位 in_med<2.0 且 frame_freeze 过有效阈",
   "作用域": "只弃权 frame_freeze 通道候选；其余 7 类与 overall 不受影响（ghosting/swap 等不碰）",
   "为什么必须声明制": "金标 008(A 真定格, ff=0.8977, in_med=0.313) 比全部 C 口播误报（in_med 0.41-0.96）更静止，"
                      "in_med 单变量不可分；无声明门时豁免必杀真检出（J6v2 034/028 交叠同源结论，v2 注记）",
   "回放声明源": "金标 manifest axis=AVATAR_EXPANSION（生成侧来源登记，Vidu S2 offline_avatar 口播）→ avatar_talk；仅 053-057 五条声明",
   "在线模式": "--profile 传入（与 J6v2 消费同一声明键）；未提供 --clip 时 in_med 不可算→豁免不触发并在 errors 留痕",
   "弃权留证样例 golden_055": {
     "verdict_reasons": rep55['verdict']['reasons'],
     "errors.J3_frame_freeze_exempt": rep55['errors']['J3_frame_freeze_exempt'],
     "qc_context": rep55.get('qc_context'),
     "scores.thresholds_applied.ff_exempt": rep55['scores']['thresholds_applied']['ff_exempt'],
     "raw_judge_untouched": "judges.J3 原始六字段一字未改（defect_detected 仍 true）——弃权发生在编排层，判官协议数据零污染"}},
 "in_med_evidence": {
   "avatar_declared_5": in_med_avatar,
   "key_AB_no_fallback": in_med_key_ab,
   "note": "in_med=原生帧率全序列相邻帧 MAD 全片中位（qc_detectors_v2 read_features 同式，"
           "qc_orch_v2.in_med_v2 就地重建，模块间不 import）；59 条全量离线复算，模块实现抽验一致（055=0.7049）"},
 "e10_exp59_metrics": {
   "recall": ev['main']['recall'], "fpr": ev['main']['fpr'], "f1": ev['main']['f1'],
   "b_flag": ev['B']['flag_rate'],
   "tp": ev['main']['tp'], "fn": ev['main']['fn'], "fp": ev['main']['fp'], "tn": ev['main']['tn'],
   "fp_clips": ev['fp_clips'], "fn_clips": ev['fn_clips']},
 "admission_checks": ev['checks'],
 "all_passed": ev['all_passed'],
 "verdict": "REJECT（仅 recall_min 0.8929<0.90 一条未过；fpr_max/f1_min/b_flag_min/schema 全过）",
 "exp59_vs_v10_bitlevel": {
   "exp59_register": "eval_results_exp59_supplement.json e10_exp59_metrics（R=0.8929/FPR=0.4706/F1=0.8197/B_flag=0.6429，tp25/fn3/fp8/tn9）",
   "delta": {
     "recall": "0.8929→0.8929（不变，与走表承诺一致；FN 仍 045/046/052，非阈可解，靠 v9 J1 rubric 线）",
     "fpr": "0.4706→0.2941（−3/17：FP 8→5，脱离 golden_055/056/057）",
     "f1": "0.8197→0.8621（+0.0424，过 f1_min=0.85 线）",
     "b_flag": "0.6429→0.5714（−1/14：golden_054 口播意图条 ff=0.8944 被豁免且 J1 未检出；仍≥0.50）"},
   "clip_level": {
     "verdict四元组逐条不变": 54,
     "flip_5": [
       {"clip": "golden_053", "class": "B", "change": "det True→True（J1 ghosting 兜底），defects 去 frame_freeze，conf 0.7292→0.65", "verdict_changed": False},
       {"clip": "golden_054", "class": "B", "change": "det True→False（豁免弃权，J1 未检出）", "verdict_changed": True},
       {"clip": "golden_055", "class": "C", "change": "det True→False（FP 脱离）", "verdict_changed": True},
       {"clip": "golden_056", "class": "C", "change": "det True→False（FP 脱离）", "verdict_changed": True},
       {"clip": "golden_057", "class": "C", "change": "det True→False（FP 脱离）", "verdict_changed": True}],
     "报告契约": "59/59 过 qc_report.schema.json（errors.J3_frame_freeze_exempt / qc_context.profile / thresholds_applied.ff_exempt 均为合法登记键）；判官六字段原始输出一字未改"},
   "remaining_fp_attribution": {
     "golden_010": "J3 frame_freeze=0.7384（非口播未声明，豁免不可及；提阈至 0.74 即杀 A 类 017，走表已排除）",
     "golden_013": "J1 布尔检出（与 J3 阈无关，exp59 已登记）",
     "golden_032": "J3 ghosting=0.930 + color_shift=0.7107（known_fp_mechanism：电影感调色；本轮射程外）",
     "golden_058": "J1 garble_text conf=0.97 主导（C 类真缺陷正例被机械记账为 FP，exp59 已登记；J3 ff=0.8685 仍 flag 但非 E10 决定侧）",
     "golden_059": "同 058（J1 conf=0.92；J3 ff=0.8004 仍 flag，非口播未声明）",
     "note": "ask 预期『059（0.800 那条）脱离』未实现——059 是 J1 检出的 E10 FP，J3 侧改动无论与否 E10 恒判检出；"
             "058/059 的 FP 记账归 owner 裁决的 C 类语义分裂（exp59 next_steps_owner 已登记）"},
   "预期对照": "ask 预期『FP 8→3 以内』未完全达成（实际 5，准入线内）：差异首因是 058/059 为 J1 检出 "
              "（E10 层不可由 J3 配方消除），次因是 010 在走表终值 0.71 下仍过阈且无声明不可豁免；"
              "FPR≤0.30 的硬目标（≤5 条）恰好达成，f1/b_flag 两线转过，recall 不变待路径 B"},
 "v1_compat_note": "qc_orch.py（契约 1.0）为冻结兼容路径，不实施 v10 配方，其登记基线停留在 exp59 状态（run_v3_checks E-v1 分支已注明分代差异，非未声明偏差）",
 "run_v3_checks_ref_update": "E-v2 分支登记基线切换至本 JSON（v8 先例：位级等于登记基线即通过）",
 "artifacts": {
   "reports": "out/qc_reports_exp59_j3v10/（59 份，契约校验 0 失败）",
   "manifest": "out/asset_manifest_exp59_j3v10.json",
   "eval_round": "eval/eval_results_exp59_j3v10.json（= canonical eval_results.json）"},
 "next_steps_owner": [
   "路径 B（v9 J1 rubric）重跑 59 条后须联合重扫：若新 J1 在 C 组新增检出（010/032/058/059 已在 FP 侧），FPR 将回升——联合轮须复跑本走表检查",
   "golden_054（B 口播意图）被豁免后 b_flag 余量仅 0.0714：J1 rubric 线若从意图维度接住 054 可回血（其 lip_* 严格词表为空集，走 lenient=other）",
   "剩余 5 FP 中 013/058/059 归 J1 侧、032 归 J3 ghosting/color_shift 通道、010 归 J3 ff 通道（无声明不可豁免）——全部在本轮配方射程外，维持上抛"]
}

out = HERE / 'eval/eval_results_exp59_j3v10_supplement.json'
out.write_text(json.dumps(supp, ensure_ascii=False, indent=1), encoding='utf-8')
print('supplement written:', out, out.stat().st_size, 'bytes')
