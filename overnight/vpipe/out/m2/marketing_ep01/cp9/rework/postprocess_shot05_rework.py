#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""postprocess_shot05_rework.py — CP12 回炉：shot_05 重渲产物 → CP9 工件更新（2026-10-09）。

沿 postprocess_cp9.py 口径，只动 shot_05 一镜；v1 工件+终稿先存档 archive_rework_r1/。
差异（回炉登记）：
  * gate.note / notes 记回炉缘由（CP12 队列 3 条：J1 identity_drift 0.62 + J3
    frame_freeze 0.711 灰区 + J6v2 zero_diff_run 0.758，均指 shot_05 14.625-17.375s）；
  * prompt 两处修订：标签 clean blank craft-paper label（no text/letters/typography，
    补 no readable label 对齐他镜 G2 条款）+ 微运动 subtle breathing drift（shot_01
    已验证配方）；其余场景/景别/造型/色彩与 v1 prompt 一致；
  * rework_route 保持 null：本次为 CP9 层 prompt 定向修订重渲，未走 cp3/cp4/cp5
    回退路由（checkpoint.schema enum 无 cp9 值，如实留 null 并以 gate.note 记录）；
  * cp9.json 聚合 est 合计 1680+280=1960 ≤ 2016；h3max 真实调用累计 7 次
    （线原红线 6 次用满后，回炉任务书另授权 ≤1 次，本次即该 1 次）。
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

HERE = Path(__file__).resolve().parent          # .../marketing_ep01/cp9/rework
EP = HERE.parent                                 # .../marketing_ep01/cp9
VPIPE = EP.parent.parent.parent.parent          # .../overnight/vpipe
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import compute_fingerprint  # noqa: E402

MODEL = "MiniMax-H3-Max"
EPISODE_CAP = 2016
PER_SHOT_ANCHOR = 280
ARCHIVE = HERE / "archive_rework_r1"

OLD_PROMPT = ("Wide shot, static camera: a serene minimalist bedroom at dusk, an amber glass "
              "reed diffuser bottle on the wooden bedside table next to a warm glowing lamp, "
              "soft linen bedding, gentle window light, calm premium lifestyle atmosphere, no "
              "people. The diffuser is an amber glass bottle on a walnut wooden base with "
              "natural rattan reeds, catching a warm highlight from the lamp; the room graded "
              "in deep cedar green-gold dusk tones with warm bedroom lamplight, soft linen and "
              "wood textures. Premium photorealistic product commercial look, calm premium "
              "lifestyle mood, rich micro-contrast, vertical 9:16 portrait framing, no "
              "on-screen text, no watermark, no subtitles.")
NEW_PROMPT = ("Wide shot, static camera with a subtle breathing drift: a serene minimalist "
              "bedroom at dusk, an amber glass reed diffuser bottle on the wooden bedside "
              "table next to a warm glowing lamp, soft linen bedding, gentle window light, "
              "calm premium lifestyle atmosphere, no people. The bottle wears a clean blank "
              "craft-paper label, no text, no letters, no typography, no readable label on "
              "the bottle. The diffuser is an amber glass bottle on a walnut wooden base with "
              "natural rattan reeds, catching a warm highlight from the lamp; the room graded "
              "in deep cedar green-gold dusk tones with warm bedroom lamplight, soft linen "
              "and wood textures. Premium photorealistic product commercial look, calm "
              "premium lifestyle mood, rich micro-contrast, vertical 9:16 portrait framing, "
              "no on-screen text, no watermark, no subtitles.")
