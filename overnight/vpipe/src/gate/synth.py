#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""synth.py — CP11 合成层确定性合成器（vpipe v4，M1-W5 像素级回归配套）。

规范出处：
- 白皮书 §3 CP11：ffmpeg 子进程确定性合成（确定性梯度顶端），同输入必须同输出；
  所有拼接硬切点登记 known_cuts。
- 白皮书 §4 T0：T0 层是唯一能承诺像素级复现的层（零调用费 + CPU 墙钟）；
  像素级回归用例 ≥3（同输入二遍编码 md5 一致，工程方案v3.1.md:218 实测口径，
  与 validate_cp11.py --self-check 同源）。
- TASK_v4 M1-W5：CP11 合成层硬校验挂载 + 像素级回归（3 个用例同输入同输出，
  md5 一致）。

用法：
    python3 src/gate/synth.py --case <case.json> --out <dir>

case.json 声明式契约（全部素材由 ffmpeg lavfi 程序生成，零模型、零下载）：
    case_id      str    用于产物命名，限 [A-Za-z0-9_.-]+
    timeline     dict   size "WxH" / fps / duration_s / mode("concat"|"xfade") /
                        shots[{input,start,duration}]（start=成片时间轴秒）；
                        xfade 模式另需 transitions[{after_shot,type,duration}]
    inputs       dict   name → {kind:"lavfi", source:"color=…|testsrc2=…"}（ffmpeg
                        内建源表达式；一个 input 可被多个 shot 复用，每 shot 实例化一份）
    subtitles    dict   可选。mode="drawtext"（items[{text,start,end,font,fontsize,
                        fontcolor,box,boxcolor,x,y}]，x/y 用内置预设 center/left/
                        right/top/bottom，文本限安全 ASCII 子集——ffmpeg 滤图两层
                        转义器是 M2 工作，夹具只放行无歧义字符）；mode="ass"
                        （content=整份 ASS 文本，落盘 out/<case_id>.ass 后 ass= 烧录，
                        libass+fontconfig 同机确定性）
    audio        dict   可选。{kind:"lavfi", source:"sine=…"}；
                        normalize={mode:"loudnorm_two_pass", I,TP,LRA} 时先跑测量遍
                        （loudnorm print_format=json 解析 stderr），再以 linear=true
                        两遍归一（EBU R128，ffmpeg 内建滤镜）
    output       dict   container/video{codec,preset,crf,pix_fmt,threads}/
                        audio{codec,bitrate}（缺省 libx264/veryfast/28/yuv420p/
                        threads=1 + aac/64k；threads=1 钉死线程数，消除 x264 帧级
                        并行的宿主核数耦合）
    cp11         dict   可选。声明了才产出 cp11_artifact.json（挂 validate_cp11.py
                        实测门）：work_id/storyboard_shot_count/known_cuts/
                        all_cuts_registered/upstream_refs。concat 模式下 known_cuts
                        与时间线隐含切点（累计 start）不符 → 拒绝生成（登记册不许
                        说谎，M1-W5 known_cuts 铁律的声明侧）；xfade 无硬切点，
                        known_cuts 登记语义不适用，带 cp11 块即拒绝。

产物（--out 目录）：
    master.mp4          成片（确定性目标：同输入同机重跑 md5 必须一致）
    synth_meta.json     每步 ffmpeg argv/退出码/stderr 摘要、master md5+sha256、
                        ffprobe 复测摘要、ffmpeg 版本（审计用，含绝对路径与时间戳，
                        不参与跨遍比对）
    md5.txt             确定性产物 md5 清单（md5sum 格式、仅相对文件名）——
                        跨遍比对的唯一载体（TASK_v4 §4 M1 验收 `diff md5.txt` 口径）
    <case_id>.ass       仅 ass 字幕模式（确定性产物，入 md5.txt）
    cp11_artifact.json  仅 case 声明 cp11 块时（checkpoint.schema v2.0 形态，
                        fingerprint 按规范化 JSON sha256 现算，同 make_fixture.py 口径）

确定性边界（诚实声明）：
- 同机 + 同 ffmpeg 版本 + threads=1 + 固定参数 → 字节级一致（本机 ffmpeg 6.1.1
  实测两遍 md5 一致，mov muxer 不写墙钟 creation_time）；跨机/跨版本不承诺
  （编码器版本差异），与 validate_cp11.py --self-check 口径一致。
- 确定性比对只覆盖 master.mp4（与 .ass）；synth_meta.json/cp11_artifact.json
  含时间戳与绝对路径，天然跨遍不同，不入比对。

