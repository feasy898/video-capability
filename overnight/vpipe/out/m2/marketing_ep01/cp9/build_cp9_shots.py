#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp9_shots.py — 营销线 EP01 CP9 终稿渲染 Shot 契约 + prompts 表（后半程）。

prompt 口径（任务书）：英文 prompt = CP3 action + CP7 草稿验证构图（prompt_en 抄底）
+ 产品色彩质感段（栖野香薰：琥珀玻璃瓶/天然藤条/雪松绿金调/卧室暖光）
+ 风格段（photorealistic 产品广告）。G2 纪律：产品名/价格不进生成侧
（prompt 内不含品牌字样，且显式 no readable label / no on-screen text）。

duration 口径：ceil(CP3 声明镜长) 夹到 H3-Max 整数秒区间 [5,15]
（MiniMax-Design-接入手册 §2 模型表；本批 5 镜 ceil 后均=5s）。

est 积分：56积分/s × Σ提交秒数 = 56×25 = 1400 ≤ 线预算 2016（cp1.budget.credit_cap_total）。
真实调用预算：本批 5 次 H3-Max（线红线 ≤6 次，余 1 次留给口播镜路径裁决后使用）。

退出码：0=契约+prompts 落盘。
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../marketing_ep01/cp9
EP = HERE.parent
VPIPE = EP.parent.parent.parent

CP3_DURATION = {  # cp3.json payload.shots[].duration_s（声明镜长）
    "shot_01": 4.78, "shot_02": 2.83, "shot_03": 4.13,
    "shot_04": 3.04, "shot_05": 2.83, "shot_06": 2.61,
}
MODEL = "MiniMax-H3-Max"

# CP7 草稿验证构图基底（cp7/cp7_prompts.json shots[].prompt_en 原文抄底）
BASE = {
    "shot_02": ("Close-up with a slow push-in: an amber glass reed diffuser bottle standing on a round wooden base, "
                "natural rattan reeds fanning out of the bottle neck, soft daylight from a bedroom window, "
                "background melting into warm bokeh, the bottle geometry stays perfectly rigid"),
    "shot_03": ("Extreme close-up, static camera: natural rattan reeds standing in the neck of an amber glass "
                "diffuser bottle, gentle light glints sliding along the glass shoulder, dark soft bedroom background, "
                "the bottle and reeds keep a perfectly rigid unchanged shape"),
    "shot_04": ("Medium close-up, static camera: a woman's hand gently swaps and tilts the rattan reeds of an amber "
                "glass diffuser bottle on a wooden bedside table beside a warm glowing lamp, cozy evening bedroom, "
                "slow calm motion, five distinct fingers"),
    "shot_05": ("Wide shot, static camera: a serene minimalist bedroom at dusk, an amber glass reed diffuser bottle "
                "on the wooden bedside table next to a warm glowing lamp, soft linen bedding, gentle window light, "
                "calm premium lifestyle atmosphere, no people"),
    "shot_06": ("Medium close-up with a slow push-in: an amber glass reed diffuser bottle with a round wooden base "
                "on a bedside table, warm lamp rim light, soft dusk window glow behind, clean empty space in the "
                "upper frame, premium calm product showcase, the bottle shape stays rigid"),
}

# CP9 新补全段：产品色彩质感 + 风格（栖野香薰：琥珀玻璃瓶/藤条/雪松绿金调/卧室暖光）
TEXTURE = {
    "shot_02": ("The product is a bedroom reed diffuser: thick amber glass with a warm honey-gold inner glow, "
                "a lathe-turned walnut wooden base with fine visible grain, natural rattan reeds with dry fibrous "
                "texture; graded in deep cedar green-gold tones under soft warm bedroom light. Premium "
                "photorealistic product commercial look, delicate glass reflections and micro highlights, rich "
                "micro-contrast, shallow depth of field, graceful slow motion, vertical 9:16 portrait framing, "
                "no on-screen text, no readable label on the bottle, no watermark, no subtitles."),
    "shot_03": ("The reeds are dry natural rattan with visible fibrous grain; the amber glass shoulder carries a "
                "warm honey-gold rim light that slowly travels along the curve; deep cedar green-gold tones in a "
                "dark warm bedroom night atmosphere. Premium photorealistic product commercial look, macro-level "
                "glass clarity, rich micro-contrast, shallow depth of field, vertical 9:16 portrait framing, "
                "no on-screen text, no readable label on the bottle, no watermark, no subtitles."),
    "shot_04": ("The amber glass bottle glows honey-gold in the lamp light on its walnut wooden base, the rattan "
                "reeds dry and fibrous, the hand moving slowly and calmly; deep cedar green-gold tone grade wrapped "
                "in warm lamplight, cozy evening bedroom atmosphere. Premium photorealistic product commercial "
                "look, natural detailed skin texture on the hand, anatomically correct five fingers, rich "
                "micro-contrast, shallow depth of field, vertical 9:16 portrait framing, no on-screen text, "
                "no readable label on the bottle, no watermark, no subtitles."),
    "shot_05": ("The diffuser is an amber glass bottle on a walnut wooden base with natural rattan reeds, catching "
                "a warm highlight from the lamp; the room graded in deep cedar green-gold dusk tones with warm "
                "bedroom lamplight, soft linen and wood textures. Premium photorealistic product commercial look, "
                "calm premium lifestyle mood, rich micro-contrast, vertical 9:16 portrait framing, no on-screen "
                "text, no watermark, no subtitles."),
    "shot_06": ("The amber glass glows honey-gold with a crisp rim highlight, the walnut base grain visible, the "
                "rattan reeds in soft focus; deep cedar green-gold tone grade in warm bedroom lamplight. Premium "
                "photorealistic product commercial look, delicate glass reflections, rich micro-contrast, shallow "
                "depth of field, slow graceful push-in, vertical 9:16 portrait framing, no on-screen text, "
                "no readable label on the bottle, no watermark, no subtitles."),
}

