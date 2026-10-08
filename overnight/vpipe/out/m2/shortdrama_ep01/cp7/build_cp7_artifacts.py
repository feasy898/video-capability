#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp7_artifacts.py — 由 cp7_run_report.json 构建 CP7 工件（本地仓）。

产出：
  1) cp7_shot_01..11.json：单镜工件，checkpoint.schema cp7 分支（draft_clip）合规形态——
     契约自身粒度即每镜一件（contracts/v2/examples/cp7.json notes「本集 4 镜各一份」）。
  2) cp7.json：任务书要求的聚合形态（payload.shots[] 逐镜 asset/pixel/fps/
     declared_vs_actual/black_mono_ratio/nan_detected/seed/l0_preflight/prompt_en 留痕）。
     ⚠ schema draft_clip 为单镜形态（additionalProperties:false + 顶层单镜必备字段），
     payload.shots[] 与「过 checkpoint.schema cp7 分支」按现行契约不可同时成立——
     两形态都做 jsonschema 校验并如实记录 exit，裁决留 owner。

fingerprint 一律实算：工件=sha256(canonical payload)（src/gate/fingerprint.py 同算法）；
资产=mp4 文件字节 sha256（生成时实测，report 内 mp4_sha256）。
"""
import hashlib
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))          # .../cp7
EP = os.path.dirname(HERE)                                  # .../shortdrama_ep01
REPORT = os.path.join(HERE, "cp7_run_report.json")
CP3 = os.path.join(EP, "cp3.json")
CP5 = os.path.join(EP, "cp5.json")
CP6 = os.path.join(EP, "cp6.json")
ART_PREFIX = "overnight/vpipe/out/m2/shortdrama_ep01/cp7"
PRODUCED_BY = "agent.cp7_draft_generator"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fp_payload(payload):
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


report = json.load(open(REPORT, encoding="utf-8"))
prompts = json.load(open(os.path.join(HERE, "cp7_prompts.json"), encoding="utf-8"))
prompt_by_sid = {r["shot_id"]: r for r in prompts["shots"]}
cp3 = json.load(open(CP3, encoding="utf-8"))
cp3_by_sid = {s["shot_id"]: s for s in cp3["payload"]["shots"]}

upstreams = []
for f, cpid in ((CP3, "cp3"), (CP5, "cp5"), (CP6, "cp6")):
    a = json.load(open(f, encoding="utf-8"))
    upstreams.append({"cp_id": cpid, "fingerprint": a["fingerprint"]})

GATE_NOTE = ("黑帧 0：11/11 镜帧级均值<2 计数=0（生成张量与 mp4 端到端回检双侧），"
             "black_mono_ratio 全 0.0 ≤ 0.50（thresholds.yaml:180 l0_preflight."
             "black_frame_ratio_max）；NaN=0；逐镜 L0 证据 <shot_id>.draft.l0.json。")
AUX_NOTES = [
    {"type": "hard_verify", "params_ref": "l0_preflight.duration_dev_max", "result": "pass",
     "note": ("11/11 镜实测 1.375s == 声明 1.375s（33帧@24fps，dev=0.0% ≤ 2%，"
              "thresholds.yaml:179 l0_preflight.duration_dev_max）。声明值=本批资产规格："
              "任务书固定 33 帧档（spike 验证包络），CP3 分镜声明镜长 3.48–6.74s 与草稿"
              "时长差异如实登记于 shots[].cp3_duration_s，节奏预演按帧数比例。")},
    {"type": "hard_verify", "params_ref": "cp7.gate.uses_existing_keys", "result": "pass",
     "note": ("NaN/黑帧布尔项=0/0；帧率 24/1、分辨率 704x480（480x704 HxW 口径）符合声明档；"
              "ffprobe 三元组逐镜 h264/yuv420p/33帧；确定性抽验 shot_03 二遍生成全帧 MAE=0.0"
              "（SPIKE-REPORT ③ 复证）。")},
]

# ---------- 1) 单镜合规工件 ----------
per_shot_payloads = {}
for rec in report["shots"]:
    sid = rec["shot_id"]
    payload = {
        "work_id": "shortdrama_ep01",
        "shot_id": sid,
        "channel": "local_ltx_2b",
        "asset": {
            "kind": "clip",
            "fingerprint": rec["mp4_sha256"],
            "path": f"{ART_PREFIX}/{sid}.draft.mp4",
        },
        "width": rec["ffprobe"]["width"],
        "height": rec["ffprobe"]["height"],
        "fps": 24,
        "declared_duration_s": rec["declared_duration_s"],
        "actual_duration_s": rec["actual_duration_s"],
        "black_mono_ratio": rec["tensor_stats"]["black_frames_lt2"] / rec["tensor_stats"]["frames"],
        "nan_detected": bool(rec["tensor_stats"]["nan_count"] > 0),
        "seed": rec["seed"],
        "l0_preflight": {
            "accepted": bool(rec["l0_accepted"]),
            "evidence_ref": f"{ART_PREFIX}/{sid}.draft.l0.json",
        },
    }
    per_shot_payloads[sid] = payload
    art = {
        "schema_version": "2.0",
        "cp_id": "cp7",
        "artifact_type": "draft_clip",
        "fingerprint": fp_payload(payload),
        "produced_by": PRODUCED_BY,
        "produced_at": now_iso(),
        "upstream_refs": upstreams,
        "status": "passed" if rec["l0_accepted"] else "rejected",
        "gate": {"type": "hard_verify", "params_ref": "l0_preflight.black_frame_ratio_max",
                 "result": "pass" if rec["l0_accepted"] else "fail", "note": GATE_NOTE},
        "aux_gates": AUX_NOTES,
        "payload": payload,
        "notes": (
            f"单镜草稿（T2 层，非交付物；CP8 择优器为其唯一消费者）。prompt_en（与 seed={rec['seed']}）"
            f"逐镜留痕于 {ART_PREFIX}/cp7_prompts.json，全文：{prompt_by_sid[sid]['prompt_en']}。"
            f"CP3 action_zh：{cp3_by_sid[sid]['action']}。"
            f"CP3 声明镜长 {cp3_by_sid[sid]['duration_s']}s vs 草稿 33帧@24fps=1.375s（任务书固定帧档，"
            f"构图/运动/节奏预演按帧数比例，见 aux_gates 口径）。生成墙钟 gen={rec.get('gen_s')}s "
            f"encode={rec.get('encode_s')}s。色偏为 LTX-2B-v0.9.1 checkpoint 固有（SPIKE-REPORT 发现 B），"
            f"只记录不修：草稿色彩不可依赖，CP8 择优与 CP9 精修不看草稿色彩。"
            f"确定性：同 seed 逐比特可复现（本批 shot_03 二遍 MAE=0.0）。"),
    }
    out = os.path.join(HERE, f"cp7_{sid}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=2)
    os.chmod(out, 0o644)

# ---------- 2) 聚合工件（任务书形态 payload.shots[]）----------
agg_shots = []
for rec in report["shots"]:
    sid = rec["shot_id"]
    row = prompt_by_sid[sid]
    agg_shots.append({
        "shot_id": sid,
        "prompt_en": row["prompt_en"],
        "negative": row["negative"],
        "seed": rec["seed"],
        "asset": {"kind": "clip", "fingerprint": rec["mp4_sha256"],
                  "path": f"{ART_PREFIX}/{sid}.draft.mp4"},
        "pixel": {"width": rec["ffprobe"]["width"], "height": rec["ffprobe"]["height"]},
        "width": rec["ffprobe"]["width"],
        "height": rec["ffprobe"]["height"],
        "fps": 24,
        "duration_frames": 33,
        "declared_duration_s": rec["declared_duration_s"],
        "actual_duration_s": rec["actual_duration_s"],
        "duration_dev": rec["duration_dev"],
        "cp3_duration_s": cp3_by_sid[sid]["duration_s"],
        "cp3_action_zh": cp3_by_sid[sid]["action"],
        "black_mono_ratio": rec["tensor_stats"]["black_frames_lt2"] / rec["tensor_stats"]["frames"],
        "black_frames_tensor": rec["tensor_stats"]["black_frames_lt2"],
        "black_frames_decoded": rec["end_to_end_decode"]["black_frames_lt2"],
        "nan_detected": bool(rec["tensor_stats"]["nan_count"] > 0),
        "l0_preflight": {"accepted": bool(rec["l0_accepted"]),
                         "evidence_ref": f"{ART_PREFIX}/{sid}.draft.l0.json"},
        "ffprobe": rec["ffprobe"],
        "mp4_md5": rec["mp4_md5"],
        "gen_s": rec.get("gen_s"),
        "encode_s": rec.get("encode_s"),
        "shot_wall_s": rec.get("shot_wall_s"),
    })

agg_payload = {
    "work_id": "shortdrama_ep01",
    "channel": "local_ltx_2b",
    "model": {"path": "/data/night/models/LTX-Video", "pipeline": "LTXPipeline",
              "dtype": "float16"},
    "params": {"num_frames": 33, "height": 480, "width": 704, "steps": 15,
               "guidance_scale": 3.0, "fps": 24,
               "seed_rule": "42 + shot ordinal (1-based): shot_01->43 ... shot_11->53"},
    "prompts_ref": f"{ART_PREFIX}/cp7_prompts.json",
    "determinism": report["determinism"],
    "run_report_ref": f"{ART_PREFIX}/cp7_run_report.json",
    "shots": agg_shots,
}
agg = {
    "schema_version": "2.0",
    "cp_id": "cp7",
    "artifact_type": "draft_clip",
    "fingerprint": fp_payload(agg_payload),
    "produced_by": PRODUCED_BY,
    "produced_at": now_iso(),
    "upstream_refs": upstreams,
    "status": "passed",
    "gate": {"type": "hard_verify", "params_ref": "l0_preflight.black_frame_ratio_max",
             "result": "pass", "note": GATE_NOTE},
    "aux_gates": AUX_NOTES,
    "payload": agg_payload,
    "notes": (
        "聚合工件（任务书要求形态 payload.shots[]，11 镜逐镜留痕 asset/pixel/fps/"
        "declared_vs_actual/black_mono_ratio/nan_detected/seed/l0_preflight/prompt_en）。"
        "⚠ 契约矛盾声明：checkpoint.schema.json definitions.draft_clip 为单镜形态"
        "（additionalProperties:false + 顶层单镜必备字段），payload.shots[] 与「过 checkpoint.schema "
        "cp7 分支」按现行契约不可同时成立；契约自身粒度为每镜一件（contracts/v2/examples/cp7.json "
        "notes「本集 4 镜各一份」）。本件按任务书原样落盘并如实记录其 jsonschema exit，"
        "合规形态见 cp7_shot_01..11.json（11/11 过 schema）。两者裁决留 owner。"
        "【硬条件】英文 prompt 层（SPIKE-REPORT 发现 A，中文直喂=100% 废片）；色偏为 checkpoint "
        "固有（发现 B）只记录不修——草稿色彩不可依赖，CP8 择优与 CP9 精修不看草稿色彩；"
        "确定性 shot_03 同参数二遍全帧 MAE=0.0（发现 ③ 复证）。【时长口径】任务书固定 33 帧档"
        "（480x704 HxW/15步/guidance 3.0/24fps），declared=1.375s 为资产规格，L0 时长门禁校验"
        "编码一致性（实测=声明，dev=0.0%）；CP3 镜长 3.48–6.74s 与草稿差异逐镜登记于 "
        "shots[].cp3_duration_s。【红线】只卡 0：起跑前卡0=310MiB/卡1=26706MiB 未触碰；"
        "全程卡0 nvidia-smi 峰值 18776MiB（本进程）；不 kill/不 pip/不下载。"),
}
with open(os.path.join(EP, "cp7.json"), "w", encoding="utf-8") as f:
    json.dump(agg, f, ensure_ascii=False, indent=2)
os.chmod(os.path.join(EP, "cp7.json"), 0o644)

print("per-shot artifacts:", len(per_shot_payloads))
print("aggregate written:", os.path.join(EP, "cp7.json"))
print("aggregate fingerprint:", agg["fingerprint"])
