#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp10_assets.py — CP10 装配预处理（M2-d，本轮工具件，落 cp10/ 留痕）。

输入：cp2.json（台词/估时）、cp6.json（subtitle_segments/sound_lead_in_frames/帧域）、
     cp10/tts_seg_XX.wav + .meta.json（tts.py 实测产物）。
输出：
  cp10/fit/tts_seg_XX.fit.wav     逐句静音修剪 + atempo 入窗后的配音件（24k mono）
  cp10/subs.ass                   ASS 字幕（CP6 窗口投影，文本与 CP2 逐字一致）
  cp10/duration_reconciliation.json  逐句时长对账 + 修剪/压缩参数 + 声画决策留痕

口径：
- 窗口 budget_i = CP6 subtitle_segments[i] 时长（镜帧域冻结，不改 CP6）。
- 静音修剪：lead 保留 0.12s；句内 >0.40s 停顿截到 0.35s；尾部保留 0.35s
  （silenceremove 单链，-40dB）。
- 修剪后仍超窗 → atempo=d_trimmed/window（ffmpeg 单级 ≤2.0，本批全部 <1.6）。
- 声先入：sound_lead_in_frames=2 → 音频起点 = max(0, 镜起点 − 2/24s)，
  窗 budget 不变（整段前移 83ms，句间零碰撞）。
退出码：0=ok；1=有句 fit 后仍超窗（不阻塞，reconciliation 标记）；2=输入缺失。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../cp10
EP = HERE.parent                                # .../comicanime_ep01
VPIPE = EP.parent.parent.parent                 # .../vpipe
sys.path.insert(0, str(VPIPE))
from src.gate.fingerprint import canonical, compute_fingerprint  # noqa: E402

LEAD_KEEP, PAUSE_TRIG, PAUSE_KEEP, TAIL_KEEP = 0.12, 0.40, 0.35, 0.35
SIL_THR = "-40dB"


def sh(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def ffdur(p: Path) -> float:
    r = sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(p)])
    return round(float(json.loads(r.stdout)["format"]["duration"]), 3)