NEG_NOTE = ("negative 语义并入 prompt 尾段（云通道 payload 白名单无 negative 字段，"
            "沿 shortdrama cp9 先例：no on-screen text / no watermark / no subtitles 显式入 prompt）")


def submitted_s(shot_id: str) -> int:
    d = CP3_DURATION[shot_id]
    return max(5, min(15, math.ceil(d)))


# shot_01 口播镜降级变体（no-talking-head）：owner 预留降级路径（任务书 ② 优先路径触发：
# 5 支 CP9 终稿实测无人物——shot_04 仅一只手；本线无 CP4 定妆照；gen_avatar --image
# 必填单人参考图两源皆缺 →「营销线口播主体参考图缺位」，不伪造人物图）。
# 该镜改为产品旁白开场镜：保留 CP3 shot_01 场景（明亮卧室窗边）/镜别（medium_close）/
# 机位（固定带微呼吸感），口播主体=产品（旁白+字幕由 CP10/CP11 承载）。
FALLBACK_SHOT_01 = ("Medium close-up, static camera with a subtle breathing drift: an amber glass reed "
                    "diffuser bottle on its round walnut wooden base standing on a bright bedroom "
                    "windowsill, natural rattan reeds catching soft morning light, sheer curtains "
                    "glowing with gentle window light, bright cozy bedroom. The amber glass glows warm "
                    "honey-gold, the rattan reeds dry and fibrous; deep cedar green-gold tones in bright "
                    "warm morning bedroom light. Premium photorealistic product commercial look, delicate "
                    "glass reflections and micro highlights, rich micro-contrast, shallow depth of field, "
                    "slow subtle motion, vertical 9:16 portrait framing, no on-screen text, no readable "
                    "label on the bottle, no watermark, no subtitles.")


