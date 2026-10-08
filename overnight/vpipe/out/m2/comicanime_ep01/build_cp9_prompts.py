#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp9_prompts.py — CP9 精修层 prompt/Shot 契约构建（漫剧线 EP01，后半程）。

沿短剧线 cp9 范式（out/m2/shortdrama_ep01/cp9/cp9_prompts.json policy）换漫剧内容：
  - 语言：英文（与草稿层一致；SPIKE-REPORT 发现 A：中文直喂=废片）
  - base：CP7 草稿验证过的构图/运动/节奏（cp7 prompt_en 构图句抄底，替换风格头）
  - added：G8 风格强约束块（CP1 主题：国漫厚涂赛璐璐/粗黑描线/高饱和暖色夜戏；
    任务书：anime cel-shading/平涂色块/清晰线稿——风格词显式强约束，H3-Max G8
    四风格全成口径 model_tiers.yaml T4）+ 人物外形块（双主角身份一致，G5）
    + 光影段（替代不可信的草稿色彩，SPIKE-REPORT 发现 B）
  - shot_09：精确计数描述（CP8 处置："exactly two bowls"，若仍失真→转人工队列如实记录）
  - duration：ceil(CP3 声明镜长) 夹到 H3-Max [5,15] 整数秒（MiniMax-Design-接入手册 §2）
  - image_mode=text-to-video（T2V 必须显式，T4 notes）；分辨率 768P；ratio 9:16

预算：Σ submitted_duration_s=46s → est=46×56=2576 积分 ≤ cap 3360（CP1 credit_cap_total）。
产出：cp9_prompts.json + cp9/shots/shot_01..09.json（Shot 契约，gen_api --shots 输入）。
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EP = HERE
CP9 = EP / "cp9"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---- G8 风格强约束块（CP1 主题逐条落词；显式防漂移负向声明）----
STYLE = ("Chinese donghua anime style, 2D hand-drawn cel animation, cel shading with flat "
         "color blocks, clean crisp line art with thick bold black outlines, anime manhua "
         "aesthetic, high-saturation warm night palette. Strictly 2D anime rendering: no "
         "photorealism, no live-action skin texture, no 3D CGI rendering, no ink-wash style, "
         "no watercolor softness.")
LIGHT = ("Rain-night lighting: a warm glowing yellow-paper lantern hangs over the stall, "
         "high-saturation amber warmth against cool blue rain-night shadows, slanting rain "
         "streaks catching the lantern light, clean cel-shaded light and shadow shapes.")
TAIL = ("Vertical 9:16 portrait framing, no on-screen text, no watermark, no subtitles, "
        "no garbled letters.")
LU = ("Lu Xingci, a handsome young Chinese man in his early twenties, the fallen young "
      "master: sleek black hair in a high half-tied ponytail with loose strands, sharp "
      "elegant brows, calm confident narrow dark eyes, wearing a dark indigo travel "
      "robe-coat with a pale silver sash")
SY = ("Shen Yu, a young Chinese man in his mid-twenties, the noodle-stall cook: black hair "
      "bound by a plain grey cloth headband, sturdy shoulders, quiet steady dark eyes, "
      "wearing a beige hemp apron over a slate-blue robe with a white towel over his left "
      "shoulder")

