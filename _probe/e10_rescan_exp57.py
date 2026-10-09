#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""e10_rescan_exp57.py — E10 掉线后的工作点重扫（扩样 57 条）。
E10 定义（thresholds.yaml ensemble.definitions）：J1.detected OR J3@thr flag；
J3 flag = any(per_type[p] > thr for 8types) or overall > thr（qc_orch_v2 同口径）。
扫描 thr 0.40-0.95 步长 0.005，输出满足全部准入线的点 + 机制明细。
"""
import json
from pathlib import Path

REPO = Path('/home/pan-ding/workspace/视频能力')
JD = REPO / 'overnight/数据/judges'
gold = json.load(open(REPO / 'overnight/vpipe/eval/golden_manifest.json'))
gmap = {it['clip_id']: it for it in gold['items']}
A = sorted(i['clip_id'] for i in gold['items'] if i['class'] == 'A')
B = sorted(i['clip_id'] for i in gold['items'] if i['class'] == 'B')
C = sorted(i['clip_id'] for i in gold['items'] if i['class'] == 'C')
TYPES8 = ["frame_freeze", "flicker", "color_shift", "face_blur",
          "garble_text", "temporal_swap", "pixelate", "ghosting"]

j1, j3, j5 = {}, {}, {}
for cid in A + B + C:
    j1[cid] = json.load(open(JD / 'glm8' / f'{cid}.json'))
    j3[cid] = json.load(open(JD / 'omnijev' / f'{cid}.json'))
    j5[cid] = json.load(open(JD / 'videochat3' / f'{cid}.json'))

j3_meta = json.load(open(JD / 'omnijev' / 'run_metadata.json'))
probs = {c['clip_id']: c['probs'] for c in j3_meta['clips'] if c.get('ok') and c.get('probs')}


def j3_flag(cid, thr):
    p = probs[cid]
    return any(p.get(t, 0.0) > thr for t in TYPES8) or p.get('overall', 0.0) > thr


def metrics(thr):
    det = {c: bool(j1[c]['defect_detected']) or j3_flag(c, thr) for c in A + B + C}
    tp = sum(det[c] for c in A)
    fp = sum(det[c] for c in C)
    rec = tp / len(A)
    fpr = fp / len(C)
    prec = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    bflag = sum(det[c] for c in B) / len(B)
    return rec, fpr, f1, bflag, tp, fp, det


rows = []
thr = 0.40
while thr <= 0.951:
    rec, fpr, f1, bflag, tp, fp, det = metrics(thr)
    ok = rec >= 0.90 and fpr <= 0.30 and f1 >= 0.85 and bflag >= 0.50
    rows.append({'thr': round(thr, 3), 'recall': round(rec, 4), 'fpr': round(fpr, 4),
                 'f1': round(f1, 4), 'b_flag': round(bflag, 4), 'tp': tp, 'fp': fp,
                 'all_pass': ok,
                 'fp_clips': [c for c in C if det[c]],
                 'fn_clips': [c for c in A if not det[c]]})
    thr += 0.005

feas = [r for r in rows if r['all_pass']]
print('feasible points:', len(feas))
for r in feas[:12]:
    print(' ', r['thr'], 'R', r['recall'], 'FPR', r['fpr'], 'F1', r['f1'], 'B', r['b_flag'],
          'FP', r['fp_clips'], 'FN', r['fn_clips'])

# 机制明细：判官×新样本
print('\n=== 17 新样本判官明细 ===')
for cid in [f'golden_{i:03d}' for i in range(41, 58)]:
    it = gmap[cid]
    p = probs[cid]
    mx_t = max(TYPES8, key=lambda t: p.get(t, 0))
    print(f"{cid} [{it['class']}:{it.get('expected_defect')}] "
          f"J1={int(j1[cid]['defect_detected'])}{j1[cid]['defect_types']} "
          f"J3max={mx_t}:{max(p.get(t,0.0) for t in TYPES8):.3f} overall:{p.get('overall',0):.3f} "
          f"J5={int(j5[cid]['defect_detected'])}{j5[cid]['defect_types']}")

# 旧 3 条 FP 在新数据上的通道
print('\n=== 旧 FP 通道（010/013/032）===')
for cid in ['golden_010', 'golden_013', 'golden_032']:
    p = probs[cid]
    mx_t = max(TYPES8, key=lambda t: p.get(t, 0))
    print(f"{cid} [{gmap[cid]['class']}] J1={int(j1[cid]['defect_detected'])} "
          f"J3max={mx_t}:{max(p.get(t,0.0) for t in TYPES8):.3f} J5={int(j5[cid]['defect_detected'])}")

# 保存扫描表
out = {'scan': rows, 'feasible_n': len(feas),
       'admission': {'recall_min': 0.90, 'fpr_max': 0.30, 'f1_min': 0.85, 'b_flag_min': 0.50},
       'current_thr': 0.71}
json.dump(out, open('/tmp/e10_rescan_exp57.json', 'w'), ensure_ascii=False, indent=1)
print('\nsaved /tmp/e10_rescan_exp57.json')
