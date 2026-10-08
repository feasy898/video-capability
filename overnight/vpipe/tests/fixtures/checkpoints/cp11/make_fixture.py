#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_fixture.py — CP11 校验器测试夹具生成器（tests/fixtures/checkpoints/cp11/）。

M3 库存（2 pass + 3 fail，全部 ffmpeg 内建 lavfi 源，零模型调用——红线：测试片必须
ffmpeg 程序生成；mp4 一律不入 git（见同目录 .gitignore），本脚本即唯一权威生成方式）：

    master_9s.mp4                      主测试片：9s / 360x640 / 30fps / h264+aac，
                                       4 段程序源拼接（smptebars→rgbtestsrc→testsrc2→
                                       灰底），硬切点恰在 2.5 / 5.0 / 7.5s
        pass/cp11_fixture.json             3 切点全登记 → --probe 判 pass（exit 0）
        fail/cp11_fixture_missing_cut.json 故意漏登记 7.5s（known_cuts=[2.5,5.0]，
                                           all_cuts_registered 仍谎报 true——TASK_v4
                                           M1-W5 要抓的「声明完备、实测漏登记」形态）
                                           → --probe fail（known_cuts_registered）；
                                             无 --probe 也 fail（cuts_segments_coherence：
                                             2 点 != 段数 4 - 1）
    master_black_9s.mp4                黑场超限片：全黑 9s，仅 4.5s 处嵌 1 帧白板作
                                       换本锚点（known_cuts 非空铁律与切镜数道需要
                                       可复现实测切点；纯全黑无可测切点会让切镜数道
                                       附带误伤、判因不干净）。blackdetect 实测黑场
                                       占比 ≈0.99 > l0_preflight.black_frame_ratio_max=0.50
        fail/cp11_fixture_black_overrun.json
                                           声明侧自认 pass（black_ratio 谎报 0.0）
                                           → --probe fail（black_ratio_cradle 独家裁决；
                                             black_ratio 声明侧只有 warn 不否决，
                                             故无 --probe 时声明道全过——黑场是实测道）
    master_12s.mp4                     时长超差片：实际 12s / 360x640 / 30fps，
                                       4 段拼接（rgbtestsrc→testsrc2→灰底→smptebars，
                                       源序与主片错开保证三处切点场景分余量），
                                       硬切点 3.0 / 6.0 / 9.0s
        fail/cp11_fixture_duration_overrun.json
                                           声明 duration_s=10s（偏差 2s >
                                           cp11.gate.duration_tol_s=1s）
                                           → --probe fail（duration_tol 独家裁决；
                                             无 --probe 时声明道全过——时长是
                                             ffprobe 实测道）
    master_8s_alt.mp4                  参数错开合规片：8s / 320x240 横版 / 24fps，
                                       smptehdbars/testsrc 两内建源交替成 4 段
                                       （2 段源 + 3 硬切点 2.0 / 4.0 / 6.0 全登记）；
                                       分辨率/帧率/时长/切点与主 pass 全错开，
                                       证明门禁不吃主夹具参数特例
        pass/cp11_fixture_alt_format.json  → --probe 判 pass（exit 0）

确定性：编码命令固定（本机 ffmpeg 6.1.1 实测二遍 md5 一致），工件 produced_at
固定常量、fingerprint=按 checkpoint.schema.json「payload 规范化 JSON 的 sha256
（不含 fingerprint/upstream_refs 自身）」现算——重跑本脚本字节级复现全部
4 个 mp4 与 5 份工件（master_9s.mp4 与既有两份工件字节不变）。

用法：python3 make_fixture.py [--out-dir DIR]   （缺省=脚本所在目录）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

PRODUCED_AT = "2026-10-08T00:00:00Z"   # 固定常量：夹具字节级可复现
FIX_DIR_REL = "tests/fixtures/checkpoints/cp11"  # 相对 overnight/vpipe 根

# 每段产出帧数：'0:DUR' 秒窗 = ceil(DUR*rate)（帧 k/rate < DUR）；帧窗 = end-start。
# guard 用它把「段窗累计 == 总帧数 == total_s*rate」钉死，防切点漂移。


def seg_frames(trim: str, rate: int) -> int:
    if trim.startswith("0:"):
        return math.ceil(float(trim[2:]) * rate - 1e-9)
    if trim.startswith("start_frame="):
        a, b = trim.split(":")
        return int(b.split("=")[1]) - int(a.split("=")[1])
    raise ValueError(f"不支持的 trim 表达式: {trim!r}")


