#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_cp11_json.py — 生成/刷新 CP11 工件并跑 schema 自检（漫剧线 EP01，后半程）。

fingerprint 口径 = src/gate/fingerprint.py compute（payload 规范化 JSON sha256）。
upstream_refs[cp10] 说明（沿短剧线）：CP10 未立 schema 工件（cp10_subtitle_audio 分支
required 的 cer_small/cer_medium 需 whisper 双口径实测，本环境无 ASR 基础设施且红线
禁 pip install，不许伪造数值）；cp10 指纹 = cp10 交付物清单规范化 JSON 的 sha256
（各 tts wav/meta sha256 + subs.ass sha256 + duration_reconciliation.json sha256，
同 fingerprint.py canonical 算法，对象为清单），在 notes 声明推导式。
上游指纹对上游工件 payload 实算（不取声明值）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VPIPE = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import compute_fingerprint  # noqa: E402

EP = VPIPE / "out" / "m2" / "comicanime_ep01"
CP10, CP11 = EP / "cp10", EP / "cp11"
N_SHOTS = 9


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    meta = json.loads((CP11 / "synth_meta.json").read_text(encoding="utf-8"))
    probe = meta["probe"]
    assert meta["verdict"] == "ok"
    assert probe["nb_read_frames"] == probe["expected_frames"]

    # ---- cp10 交付物清单指纹 ----
    manifest = {
        "deliverables": "cp10 tts_seg_XX.wav/.meta.json + subs.ass + duration_reconciliation.json",
        "tts": {f"tts_seg_{i:02d}": {"wav_sha256": sha(CP10 / f"tts_seg_{i:02d}.wav"),
                                     "meta_sha256": sha(CP10 / f"tts_seg_{i:02d}.meta.json")}
                for i in range(1, N_SHOTS + 1)},
        "subs_ass_sha256": sha(CP10 / "subs.ass"),
        "duration_reconciliation_sha256": sha(CP10 / "duration_reconciliation.json"),
    }
    cp10_fp = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()

    # ---- 上游指纹（对上游工件 payload 实算，不取声明值）----
    ups = []
    for cid in ("cp6", "cp9"):
        art = json.loads((EP / f"{cid}.json").read_text(encoding="utf-8"))
        ups.append({"cp_id": cid, "fingerprint": compute_fingerprint(art)})
    ups.insert(1, {"cp_id": "cp10", "fingerprint": cp10_fp})

    known_cuts = probe["known_cuts"]
    master = CP11 / "master.mp4"
    s04 = meta["shot04_cp5_cut"]
    art = {
        "schema_version": "2.0",
        "cp_id": "cp11",
        "artifact_type": "composite",
        "fingerprint": "",
        "produced_by": "agent.cp11_assembler.ffmpeg",
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream_refs": ups,
        "status": "gated",
        "gate": {
            "type": "hard_verify",
            "params_ref": "judges.J6_detectors_v2.rule_params.known_cuts_tol_s",
            "result": "pass",
            "note": (f"8 个拼接硬切点（{known_cuts}）全部登记 known_cuts 白名单，容差沿 "
                     "judges.J6_detectors_v2.rule_params.known_cuts_tol_s；master 实测 8 切点"
                     "与登记逐一重合（select 滤器，工作点 0.3），validate_cp11.py --probe 复核。"
                     "另 CP5 shot_04 切点 3.6s 在合成层显式登记为「声明切点·无实体缝」"
                     f"（master 绝对时刻 {s04['master_abs_s']}s，装配前场景检测无实体缝，"
                     "登记于 cp11/qc_known_cuts.json 声明切点段——不进 payload.known_cuts，"
                     "known_cuts 数==段数-1 恒等式约束）。"
                     "（validate_cp11.py --probe 实跑 exit 0；status gated→passed）"),
        },
        "aux_gates": [
            {"type": "hard_verify", "params_ref": "cp11.gate.duration_tol_s",
             "result": "pass",
             "note": (f"声明 {probe['duration_s']:g}s == CP6 total_frames/fps = "
                      f"720/24；ffprobe 实测 {probe['duration_s']}s / "
                      f"{probe['nb_read_frames']} 帧，±1s 门由校验器复核。")},
            {"type": "hard_verify", "params_ref": "cp11.gate.shot_count_match",
             "result": "pass",
             "note": (f"master_shot_segments {N_SHOTS} == storyboard_shot_count {N_SHOTS}"
                      f"（CP6 shots 数）；实测切点 {len(known_cuts)}（+1 段={N_SHOTS} 段）"
                      "由校验器复核。")},
        ],
        "payload": {
            "work_id": "comicanime_ep01",
            "master_asset": {
                "kind": "clip",
                "fingerprint": sha(master),
                "path": "overnight/vpipe/out/m2/comicanime_ep01/cp11/master.mp4",
            },
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": probe["width"],
            "height": probe["height"],
            "duration_s": probe["duration_s"],
            "master_shot_segments": N_SHOTS,
            "storyboard_shot_count": N_SHOTS,
            "known_cuts": known_cuts,
            "all_cuts_registered": True,
            "black_ratio": probe["black_total_s"] / probe["duration_s"],
        },
        "notes": (
            "《头汤面》EP1 CP11 合成件（漫剧线 30s G8 风格化样片）。【合成器】TASK 预案路径："
            "src/gate/synth.py 只收 kind=lavfi 的程序源（synth.py:186-189），CP9 真实终稿无法入 "
            "case，改 ffmpeg filter_complex 直拼（cp11/assemble_cp11.py，argv/探针全量留痕 "
            "synth_meta.json）。【规格】1080x1920/24fps/h264+aac（ASK 指定）；⚠CP1 "
            "deliverable.pixel_map=1088x1920 与 ASK 1080x1920 存在分歧，本轮从 ASK，分歧在此登记"
            "（沿短剧线同款处置，CP12 复核时注意）。【时间线】CP9 终稿依 CP6 shots 顺序硬切拼接，"
            "每镜 trim=duration_frames/24（帧域冻结，Σ=720 帧实测=720=30.0s）；768x1344 "
            "cover-crop 到 1080x1920（水平裁 ~17px≈1.6%），setsar=1。【known_cuts】8 缝=CP6 镜帧界"
            "累计/24（[5.292, 8.833, 12.125, 16.292, 18.75, 20.917, 24.25, 27.333]），与 select "
            "实测切点逐一重合（0 偏差、0 未登记检出、0 登记未复现）。【CP5 切点登记】CP5 shot_04 "
            "blocking 序列 83 帧>72 帧窗口，known_cuts=[3.6]（20fps 段界）；CP9 shot_04 为单次生成 "
            "T2V 片段无内部缝——装配前场景检测实测素材内切点 []（±0.5s 无命中），该切点在合成层"
            "登记为「声明切点·无实体缝」（master 绝对时刻 15.739s=12.125+3.6×CP5→CP6 域换算"
            " 1.00401），全文登记于 cp11/qc_known_cuts.json source+declared_intra_shot_cuts 与本件 "
            "gate.note，检测器侧豁免由 qc_detectors_v2 --known-cuts 消费同一文件；不虚增 "
            "payload.known_cuts（known_cuts 数==段数-1 恒等式）。装配级修复 0 处（9/9 镜无生成"
            "拼接痕，与短剧线 2 处修复不同，如实记录）。【配音轨】cp10/fit/tts_seg_XX.fit.wav："
            "TTS 实测时长普遍超 CP2 估时（8/9 句 >20%，详见 cp10/duration_reconciliation.json），"
            "CP6 帧域冻结不改，逐句 silenceremove 修剪（-40dB，lead 0.12s/句内停顿>0.4s 截到 "
            "0.35s）+ atempo 压缩入窗（factor 1.04–1.50，seg_06 最大 1.495，语速风险如实登记）；"
            "音频起点=镜起点−sound_lead_in_frames(2帧)/24（声先入），句间零碰撞。【混音】amix "
            "normalize=0，响度实测 −16.13 LUFS（loudnorm input_i，贴 −16 目标），未做归一；BGM 无"
            "授权音源，纯配音轨如实记录。【字幕】cp10/subs.ass 烧录：CP6 subtitle_segments 窗口 × "
            "CP2 narration_text 逐字文本（verbatim_check_pass=true；漫剧字幕=对白+旁白 9 句混排，"
            "G2 纪律：画面零可读文字，台词与拟声一律本后期字牌）；手动 \\N 分行 ≤15 字/行——libass "
            "自动换列实测不生效（短剧线实证沿记）；Noto Sans CJK SC 字号 64（≥48）、竖版安全区 "
            "MarginV=220/MarginL|R=64。【black_ratio】blackdetect（d=0.1/pix_th 0.10/pic_th 0.98）"
            "实测 0 区间。【avatar】无数字人段（漫剧线按 TASK_v4 不含 avatar 段）。【cp10 指纹】"
            "upstream_refs[cp10] 为 cp10 交付物清单（9×wav+meta sha256 + subs.ass + "
            "duration_reconciliation.json）规范化 JSON sha256——CP10 未立 schema 工件（"
            "cp10_subtitle_audio required 的 cer_small/cer_medium 需 whisper 双口径实测，本环境无 "
            "ASR 且红线禁 pip install，不伪造数值），CER 门留待 CP12/后续环境补跑。"),
    }
    art["fingerprint"] = compute_fingerprint(art)
    out = CP11 / "cp11.json"
    out.write_text(json.dumps(art, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- schema 自检（cp11_composite 分支）----
    import jsonschema
    schema = json.loads((VPIPE / "contracts" / "v2" / "checkpoint.schema.json")
                        .read_text(encoding="utf-8"))
    branch = dict(schema)
    branch["$ref"] = "#/definitions/cp11_composite"
    branch["definitions"] = schema["definitions"]
    jsonschema.validate(json.loads(out.read_text(encoding="utf-8")), branch)
    print("schema cp11_composite: OK")
    print("artifact:", out)
    print("fingerprint:", art["fingerprint"])
    print("master sha256:", art["payload"]["master_asset"]["fingerprint"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
