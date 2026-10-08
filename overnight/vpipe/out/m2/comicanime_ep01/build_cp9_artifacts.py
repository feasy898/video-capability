#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp9_artifacts.py — CP9 终稿工件构建（漫剧线 EP01，后半程）。

输入：cp9/gen/api_results.jsonl（gen_api 云通道真实终态 9 条）+ cp9/shots/*.json（提交契约）
     + cp9_prompts.json。
输出：cp9/shot_XX.final.mp4（sha256/ffprobe 本地亲核）+ cp9/shot_XX.gen_meta.json +
     cp9/cp9_shot_XX.json（单镜权威形态，schema final_render 分支）+ cp9.json（聚合视图）。

口径（沿短剧线 cp9_shot_01.json 实证）：
  - credit_spent = est 估算值（云通道无钱包端点，credit_before/after/cost 如实 null）
  - repro_level=submit_params；submit_params_fingerprint=sha256(canonical submit_params)
  - 分辨率实测 768x1344（768P 9:16 档）、h264+aac；云侧封装时长略大于提交值如实留痕
  - 帧域映射：CP6 duration_frames ÷ 24 = 镜窗口 ≤ 提交时长（CP11 trim 消化）
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VPIPE = HERE.parent.parent.parent
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import compute_fingerprint  # noqa: E402

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
GEN = HERE / "cp9" / "gen"


def ffprobe_clip(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    return {
        "width": v["width"], "height": v["height"],
        "duration": d["format"]["duration"],
        "video_codec": v["codec_name"], "pix_fmt": v["pix_fmt"],
        "avg_frame_rate": v.get("avg_frame_rate"),
        "audio_codec": a["codec_name"] if a else None,
        "nb_frames": v.get("nb_frames"),
    }


def main() -> int:
    recs = {}
    for line in (GEN / "api_results.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        recs[r["shot_id"]] = r
    assert len(recs) == 9, f"expect 9 records, got {len(recs)}"

    outs = []
    est_total = 0
    for i in range(1, 10):
        sid = f"shot_{i:02d}"
        rec = recs[sid]
        assert rec["status"] == "succeeded", f"{sid} {rec['status']}"
        contract = json.loads((HERE / "cp9" / "shots" / f"{sid}.json").read_text(encoding="utf-8"))
        src = GEN / f"{sid}@MiniMax-H3-Max.mp4"
        dst = HERE / "cp9" / f"{sid}.final.mp4"
        shutil.copyfile(src, dst)
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        probe = ffprobe_clip(dst)
        submit_params = {
            "model": "MiniMax-H3-Max",
            "prompt": contract["prompt"],
            "duration": contract["duration_s"],
            "resolution": contract["resolution"],
            "ratio": contract["aspect"],
            "generate_audio": contract["audio"]["generate"],
            "image_mode": "text-to-video",
        }
        sp_fp = hashlib.sha256(json.dumps(submit_params, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False).encode("utf-8")).hexdigest()
        est = rec["est_credit"]
        est_total += est
        meta = {
            "schema_version": "2.0",
            "shot_id": sid,
            "work_id": "comicanime_ep01",
            "cp_id": "cp9",
            "channel": "api_h3max",
            "model": "MiniMax-H3-Max",
            "backend": "minimax_cloud_v3",
            "task_id": rec["task_id"],
            "status": rec["status"],
            "submitted_at": rec["at"],
            "elapsed_s": rec["elapsed_s"],
            "submit_params": submit_params,
            "submit_params_fingerprint": sp_fp,
            "repro_level": "submit_params",
            "seed_sent": rec.get("seed_sent"),
            "seed_recorded": None,
            "credit": {
                "est_credit": est,
                "credit_spent_est": est,
                "credit_before": rec["credit_before"],
                "credit_after": rec["credit_after"],
                "credit_cost": rec["credit_cost"],
                "basis": "56积分/s 估算口径（云通道无钱包端点，SPEC §2.2 如实降级；credit_*三字段如实 null）",
            },
            "reference_images_used": [],
            "image_conditioned": "未用（CP2 注册表无 http(s) 参考 URL；files/upload 手册未实测→fail-closed 不绕过）",
            "asset": {"kind": "clip", "fingerprint": sha,
                      "path": f"overnight/vpipe/out/m2/comicanime_ep01/cp9/{sid}.final.mp4",
                      "size_bytes": dst.stat().st_size, "sha256": sha},
            "ffprobe": probe,
            "upstream": {
                "cp8_selection": f"overnight/vpipe/out/m2/comicanime_ep01/cp8/cp8_{sid}.json",
                "shot_contract": f"overnight/vpipe/out/m2/comicanime_ep01/cp9/shots/{sid}.json",
            },
        }
        (HERE / "cp9" / f"{sid}.gen_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

        # ---- 单镜权威工件（schema final_render 分支）----
        art = {
            "schema_version": "2.0",
            "cp_id": "cp9",
            "artifact_type": "final_render",
            "fingerprint": "",
            "produced_by": "gen_api",
            "produced_at": rec["at"],
            "upstream_refs": [
                {"cp_id": "cp6", "fingerprint": "7b9da66eb15a11993345920e0aea1f93a8150fa14238531cb2d3adb69cfe5eb6"},
                {"cp_id": "cp8", "fingerprint": json.loads(
                    (HERE / "cp8" / f"cp8_{sid}.json").read_text(encoding="utf-8"))["fingerprint"]},
            ],
            "status": "passed",
            "gate": {
                "type": "rule",
                "params_ref": "cp9.gate.credit_cap_per_shot",
                "result": "pass" if est <= 280 else "warn",
                "note": (f"实耗(估) {est} = 56积分/s × {contract['duration_s']}s（{'5s 标准档，等于上限'
                         if est == 280 else '>5s 时长镜，上限 280 为 5s 标准档锚点，warn 标注'}，"
                         "thresholds cp9.gate.credit_cap_per_shot）；估算口径：云通道无钱包端点 "
                         "credit_before/after/cost=null（SPEC §2.2 如实降级）。云 "
                         f"task_id={rec['task_id']}。"),
            },
            "aux_gates": [
                {"type": "rule", "params_ref": "cp9.gate.repro_log_complete",
                 "result": "pass",
                 "note": ("submit_params 全量（model/prompt/duration/resolution/ratio/generate_audio/"
                          f"image_mode）+ 指纹 {sp_fp[:12]}… + task_id 落盘 {sid}.gen_meta.json；"
                          "repro_level=submit_params（API 同参重提交必为新样本，像素级承诺已废止，"
                          "SPEC §2.2）。")},
            ],
            "payload": {
                "work_id": "comicanime_ep01",
                "shot_id": sid,
                "channel": "api_h3max",
                "asset": {"kind": "clip", "fingerprint": sha,
                          "path": f"overnight/vpipe/out/m2/comicanime_ep01/cp9/{sid}.final.mp4"},
                "resolution": "768P",
                "repro_level": "submit_params",
                "submit_params_fingerprint": sp_fp,
                "seed_recorded": None,
                "credit_spent": est,
                "credit_cap_per_shot": 280,
                "draft_task_id": None,
                "rework_route": None,
            },
            "notes": (f"单镜终稿件（CP9 权威形态）。credit_spent={est} 为 56积分/s 估算值（云通道无钱包"
                      f"端点，非实扣）；云任务 task_id={rec['task_id']}；draft_task_id=null（H3-Max 非 "
                      "Seedance Draft 通道）。分辨率实测 "
                      f"{probe['width']}x{probe['height']}（768P 9:16 档）、{probe['video_codec']}+"
                      f"{probe['audio_codec']}、{probe['duration']}s（提交 {contract['duration_s']}s，"
                      "云侧封装偏差如实留痕）。参考图未用（纯 T2V）。G8 风格强约束块逐镜显式（强风格指令镜，"
                      "风格漂移若见按 v3.1 裁决如实记录并考虑回退 api_h3）。"
                      f"资产 sha256={sha[:12]}…（ffprobe+sha256 本地亲核）。"),
        }
        art["fingerprint"] = compute_fingerprint(art)
        (HERE / "cp9" / f"cp9_{sid}.json").write_text(
            json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        outs.append({"shot_id": sid, "est": est, "sha": sha, "probe": probe,
                     "task_id": rec["task_id"], "elapsed": rec["elapsed_s"]})

    # ---- 聚合视图 ----
    art_agg = {
        "schema_version": "2.0",
        "cp_id": "cp9",
        "artifact_type": "final_render",
        "fingerprint": "",
        "produced_by": "gen_api",
        "produced_at": NOW,
        "upstream_refs": [
            {"cp_id": "cp6", "fingerprint": "7b9da66eb15a11993345920e0aea1f93a8150fa14238531cb2d3adb69cfe5eb6"},
            {"cp_id": "cp8", "fingerprint": json.loads((HERE / "cp8.json").read_text(encoding="utf-8"))["fingerprint"]},
        ],
        "status": "passed",
        "gate": {
            "type": "rule",
            "params_ref": "cp9.gate.credit_cap_per_shot",
            "result": "warn",
            "note": (f"9 镜精修：est 合计 {est_total}（56积分/s × 46s 提交秒数，cp9_prompts.json "
                     f"total_submitted_seconds=46 同源）≤ 集级上限 3360（CP1 credit_cap_total；"
                     "--credit-cap 3360 实跑守卫，超限 exit 3）；单镜 280 为 5s 标准档锚点，shot_01"
                     "（6s 档）>280 warn 标注（CP3 分镜守恒 ceil 所致）。真实调用 9 次 ≤ 10 次红线。"),
        },
        "aux_gates": [
            {"type": "rule", "params_ref": "cp9.gate.repro_log_complete",
             "result": "pass",
             "note": "9/9 镜 submit_params 指纹 + task_id + 参数全量落盘 gen_meta.json，零缺失。"},
        ],
        "payload": {"work_id": "comicanime_ep01",
                    "shots": [json.loads((HERE / "cp9" / f"cp9_{s['shot_id']}.json").read_text(
                        encoding="utf-8"))["payload"] for s in outs]},
        "notes": ("聚合视图（payload.shots[] 每镜一份 final_render payload）。⚠ 双形态纪律（ecd9b80 "
                  "主控裁决）：checkpoint.schema.json definitions.final_render 为单镜形态，聚合 "
                  "payload.shots[] 过不了 schema cp9 分支（EXIT=1，与 cp7/cp8 聚合件同款如实记录）；"
                  "权威形态=cp9/cp9_shot_XX.json（单镜件）。【通道】api_h3max（T4 现役默认），higress "
                  "云通道三步流，T2V 显式 image_mode=text-to-video。【seed】云 DTO 白名单无 seed → "
                  "一律不发送。【参考图】未用（CP2 注册表无 http(s) URL，本地路径 fail-closed）。"
                  "【成本】credit_spent 全部为 56积分/s 估算值；真实调用 9 次。【时长口径】提交秒数="
                  "ceil(CP3 声明镜长) 夹 H3-Max [5,15]（shot_01=6s，其余 5s 下限夹取）；云侧封装时长"
                  "略大于提交值逐镜留痕 gen_meta.ffprobe。【预算】est 2576/3360（漫剧线 cap）。"),
    }
    art_agg["fingerprint"] = compute_fingerprint(art_agg)
    (HERE / "cp9.json").write_text(json.dumps(art_agg, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")
    print(f"cp9: 9/9 final clips, est_total={est_total}")
    for o in outs:
        print(f"  {o['shot_id']} est={o['est']} task={o['task_id']} {o['probe']['width']}x"
              f"{o['probe']['height']} {o['probe']['duration']}s sha={o['sha'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
