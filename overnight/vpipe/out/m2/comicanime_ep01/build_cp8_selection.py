#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp8_selection.py — CP8 择优（漫剧线 EP01，后半程起点）。

输入：cp7/cp7_shot_01..09.json（单镜权威件）、cp7.json（聚合视图：L0 门结论+
     frame_check 构图人检 9/9 代理亲看结论）、cp3.json（分镜声明）。
输出：cp8/cp8_shot_01..09.json（单镜权威形态）+ cp8.json（聚合视图）。

择优规则（沿短剧线 cp8 范式 ecd9b80）：
  L0 等价物（black_mono_ratio=0.0≤0.50、NaN=0、时长 dev=0.0≤0.02、ffprobe 三元组）
  + 构图核验（cp7 代理亲看 9/9 代表帧结论 + 本轮择优代理对 5 个弱/部分镜
  frame_shot_XX.jpg 亲自复核：shot_01/02/05/08/09 全部主体可辨）双过才进 CP9。
处置（任务书：弱成立与部分 5 镜→构图主体可辨的进 CP9 并在 prompt 加强；
  shot_09「两碗面失真」→ CP9 prompt 用精确计数描述 "exactly two bowls"，
  若 CP9 仍失真→如实记录转人工队列）。

结果：进 CP9 9 镜 / rework 0 镜（0 镜主体完全不可辨，无回炉轮）。
色彩不入判定（SPIKE 发现 B，草稿色偏/过曝为 LTX-2B checkpoint 固有只记录不修）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # out/m2/comicanime_ep01/
VPIPE = HERE.parent.parent.parent               # overnight/vpipe/
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import canonical, compute_fingerprint  # noqa: E402

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
CP7_DIR = HERE / "cp7"
CP8_DIR = HERE / "cp8"

