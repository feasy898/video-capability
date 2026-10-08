#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_cp7_shot09_rework.py — CP7 回炉重生：shot_09 单镜草稿重生成（CP8 rework_cp3 回退环）。

背景：CP8 择优拦下 shot_09 草稿「全程无可辨主体/面部」（cp8_shot_09.json status=rejected，
rework_route=cp3）。归因：原 prompt 三重负荷（人物走向镜头+镜头后移跟拍双重反向运动 ×
「面部逐渐占满」渐变构图 ×满堂宾客光斑环境）超 33 帧容量，主体被环境吞没。
修订：CP3 action 已改（驻步静态+面部开场即占满+单一极缓推+背景静止光斑，cp3 fingerprint
ca1f0a7e…）；本脚本用修订 prompt_en 重生草稿。

硬条件（SPIKE-REPORT §4 + run_cp7_drafts.py 同款）：
  ① 英文 prompt 层（发现 A：中文直喂 100% 废片）；
  ② 色偏固有（发现 B）只记录不修；
  ③ 确定性：同 seed/params 二遍生成全帧 MAE 须=0.0。
参数不变：33 帧 / 480x704(HxW) / 15 步 / guidance 3.0 / 24fps / seed=51（42+镜序规则不动；
本轮回炉的唯一自变量=prompt 修订，seed 固定以保持可复现与对照）。

