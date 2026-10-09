# -*- coding: utf-8 -*-
"""VDL v2 投影器：包 YAML → CP 工件链 cp1–cp6（checkpoint.schema.json 形态）+ 往返对账。

定位：替代手写 build_cp*.py 的机械投影工具——包（规格面）→ CP 工件（契约面）。
方向与 vdl2_skeleton.py 相反（骨架器：CP 工件 → 包；本件：包 → CP 工件），
二者合起来构成「包 ⇄ CP 工件链」的往返对账闭环。

指纹：唯一口径复用 src/gate/fingerprint.py（sha256(canonical_json(payload))，
键排序+紧凑分隔符+保 UTF-8），本模块**不自造第二套算法**——缺该模块即 exit 2 拒跑。

=======================================================================
映射口径（包 → cp1–cp6 payload；逐字段标注来源类别，语义创作=0）
=======================================================================
每个投影值属三类之一（登记于工件顶层 notes 与 project_report.json）：
  [派生]   包内字段或仓内既定算法可确定（如 frame_count=ceil(duration_s×20)、
           Hamilton 最大余数法帧数折算、source_script_fingerprint=上游实算指纹）；
  [惯例]   包内无来源、但仓内文档既有缺省（如 deliverable 竖版口径 1088×1920
           INTENT.md:89、encode mp4/h264/aac（M2 三线同款）、sound_lead_in=2 帧
           （D3-8 83ms@24fps，out/m2 cp6 notes 既有声明））——照填但在 notes 声明
           「包内无此字段，投影器惯例缺省」；
  [损失标记] 包内无来源且无惯例缺省的 schema 必备字段：字符串填 "[unprojected] …"、
           defect_code 填 "X_UNPROJECTED"、target_duration_s 以 Σ镜时代用——
           明示信息在骨架化/包化时丢失，对账时按内容类差异如实暴露，不豁免。

cp1 意图单（artifact_type=intent_card）：
  work_id ←包顶层；budget.credit_cap_total ←包 budget（缺省=Σ credit_cap_per_shot，
    再缺省=Σ镜×280 惯例）；
  deliverable.pixel_map.aspect ←shots[].aspect（首镜）；width/height/encode_contract
    =惯例缺省（1088×1920 / mp4·h264·aac）；
  must_keep ←首镜 notes「cp1_must_keep」登记位原文回读（骨架器自来源 cp1 保序反投影；
    无登记位时回退 intents[].predicate strength=must 者原文收编）；
  forbidden_zones ←首镜 notes「cp1_forbidden_zones」登记位回读（无登记位 → 损失标记
    1 条 {X_UNPROJECTED}）；
  theme / selling_point ←首镜 notes「cp1_theme」「cp1_selling_point」登记位回读
    （无登记位 → 损失标记）。
cp2 剧本（script）：逐镜一段（逐行一拍一镜形态；无 audio.speech 的镜不产段）：
  segment_id="seg_%02d"（镜序惯例）；narration_text ←shots[].audio.speech；
  visual_description ←本镜 notes「cp2_visual_description」登记位回读（骨架器自来源
    cp2 反投影原文；无登记位回退 camera.description 代用并如实损失标记）；
  estimated_duration_s ←shots[].duration_s；
  tts_safe ←投影器字符集复核（声明+复核双口径中的复核侧）；
  cast_refs ←本镜 notes「cp2_cast_refs」登记位回读（骨架器自来源 cp2 逐段反投影原文；
    空表=「k=」空值；无登记位回退 shots[].characters——参照链 cp2 逐段 cast 为逐段手写
    事实不必等于 cp3.refs 拆分：营销 seg_01 cast_refs=[] 而 cp3.refs=[cast_host]）；
  props_refs ←本镜 notes「cp2_props_refs」登记位回读（同上；无登记位回退「props=…」
    登记位解析——漫剧 seg_01 props_refs=[] 而登记位有 prop_lantern_01 实证）；
  cast=全片首次出现序去重；props ←首镜 notes「cp2_props」登记位原序回读
    （无登记位回退全片首次出现序）；
  target_duration_s ←首镜 notes「cp2_target_duration_s」登记位回读（JSON 数字原文，
    int/float 保真；无登记位=损失标记代用 Σ镜长）；
  estimated_total_duration_s=Σ estimated_duration_s（round 2）。
cp3 分镜表（storyboard）：shot_id/duration_s/action(←camera.description)/
  move(←camera.movement)/channel_hint(←engine.channel) 直投；shot_scale ←shots[].notes
  「cp3_shot_scale=…」登记位解析（缺→结构性错误拒收）；refs=characters+props；
  word_anchors ←本镜 notes「word_anchor_segment/word_anchor_text」登记位回读重建
  （骨架器自来源 cp3 反投影；无登记位不产——字段可选，缺失在对账中如实暴露）；
  source_script_fingerprint=cp2 实算指纹 [派生]。
cp4 关键帧：包无关键帧面 → 不投影（登记；三线参照链亦均无 cp4，双方均缺=对账 OK 项）。
cp5 动作脚本（blocking）：姿态轨道（joint rotation 逐帧数据）是内容本体不是执行态——
  骨架器已把来源 cp5 逐镜序列以「cp5_blocking=<compact JSON>」寄存于各镜 notes
  （json int/float 类型保真回读），本件逐镜回收、按镜序组装 sequences 投影 cp5；
  包内无该登记位时仍不投影（不脑补伪造动画数据），对账按内容类缺失如实计。
  upstream_refs=[cp3 实算指纹]。
cp6 时间线（timeline）：fps ←intents[].temporal_extent.time_base.rate_num（缺省 24 惯例）；
  total_frames=round(target_duration_s×fps)（target ←首镜 notes「cp2_target_duration_s」
  登记位；无登记位回退 round(Σ duration_s×fps)，目标时长缺失在对账中如实暴露）；
  逐镜 duration_frames=Hamilton 最大余数法比例折算（Σ==total_frames 精确守恒，
  同余数按镜序破并列，白皮书 CP6 失败回退行口径）；start_frame 累计排布；
  subtitle_segments=逐镜一段（start/end=帧界÷fps round 3）；rhythm_segments
  （id="rs_%02d"，duration_s=帧数÷fps round 4）；
  subtitle_align_max_dev_ms=ceil(半帧 ms + 0.5ms 进位)（参照链 gate note 既有推导式）；
  sound_lead_in_frames=惯例缺省 2 帧（D3-8）；
  upstream_refs=[cp3]+[cp5 若已投影]（与参照链同序）。

信封（全部属对账「元数据类」，投影器 fresh 产物如实填）：
  produced_by="agent.vdl2Projector"；produced_at=当前 UTC；
  status="pending"、gate.result="pending"（工件刚产出、校验器尚未运行——schema
  status/gate 枚举注释明示的未判定态；不冒充 passed）；
  gate/aux_gates.params_ref 沿 thresholds.yaml 既有键（cp1.gate.forbidden_defect_code_registry /
  cp2.gate.duration_dev_max / cp2.gate.line_shot_ratio / cp3.gate.max_shot_duration_s /
  cp3.gate.word_anchor_valid / cp3.gate.shot_line_count_match / cp6.gate.duration_conservation_frames /
  cp6.gate.subtitle_align_ms_max / cp6.gate.rhythm_segment_s；cp5 已投影时为
  cp5.gate.pose_frame_max + aux frame_time_monotonic / speech_fullbody_lip_layer，
  未投影则无门）；
  upstream_refs=本链实算指纹（cp2←cp1、cp3←cp2、cp6←cp3[+cp5 若在]）；
  notes=本 CP 填充台账（[派生]/[惯例]/[损失标记] 逐条登记）。

自检：产物逐件过 checkpoint.schema.json 对应 cpN 分支（jsonschema，缺库则跳过并警告；
校验失败 exit 1 不落伪工件）。

=======================================================================
对账口径（--reconcile <参照工件目录>）
=======================================================================
对 cp1–cp6 逐件定位（先 <dir>/cpN.json 后 <dir>/cpN/cpN.json），投影目录 vs 参照目录：
  指纹三查：①投影件声明指纹==实算（自洽，违者内容类）；②参照件声明指纹==实算
  （参照自洽性，仅登记）；③投影指纹==参照指纹（等价必要条件）。
  差异两分类：
  · 执行态/元数据类（打印但不改 exit）：顶层 produced_by / produced_at / status /
    gate / aux_gates / notes——投影 fresh 产物与执行链在这六处必然不同，此即
    「包是规格不是执行记录」的分类学边界；
    —— 元数据类边界声明（2026-10-09 复审补记）：notes 整体归元数据类，而参照链
    producer 因 schema additionalProperties=false 把部分语义内容寄存在 notes——
    cp2 cast/props 的一句话人设与道具名称（cp2_script 分支条目只收 ID）、cp1
    溯源三元组 source/clip/sha256/role（intent_card 分支不收编 reference 对象）。
    notes 内承载的语义内容不在等价性 claims 覆盖范围内：投影往返丢失它们仍判
    exit 0；payload 层等价是已证判据。
  · 内容类（任一存在 → exit 1 并逐字段打印）：payload 递归字段级 diff（键缺失/
    多出/数组逐位/标量不等）、fingerprint、upstream_refs（携带上游内容身份，
    随 payload 差异传播，不属元数据）、schema_version/cp_id/artifact_type 身份
    错配、任一侧工件缺失。
  cp7–cp12 不在本投影器交付面，不参与对账（打印 INFO 一行）。
  损失标记产生的差异**不豁免**：已知骨架器丢字段导致的差异照按内容类计——
  宁可诚实 exit 1，不用放宽口径制造通过。

CLI:
  python vdl2_project.py --pkg <包.yaml> --out-dir <目录> [--reconcile <参照工件目录>]
exit：投影模式 0=成功 / 1=结构无法投影或产物自检失败 / 2=IO·环境错误；
     --reconcile：0=仅元数据类差异（或无差异）/ 1=存在内容类差异 / 2=IO·环境错误。
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yaml

HERE = Path(__file__).resolve().parent
VPIPE_ROOT = HERE.parent.parent
sys.path.insert(0, str(VPIPE_ROOT / "src"))
try:
    from gate.fingerprint import compute_fingerprint  # noqa: E402  唯一指纹口径，不得自造第二套
except ImportError as e:   # docstring：缺该模块即 exit 2 拒跑（ImportError 裸崩=1，须显式拦截归 2）
    print(f"[vdl2_project] FATAL 指纹模块缺失：src/gate/fingerprint.py 导入失败 {type(e).__name__}: {e}",
          file=sys.stderr)
    print("[vdl2_project] 指纹唯一口径要求复用该模块（sha256(canonical_json(payload))），"
          "本件不自造第二套算法 → 拒跑（exit 2）", file=sys.stderr)
    sys.exit(2)

CP_SCHEMA = VPIPE_ROOT / "contracts" / "v2" / "checkpoint.schema.json"

PROJECTOR_ID = "vdl2_project.py@vpipe2.0-dev"
PRODUCED_BY = "agent.vdl2Projector"

# 对账「执行态/元数据类」顶层键（其余顶层键一律内容类）
METADATA_KEYS = {"produced_by", "produced_at", "status", "gate", "aux_gates", "notes"}
# 身份键（错配=内容类+结构告警）
IDENTITY_KEYS = ("schema_version", "cp_id", "artifact_type")
RECONCILE_CP_IDS = [f"cp{i}" for i in range(1, 7)]   # 投影器交付面 cp1–cp6

ARTIFACT_TYPE = {"cp1": "intent_card", "cp2": "script", "cp3": "storyboard",
                 "cp5": "blocking", "cp6": "timeline"}

GATE_PENDING_NOTE = "投影器 fresh 产物：门禁判定未运行，result=pending（未判定态），判定数值全部以 params_ref 引 thresholds.yaml 既有键。"

LOSS_PREFIX = "[unprojected]"
LOSS_DEFECT_CODE = "X_UNPROJECTED"


def now_utc_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _err(code, msg):
    return {"code": code, "msg": msg}


def locate_cp(cdir: Path, cp_id: str):
    """cpN.json 定位：先 <dir>/cpN.json 后 <dir>/cpN/cpN.json（与骨架器同规则）。"""
    for rel in (f"{cp_id}.json", Path(cp_id) / f"{cp_id}.json"):
        p = cdir / rel
        if p.is_file():
            return p
    return None


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_shot_notes(notes: str) -> dict:
    """解析骨架器 shots[].notes 登记位：'skeleton: k=v; k=v' → {k: v}（props=逗号分隔）。"""
    out = {}
    for part in str(notes or "").split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip().removeprefix("skeleton:").strip()
            out[k] = v.strip()
    return out


def package_reg(pkg: dict) -> dict:
    """包级登记位 = 首镜 notes 的骨架器登记解析（cp1_*/cp2_* 键；v2 包顶层无登记位）。"""
    shots = pkg.get("shots") or []
    return parse_shot_notes(shots[0].get("notes")) if shots else {}


def tts_safe_check(text: str) -> bool:
    """保守字符集复核：汉字/ASCII 可打印/常用中英标点之外一律判 False。"""
    allow_extra = set("，。！？；：、——……·“”‘’《》（）【】—…!?,:;\"'()%-")
    for ch in str(text):
        if "\u4e00" <= ch <= "\u9fff":
            continue
        if 0x20 <= ord(ch) <= 0x7E:
            continue
        if ch in allow_extra:
            continue
        return False
    return True


def hamilton_frames(durations: list, total: int) -> list:
    """最大余数法（Hamilton）：按 duration 比例把 total 帧分到各镜，Σ==total 精确守恒，
    同余数按镜序破并列（确定性）。白皮书 CP6 失败回退行「确定性折算」口径。"""
    s = sum(durations)
    ideals = [d * total / s for d in durations]
    floors = [int(math.floor(x)) for x in ideals]
    rem = total - sum(floors)
    order = sorted(range(len(durations)), key=lambda i: (-(ideals[i] - floors[i]), i))
    for i in order[:rem]:
        floors[i] += 1
    return floors


def derive_fps(pkg: dict, ledger: list) -> int:
    for it in pkg.get("intents") or []:
        rate = (((it or {}).get("temporal_extent") or {}).get("time_base") or {}).get("rate_num")
        if isinstance(rate, int) and rate >= 1:
            ledger.append(f"[派生] fps={rate} ← intents.temporal_extent.time_base.rate_num")
            return rate
    ledger.append("[惯例] fps=24（包内无 temporal_extent.time_base，投影器缺省帧率）")
    return 24


def derive_props(shot: dict, np_: dict) -> list:
    raw = np_.get("props", "")
    return [t.strip() for t in raw.split(",") if t.strip()] if raw else []


# =====================================================================
# 逐 CP payload 投影
# =====================================================================
def build_cp1(pkg: dict, ledger: list) -> dict:
    shots = pkg.get("shots") or []
    preg = package_reg(pkg)
    aspect = next((s.get("aspect") for s in shots if s.get("aspect")), None)
    if aspect:
        ledger.append(f"[派生] deliverable.pixel_map.aspect={aspect} ← shots[].aspect（首镜）")
    cap_total = (pkg.get("budget") or {}).get("credit_cap_total")
    if cap_total is None:
        per = [s.get("budget", {}).get("credit_cap_per_shot") for s in shots]
        if all(isinstance(x, int) for x in per) and per:
            cap_total = sum(per)
            ledger.append(f"[派生] budget.credit_cap_total={cap_total}=Σ credit_cap_per_shot")
    must_keep = None
    mk_raw = preg.get("cp1_must_keep")
    if mk_raw:
        try:
            mk = json.loads(mk_raw)
            if isinstance(mk, list):
                must_keep = mk
                ledger.append(f"[恢复] must_keep {len(mk)} 条 ← 首镜 notes「cp1_must_keep」登记位"
                              "（骨架器自来源 cp1 保序反投影）")
        except Exception:
            pass
    if must_keep is None:
        must_keep = []
        for it in pkg.get("intents") or []:
            pred = it.get("predicate")
            strength = str(it.get("strength") or "")
            if isinstance(pred, str) and pred.strip() and strength.endswith("must"):
                must_keep.append(pred.strip())
        if must_keep:
            ledger.append(f"[派生] must_keep 收编 {len(must_keep)} 条 intents[].predicate（strength=must 原文）")
        else:
            ledger.append("[损失标记] must_keep：包内无可收编 predicate 且无登记位")
    forbidden_zones = None
    fz_raw = preg.get("cp1_forbidden_zones")
    if fz_raw:
        try:
            fz = json.loads(fz_raw)
            if isinstance(fz, list):
                forbidden_zones = fz
                ledger.append(f"[恢复] forbidden_zones {len(fz)} 条 ← 首镜 notes「cp1_forbidden_zones」"
                              "登记位（骨架器自来源 cp1 反投影）")
        except Exception:
            pass
    if forbidden_zones is None:
        forbidden_zones = [{
            "description": f"{LOSS_PREFIX} 包内无禁区清单（骨架器未投影禁区轴），须 owner 补录",
            "defect_code": LOSS_DEFECT_CODE,
        }]
        ledger.append(f"[损失标记] forbidden_zones：包内无禁区轴，填损失标记条目 defect_code={LOSS_DEFECT_CODE}")
    theme = preg.get("cp1_theme")
    if theme:
        ledger.append("[恢复] theme ← 首镜 notes「cp1_theme」登记位（骨架器自来源 cp1 反投影）")
    else:
        theme = f"{LOSS_PREFIX} 包内无 theme 字段（语义创作=0，原值见来源工件 cp1）"
        ledger.append("[损失标记] theme：包内无登记位")
    selling_point = preg.get("cp1_selling_point")
    if selling_point:
        ledger.append("[恢复] selling_point ← 首镜 notes「cp1_selling_point」登记位（骨架器自来源 cp1 反投影）")
    else:
        selling_point = f"{LOSS_PREFIX} 包内无 selling_point 字段（语义创作=0，原值见来源工件 cp1）"
        ledger.append("[损失标记] selling_point：包内无登记位")
    ledger.append("[惯例] deliverable width/height/encode_contract=1088×1920 / mp4·h264·aac"
                  "（INTENT.md:89 竖版口径；包内无 deliverable 段，投影器惯例缺省）")
    payload = {
        "work_id": pkg.get("work_id"),
        "theme": theme,
        "selling_point": selling_point,
        "must_keep": must_keep,
        "forbidden_zones": forbidden_zones,
        "deliverable": {
            "pixel_map": {"width": 1088, "height": 1920, "aspect": aspect},
            "encode_contract": {"container": "mp4", "video_codec": "h264", "audio_codec": "aac"},
        },
        "budget": {"credit_cap_total": cap_total},
    }
    return payload


def build_cp2(pkg: dict, ledger: list) -> dict:
    shots = pkg.get("shots") or []
    preg = package_reg(pkg)
    segments, cast_seen = [], []
    n_cast_reg = n_props_reg = 0
    for i, s in enumerate(shots, 1):
        speech = ((s.get("audio") or {}).get("speech")) or ""
        if not speech:
            continue
        chars = [c.get("char_id") for c in s.get("characters") or [] if c.get("char_id")]
        np_ = parse_shot_notes(s.get("notes"))
        props = derive_props(s, np_)
        # cp2 逐段 cast/props 回读（骨架器登记位 cp2_cast_refs/cp2_props_refs，空值=空表）：
        # 参照链 cp2 逐段 cast/props 是逐段手写事实（marketing build_cp1_cp6.py SEG_REFS 实证），
        # 不必等于包 characters/props 的 cp3.refs 拆分推导；登记位存在才回读，
        # 无登记位=旧回退路径（characters / props 登记位），既有包不受影响。
        if "cp2_cast_refs" in np_:
            cast_refs = [t.strip() for t in np_["cp2_cast_refs"].split(",") if t.strip()]
            n_cast_reg += 1
        else:
            cast_refs = chars
        if "cp2_props_refs" in np_:
            props_refs = [t.strip() for t in np_["cp2_props_refs"].split(",") if t.strip()]
            n_props_reg += 1
        else:
            props_refs = props
        for c in cast_refs:
            if c not in cast_seen:
                cast_seen.append(c)
        vis = np_.get("cp2_visual_description")
        segments.append({
            "segment_id": f"seg_{i:02d}",
            "narration_text": speech,
            "visual_description": vis or (s.get("camera") or {}).get("description")
                                  or f"{LOSS_PREFIX} 包内无画面描述",
            "estimated_duration_s": s.get("duration_s"),
            "tts_safe": tts_safe_check(speech),
            "cast_refs": cast_refs,
            "props_refs": props_refs,
        })
    est_total = round(sum(s.get("estimated_duration_s") or 0 for s in segments), 2)
    n_vis = sum(1 for s in segments)
    vis_reg = sum(1 for s in shots if parse_shot_notes(s.get("notes")).get("cp2_visual_description"))
    ledger.append(f"[派生] narration_segments={len(segments)} 段（逐镜一段，segment_id=seg_NN 镜序惯例；"
                  "narration_text←audio.speech、estimated_duration_s←duration_s、"
                  "cast/props←cp2_cast_refs/cp2_props_refs 登记位回读，缺登记位段回退 "
                  "characters/props 登记位推导）")
    if n_cast_reg:
        ledger.append(f"[恢复] cast_refs {n_cast_reg}/{n_vis} 段 ← 本镜 notes「cp2_cast_refs」登记位"
                      "（骨架器自来源 cp2 逐段反投影原文，与 characters 推导值不同者才寄存）")
    if n_props_reg:
        ledger.append(f"[恢复] props_refs {n_props_reg}/{n_vis} 段 ← 本镜 notes「cp2_props_refs」登记位"
                      "（骨架器自来源 cp2 逐段反投影原文，与 props 登记位推导值不同者才寄存）")
    if vis_reg:
        ledger.append(f"[恢复] visual_description {vis_reg}/{n_vis} 段 ← 本镜 notes「cp2_visual_description」"
                      "登记位（骨架器自来源 cp2 反投影原文；缺登记位段回退 camera.description 代用）")
    else:
        ledger.append("[损失标记] visual_description：包内无登记位，回退 camera.description 代用")
    ledger.append(f"[派生] estimated_total_duration_s={est_total}=Σ estimated_duration_s（round 2）")
    target = None
    t_raw = preg.get("cp2_target_duration_s")
    if t_raw:
        try:
            tv = json.loads(t_raw)
            if isinstance(tv, (int, float)):
                target = tv
                ledger.append(f"[恢复] target_duration_s={tv} ← 首镜 notes「cp2_target_duration_s」"
                              "登记位（骨架器自来源 cp2 反投影，JSON 数字 int/float 保真）")
        except Exception:
            pass
    if target is None:
        target = est_total
        ledger.append("[损失标记] target_duration_s：包内无目标时长，以 Σ镜长 代用"
                      "（原值在包化时丢失，对账时按内容类差异暴露）")
    props_order = [p for p in (preg.get("cp2_props") or "").split(",") if p]
    if props_order:
        ledger.append(f"[恢复] props 注册表 {len(props_order)} 条 ← 首镜 notes「cp2_props」登记位"
                      "（骨架器自来源 cp2 原序反投影）")
    else:
        props_order = []
        for s in shots:
            for p in derive_props(s, parse_shot_notes(s.get("notes"))):
                if p not in props_order:
                    props_order.append(p)
        ledger.append("[派生] props 注册表=全片首次出现序（包内无 cp2_props 登记位）")
    ledger.append("[派生] tts_safe=投影器字符集复核（保守白名单）")
    return {
        "work_id": pkg.get("work_id"),
        "target_duration_s": target,
        "estimated_total_duration_s": est_total,
        "narration_segments": segments,
        "cast": [{"char_id": c} for c in cast_seen],
        "props": [{"prop_id": p} for p in props_order],
    }


def build_cp3(pkg: dict, cp2_fp: str, errors: list, ledger: list) -> dict:
    shots_out = []
    n_anchors = 0
    for s in pkg.get("shots") or []:
        np_ = parse_shot_notes(s.get("notes"))
        scale = np_.get("cp3_shot_scale")
        if not scale:
            errors.append(_err("CP3.field_missing",
                               f"{s.get('shot_id')}: notes 无 cp3_shot_scale 登记位，shot_scale 必备字段无来源"))
            scale = f"{LOSS_PREFIX}"
        chars = [c.get("char_id") for c in s.get("characters") or [] if c.get("char_id")]
        props = derive_props(s, np_)
        entry = {
            "shot_id": s.get("shot_id"),
            "shot_scale": scale,
            "move": (s.get("camera") or {}).get("movement"),
            "duration_s": s.get("duration_s"),
            "action": (s.get("camera") or {}).get("description") or f"{LOSS_PREFIX} 包内无画面描述",
            "refs": chars + props,
            "channel_hint": ((s.get("engine") or {}).get("channel")) or None,
        }
        a_seg, a_text = np_.get("word_anchor_segment"), np_.get("word_anchor_text")
        if a_seg and a_text:
            entry["word_anchors"] = [{"anchor": a_text, "segment_id": a_seg}]
            n_anchors += 1
        shots_out.append(entry)
    shots_out = [{k: v for k, v in sh.items() if v is not None} for sh in shots_out]
    ledger.append("[派生] shots 骨架直投（shot_id/duration_s/action←camera.description/"
                  "move←camera.movement/channel_hint←engine.channel/refs←characters+notes props）")
    ledger.append("[派生] shot_scale ←shots[].notes「cp3_shot_scale=…」登记位解析")
    if n_anchors:
        ledger.append(f"[恢复] word_anchors {n_anchors} 镜 ← notes「word_anchor_segment/word_anchor_text」"
                      "登记位（骨架器自来源 cp3 反投影；缺登记位镜不产——字段可选，对账如实暴露）")
    else:
        ledger.append("[损失标记] word_anchors：包内无词锚登记位（字段可选故不产；锚文本在包化时丢失，对账如实暴露）")
    ledger.append("[派生] source_script_fingerprint=本链 cp2 实算指纹")
    return {
        "work_id": pkg.get("work_id"),
        "source_script_fingerprint": cp2_fp,
        "shots": shots_out,
    }


def build_cp5(pkg: dict, ledger: list) -> dict | None:
    """cp5 动作脚本：姿态轨道（joint rotation 逐帧数据）是内容本体不是执行态——骨架器已把
    来源 cp5 逐镜序列以「cp5_blocking=<compact JSON>」寄存于各镜 notes，本件逐镜回收、
    按镜序组装 sequences。json 回读 int/float 类型保真（指纹唯一口径下 0 与 0.0 不同键）。
    包内无该登记位 → 返回 None（不脑补伪造动画数据，对账按内容类缺失如实计）。"""
    seqs = []
    for s in pkg.get("shots") or []:
        raw = parse_shot_notes(s.get("notes")).get("cp5_blocking")
        if not raw:
            continue
        try:
            seqs.append(json.loads(raw))
        except Exception as e:
            ledger.append(f"[损失标记] cp5_blocking JSON 解析失败（{s.get('shot_id')}，{type(e).__name__}），本镜序列缺失")
    if not seqs:
        return None
    ledger.append(f"[恢复] sequences={len(seqs)} 条 ← shots[].notes「cp5_blocking」登记位"
                  "（骨架器自来源 cp5 逐镜反投影，JSON 原文回读类型保真）")
    ledger.append("[派生] sequences 按包镜序组装；upstream_refs=[cp3 实算指纹]")
    return {"work_id": pkg.get("work_id"), "sequences": seqs}


def cp5_would_be(pkg: dict, fps: int) -> list:
    """cp5 可机械推导面（仅登记备查——姿态轨道数据以登记位承载，本函数用于无登记位时的备查）。"""
    lines = []
    for s in pkg.get("shots") or []:
        f20 = math.ceil(float(s.get("duration_s") or 0) * 20)
        cuts = [3.6] * (math.ceil(f20 / 72) - 1) if f20 > 72 else []
        lines.append(f"{s.get('shot_id')}: frame_count(20fps)={f20}, known_cuts={cuts}")
    return lines


def build_cp6(pkg: dict, fps: int, upstream: list, ledger: list, target_duration=None) -> dict:
    shots = pkg.get("shots") or []
    durations = [float(s.get("duration_s") or 0) for s in shots]
    if target_duration is not None:
        total = int(round(float(target_duration) * fps))
        ledger.append(f"[派生] total_frames={total}=round(target_duration_s×fps)（目标集时长收敛口，"
                      f"target_duration_s={target_duration} ← 包首镜 notes「cp2_target_duration_s」登记位）")
    else:
        total = int(round(sum(durations) * fps))
        ledger.append(f"[派生] total_frames={total}=round(Σ duration_s×fps)"
                      "（包内无 target_duration_s，无法收敛到目标集时长——若原链存在目标时长，"
                      "此处帧数与之的差在对账中如实暴露）")
    frames = hamilton_frames(durations, total)
    ledger.append("[派生] duration_frames=Hamilton 最大余数法比例折算（Σ==total_frames 守恒，"
                  "同余数按镜序破并列）；start_frame 累计排布")
    cp6_shots, subtitles, rhythms = [], [], []
    start = 0
    seg_i = 0
    for s, fr in zip(shots, frames):
        sid = s.get("shot_id")
        cp6_shots.append({"shot_id": sid, "start_frame": start, "duration_frames": fr})
        speech = ((s.get("audio") or {}).get("speech")) or ""
        if speech:
            seg_i += 1
            end_s = round((start + fr) / fps, 3)
            subtitles.append({"segment_id": f"seg_{seg_i:02d}", "start_s": round(start / fps, 3),
                              "end_s": end_s, "text": speech})
        rhythms.append({"segment_id": f"rs_{len(rhythms) + 1:02d}",
                        "duration_s": round(fr / fps, 4)})
        start += fr
    dev = start - total
    align_ms = math.ceil(500 / fps + 0.5)
    ledger.append(f"[派生] subtitle_align_max_dev_ms={align_ms}=ceil(半帧 ms + 0.5ms 进位)（参照链既有推导式）")
    ledger.append("[惯例] sound_lead_in_frames=2（D3-8 声音先入 83ms@24fps；包内 TransitionIntent 未生成，投影器惯例缺省）")
    return {
        "work_id": pkg.get("work_id"),
        "fps": fps,
        "total_frames": total,
        "episode_duration_s": round(total / fps, 3),
        "duration_conservation_dev_frames": dev,
        "shots": cp6_shots,
        "subtitle_segments": subtitles,
        "subtitle_align_max_dev_ms": align_ms,
        "sound_lead_in_frames": 2,
        "rhythm_segments": rhythms,
        # upstream 由调用方注入（信封层）
    }, upstream


# =====================================================================
# 信封与落盘
# =====================================================================
GATES = {
    "cp1": ({"type": "rule", "params_ref": "cp1.gate.forbidden_defect_code_registry"},
            [{"type": "human", "params_ref": "cp1.gate.owner_confirmation",
              "result": "pending", "note": "CP1 设计内人工介入点：意图卡须 owner 确认，投影器不代签（pending）"}]),
    "cp2": ({"type": "rule", "params_ref": "cp2.gate.duration_dev_max"},
            [{"type": "rule", "params_ref": "cp2.gate.line_shot_ratio", "result": "pending", "note": GATE_PENDING_NOTE}]),
    "cp3": ({"type": "rule", "params_ref": "cp3.gate.max_shot_duration_s"},
            [{"type": "rule", "params_ref": "cp3.gate.word_anchor_valid", "result": "pending", "note": GATE_PENDING_NOTE},
             {"type": "rule", "params_ref": "cp3.gate.shot_line_count_match", "result": "pending", "note": GATE_PENDING_NOTE}]),
    "cp5": ({"type": "rule", "params_ref": "cp5.gate.pose_frame_max"},
            [{"type": "rule", "params_ref": "cp5.gate.frame_time_monotonic", "result": "pending", "note": GATE_PENDING_NOTE},
             {"type": "rule", "params_ref": "cp5.gate.speech_fullbody_lip_layer", "result": "pending", "note": GATE_PENDING_NOTE}]),
    "cp6": ({"type": "rule", "params_ref": "cp6.gate.duration_conservation_frames"},
            [{"type": "rule", "params_ref": "cp6.gate.subtitle_align_ms_max", "result": "pending", "note": GATE_PENDING_NOTE},
             {"type": "rule", "params_ref": "cp6.gate.rhythm_segment_s", "result": "pending", "note": GATE_PENDING_NOTE}]),
}


def envelope(cp_id: str, payload: dict, upstream: list, notes: str) -> dict:
    gate, aux = GATES[cp_id]
    gate = dict(gate, result="pending", note=GATE_PENDING_NOTE)
    art = {
        "schema_version": "2.0",
        "cp_id": cp_id,
        "artifact_type": ARTIFACT_TYPE[cp_id],
        "fingerprint": compute_fingerprint({"payload": payload}),
        "produced_by": PRODUCED_BY,
        "produced_at": now_utc_iso(),
        "upstream_refs": upstream,
        "status": "pending",
        "gate": gate,
        "payload": payload,
        "notes": notes,
    }
    if aux:
        art["aux_gates"] = aux
    return art


def validate_against_schema(artifacts: dict, warnings: list) -> list:
    """产物逐件过 checkpoint.schema.json 对应分支；返回 errors（空=全过）。"""
    try:
        import jsonschema
    except Exception:
        warnings.append("jsonschema 不可用：产物 schema 自检跳过（不冒充已校验）")
        return []
    schema = load_json(CP_SCHEMA)
    errors = []
    for cp_id, art in artifacts.items():
        branch_name = f"{cp_id}_{'intent_card' if cp_id == 'cp1' else ARTIFACT_TYPE[cp_id]}"
        full = {"$schema": "http://json-schema.org/draft-07/schema#",
                "definitions": schema["definitions"], "$ref": f"#/definitions/{branch_name}"}
        for e in jsonschema.Draft7Validator(full).iter_errors(art):
            errors.append(_err("SCHEMA", f"{cp_id}: {'/'.join(str(x) for x in e.absolute_path)}: {e.message}"))
    return errors


def project_package(pkg_path: Path, out_dir: Path):
    """包 → CP 工件链。返回 (exit_code, report_dict)。"""
    report = {"projector": PROJECTOR_ID, "projected_at": now_utc_iso(),
              "package": str(pkg_path), "out_dir": str(out_dir),
              "artifacts": {}, "fill_ledger": {}, "skipped": {}, "warnings": [], "errors": []}
    try:
        pkg = yaml.safe_load(pkg_path.read_text(encoding="utf-8"))
    except Exception as e:
        report["errors"].append(_err("PKG.io", f"包读取/解析失败 {type(e).__name__}: {e}"))
        return 2, report
    if not isinstance(pkg, dict) or not pkg.get("work_id") or not (pkg.get("shots") or []):
        report["errors"].append(_err("PKG.structure", "包缺 work_id 或 shots 为空：无可投影面"))
        return 1, report
    # 深校验归 vdl2_validate.py（单一职责）；本件只做投影面结构自检。

    errors = report["errors"]
    ledger_all = report["fill_ledger"]

    # ---- cp1 ----
    led1 = []
    cp1_payload = build_cp1(pkg, led1)
    # ---- cp2 ----
    led2 = []
    cp2_payload = build_cp2(pkg, led2)
    cp2_fp = compute_fingerprint({"payload": cp2_payload})
    # ---- cp3 ----
    led3 = []
    cp3_payload = build_cp3(pkg, cp2_fp, errors, led3)
    cp3_fp = compute_fingerprint({"payload": cp3_payload})
    # ---- cp5（登记位承载姿态轨道；无登记位 → None 不投影）----
    led5 = []
    cp5_payload = build_cp5(pkg, led5)
    cp5_fp = compute_fingerprint({"payload": cp5_payload}) if cp5_payload is not None else None
    # ---- fps / cp6 ----
    led6 = []
    fps = derive_fps(pkg, led6)
    target = None
    t_raw = package_reg(pkg).get("cp2_target_duration_s")
    if t_raw:
        try:
            tv = json.loads(t_raw)
            if isinstance(tv, (int, float)):
                target = tv
        except Exception:
            pass
    cp6_payload, _ = build_cp6(pkg, fps, [], led6, target_duration=target)

    if errors:
        return 1, report

    notes1 = ("投影器填充台账（vdl2_project.py 机械投影，语义创作=0；包是规格不是执行记录，"
              "本件 status/gate=pending 为未判定态非执行结论）：" + "；".join(led1))
    notes2 = "投影器填充台账：" + "；".join(led2)
    notes3 = "投影器填充台账：" + "；".join(led3)
    notes5 = "投影器填充台账：" + "；".join(led5)
    notes6 = "投影器填充台账：" + "；".join(led6)

    cp6_upstream = [{"cp_id": "cp3", "fingerprint": cp3_fp}]
    if cp5_fp is not None:
        cp6_upstream.append({"cp_id": "cp5", "fingerprint": cp5_fp})
    artifacts = {
        "cp1": envelope("cp1", cp1_payload, [], notes1),
        "cp2": envelope("cp2", cp2_payload, [{"cp_id": "cp1", "fingerprint": artifacts_fp(cp1_payload)}], notes2),
        "cp3": envelope("cp3", cp3_payload, [{"cp_id": "cp2", "fingerprint": cp2_fp}], notes3),
        "cp6": envelope("cp6", cp6_payload, cp6_upstream, notes6),
    }
    if cp5_payload is not None:
        artifacts["cp5"] = envelope("cp5", cp5_payload, [{"cp_id": "cp3", "fingerprint": cp3_fp}], notes5)

    # ---- cp4 / cp5 不投影的登记 ----
    report["skipped"]["cp4"] = ("包内无关键帧面（frames/identity 数据）：不投影；"
                                "参照链三线亦均无 cp4（双方均缺=对账 OK 项）")
    if cp5_payload is None:
        report["skipped"]["cp5"] = ("姿态轨道（joint rotation 逐帧数据）是内容本体，包内无「cp5_blocking」"
                                    "登记位（骨架器未反投影或来源线无 cp5）且不可机械推导，"
                                    "投影器不脑补伪造动画数据 → 不落 cp5.json（对账按内容类缺失如实计）。"
                                    "可机械推导面备查：" + "；".join(cp5_would_be(pkg, fps)))
    ledger_all["cp1"], ledger_all["cp2"], ledger_all["cp3"], ledger_all["cp6"] = led1, led2, led3, led6
    if cp5_payload is not None:
        ledger_all["cp5"] = led5

    # ---- schema 自检 ----
    errors.extend(validate_against_schema(artifacts, report["warnings"]))
    if errors:
        return 1, report

    out_dir.mkdir(parents=True, exist_ok=True)
    for cp_id, art in artifacts.items():
        write_json(out_dir / f"{cp_id}.json", art)
        report["artifacts"][cp_id] = {"file": f"{cp_id}.json", "fingerprint": art["fingerprint"]}
    report["ok"] = True
    return 0, report


def artifacts_fp(payload: dict) -> str:
    return compute_fingerprint({"payload": payload})


# =====================================================================
# 对账（--reconcile）
# =====================================================================
def diff_value(proj, ref, path: str, content: list):
    """递归字段级 diff；内容类差异追加 (path, proj, ref) 三元组。"""
    if isinstance(proj, dict) and isinstance(ref, dict):
        for k in sorted(set(proj) | set(ref)):
            p = f"{path}.{k}" if path else k
            if k not in proj:
                content.append((f"{p}", "<投影侧缺失>", _short(ref[k])))
            elif k not in ref:
                content.append((f"{p}", _short(proj[k]), "<参照侧缺失>"))
            else:
                diff_value(proj[k], ref[k], p, content)
    elif isinstance(proj, list) and isinstance(ref, list):
        if len(proj) != len(ref):
            content.append((f"{path}[]", f"len={len(proj)}", f"len={len(ref)}"))
        for i, (a, b) in enumerate(zip(proj, ref)):
            diff_value(a, b, f"{path}[{i}]", content)
        for i in range(len(proj), len(ref)):      # 参照侧多出的尾元素=投影侧丢失，逐条列出
            content.append((f"{path}[{i}]", "<投影侧缺失>", _short(ref[i])))
        for i in range(len(ref), len(proj)):
            content.append((f"{path}[{i}]", _short(proj[i]), "<参照侧缺失>"))
    else:
        if proj != ref:
            content.append((path, _short(proj), _short(ref)))


def _short(v, n=120):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + "…"


def reconcile_dirs(proj_dir: Path, ref_dir: Path) -> int:
    """投影目录 vs 参照目录逐 CP 对账。返回 exit code（0=仅元数据类，1=内容类，2=环境错误）。"""
    print(f"[vdl2_project][reconcile] 投影目录 {proj_dir}")
    print(f"[vdl2_project][reconcile] 参照目录   {ref_dir}")
    print(f"[vdl2_project][reconcile] 对账面 cp1–cp6（cp7–cp12 不在本投影器交付面，不参与对账）")
    if not proj_dir.is_dir() or not ref_dir.is_dir():
        print("[vdl2_project][reconcile] FATAL 目录不存在", file=sys.stderr)
        return 2
    n_content = n_meta = 0
    bad_cp = []
    for cp_id in RECONCILE_CP_IDS:
        pp, rp = locate_cp(proj_dir, cp_id), locate_cp(ref_dir, cp_id)
        print(f"== {cp_id} " + "-" * 60)
        if pp is None and rp is None:
            print("   双方均无此工件（OK，不计数）")
            continue
        if pp is None or rp is None:
            who = "投影侧缺失" if pp is None else "参照侧缺失"
            print(f"   [内容类] {who}（仅一侧存在：proj={pp} ref={rp}）")
            n_content += 1
            bad_cp.append(cp_id)
            continue
        pa, ra = load_json(pp), load_json(rp)
        # 指纹三查
        for tag, art in (("投影件", pa), ("参照件", ra)):
            try:
                ok = compute_fingerprint(art) == art.get("fingerprint")
            except Exception as e:
                ok = False
                print(f"   [指纹] {tag} 实算异常 {type(e).__name__}: {e}")
            if not ok:
                print(f"   [指纹] {tag} 声明指纹与实算不一致（自洽性破坏→内容类）")
                n_content += 1
        pf, rf = pa.get("fingerprint"), ra.get("fingerprint")
        fp_eq = pf == rf
        print(f"   [指纹] 投影={str(pf)[:16]}… 参照={str(rf)[:16]}… "
              f"{'一致' if fp_eq else '不一致（内容类）'}")
        cdiffs, mdiffs = [], []
        for k in sorted(set(IDENTITY_KEYS) | METADATA_KEYS | {"payload", "fingerprint", "upstream_refs"}):
            pv, rv = pa.get(k, "<投影侧缺失>"), ra.get(k, "<参照侧缺失>")
            if pv == rv:
                continue
            if k in METADATA_KEYS:
                mdiffs.append((k, _short(pv), _short(rv)))
            else:
                if k == "payload":
                    diff_value(pa.get("payload"), ra.get("payload"), "payload", cdiffs)
                else:
                    cdiffs.append((k, _short(pv), _short(rv)))
        for k, a, b in mdiffs:
            print(f"   [元数据] {k}:\n      proj: {a}\n      ref : {b}")
        for p, a, b in cdiffs:
            print(f"   [内容类] {p}:\n      proj: {a}\n      ref : {b}")
        n_meta += len(mdiffs)
        n_content += len(cdiffs)
        if cdiffs:
            bad_cp.append(cp_id)
        print(f"   -- {cp_id} 结论: 内容类 {len(cdiffs)} 处 / 元数据类 {len(mdiffs)} 处")
    print("=" * 72)
    print(f"[vdl2_project][reconcile] RESULT 内容类差异 {n_content} 处 / 元数据类差异 {n_meta} 处"
          + (f"（分布 CP: {','.join(sorted(set(bad_cp)))}）" if bad_cp else ""))
    print("[vdl2_project][reconcile] 边界声明：notes 整体归元数据类——参照链 producer 因 schema "
          "additionalProperties=false 寄存在 notes 的语义内容（cp2 cast/props 一句话人设与道具名称、"
          "cp1 溯源三元组 source/clip/sha256/role）不在等价性 claims 覆盖范围内，投影往返丢失它们仍判 "
          "exit 0；payload 层等价是已证判据")
    if n_content:
        print("[vdl2_project][reconcile] 判定：存在内容类差异 → 语义等价不成立（诚实口径，不放宽）")
        return 1
    print("[vdl2_project][reconcile] 判定：仅元数据类差异（或无差异）")
    return 0


# =====================================================================
def main():
    ap = argparse.ArgumentParser(
        description="VDL v2 投影器（包 → CP 工件链 cp1–cp6；--reconcile 往返对账）")
    ap.add_argument("--pkg", required=True, help="VDL v2 包 YAML 路径")
    ap.add_argument("--out-dir", required=True, help="CP 工件输出目录")
    ap.add_argument("--reconcile", default=None, metavar="参照工件目录",
                    help="对账参照（如 out/m2/shortdrama_ep01）；exit 0=仅元数据类差异，1=内容类差异")
    args = ap.parse_args()
    pkg_path, out_dir = Path(args.pkg), Path(args.out_dir)
    if not pkg_path.is_file():
        print(f"[vdl2_project] FATAL 包不存在: {pkg_path}", file=sys.stderr)
        return 2
    try:
        code, report = project_package(pkg_path, out_dir)
    except Exception as e:
        print(f"[vdl2_project] FATAL {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    for e in report["errors"]:
        print(f"  [ERROR] {e['code']}: {e['msg']}")
    if code != 0:
        print(f"[vdl2_project] FAIL(exit {code}) 投影未产出工件")
        return code
    print(f"[vdl2_project] OK 投影 → {out_dir}")
    for cp_id, info in report["artifacts"].items():
        print(f"  {cp_id}: fingerprint={info['fingerprint'][:16]}…")
    for cp_id, why in report["skipped"].items():
        print(f"  {cp_id}: 未投影——{why}")
    for w in report["warnings"]:
        print(f"  [WARN ] {w}")
    write_json(out_dir / "project_report.json", report)
    if args.reconcile:
        return reconcile_dirs(out_dir, Path(args.reconcile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