# 每镜：CP3 action（zh，留档）+ 构图运动句（CP7 草稿 prompt_en 抄底+CP8 加强项）
ROWS = [
    {"shot_id": "shot_01", "cp3_duration_s": 5.22, "refs": ["cast_lu", "prop_lantern_01"],
     "action_zh": "雨夜面摊棚全景：暖黄灯笼挂摊前，雨线斜织，陆星辞掀帘钻进棚里，背影逆光勾边，画格流定格开场",
     "body": ("Medium wide shot, static camera: a rain-soaked street noodle stall at night "
              "under a warm glowing lantern, a young man pushes through the hanging plastic "
              "strip curtain into the awning, his backlit silhouette edged by slanting rain "
              "streaks, the lantern light wrapping his outline in one clean warm rim, "
              "balanced contrast, deep blue night around the warm stall. The young man is " + LU + "."),
     "chars": True},
    {"shot_id": "shot_02", "cp3_duration_s": 3.48, "refs": ["cast_lu"],
     "action_zh": "陆星辞在案前坐下，指节在木案上敲了两下点单，近景面部大半占幅，灯笼暖光勾边，画格流定格",
     "body": ("Close-up, static camera: the same young man sits down at the wooden stall "
              "counter and raps his knuckle on the counter twice to order, his face filling "
              "most of the frame in a clear anime close-up with sharp readable features, "
              "warm lantern light edging his profile, rain haze drifting behind him. He is " + LU + "."),
     "chars": True},
    {"shot_id": "shot_03", "cp3_duration_s": 3.26, "refs": ["cast_shenyu"],
     "action_zh": "沈聿在灶后抬眼，手上擦手的动作不停，毛巾搭回肩上，中近景不抬头回话，画格流定格",
     "body": ("Medium close-up, static camera: a young cook behind the noodle stall glances "
              "up from his pot without lifting his head as he answers, his hands keep wiping "
              "on a towel, then he flips the towel back over his shoulder, steam drifting "
              "past him. He is " + SY + "."),
     "chars": True},
    {"shot_id": "shot_04", "cp3_duration_s": 4.13, "refs": ["cast_shenyu", "prop_bowl_01", "prop_ladle_01"],
     "action_zh": "俯拍案台：下面、收汤、热油淋面的手部特写，蒸汽漫过画幅上沿，面碗粗陶体不形变",
     "body": ("Overhead close-up of hands, static camera: a cook lifts noodles into a rough "
              "ceramic bowl with a long wooden ladle, ladles golden broth over them, then "
              "drizzles sizzling hot oil from a small pot in one unbroken flow, steam rolling "
              "up past the top of the frame; the rough ceramic bowl and ladle keep perfectly "
              "rigid shapes, no deformation, one pair of hands only."),
     "chars": False},
    {"shot_id": "shot_05", "cp3_duration_s": 2.39, "refs": ["prop_pot_01"],
     "action_zh": "汤锅特写：锅沿磨痕与老垢清晰可见，火苗舔着锅底，画面里没有人的脸，器物恒存不形变",
     "body": ("Extreme close-up of an old stockpot, static camera: the worn rim with scratch "
              "marks and years of dark patina clearly visible across the metal lip, bright "
              "orange-blue gas flames clearly licking the pot bottom from below, thin steam "
              "curling up the side, no people in frame, no faces; the pot holds one constant "
              "solid shape."),
     "chars": False},
    {"shot_id": "shot_06", "cp3_duration_s": 2.17, "refs": ["cast_shenyu", "prop_bowl_01"],
     "action_zh": "沈聿舀汤尝味的手停在半空，瞳孔骤缩的面部大特写，蒸汽在背景虚开，镜头极缓推近",
     "body": ("Extreme close-up, the camera very slowly pushing in: the same young cook "
              "freezes with a tasting ladle stopped in mid-air, his eyes widening and pupils "
              "contracting in shock, a clean readable anime face in large scale, steam "
              "dissolving into soft flat cel-shaded blur behind him. He is " + SY + "."),
     "chars": True},
    {"shot_id": "shot_07", "cp3_duration_s": 3.26, "refs": ["cast_lu", "cast_shenyu", "prop_bowl_01", "prop_chopsticks_01"],
     "action_zh": "双人同框隔案对坐，陆星辞把筷子横搁碗沿，直视沈聿，近景一镜不切，双主角身份不漂移",
     "body": ("Medium close-up two-shot, one static take, no cuts: two young men sit facing "
              "each other across the narrow stall counter, on the left " + LU + ", on the "
              "right " + SY + ", two clearly distinct faces that never merge or swap; the "
              "man on the left lays his chopsticks across the rim of an empty ceramic bowl "
              "and stares straight at the cook."),
     "chars": True},
    {"shot_id": "shot_08", "cp3_duration_s": 3.04, "refs": ["cast_shenyu"],
     "action_zh": "沈聿后退半步扶住案沿，毛巾从手里滑落，近景拍他失神的脸，画格流定格",
     "body": ("Close-up, static camera, one single centered subject: the same young cook "
              "staggers half a step backward and grips the counter edge, the towel slipping "
              "from his hand, his face draining into blank disbelief in a clean readable "
              "anime expression, simple uncluttered stall background behind him. He is " + SY + "."),
     "chars": True},
    {"shot_id": "shot_09", "cp3_duration_s": 2.61, "refs": ["cast_lu", "cast_shenyu", "prop_bowl_01", "prop_lantern_01"],
     "action_zh": "两碗面并排凉在案上热气散尽，镜头缓缓拉出门棚，灯笼在雨里晃，收尾呼应开场",
     "body": ("Medium shot, static props, the camera slowly pulling back out past the stall "
              "curtain: exactly two noodle bowls sit side by side on the stall counter with "
              "their steam gone — only two bowls in the whole frame, no third bowl, no "
              "plates, no clutter; behind them the warm lantern sways gently in the rain, "
              "echoing the opening shot, the stall empty of people."),
     "chars": False},
]


def submitted_s(cp3_s: float) -> int:
    return max(5, min(15, int(math.ceil(cp3_s))))


