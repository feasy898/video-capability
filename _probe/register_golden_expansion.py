#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_golden_expansion.py — D-3 收尾 S2：17 条新样本登记入 golden manifest（同构追加）。"""
import json, hashlib, subprocess, glob, os
from collections import Counter
from datetime import datetime

ROOT = '/home/pan-ding/workspace/视频能力'
G = f'{ROOT}/overnight/数据/golden'
man = json.load(open(f'{G}/manifest.json'))
assert len(man['items']) == 40, f'expect 40 items, got {len(man["items"])}'


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def probe(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                        '-show_entries', 'stream=width,height,r_frame_rate',
                        '-show_entries', 'format=duration', '-of', 'json', p],
                       capture_output=True, text=True)
    j = json.loads(r.stdout)
    s = j['streams'][0]
    n, d = s['r_frame_rate'].split('/')
    cid = os.path.basename(p).replace('.mp4', '')
    njpg = len(glob.glob(f'{G}/frames/{cid}/f*.jpg'))
    return {'dur_s': round(float(j['format']['duration']), 3), 'wh': [s['width'], s['height']],
            'fps': round(float(n) / float(d), 3), 'n_frames': njpg}


def mtime(p):
    return datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%dT%H:%M:%S')


HOSTS = {
    'G6-28__wan.mp4': ('G6-28', 'G6', 'Wan2.1-T2V-1.3B'),
    'G4-19__ltx.mp4': ('G4-19', 'G4', 'LTX-Video-2B'),
    'G9-38__ltx.mp4': ('G9-38', 'G9', 'LTX-Video-2B'),
    'G2-07__ltx.mp4': ('G2-07', 'G2', 'LTX-Video-2B'),
    'G6-26__wan.mp4': ('G6-26', 'G6', 'Wan2.1-T2V-1.3B'),
    'G6-26__ltx.mp4': ('G6-26', 'G6', 'LTX-Video-2B'),
}
CHOSTS = {
    'golden_025': ('G2-08', 'G2', 'MiniMax-H3'),
    'golden_037': ('G6-25', 'G6', 'MiniMax-H3'),
    'golden_032': ('G6-26', 'G6', 'MiniMax-H3'),
    'golden_001': ('G7-30', 'G7', 'MiniMax-H3'),
    'golden_006': ('G7-33', 'G7', 'MiniMax-H3'),
    'golden_009': ('G7-31', 'G7', 'MiniMax-H3'),
}

new_items = []
sign_recheck = json.load(open('/tmp/sign_recheck.json'))

# ---- A 组 12 条（041-052）：以 _sign/*.sign.json 为登记底稿
for f in sorted(glob.glob(f'{G}/_sign/golden_*.sign.json')):
    rec = json.load(open(f))
    cid = rec['dst'].split('/')[-1].replace('.mp4', '')
    host = rec['host'].replace('overnight/数据/golden/', '')
    hname = host.split('/')[-1]
    if hname in HOSTS:
        pid, axis, model = HOSTS[hname]
    else:
        pid, axis, model = CHOSTS[hname.replace('.mp4', '')]
        host = f'clips/{hname}'
    clip_rel = f'clips/{cid}.mp4'
    v = probe(f'{G}/{clip_rel}')
    assert v['n_frames'] == 8, (cid, v)
    sig = rec['signature']
    assert sign_recheck[cid]['recheck_ok'] is True, cid
    new_items.append({
        'clip_id': cid, 'class': 'A',
        'defect_type': rec['defect'], 'expected_defect': rec['defect'],
        'probable': False,
        'inject_pos': rec['inject_pos'],
        'source_clip': host, 'source_prompt_id': pid, 'axis': axis, 'model': model,
        'observed_evidence': None,
        'paths': {'clip': clip_rel, 'frames': f'frames/{cid}/'},
        'verify': v,
        'construction': {
            'date': '2026-10-09',
            'generated_at': mtime(f'{G}/{clip_rel}'),
            'method': (f"inject_a_timing.py（{rec['inject_pos'].get('builder', '')}）"
                       '金标扩样 A 组时序注入，配方复刻 2026-09-29/30 同类条目，seed 换新'),
            'tool': 'overnight/vpipe/tools/golden_expansion/inject_a_timing.py',
            'seed': rec['seed'],
            'sha256': sha(f'{G}/{clip_rel}'),
            'signature_selfcheck': {
                'ok': sig['ok'],
                'evidence': {k: val for k, val in sig.items() if k != 'ok'},
                'evidence_file': f'_sign/{cid}.sign.json',
                'independent_recheck_20261009': True,
            },
        },
    })

vidu = {m['task_id']: m for m in
        (json.load(open(f)) for f in glob.glob(f'{G}/_avatar_expansion/vidu/*.meta.json'))}
T1, T2, T3, T4, T5 = ('1005950171411910656', '1005950411405815808', '1005950605375610880',
                      '1005951074575609856', '1005951268516036608')


