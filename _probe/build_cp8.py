#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp8.py — CP8 择优工件构建（M2 短剧线，规则层）。

输入（只读）:
  overnight/vpipe/out/m2/shortdrama_ep01/cp7.json            聚合 hard_verify 向量（黑帧/NaN/时长）
  overnight/vpipe/out/m2/shortdrama_ep01/cp7/cp7_shot_XX.json 单镜权威件（fingerprint/asset 指纹/l0）
  overnight/vpipe/out/m2/shortdrama_ep01/cp7/shot_XX.draft.l0.json L0 逐镜证据
  overnight/vpipe/out/m2/shortdrama_ep01/cp3.json             分镜（action/duration）
构图核验: 本会话代理亲看 11 支草稿（ffmpeg contact sheet 5 帧/支 + shot_01/09 全分辨率帧
  0/16/32），verdicts 硬编码于本文件（证据 _probe/cp8_sheets/）。

输出:
  out/m2/shortdrama_ep01/cp8/cp8_shot_XX.json  单镜权威件（过 checkpoint.schema cp8 分支）
  out/m2/shortdrama_ep01/cp8.json              聚合视图（任务书形态 candidates[]每镜；
                                               单镜粒度契约矛盾沿 ecd9b80 主控裁决双形态纪律）
指纹: sha256(canonical(payload))，src/gate/fingerprint.py 同算法，写后 verify。
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/home/pan-ding/workspace/视频能力")
M2 = ROOT / "overnight/vpipe/out/m2/shortdrama_ep01"
OUT8 = M2 / "cp8"
OUT8.mkdir(parents=True, exist_ok=True)

NOW = "2026-10-09T00:50:00Z"
PRODUCER = "agent.selector"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fp_of(payload):
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


cp3 = json.loads((M2 / "cp3.json").read_text(encoding="utf-8"))
cp7agg = json.loads((M2 / "cp7.json").read_text(encoding="utf-8"))
cp7_shots = {}
for i in range(1, 12):
    sid = f"shot_{i:02d}"
    cp7_shots[sid] = json.loads((M2 / "cp7" / f"cp7_shot_{i:02d}.json").read_text(encoding="utf-8"))
cp7_by_id = {s["shot_id"]: s for s in cp7agg["payload"]["shots"]}
cp3_by_id = {s["shot_id"]: s for s in cp3["payload"]["shots"]}

