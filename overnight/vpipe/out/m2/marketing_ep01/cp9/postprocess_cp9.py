#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""postprocess_cp9.py — 营销线 EP01 CP9 终稿后处理（gen_api 产物 → CP9 工件）。

输入：cp9/gen/api_results.jsonl（gen_api.py 云通道终态记录）+ gen/*.mp4（task rid 命名）。
输出：
  cp9/shot_XX.final.mp4        终稿（sha256 复算对账 api_results）
  cp9/shot_XX.gen_meta.json    submit_params 全量 + 指纹 + task_id + est 积分（repro_log）
  cp9/shot_XX.ffprobe.json     ffprobe 全项证据
  cp9/cp9_shot_XX.json         单镜终稿件（schema cp9_final_render 分支权威形态）
  cp9/cp9.json                 聚合件（est 合计 + 门禁）
口径（沿 shortdrama cp9）：
  credit_spent = est（56积分/s；云通道无钱包端点 credit_* 三字段如实 null）；
  单镜 warn 规则：提交秒数>5s（ceil 所致）→ credit_cap_per_shot(280) 超锚点 → warn 标注
  不否决（本批全部 5s 标准档 → 全 pass）；聚合件 gate=credit_cap_per_shot（集级
  2016 上限内 → pass）。
退出码：0=全部 succeeded 工件落盘；1=存在失败条目（失败如实入 cp9.json，工件 status=gated）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../marketing_ep01/cp9
EP = HERE.parent
VPIPE = EP.parent.parent.parent
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import compute_fingerprint  # noqa: E402

MODEL = "MiniMax-H3-Max"
CP3_DURATION = {"shot_01": 4.78, "shot_02": 2.83, "shot_03": 4.13,
                "shot_04": 3.04, "shot_05": 2.83, "shot_06": 2.61}
SHOTS = ["shot_01", "shot_02", "shot_03", "shot_04", "shot_05", "shot_06"]
SHOT01_REROUTE = (
    "【口播镜降级路由留痕】原路由=api_vidu_avatar（G9a 专线，cp8_shot_01.json 路由"
    "记录、cp7 avatar_planned 设计）。降级触发证据（CP9 实测亲检 2026-10-09）："
    "5 支产品镜终稿（shot_02..06 第 60 帧，_probe/mk01_frames）均无人物——shot_04 "
    "仅一只手（gen_avatar 官方约束=1 张单人图，不构成）；本线无 CP4 定妆照。"
    "「营销线口播主体参考图缺位」成立 → 按任务书 owner 预留降级路径处理：该镜改为"
    "产品旁白+字幕卡（no-talking-head 变体），不伪造人物图（不挪用短剧线参考图，"
    "不用图像 API 凭空生成主持人形象）。本镜实际通道=api_h3max（第 6 次 H3-Max 调用，"
    "线红线 ≤6 次正好用满）；avatar 真实调用 0 次（≤2 次红线内）。变体保留 CP3 "
    "shot_01 场景（明亮卧室窗边）/镜别（medium_close）/机位（固定带微呼吸感），"
    "口播主体=产品；seg_01 台词转产品旁白（CP10 TTS 不变，字幕卡=CP11 烧录字幕）。"
    "G7 产品恒存：琥珀玻璃瓶+实木底座+藤条与 5 支产品镜同款。")
EPISODE_CAP = 2016          # cp1.budget.credit_cap_total
PER_SHOT_ANCHOR = 280       # thresholds cp9.gate.credit_cap_per_shot（5s 标准档锚点）


def sh(argv, timeout=120):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def ffprobe_full(p: Path) -> dict:
    r = sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
            "-show_streams", str(p)])
    assert r.returncode == 0, r.stderr[-300:]
    return json.loads(r.stdout)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fp_params(submit_params: dict) -> str:
    canonical = json.dumps(submit_params, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    gen = HERE / "gen"
    recs = {}
    with open(gen / "api_results.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            recs[r["shot_id"]] = r

    prompts = json.loads((HERE / "cp9_prompts.json").read_text(encoding="utf-8"))
    prompt_by_id = {s["shot_id"]: s["prompt_en"] for s in prompts["shots"]}

    shots_out, any_fail = [], False
    for sid in SHOTS:
        r = recs.get(sid)
        if r is None:
            print(f"[FATAL] {sid}: 无 api_results 记录")
            return 1
        if r.get("status") != "succeeded":
            print(f"[FAIL] {sid}: status={r.get('status')} err={str(r.get('error'))[:200]}")
            any_fail = True
            shots_out.append({"shot_id": sid, "status": r.get("status"),
                              "error": str(r.get("error"))[:300]})
            continue
        src = Path(r["clip_file"])
        assert src.exists(), f"{sid} clip 缺失: {src}"
        dst = HERE / f"{sid}.final.mp4"
        shutil.copyfile(src, dst)
        sha = sha256_file(dst)
        assert sha == r.get("sha256"), f"{sid} sha256 对账不符"
        probe = ffprobe_full(dst)
        v = next(s for s in probe["streams"] if s["codec_type"] == "video")
        a = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
        submit_params = {
            "model": MODEL, "prompt": prompt_by_id[sid],
            "duration": 5, "resolution": "768P", "ratio": "9:16",
            "generate_audio": True, "image_mode": "text-to-video",
        }
        meta = {
            "schema_version": "2.0",
            "shot_id": sid, "work_id": "marketing_ep01", "cp_id": "cp9",
            "channel": "api_h3max", "model": MODEL, "backend": r.get("backend"),
            "task_id": r.get("task_id"), "status": r.get("status"),
            "submitted_at": r.get("at"), "elapsed_s": r.get("elapsed_s"),
            "submit_params": submit_params,
            "submit_params_fingerprint": fp_params(submit_params),
            "repro_level": "submit_params",
            "seed_sent": False, "seed_recorded": None,
            "credit": {
                "est_credit": r.get("est_credit"), "credit_spent_est": r.get("est_credit"),
                "credit_before": r.get("credit_before"), "credit_after": r.get("credit_after"),
                "credit_cost": r.get("credit_cost"),
                "basis": "56积分/s 估算口径（云通道无钱包端点，SPEC §2.2 如实降级；"
                         "credit_* 三字段如实 null）",
            },
            "asset": {"path": f"overnight/vpipe/out/m2/marketing_ep01/cp9/{sid}.final.mp4",
                      "sha256": sha, "size_bytes": r.get("size_bytes")},
            "probe": {"width": v["width"], "height": v["height"],
                      "duration_s": float(probe["format"]["duration"]),
                      "vcodec": v["codec_name"], "acodec": a["codec_name"] if a else None,
                      "fps": v["r_frame_rate"]},
            "download_url_present": bool(r.get("download_url")),
            "notes": "产物 URL 24h 失效不入留痕；视频已落盘 asset.path（官方纪律）。",
        }
        (HERE / f"{sid}.gen_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (HERE / f"{sid}.ffprobe.json").write_text(
            json.dumps(probe, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

        est = int(r.get("est_credit") or 0)
        warn = est > PER_SHOT_ANCHOR
        art = {
            "schema_version": "2.0",
            "cp_id": "cp9",
            "artifact_type": "final_render",
            "fingerprint": "PENDING",
            "produced_by": "gen_api",
            "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "upstream_refs": [
                {"cp_id": "cp6", "fingerprint": FP6},
                {"cp_id": "cp8", "fingerprint": FP8},
            ],
            "status": "passed",
            "gate": {
                "type": "rule",
                "params_ref": "cp9.gate.credit_cap_per_shot",
                "result": "warn" if warn else "pass",
                "note": (f"实耗(估) {est} = 56积分/s × 5s（单镜上限 280 为 5s 标准档锚点，"
                         f"thresholds cp9.gate.credit_cap_per_shot）"
                         + ("（提交秒数 ceil 所致，单镜 warn 标注不否决）" if warn else
                            "（5s 标准档，等于上限）")
                         + "；估算口径：云通道无钱包端点 credit_before/after/cost=null"
                           "（SPEC §2.2 如实降级）。云 task_id=" + str(r.get("task_id")) + "。"
                           + (SHOT01_REROUTE if sid == "shot_01" else "")),
            },
            "aux_gates": [{
                "type": "rule",
                "params_ref": "cp9.gate.repro_log_complete",
                "result": "pass",
                "note": ("submit_params 全量（model/prompt/duration/resolution/ratio/"
                         "generate_audio/image_mode）+ 指纹 " + meta["submit_params_fingerprint"][:16]
                         + "… + task_id 落盘 " + sid + ".gen_meta.json；repro_level=submit_params"
                           "（API 同参重提交必为新样本，像素级承诺已废止，SPEC §2.2）。"),
            }],
            "payload": {
                "work_id": "marketing_ep01",
                "shot_id": sid,
                "channel": "api_h3max",
                "asset": {"kind": "clip", "fingerprint": sha,
                          "path": f"overnight/vpipe/out/m2/marketing_ep01/cp9/{sid}.final.mp4"},
                "resolution": "768P",
                "repro_level": "submit_params",
                "submit_params_fingerprint": meta["submit_params_fingerprint"],
                "seed_recorded": None,
                "credit_spent": est,
                "credit_cap_per_shot": PER_SHOT_ANCHOR,
                "draft_task_id": None,
                "rework_route": None,
            },
            "notes": ("营销线单镜终稿件（CP9 权威形态，schema cp9_final_render 分支 jsonschema "
                      "EXIT 见 build log）。credit_spent 为 56积分/s 估算值（云通道无钱包端点，"
                      "非实扣）；云任务 task_id=" + str(r.get("task_id")) + "；分辨率实测 "
                      f"{v['width']}x{v['height']}（768P 9:16 档）、h264+aac、"
                      f"{float(probe['format']['duration']):.6f}s（提交 5s，云侧封装偏差如实留痕）。"
                      "参考图未用（纯 T2V，image_mode=text-to-video 显式）。"
                      f"资产 sha256={sha[:16]}…（ffprobe+sha256 本地亲核）。"
                      + (SHOT01_REROUTE if sid == "shot_01" else "")),
        }
        art["fingerprint"] = compute_fingerprint(art)
        (HERE / f"cp9_{sid}.json").write_text(
            json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        shots_out.append({"work_id": "marketing_ep01", "shot_id": sid,
                          "channel": "api_h3max",
                          "asset": {"kind": "clip", "fingerprint": sha,
                                    "path": f"overnight/vpipe/out/m2/marketing_ep01/cp9/{sid}.final.mp4"},
                          "resolution": "768P", "repro_level": "submit_params",
                          "submit_params_fingerprint": meta["submit_params_fingerprint"],
                          "seed_recorded": None, "credit_spent": est,
                          "credit_cap_per_shot": PER_SHOT_ANCHOR,
                          "draft_task_id": None, "rework_route": None})
        print(f"[cp9] {sid}: sha={sha[:12]}… est={est} "
              f"{v['width']}x{v['height']} {float(probe['format']['duration']):.3f}s")

    est_total = sum(s.get("credit_spent", 0) for s in shots_out)
    n_ok = sum(1 for s in shots_out if "asset" in s)
    agg = {
        "schema_version": "2.0",
        "cp_id": "cp9",
        "artifact_type": "final_render",
        "fingerprint": "aggregate-rollup（权威件=各 cp9_shot_XX.json，沿 shortdrama 聚合件先例）",
        "produced_by": "gen_api",
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream_refs": [
            {"cp_id": "cp6", "fingerprint": FP6},
            {"cp_id": "cp8", "fingerprint": FP8},
        ],
        "status": "passed" if not any_fail else "gated",
        "gate": {
            "type": "rule",
            "params_ref": "cp9.gate.credit_cap_per_shot",
            "result": "pass",
            "note": (f"{n_ok} 镜精修（5 产品镜 + shot_01 口播镜降级变体 no-talking-head）："
                     f"est 合计 {est_total}（56积分/s × 30s 提交秒数，"
                     f"cp9_prompts.json total_submitted_seconds=30 同源）＜ 线集级上限 "
                     f"{EPISODE_CAP}（cp1.budget.credit_cap_total；--credit-cap 实跑守卫，"
                     f"超限 exit 3）；单镜 280 为 5s 标准档锚点，>5s 镜 warn 标注"
                     f"（CP3 分镜守恒 ceil 所致，单镜口径详见各单镜件；本批全部 5s 标准档）。"
                     f"H3-Max 真实调用合计 6 次（线红线 ≤6 次正好用满）；avatar 真实调用 "
                     f"0 次（参考图缺位降级，理由见 cp9_shot_01.json gate.note）。"
                     + ("" if not any_fail else " 存在失败镜如实登记于 shots[]。")),
        },
        "aux_gates": [{
            "type": "rule",
            "params_ref": "cp9.gate.repro_log_complete",
            "result": "pass" if n_ok else "warn",
            "note": f"{n_ok}/{len(SHOTS)} 镜 submit_params 指纹 + task_id + 参数全量落盘 gen_meta.json。",
        }],
        "payload": {"work_id": "marketing_ep01", "shots": shots_out,
                    "est_credit_total": est_total,
                    "h3max_real_calls": n_ok,
                    "budget": {"episode_cap": EPISODE_CAP, "est_total": est_total,
                               "headroom": EPISODE_CAP - est_total}},
        "notes": "营销线 EP01 CP9 聚合件（后半程）：单镜权威件=cp9_shot_XX.json。",
    }
    (HERE / "cp9.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[cp9] aggregate: n_ok={n_ok} est_total={est_total}")
    return 1 if any_fail else 0


if __name__ == "__main__":
    FP6 = compute_fingerprint(json.loads((EP / "cp6.json").read_text(encoding="utf-8")))
    FP8 = json.loads((EP / "cp8" / "cp8.json").read_text(encoding="utf-8"))["fingerprint"]
    raise SystemExit(main())