退出码：0=合成成功；1=合成失败（ffmpeg 非零退出，meta 照写留痕）；
2=用法或读取错误（case 不可读/非 JSON 映射/声明字段非法/声明自洽性校验不过
——与兄弟 validate_cpN「判不了就不是门禁」同口径：宁可 2 不静默猜测）。
依赖：标准库 + 本机 ffmpeg/ffprobe（零外部模型、零网络）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME = "synth.py"
TOOL_VERSION = "1.0"
DEFAULT_SIZE = "360x640"
DEFAULT_FPS = 30

# 编码缺省（case 未声明时的兜底；三个回归 case 全部显式声明，缺省只为健壮）
DEFAULT_VIDEO = {"codec": "libx264", "preset": "veryfast", "crf": 28,
                 "pix_fmt": "yuv420p", "threads": 1}
DEFAULT_AUDIO_OUT = {"codec": "aac", "bitrate": "64k"}

# 声明自洽性容差（浮点时间轴等值比较；不放宽任何 ffmpeg 语义）
EPS_T = 1e-6

# drawtext 文本安全子集：ffmpeg 滤图对 ' : \ , ; [] % 有两层转义语义，
# 夹具只放行不含这些字符的可打印 ASCII（全量转义器归 M2，见模块头注）
DRAWTEXT_TEXT_FORBIDDEN = set("\\':;,[]%")
_DRAWTEXT_TEXT_RE = re.compile(r"^[\x20-\x7e]+$")

# drawtext x/y 内置预设（声明式，不透传任意表达式进滤图）
XY_PRESETS = {
    "left": "40", "center": "(w-text_w)/2", "right": "w-text_w-40",
    "top": "60", "middle": "(h-text_h)/2", "bottom": "h-text_h-60",
}

# loudnorm 归一目标缺省（EBU R128 广播响度；case 显式声明优先）
LOUDNORM_DEFAULT = {"I": -16.0, "TP": -1.5, "LRA": 11.0}
_LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


class CaseError(Exception):
    """case 声明非法/不可读/自洽性不过 → exit 2（用法类，宁 2 不猜）。"""


class SynthError(Exception):
    """ffmpeg 执行失败 → exit 1（合成失败，meta 照写留痕）。"""


# ---------------------------------------------------------------- 基础工具