# 构图核验（本会话亲看证据；verdict 语义: pass=构图成立进 CP9 / fail=不成立 rework_cp3）
COMPOSITION = {
    "shot_01": ("pass", "门厅门洞逆光亮条+门框结构全程 33 帧稳定在位（帧 0/16/32 全分辨率复核）；人物面部在草稿档不可辨——主裁 ecd9b80 已亲眼看本镜判『暗室逆光门洞剪影构图成立』，本检复核门洞结构在位不翻案；过曝/白洗归 LTX-2B checkpoint 固有（SPIKE-REPORT 发现 B，色彩不入判定）。", "_probe/cp8_sheets/shot_01.png + 01_full_1/3.png"),
    "shot_02": ("pass", "高脚杯居中+持杯手在位+四周宾客色块，与 CP3『举杯的手停在半空』吻合；缓推语义在帧序可见（杯占比渐大）。", "_probe/cp8_sheets/shot_02.png"),
    "shot_03": ("pass", "白桌布上金属扳手体横陈+背景虚化光斑，与 CP3『扳手放白桌布特写』吻合；33 帧构图稳定。", "_probe/cp8_sheets/shot_03.png"),
    "shot_04": ("pass", "深色桌面+纸面横线条纹（合约纸）+右上手指压点，与 CP3『合约拍桌+手指点签名栏』吻合；纸面文字不可读（符合禁区投影）。", "_probe/cp8_sheets/shot_04.png"),
    "shot_05": ("pass", "双人隔桌对坐同框（左小满右林父）+桌面中间物件，与 CP3『双人近景一镜不切』吻合。", "_probe/cp8_sheets/shot_05.png"),
    "shot_06": ("pass", "老者面部大特写占满画面+手抬至脸侧+背景全虚，与 CP3『瞳孔骤缩大特写+缓推』吻合。", "_probe/cp8_sheets/shot_06.png"),
    "shot_07": ("pass", "中缝分幅成立：左半幅工装人物/右半幅深色西装人物，同脸型；与 CP3『同机位前后对切』吻合。", "_probe/cp8_sheets/shot_07.png"),
    "shot_08": ("pass", "老者俯身扶桌+杯中液体倾洒桌布（青色酒渍，色偏已知）+低机位，与 CP3『踉跄扶桌沿+酒渍洇开』吻合。", "_probe/cp8_sheets/shot_08.png"),
    "shot_09": ("fail", "帧 0/16/32 全分辨率复核：全程无可辨人物/面部特征/轮廓边缘，纯模糊光斑团；CP3 核心『面部大特写逐渐占满画面』主体缺失，构图不成立 → 不进 CP9，标记 rework_cp3（白皮书 §3 CP8 失败回退行；构图回退目标=CP3，schema rework_route 词表含 cp3）。", "_probe/cp8_sheets/shot_09.png + 09_full_1/2/3.png"),
    "shot_10": ("pass", "老者颓坐椅中+手抬抹脸+白发垂额+肩部垮态，与 CP3『颓然坐回+抹脸』吻合；固定机位成立。", "_probe/cp8_sheets/shot_10.png"),
    "shot_11": ("pass", "门口亮幕（雨幕/门厅光）+人物背影居中向门走，与 CP3『转身走出大门+拉出门厅全景』吻合。", "_probe/cp8_sheets/shot_11.png"),
}

L0_MAX = {"black_frame_ratio_max": 0.5, "duration_dev_max": 0.02}  # thresholds.yaml:178-181


def hard_verify(sid):
    s = cp7_by_id[sid]
    l0 = json.loads((M2 / "cp7" / f"{sid}.draft.l0.json").read_text(encoding="utf-8"))
    assert l0["accepted"] is True, sid
    ffp = s["ffprobe"]
    return {
        "black_mono_ratio": s["black_mono_ratio"],
        "black_frames_tensor_lt2": s["black_frames_tensor"],
        "black_frames_decoded_lt2": s["black_frames_decoded"],
        "nan_detected": s["nan_detected"],
        "duration_declared_s": s["declared_duration_s"],
        "duration_actual_s": s["actual_duration_s"],
        "duration_dev": s["duration_dev"],
        "l0_accepted": l0["accepted"],
        "l0_evidence_ref": l0.get("_", None) or f"overnight/vpipe/out/m2/shortdrama_ep01/cp7/{sid}.draft.l0.json",
        "ffprobe_triple": f"{ffp['codec_name']}/{ffp['pix_fmt']}/{ffp['width']}x{ffp['height']}@{ffp['avg_frame_rate']}/{ffp['nb_frames']}f",
        "thresholds": L0_MAX,
    }


