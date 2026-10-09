# -*- coding: utf-8 -*-
"""VDL v2 反向骨架器：存量 CP 工件链（cp1–cp9）→ VDL v2 包（YAML）。

方向与正向链相反：M2 三线（out/m2/<line>/）的 cpN.json 是执行链产物；本工具把它们
**机械反投影**成 VDL v2 包（contracts/v2/vdl_package.schema.json 形态，examples/vdl2/
10_shortdrama_ep01.yaml 为参照范式），供 vdl2_validate.py / vdl2_compile.py 直接消费。

=======================================================================
映射口径（投影方向 CP 工件 → 包；逐条注明工件出处，语义创作=0）
=======================================================================
顶层：
  work_id                 ← cp1.payload.work_id（并对所有已读到的 cpN.payload.work_id 做一致性核对）
  budget.credit_cap_total ← cp1.payload.budget.credit_cap_total
  created                 ← 骨架生成时刻（登记用；包自身的创建时刻，非 CP 执行态）
  default_prompt_mode     = handwritten（prompt 字段是工件 prompt 原文登记，编译器不加工；
                            CP 链无常驻意图→编译依赖，与草案 §2.2「handwritten=intents 仅登记」一致）
shots[]（逐镜 ← cp3.payload.shots[]，段/词锚/注册表 ← cp2，帧率/字幕 ← cp6，终稿档 ← cp9 系）：
  shot_id / duration_s / move / action      ← cp3（duration_s=分镜声明镜长，非 cp9 提交时长）
  camera.movement                           ← cp3.move（v1 词表 static/push_in/pull_out/handheld 原词直落）
  camera.description                        ← cp3.action（原样）
  characters[].char_id                      ← cp3.refs 中解析到 cp2.payload.cast 的 ID
                                              （props 无 v2 结构位 → 落该镜 notes 登记）
  audio.speech                              ← cp2.payload.narration_segments[word_anchors[0].segment_id]
                                              .narration_text（词锚=镜↔段的机械链接）
  aspect                                    ← cp1.payload.deliverable.pixel_map.aspect
  resolution                                ← cp9 系 prompts（cp9_prompts.json，终稿档逐镜声明）
  engine.channel                            ← cp3.channel_hint（规格侧通道；cp9 实落通道属执行态不入包）
  prompt                                    ← cp9 系 prompts 的 prompt_en 原文（终稿提交文本；
                                            缺该文件时回退 cp7.payload.shots[].prompt_en 草稿文本并在 notes 登记）
  prompt_mode                               = handwritten（同上）
  budget.credit_cap_per_shot                ← cp9.payload.shots[].credit_cap_per_shot
  continuity                                = {link: none, seed_policy: none, d3_split_declared: false}
                                            （CP 链为独立成段 + cp6 start_frame 时间线装配，无
                                             prev_tail_frame 链接声明；seed 策略工件未声明）
  intent_refs / acceptance_refs / edit_ops  = []（无常驻意图可引用，见下）
  seed / negative_prompt / cache / axis / engine.route_rule 等不投影：工件无对应声明
                                            （cp9.seed_recorded=null——API seed 零控制力；
                                             cp7.seed 属草稿层执行记录）
notes 登记位（「skeleton: k=v; k=v」记法，往返不丢字段面——2026-10-09 对账修复）：
  cp2_visual_description                    ← cp2.payload.narration_segments[word_anchors[0]
                                              .segment_id].visual_description 原文（v2 Shot 无该结构位，
                                              寄存本镜 notes；投影器回读恢复 cp2 画面描述，不落 camera.description 代用）
  word_anchor_segment / word_anchor_text    ← cp3.payload.shots[].word_anchors[0]（锚文本+段 ID 原文寄存，
                                              投影器回读重建 cp3 word_anchors）
  cp5_blocking                              ← cp5.payload.sequences[] 中本镜序列原文（compact JSON 寄存——
                                              姿态轨道是内容本体不是执行态，json int/float 类型保真回读）；
                                              值含 ASCII ';' 会破坏记法 → 结构性拒收（REG.semicolon）
首镜 notes 追加包级登记（v2 包顶层无登记位，寄存 shots[0]）：
  cp1_theme / cp1_selling_point             ← cp1.payload 原文
  cp1_must_keep / cp1_forbidden_zones       ← cp1.payload 列表原文（compact JSON，保序）
  cp2_target_duration_s                     ← cp2.payload.target_duration_s（JSON 数字原文，int/float 保真；
                                              投影器以 round(target×fps) 收敛 cp6 total_frames 至目标集时长）
  cp2_props                                 ← cp2.payload.props[].prop_id 原序（逗号连接）
intents[]：仅 PostProcessIntent（subtitle_burn）可无损构建，逐字段出处：
  identity.intent_id                        = i-pp-<work_id>-sub（骨架命名约定）
  target/scope                              = work 级（字幕覆盖全片：cp6.subtitle_segments 首尾贯穿）
  temporal_extent.time_base                 ← cp6.payload.fps（rate_num=fps, rate_den=1）
  predicate / ops[0].note                   ← cp1.payload.must_keep 中含
                                              「small_text_policy=post_render_plate」的条目原文
  value                                     = "subtitle_burn"（VPO intent-common anyOf 要求 value/absence
                                              必居其一；工件无措辞来源，取 op 词干最小事实标签）
  strength                                  = must（出处条目属 must_keep）
  control_channel                           = [post_comp]（post_render_plate → 后期绕行的既定映射）
  ops[0].op                                 = subtitle_burn（cp6.subtitle_segments + cp10 字牌资产存在）
  input_refs                                = ["clip:<work_id>"]（合成集输入；自由字符串位）
  output_kind                               = master（终稿成片）
  authority                                 ← cp1.produced_by 去掉「agent.」前缀（意图卡=导演侧工件）
  tolerance                                 = {evidence_status: prior}（VPO tolerance 唯一必备键，首版缺省）
  其余十二元组必填位（reference_context={} / exceptions=[] / acceptance_ref）按 VPO intent-common
  必备面补齐；acceptance_ref 指向本包 acceptance[0]。
  —— 不生成的段及原因（如实登记于包头注释，不静默）：
  · CameraIntent：VPO 必备七元组中 subject_frame_ratio/camera_angle/movement_speed/framing_anchor
    在 CP 工件无对应（cp3 仅 shot_scale/move，且 medium_close 不在 VPO shot_scale 词表）；
    镜头语义改落 shots[].camera 登记位（编译器①的既定回退路径）。
  · TransitionIntent：cp3 notes 明记「逐行一拍一镜无需跨镜引用」；
    boundary_constraints.outgoing_tail/incoming_head.state_assertion 无工件来源。
  · deliverable（DeliverableSet）：VPO 必备 display_target/readability/optical 与 encode 的
    fps/max_bitrate/max_file_mb/audio_policy 无工件对应；cp1 仅 pixel_map{width,height,aspect}+
    encode_contract{container,video_codec,audio_codec}。aspect 投影进每镜 aspect。
  · template：工件无模板槽位定义。
acceptance[]：1 条字幕判据（确定性烧录→可仪表验收）：intent_path 指向 PP 意图 ops[0]、
  metric=subtitle_verbatim_match、gate=block、detector_id=J6_detectors（judges/detectors/ 判官目录
  实存）；detector_version 沿 examples/vdl2 惯例填 vpipe1.0（工件未登记判官版本号，如实注记）。
post_ops[]：[{intent_ref: PP 意图, run_after: [全部 shot_id]}]（字幕在全部镜头完成后烧录）。
CP 清单：cp1–cp9 逐个盘点写进包头注释；缺失者登记「该线无此 CP」（三线 cp4 均缺）。

=======================================================================
纪律
=======================================================================
1. 骨架器是机械投影不做语义创作：包内每个值都能指回某个工件的某字段或本 docstring 的
   既定映射规则；工件里没有的信息不脑补（宁缺勿造，缺的登记在包头注释）。
2. 执行态字段不入包——包是规格不是执行记录：fingerprint / produced_at / status / gate /
   aux_gates / upstream_refs / credit_spent / seed_recorded / asset 路径 / ffprobe / mp4_md5 /
   gen_s / task_id / 判官打分等一律不投影。唯一时刻字段 created 是包自身创建时刻（登记用）。
3. 前缀「skeleton:」保留给该工具写入的 shot.notes 登记位，人工修订时可直接改写。

CLI:
  python vdl2_skeleton.py --dir out/m2/shortdrama_ep01 --out out/vdl2/skeleton/shortdrama_ep01/pkg.yaml
  exit 0 = 生成成功；1 = 结构性无法成包（errors 非空，缺 cp1/cp3、work_id 不一致、镜缺 prompt 等）；
  2 = 输入/环境错误（--dir 不存在、--out 不可写）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yaml

SKELETON_ID = "vdl2_skeleton.py@vpipe2.0-dev"

# 骨架器读取面：cp1–cp9（cp8/cp9 允许在 cpN/ 子目录；其余同）
CP_IDS = [f"cp{i}" for i in range(1, 10)]

# cp1.must_keep 中标志「小字→后期字牌绕行」的既定口径串（G2 实测绕行定稿）
SMALL_TEXT_POLICY_TOKEN = "small_text_policy=post_render_plate"

PP_OP_SUBTITLE_BURN = "vpo:delivery.postprocess_op.subtitle_burn"
CHANNEL_POST_COMP = "vpo:delivery.control_channel.post_comp"
STRENGTH_MUST = "vpo:delivery.strength.must"
GATE_BLOCK = "vpo:delivery.gate.block"
DETECTOR_J6 = "J6_detectors"
DETECTOR_VERSION_CONVENTION = "vpipe1.0"     # examples/vdl2 惯例值；工件未登记判官版本号


def now_utc_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _err(code, msg):
    return {"code": code, "msg": msg}


def locate_cp(cdir: Path, cp_id: str):
    """cpN.json 定位：先 <dir>/cpN.json 后 <dir>/cpN/cpN.json（marketing 形态）。"""
    for rel in (f"{cp_id}.json", Path(cp_id) / f"{cp_id}.json"):
        p = cdir / rel
        if p.is_file():
            return p
    return None


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# =====================================================================
# 逐段投影
# =====================================================================
def _reg(key: str, value) -> str:
    """登记位条目 k=v。结构值以 compact JSON 承载（int/float 类型保真）；
    值含 ASCII ';' 会破坏 'k=v; k=v' 记法 → 抛 ValueError 由调用方结构性拒收（不静默截断）。"""
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if ";" in s:
        raise ValueError(f"REG.semicolon 登记值含 ASCII ';'，'skeleton:' 记法无法无损承载: {key}={s[:80]}…")
    return f"{key}={s}"


def project_shot(cp3_shot: dict, cast_ids: set, props_ids: set, seg_text: dict,
                 prompt_map: dict, prompt_src: str, aspect: str, cap_map: dict,
                 cp2_vis: str | None = None, cp5_seq: dict | None = None):
    """单镜：cp3 一条 + cp2 词锚/注册表 + cp9 系 prompts/cp9 终稿档 → VDL Shot v2。
    返回 (shot_v2 dict, gaps[list[str]])。只投工件里有的事实，缺的进 gaps 由调用方登记。
    cp2_vis：来源 cp2 本镜段 visual_description 原文（寄存 notes，往返恢复）；
    cp5_seq：来源 cp5 本镜姿态序列 dict（compact JSON 寄存 notes，往返恢复）。"""
    sid = cp3_shot.get("shot_id") or ""
    gaps = []
    shot = {
        "schema_version": "2.0",
        "shot_id": sid,
        "duration_s": cp3_shot.get("duration_s"),
        "aspect": aspect,
        "characters": [{"char_id": r} for r in cp3_shot.get("refs") or [] if r in cast_ids],
        "camera": {
            "movement": cp3_shot.get("move"),          # v1 词表 static/push_in/pull_out/…原词
            "description": cp3_shot.get("action"),     # cp3 action 原样
        },
        "intent_refs": [],                             # 无常驻意图可引用（见模块 docstring）
        "prompt_mode": "handwritten",
        "continuity": {"link": "none", "seed_policy": "none", "d3_split_declared": False},
        "edit_ops": [],
    }
    # 台词：cp3 word_anchors[0].segment_id → cp2 narration_text（镜↔段机械链接）
    anchors = cp3_shot.get("word_anchors") or []
    anchor_regs = []
    if len(anchors) == 1:
        speech = seg_text.get(anchors[0].get("segment_id"))
        if speech:
            shot["audio"] = {"speech": speech}
        else:
            gaps.append(f"word_anchor 段 {anchors[0].get('segment_id')!r} 未解析到 cp2 narration_text")
        anchor_regs = [
            _reg("word_anchor_segment", anchors[0].get("segment_id")),
            _reg("word_anchor_text", anchors[0].get("anchor")),
        ]
    elif anchors:
        gaps.append(f"word_anchors={len(anchors)} 个（骨架口径只承接单锚点镜），未投影 audio.speech")

    # 终稿档：prompt 文本与分辨率（cp9 系 prompts；执行态数字一概不取）
    pm = prompt_map.get(sid) or {}
    prompt = (pm.get("prompt_en") or "").strip()
    if prompt:
        shot["prompt"] = prompt
    else:
        gaps.append("cp9 系 prompts 无本镜 prompt_en")
    if pm.get("resolution"):
        shot["resolution"] = pm["resolution"]

    ch = cp3_shot.get("channel_hint")
    if ch:
        shot["engine"] = {"channel": ch}               # 规格侧通道（cp3.channel_hint）
    cap = cap_map.get(sid)
    if cap is not None:
        shot["budget"] = {"credit_cap_per_shot": cap}

    # notes 登记位：无处安放的结构化事实（景别词原值 / props / prompt 出处 /
    # cp2 画面描述 / 词锚 / cp5 姿态序列——后五者为往返不丢字段面，2026-10-09 对账修复）
    reg = [f"prompt_src={prompt_src}", f"cp3_shot_scale={cp3_shot.get('shot_scale')}"]
    props = [r for r in cp3_shot.get("refs") or [] if r in props_ids]
    if props:
        reg.append("props=" + ",".join(props))
    cast_in_ref = [r for r in cp3_shot.get("refs") or [] if r in cast_ids]
    if cast_in_ref and not shot["characters"]:
        reg.append("cast_refs_unresolved=" + ",".join(cast_in_ref))
    if cp2_vis:
        reg.append(_reg("cp2_visual_description", cp2_vis))
    reg.extend(anchor_regs)
    if cp5_seq is not None:
        reg.append(_reg("cp5_blocking", cp5_seq))
    shot["notes"] = "skeleton: " + "; ".join(reg)
    return shot, gaps


def build_postprocess_intent(work_id: str, cp1: dict, cp6: dict | None, shots: list):
    """字幕烧录 PostProcessIntent + 对应 AcceptanceSpec + post_ops 引用形。
    返回 (intent|None, acceptance|None, post_op|None, reg_lines)。"""
    reg = []
    if cp1 is None or cp6 is None:
        return None, None, None, ["postprocess：缺 cp1/cp6，无法构建字幕烧录意图"]
    quote = next((m for m in cp1.get("must_keep") or []
                  if SMALL_TEXT_POLICY_TOKEN in str(m)), None)
    if quote is None:
        return None, None, None, [f"postprocess：cp1.must_keep 无 {SMALL_TEXT_POLICY_TOKEN} 条目，不生成字幕烧录意图"]
    if not (cp6.get("subtitle_segments") or []):
        return None, None, None, ["postprocess：cp6.subtitle_segments 为空，不生成字幕烧录意图"]
    fps = (cp6.get("fps") if isinstance(cp6.get("fps"), int) and cp6.get("fps") >= 1 else None)
    if fps is None:
        return None, None, None, ["postprocess：cp6.fps 非法，无法构建 temporal_extent"]

    intent_id = f"i-pp-{work_id}-sub"
    criterion_id = f"acc-sub-{work_id}"
    authority = str(cp1.get("produced_by") or "").removeprefix("agent.") or "director"
    intent = {
        "identity": {"intent_id": intent_id, "version": "1.0.0"},
        "intent_type": "vpo:craft.intent_object.postprocess_intent",
        "target": {"kind": "work", "ref": work_id},            # 字幕覆盖全片
        "scope": {"level": "vpo:delivery.scope.work", "ref": work_id},
        "temporal_extent": {"time_base": {"rate_num": fps, "rate_den": 1}},
        "reference_context": {},
        "predicate": quote,                                    # cp1.must_keep 原文
        "value": "subtitle_burn",                     # intent-common anyOf 要求 value/absence 必居其一；
                                                      # 工件无措辞来源，取 op 词干最小事实标签（机械复用）
        "strength": STRENGTH_MUST,
        "tolerance": {"evidence_status": "vpo:delivery.evidence_status.prior"},
        "exceptions": [],
        "acceptance_ref": f"{criterion_id}:v1.0.0",
        "authority": authority,
        "control_channel": [CHANNEL_POST_COMP],
        "ops": [{
            "op": PP_OP_SUBTITLE_BURN,
            "note": f"cp1.must_keep 原文：{quote}；字幕段 cp6.subtitle_segments={len(cp6['subtitle_segments'])} 段",
        }],
        "input_refs": [f"clip:{work_id}"],                     # 合成集输入（自由字符串位）
        "output_kind": "vpo:delivery.deliverable_kind.master",
    }
    acceptance = {
        "schema": "https://vpo.example/schemas/v1/l4/acceptance-spec.schema.json",
        "criterion_id": criterion_id,
        "version": "1.0.0",
        "intent_path": f"{intent_id}.ops[0]",
        "metric": "subtitle_verbatim_match",                   # 确定性烧录：逐字可仪表核对
        "tolerance": {"evidence_status": "vpo:delivery.evidence_status.prior"},
        "gate": GATE_BLOCK,
        "detector_id": DETECTOR_J6,
        "detector_version": DETECTOR_VERSION_CONVENTION,
    }
    post_op = {"intent_ref": intent_id, "run_after": [s["shot_id"] for s in shots]}
    reg += [
        f"intents[0]=PostProcessIntent(subtitle_burn, post_comp)；predicate/ops[0].note=cp1.must_keep 原文引用",
        f"acceptance[0]={criterion_id}(block, {DETECTOR_J6})；detector_version={DETECTOR_VERSION_CONVENTION} 沿 examples/vdl2 惯例（工件未登记判官版本号）",
        f"authority={authority} ← cp1.produced_by 去「agent.」前缀",
    ]
    return intent, acceptance, post_op, reg


# =====================================================================
# 主流程
# =====================================================================
def build_skeleton(cdir: Path):
    """读 <cdir> 下 cp1–cp9 → (pkg dict, 包头注释行, errors, warnings)。不做 IO 写盘。"""
    errors, warnings, header = [], [], []
    cps, cps_rel = {}, {}
    for cp_id in CP_IDS:
        p = locate_cp(cdir, cp_id)
        if p is None:
            header.append(f"CP 盘点 {cp_id}: 该线无此 CP（{cp_id}.json 未见于工件目录及其 cpN/ 子目录）")
            continue
        try:
            cps[cp_id] = load_json(p)
            cps_rel[cp_id] = str(p.relative_to(cdir))
            header.append(f"CP 盘点 {cp_id}: ← {cps_rel[cp_id]}")
        except Exception as e:
            errors.append(_err("CP.io", f"{cp_id} 读取/解析失败 {type(e).__name__}: {e}"))

    cp1 = (cps.get("cp1") or {}).get("payload")
    cp2 = (cps.get("cp2") or {}).get("payload")
    cp3 = (cps.get("cp3") or {}).get("payload")
    cp5 = (cps.get("cp5") or {}).get("payload")
    cp6 = (cps.get("cp6") or {}).get("payload")
    cp7 = (cps.get("cp7") or {}).get("payload")
    cp9 = (cps.get("cp9") or {}).get("payload")

    if cp1 is None:
        errors.append(_err("CP.missing", "cp1 缺失：无法确定 work_id / 包级预算 / 画幅（结构性无法成包）"))
    if cp3 is None or not (cp3 or {}).get("shots"):
        errors.append(_err("CP.missing", "cp3 缺失或 shots 为空：无镜头可投影（结构性无法成包）"))
    if errors:
        return None, header, errors, warnings

    work_id = cp1.get("work_id")
    # 跨工件 work_id 一致性（机械核对，不一致=结构错误）
    for cp_id, doc in cps.items():
        w = ((doc.get("payload") or {}).get("work_id"))
        if w is not None and w != work_id:
            errors.append(_err("CP.work_id_mismatch", f"{cp_id}.payload.work_id={w!r} ≠ cp1 的 {work_id!r}"))

    # ---- 包头：映射登记 ----
    header.insert(0, f"VDL v2 反向骨架包 · 来源工件目录 {cdir} · 生成器 {SKELETON_ID} · {now_utc_iso()}")
    header.append("映射口径：机械投影（cp1→work_id/budget/aspect；cp2→台词/注册表；cp3→shots 骨架与"
                  "engine.channel=channel_hint；cp5→逐镜 cp5_blocking 登记位；cp6→帧率/字幕；"
                  "cp9 系 prompts→终稿 prompt/resolution；cp9→credit_cap_per_shot；"
                  "cp1/cp2 语义面与目标时长→notes 登记位），逐字段出处见 src/vdl2/vdl2_skeleton.py 模块 docstring")
    header.append("纪律：包是规格不是执行记录——fingerprint/produced_at/status/gate/upstream_refs/"
                  "credit_spent/seed_recorded/asset/ffprobe 等执行态字段一律不入包；工件缺失的信息不脑补，登记于本注释")

    pkg = {
        "vdl_version": "2.0",
        "work_id": work_id,
        "created": now_utc_iso(),
        "default_prompt_mode": "handwritten",
        "budget": {"credit_cap_total": cp1.get("budget", {}).get("credit_cap_total")},
    }
    if pkg["budget"]["credit_cap_total"] is None:
        pkg["budget"] = {}
        warnings.append("cp1.payload.budget.credit_cap_total 缺失：包级 budget 未投影")
        header.append("登记：包级 credit_cap_total 未投影（cp1.payload.budget 无该键）")
    pixel = cp1.get("deliverable", {}).get("pixel_map") or {}
    aspect = pixel.get("aspect")
    if not aspect:
        errors.append(_err("CP.field_missing", "cp1.payload.deliverable.pixel_map.aspect 缺失：无画幅可投影"))
        return None, header, errors, warnings
    header.append("登记：包级 deliverable 段不生成——cp1 只有 pixel_map/encode_contract 骨架，VPO DeliverableSet "
                  "必备 display_target/readability/optical/encode(fps·bitrate·audio_policy) 无工件对应；"
                  f"aspect={aspect} 已投影进每镜 aspect")

    # ---- cp9 系 prompts（终稿 prompt/resolution 的来源）----
    prompt_map, prompt_src = {}, ""
    for rel in ("cp9_prompts.json", "cp9/cp9_prompts.json"):
        p = cdir / rel
        if p.is_file():
            try:
                prompt_map = {s.get("shot_id"): s for s in load_json(p).get("shots") or []}
                prompt_src = rel
            except Exception as e:
                warnings.append(f"{rel} 解析失败：{type(e).__name__}: {e}")
            break
    if not prompt_map and cp7:
        prompt_map = {s.get("shot_id"): s for s in cp7.get("shots") or [] if s.get("prompt_en")}
        prompt_src = "cp7.json(prompt_en 草稿文本回退)"
        header.append("登记：cp9 系 prompts 缺失，prompt 回退 cp7 草稿层 prompt_en（降级口径）")

    # ---- shots ----
    cast_ids = {c.get("char_id") for c in (cp2 or {}).get("cast") or []}
    props_ids = {x.get("prop_id") for x in (cp2 or {}).get("props") or []}
    seg_text = {s.get("segment_id"): s.get("narration_text")
                for s in (cp2 or {}).get("narration_segments") or []}
    seg_vis = {s.get("segment_id"): s.get("visual_description")
               for s in (cp2 or {}).get("narration_segments") or []}
    seq_map = {}
    for seq in (cp5 or {}).get("sequences") or []:
        sid = seq.get("shot_id")
        if sid:
            seq_map[sid] = seq
    if cp5 and len(seq_map) != len(cp5.get("sequences") or []):
        warnings.append("cp5.sequences 存在同 shot_id 重复序列：登记位每镜仅承载一条，重复者以后者覆盖（如实登记）")
    cap_map = {s.get("shot_id"): s.get("credit_cap_per_shot")
               for s in (cp9 or {}).get("shots") or []}
    pkg["shots"] = []
    for cp3_shot in cp3["shots"]:
        anchors = cp3_shot.get("word_anchors") or []
        cp2_vis = seg_vis.get(anchors[0].get("segment_id")) if len(anchors) == 1 else None
        try:
            shot, gaps = project_shot(cp3_shot, cast_ids, props_ids, seg_text,
                                      prompt_map, prompt_src, aspect, cap_map,
                                      cp2_vis=cp2_vis, cp5_seq=seq_map.get(cp3_shot.get("shot_id")))
        except ValueError as e:   # _reg 的 ';' 冲突结构性拒收
            errors.append(_err("REG.semicolon", f"{cp3_shot.get('shot_id')}: {e}"))
            continue
        pkg["shots"].append(shot)
        for g in gaps:
            errors.append(_err("SHOT.gap", f"{shot.get('shot_id')}: {g}"))
    if errors:
        return None, header, errors, warnings

    # ---- 包级登记（寄存首镜 notes；v2 包顶层 schema additionalProperties=false 无登记位）----
    pkg_regs = []
    if cp1 is not None:
        if cp1.get("theme"):
            pkg_regs.append(_reg("cp1_theme", cp1["theme"]))
        if cp1.get("selling_point"):
            pkg_regs.append(_reg("cp1_selling_point", cp1["selling_point"]))
        if cp1.get("must_keep"):
            pkg_regs.append(_reg("cp1_must_keep", cp1["must_keep"]))
        if cp1.get("forbidden_zones"):
            pkg_regs.append(_reg("cp1_forbidden_zones", cp1["forbidden_zones"]))
    if cp2 is not None:
        if cp2.get("target_duration_s") is not None:
            pkg_regs.append(_reg("cp2_target_duration_s", cp2["target_duration_s"]))
        prop_ids = [p.get("prop_id") for p in cp2.get("props") or [] if p.get("prop_id")]
        if prop_ids:
            pkg_regs.append("cp2_props=" + ",".join(prop_ids))
    if pkg_regs:
        first = pkg["shots"][0]
        first["notes"] = first["notes"] + "; " + "; ".join(pkg_regs)
        header.append("登记：包级登记寄存首镜 notes（cp1_theme/cp1_selling_point/cp1_must_keep/"
                      "cp1_forbidden_zones/cp2_target_duration_s/cp2_props）——v2 包顶层无登记位，"
                      "投影器回读恢复来源 cp1/cp2 语义面与目标时长，往返不丢字段")

    # ---- intents / acceptance / post_ops ----
    intent, acceptance, post_op, reg = build_postprocess_intent(work_id, cp1, cp6, pkg["shots"])
    header += [f"登记：{r}" for r in reg]
    header.append("登记：CameraIntent 不生成——subject_frame_ratio/camera_angle/movement_speed/framing_anchor "
                  "无工件对应（cp3 仅 shot_scale/move，且 medium_close 不在 VPO shot_scale 词表）；"
                  "镜头语义落 shots[].camera 登记位（原值见各镜 notes 的 cp3_shot_scale）")
    header.append("登记：TransitionIntent 不生成——cp3 notes 明记「逐行一拍一镜无需跨镜引用」，"
                  "boundary_constraints.state_assertion 无工件来源")
    header.append("登记：template 段不生成——工件无模板槽位定义")
    pkg["intents"] = [intent] if intent else []
    if acceptance:
        pkg["acceptance"] = [acceptance]
    if post_op:
        pkg["post_ops"] = [post_op]
    if not intent:
        warnings.append("无常驻意图可构建：intents 为空数组（结构性合法，语义全部在 shots 登记位）")

    return pkg, header, errors, warnings


def main():
    ap = argparse.ArgumentParser(
        description="VDL v2 反向骨架器（存量 CP 工件链 cp1–cp9 → VDL v2 包 YAML；机械投影，执行态不入包）")
    ap.add_argument("--dir", required=True, help="CP 工件目录（如 out/m2/shortdrama_ep01）")
    ap.add_argument("--out", required=True, help="包 YAML 输出路径（父目录自动创建）")
    args = ap.parse_args()

    cdir = Path(args.dir)
    if not cdir.is_dir():
        print(f"[vdl2_skeleton] FATAL 工件目录不存在: {cdir}", file=sys.stderr)
        return 2
    try:
        pkg, header, errors, warnings = build_skeleton(cdir)
    except Exception as e:
        print(f"[vdl2_skeleton] FATAL {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if errors:
        print(f"[vdl2_skeleton] REJECT errors={len(errors)} warnings={len(warnings)}")
        for e in errors:
            print(f"  [ERROR] {e['code']}: {e['msg']}")
        return 1

    out = Path(args.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        body = yaml.safe_dump(pkg, allow_unicode=True, sort_keys=False,
                              default_flow_style=False, width=100)
        out.write_text("\n".join(f"# {h}" for h in header) + "\n" + body, encoding="utf-8")
    except Exception as e:
        print(f"[vdl2_skeleton] FATAL 写盘失败 {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print(f"[vdl2_skeleton] OK 包 → {out}")
    print(f"  work_id={pkg['work_id']} shots={len(pkg['shots'])} intents={len(pkg['intents'])} "
          f"acceptance={len(pkg.get('acceptance') or [])} post_ops={len(pkg.get('post_ops') or [])} "
          f"warnings={len(warnings)}")
    for w in warnings:
        print(f"  [WARN ] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
