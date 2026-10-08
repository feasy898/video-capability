#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_fixture.py — CP11 校验器测试夹具生成器（tests/fixtures/checkpoints/cp11/）。

产出（同目录）：
    master_9s.mp4                     9s / 360x640 / 30fps / h264+aac 测试片，
                                      4 段程序源拼接，硬切点恰在 2.5 / 5.0 / 7.5s
                                      （smptebars→rgbtestsrc→testsrc2→灰底，全部
                                      ffmpeg 内建 lavfi 源，零模型调用——红线：测试片
                                      必须 ffmpeg 程序生成）。mp4 不入 git（见同目录
                                      .gitignore），本脚本即唯一权威生成方式。
    pass/cp11_fixture.json            切点 2.5/5.0/7.5 全部登记 known_cuts
                                      → validate_cp11.py --probe 判 pass（exit 0）
    fail/cp11_fixture_missing_cut.json
                                      故意漏登记 7.5s 切点（known_cuts=[2.5,5.0]，
                                      all_cuts_registered 仍谎报 true——正是 M1-W5
                                      要抓的「声明完备、实测漏登记」）
                                      → --probe 判 fail（exit 1，known_cuts_registered）；
                                        无 --probe 也 fail（cuts_segments_coherence：
                                        2 点 != 段数 4 - 1）

确定性：编码命令固定（本机 ffmpeg 6.1.1 实测二遍 md5 一致），工件 produced_at
固定常量、fingerprint=按 checkpoint.schema.json「payload 规范化 JSON 的 sha256
（不含 fingerprint/upstream_refs 自身）」现算——重跑本脚本字节级复现同工件。

用法：python3 make_fixture.py [--out-dir DIR]   （缺省=脚本所在目录）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# 4 段节目源（完整 lavfi 图片段）与各自时长（切点 = 时长累计：2.5 / 5.0 / 7.5）
SIZE, RATE, TOTAL_S = "360x640", "30", 9.0
SEGMENTS = [
    (f"smptebars=size={SIZE}:rate={RATE}", 2.5),
    (f"rgbtestsrc=size={SIZE}:rate={RATE}", 2.5),
    (f"testsrc2=size={SIZE}:rate={RATE}", 2.5),
    (f"color=c=0x404040:size={SIZE}:rate={RATE}", 1.5),
]

FFMPEG_CMD = (
    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    + [arg for src, _ in SEGMENTS for arg in ("-f", "lavfi", "-i", src)]
    + ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
    + [
        "-filter_complex",
        ";".join(
            f"[{i}:v]trim=0:{dur},setpts=PTS-STARTPTS[{chr(97 + i)}]"
            for i, (_, dur) in enumerate(SEGMENTS)
        )
        + ";" + "".join(f"[{chr(97 + i)}]" for i in range(len(SEGMENTS)))
        + f"concat=n={len(SEGMENTS)}:v=1:a=0[v];[4:a]atrim=0:{TOTAL_S},asetpts=PTS-STARTPTS[aud]",
        "-map", "[v]", "-map", "[aud]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
        "-t", str(TOTAL_S),
    ]
)