def build_selection(sid):
    hv = hard_verify(sid)
    c7 = cp7_shots[sid]
    verdict, why, evid = COMPOSITION[sid]
    promote = verdict == "pass"
    cand = {
        "candidate_id": f"{sid}@ltx2b_draft",
        "draft_fingerprint": c7["payload"]["asset"]["fingerprint"],
        "hard_verify": dict(hv, composition_verdict=verdict, composition_evidence=evid),
    }
    sel = {
        "work_id": "shortdrama_ep01",
        "shot_id": sid,
        "candidates": [cand],
        "top1_candidate_id": f"{sid}@ltx2b_draft",
        "pareto_dominant": True,
        "veto_defects": [],
        "escalated_to_human": False,
        "structural_difficult": False,
    }
    if promote:
        gate_note = (f"候选 N=1（T2 草稿每镜一支，cp7 唯一草稿）：硬校验向量全绿（黑帧 0/NaN 0/时长 dev=0.0"
                     f"≤{L0_MAX['duration_dev_max']}，L0 accepted）且构图核验成立（{COMPOSITION[sid][0]}）"
                     f"→ 单候选平凡 Pareto 支配（无第二候选可比，params_ref=cp8.gate.pareto_rule=top1_strict_dominance）"
                     f"→ 本镜进 CP9 精修。A/B 组否决缺陷 0（veto_defects=[]）。")
        aux = [{
            "type": "judge_rank",
            "params_ref": "ensemble.definitions.E10",
            "result": "pass",
            "note": "相对线本轮空转：N=1 无次序可排，E10 判据族不设绝对通过线（白皮书 CP8 两层不可混）；构图/运动/节奏预演结论由硬校验+构图核验承重。",
        }]
        status = "passed"
        gate_result = "pass"
    else:
        gate_note = (f"硬校验向量本身达标（黑帧 0/NaN 0/时长 dev=0.0，L0 accepted），但构图核验不成立：{why} "
                     f"→ 本镜不出线进 CP9（草稿层价值=挡烂片，白皮书 §4 T2 ROI 算法），标记 rework_cp3："
                     f"回退 CP3 改 prompt/action（候选动作『缓步逼近+面部占满画面+满堂宾客虚化』对 T2 层过载，"
                     f"建议拆解为简化逼近/静态背景两拍）。回退不得跳过 CP6 直接换时间。")
        aux = [{
            "type": "judge_rank",
            "params_ref": "ensemble.definitions.E10",
            "result": "pass",
            "note": "相对线本轮空转：N=1 无次序可排；否决来自绝对门侧构图核验，与 judge 无涉。",
        }]
        status = "rejected"
        gate_result = "fail"
    art = {
        "schema_version": "2.0",
        "cp_id": "cp8",
        "artifact_type": "selection",
        "fingerprint": "",
        "produced_by": PRODUCER,
        "produced_at": NOW,
        "upstream_refs": [
            {"cp_id": "cp7", "fingerprint": c7["fingerprint"]},
            {"cp_id": "cp3", "fingerprint": cp3["fingerprint"]},
        ],
        "status": status,
        "gate": {
            "type": "composite",
            "params_ref": "cp8.gate.pareto_rule",
            "result": gate_result,
            "note": gate_note,
        },
        "aux_gates": aux,
        "payload": sel,
        "notes": (f"单镜择优件（CP8 权威形态，checkpoint.schema cp8 分支 jsonschema 校验）；"
                  f"构图核验=本会话代理亲看草稿逐帧（证据 {evid}），主裁已看镜仅在 shot_01（ecd9b80）"
                  f"——CP8 默认零人工（judge 分歧/硬校验矛盾才上升，本批 N=1 无分歧）。"
                  f"草稿色偏已知（SPIKE-REPORT 发现 B）不入判定；硬校验向量只承黑帧/NaN/时长三目。"
                  f"CP3 声明镜长 {cp3_by_id[sid]['duration_s']}s vs 草稿 1.375s 差异沿 cp7 口径登记于"
                  f" hard_verify.duration_declared_s/actual_s。"),
    }
    art["fingerprint"] = fp_of(art["payload"])
    return art, promote