REWORK_NOTE = (
    "【CP12 回炉重渲 2026-10-09】缘由=cp12.json human_review.queue 3 条全指向本镜"
    "（14.625-17.375s）：J1 glm8 identity_drift conf=0.62（瓶身标签乱码纹理与他镜不一致）"
    "+ J3 omnijev frame_freeze P=0.711 灰区 + J6v2 qc_detectors_v2 frame_freeze conf=0.758"
    "（zero_diff_run 2.75s，同 span 互证）。根因=v1 prompt 两缺陷：① 6 镜中唯一缺"
    " no readable label 条款且无空白标签描述 → 生成侧凭空白色标签带小字；② "
    "「static camera」零运动描述 → 全镜近零帧差。修订：① 「clean blank craft-paper "
    "label, no text, no letters, no typography」+ 补「no readable label on the bottle」"
    "（G2 纪律：产品名只走后期字牌）；② 「static camera with a subtle breathing drift」"
    "（shot_01 同款已验证微运动配方，幅度小不影响产品展示）。场景/景别/产品造型/色彩"
    "与 v1 一致。H3-Max 真实调用 1 次（回炉任务书授权 ≤1 次），task_id=1y1KngRVLRVj，"
    "est 280 积分（ledger 行#80）；v1 终稿+工件存档 archive_rework_r1/。")


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
            if r.get("shot_id") == "shot_05" and r.get("terminal"):
                rec = r
    assert rec and rec.get("status") == "succeeded", f"rework 记录异常: {rec}"
    src = Path(rec["clip_file"])
    assert src.exists(), f"clip 缺失: {src}"

    # ---- v1 存档（终稿 + 三工件；已存在则跳过防覆盖）----
    ARCHIVE.mkdir(exist_ok=True)
    for name in ("shot_05.final.mp4", "shot_05.gen_meta.json",
                 "shot_05.ffprobe.json", "cp9_shot_05.json"):
        dst = ARCHIVE / name
        if not dst.exists():
            shutil.copyfile(EP / name, dst)
    old_sha = sha256_file(ARCHIVE / "shot_05.final.mp4")
    assert old_sha == "3ed08636c1fca2c87d06c319d398d500debf494d7d9eebc86511e40890f3c28f", \
        f"v1 存档 sha 不符: {old_sha}"

    # ---- 新终稿落位 + 对账 ----
    dst = EP / "shot_05.final.mp4"
    shutil.copyfile(src, dst)
    sha = sha256_file(dst)
    assert sha == rec["sha256"], f"sha256 对账不符: {sha} != {rec['sha256']}"
    probe = ffprobe_full(dst)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = next(s for s in probe["streams"] if s["codec_type"] == "audio")

    # ---- gen_meta（repro_log，口径同 postprocess_cp9.py）----
    submit_params = {
        "model": MODEL, "prompt": NEW_PROMPT,
        "duration": 5, "resolution": "768P", "ratio": "9:16",
        "generate_audio": True, "image_mode": "text-to-video",
    }
    meta = {
        "schema_version": "2.0",
        "shot_id": "shot_05", "work_id": "marketing_ep01", "cp_id": "cp9",
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
        "asset": {"path": "overnight/vpipe/out/m2/marketing_ep01/cp9/shot_05.final.mp4",
                  "sha256": sha, "size_bytes": rec.get("size_bytes")},
        "probe": {"width": v["width"], "height": v["height"],
                  "duration_s": float(probe["format"]["duration"]),
                  "vcodec": v["codec_name"], "acodec": a["codec_name"] if a else None,
                  "fps": v["r_frame_rate"]},
        "download_url_present": bool(rec.get("download_url")),
        "notes": "产物 URL 24h 失效不入留痕；视频已落盘 asset.path（官方纪律）。"
                 "回炉重渲（v1 task_id=AP94la8EnPqb 存档 archive_rework_r1/）。",
    }
    (EP / "shot_05.gen_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (EP / "shot_05.ffprobe.json").write_text(
        json.dumps(probe, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- cp9_shot_05.json（权威单镜件）----
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
                     "（SPEC §2.2 如实降级）。云 task_id=1y1KngRVLRVj。" + REWORK_NOTE),
        },
        "aux_gates": [{
            "type": "rule",
            "params_ref": "cp9.gate.repro_log_complete",
            "result": "pass",
            "note": ("submit_params 全量（model/prompt/duration/resolution/ratio/"
                     "generate_audio/image_mode）+ 指纹 " + meta["submit_params_fingerprint"][:16]
                     + "… + task_id 落盘 shot_05.gen_meta.json；repro_level=submit_params"
                       "（API 同参重提交必为新样本，像素级承诺已废止，SPEC §2.2）。"),
        }],
        "payload": {
            "work_id": "marketing_ep01",
            "shot_id": "shot_05",
            "channel": "api_h3max",
            "asset": {"kind": "clip",
                      "fingerprint": sha,
                      "path": "overnight/vpipe/out/m2/marketing_ep01/cp9/shot_05.final.mp4"},
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
                  "非实扣）；云任务 task_id=1y1KngRVLRVj；分辨率实测 "
                  f"{v['width']}x{v['height']}（768P 9:16 档）、h264+aac、"
                  f"{float(probe['format']['duration']):.6f}s（提交 5s，云侧封装偏差如实留痕）。"
                  "参考图未用（纯 T2V，image_mode=text-to-video 显式）。"
                  f"资产 sha256={sha[:16]}…（ffprobe+sha256 本地亲核）。"
                  "rework_route=null：本次为 CP9 层 prompt 定向修订重渲，未走 cp3/cp4/cp5 "
                  "回退路由（checkpoint.schema rework_route enum 无 cp9 值，如实留 null，"
                  "回炉缘由与修订内容见 gate.note）。回炉亲检（代理看帧 2026-10-09）："
                  "微运动实测可见（YDIF 中位 0.2195→1.3746，v1→v2 同口径 160x90 灰度帧差）；"
                  "标签远观为空白奶油色纸标，像素级放大仍有模糊仿文字痕迹（弱于 v1 可读"
                  "衬线字，「no text」未被执行 100%，如实登记交判官复判）；瓶型变为宽肩琥珀瓶"
                  "+木色瓶颈环（与他镜玻璃罗纹颈仍有可见差异，v1 为实验室细颈瓶+清晰白标签，"
                  "偏差方向收敛）。最终判定以 CP12 三判官对新 master 重跑为准，不以亲检代判。"),
    }
    art["fingerprint"] = compute_fingerprint(art)
    (EP / "cp9_shot_05.json").write_text(
        json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- cp9_prompts.json：shot_05 prompt_en 更新 + policy 回炉注记 ----
    prompts_path = EP / "cp9_prompts.json"
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    for s in prompts["shots"]:
        if s["shot_id"] == "shot_05":
            s["prompt_en"] = NEW_PROMPT
            s["prompt_chars"] = len(NEW_PROMPT)
            s["base_ref"] = ("cp7/cp7_prompts.json shots[].prompt_en（构图/运动/节奏基底）；"
                             "2026-10-09 CP12 回炉修订（标签空白化+微运动，差异见 "
                             "cp9_shot_05.json gate.note；v1 prompt 存 "
                             "archive_rework_r1/cp9_prompts 段）")
    prompts["policy"]["rework_shot05"] = (
        "CP12 回炉（2026-10-09）：shot_05 定向修订重渲 1 次（H3-Max，task_id=1y1KngRVLRVj，"
        "est 280，ledger 行#80；线 est 合计 1680+280=1960 ≤ 2016，真实调用累计 7 次=线红线 "
        "6 次+回炉授权 1 次）。两处差异：标签 clean blank craft-paper label（no text/letters/"
        "typography，补 no readable label 对齐他镜 G2 条款）+ subtle breathing drift 微运动"
        "（shot_01 已验证配方）；其余与 v1 一致。")
    prompts_path.write_text(json.dumps(prompts, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")

    # ---- cp9/shots/shot_05.json（现役契约同步）----
    contract_path = EP / "shots" / "shot_05.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["prompt"] = NEW_PROMPT
    contract["notes"] = (
        "CP9 精修（T4 api_h3max，营销线后半程）。CP3 声明镜长 2.83s → ceil=5s"
        "（H3-Max 整数秒区间 [5,15]，不截动作拍）。2026-10-09 CP12 回炉修订：① 标签条款"
        "clean blank craft-paper label（no text/letters/typography，补 no readable label）；"
        "② static camera → static camera with a subtle breathing drift（shot_01 已验证"
        "微运动配方）。场景/景别/造型/色彩与 v1 一致；修订缘由=cp12 队列 3 条"
        "（identity_drift+frame_freeze×2 互证），详见 cp9_shot_05.json gate.note。"
        "G2 纪律：品牌名/价格不进生成侧。image_mode=云通道显式 text-to-video。")
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")

    # ---- cp9.json 聚合更新（只动 shot_05 条目与合计）----
    agg_path = EP / "cp9.json"
    agg = json.loads(agg_path.read_text(encoding="utf-8"))
    old_total = agg["payload"]["est_credit_total"]
    for s in agg["payload"]["shots"]:
        if s["shot_id"] == "shot_05":
            s["asset"]["fingerprint"] = sha
            s["submit_params_fingerprint"] = meta["submit_params_fingerprint"]
            s["credit_spent"] = est
    new_total = sum(s.get("credit_spent", 0) for s in agg["payload"]["shots"])
    n_ok = sum(1 for s in agg["payload"]["shots"] if "asset" in s)
    agg["payload"]["est_credit_total"] = new_total
    agg["payload"]["h3max_real_calls"] = n_ok + 1          # 6 v1 + 1 回炉
    agg["payload"]["budget"] = {"episode_cap": EPISODE_CAP, "est_total": new_total,
                                "headroom": EPISODE_CAP - new_total}
    agg["produced_at"] = now
    agg["gate"]["note"] = (
        f"{n_ok} 镜精修（5 产品镜 + shot_01 口播镜降级变体 no-talking-head）："
        f"est 合计 {new_total}（v1 1680 + CP12 回炉 shot_05 重渲 280 = "
        f"56积分/s × 35s 累计提交秒数）＜ 线集级上限 {EPISODE_CAP}"
        f"（cp1.budget.credit_cap_total；--credit-cap 实跑守卫，超限 exit 3）；"
        f"单镜 280 为 5s 标准档锚点，>5s 镜 warn 标注（CP3 分镜守恒 ceil 所致，"
        f"单镜口径详见各单镜件；全部 5s 标准档）。H3-Max 真实调用累计 7 次"
        f"（v1 线红线 6 次用满 + CP12 回炉任务书授权 1 次，2026-10-09）；"
        f"avatar 真实调用 0 次（参考图缺位降级，理由见 cp9_shot_01.json gate.note）。"
        f"【回炉】shot_05 于 2026-10-09 定向修订重渲（CP12 队列 3 条清偿动作，"
        f"缘由与差异见 cp9_shot_05.json gate.note；v1 存档 archive_rework_r1/）。")
    agg["notes"] = ("营销线 EP01 CP9 聚合件（后半程）：单镜权威件=cp9_shot_XX.json。"
                    "2026-10-09 CP12 回炉更新：shot_05 条目已替换为重渲版"
                    "（新 sha256/参数指纹，est 合计 1960）。")
    agg_path.write_text(json.dumps(agg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"[rework] shot_05: sha={sha[:12]}… est={est} {v['width']}x{v['height']} "
          f"{float(probe['format']['duration']):.3f}s task={rec.get('task_id')}")
    print(f"[rework] aggregate est_total {old_total} -> {new_total} (cap {EPISODE_CAP})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