MP4_NAME = "master_9s.mp4"
PRODUCED_AT = "2026-10-08T00:00:00Z"   # 固定常量：夹具字节级可复现
MP4_VPIPE_REL = "tests/fixtures/checkpoints/cp11/master_9s.mp4"  # 相对 overnight/vpipe 根


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def artifact_fingerprint(art: dict) -> str:
    """checkpoint.schema.json fingerprint 定义：工件身份 = 规范化 JSON 的 sha256，
    不含 fingerprint / upstream_refs 自身。"""
    core = {k: v for k, v in art.items() if k not in ("fingerprint", "upstream_refs")}
    canon = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def build_artifact(known_cuts: list[float], all_registered: bool, master_sha: str,
                   gate_result: str, gate_note: str, aux_shot_note: str) -> dict:
    seg_count = len(SEGMENTS)
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
            "result": gate_result,
            "note": gate_note,
        },
        "aux_gates": [
            {
                "type": "hard_verify",
                "params_ref": "cp11.gate.duration_tol_s",
                "result": "pass",
                "note": f"成片 {TOTAL_S:g}s vs 声明 {TOTAL_S:g}s，±1s 内（ffprobe 实测由校验器复核）。",
            },
            {
                "type": "hard_verify",
                "params_ref": "cp11.gate.shot_count_match",
                # 两件夹具的声明侧都写 pass：fail 件的本质就是「声明完备、实测漏登记」，
                # 抓它的必须是校验器实测道，不是声明自认。
                "result": "pass",
                "note": aux_shot_note,
            },
        ],
        "payload": {
            "work_id": "cp11_fixture",
            "master_asset": {
                "kind": "clip",
                "fingerprint": master_sha,     # sha256 是资产身份（本生成器实测）
                "path": MP4_VPIPE_REL,
            },
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": int(SIZE.split("x")[0]),
            "height": int(SIZE.split("x")[1]),
            "duration_s": TOTAL_S,
            "master_shot_segments": seg_count,
            "storyboard_shot_count": seg_count,
            "known_cuts": known_cuts,
            "all_cuts_registered": all_registered,
            "black_ratio": 0.0,
        },
        "notes": (
            "CP11 校验器夹具：ffmpeg 内建 lavfi 源程序拼接（smptebars/rgbtestsrc/testsrc2/"
            "灰底），硬切点 2.5/5.0/7.5s。由 make_fixture.py 生成，重跑字节级复现。"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 CP11 校验器测试夹具（mp4+工件）")
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    args = ap.parse_args()
    if abs(sum(d for _, d in SEGMENTS) - TOTAL_S) > 1e-9:
        print("段时长累计 != TOTAL_S（切点位置会漂移），拒绝生成", file=sys.stderr)
        return 2
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mp4 = out / MP4_NAME

    print(f"[1/3] 编码 {mp4}（ffmpeg 内建源，零模型）…")
    proc = subprocess.run(FFMPEG_CMD + [str(mp4)], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"ffmpeg 失败 rc={proc.returncode}: {proc.stderr[:500]}", file=sys.stderr)
        return 2
    master_sha = sha256_file(mp4)
    print(f"      sha256={master_sha}  size={mp4.stat().st_size}B")

    print("[2/3] 写 pass/fail 工件（fingerprint 按 schema 口径现算）…")
    cases = {
        "pass": build_artifact(
            known_cuts=[2.5, 5.0, 7.5],
            all_registered=True,
            master_sha=master_sha,
            gate_result="pass",
            gate_note="3 个拼接硬切点（2.5/5.0/7.5s）全部登记 known_cuts 白名单，"
                      "容差 0.5s 沿 judges.J6_detectors_v2.rule_params.known_cuts_tol_s。",
            aux_shot_note="实测切点数 3（+1 段 = 4）== master_shot_segments 4 "
                          "== storyboard_shot_count 4。",
        ),
        "fail": build_artifact(
            known_cuts=[2.5, 5.0],            # 故意漏登记 7.5
            all_registered=True,              # 声明谎报完备——M1-W5 要抓的形态
            master_sha=master_sha,
            gate_result="pass",               # 声明侧自认为 pass
            gate_note="（漏登记件）声明 2 个切点已登记——实测道应抓出 7.5s 未登记硬切点。",
            aux_shot_note="（漏登记件）声明段数 4 与分镜表 4 一致——实测道应抓出登记册缺点。",
        ),
    }
    for case, art in cases.items():
        art["fingerprint"] = artifact_fingerprint(art)
        d = out / case
        d.mkdir(parents=True, exist_ok=True)
        name = ("cp11_fixture_missing_cut.json" if case == "fail"
                else "cp11_fixture.json")
        p = d / name
        p.write_text(json.dumps(art, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"      {p}")

    print("[3/3] 自检：ffprobe 时长与容器…")
    pr = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(mp4)],
        capture_output=True, text=True, check=True)
    dur = float(pr.stdout.strip())
    if abs(dur - TOTAL_S) > 0.05:
        print(f"时长异常：{dur}s（期望 {TOTAL_S}s）", file=sys.stderr)
        return 2
    print(f"      duration={dur}s OK")
    print("完成。验证：")
    print(f"  python3 src/gate/validate_cp11.py {out}/pass/cp11_fixture.json "
          f"--probe {mp4}   # 期望 exit 0")
    print(f"  python3 src/gate/validate_cp11.py {out}/fail/cp11_fixture_missing_cut.json "
          f"--probe {mp4}   # 期望 exit 1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