def _num(x) -> bool:
    """数字（排除 bool——bool 是 int 子类，不能当时长/坐标用）。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt(x) -> str:
    return f"{float(x):g}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _md5_file(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tool_version_line(binname: str) -> str:
    """ffmpeg/ffprobe -version 首行（meta/evidence 留痕）。不可用时如实 'unknown'。"""
    try:
        out = subprocess.run([binname, "-version"], capture_output=True,
                             text=True, timeout=30, check=True)
        return (out.stdout.splitlines() or [""])[0].strip() or "unknown"
    except Exception:
        return "unknown"


def artifact_fingerprint(art: dict) -> str:
    """checkpoint.schema.json fingerprint 口径：工件身份 = 规范化 JSON 的 sha256，
    不含 fingerprint / upstream_refs 自身（同 make_fixture.py）。"""
    core = {k: v for k, v in art.items() if k not in ("fingerprint", "upstream_refs")}
    canon = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- case 声明校验

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise CaseError(msg)


def load_case(path: str) -> dict:
    """读 + 全量校验 case.json（声明非法 fail-fast，带字段路径的诚实报错）。"""
    p = Path(path)
    if not p.is_file():
        raise CaseError(f"case 文件不存在或不是文件: {p}")
    try:
        case = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CaseError(f"case 读取/解析失败 {p}: {e}")
    _require(isinstance(case, dict), "case 顶层不是 JSON 映射")

    cid = case.get("case_id")
    _require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", cid or ""),
             f"case_id 须匹配 [A-Za-z0-9_.-]+（实得 {cid!r}）")

    # ---- inputs：全部 ffmpeg lavfi 程序源（红线：零模型、零下载）----
    inputs = case.get("inputs")
    _require(isinstance(inputs, dict) and inputs, "inputs 须为非空映射")
    for name, spec in inputs.items():
        _require(isinstance(spec, dict), f"inputs.{name} 须为映射")
        _require(spec.get("kind") == "lavfi",
                 f"inputs.{name}.kind 只支持 \"lavfi\"（ffmpeg 内建程序源；实得 {spec.get('kind')!r}）")
        _require(isinstance(spec.get("source"), str) and spec["source"].strip(),
                 f"inputs.{name}.source 须为非空 lavfi 表达式")

    # ---- timeline ----
    tl = case.get("timeline")
    _require(isinstance(tl, dict), "timeline 缺失或非映射")
    size = tl.get("size", DEFAULT_SIZE)
    _require(isinstance(size, str) and re.fullmatch(r"(\d+)x(\d+)", size),
             f"timeline.size 须为 \"WxH\"（实得 {size!r}）")
    fps = tl.get("fps", DEFAULT_FPS)
    _require(_num(fps) and fps > 0, f"timeline.fps 须为正数（实得 {fps!r}）")
    dur = tl.get("duration_s")
    _require(_num(dur) and dur > 0, f"timeline.duration_s 须为正数（实得 {dur!r}）")
    mode = tl.get("mode")
    _require(mode in ("concat", "xfade"),
             f"timeline.mode 须为 \"concat\"|\"xfade\"（实得 {mode!r}）")
    shots = tl.get("shots")
    _require(isinstance(shots, list) and shots, "timeline.shots 须为非空数组")
    for i, sh in enumerate(shots):
        _require(isinstance(sh, dict), f"timeline.shots[{i}] 须为映射")
        _require(sh.get("input") in inputs,
                 f"timeline.shots[{i}].input={sh.get('input')!r} 不在 inputs 名册")
        _require(_num(sh.get("start")) and sh["start"] >= 0,
                 f"timeline.shots[{i}].start 须为非负数（实得 {sh.get('start')!r}）")
        _require(_num(sh.get("duration")) and sh["duration"] > 0,
                 f"timeline.shots[{i}].duration 须为正数（实得 {sh.get('duration')!r}）")

    if mode == "concat":
        # 硬切拼接语义：start 依序紧接（首 shot 从 0 起），末尾 == duration_s
        _require(abs(shots[0]["start"]) <= EPS_T,
                 f"concat 模式 shots[0].start 须为 0（实得 {_fmt(shots[0]['start'])}）")
        for i in range(1, len(shots)):
            expect = shots[i - 1]["start"] + shots[i - 1]["duration"]
            _require(abs(shots[i]["start"] - expect) <= EPS_T,
                     f"concat 模式 shots[{i}].start={_fmt(shots[i]['start'])} != "
                     f"前一镜 end={_fmt(expect)}（硬切拼接语义下时间轴不许有缝/叠）")
        tail = shots[-1]["start"] + shots[-1]["duration"]
        _require(abs(tail - dur) <= EPS_T,
                 f"concat 模式末镜 end={_fmt(tail)} != timeline.duration_s={_fmt(dur)}"
                 "（声明自相矛盾）")
    else:
        # xfade 语义：n 镜须 n-1 个过渡；next.start == prev.start+prev.duration-trans.duration
        trans = tl.get("transitions")
        _require(isinstance(shots, list) and len(shots) >= 2,
                 "xfade 模式 shots 须 ≥2 镜")
        _require(isinstance(trans, list) and len(trans) == len(shots) - 1,
                 f"xfade 模式 transitions 须为 {len(shots) - 1} 个（=镜数-1；实得 "
                 f"{len(trans) if isinstance(trans, list) else trans!r}）")
        for j, tr in enumerate(trans):
            _require(isinstance(tr, dict), f"timeline.transitions[{j}] 须为映射")
            _require(tr.get("after_shot") == j,
                     f"transitions[{j}].after_shot 须为 {j}（依序链式 xfade；实得 "
                     f"{tr.get('after_shot')!r}）")
            _require(isinstance(tr.get("type"), str) and tr["type"].strip(),
                     f"transitions[{j}].type 须为非空 xfade 过渡名（fade/wipeleft/…）")
            _require(_num(tr.get("duration")) and tr["duration"] > 0,
                     f"transitions[{j}].duration 须为正数（实得 {tr.get('duration')!r}）")
            expect = shots[j]["start"] + shots[j]["duration"] - tr["duration"]
            _require(abs(shots[j + 1]["start"] - expect) <= EPS_T,
                     f"xfade 链不一致：shots[{j + 1}].start={_fmt(shots[j + 1]['start'])} != "
                     f"shots[{j}].end-过渡时长={_fmt(expect)}（重叠区=过渡区，声明自洽性）")
            _require(shots[j]["duration"] >= tr["duration"] - EPS_T,
                     f"shots[{j}].duration < 过渡时长（xfade 无从展开）")
        tail = shots[-1]["start"] + shots[-1]["duration"]
        _require(abs(tail - dur) <= EPS_T,
                 f"xfade 模式末镜 end={_fmt(tail)} != timeline.duration_s={_fmt(dur)}")

    # ---- subtitles（可选）----
    subs = case.get("subtitles")
    if subs is not None:
        _require(isinstance(subs, dict), "subtitles 须为映射")
        smode = subs.get("mode")
        _require(smode in ("drawtext", "ass"),
                 f"subtitles.mode 须为 \"drawtext\"|\"ass\"（实得 {smode!r}）")
        if smode == "drawtext":
            items = subs.get("items")
            _require(isinstance(items, list) and items,
                     "subtitles.items 须为非空数组（drawtext 模式）")
            for i, it in enumerate(items):
                _require(isinstance(it, dict), f"subtitles.items[{i}] 须为映射")
                text = it.get("text")
                _require(isinstance(text, str) and text
                         and _DRAWTEXT_TEXT_RE.fullmatch(text)
                         and not (DRAWTEXT_TEXT_FORBIDDEN & set(text)),
                         f"subtitles.items[{i}].text 须为不含 {''.join(sorted(DRAWTEXT_TEXT_FORBIDDEN))} "
                         f"的可打印 ASCII（ffmpeg 滤图转义安全子集；实得 {text!r}）")
                for k in ("start", "end"):
                    _require(_num(it.get(k)) and 0 <= it[k] <= dur,
                             f"subtitles.items[{i}].{k} 须为 [0,{_fmt(dur)}] 内的数"
                             f"（实得 {it.get(k)!r}）")
                _require(it["end"] > it["start"],
                         f"subtitles.items[{i}].end 须 > start")
                for k in ("x", "y"):
                    _require(it.get(k) in XY_PRESETS,
                             f"subtitles.items[{i}].{k} 须为内置预设 "
                             f"{sorted(XY_PRESETS)} 之一（实得 {it.get(k)!r}）")
        else:
            _require(isinstance(subs.get("content"), str) and subs["content"].strip(),
                     "subtitles.content 须为非空 ASS 文本（ass 模式）")

    # ---- audio（可选）----
    aud = case.get("audio")
    if aud is not None:
        _require(isinstance(aud, dict), "audio 须为映射")
        _require(aud.get("kind") == "lavfi",
                 f"audio.kind 只支持 \"lavfi\"（实得 {aud.get('kind')!r}）")
        _require(isinstance(aud.get("source"), str) and aud["source"].strip(),
                 "audio.source 须为非空 lavfi 表达式")
        norm = aud.get("normalize")
        if norm is not None:
            _require(isinstance(norm, dict), "audio.normalize 须为映射")
            _require(norm.get("mode") == "loudnorm_two_pass",
                     f"audio.normalize.mode 只支持 \"loudnorm_two_pass\"（实得 {norm.get('mode')!r}）")
            for k in ("I", "TP", "LRA"):
                _require(_num(norm.get(k)), f"audio.normalize.{k} 须为数（实得 {norm.get(k)!r}）")

    # ---- output（可选，缺省兜底）----
    out = case.get("output")
    if out is not None:
        _require(isinstance(out, dict), "output 须为映射")
        v = out.get("video", {})
        _require(isinstance(v, dict), "output.video 须为映射")
        for k in ("codec", "preset", "pix_fmt"):
            if k in v:
                _require(isinstance(v[k], str) and v[k].strip(),
                         f"output.video.{k} 须为非空字符串")
        for k in ("crf", "threads"):
            if k in v:
                _require(_num(v[k]) and v[k] >= 0, f"output.video.{k} 须为非负数")
        a = out.get("audio", {})
        _require(isinstance(a, dict), "output.audio 须为映射")
        for k in ("codec", "bitrate"):
            if k in a:
                _require(isinstance(a[k], str) and a[k].strip(),
                         f"output.audio.{k} 须为非空字符串")

    # ---- cp11 块（可选）----
    cp11 = case.get("cp11")
    if cp11 is not None:
        _require(isinstance(cp11, dict), "cp11 须为映射")
        _require(isinstance(cp11.get("work_id"), str) and cp11["work_id"],
                 "cp11.work_id 须为非空字符串")
        sbc = cp11.get("storyboard_shot_count")
        _require(_num(sbc) and sbc >= 1 and float(sbc).is_integer(),
                 "cp11.storyboard_shot_count 须为 ≥1 整数")
        _require(sbc == len(shots),
                 f"cp11.storyboard_shot_count={sbc} != 实际镜数 {len(shots)}"
                 "（切镜数==分镜表镜头数，声明侧先自证——cp11.gate.shot_count_match）")
        kc = cp11.get("known_cuts")
        _require(isinstance(kc, list) and all(_num(x) and x >= 0 for x in kc),
                 "cp11.known_cuts 须为非负数数组")
        if mode == "concat":
            implied = [round(shots[i]["start"], 6) for i in range(1, len(shots))]
            declared = sorted(round(float(x), 6) for x in kc)
            _require(declared == implied,
                     f"cp11.known_cuts={declared} != 时间线隐含硬切点 {implied}"
                     "（concat 拼接缝=累计 start；登记册不许与时间线说两套话，"
                     "TASK_v4 M1-W5 known_cuts 铁律声明侧）")
            _require(cp11.get("all_cuts_registered") is True,
                     "cp11.all_cuts_registered 须为 true（声明自认未齐=拒收）")
        else:
            _require(kc == [],
                     "xfade 模式无硬切点（过渡≠硬切），cp11.known_cuts 登记语义不适用，"
                     "须为空数组；且本合成器不为 xfade 产 cp11_artifact（CP11 门禁 "
                     "known_cuts 铁律针对硬切拼接，空登记册过不了校验器——如需挂载归 M2 放行）")
        ups = cp11.get("upstream_refs")
        _require(isinstance(ups, list) and all(isinstance(u, dict) and u.get("cp_id")
                                               for u in ups),
                 "cp11.upstream_refs 须为 [{cp_id,fingerprint}, …] 数组"
                 "（字幕≠台词道挂载点须含 cp10）")

    return case


# ---------------------------------------------------------------- 滤图构建

def build_concat_chain(case: dict, vidx: list[int], aidx: int | None) -> tuple[str, str, str]:
    """concat 模式滤图。返回 (filter_complex, vlabel, alabel)。链形同
    cp11/make_fixture.py（trim→setpts→concat），字幕道缀在 concat 后。"""
    shots = case["timeline"]["shots"]
    parts = []
    for i, sh in enumerate(shots):
        parts.append(f"[{vidx[i]}:v]trim=0:{_fmt(sh['duration'])},"
                     f"setpts=PTS-STARTPTS[s{i}]")
    parts.append("".join(f"[s{i}]" for i in range(len(shots)))
                 + f"concat=n={len(shots)}:v=1:a=0[vc]")
    sub_filter, vout = subtitle_chain(case, "[vc]")
    if sub_filter:
        parts.append(sub_filter)
    if aidx is not None:
        parts.append(audio_chain(case, aidx))
    return ";".join(parts), vout, ("[aout]" if aidx is not None else "")


def build_xfade_chain(case: dict, vidx: list[int], aidx: int | None) -> tuple[str, str, str]:
    """xfade 模式滤图：各镜 format+settb 归一后依过渡链式叠加；
    offset = 后镜 start（重叠区即过渡区，声明校验已保证自洽）。"""
    shots = case["timeline"]["shots"]
    trans = case["timeline"]["transitions"]
    parts = []
    for i in range(len(shots)):
        parts.append(f"[{vidx[i]}:v]format=yuv420p,settb=AVTB[v{i}]")
    cur = "[v0]"
    for j, tr in enumerate(trans):
        nxt = f"[x{j + 1}]" if j + 1 < len(trans) else "[xc]"
        parts.append(f"{cur}[v{j + 1}]xfade=transition={tr['type']}"
                     f":duration={_fmt(tr['duration'])}:offset={_fmt(shots[j + 1]['start'])}{nxt}")
        cur = nxt
    sub_filter, vout = subtitle_chain(case, "[xc]")
    if sub_filter:
        parts.append(sub_filter)
    if aidx is not None:
        parts.append(audio_chain(case, aidx))
    return ";".join(parts), vout, ("[aout]" if aidx is not None else "")


def subtitle_chain(case: dict, vlabel: str) -> tuple[str | None, str]:
    """字幕道（drawtext 项 或 ass 烧录），缀在时间线滤镜之后。
    返回 (滤镜串或 None, 出标签)；None=无字幕直通。"""
    subs = case.get("subtitles")
    if not subs:
        return None, vlabel
    if subs["mode"] == "drawtext":
        chain = vlabel          # 段首=输入标签（前段 concat/xfade 产出），标签紧贴滤镜
        for it in subs["items"]:
            if chain != vlabel:
                chain += ","     # 多条 drawtext 同链串联
            opts = [
                f"font={it.get('font', 'DejaVu Sans')}",
                f"fontsize={_fmt(it.get('fontsize', 30))}",
                f"fontcolor={it.get('fontcolor', 'white')}",
                f"x={XY_PRESETS[it['x']]}",
                f"y={XY_PRESETS[it['y']]}",
                f"text={it['text']}",
                f"enable='between(t,{_fmt(it['start'])},{_fmt(it['end'])})'",
            ]
            if it.get("box"):
                opts.insert(4, f"box=1:boxcolor={it.get('boxcolor', 'black@0.5')}")
            chain += f"drawtext={':'.join(opts)}"
        return chain + "[v]", "[v]"
    return f"{vlabel}ass={case['_ass_basename']}[v]", "[v]"


def audio_chain(case: dict, aidx: int) -> str:
    """音轨链：atrim 对齐时间线 →（声明时）loudnorm 两遍 linear 归一 → 复采样。
    loudnorm 内部升到 192kHz 处理，aresample 回源率，aac 按原采样率编码。"""
    aud = case["audio"]
    dur = case["timeline"]["duration_s"]
    chain = f"[{aidx}:a]atrim=0:{_fmt(dur)},asetpts=PTS-STARTPTS"
    norm = aud.get("normalize")
    if norm:
        m = case["_loudnorm_measured"]
        chain += (f",loudnorm=I={_fmt(norm['I'])}:TP={_fmt(norm['TP'])}"
                  f":LRA={_fmt(norm['LRA'])}"
                  f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                  f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                  f":offset={m['target_offset']}:linear=true")
        chain += ",aresample=44100"
    return chain + "[aout]"


# ---------------------------------------------------------------- 执行步骤

def run_ffmpeg(argv: list[str], cwd: Path, step_name: str,
               steps: list[dict], timeout: int = 600) -> subprocess.CompletedProcess:
    """跑一步 ffmpeg，把 argv/rc/stderr 尾巴如实记入 steps。失败抛 SynthError。"""
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(cwd))
    steps.append({"name": step_name, "kind": "ffmpeg", "argv": argv,
                  "rc": proc.returncode,
                  "stderr_tail": proc.stderr.strip()[-800:]})
    if proc.returncode != 0:
        raise SynthError(f"步骤 {step_name} ffmpeg 失败 rc={proc.returncode}: "
                         f"{proc.stderr.strip()[-500:]}")
    return proc


def loudnorm_measure(case: dict, out_dir: Path, steps: list[dict],
                     ffmpeg: str) -> dict:
    """loudnorm 第一遍（测量）：解析 stderr 末尾 JSON 块。解析失败 = 合成失败
    （宁可失败不静默跳过归一）。"""
    aud = case["audio"]
    norm = aud["normalize"]
    dur = case["timeline"]["duration_s"]
    af = (f"loudnorm=I={_fmt(norm['I'])}:TP={_fmt(norm['TP'])}"
          f":LRA={_fmt(norm['LRA'])}:print_format=json")
    argv = [ffmpeg, "-hide_banner", "-nostats", "-loglevel", "info",
            "-f", "lavfi", "-i", aud["source"], "-t", _fmt(dur),
            "-af", af, "-f", "null", "-"]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    steps.append({"name": "loudnorm_measure", "kind": "ffmpeg", "argv": argv,
                  "rc": proc.returncode, "stderr_tail": proc.stderr.strip()[-800:]})
    if proc.returncode != 0:
        raise SynthError(f"loudnorm 测量遍失败 rc={proc.returncode}: "
                         f"{proc.stderr.strip()[-300:]}")
    blocks = _LOUDNORM_JSON_RE.findall(proc.stderr)
    if not blocks:
        raise SynthError("loudnorm 测量遍 stderr 无 JSON 块（print_format=json 未复现）")
    try:
        m = json.loads(blocks[-1])
        for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            float(m[k])  # 值必须是可解析数
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise SynthError(f"loudnorm 测量 JSON 解析失败: {e}（实得 {blocks[-1][:200]!r}）")
    return m


def write_cp11_artifact(case: dict, master: Path) -> dict:
    """按 case.cp11 块产 CP11 工件（checkpoint.schema v2.0 形态，同
    cp11/make_fixture.py build_artifact 口径；master_asset.fingerprint=实测 sha256，
    produced_at=真实时刻——字节可复现承诺在 mp4 的 md5，不在本派生工件）。"""
    c11 = case["cp11"]
    tl = case["timeline"]
    w, h = (int(x) for x in tl["size"].split("x"))
    v = {**DEFAULT_VIDEO, **(case.get("output", {}).get("video") or {})}
    a = {**DEFAULT_AUDIO_OUT, **(case.get("output", {}).get("audio") or {})}
    art = {
        "schema_version": "2.0",
        "cp_id": "cp11",
        "artifact_type": "composite",
        "fingerprint": "",
        "produced_by": TOOL_NAME,
        "produced_at": _now_iso(),
        "upstream_refs": c11["upstream_refs"],
        "status": "gated",
        "gate": {
            "type": "hard_verify",
            "params_ref": "judges.J6_detectors_v2.rule_params.known_cuts_tol_s",
            "result": "pass",
            "note": (f"{len(c11['known_cuts'])} 个拼接硬切点 "
                     f"({_fmt_list(c11['known_cuts'])}s) 全部登记 known_cuts 白名单，"
                     "容差沿 judges.J6_detectors_v2.rule_params.known_cuts_tol_s；"
                     "实测由 validate_cp11.py --probe 复核。"),
        },
        "aux_gates": [
            {"type": "hard_verify", "params_ref": "cp11.gate.duration_tol_s",
             "result": "pass",
             "note": (f"成片声明 {tl['duration_s']:g}s，±cp11.gate.duration_tol_s 内"
                      "（ffprobe 实测由校验器复核）。")},
            {"type": "hard_verify", "params_ref": "cp11.gate.shot_count_match",
             "result": "pass",
             "note": (f"master_shot_segments {len(tl['shots'])} == "
                      f"storyboard_shot_count {c11['storyboard_shot_count']}"
                      "（声明侧；实测切点数+1 由校验器复核）。")},
        ],
        "payload": {
            "work_id": c11["work_id"],
            "master_asset": {
                "kind": "clip",
                "fingerprint": _sha256_file(master),
                "path": str(master.resolve()),
            },
            "container": "mp4",
            "video_codec": "h264" if "264" in v["codec"] else v["codec"],
            "audio_codec": a["codec"],
            "width": w,
            "height": h,
            "duration_s": tl["duration_s"],
            "master_shot_segments": len(tl["shots"]),
            "storyboard_shot_count": c11["storyboard_shot_count"],
            "known_cuts": c11["known_cuts"],
            "all_cuts_registered": c11["all_cuts_registered"],
            "black_ratio": 0.0,
        },
        "notes": (f"CP11 像素级回归成片工件（{case['case_id']}）：ffmpeg lavfi 程序源"
                  "确定性合成（synth.py，零模型零下载），同输入重跑 master.mp4 md5 一致"
                  "（md5.txt 口径）。upstream_refs 为夹具占位指纹（回归夹具无真实上游），"
                  "cp10 在册以满足字幕≠台词道挂载点校验。"),
    }
    art["fingerprint"] = artifact_fingerprint(art)
    return art


def _fmt_list(xs: list) -> str:
    return "[" + ",".join(_fmt(x) for x in xs) + "]"


# ---------------------------------------------------------------- 主流程

def synth(case_path: str, out_dir: Path) -> tuple[dict, int]:
    """执行合成。返回 (stdout 摘要 dict, exit 码)。meta 无论成败照写（审计留痕）。"""
    steps: list[dict] = []
    case = load_case(case_path)          # 声明非法 → CaseError → exit 2（meta 免写：
    case_sha = _sha256_file(Path(case_path))  #  case 本身没立住，无可审计产物）
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    summary: dict = {"tool": TOOL_NAME, "case_id": case["case_id"],
                     "out_dir": str(out_dir), "verdict": "failed"}

    try:
        tl = case["timeline"]
        dur = tl["duration_s"]

        # ---- 步骤 A：ass 字幕落盘（确定性产物，入 md5.txt）----
        ass_name = None
        if (case.get("subtitles") or {}).get("mode") == "ass":
            ass_name = f"{case['case_id']}.ass"
            case["_ass_basename"] = ass_name   # ass= 滤器吃 cwd=out 相对名，免路径转义
            ass_path = out_dir / ass_name
            ass_path.write_text(case["subtitles"]["content"], encoding="utf-8", newline="\n")
            steps.append({"name": "ass_write", "kind": "file_write",
                          "path": str(ass_path), "sha256": _sha256_file(ass_path)})

        # ---- 步骤 B：loudnorm 测量遍（声明归一时）----
        if (case.get("audio") or {}).get("normalize"):
            case["_loudnorm_measured"] = loudnorm_measure(case, out_dir, steps, ffmpeg)

        # ---- 步骤 C：主编码（时间线 + 字幕 + 音轨 → master.mp4）----
        shots = tl["shots"]
        vidx = list(range(len(shots)))
        aidx = len(shots) if case.get("audio") else None
        argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-y"]
        for i, sh in enumerate(shots):
            argv += ["-f", "lavfi", "-i", case["inputs"][sh["input"]]["source"]]
        if aidx is not None:
            argv += ["-f", "lavfi", "-i", case["audio"]["source"]]
        if tl["mode"] == "concat":
            fc, vlabel, alabel = build_concat_chain(case, vidx, aidx)
        else:
            fc, vlabel, alabel = build_xfade_chain(case, vidx, aidx)
        argv += ["-filter_complex", fc, "-map", vlabel]
        if alabel:
            argv += ["-map", alabel]
        ov = {**DEFAULT_VIDEO, **(case.get("output", {}).get("video") or {})}
        oa = {**DEFAULT_AUDIO_OUT, **(case.get("output", {}).get("audio") or {})}
        argv += ["-c:v", ov["codec"], "-preset", ov["preset"], "-crf", _fmt(ov["crf"]),
                 "-pix_fmt", ov["pix_fmt"], "-threads", str(int(ov["threads"]))]
        if aidx is not None:
            argv += ["-c:a", oa["codec"], "-b:a", oa["bitrate"]]
        argv += ["-t", _fmt(dur), "master.mp4"]
        run_ffmpeg(argv, out_dir, "encode_master", steps)

        master = out_dir / "master.mp4"
        master_md5, master_sha = _md5_file(master), _sha256_file(master)

        # ---- 步骤 D：ffprobe 复测（时长/分辨率/双流编解码入 meta）----
        probe = {"ffprobe": "skipped"}
        try:
            pr = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(master)],
                capture_output=True, text=True, timeout=120, check=True)
            pj = json.loads(pr.stdout)
            fmt = pj.get("format") or {}
            vs = next((s for s in pj.get("streams") or []
                       if s.get("codec_type") == "video"), {})
            as_ = next((s for s in pj.get("streams") or []
                        if s.get("codec_type") == "audio"), {})
            probe = {"duration_s": float(fmt.get("duration", 0)),
                     "width": vs.get("width"), "height": vs.get("height"),
                     "vcodec": vs.get("codec_name"), "acodec": as_.get("codec_name"),
                     "container": fmt.get("format_name")}
        except Exception as e:                       # noqa: BLE001 —— 复测失败只降级，
            probe = {"ffprobe": f"failed: {e}"}      # 不推翻已成功的编码事实

        # ---- 步骤 E：md5.txt（确定性产物清单，md5sum 格式，仅相对名）----
        det_files = ["master.mp4"] + ([ass_name] if ass_name else [])
        lines = "".join(f"{_md5_file(out_dir / f)}  {f}\n"
                        for f in sorted(det_files))
        (out_dir / "md5.txt").write_text(lines, encoding="utf-8")

        # ---- 步骤 F：cp11 工件（case 声明 cp11 块时；concat 专属，校验已挡 xfade）----
        cp11_path = None
        if case.get("cp11"):
            art = write_cp11_artifact(case, master)
            cp11_path = out_dir / "cp11_artifact.json"
            cp11_path.write_text(json.dumps(art, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")

        meta = {
            "tool": TOOL_NAME, "synth_version": TOOL_VERSION,
            "case_path": str(Path(case_path).resolve()), "case_id": case["case_id"],
            "case_sha256": case_sha,
            "generated_at": _now_iso(),
            "ffmpeg": tool_version_line("ffmpeg"), "ffprobe": tool_version_line("ffprobe"),
            "mode": tl["mode"], "timeline": tl,
            "determinism_note": ("同输入同机重跑 master.mp4 md5 必须一致（threads=1 钉死、"
                                 "固定参数、lavfi 程序源零墙钟注入；比对只覆盖 md5.txt 所列"
                                 "确定性产物——本 meta 与 cp11_artifact.json 含时间戳/绝对"
                                 "路径，天然跨遍不同，不入比对）"),
            "steps": steps,
            "master": {"path": "master.mp4", "md5": master_md5, "sha256": master_sha,
                       "bytes": master.stat().st_size},
            "ffprobe_summary": probe,
            "md5_file": "md5.txt",
            "cp11_artifact": (cp11_path.name if cp11_path else None),
        }
        meta_path = out_dir / "synth_meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

        summary.update({"verdict": "ok", "master_md5": master_md5,
                        "master_sha256": master_sha, "master_bytes": meta["master"]["bytes"],
                        "md5_file": str(meta_path.parent / "md5.txt"),
                        "cp11_artifact": str(cp11_path) if cp11_path else None,
                        "ffprobe_summary": probe, "n_steps": len(steps),
                        "synth_meta": str(meta_path)})
        return summary, 0

    except SynthError as e:
        # ffmpeg 失败：meta 照写留痕（steps 里已有 rc/stderr），exit 1
        (out_dir / "synth_meta.json").write_text(json.dumps(
            {**summary, "generated_at": _now_iso(), "case_sha256": case_sha,
             "steps": steps, "error": str(e)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        summary["error"] = str(e)
        return summary, 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CP11 合成层确定性合成器：--case 声明式时间线 → master.mp4 + "
                    "synth_meta.json + md5.txt（同输入同机重跑 md5 必须一致；"
                    "exit 0=ok / 1=合成失败 / 2=用法或声明错误）")
    ap.add_argument("--case", required=True, help="case.json（声明式：lavfi 素材 + "
                                                   "timeline.shots + 字幕轨 + 输出参数）")
    ap.add_argument("--out", required=True, help="产物目录（不存在则建；master.mp4 同名覆盖）")
    args = ap.parse_args(argv)

    try:
        summary, rc = synth(args.case, Path(args.out))
    except CaseError as e:
        print(json.dumps({"tool": TOOL_NAME, "verdict": "error", "error": str(e)},
                         ensure_ascii=False, indent=2))
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if rc != 0:
        print(f"ERROR: {summary.get('error')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
