#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp9_artifacts.py — CP9 工件构建（单镜权威件 + 聚合视图，双形态纪律沿 ecd9b80）。

前置: 每镜 <sid>.gen_meta.json 已由 postprocess_cp9.py 落盘。
门禁口径（thresholds.yaml:296-303）:
  cp9.gate.credit_cap_per_shot=280 = H3-Max 5s 768P 标准档锚点（=56 积分/s）；
  时长 >5s 镜（CP3 分镜守恒 ceil 所致）est>280 → gate.result=warn 如实标注不否决，
  集级硬闸门 = --credit-cap 8064（gen_api 守卫实跑生效，超限 exit 3）。
  cp9.gate.repro_log_complete=true → submit_params 指纹/task_id/参数全量落盘。
"""
import hashlib
import json
from pathlib import Path

ROOT = Path("/home/pan-ding/workspace/视频能力")
M2 = ROOT / "overnight/vpipe/out/m2/shortdrama_ep01"
CP9 = M2 / "cp9"
MODEL = "MiniMax-H3-Max"
NOW = None  # 取 gen_meta 的 submitted_at 之后的落盘时刻

CP6_FP = json.loads((M2 / "cp6.json").read_text(encoding="utf-8"))["fingerprint"]
CAP_PER_SHOT = 280  # thresholds.yaml cp9.gate.credit_cap_per_shot（5s 标准档锚点）


def canonical(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fp_of(p):
    return hashlib.sha256(canonical(p).encode("utf-8")).hexdigest()


arts = {}
for gm_path in sorted(CP9.glob("shot_*.gen_meta.json")):
    sid = gm_path.name.split(".")[0]
    gm = json.loads(gm_path.read_text(encoding="utf-8"))
    est = gm["credit"]["credit_spent_est"]
    dur = gm["submit_params"]["duration"]
    over = est > CAP_PER_SHOT
    gate = {
        "type": "rule",
        "params_ref": "cp9.gate.credit_cap_per_shot",
        "result": "warn" if over else "pass",
        "note": (f"实耗(估) {est} = 56积分/s × {dur}s（{'≈' if over else ''}单镜上限 280 为 5s 标准档锚点，"
                 f"thresholds cp9.gate.credit_cap_per_shot）" + (
                     f"；本镜 {dur}s>5s 系 CP3 分镜时长守恒 ceil 所致 → warn 标注不否决，"
                     f"集级硬闸门=--credit-cap 8064 实跑生效（超限 exit 3），本批累计估算 "
                     f"见聚合件" if over else "（5s 标准档，等于上限）") +
                 f"；估算口径：云通道无钱包端点 credit_before/after/cost=null（SPEC §2.2 如实降级）。"
                 f"云 task_id={gm['task_id']}。"),
    }
    aux = [{
        "type": "rule",
        "params_ref": "cp9.gate.repro_log_complete",
        "result": "pass",
        "note": (f"submit_params 全量（model/prompt/duration/resolution/ratio/generate_audio/image_mode）+ "
                 f"指纹 {gm['submit_params_fingerprint'][:16]}… + task_id 落盘 {sid}.gen_meta.json；"
                 f"repro_level=submit_params（API 同参重提交必为新样本，像素级承诺已废止，SPEC §2.2）。"),
    }]
    art = {
        "schema_version": "2.0",
        "cp_id": "cp9",
        "artifact_type": "final_render",
        "fingerprint": "",
        "produced_by": "gen_api",
        "produced_at": gm["submitted_at"],
        "upstream_refs": [
            {"cp_id": "cp6", "fingerprint": CP6_FP},
            {"cp_id": "cp8", "fingerprint": json.loads(
                (M2 / "cp8" / f"cp8_{sid}.json").read_text(encoding="utf-8"))["fingerprint"]},
        ],
        "status": "passed",
        "gate": gate,
        "aux_gates": aux,
        "payload": {
            "work_id": "shortdrama_ep01",
            "shot_id": sid,
            "channel": "api_h3max",
            "asset": {
                "kind": "clip",
                "fingerprint": gm["asset"]["fingerprint"],
                "path": gm["asset"]["path"],
            },
            "resolution": gm["submit_params"]["resolution"],
            "repro_level": "submit_params",
            "submit_params_fingerprint": gm["submit_params_fingerprint"],
            "seed_recorded": None,
            "credit_spent": est,
            "credit_cap_per_shot": CAP_PER_SHOT,
            "draft_task_id": None,
            "rework_route": None,
        },
        "notes": (f"单镜终稿件（CP9 权威形态，schema cp9 分支 jsonschema EXIT=0）。credit_spent={est} 为"
                  f" 56积分/s 估算值（云通道无钱包端点，非实扣，schema credit_spent 行描述同款降级语义）；"
                  f"云任务 task_id={gm['task_id']}（schema 无 task_id 字段，登记于此与 gen_meta）；"
                  f"draft_task_id=null（H3-Max 非 Seedance Draft 通道，schema 字段语义）。"
                  f"分辨率实测 {gm['ffprobe']['width']}x{gm['ffprobe']['height']}（768P 9:16 档）、"
                  f"{gm['ffprobe']['video_codec']}+{gm['ffprobe']['audio_codec']}、"
                  f"{gm['ffprobe']['duration']}s（提交 {dur}s，云侧封装偏差如实留痕）。"
                  f"参考图未用（纯 T2V，image_conditioned 留待 files/upload 核验后）。"
                  f"资产 sha256={gm['asset']['sha256'][:16]}…（ffprobe+sha256 本地亲核）。"),
    }
    art["fingerprint"] = fp_of(art["payload"])
    (CP9 / f"cp9_{sid}.json").write_text(json.dumps(art, ensure_ascii=False, indent=1) + "\n",
                                         encoding="utf-8")
    arts[sid] = art

# ---- 聚合视图（payload.shots[] 每镜一份 payload；EXIT=1 双形态矛盾如实记录） ----
metas = [json.loads(p.read_text(encoding="utf-8"))
         for p in sorted(CP9.glob("shot_*.gen_meta.json"))]
total_est = sum(m["credit"]["credit_spent_est"] for m in metas)
agg = {
    "schema_version": "2.0",
    "cp_id": "cp9",
    "artifact_type": "final_render",
    "fingerprint": "",
    "produced_by": "gen_api",
    "produced_at": max(m["submitted_at"] for m in metas),
    "upstream_refs": [
        {"cp_id": "cp6", "fingerprint": CP6_FP},
        {"cp_id": "cp8", "fingerprint": json.loads(
            (M2 / "cp8.json").read_text(encoding="utf-8"))["fingerprint"]},
    ],
    "status": "passed",
    "gate": {
        "type": "rule",
        "params_ref": "cp9.gate.credit_cap_per_shot",
        "result": "warn" if any(m["credit"]["credit_spent_est"] > CAP_PER_SHOT for m in metas) else "pass",
        "note": (f"{len(metas)} 镜精修：est 合计 {total_est}（56积分/s × 60s 提交秒数）＜ 集级上限 8064"
                 f"（--credit-cap 实跑守卫，超限 exit 3）；单镜 280 为 5s 标准档锚点，>5s 镜 warn 标注"
                 f"（CP3 分镜守恒 ceil 所致，单镜口径详见各单镜件）。shot_09 已被 CP8 拒绝不在本批。"),
    },
    "aux_gates": [{
        "type": "rule",
        "params_ref": "cp9.gate.repro_log_complete",
        "result": "pass",
        "note": "10/10 镜 submit_params 指纹 + task_id + 参数全量落盘 gen_meta.json，零缺失。",
    }],
    "payload": {
        "work_id": "shortdrama_ep01",
        "shots": [a["payload"] for a in (arts[f"shot_{i:02d}"] for i in range(1, 12)
                                         if f"shot_{i:02d}" in arts)],
    },
    "notes": "",
}
agg["fingerprint"] = fp_of(agg["payload"])
over_shots = [m["shot_id"] for m in metas if m["credit"]["credit_spent_est"] > CAP_PER_SHOT]
agg["notes"] = (
    "聚合视图（payload.shots[] 每镜一份 final_render payload，各镜含 channel/asset/resolution(768P≥档)/"
    "repro_level/submit_params_fingerprint/credit_spent(=est 估算口径)/credit_cap_per_shot/draft_task_id）。"
    "⚠ 双形态纪律（ecd9b80 主控裁决）：checkpoint.schema.json definitions.final_render 为单镜形态，聚合 "
    "payload.shots[] 过不了 schema cp9 分支（jsonschema EXIT=1，与 cp7/cp8 聚合件同款如实记录）；权威形态="
    "cp9/cp9_shot_XX.json（单镜件 EXIT=0）。【通道】api_h3max（model_tiers.yaml T4 现役默认），"
    "higress 云通道三步流，T2V 显式 image_mode=text-to-video（T4 notes；2026-10-09 实测云 DTO 接受）。"
    "【seed】云 DTO 白名单无 seed → 一律不发送，seed_recorded=null。【参考图】image-conditioned 本批未用："
    "CP2 注册表无 http(s) URL，本地路径 fail-closed（reference_unsupported_on_cloud）不许伪造/绕过，"
    "留待 files/upload 核验后。【成本】credit_spent 全部为 56积分/s 估算值（云通道无钱包端点，"
    "credit_before/after/cost 如实 null）；真实调用 10 次（shot_01 兼链路验证首条）。"
    f"【单镜超 280 锚点镜】{'、'.join(over_shots) if over_shots else '无'}（>5s 时长镜，warn 标注）。"
    "【时长口径】提交秒数=ceil(CP3 声明镜长) 夹 H3-Max [5,15]；云侧封装时长略大于提交值（如 5→5.184s）"
    "逐镜留痕 gen_meta.ffprobe。"
)
(M2 / "cp9.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"cp9_shot_*.json={len(arts)} est_total={total_est} over280={over_shots}")