def main() -> int:
    total_s = 0
    shots_out = []
    prompt_rows = []
    for r in ROWS:
        d = submitted_s(r["cp3_duration_s"])
        total_s += d
        prompt_en = r["body"] + " " + LIGHT + " " + STYLE + " " + TAIL
        shots_out.append({
            "schema_version": "1.0",
            "shot_id": r["shot_id"],
            "axis": "OTHER",
            "duration_s": d,
            "aspect": "9:16",
            "resolution": "768P",
            "prompt": prompt_en,
            "audio": {"generate": True},
            "engine_hint": {"preferred": "api", "model": "MiniMax-H3-Max"},
            "notes": ("CP9 精修（T4 api_h3max）。CP3 声明镜长 %.2fs → ceil=%ds（H3-Max 整数秒区间 "
                      "[5,15]%s）。prompt 基底=cp7 草稿验证构图（asset %s）+CP8 加强项；G8 风格强约束块+"
                      "光影段为 CP9 补全（SPIKE-REPORT 发现 B：草稿色偏不可信）。CP8 择优件 upstream。"
                      "image_conditioned=未用（CP2 注册表无 http(s) 参考 URL；files/upload 手册未实测 "
                      "→ fail-closed 不绕过）。"
                      % (r["cp3_duration_s"], d,
                         "，下限夹取" if math.ceil(r["cp3_duration_s"]) < 5 else "",
                         "见 cp8/cp8_%s.json" % r["shot_id"])),
        })
        prompt_rows.append({
            "shot_id": r["shot_id"],
            "cp3_duration_s": r["cp3_duration_s"],
            "submitted_duration_s": d,
            "aspect": "9:16",
            "resolution": "768P",
            "model": "MiniMax-H3-Max",
            "prompt_en": prompt_en,
            "prompt_chars": len(prompt_en),
            "cp3_action_zh": r["action_zh"],
            "base_ref": "cp7 payload.shots[].prompt_en（构图/运动/节奏基底）",
            "cp8_strengthening": "cp8/cp8_%s.json notes（弱/部分镜 prompt 加强项）" % r["shot_id"],
            "g8_style_block": "全镜显式强约束（donghua/cel-shading/平涂色块/清晰线稿/粗黑描线/"
                              "高饱和暖色夜戏 + 防漂移负向声明）；强风格指令镜按 v3.1 裁决：若风格漂移"
                              "如实记录并考虑回退 api_h3（model_tiers api_h3 notes）",
            "reference_images": "none（T2V 纯文生；image-conditioned 留待 files/upload 核验后，本次未用）",
        })

    est_total = total_s * 56
    doc = {
        "schema_version": "2.0",
        "work_id": "comicanime_ep01",
        "produced_by": "agent.cp9_prompt_builder",
        "produced_at": NOW,
        "policy": {
            "language": "en（与草稿层一致；SPIKE-REPORT 发现 A）",
            "base": "CP7 草稿验证过的构图/运动/节奏（cp7 prompt_en 构图句抄底，替换风格头）",
            "g8_style": ("G8 风格化由 CP9 承担（任务书）：风格词显式强约束（anime cel-shading/"
                         "国漫厚涂赛璐璐/平涂色块/清晰线稿/粗黑描线/高饱和暖色夜戏），H3-Max G8 "
                         "四风格全成口径（model_tiers.yaml T4）；若风格漂移按 v3.1 裁决如实记录"
                         "并考虑回退 api_h3，不许静默改 prompt 凑数"),
            "identity": ("双主角外形块逐镜同文（LU/SY）锁身份（G5）；shot_07 双人同框双脸显式"
                         "「distinct faces that never merge or swap」"),
            "count": ("shot_09 精确计数（CP8 处置）：exactly two bowls/only two bowls；若精修层"
                      "仍失真如实记录转人工队列"),
            "color_texture_lighting": "色彩/质感/光影/风格描述全部由 prompt 本身承载（发现 B：草稿色偏不可依赖）",
            "duration": "ceil(CP3 声明镜长) 夹到 H3-Max [5,15] 整数秒（MiniMax-Design-接入手册 §2）",
            "image_mode": "text-to-video（T2V 必须显式；reference_images 未用——CP2 注册表无 http(s) URL）",
            "total_submitted_seconds": total_s,
            "est_credit_total": est_total,
            "budget_note": "est=%d ≤ cap 3360（CP1 credit_cap_total）；H3-Max 真实调用 9 次 ≤ 10 次（红线）" % est_total,
        },
        "shots": prompt_rows,
    }
    (EP / "cp9_prompts.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                                         encoding="utf-8")
    sd = CP9 / "shots"
    sd.mkdir(parents=True, exist_ok=True)
    for s in shots_out:
        (sd / f"{s['shot_id']}.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"cp9_prompts.json + cp9/shots/ 9 镜：total_submitted_seconds={total_s} "
          f"est_credit_total={est_total}（cap 3360）")
    for r in prompt_rows:
        print(f"  {r['shot_id']}: cp3={r['cp3_duration_s']}s -> submit={r['submitted_duration_s']}s "
              f"est={r['submitted_duration_s']*56} chars={r['prompt_chars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