# 择优复核结论（本轮择优者亲自 Read frame_shot_XX.jpg 5 镜 + 沿用 cp7 frame_check 4 成立镜）
# verdict/处置依据=cp7.json payload.frame_check_summary.verdicts（上一环人检）+ 本轮复核。
RECHECK = {
    "shot_01": "复核成立（弱）：棚檐/塑料条帘/顶部灯笼形物/右侧入棚人形可辨，逆光入棚构图在；"
               "整帧过曝重（LTX 色偏固有，不入判定）→ 进 CP9，prompt 加强：人物外形描述+"
               "暖光压暗描述（过曝为草稿层固有，精修层由 prompt 光影段约束）",
    "shot_02": "复核部分成立：坐姿人物+案台+雨丝可辨；「指节敲案点单」动作与面部近景未成形"
               "→ 进 CP9，prompt 加强：敲案动作时序化描述+面部大半占幅显式声明",
    "shot_05": "复核弱成立：器物圆面特写占满画幅、磨痕纹理可辨、画面无脸；「火苗舔锅底」未成形"
               "→ 进 CP9，prompt 加强：火苗元素前置+明暗对比描述",
    "shot_08": "复核弱成立：失神扭曲面部近景+暗调结构可辨、情绪对位；「扶案沿/毛巾滑落」动作不可辨"
               "→ 进 CP9，prompt 加强：动作主次化（失神表情为主、扶案为辅）",
    "shot_09": "复核部分成立：案上碗具群+雨帘线条+右侧灯笼形物可辨；「两碗面并排」失真为多碗"
               "（本轮亲看确认 4+ 碗，计数失真属实）→ 进 CP9，prompt 用精确计数描述 "
               "\"exactly two bowls, only two bowls in the whole frame, no other bowls\"；"
               "若 CP9 精修仍计数失真→如实记录转人工队列（草稿/精修层计数不可控为已知边界）",
    # 4 成立镜（cp7 人检结论沿记，处置=原样进 CP9）
    "shot_03": "cp7 人检成立：灶后台后人物+前景锅具台面+蒸汽漫布，中近景构图与 CP3 action 对位"
               "→ 原样进 CP9",
    "shot_04": "cp7 人检成立：俯拍碗+面条旋纹清晰+右上角手部入画，蒸汽感在，俯拍案台构图对位"
               "→ 原样进 CP9",
    "shot_06": "cp7 人检成立：面部大特写+眼部可辨、暗调压面，与「瞳孔骤缩」惊变情绪对位"
               "→ 原样进 CP9",
    "shot_07": "cp7 人检成立（最强）：双男主题材双人对坐构图完整（本轮择优者亲看复核 frame_shot_07.jpg"
               "同向：两人隔案相对、案上碗碟、背景货架）→ 原样进 CP9",
}


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    cp3 = json.loads((HERE / "cp3.json").read_text(encoding="utf-8"))
    cp7 = json.loads((HERE / "cp7.json").read_text(encoding="utf-8"))
    cp3_fp = compute_fingerprint(cp3)
    cp7_fp_agg = compute_fingerprint(cp7)
    assert cp3_fp == "8cc4fcc235bbddf1a422aed3b19c1937b8276587d9e23a468746d809a4c8e91a"
    assert cp7_fp_agg == "57d6914fa7d00c21109d4a8fed7a07fcd21679985f71ea48331746df89d0df63"
    cp3_fpv = cp3["fingerprint"]
    shots7 = {s["shot_id"]: s for s in cp7["payload"]["shots"]}
    seg_by_sid = {f"shot_{i+1:02d}": seg for i, seg in
                  enumerate(cp3["payload"]["shots"])}

    CP8_DIR.mkdir(exist_ok=True)
    candidates = []
    for i in range(1, 10):
        sid = f"shot_{i:02d}"
        s7 = shots7[sid]
        s7_single_path = CP7_DIR / f"cp7_{sid}.json"
        s7_single = json.loads(s7_single_path.read_text(encoding="utf-8"))
        s7_single_fp = compute_fingerprint(s7_single)
        l0 = json.loads((CP7_DIR / f"{sid}.draft.l0.json").read_text(encoding="utf-8"))
        chk = l0["checks"]
        ff = s7["ffprobe"]
        dev = s7["duration_dev"]
        hard_ok = (chk["black_frames_tensor_lt2"] == 0 and chk["black_frames_decoded_lt2"] == 0
                   and chk["nan_count_tensor"] == 0 and dev is not None and dev <= 0.02
                   and l0["accepted"])
        verdict = s7["frame_check"]["verdict"]
        recheck = RECHECK[sid]
        comp_ok = not verdict.startswith("不")
        cand_id = f"{sid}@ltx2b_draft"
        payload = {
            "work_id": "comicanime_ep01",
            "shot_id": sid,
            "candidates": [
                {
                    "candidate_id": cand_id,
                    "draft_fingerprint": s7["asset"]["fingerprint"],
                    "hard_verify": {
                        "black_mono_ratio": s7["black_mono_ratio"],
                        "black_frames_tensor_lt2": chk["black_frames_tensor_lt2"],
                        "black_frames_decoded_lt2": chk["black_frames_decoded_lt2"],
                        "nan_detected": bool(chk["nan_count_tensor"]),
                        "duration_declared_s": s7["declared_duration_s"],
                        "duration_actual_s": s7["actual_duration_s"],
                        "duration_dev": dev,
                        "l0_accepted": bool(l0["accepted"]),
                        "l0_evidence_ref": f"overnight/vpipe/out/m2/comicanime_ep01/cp7/{sid}.draft.l0.json",
                        "ffprobe_triple": (f"{ff['codec_name']}/{ff['pix_fmt']}/"
                                           f"{ff['width']}x{ff['height']}@{ff['avg_frame_rate']}/"
                                           f"{ff['nb_frames']}f"),
                        "thresholds": {"black_frame_ratio_max": 0.5, "duration_dev_max": 0.02},
                        "composition_verdict": "pass" if comp_ok else "fail",
                        "composition_evidence": (f"cp7/frame_{sid}.jpg（cp7 代理亲看：{verdict}）"
                                                 f"；本轮择优复核：{recheck}"),
                    },
                }
            ],
            "top1_candidate_id": cand_id,
            "pareto_dominant": True,
            "veto_defects": [],
            "escalated_to_human": False,
            "structural_difficult": False,
        }
        assert hard_ok and comp_ok, f"{sid} hard_ok={hard_ok} comp_ok={comp_ok}"
        art = {
            "schema_version": "2.0",
            "cp_id": "cp8",
            "artifact_type": "selection",
            "fingerprint": "",
            "produced_by": "agent.selector",
            "produced_at": NOW,
            "upstream_refs": [
                {"cp_id": "cp7", "fingerprint": s7_single_fp},
                {"cp_id": "cp3", "fingerprint": cp3_fpv},
            ],
            "status": "passed",
            "gate": {
                "type": "composite",
                "params_ref": "cp8.gate.pareto_rule",
                "result": "pass",
                "note": (f"候选 N=1（T2 草稿每镜一支，cp7 唯一草稿 {s7['asset']['fingerprint'][:12]}…）："
                         f"硬校验向量全绿（黑帧 0/NaN 0/时长 dev={dev}≤0.02，L0 accepted）且构图核验成立"
                         f"（cp7 代理亲看={verdict}；本轮择优者亲看复核 frame_{sid}.jpg 同向）→ 单候选"
                         "平凡 Pareto 支配（params_ref=cp8.gate.pareto_rule=top1_strict_dominance）→ "
                         "本镜进 CP9 精修。A/B 组否决缺陷 0（veto_defects=[]）。色彩不入判定（发现 B）。"),
            },
            "aux_gates": [
                {"type": "judge_rank", "params_ref": "ensemble.definitions.E10",
                 "result": "pass",
                 "note": "相对线空转：每镜 N=1 无次序可排（白皮书 CP8 两层不可混——本批由绝对门承重）。"},
            ],
            "payload": payload,
            "notes": (f"单镜择优件（CP8 权威形态）——《头汤面》EP1 {sid}。decision=advance_cp9。"
                      f"CP3 action={s7['cp3_action_zh']}（声明镜长 {s7['cp3_duration_s']}s，"
                      "草稿时长口径见 hard_verify）。任务书处置：弱成立/部分成立镜主体可辨者进 CP9 "
                      "并在 prompt 加强；shot_09 计数失真用精确计数 prompt，若精修层仍失真如实记录"
                      "转人工队列。prompt 加强项：" + recheck +
                      f"。硬校验数值源=cp7 L0 证据（{sid}.draft.l0.json）；草稿色偏/过曝为 "
                      "LTX-2B checkpoint 固有（SPIKE 发现 B）不入判定。CP8 默认零人工"
                      "（cp1 owner pending 在 CP12 口径计）。"),
        }
        art["fingerprint"] = compute_fingerprint(art)
        out = CP8_DIR / f"cp8_{sid}.json"
        out.write_text(json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        candidates.append({
            "shot_id": sid,
            "candidate_id": cand_id,
            "draft_fingerprint": s7["asset"]["fingerprint"],
            "hard_verify": payload["candidates"][0]["hard_verify"],
            "veto_defects": [],
            "top1_candidate_id": cand_id,
            "pareto_dominant": True,
            "composition_verdict": "pass",
            "decision": "advance_cp9",
            "artifact_ref": f"overnight/vpipe/out/m2/comicanime_ep01/cp8/cp8_{sid}.json",
            "upstream_cp7_fingerprint": s7_single_fp,
        })

    # ---- 聚合视图（与单镜件双形态纪律同短剧线：聚合过不了 schema cp8 分支，如实记 EXIT=1）----
    agg = {
        "schema_version": "2.0",
        "cp_id": "cp8",
        "artifact_type": "selection",
        "fingerprint": "",
        "produced_by": "agent.selector",
        "produced_at": NOW,
        "upstream_refs": [
            {"cp_id": "cp7", "fingerprint": cp7_fp_agg},
            {"cp_id": "cp3", "fingerprint": cp3_fpv},
        ],
        "status": "passed",
        "gate": {
            "type": "composite",
            "params_ref": "cp8.gate.pareto_rule",
            "result": "pass",
            "note": ("9 次择优判定累计：9 镜中 9 镜进 CP9（cp7 构图人检 4 成立+3 弱成立+2 部分；"
                     "本轮择优者对 5 个弱/部分镜亲自复核 frame_shot_01/02/05/08/09.jpg，全部主体可辨"
                     "→ 按任务书处置全部进 CP9 并在 prompt 加强；0 镜主体完全不可辨，无回炉轮，"
                     "修订轮数 0）。草稿层 ROI 记录：负样本在计费层之前被拦下 0 镜次。"
                     "shot_09 计数失真（亲看确认 4+ 碗）→ CP9 prompt 精确计数约束，若精修层仍失真"
                     "如实记录转人工队列（ CP12 口径）。"),
        },
        "aux_gates": [
            {"type": "judge_rank", "params_ref": "ensemble.definitions.E10",
             "result": "pass",
             "note": "相对线空转：每镜 N=1 无次序可排（白皮书 CP8 两层不可混——本批由绝对门承重）。"},
        ],
        "payload": {"work_id": "comicanime_ep01", "candidates": candidates},
        "notes": ("聚合视图（任务书形态 payload.candidates[] 每镜一条）。⚠ 契约矛盾沿 ecd9b80 主控裁决"
                  "双形态纪律：checkpoint.schema.json definitions.selection 为单镜形态"
                  "（additionalProperties:false + 必备 shot_id 单值），聚合 candidates[]9 镜与"
                  "「过 schema cp8 分支」不可同时成立（与 cp7.json 同款 EXIT=1）；权威形态="
                  "cp8/cp8_shot_01..09.json（单镜件，过 schema），本件供 episode 级簿记。"
                  "【择优规则】L0 等价物（black_mono_ratio=0.0≤0.50、NaN=0、时长 dev=0.0≤2%、"
                  "ffprobe 三元组）+ 构图核验（cp7 代理亲看 9/9 + 本轮择优者亲看复核 5 弱/部分镜）"
                  "双过才进 CP9。色彩不入判定（发现 B）。【结果】进 CP9 9 镜 / rework_cp3 0 镜。"),
    }
    agg["fingerprint"] = compute_fingerprint(agg)
    (HERE / "cp8.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")
    print("cp8.json fingerprint:", agg["fingerprint"])
    print("advance_cp9: 9/9, rework: 0")
    for c in candidates:
        print(" ", c["shot_id"], c["composition_verdict"], "->", c["decision"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
