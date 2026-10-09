#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""postprocess_shot03_rework_r2.py — CP12 二轮回炉：shot_03 重渲产物 → CP9 工件更新（2026-10-09）。

沿 postprocess_shot05_rework.py 口径，只动 shot_03 一镜；v1 工件+终稿先存档
archive_rework_r1/（本目录，等价于 shot_05 轮的「被替换版存档」语义）。
差异（回炉登记）：
  * gate.note / notes 记二轮回炉缘由（CP12 人工队列 2 条指向 shot_03，时间窗
    9.083-11.250s = CP3 shot_03 的 7.542-11.625s 区间：J3 frame_freeze P=0.7500
    灰区 + J6v2 zero_diff_run conf=0.617（run_diff_med=0.5534 近零帧差）——微距
    特写+static 机位运动过小；J1 identity_drift conf=0.60——瓶身标签/瓶型与
    shot_05 回炉后终稿不一致）；
  * prompt 两处修订：① 可见微运动（删 rigid unchanged shape 零运动指令，改
    subtle breathing drift + 藤条轻摇/光影漂移）；② 瓶型统一（wide-shoulder
    amber glass bottle with a clean blank craft-paper label and a wooden neck
    ring，与 shot_05 回炉后终稿一致）；场景/景别/产品定义其余不变；
  * rework_route 保持 null：CP9 层 prompt 定向修订重渲，未走 cp3/cp4/cp5 回退
    路由（沿 shot_05 轮口径）；
  * cp9.json 聚合：现役 est 合计仍 1680（6 镜各 280），回炉沉没累计
    280+280=560（行#80 shot_05 + 行#81 shot_03），线累计 2240 ＞ 原 cap 2016
    （超 224：owner 300 元口径授权内特批，如实登记不伪造 cap 合规）；
    h3max 真实调用累计 8 次（线红线 6 次 + shot_05 回炉授权 1 次 + 本轮回炉
    授权 1 次）。
退出码：0=工件落盘且 sha256 对账一致；1=对账失败。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../marketing_ep01/cp9/rework_r2
EP = HERE.parent                                 # .../marketing_ep01/cp9
VPIPE = EP.parent.parent.parent.parent          # .../overnight/vpipe
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import compute_fingerprint  # noqa: E402

MODEL = "MiniMax-H3-Max"
EPISODE_CAP = 2016
PER_SHOT_ANCHOR = 280
ARCHIVE = HERE / "archive_rework_r1"
LEDGER_ROW = 81
TASK_ID = "l7xOQ0PXLaDX"
V1_SHA = "1a38758741ab59c0f3f6541cde6023ad6079c4059fb27fc94acb0450515356b9"

NEW_PROMPT = ("Extreme close-up, static camera with a subtle breathing drift: natural "
              "rattan reeds standing in the neck of a wide-shoulder amber glass bottle "
              "with a clean blank craft-paper label and a wooden neck ring, dark soft "
              "bedroom background, the reed diffuser reeds sway gently as if touched by "
              "a soft breeze, light reflections drift slowly across the glass shoulder. "
              "The reeds are dry natural rattan with visible fibrous grain; the amber "
              "glass shoulder carries a warm honey-gold rim light that slowly travels "
              "along the curve; the blank craft-paper label stays clean and empty, no "
              "text, no letters, no typography; deep cedar green-gold tones in a dark "
              "warm bedroom night atmosphere. Premium photorealistic product commercial "
              "look, macro-level glass clarity, rich micro-contrast, shallow depth of "
              "field, vertical 9:16 portrait framing, no on-screen text, no readable "
              "label on the bottle, no watermark, no subtitles.")