# (lavfi 源串, trim 表达式)；总帧数 = 段帧数累计 = total_s * rate
SPECS: list[dict] = [
    {
        "key": "主夹具",
        "mp4": "master_9s.mp4",
        "size": (360, 640), "rate": 30, "total_s": 9.0, "frames": 270,
        "segments": [
            ("smptebars=size=360x640:rate=30", "0:2.5"),
            ("rgbtestsrc=size=360x640:rate=30", "0:2.5"),
            ("testsrc2=size=360x640:rate=30", "0:2.5"),
            ("color=c=0x404040:size=360x640:rate=30", "0:1.5"),
        ],
        "artifacts": [
            {
                "path": "pass/cp11_fixture.json",
                "work_id": "cp11_fixture",
                "known_cuts": [2.5, 5.0, 7.5], "all_registered": True,
                "duration_declared": 9.0, "black_ratio": 0.0,
                "gate_result": "pass",
                "gate_note": "3 个拼接硬切点（2.5/5.0/7.5s）全部登记 known_cuts 白名单，"
                             "容差 0.5s 沿 judges.J6_detectors_v2.rule_params.known_cuts_tol_s。",
                "aux_dur_note": "成片 9s vs 声明 9s，±1s 内（ffprobe 实测由校验器复核）。",
                "aux_shot_note": "实测切点数 3（+1 段 = 4）== master_shot_segments 4 "
                                 "== storyboard_shot_count 4。",
                "notes": "CP11 校验器夹具：ffmpeg 内建 lavfi 源程序拼接（smptebars/rgbtestsrc/testsrc2/"
                         "灰底），硬切点 2.5/5.0/7.5s。由 make_fixture.py 生成，重跑字节级复现。",
            },
            {
                "path": "fail/cp11_fixture_missing_cut.json",
                "work_id": "cp11_fixture",
                "known_cuts": [2.5, 5.0], "all_registered": True,   # 故意漏登记 7.5
                "duration_declared": 9.0, "black_ratio": 0.0,
                "gate_result": "pass",                              # 声明侧自认为 pass
                "gate_note": "（漏登记件）声明 2 个切点已登记——实测道应抓出 7.5s 未登记硬切点。",
                "aux_dur_note": "成片 9s vs 声明 9s，±1s 内（ffprobe 实测由校验器复核）。",
                "aux_shot_note": "（漏登记件）声明段数 4 与分镜表 4 一致——实测道应抓出登记册缺点。",
                "notes": "CP11 校验器夹具：ffmpeg 内建 lavfi 源程序拼接（smptebars/rgbtestsrc/testsrc2/"
                         "灰底），硬切点 2.5/5.0/7.5s。由 make_fixture.py 生成，重跑字节级复现。",
            },
        ],
    },
    {
        "key": "黑场超限片",
        "mp4": "master_black_9s.mp4",
        "size": (360, 640), "rate": 30, "total_s": 9.0, "frames": 270,
        "declared_segments": 2,   # 实测口径：切点簇 [4.5] +1 = 2 镜（白板是切点本体非镜头）
        "segments": [
            ("color=c=black:size=360x640:rate=30", "start_frame=0:end_frame=135"),   # 0→4.5s
            ("color=c=white:size=360x640:rate=30", "start_frame=135:end_frame=136"), # 1 帧换本锚 @4.5s
            ("color=c=black:size=360x640:rate=30", "start_frame=0:end_frame=134"),   # →9.0s
        ],
        "artifacts": [
            {
                "path": "fail/cp11_fixture_black_overrun.json",
                "work_id": "cp11_fixture_black",
                "known_cuts": [4.5], "all_registered": True,
                "duration_declared": 9.0, "black_ratio": 0.0,    # 声明谎称无黑场——实测道抓
                "gate_result": "pass",
                "gate_note": "（黑场超差件）唯一换本锚点切点 4.5s 已登记——主门自认 pass；"
                             "本件缺陷在黑场道，blackdetect 实测应抓黑场占比 ≈0.99 > "
                             "l0_preflight.black_frame_ratio_max=0.50。",
                "aux_dur_note": "成片 9s vs 声明 9s，±1s 内（ffprobe 实测由校验器复核）。",
                "aux_shot_note": "实测切点数 1（+1 段 = 2）== master_shot_segments 2 "
                                 "== storyboard_shot_count 2（切点=4.5s 处 1 帧白板换本锚）。",
                "notes": "黑场超限夹具：全黑 9s，仅 4.5s 处嵌 1 帧白板作换本锚点（known_cuts "
                         "非空铁律与切镜数道需要可复现实测切点，纯全黑无切点会让切镜数道附带"
                         "误伤、判因不干净）。blackdetect 实测黑场占比 ≈0.99 > 0.50 → --probe "
                         "fail 由黑场道独家裁决；无 --probe 时声明道全过（black_ratio 声明侧"
                         "仅 warn 不否决）。由 make_fixture.py 生成，重跑字节级复现。",
            },
        ],
    },
    {
        "key": "时长超差片",
        "mp4": "master_12s.mp4",
        "size": (360, 640), "rate": 30, "total_s": 12.0, "frames": 360,
        "segments": [   # 源序与主片错开：三处切点场景分实测 0.81/0.62/0.53，余量充足
            ("rgbtestsrc=size=360x640:rate=30", "0:3.0"),
            ("testsrc2=size=360x640:rate=30", "0:3.0"),
            ("color=c=0x404040:size=360x640:rate=30", "0:3.0"),
            ("smptebars=size=360x640:rate=30", "0:3.0"),
        ],
        "artifacts": [
            {
                "path": "fail/cp11_fixture_duration_overrun.json",
                "work_id": "cp11_fixture_dur",
                "known_cuts": [3.0, 6.0, 9.0], "all_registered": True,
                "duration_declared": 10.0, "black_ratio": 0.0,   # 声明 10s，实际 12s：dev 2s > 1s
                "gate_result": "pass",
                "gate_note": "（时长超差件）3 个拼接切点（3.0/6.0/9.0s）声明已登记——"
                             "主门自认 pass；本件缺陷在时长道。",
                "aux_dur_note": "（超差件）声明 10s——实测道应以 ffprobe 实测 12s 抓出偏差 "
                                "2s > cp11.gate.duration_tol_s=1s。",
                "aux_shot_note": "实测切点数 3（+1 段 = 4）== master_shot_segments 4 "
                                 "== storyboard_shot_count 4。",
                "notes": "时长超差夹具：成片实际 12s（工件声明 duration_s=10s，偏差 2s > "
                         "±1s 容差）。--probe fail 由时长道独家裁决；无 --probe 时声明道"
                         "全过（时长是 ffprobe 实测道）。由 make_fixture.py 生成，重跑字节级复现。",
            },
        ],
    },
    {
        "key": "参数错开合规片",
        "mp4": "master_8s_alt.mp4",
        "size": (320, 240), "rate": 24, "total_s": 8.0, "frames": 192,
        "segments": [   # 2 内建源交替 → 3 硬切点；切点场景分实测 0.93/0.95/0.93
            ("smptehdbars=size=320x240:rate=24", "0:2.0"),
            ("testsrc=size=320x240:rate=24", "0:2.0"),
            ("smptehdbars=size=320x240:rate=24", "0:2.0"),
            ("testsrc=size=320x240:rate=24", "0:2.0"),
        ],
        "artifacts": [
            {
                "path": "pass/cp11_fixture_alt_format.json",
                "work_id": "cp11_fixture_alt",
                "known_cuts": [2.0, 4.0, 6.0], "all_registered": True,
                "duration_declared": 8.0, "black_ratio": 0.0,
                "gate_result": "pass",
                "gate_note": "3 个拼接硬切点（2.0/4.0/6.0s）全部登记 known_cuts 白名单，"
                             "容差 0.5s 沿 judges.J6_detectors_v2.rule_params.known_cuts_tol_s；"
                             "参数组 320x240 横版 24fps 与主夹具 360x640 竖版 30fps 错开。",
                "aux_dur_note": "成片 8s vs 声明 8s，±1s 内（ffprobe 实测由校验器复核）。",
                "aux_shot_note": "实测切点数 3（+1 段 = 4）== master_shot_segments 4 "
                                 "== storyboard_shot_count 4。",
                "notes": "参数错开合规夹具：smptehdbars/testsrc 两内建源交替成 4 段、硬切点 "
                         "2.0/4.0/6.0 全登记；分辨率/帧率/时长/切点位置与主 pass 夹具全错开，"
                         "证明门禁不吃参数特例。由 make_fixture.py 生成，重跑字节级复现。",
            },
        ],
    },
]


