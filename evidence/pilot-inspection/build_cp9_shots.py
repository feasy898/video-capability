#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp9_shots.py — CP9 精修 Shot 契约 + prompt 表构建（10 镜，shot_09 已被 CP8 拒绝）。

prompt 构造规则（任务书 + SPIKE-REPORT §4）:
  基底 = CP7 草稿验证过的构图/运动/节奏（cp7 prompt_en 逐镜抄底）
  补全 = 色彩/质感/光影/风格（草稿色偏不可信 → 色彩信息全部来自 prompt 本身）
  语言 = 英文（与草稿层一致）
时长 = ceil(CP3 声明镜长) 且夹到 H3-Max 区间 [5,15] 整数秒（手册 §2 模型表）。
输出:
  overnight/vpipe/out/m2/shortdrama_ep01/cp9/shots/shot_XX.json   (contracts/shot.schema.json 契约)
  overnight/vpipe/out/m2/shortdrama_ep01/cp9/cp9_prompts.json     (prompt 表留痕)
"""
import datetime
import json
import math
from pathlib import Path

ROOT = Path("/home/pan-ding/workspace/视频能力")
M2 = ROOT / "overnight/vpipe/out/m2/shortdrama_ep01"
OUT = M2 / "cp9"
(OUT / "shots").mkdir(parents=True, exist_ok=True)

cp3 = json.loads((M2 / "cp3.json").read_text(encoding="utf-8"))
cp3_by_id = {s["shot_id"]: s for s in cp3["payload"]["shots"]}
cp7 = json.loads((M2 / "cp7.json").read_text(encoding="utf-8"))
cp7_by_id = {s["shot_id"]: s for s in cp7["payload"]["shots"]}

STYLE = ("Cinematic photorealistic live-action Chinese short-drama look, natural detailed skin texture, "
         "filmic color grade of warm amber banquet glow against cool rain-blue night tones, soft volumetric "
         "practical lighting, 35mm anamorphic lens look, shallow depth of field, rich micro-contrast, "
         "graceful natural motion, vertical 9:16 portrait framing, no on-screen text, no watermark, no subtitles.")

CHAR_XIAOMAN = ("She is Xiaoman, a Chinese woman in her early twenties, pale rain-damp skin, sleek black "
                "shoulder-length hair with fine water droplets at the tips, calm defiant dark eyes, wearing "
                "a tailored charcoal-black wool blazer over a white shirt.")
CHAR_LIN = ("He is Father Lin, a Chinese patriarch in his sixties, combed-back silver-white hair, deep frown "
            "lines, stern hooded eyes, wearing an impeccable dark navy three-piece suit with a burgundy tie.")

# 基底抄 cp7 prompt_en（构图/运动/节奏已被草稿层验证），色彩/质感/光影/风格为新补全段
PROMPTS = {
    "shot_01": (
        "Extreme close-up at a low angle: a young woman pushes open a heavy carved wooden door of an old "
        "mansion on a rainy night and steps into the foyer, her face filling the frame, backlit by the glowing "
        "rain curtain behind her, water droplets dripping from her hair. " + CHAR_XIAOMAN + " "
        "Cool steel-blue moonlight from the storm outside rims her silhouette and the thousands of backlit "
        "rain streaks; a warm dim amber foyer lamp wraps one side of her cheek; the old door's wet walnut "
        "wood grain glistens; thin mist drifts through the backlight beam. " + STYLE),
    "shot_02": (
        "Medium shot at a crowded banquet: an elderly man in a dark suit freezes with a raised wine glass, "
        "red wine rippling in the bowl, the camera slowly pushing in over the rim of the glass as he lifts his "
        "other hand to beckon a guard at the door, guests turning their heads. " + CHAR_LIN + " "
        "The crystal goblet refracts warm golden chandelier light, the wine a deep garnet red catching a spark; "
        "white damask tablecloth, candle flames in soft bokeh, guests in black-tie dissolving into warm golden "
        "circles; his silver hair glossed by the chandelier, cut-glass reflections trembling across his brow. " + STYLE),
    "shot_03": (
        "Close-up: a young woman places a steel wrench on a white tablecloth, light glinting along the rigid "
        "metal body, the camera slowly pushing in while staying locked on the wrench, the banquet hall melted "
        "into soft bokeh behind. The wrench is brushed drop-forged steel with machined edges, its silhouette "
        "streaked by golden chandelier reflections; the cloth is crisp white damask with woven gloss; the steel "
        "body stays perfectly rigid and undeformed through the whole move; " + CHAR_XIAOMAN.replace("She is Xiaoman, a Chinese woman", "her hand entering frame is Xiaoman's, a Chinese woman") + " "
        "warm amber key light rakes across the metal, cool blue window fill keeps the shadows neutral. " + STYLE),
    "shot_04": (
        "Close-up: an elderly man slams a contract dossier onto the table and presses his finger hard on the "
        "signature line, the paper sheet dominating half of the frame with soft illegible printed lines, static "
        "camera, dramatic side light. " + CHAR_LIN + " "
        "The contract paper is aged ivory with a visible tooth and soft unreadable printed rules; his weathered "
        "hand, veins and a heavy gold signet ring, dents the page; the table is dark polished walnut mirroring "
        "a knife-edge of warm amber lamplight; dust motes hang in the raking side beam; deep shadow swallows "
        "the background. " + STYLE),
    "shot_05": (
        "Medium close-up two-shot, one static take: a young woman and an elderly man sit facing each other "
        "across a banquet table, she slides the last page of a contract across the table with one fingertip, "
        "both in frame, no cuts. " + CHAR_XIAOMAN + " " + CHAR_LIN + " "
        "A single warm candle centerpiece burns between them, carving her youthful jaw against his deep frown "
        "lines; the contract page is bright ivory against dark walnut; crystal and cutlery glint at the frame "
        "edges; the background falls into warm amber gloom with faint cold blue window light far behind. " + STYLE),
    "shot_06": (
        "Extreme close-up: an elderly man's eyes widen and his pupil contracts in shock, his fingers trembling "
        "as they pinch the paper page, guests behind him blurred into round bokeh, the camera slowly pushing in "
        "toward his eye. " + CHAR_LIN + " "
        "The contracting pupil catches a single spark of candlelight; weathered skin with deep wrinkles and "
        "silver eyebrow hairs rendered in fine detail; the ivory page edge trembles in his grip; the background "
        "bokeh burns warm gold with faint red lantern accents; a cold blue rim light separates his temple from "
        "the gloom. " + STYLE),
    "shot_07": (
        "Medium shot, fixed camera, split composition: on the left the same young woman in oil-stained mechanic "
        "overalls from years ago, on the right she stands today in a sharp tailored business suit, the same "
        "steady unwavering gaze in both halves. She is Xiaoman, a Chinese woman in her early twenties with "
        "sleek black shoulder-length hair and calm defiant dark eyes. "
        "Left half: cold blue-green fluorescent garage light, oil-stained orange canvas overalls with grease "
        "marks, concrete wall and tool board behind, faint dust in the air. Right half: warm golden chandelier "
        "banquet light, a sharp charcoal-black tailored suit with a subtle sheen, dark walnut and amber gloom "
        "behind. The two halves meet on a clean vertical seam; her gaze never changes across the seam. " + STYLE),
    "shot_08": (
        "Handheld medium close-up from a low angle with a slight shake: an elderly man staggers half a step and "
        "grips the table edge, his wine glass topples and red wine soaks into the white tablecloth, his face "
        "draining into blank shock. " + CHAR_LIN + " "
        "The garnet-red wine blooms and bleeds through the white damask weave; the crystal glass rolls on its "
        "side; chandelier light smears warm across the frame with the handheld sway; his silver hair falls "
        "loose over the furrowed brow; a cold blue window edge glows far behind the guests' bokeh. " + STYLE),
    "shot_10": (
        "Medium shot, fixed camera, no cutaway: an elderly man slumps back into his chair defeated, white hair "
        "falling across his forehead, he drags a hand down his face, his shoulders collapsing. " + CHAR_LIN + " "
        "A single warm overhead lamp carves deep shadows into his wrinkles and silver hair while a cold blue "
        "night window rims his shoulder; the burgundy tie hangs loose, the navy suit jacket creasing as his "
        "frame gives way; crystal glassware glints dimly at the table edge; the banquet gloom swallows the "
        "background. " + STYLE),
    "shot_11": (
        "Wide shot: a young woman downs her drink in one gulp with the glass tilted fully vertical, turns and "
        "walks out through the front door, the camera pulling back and rising to reveal the whole mansion foyer "
        "as the rain curtain closes behind her silhouette. " + CHAR_XIAOMAN + " "
        "The last swallow of garnet-red wine catches the chandelier flame; the double-height marble foyer glows "
        "warm amber from wall sconces while the open door pours in cold silver-blue storm light and curtains of "
        "rain; her charcoal blazer reads as a crisp dark silhouette against the downpour; wet marble floor "
        "mirrors both light worlds. " + STYLE),
}

ADVANCE = ["shot_01", "shot_02", "shot_03", "shot_04", "shot_05",
           "shot_06", "shot_07", "shot_08", "shot_10", "shot_11"]

rows = []
for sid in ADVANCE:
    c3 = cp3_by_id[sid]
    c7 = cp7_by_id[sid]
    dur = max(5, min(15, math.ceil(c3["duration_s"])))   # H3-Max: 整数 5..15（手册 §2 模型表）
    prompt = PROMPTS[sid]
    assert len(prompt) <= 7000, (sid, len(prompt))
    shot = {
        "schema_version": "1.0",
        "shot_id": sid,
        "axis": "OTHER",
        "duration_s": dur,
        "aspect": "9:16",
        "resolution": "768P",
        "prompt": prompt,
        "audio": {"generate": True},
        "engine_hint": {"preferred": "api", "model": "MiniMax-H3-Max"},
        "notes": (f"CP9 精修（T4 api_h3max）。CP3 声明镜长 {c3['duration_s']}s → ceil={dur}s"
                  f"（H3-Max 整数秒区间 [5,15]，不截动作拍）。prompt 基底=cp7 草稿验证构图（asset "
                  f"{c7['asset']['fingerprint'][:16]}…），色彩/质感/光影/风格段为 CP9 补全（SPIKE-REPORT "
                  f"§4：草稿色偏不可信）。CP8 择优件 upstream。image_conditioned=未用（CP2 注册表无 "
                  f"http(s) 参考 URL；files/upload 手册未实测 → fail-closed 不绕过）。"),
    }
    (OUT / "shots" / f"{sid}.json").write_text(
        json.dumps(shot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rows.append({
        "shot_id": sid,
        "cp3_duration_s": c3["duration_s"],
        "submitted_duration_s": dur,
        "aspect": "9:16",
        "resolution": "768P",
        "model": "MiniMax-H3-Max",
        "prompt_en": prompt,
        "prompt_chars": len(prompt),
        "base_ref": "cp7 payload.shots[].prompt_en（构图/运动/节奏基底）",
        "color_texture_lighting": "CP9 新补全段（本表 prompt 第 2 段起）",
        "reference_images": "none（T2V 纯文生；image-conditioned 留待 files/upload 核验后，本次未用）",
    })

table = {
    "schema_version": "2.0",
    "work_id": "shortdrama_ep01",
    "produced_by": "agent.cp9_prompt_builder",
    "produced_at": "2026-10-09T01:05:00Z",
    "policy": {
        "language": "en（与草稿层一致）",
        "base": "CP7 草稿验证过的构图/运动/节奏（cp7 prompt_en 抄底）",
        "added": "色彩/质感/光影/风格描述全部由 prompt 本身承载（SPIKE-REPORT §4 发现 B：草稿色偏不可依赖）",
        "duration": "ceil(CP3 声明镜长) 夹到 H3-Max [5,15] 整数秒（MiniMax-Design-接入手册 §2 模型表）",
        "image_mode": "text-to-video（T2V 必须显式；reference_images 未用——参考图仅 http(s) URL 可直传，CP2 注册表无 URL，本地路径 fail-closed）",
        "total_submitted_seconds": sum(r["submitted_duration_s"] for r in rows),
        "est_credit_total": 56 * sum(r["submitted_duration_s"] for r in rows),
    },
    "shots": rows,
}
(OUT / "cp9_prompts.json").write_text(
    json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"shots={len(rows)} total_s={table['policy']['total_submitted_seconds']} "
      f"est_credit={table['policy']['est_credit_total']} (cap 8064)")