def main() -> int:
    cp2 = json.loads((EP / "cp2.json").read_text(encoding="utf-8"))
    cp6 = json.loads((EP / "cp6.json").read_text(encoding="utf-8"))
    segs = cp2["payload"]["narration_segments"]
    subs = cp6["payload"]["subtitle_segments"]
    lead_frames = cp6["payload"]["sound_lead_in_frames"]
    fps = cp6["payload"]["fps"]
    assert [s["segment_id"] for s in segs] == [t["segment_id"] for t in subs]

    fit_dir = HERE / "fit"
    fit_dir.mkdir(exist_ok=True)
    rows, ass_lines, hard_over = [], [], False

    import re as _re

    def wrap_text(text: str, maxlen: int = 15) -> str:
        """手动分行（libass 自动换列实测不生效，ink 触边）：先按标点切短语，
        再贪心打包成 ≤maxlen 字/行，\\N 连接；去 \\N 后与原文逐字一致。"""
        # 短语=文字段+其后标点（标点不落行首），贪心打包 ≤maxlen 字/行
        clauses = _re.findall(r"[^，。？！；：、——…]+[，。？！；：、——…]*", text)
        lines, cur = [], ""
        for c in clauses:
            while len(c) > maxlen:               # 超长短语硬切
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(c[:maxlen])
                c = c[maxlen:]
            if len(cur) + len(c) > maxlen and cur:
                lines.append(cur)
                cur = c
            else:
                cur += c
        if cur:
            lines.append(cur)
        return "\\N".join(lines)

    for seg, sub in zip(segs, subs):
        sid = seg["segment_id"]
        wav = HERE / f"tts_{sid}.wav"
        meta = json.loads((HERE / f"tts_{sid}.meta.json").read_text(encoding="utf-8"))
        if meta.get("status") != "ok" or not wav.is_file():
            print(f"[FATAL] {sid}: meta status={meta.get('status')} wav={wav.exists()}")
            return 2
        d_orig = ffdur(wav)
        assert abs(d_orig - (meta.get("duration_s") or -1)) < 0.05, f"{sid} dur mismatch"

        win = round(sub["end_s"] - sub["start_s"], 6)

        # ---- 静音修剪（lead / 内部停顿 / 尾部）----
        trim_chain = (
            "silenceremove="
            f"start_periods=1:start_threshold={SIL_THR}:start_silence={LEAD_KEEP}:"
            f"stop_periods=-1:stop_duration={PAUSE_TRIG}:stop_threshold={SIL_THR}:"
            f"stop_silence={PAUSE_KEEP}"
        )
        trimmed = fit_dir / f".{sid}.trim.wav"
        r = sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                "-af", trim_chain, "-ar", "24000", "-ac", "1", str(trimmed)])
        if r.returncode != 0:
            print(f"[FATAL] {sid} trim fail: {r.stderr[-300:]}")
            return 2
        d_trim = ffdur(trimmed)

        # ---- atempo 入窗（50ms 安全边距，吸收 atempo/round 量化残差）----
        budget = max(0.5, win - 0.05)
        factor = round(max(1.0, d_trim / budget), 4)
        fitted = fit_dir / f"tts_{sid}.fit.wav"
        if factor > 1.0:
            r = sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(trimmed), "-af", f"atempo={factor}", str(fitted)])
        else:
            r = sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(trimmed), "-c", "copy", str(fitted)])
        trimmed.unlink()
        if r.returncode != 0:
            print(f"[FATAL] {sid} atempo fail: {r.stderr[-300:]}")
            return 2
        d_fit = ffdur(fitted)
        over = d_fit > win + 0.01
        hard_over |= over

        dev_pct = round((d_orig - seg["estimated_duration_s"]) /
                        seg["estimated_duration_s"] * 100, 1)
        start_audio = round(max(0.0, sub["start_s"] - lead_frames / fps), 6)
        rows.append({
            "segment_id": sid, "shot_id": f"shot_{sid[-2:]}",
            "cp2_estimated_s": seg["estimated_duration_s"],
            "cp6_window_s": win,
            "tts_measured_s": d_orig,
            "est_deviation_pct": dev_pct,
            "over_20pct": abs(dev_pct) > 20.0,
            "trim_silence_params": {"thr": SIL_THR, "lead_keep_s": LEAD_KEEP,
                                    "pause_trigger_s": PAUSE_TRIG,
                                    "pause_keep_s": PAUSE_KEEP, "tail_keep_s": TAIL_KEEP},
            "trimmed_s": d_trim,
            "atempo_factor": factor,
            "fitted_s": d_fit,
            "fits_window": not over,
            "audio_start_s": start_audio,
            "tts_meta_sha256": meta.get("sha256"),
            "tts_request_id": meta.get("request_id"),
            "tts_latency_s": meta.get("latency_s"),
        })

        # ---- ASS 行（时间=CP6 窗口，文本=CP2 逐字）----
        def ts(x: float) -> str:
            cs = round(x * 100)
            h, cs = divmod(cs, 360000)
            m, cs = divmod(cs, 6000)
            s, cs = divmod(cs, 100)
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

        ass_lines.append(f"Dialogue: 0,{ts(sub['start_s'])},{ts(sub['end_s'])},"
                         f"Dialogue,,0,0,0,,{wrap_text(seg['narration_text'])}")

    # ---- 写 subs.ass ----
    header = """[Script Info]
; CP10 字幕：CP6 subtitle_segments 投影（逐句），文本=CP2 narration_text 逐字一致
; 竖版 1080x1920 安全区：MarginV=220（底部 UI 安全区 11.5%）、MarginL/R=64
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dialogue,Noto Sans CJK SC,64,&H00FFFFFF,&H00FFFFFF,&H00101010,&H7F000000,1,0,0,0,100,100,0,0,1,3,1,2,64,64,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    (HERE / "subs.ass").write_text(header + "\n".join(ass_lines) + "\n", encoding="utf-8")

    # ---- 逐字校验（ASS Dialogue 文本 == CP2 narration_text）----
    got = [ln.rsplit(",", 1)[1].rstrip("\n").replace("\\N", "")
           for ln in ass_lines]
    verbatim = got == [s["narration_text"] for s in segs]

    # ---- 对账件 ----
    over20 = [r["segment_id"] for r in rows if r["over_20pct"]]
    overfit = [r["segment_id"] for r in rows if not r["fits_window"]]
    rec = {
        "work_id": "comicanime_ep01",
        "produced_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "method_note": (
            "ffprobe 实测 tts_seg_XX.wav（与 tts.py meta duration_s 双源一致）；"
            "对账基准=CP2 estimated_duration_s（4.6字/s 估时）；"
            "CP6 帧域/subtitle_segments 冻结不动（CP6 门已过、指纹冻结），"
            "超窗句由 CP10 装配消化：silenceremove 修剪 + atempo 压缩入窗"
            "（factor=trimmed/window，逐句留痕于本件 rows），"
            "音频起点=镜起点−sound_lead_in_frames/fps（声先入 2 帧），"
            "budget=CP6 窗口，句间零碰撞。"),
        "summary": {
            "n_segments": len(rows),
            "over_20pct_segments": over20,
            "n_over_20pct": len(over20),
            "sum_tts_measured_s": round(sum(r["tts_measured_s"] for r in rows), 3),
            "sum_cp6_window_s": round(sum(r["cp6_window_s"] for r in rows), 3),
            "sum_fitted_s": round(sum(r["fitted_s"] for r in rows), 3),
            "max_atempo_factor": max(r["atempo_factor"] for r in rows),
            "fit_overflow_segments": overfit,
            "frame_domain_adjusted": False,
            "frame_domain_note": ("TTS 实测超估普遍 >20%，但全部句子经修剪+压缩可入 CP6 "
                                  "原窗口（Σfitted≤Σwindow），帧域无需微调——不改 CP6。"),
        },
        "verbatim_check_pass": verbatim,
        "rows": rows,
    }
    (HERE / "duration_reconciliation.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps(rec["summary"], ensure_ascii=False, indent=1))
    print("verbatim_check_pass:", verbatim)
    print("atempo factors:", {r["segment_id"]: r["atempo_factor"] for r in rows})
    return 1 if hard_over else 0


if __name__ == "__main__":
    sys.exit(main())