红线：只卡 0（CUDA_VISIBLE_DEVICES=0 由启动命令注入，起跑前内联复测 ≤1024MiB 才发车，
卡 1 只记录不碰）；不 kill、不 pip install、不下载（HF_HUB_OFFLINE=1）。
旧废片留痕：跑前 mv shot_09.draft.mp4 → shot_09.draft.v1_rejected.mp4（资产字节不动，
sha256=47cb5583…，与 git 跟踪版本一致）。
"""
import hashlib
import json
import os
import subprocess
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))  # <gpu-repo>/out/m2/shortdrama_ep01/cp7
MODEL = "/data/night/models/LTX-Video"
HEIGHT, WIDTH = 480, 704
NUM_FRAMES = 33
STEPS = 15
GUIDANCE = 3.0
FPS = 24
SEED = 51  # 42 + 镜序 9（规则不动；回炉自变量=prompt，seed 固定保持确定性对照）
NEG = ("worst quality, inconsistent motion, blurry, jittery, distorted, "
       "text, watermark, subtitles")
DECLARED_S = NUM_FRAMES / FPS  # 1.375s

SHOT = {
    "shot_id": "shot_09",
    "seed": SEED,
    "action_zh_revised": "小满驻步正面直视镜头，竖屏面部大特写开场即占满画面，镜头极缓推近锁定双眼，身后满堂宾客虚成静止光斑",
    "prompt_en_revised": ("Extreme close-up, centered: a young Chinese woman stands still facing the "
                          "camera, her face filling the frame from the very first moment, calm defiant "
                          "eyes locked on the lens, breathing gently, only her hair strands swaying "
                          "faintly; the camera creeps forward very slowly, locked on her eyes, while "
                          "the banquet hall guests behind her melt into a still field of round bokeh, "
                          "no walking, shallow depth of field"),
    "prompt_en_v1_rejected": ("Extreme close-up tracking shot: a young woman walks slowly straight toward the "
                              "camera, her face gradually filling the frame while a hall full of guests "
                              "dissolves into glowing bokeh behind her, the camera gliding backward with her, "
                              "focus locked on her eyes"),
    "negative": NEG,
}

RESULT = {
    "task": "cp7-shot09-rework-round2",
    "host": os.uname().nodename,
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "model": {"path": MODEL, "dtype": "float16", "pipeline": "LTXPipeline"},
    "params": {"height": HEIGHT, "width": WIDTH, "num_frames": NUM_FRAMES,
               "num_inference_steps": STEPS, "guidance_scale": GUIDANCE,
               "seed": SEED, "seed_rationale": "seed 规则 42+镜序不动；回炉唯一自变量=prompt 修订",
               "fps_out": FPS, "declared_duration_s": DECLARED_S,
               "negative_prompt": NEG},
    "provenance": {
        "cp8_rejection": "overnight/vpipe/out/m2/shortdrama_ep01/cp8/cp8_shot_09.json status=rejected rework_cp3",
        "cp3_revision": "cp3.json fingerprint ca1f0a7e88bf86c6…（action/move 修订，validate_cp3 exit 0）",
        "attribution": "双重反向运动×渐变构图×光斑环境三重负荷超 33 帧容量，主体被环境吞没",
    },
    "shots": [],
    "errors": [],
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def gpu_used_mib(idx):
    p = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", str(idx)],
        capture_output=True, text=True, timeout=10)
    if p.returncode != 0:
        raise RuntimeError(f"nvidia-smi rc={p.returncode}: {p.stderr.strip()}")
    return int(p.stdout.strip().splitlines()[0])


class NvidiaSampler:
    def __init__(self, interval=2.0):
        self.interval = interval
        self.samples = []
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.samples.append((round(time.monotonic() - self._t0, 2), gpu_used_mib(0)))
            except Exception as e:  # noqa: BLE001
                RESULT["errors"].append(f"nvidia_smi_query_failed: {e}")
            self._stop.wait(self.interval)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=15)


def to_np_uint8(frames, expect_shape):
    import numpy as np
    import torch
    if isinstance(frames, torch.Tensor):
        arr = frames.detach().float().cpu().numpy()
    else:
        arr = np.asarray(frames)
    arr = np.squeeze(arr)
    ch_axes = [i for i, s in enumerate(arr.shape) if s == 3]
    if len(ch_axes) != 1:
        raise ValueError(f"cannot locate channel axis in shape {arr.shape}")
    arr = np.moveaxis(arr, ch_axes[0], -1)
    if arr.dtype != np.uint8:
        if arr.max() <= 1.0:
            arr = arr * 255.0
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.shape != expect_shape:
        raise ValueError(f"unexpected final shape {arr.shape}, expect {expect_shape}")
    return arr


def frame_stats(arr):
    import numpy as np
    f = arr.astype(np.float32)
    nan_count = int(np.isnan(f).sum())
    frame_mean = f.mean(axis=(1, 2, 3))
    black = int((frame_mean < 2.0).sum())
    return {"frames": int(arr.shape[0]), "nan_count": nan_count,
            "black_frames_lt2": black,
            "frame_mean_min": round(float(frame_mean.min()), 3),
            "frame_mean_max": round(float(frame_mean.max()), 3),
            "frame_mean_overall": round(float(frame_mean.mean()), 3)}


def encode_video(arr, path):
    from diffusers.utils import export_to_video
    t0 = time.monotonic()
    export_to_video(arr, fps=FPS, output_video_path=path)
    return round(time.monotonic() - t0, 3)


def ffprobe_triple(path):
    p = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe rc={p.returncode}")
    d = json.loads(p.stdout)
    st = d["streams"][0]
    return {"codec_name": st.get("codec_name"), "pix_fmt": st.get("pix_fmt"),
            "width": st.get("width"), "height": st.get("height"),
            "avg_frame_rate": st.get("avg_frame_rate"), "nb_frames": st.get("nb_frames"),
            "duration_s": float(d["format"]["duration"]) if d["format"].get("duration") else None,
            "bit_rate": d["format"].get("bit_rate")}


def decode_mp4_check(path):
    import numpy as np
    p = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=120)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"mp4 decode rc={p.returncode}")
    raw = np.frombuffer(p.stdout, dtype=np.uint8)
    n = len(raw) // (HEIGHT * WIDTH * 3)
    arr = raw[: n * HEIGHT * WIDTH * 3].reshape(n, HEIGHT, WIDTH, 3)
    mean = arr.astype(np.float32).mean(axis=(1, 2, 3))
    return {"decoded_frames": int(n), "black_frames_lt2": int((mean < 2.0).sum()),
            "frame_mean_min": round(float(mean.min()), 3),
            "frame_mean_overall": round(float(mean.mean()), 3)}


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import numpy as np
    import torch

    # ---- 旧废片留痕（资产字节原样改名，sha256 须仍= 47cb5583…）----
    old_mp4 = os.path.join(BASE, "shot_09.draft.mp4")
    v1_path = os.path.join(BASE, "shot_09.draft.v1_rejected.mp4")
    if os.path.exists(old_mp4):
        old_sha = sha256_of(old_mp4)
        if old_sha == "47cb5583ee12f2c1fccb65da317c0cdb7362b6a8db71d029b1ef1acc08521cf4":
            os.rename(old_mp4, v1_path)
            RESULT["v1_rejected_archive"] = {"path": os.path.basename(v1_path), "sha256": old_sha}
            log(f"旧废片留痕 -> {os.path.basename(v1_path)} (sha256 {old_sha[:12]}…)")
        else:
            RESULT["v1_rejected_archive"] = {"note": "现行 draft 非 v1 废片，不归档不改名",
                                             "sha256": old_sha}
            log(f"现行 draft sha={old_sha[:12]}… 非 v1，保留不归档")
    if os.path.exists(v1_path) and not os.path.exists(old_mp4):
        RESULT.setdefault("v1_rejected_archive",
                          {"path": os.path.basename(v1_path), "sha256": sha256_of(v1_path)})

    # ---- 红线复测：卡 0 ≤1024MiB 才发车；卡 1 只记录不碰 ----
    pre = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "card0_used_mib": gpu_used_mib(0), "card1_used_mib": gpu_used_mib(1)}
    if pre["card0_used_mib"] > 1024:
        RESULT["errors"].append(f"preflight_card0_busy: {pre['card0_used_mib']}MiB > 1024MiB，拒发车")
        raise SystemExit("PREFLIGHT_FAIL card0 > 1GiB")
    RESULT["preflight"] = pre
    log(f"preflight card0={pre['card0_used_mib']}MiB card1={pre['card1_used_mib']}MiB -> GO")

    RESULT["gpu"] = {"name": torch.cuda.get_device_name(0),
                     "capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
                     "bf16_supported": torch.cuda.is_bf16_supported()}

    sampler = NvidiaSampler().start()
    t_all = time.monotonic()

    from diffusers import LTXPipeline
    t0 = time.monotonic()
    pipe = LTXPipeline.from_pretrained(MODEL, torch_dtype=torch.float16)
    pipe.to("cuda")
    load_s = time.monotonic() - t0
    torch.cuda.reset_peak_memory_stats()
    log(f"模型加载完成 load_s={load_s:.1f}")

    expect_shape = (NUM_FRAMES, HEIGHT, WIDTH, 3)

    def gen_once():
        g = torch.Generator(device="cuda").manual_seed(SHOT["seed"])
        t = time.monotonic()
        with torch.inference_mode():
            out = pipe(prompt=SHOT["prompt_en_revised"], negative_prompt=SHOT["negative"],
                       height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
                       num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=g)
        dt = time.monotonic() - t
        torch.cuda.synchronize()
        peak = torch.cuda.max_memory_allocated() / 2 ** 20
        torch.cuda.reset_peak_memory_stats()
        return out.frames, dt, peak

    rec = {"shot_id": SHOT["shot_id"], "seed": SHOT["seed"], "round": 2}
    try:
        frames_raw, gen_s, peak = gen_once()
        arr = to_np_uint8(frames_raw, expect_shape)
        stats = frame_stats(arr)
        rec.update(gen_s=round(gen_s, 2), torch_peak_mib=round(peak, 1), tensor_stats=stats)

        if stats["nan_count"] > 0:
            RESULT["errors"].append(f"{SHOT['shot_id']}: NaN={stats['nan_count']}，走 VAE fp32 预案重跑")
            pipe.vae.to(torch.float32)
            frames_raw, gen_s, peak = gen_once()
            arr = to_np_uint8(frames_raw, expect_shape)
            stats = frame_stats(arr)
            pipe.vae.to(torch.float16)
            rec.update(vae_fp32_fallback=True, gen_s=round(gen_s, 2),
                       torch_peak_mib=round(peak, 1), tensor_stats=stats)

        mp4 = os.path.join(BASE, "shot_09.draft.mp4")
        enc_s = encode_video(arr, mp4)
        os.chmod(mp4, 0o644)
        probe = ffprobe_triple(mp4)
        e2e = decode_mp4_check(mp4)
        actual = probe.get("duration_s")
        dev = abs(actual - DECLARED_S) / DECLARED_S if actual else None
        rec.update(encode_s=enc_s, mp4_sha256=sha256_of(mp4),
                   mp4_size_bytes=os.path.getsize(mp4), ffprobe=probe,
                   end_to_end_decode=e2e, declared_duration_s=DECLARED_S,
                   actual_duration_s=actual,
                   duration_dev=round(dev, 6) if dev is not None else None)

        l0 = {"shot_id": SHOT["shot_id"], "asset": os.path.basename(mp4), "round": 2,
              "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "thresholds_ref": "eval/thresholds.yaml:178-181 l0_preflight",
              "checks": {"black_frames_tensor_lt2": stats["black_frames_lt2"],
                         "black_frames_decoded_lt2": e2e["black_frames_lt2"],
                         "nan_count_tensor": stats["nan_count"],
                         "duration_dev": rec["duration_dev"], "duration_dev_max": 0.02,
                         "black_frame_ratio": (stats["black_frames_lt2"] / stats["frames"]),
                         "black_frame_ratio_max": 0.50,
                         "ffprobe_triple": {"codec": probe["codec_name"], "pix_fmt": probe["pix_fmt"],
                                            "wh": f"{probe['width']}x{probe['height']}",
                                            "fps": probe["avg_frame_rate"],
                                            "nb_frames": probe["nb_frames"]}}}
        # ffprobe JSON 数值恒为字符串（原批 run_cp7_drafts 实跑同款 fixup）：int() 比较后判定，留痕 marker
        l0["checks"]["ffprobe_triple"]["nb_frames_type"] = "string(fixup: int() 比较后判定)"
        l0["accepted"] = bool(
            stats["black_frames_lt2"] == 0 and e2e["black_frames_lt2"] == 0
            and stats["nan_count"] == 0 and dev is not None and dev <= 0.02
            and probe["codec_name"] == "h264" and probe["pix_fmt"] == "yuv420p"
            and probe["width"] == WIDTH and probe["height"] == HEIGHT
            and int(probe["nb_frames"]) == NUM_FRAMES)
        l0_path = os.path.join(BASE, "shot_09.draft.l0.json")
        with open(l0_path, "w", encoding="utf-8") as f:
            json.dump(l0, f, ensure_ascii=False, indent=2)
        os.chmod(l0_path, 0o644)
        rec["l0_accepted"] = l0["accepted"]
        log(f"{SHOT['shot_id']}: gen={rec['gen_s']}s enc={enc_s}s "
            f"black={stats['black_frames_lt2']}/{e2e['black_frames_lt2']} "
            f"nan={stats['nan_count']} dev={rec['duration_dev']} l0={l0['accepted']}")

        # ---- 确定性抽验：同 seed/params 二遍生成，全帧 MAE 须=0.0 ----
        frames_b, gen2_s, _ = gen_once()
        arr_b = to_np_uint8(frames_b, expect_shape)
        mae = float(np.abs(arr.astype(np.float32) - arr_b.astype(np.float32)).mean())
        rec["determinism"] = {"method": "same seed/params second generation, full-frame MAE",
                              "gen2_s": round(gen2_s, 2), "mae_all_frames": round(mae, 6),
                              "equal_bits": mae == 0.0}
        log(f"确定性抽验: MAE={mae}")
        RESULT["shots"].append(rec)
    except Exception as e:  # noqa: BLE001
        import traceback
        RESULT["errors"].append({"shot_id": SHOT["shot_id"],
                                 "error": f"{e.__class__.__name__}: {e}",
                                 "trace": traceback.format_exc()[-1500:]})
        log(f"{SHOT['shot_id']}: FAILED {e.__class__.__name__}: {e}")
        RESULT["shots"].append(rec)

    sampler.stop()
    RESULT["timing_s"] = {"load": round(load_s, 2), "total": round(time.monotonic() - t_all, 2)}
    sm = [s for _, s in sampler.samples]
    RESULT["vram"] = {"baseline_used_mib": (sm[0] if sm else None),
                      "nvidia_smi_max_used_mib": (max(sm) if sm else None),
                      "nvidia_smi_samples": len(sm)}
    RESULT["ok"] = (len(RESULT["errors"]) == 0
                    and bool(rec.get("l0_accepted"))
                    and rec.get("determinism", {}).get("mae_all_frames") == 0.0)

    report = os.path.join(BASE, "cp7_shot09_rework_report.json")
    with open(report, "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=2)
    os.chmod(report, 0o644)
    log(f"完成 ok={RESULT['ok']} total_s={RESULT['timing_s']['total']} errors={len(RESULT['errors'])}")
    if not RESULT["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        RESULT["errors"].append(f"fatal: {e.__class__.__name__}: {e}")
        RESULT["ok"] = False
        with open(os.path.join(BASE, "cp7_shot09_rework_report.json"), "w", encoding="utf-8") as f:
            json.dump(RESULT, f, ensure_ascii=False, indent=2)
        traceback.print_exc()
        raise SystemExit(1)