def ffmpeg_cmd(segments: list[tuple[str, str]], total_s: float) -> list[str]:
    """4 输入 lavfi 源 → trim/setpts 对齐 → concat（v-only）+ anullsrc 音轨 atrim。
    与 v1 主夹具命令逐字节同构（master_9s.mp4 保持字节级复现）。"""
    n = len(segments)
    return (
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        + [arg for src, _ in segments for arg in ("-f", "lavfi", "-i", src)]
        + ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
        + [
            "-filter_complex",
            ";".join(
                f"[{i}:v]trim={trim},setpts=PTS-STARTPTS[{chr(97 + i)}]"
                for i, (_, trim) in enumerate(segments)
            )
            + ";" + "".join(f"[{chr(97 + i)}]" for i in range(n))
            + f"concat=n={n}:v=1:a=0[v];[{n}:a]atrim=0:{total_s},asetpts=PTS-STARTPTS[aud]",
            "-map", "[v]", "-map", "[aud]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
            "-t", str(total_s),
        ]
    )


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def artifact_fingerprint(art: dict) -> str:
    """checkpoint.schema.json fingerprint 定义：工件身份 = 规范化 JSON 的 sha256，
    不含 fingerprint / upstream_refs 自身。"""
    core = {k: v for k, v in art.items() if k not in ("fingerprint", "upstream_refs")}
    canon = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def build_artifact(spec: dict, art_spec: dict, master_sha: str) -> dict:
    w, h = spec["size"]
    # 声明镜头段数 = 检测器实测口径（切点簇数 +1）；黑场片的 1 帧白板是切点本体
    # 不是镜头，3 段 lavfi 实测 2 镜，故允许 spec 显式声明覆盖。
    seg_count = spec.get("declared_segments", len(spec["segments"]))
    return {
        "schema_version": "2.0",
        "cp_id": "cp11",
        "artifact_type": "composite",
        "fingerprint": "",            # 由 artifact_fingerprint 现算回填
        "produced_by": "fixture.gen",
        "produced_at": PRODUCED_AT,
        "upstream_refs": [
            {"cp_id": "cp3", "fingerprint": "f" * 64},
            {"cp_id": "cp9", "fingerprint": "e" * 64},
            {"cp_id": "cp10", "fingerprint": "d" * 64},
        ],
        "status": "gated",
        "gate": {
            "type": "hard_verify",
            "params_ref": "judges.J6_detectors_v2.rule_params.known_cuts_tol_s",
            "result": art_spec["gate_result"],
            "note": art_spec["gate_note"],
        },
        "aux_gates": [
            {
                "type": "hard_verify",
                "params_ref": "cp11.gate.duration_tol_s",
                "result": "pass",
                "note": art_spec["aux_dur_note"],
            },
            {
                "type": "hard_verify",
                "params_ref": "cp11.gate.shot_count_match",
                # 工件声明侧都写 pass：fail 件的本质就是「声明完备、实测缺陷」，
                # 抓它的必须是校验器实测道，不是声明自认。
                "result": "pass",
                "note": art_spec["aux_shot_note"],
            },
        ],
        "payload": {
            "work_id": art_spec["work_id"],
            "master_asset": {
                "kind": "clip",
                "fingerprint": master_sha,     # sha256 是资产身份（本生成器实测）
                "path": f"{FIX_DIR_REL}/{spec['mp4']}",
            },
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": w,
            "height": h,
            "duration_s": art_spec["duration_declared"],
            "master_shot_segments": seg_count,
            "storyboard_shot_count": seg_count,
            "known_cuts": art_spec["known_cuts"],
            "all_cuts_registered": art_spec["all_registered"],
            "black_ratio": art_spec["black_ratio"],
        },
        "notes": art_spec["notes"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 CP11 校验器测试夹具（4 mp4 + 5 工件）")
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for spec in SPECS:
        rate = spec["rate"]
        n_frames = sum(seg_frames(trim, rate) for _, trim in spec["segments"])
        if n_frames != spec["frames"] or abs(n_frames / rate - spec["total_s"]) > 1e-9:
            print(f"[{spec['key']}] 段帧数累计 {n_frames} != 预期 {spec['frames']}"
                  f"（切点位置会漂移），拒绝生成", file=sys.stderr)
            return 2

        mp4 = out / spec["mp4"]
        print(f"[{spec['key']}] 编码 {mp4}（ffmpeg 内建源，零模型）…")
        proc = subprocess.run(ffmpeg_cmd(spec["segments"], spec["total_s"]) + [str(mp4)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"ffmpeg 失败 rc={proc.returncode}: {proc.stderr[:500]}", file=sys.stderr)
            return 2
        master_sha = sha256_file(mp4)
        print(f"      sha256={master_sha}  size={mp4.stat().st_size}B")

        for art_spec in spec["artifacts"]:
            art = build_artifact(spec, art_spec, master_sha)
            art["fingerprint"] = artifact_fingerprint(art)
            p = out / art_spec["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(art, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"      {p}")

        print(f"      自检：ffprobe 时长…", end=" ")
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(mp4)],
            capture_output=True, text=True, check=True)
        dur = float(pr.stdout.strip())
        if abs(dur - spec["total_s"]) > 0.05:
            print(f"时长异常：{dur}s（期望 {spec['total_s']}s）", file=sys.stderr)
            return 2
        print(f"{dur}s OK")

    vpipe = Path(__file__).resolve().parents[4]  # cp11 → checkpoints → fixtures → tests → vpipe
    print("完成。验证（--probe 缺省取各工件 payload.master_asset.path，可从仓根直跑）：")
    for spec in SPECS:
        for art_spec in spec["artifacts"]:
            expect = ("exit 0" if art_spec["path"].startswith("pass/") else "exit 1")
            print(f"  python3 src/gate/validate_cp11.py {out / art_spec['path']} --probe"
                  f"   # 期望 {expect}")
    print(f"  （基准：cd {vpipe} 下执行；工件 master_asset.path 按 vpipe 根相对登记）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