def main() -> int:
    shots_dir = HERE / "shots"
    shots_dir.mkdir(exist_ok=True)
    cp7p = json.loads((EP / "cp7" / "cp7_prompts.json").read_text(encoding="utf-8"))
    base_by_id = {s["shot_id"]: s for s in cp7p["shots"]}

    rows, total = [], 0
    plan = [("shot_01", FALLBACK_SHOT_01, TEXTURE["shot_02"]),
            ("shot_02", BASE["shot_02"], TEXTURE["shot_02"]),
            ("shot_03", BASE["shot_03"], TEXTURE["shot_03"]),
            ("shot_04", BASE["shot_04"], TEXTURE["shot_04"]),
            ("shot_05", BASE["shot_05"], TEXTURE["shot_05"]),
            ("shot_06", BASE["shot_06"], TEXTURE["shot_06"])]
    for sid, base, tex in plan:
        dur = submitted_s(sid)
        total += dur
        prompt = base + ". " + tex
        notes_extra = ""
        if sid == "shot_01":
            notes_extra = (
                "【口播镜降级变体 no-talking-head】原路由=api_vidu_avatar（G9a 专线，"
                "cp8_shot_01.json 路由记录），实测降级触发：5 支 CP9 终稿亲检均无人物"
                "（shot_04 仅一只手，不构成 gen_avatar 官方要求的单人参考图）；本线无 CP4 "
                "定妆照——「营销线口播主体参考图缺位」成立，按任务书 owner 预留降级路径"
                "处理（该镜改为产品旁白+字幕卡变体），不伪造人物图。保留 CP3 shot_01 场景"
                "（明亮卧室窗边）/镜别/机位，口播主体=产品；seg_01 台词转产品旁白"
                "（CP10 TTS 不变）。")
        contract = {
            "schema_version": "1.0",
            "shot_id": sid,
            "axis": "OTHER",
            "duration_s": dur,
            "aspect": "9:16",
            "resolution": "768P",
            "prompt": prompt,
            "audio": {"generate": True},
            "engine_hint": {"preferred": "api", "model": MODEL},
            "notes": ("CP9 精修（T4 api_h3max，营销线后半程）。CP3 声明镜长 "
                      f"{CP3_DURATION[sid]}s → ceil=5s（H3-Max 整数秒区间 [5,15]，不截动作拍）。"
                      + ("prompt=CP3 shot_01 场景/镜别/机位的产品变体（降级路径，见下）。"
                         if sid == "shot_01" else
                         "prompt 基底=cp7 草稿验证构图（draft "
                         f"{sid}@ltx2b_draft，CP8 单镜件 upstream），")
                      + "色彩/质感/光影/风格段为 CP9 新补全（栖野香薰：琥珀玻璃瓶/天然藤条/"
                      "雪松绿金调/卧室暖光；SPIKE-REPORT 发现 B：草稿色偏不可信，色彩全由 "
                      "prompt 承载）。G2 纪律：品牌名/价格不进生成侧，no readable label 显式。"
                      "image_mode=云通道显式 text-to-video（纯 T2V，无参考图）。"
                      + notes_extra),
        }
        (shots_dir / f"{sid}.json").write_text(
            json.dumps(contract, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        rows.append({
            "shot_id": sid,
            "cp3_duration_s": CP3_DURATION[sid],
            "submitted_duration_s": dur,
            "aspect": "9:16",
            "resolution": "768P",
            "model": MODEL,
            "prompt_en": prompt,
            "prompt_chars": len(prompt),
            "base_ref": ("CP3 shot_01 场景/镜别/机位的产品变体（no-talking-head 降级路径）"
                         if sid == "shot_01" else
                         "cp7/cp7_prompts.json shots[].prompt_en（构图/运动/节奏基底）"),
            "color_texture_lighting": "CP9 新补全段（本表 prompt 第 2 段起）",
            "reference_images": "none（T2V 纯文生；image_mode 显式 text-to-video）",
        })
        print(f"[cp9] {sid}: dur={dur}s prompt_chars={len(prompt)}")

    prompts_art = {
        "schema_version": "2.0",
        "work_id": "marketing_ep01",
        "produced_by": "agent.cp9_prompt_builder",
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "policy": {
            "language": "en（与草稿层一致）",
            "base": "CP7 草稿验证过的构图/运动/节奏（cp7 prompt_en 抄底）",
            "added": ("色彩/质感/光影/风格描述全部由 prompt 本身承载"
                      "（SPIKE-REPORT §4 发现 B：草稿色偏不可依赖）；产品质感口径="
                      "栖野香薰（琥珀玻璃瓶/天然藤条/雪松绿金调/卧室暖光，cp1 theme）"),
            "duration": "ceil(CP3 声明镜长) 夹到 H3-Max [5,15] 整数秒（接入手册 §2 模型表）",
            "image_mode": "text-to-video（T2V 必须显式；本线 CP2 注册表无 http(s) 参考 URL，"
                          "files/upload 未实测 → 不用参考图）",
            "g2_discipline": "产品名/价格/链接不进生成侧（no readable label + no on-screen text 显式）",
            "total_submitted_seconds": total,
            "est_credit_total": total * 56,
            "budget_note": f"est {total * 56} ≤ cp1.budget.credit_cap_total=2016；"
                           f"H3-Max 真实调用合计 6 次（5 产品镜 + shot_01 降级变体，"
                           f"线红线 ≤6 次正好用满）",
            "shot_01_fallback": (
                "口播镜降级变体（no-talking-head）：触发证据=5 支 CP9 终稿亲检无人物"
                "（shot_04 仅一只手）+ 本线无 CP4 定妆照 → gen_avatar --image 必填的"
                "单人参考图两源皆缺，「营销线口播主体参考图缺位」；按任务书 owner 预留"
                "降级路径处理（产品旁白+字幕卡变体），不伪造人物图。avatar 真实调用 "
                "0 次（≤2 次红线内，未触发原因=参考图缺位）。"),
            "negative_note": NEG_NOTE,
        },
        "shots": rows,
    }
    (HERE / "cp9_prompts.json").write_text(
        json.dumps(prompts_art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[cp9] total_submitted_seconds={total} est_credit_total={total * 56}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
