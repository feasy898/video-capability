#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""postprocess_cp9.py — 单镜收尾：落 final.mp4 + ffprobe 亲核 + sha256 + gen_meta.json。

用法: python3 _probe/postprocess_cp9.py <shot_id>
读 out/api_results.jsonl 里 <shot_id>@MiniMax-H3-Max 的 succeeded 记录；
拷贝 out/<rid>.mp4 → out/m2/shortdrama_ep01/cp9/<shot_id>.final.mp4；
gen_meta.json 含 submit_params_fingerprint（sha256(canonical(提交 payload))）/credit 留痕/repro_level。
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/pan-ding/workspace/视频能力")
VP = ROOT / "overnight/vpipe"
OUT = VP / "out"
CP9 = OUT / "m2/shortdrama_ep01/cp9"
MODEL = "MiniMax-H3-Max"
EST_PER_SEC = 56


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(p)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[:300]
    return json.loads(r.stdout)


def main(sid):
    rid = f"{sid}@{MODEL}"
    rec = None
    for line in (OUT / "api_results.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d.get("rid") == rid:
            rec = d
    assert rec is not None, f"{rid} 无记录"
    assert rec.get("status") == "succeeded", f"{rid} 终态={rec.get('status')} error={rec.get('error','')[:200]}"
    src = OUT / f"{rid}.mp4"
    dst = CP9 / f"{sid}.final.mp4"
    shutil.copyfile(src, dst)

    # 亲核：本地 ffprobe + sha256（对拷贝产物，不信任 run 记录）
    probe = ffprobe(dst)
    sha = sha256_file(dst)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)

    # 提交参数还原（与 gen_api build_cloud_payload 一致；prompt 从 shot 契约取）
    shot = json.loads((CP9 / "shots" / f"{sid}.json").read_text(encoding="utf-8"))
    submit_params = {
        "model": MODEL,
        "prompt": shot["prompt"][:7000],
        "duration": int(shot["duration_s"]),
        "resolution": shot.get("resolution") or "768P",
        "ratio": shot["aspect"],
        "generate_audio": bool((shot.get("audio") or {}).get("generate", True)),
        "image_mode": "text-to-video",
    }
    sp_fp = hashlib.sha256(canonical(submit_params).encode("utf-8")).hexdigest()

    est = EST_PER_SEC * int(shot["duration_s"])
    meta = {
        "schema_version": "2.0",
        "shot_id": sid,
        "work_id": "shortdrama_ep01",
        "cp_id": "cp9",
        "channel": "api_h3max",
        "model": MODEL,
        "backend": rec.get("backend"),
        "task_id": rec.get("task_id"),
        "status": rec.get("status"),
        "submitted_at": rec.get("at"),
        "elapsed_s": rec.get("elapsed_s"),
        "submit_params": submit_params,
        "submit_params_fingerprint": sp_fp,
        "repro_level": "submit_params",
        "seed_sent": rec.get("seed_sent"),
        "seed_recorded": None,
        "credit": {
            "est_credit": rec.get("est_credit"),
            "credit_spent_est": est,
            "credit_before": rec.get("credit_before"),
            "credit_after": rec.get("credit_after"),
            "credit_cost": rec.get("credit_cost"),
            "basis": "56积分/s 估算口径（云通道无钱包端点，SPEC §2.2 如实降级；credit_*三字段如实 null）",
        },
        "reference_images_used": [],
        "image_conditioned": "未用（CP2 注册表无 http(s) 参考 URL；files/upload 手册未实测→fail-closed 不绕过）",
        "asset": {
            "kind": "clip",
            "fingerprint": sha,
            "path": f"overnight/vpipe/out/m2/shortdrama_ep01/cp9/{sid}.final.mp4",
            "size_bytes": dst.stat().st_size,
            "sha256": sha,
        },
        "ffprobe": {
            "width": v.get("width"), "height": v.get("height"),
            "duration": probe["format"].get("duration"),
            "video_codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
            "avg_frame_rate": v.get("avg_frame_rate"),
            "audio_codec": a.get("codec_name") if a else None,
            "nb_frames": v.get("nb_frames"),
        },
        "upstream": {
            "cp8_selection": f"overnight/vpipe/out/m2/shortdrama_ep01/cp8/cp8_{sid}.json",
            "shot_contract": f"overnight/vpipe/out/m2/shortdrama_ep01/cp9/shots/{sid}.json",
        },
    }
    (CP9 / f"{sid}.gen_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"OK {sid}: {dst.name} sha256={sha[:16]}… {v.get('width')}x{v.get('height')} "
          f"{probe['format'].get('duration')}s v={v.get('codec_name')} a={a.get('codec_name') if a else None} "
          f"est={est} task={rec.get('task_id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