def avatar_item(cid, task_video, cls, defect, inject_pos, obs, note_extra):
    clip_rel = f'clips/{cid}.mp4'
    v = probe(f'{G}/{clip_rel}')
    assert v['n_frames'] == 8, (cid, v)
    m = vidu[task_video]
    return {
        'clip_id': cid, 'class': cls,
        'defect_type': defect, 'expected_defect': defect,
        'probable': False,
        'inject_pos': inject_pos,
        'source_clip': f'_avatar_expansion/vidu/avatar_{task_video}.mp4',
        'source_prompt_id': f'vidu_task_{task_video}',
        'axis': 'AVATAR_EXPANSION', 'model': f"Vidu S2 offline_avatar ({m['resolution']})",
        'observed_evidence': obs,
        'paths': {'clip': clip_rel, 'frames': f'frames/{cid}/'},
        'verify': v,
        'construction': {
            'date': '2026-10-09',
            'generated_at': mtime(f'{G}/{clip_rel}'),
            'method': note_extra,
            'tool': 'gen_avatar.py@vpipe-v4-1.0 + ffmpeg 本地后处理',
            'seed': None,
            'sha256': sha(f'{G}/{clip_rel}'),
            'upstream_generation': {
                'vidu_task_id': task_video,
                'generated_at': m['generated_at'],
                'resolution': m['resolution'],
                'credits_reported': m['credits']['reported'],
                'ref_image': 'overnight/vpipe/out/m2/shortdrama_ep01/avatar/ref_shot09_mid.png',
                'tts_audio': m['repro']['audio']['path'],
                'meta_file': f'_avatar_expansion/vidu/avatar_{task_video}.meta.json',
            },
        },
    }


new_items.append(avatar_item(
    'golden_053', T1, 'B', 'lip_sync_desync',
    {'mode': 'audio_delay', 'delay_s': 0.5, 'builder': 'ffmpeg 音频整体右移 0.5s（视频流原样）'},
    '音轨相对口型实测延迟 +0.500s（16kHz 互相关：MAD 78 @+500ms vs 4681 @0ms）',
    'Vidu avatar 真实生成（L1 台词）后 ffmpeg 音频延迟 0.5s 制造唇形不同步；保留音轨'
    '（唇形同步评估必需，偏离金标 -an 协议，必要偏差如实记录）；帧图 2026-10-09 收尾补抽 8 帧（前序只抽到 7 帧）'))

new_items.append(avatar_item(
    'golden_054', T2, 'B', 'lip_script_mismatch',
    {'mode': 'av_cross_pair',
     'video_from': f'avatar_{T2}（L2 台词口型）',
     'audio_from': f'avatar_{T1}（L1 台语音轨）',
     'builder': 'ffmpeg 视频流 avatar2 × 音轨 avatar1 交叉合成'},
    '音轨实测=avatar1/L1 台词（互相关 MAD 58@0ms），口型=avatar2/L2 生成——口型与台词错位',
    'Vidu avatar 真实生成 2 条后音画交叉配对（视频 L2 口型 × 音频 L1 台词）制造口型与台词错位；'
    '保留音轨（必要偏差如实记录）。构造方式与方案 §2.1「1 条音频故意错位」的记载不同，同属意图类构造，如实登记'))

for cid, T, note in [
    ('golden_055', T3, 'Vidu avatar 真实生成口播干净正例（L3 台词，540p），转码统一 crf18 + 去音轨（-an，同金标协议）'),
    ('golden_056', T4, 'Vidu avatar 真实生成口播干净正例（L4 台词，720p），转码统一 crf18 + 去音轨（-an，同金标协议）'),
    ('golden_057', T5, 'Vidu avatar 真实生成口播干净正例（L5 台词，540p），转码统一 crf18 + 去音轨（-an，同金标协议）')]:
    new_items.append(avatar_item(cid, T, 'C', None, None, None, note))

# ---- counts + 登记写回
cnt = Counter(i['class'] for i in man['items'] + new_items)
man['counts'] = {'A': cnt['A'], 'B': cnt['B'], 'C': cnt['C'],
                 'total': len(man['items']) + len(new_items)}
man['items'].extend(new_items)
man['expanded_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
man['expansion_note'] = (
    '2026-10-09 D-3 扩样 +17（041-052 A 组时序注入 freeze/swap/ghosting/flicker 各+3，'
    'inject_a_timing.py v2 builder + 帧级签名自检全数生效并独立复核；053/054 B 组口播意图'
    '（053 音频+0.5s 延迟、054 音画交叉配对）；055-057 C 组口播干净 540p/720p 两档，-an 同协议）。'
    '与 evidence/golden-expansion-plan.md §2.1 的差异如实记录：'
    '①C 组 API 乱码正例 2 条（H3-Max）未构造——17 条新增中无 H3-Max 产物，该缺口仍在，'
    'J1 G2 召回在金标上仍无新正例可量；'
    '②B 组第 2 条构造方式为音画交叉配对（方案只写了音频错位）；'
    '③053/054 保留音轨（唇形评估必需，偏离 -an 协议）；'
    '④扩样后 A28/B14/C15=57。'
    '新增条目含 sha256/seed/generated_at/construction 字段（旧 40 条无此字段，保持原样）')
man['failures'] = []

json.dump(man, open(f'{G}/manifest.json', 'w'), ensure_ascii=False, indent=1)
print('counts:', man['counts'], '| failures:', man['failures'], '| items:', len(man['items']))

missing = []
for it in man['items']:
    if not os.path.exists(f"{G}/{it['paths']['clip']}"):
        missing.append(it['paths']['clip'])
    n = len(glob.glob(f"{G}/{it['paths']['frames']}/f*.jpg"))
    if n != 8:
        missing.append(f"{it['paths']['frames']} n={n}")
print('missing/abnormal:', missing)
for it in man['items'][-3:]:
    assert sha(f"{G}/{it['paths']['clip']}") == it['construction']['sha256']
print('sha re-verify last3: OK')