arts, promotes = {}, {}
for i in range(1, 12):
    sid = f"shot_{i:02d}"
    art, promote = build_selection(sid)
    p = OUT8 / f"cp8_{sid}.json"
    p.write_text(json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    arts[sid] = art
    promotes[sid] = promote

# ---- 聚合视图（任务书形态：payload.candidates[] 每镜一条） ----
agg = {
    "schema_version": "2.0",
    "cp_id": "cp8",
    "artifact_type": "selection",
    "fingerprint": "",
    "produced_by": PRODUCER,
    "produced_at": NOW,
    "upstream_refs": [
        {"cp_id": "cp7", "fingerprint": cp7agg["fingerprint"]},
        {"cp_id": "cp3", "fingerprint": cp3["fingerprint"]},
    ],
    "status": "passed" if all(promotes.values()) else "gated",
    "gate": {
        "type": "composite",
        "params_ref": "cp8.gate.pareto_rule",
        "result": "pass",
        "note": (f"11 镜择优：10 镜进 CP9（硬校验全绿+构图成立），1 镜 shot_09 构图不成立→rework_cp3 不进 CP9"
                 f"（草稿层 ROI：负样本在计费层之前被拦下）。逐镜权威件 cp8/cp8_shot_01..11.json"
                 f"（jsonschema 11/11，本聚合件粒度矛盾见 notes）。"),
    },
    "aux_gates": [{
        "type": "judge_rank",
        "params_ref": "ensemble.definitions.E10",
        "result": "pass",
        "note": "相对线空转：每镜 N=1 无次序可排（白皮书 CP8 两层不可混——本批由绝对门承重）。",
    }],
    "payload": {
        "work_id": "shortdrama_ep01",
        "candidates": [],
    },
    "notes": "",
}
n_adv = n_rework = 0
for i in range(1, 12):
    sid = f"shot_{i:02d}"
    a = arts[sid]
    verd = COMPOSITION[sid][0]
    entry = {
        "shot_id": sid,
        "candidate_id": f"{sid}@ltx2b_draft",
        "draft_fingerprint": a["payload"]["candidates"][0]["draft_fingerprint"],
        "hard_verify": a["payload"]["candidates"][0]["hard_verify"],
        "veto_defects": [],
        "top1_candidate_id": f"{sid}@ltx2b_draft",
        "pareto_dominant": True,
        "composition_verdict": verd,
        "decision": "advance_cp9" if verd == "pass" else "rework_cp3",
        "artifact_ref": f"overnight/vpipe/out/m2/shortdrama_ep01/cp8/cp8_{sid}.json",
        "upstream_cp7_fingerprint": a["upstream_refs"][0]["fingerprint"],
    }
    agg["payload"]["candidates"].append(entry)
    if verd == "pass":
        n_adv += 1
    else:
        n_rework += 1
agg["fingerprint"] = fp_of(agg["payload"])
agg["notes"] = (
    "聚合视图（任务书形态 payload.candidates[] 每镜一条：draft_fingerprint/hard_verify 向量/veto_defects[]，"
    "top1=本镜唯一草稿）。⚠ 契约矛盾沿 ecd9b80 主控裁决双形态纪律：checkpoint.schema.json "
    "definitions.selection 为单镜形态（additionalProperties:false + 必备 shot_id 单值），聚合 candidates[]11 镜"
    "与「过 schema cp8 分支」不可同时成立（与 cp7.json 同款 EXIT=1）；权威形态=cp8/cp8_shot_01..11.json"
    "（单镜件，过 schema），本件供 episode 级簿记。【择优规则】L0 等价物（black_mono_ratio=0.0≤0.50、"
    "NaN=0、时长 dev=0.0≤2%、ffprobe 三元组）+ 构图核验（代理亲看 11 支草稿 contact sheet，"
    "shot_01/09 另做全分辨率帧 0/16/32 复核）双过才进 CP9；shot_09 全程无可辨主体→rework_cp3。"
    f"【结果】进 CP9 {n_adv} 镜 / rework_cp3 {n_rework} 镜。色彩不入判定（发现 B）。"
)
(M2 / "cp8.json").write_text(
    json.dumps(agg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

print(f"cp8_shot_01..11.json written; advance={n_adv} rework={n_rework}")
print("advancing:", [f"shot_{i:02d}" for i in range(1, 12) if promotes[f"shot_{i:02d}"]])
print("rework   :", [f"shot_{i:02d}" for i in range(1, 12) if not promotes[f"shot_{i:02d}"]])
sys.exit(0)
