#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""j6v2_promote_retest.py — S5：J6v2 时序哨兵转正复测（扩样后金标 57 条）。

口径（对照 thresholds.yaml judges.J6_detectors_v2.measured_on_golden 的历史字段）：
  时序四类 = frame_freeze / temporal_swap / ghosting / flicker（TEMPORAL_TYPES）
  a_temporal_clip_recall = A 类时序片中 temporal_protocol.defect_detected=true 的比例（clip 级，类型不匹配也算检出）
  a_temporal_typematch_recall = A 类时序片中 期望类型 ∈ defect_types 的比例（类型匹配口径）
  a_temporal_type_macro_recall = 四类各自的类型匹配召回的宏平均
  c_fpr = C 类干净片中 defect_detected=true 的比例
参数：--params-yaml thresholds.yaml judges.J6_detectors_v2（与历史 R3b 同源）；无 --profile（不开豁免，
  与 2026-09-30 金标计分同纪律）。
"""
import json, sys, glob
from collections import defaultdict

ROOT = '/home/pan-ding/workspace/视频能力'
MAN = json.load(open(f'{ROOT}/overnight/数据/golden/manifest.json'))
TEMPORAL = {"frame_freeze", "temporal_swap", "ghosting", "flicker"}

rows = []
per_type = defaultdict(lambda: {"n": 0, "det": 0, "typematch": 0, "missed": [], "wrong_type": []})
c_total = c_fp = 0
c_fp_clips = []
b_total = b_det = 0
b_rows = []

for it in MAN['items']:
    cid = it['clip_id']
    r = json.load(open(f'{ROOT}/overnight/数据/j6_v2/results_exp57/{cid}.qc2.json'))
    proto = r['temporal_protocol']
    det = bool(proto['defect_detected'])
    types = set(proto['defect_types'])
    exp = it.get('expected_defect')
    cls = it['class']
    row = {'clip_id': cid, 'class': cls, 'expected': exp, 'detected': det,
           'types': sorted(types), 'conf': proto['confidence']}
    if cls == 'A' and exp in TEMPORAL:
        per_type[exp]['n'] += 1
        row['typematch'] = exp in types
        per_type[exp]['typematch'] += int(row['typematch'])
        if det:
            per_type[exp]['det'] += 1
        else:
            per_type[exp]['missed'].append(cid)
        if det and not row['typematch']:
            per_type[exp]['wrong_type'].append(f"{cid}:{','.join(sorted(types))}")
    elif cls == 'C':
        c_total += 1
        if det:
            c_fp += 1
            c_fp_clips.append({'clip_id': cid, 'types': sorted(types), 'conf': proto['confidence']})
    elif cls == 'B':
        b_total += 1
        b_det += int(det)
        if det:
            b_rows.append({'clip_id': cid, 'expected': exp, 'types': sorted(types)})
    row['tp_or_fp'] = ('A' if cls == 'A' else ('C' if cls == 'C' else 'B'))
    rows.append(row)

a_rows = [r for r in rows if r['tp_or_fp'] == 'A' and r['expected'] in TEMPORAL]
n_a = len(a_rows)
n_det = sum(r['detected'] for r in a_rows)
n_tm = sum(1 for r in a_rows if r.get('typematch'))
macro = sum((v['typematch'] / v['n']) if v['n'] else 0.0 for v in per_type.values()) / 4

res = {
  'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
  'purpose': 'J6v2 promote_criteria 复测（D-3 扩样后：时序四类 n=5/类）',
  'params_source': 'eval/thresholds.yaml judges.J6_detectors_v2（v7；--params-yaml 注入，无 --profile 无豁免）',
  'results_dir': 'overnight/数据/j6_v2/results_exp57（57 条 qc2.json）',
  'metric_definitions': {
    'a_temporal_clip_recall': 'A 类时序片 defect_detected=true 比例（clip 级）',
    'a_temporal_typematch_recall': '期望类型 ∈ defect_types 比例（类型匹配）',
    'a_temporal_type_macro_recall': '四类类型匹配召回宏平均',
    'c_fpr': 'C 类干净片 defect_detected=true 比例',
  },
  'promote_criteria': {'recall_min': 0.85, 'fpr_max': 0.15},
  'a_temporal': {'n': n_a, 'detected': n_det, 'clip_recall': round(n_det / n_a, 4),
                 'typematch': n_tm, 'typematch_recall': round(n_tm / n_a, 4)},
  'a_temporal_type_macro_recall': round(macro, 4),
  'per_type': {k: {'n': v['n'], 'detected': v['det'], 'typematch': v['typematch'],
                   'clip_recall': round(v['det'] / v['n'], 4),
                   'typematch_recall': round(v['typematch'] / v['n'], 4),
                   'missed': v['missed'], 'detected_wrong_type': v['wrong_type']}
               for k, v in sorted(per_type.items())},
  'c_clean': {'n': c_total, 'fp': c_fp, 'fpr': round(c_fp / c_total, 4), 'fp_clips': c_fp_clips},
  'b_avatar': {'n': b_total, 'detected': b_det, 'rows': b_rows},
  'per_clip': rows,
}
rec, fpr = res['a_temporal']['clip_recall'], res['c_clean']['fpr']
res['verdict'] = ('达标（recall %.4f >= 0.85 且 fpr %.4f <= 0.15 → 可出转正评估）' % (rec, fpr)
                  if (rec >= 0.85 and fpr <= 0.15) else
                  '未达线（recall %.4f vs >=0.85 / fpr %.4f vs <=0.15 → 仍 signal_only）' % (rec, fpr))

out = f'{ROOT}/overnight/数据/j6_v2/promote_retest_exp57.json'
json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
print(json.dumps({k: res[k] for k in ('a_temporal', 'a_temporal_type_macro_recall', 'per_type',
                                      'c_clean', 'b_avatar', 'verdict')},
                 ensure_ascii=False, indent=1))
print('saved ->', out)