REWORK_NOTE = (
    "【CP12 二轮回炉重渲 2026-10-09】缘由=cp12.json human_review.queue 2 条指向本镜"
    "（span 9.083-11.250s = CP3 shot_03 的 7.542-11.625s 区间）：J3 omnijev "
    "frame_freeze P=0.7500 灰区（[0.71,0.90)，未达 auto_reject 0.90）+ J6v2 "
    "qc_detectors_v2 frame_freeze conf=0.617（kind=zero_diff_run，run_diff_med=0.5534 "
    "近零帧差，run_pairs=52，同 span 互证）；另有 J1 glm8 identity_drift conf=0.60"
    "（瓶身标签/瓶型与 shot_05 回炉后终稿不一致）。根因=v1 prompt 两缺陷：① "
    "「static camera」+「the bottle and reeds keep a perfectly rigid unchanged shape」"
    "为零运动指令，微距特写+static 机位致画面运动过小；② 「an amber glass diffuser "
    "bottle」无瓶型约束 → 生成侧凭空玻璃罗纹颈。修订：① 删 rigid unchanged shape "
    "条款，改「static camera with a subtle breathing drift」（shot_01/shot_05 已验证"
    "微运动配方）+ 增「the reed diffuser reeds sway gently as if touched by a soft "
    "breeze, light reflections drift slowly across the glass shoulder」（藤条轻摇+"
    "光影漂移，幅度小而持续可测，替换 v1 光斑滑移短语）；② 改「a wide-shoulder "
    "amber glass bottle with a clean blank craft-paper label and a wooden neck ring」"
    "与 shot_05 回炉后终稿一致，并增「no text, no letters, no typography」空白标强化"
    "（G2 纪律）。场景（暗调卧室夜景）/景别（extreme close-up）/产品定义（天然藤条+"
    "琥珀玻璃）/色彩（雪松绿金）与 v1 一致。H3-Max 真实调用 1 次（本轮回炉任务书"
    f"授权 ≤1 次），task_id={TASK_ID}，est 280 积分（ledger 行#{LEDGER_ROW}）；"
    "线累计 1960+280=2240 ＞ 原 cap 2016（超 224=owner 300 元口径授权内特批，"
    "如实登记不伪造合规）；v1 终稿+工件存档 archive_rework_r1/。")
SELF_CHECK_NOTE = (
    "回炉亲检（代理看帧+实测 2026-10-09，不代判）：微运动实测同口径 160x90 灰度帧差"
    "中位 v1 0.5929 → v2 0.6267（p10 0.1780→0.4001、min 0.0714→0.2490，近零帧差段"
    "显著收敛，中位增幅有限如实登记）；瓶型宽肩琥珀瓶+瓶颈牛皮纸色空白环带无任何文字"
    "（像素级放大复核）；木色颈圈未以木纹质感呈现（瓶颈带为纸色，与 shot_05 终稿的"
    "木圈+浅色瓶身标仍有可见差异，偏差方向较 v1 玻璃罗纹颈收敛，如实登记交判官复判）。"
    "最终判定以 CP12 三判官对新 master 重跑为准，不以亲检代判。")


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


def ffprobe_full(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(p)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-300:]
    return json.loads(r.stdout)


def main() -> int:
    rec = None
    with open(HERE / "gen" / "api_results.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("shot_id") == "shot_03" and r.get("terminal"):
                rec = r
    assert rec and rec.get("status") == "succeeded", f"rework 记录异常: {rec}"
    src = Path(rec["clip_file"])
    assert src.exists(), f"clip 缺失: {src}"

    # ---- v1 存档对账（终稿 + 三工件；本脚本运行前已拷贝，此处只核 sha）----
    for name in ("shot_03.final.mp4", "shot_03.gen_meta.json",
                 "shot_03.ffprobe.json", "cp9_shot_03.json"):
        assert (ARCHIVE / name).exists(), f"v1 存档缺 {name}"
    old_sha = sha256_file(ARCHIVE / "shot_03.final.mp4")
    assert old_sha == V1_SHA, f"v1 存档 sha 不符: {old_sha}"

    # ---- 新终稿落位 + 对账 ----
    dst = EP / "shot_03.final.mp4"
    shutil.copyfile(src, dst)
    sha = sha256_file(dst)
    assert sha == rec["sha256"], f"sha256 对账不符: {sha} != {rec['sha256']}"
    probe = ffprobe_full(dst)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = next(s for s in probe["streams"] if s["codec_type"] == "audio")

    # ---- gen_meta（repro_log，口径同 postprocess_cp9.py / shot_05 轮）----
    submit_params = {
        "model": MODEL, "prompt": NEW_PROMPT,
        "duration": 5, "resolution": "768P", "ratio": "9:16",
        "generate_audio": True, "image_mode": "text-to-video",
    }
    meta = {
        "schema_version": "2.0",
        "shot_id": "shot_03", "work_id": "marketing_ep01", "cp_id": "cp9",
        "channel": "api_h3max", "model": MODEL, "backend": rec.get("backend"),
        "task_id": rec.get("task_id"), "status": rec.get("status"),
        "submitted_at": rec.get("at"), "elapsed_s": rec.get("elapsed_s"),
        "submit_params": submit_params,
        "submit_params_fingerprint": fp_params(submit_params),
        "repro_level": "submit_params",
        "seed_sent": False, "seed_recorded": None,
        "credit": {
            "est_credit": rec.get("est_credit"), "credit_spent_est": rec.get("est_credit"),
            "credit_before": rec.get("credit_before"), "credit_after": rec.get("credit_after"),
            "credit_cost": rec.get("credit_cost"),
            "basis": "56积分/s 估算口径（云通道无钱包端点，SPEC §2.2 如实降级；"
                     "credit_* 三字段如实 null）",
        },
        "asset": {"path": "overnight/vpipe/out/m2/marketing_ep01/cp9/shot_03.final.mp4",
                  "sha256": sha, "size_bytes": rec.get("size_bytes")},
        "probe": {"width": v["width"], "height": v["height"],
                  "duration_s": float(probe["format"]["duration"]),
                  "vcodec": v["codec_name"], "acodec": a["codec_name"] if a else None,
                  "fps": v["r_frame_rate"]},
        "download_url_present": bool(rec.get("download_url")),
        "notes": "产物 URL 24h 失效不入留痕；视频已落盘 asset.path（官方纪律）。"
                 f"二轮回炉重渲（v1 task_id=l7xJ2mybd23b 存档 archive_rework_r1/；"
                 f"本轮 task_id={TASK_ID}）。",
    }
    (EP / "shot_03.gen_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (EP / "shot_03.ffprobe.json").write_text(
        json.dumps(probe, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- cp9_shot_03.json（权威单镜件）----
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    est = int(rec.get("est_credit") or 0)
    art = {
        "schema_version": "2.0",
        "cp_id": "cp9",
        "artifact_type": "final_render",
        "fingerprint": "PENDING",
        "produced_by": "gen_api",
        "produced_at": now,
        "upstream_refs": [
            {"cp_id": "cp6",
             "fingerprint": compute_fingerprint(json.loads((EP.parent / "cp6.json").read_text(encoding="utf-8")))},
            {"cp_id": "cp8",
             "fingerprint": json.loads((EP.parent / "cp8" / "cp8.json").read_text(encoding="utf-8"))["fingerprint"]},
        ],
        "status": "passed",
        "gate": {
            "type": "rule",
            "params_ref": "cp9.gate.credit_cap_per_shot",
            "result": "pass",
            "note": ("实耗(估) 280 = 56积分/s × 5s（单镜上限 280 为 5s 标准档锚点，"
                     "thresholds cp9.gate.credit_cap_per_shot）（5s 标准档，等于上限）；"
                     "估算口径：云通道无钱包端点 credit_before/after/cost=null"
                     f"（SPEC §2.2 如实降级）。云 task_id={TASK_ID}。" + REWORK_NOTE),
        },
        "aux_gates": [{
            "type": "rule",
            "params_ref": "cp9.gate.repro_log_complete",
            "result": "pass",
            "note": ("submit_params 全量（model/prompt/duration/resolution/ratio/"
                     "generate_audio/image_mode）+ 指纹 " + meta["submit_params_fingerprint"][:16]
                     + "… + task_id 落盘 shot_03.gen_meta.json；repro_level=submit_params"
                       "（API 同参重提交必为新样本，像素级承诺已废止，SPEC §2.2）。"),
        }],
        "payload": {
            "work_id": "marketing_ep01",
            "shot_id": "shot_03",
            "channel": "api_h3max",
            "asset": {"kind": "clip",
                      "fingerprint": sha,
                      "path": "overnight/vpipe/out/m2/marketing_ep01/cp9/shot_03.final.mp4"},
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
                  f"非实扣）；云任务 task_id={TASK_ID}；分辨率实测 "
                  f"{v['width']}x{v['height']}（768P 9:16 档）、h264+aac、"
                  f"{float(probe['format']['duration']):.6f}s（提交 5s，云侧封装偏差如实留痕）。"
                  "参考图未用（纯 T2V，image_mode=text-to-video 显式）。"
                  f"资产 sha256={sha[:16]}…（ffprobe+sha256 本地亲核）。"
                  "rework_route=null：本次为 CP9 层 prompt 定向修订重渲，未走 cp3/cp4/cp5 "
                  "回退路由（checkpoint.schema rework_route enum 无 cp9 值，如实留 null，"
                  "回炉缘由与修订内容见 gate.note）。" + SELF_CHECK_NOTE),
    }
    art["fingerprint"] = compute_fingerprint(art)
    (EP / "cp9_shot_03.json").write_text(
        json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- cp9_prompts.json：shot_03 prompt_en 更新 + policy 回炉注记 ----
    prompts_path = EP / "cp9_prompts.json"
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    for s in prompts["shots"]:
        if s["shot_id"] == "shot_03":
            s["prompt_en"] = NEW_PROMPT
            s["prompt_chars"] = len(NEW_PROMPT)
            s["base_ref"] = ("cp7/cp7_prompts.json shots[].prompt_en（构图/运动/节奏基底）；"
                             "2026-10-09 CP12 二轮回炉修订（可见微运动+瓶型统一，差异见 "
                             "cp9_shot_03.json gate.note；v1 prompt 存 "
                             "rework_r2/archive_rework_r1/cp9_shot_03 与本表 git 历史）")
    prompts["policy"]["rework_shot03"] = (
        "CP12 二轮回炉（2026-10-09）：shot_03 定向修订重渲 1 次（H3-Max，"
        f"task_id={TASK_ID}，est 280，ledger 行#{LEDGER_ROW}；线 est 合计 "
        "1960+280=2240 ＞ 原 cap 2016，超 224 为 owner 300 元口径授权内特批、"
        "如实登记不伪造合规；真实调用累计 8 次=线红线 6 次+shot_05 回炉授权 1 次"
        "+本轮回炉授权 1 次）。两处差异：① 可见微运动——删「rigid unchanged shape」"
        "零运动指令，改 subtle breathing drift + 藤条轻摇/光影漂移（shot_01/shot_05 "
        "已验证配方）；② 瓶型统一——wide-shoulder amber glass bottle with a clean "
        "blank craft-paper label and a wooden neck ring（与 shot_05 回炉后终稿一致）"
        "+ 空白标 no text/letters/typography 强化；其余与 v1 一致。")
    prompts_path.write_text(json.dumps(prompts, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")

    # ---- cp9/shots/shot_03.json（现役契约同步）----
    contract_path = EP / "shots" / "shot_03.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["prompt"] = NEW_PROMPT
    contract["notes"] = (
        "CP9 精修（T4 api_h3max，营销线后半程）。CP3 声明镜长 4.13s → ceil=5s"
        "（H3-Max 整数秒区间 [5,15]，不截动作拍）。2026-10-09 CP12 二轮回炉修订："
        "① 删「the bottle and reeds keep a perfectly rigid unchanged shape」零运动"
        "指令，static camera → static camera with a subtle breathing drift（shot_01/"
        "shot_05 已验证微运动配方）+ 增藤条轻摇/光影漂移条款；② 瓶型统一为 "
        "wide-shoulder amber glass bottle with a clean blank craft-paper label and "
        "a wooden neck ring（与 shot_05 回炉后终稿一致）+ 空白标强化。场景/景别/"
        "产品定义/色彩与 v1 一致；修订缘由=cp12 队列 2 条指本镜（frame_freeze×2 "
        "互证 + J1 identity_drift），详见 cp9_shot_03.json gate.note。"
        "G2 纪律：品牌名/价格不进生成侧。image_mode=云通道显式 text-to-video。")
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")

    # ---- cp9.json 聚合更新（只动 shot_03 条目与合计/预算字段）----
    agg_path = EP / "cp9.json"
    agg = json.loads(agg_path.read_text(encoding="utf-8"))
    old_budget = dict(agg["payload"]["budget"])
    for s in agg["payload"]["shots"]:
        if s["shot_id"] == "shot_03":
            s["asset"]["fingerprint"] = sha
            s["submit_params_fingerprint"] = meta["submit_params_fingerprint"]
            s["credit_spent"] = est
    n_ok = sum(1 for s in agg["payload"]["shots"] if "asset" in s)
    new_total = sum(s.get("credit_spent", 0) for s in agg["payload"]["shots"])
    sunk = old_budget.get("rework_sunk_credit", 0) + est
    cumulative = new_total + sunk
    agg["payload"]["est_credit_total"] = new_total
    agg["payload"]["h3max_real_calls"] = n_ok + 2          # 6 v1 + 2 回炉
    agg["payload"]["budget"] = {
        "episode_cap": EPISODE_CAP, "est_total": new_total,
        "rework_sunk_credit": sunk, "cumulative_spent": cumulative,
        "headroom": EPISODE_CAP - cumulative,
        "note": (f"现役 6 镜 est 合计 {new_total}（30s 提交秒数）+ CP12 回炉沉没 "
                 f"{sunk}（shot_05 重渲 280=ledger 行#80 + shot_03 二轮回炉 280=行#81）"
                 f"= 线累计 {cumulative} ＞ 原 cap {EPISODE_CAP}"
                 f"（cp1.budget.credit_cap_total），超 {cumulative - EPISODE_CAP}："
                 "owner 300 元口径授权内特批，如实登记不伪造 cap 合规"),
    }
    agg["produced_at"] = now
    agg["gate"]["note"] = (
        f"{n_ok} 镜精修（5 产品镜 + shot_01 口播镜降级变体 no-talking-head）："
        f"现役 est 合计 {new_total}（56积分/s × 30s 提交秒数）；回炉沉没累计 {sunk}"
        f"（shot_05 2026-10-09 行#80 + shot_03 二轮回炉同日行#81），线累计 {cumulative} "
        f"＞ 线集级原上限 {EPISODE_CAP}（cp1.budget.credit_cap_total），超 "
        f"{cumulative - EPISODE_CAP} 为 owner 300 元口径授权内特批（如实登记，"
        f"不伪造 cap 合规）；单镜 280 为 5s 标准档锚点（全部 5s 标准档）。"
        f"H3-Max 真实调用累计 {n_ok + 2} 次（v1 线红线 6 次用满 + shot_05 回炉授权 "
        f"1 次 + shot_03 二轮回炉授权 1 次，均 2026-10-09）；avatar 真实调用 0 次"
        f"（参考图缺位降级，理由见 cp9_shot_01.json gate.note）。"
        f"【回炉】shot_05 于 2026-10-09 一轮定向修订重渲（CP12 队列 3 条清偿动作，"
        f"见 cp9_shot_05.json gate.note；v1 存档 rework/archive_rework_r1/）；"
        f"shot_03 同日二轮定向修订重渲（CP12 残留队列 2 条清偿动作：J3 灰区 "
        f"frame_freeze + J6v2 zero_diff_run 同指 9.083-11.250s，另 J1 identity_drift "
        f"瓶型跨镜不一致；缘由与差异见 cp9_shot_03.json gate.note；v1 存档 "
        f"rework_r2/archive_rework_r1/）。")
    agg["notes"] = ("营销线 EP01 CP9 聚合件（后半程）：单镜权威件=cp9_shot_XX.json。"
                    "2026-10-09 CP12 回炉更新（两轮）：shot_05（一轮）与 shot_03（二轮）"
                    "条目均已替换为重渲版（新 sha256/参数指纹）；现役 est 合计 1680、"
                    "线累计 2240（含回炉沉没 560，超原 cap 224 已如实登记）。")
    agg_path.write_text(json.dumps(agg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"[rework_r2] shot_03: sha={sha[:12]}… est={est} {v['width']}x{v['height']} "
          f"{float(probe['format']['duration']):.3f}s task={rec.get('task_id')}")
    print(f"[rework_r2] budget: est_total {new_total} + sunk {sunk} = cumulative "
          f"{cumulative} (cap {EPISODE_CAP}, over {cumulative - EPISODE_CAP})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
