#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LTX-Video 2B 单条基线 spike（v4 草稿层决策实测数据）。

铁律执行环境：仅卡 0（CUDA_VISIBLE_DEVICES=0 由 nohup 启动命令注入）。
产物：本目录 ltx_baseline.json + ltx_out.mp4。
参数：中文固定 prompt / 480x704(高x宽) / 33 帧 / 15 步 / seed 42 / fp16（V100S major7，bf16 不可用）。
"""
import hashlib
import json
import os
import subprocess
import threading
import time

import numpy as np
import torch

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL = "/data/night/models/LTX-Video"
OUT_MP4 = os.path.join(BASE, "ltx_out.mp4")
OUT_MP4_2 = os.path.join(BASE, "ltx_out_encode2.mp4")
OUT_JSON = os.path.join(BASE, "ltx_baseline.json")
LOG = os.path.join(BASE, "ltx_baseline.log")

PROMPT = "一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云"
NEGATIVE = ""
HEIGHT, WIDTH = 480, 704  # 480P，HxW
NUM_FRAMES = 33           # 33 = 8*4+1，满足 LTX 时间压缩约束
STEPS = 15
GUIDANCE = 3.0
SEED = 42
FPS = 24
SAMPLE_IDX = [0, 8, 16, 24, 32]

RESULT = {
    "task": "ltx-2b-baseline-spike",
    "host": os.uname().nodename,
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "errors": [],
}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class NvidiaSampler:
    """每 2s 采样一次 nvidia-smi 卡 0 已用显存（MiB）。"""

    def __init__(self, interval=2.0):
        self.interval = interval
        self.samples = []  # (t_offset_s, mib)
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _query(self):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                capture_output=True, text=True, timeout=10,
            )
            return int(out.stdout.strip().splitlines()[0]), out.returncode
        except Exception as e:  # noqa: BLE001
            RESULT["errors"].append(f"nvidia_smi_query_failed: {e}")
            return None, 1

    def _run(self):
        while not self._stop.is_set():
            mib, rc = self._query()
            if mib is not None:
                self.samples.append((round(time.monotonic() - self._t0, 2), mib))
            self._stop.wait(self.interval)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=15)


def to_np_uint8(frames):
    """pipeline 输出 -> np.uint8 (T,H,W,C)。布局自适应：找出 size==3 的通道轴移到最后。"""
    if isinstance(frames, torch.Tensor):
        arr = frames.detach().float().cpu().numpy()
        src = "torch_tensor"
    else:
        arr = np.asarray(frames)
        src = type(frames).__name__
    in_shape = arr.shape
    arr = np.squeeze(arr)  # 去掉大小为 1 的批维
    # 通道轴 = 唯一 size==3 的轴（T=33/H=480/W=704 都 !=3，安全）
    ch_axes = [i for i, s in enumerate(arr.shape) if s == 3]
    if len(ch_axes) != 1:
        raise ValueError(f"cannot locate channel axis in shape {arr.shape}")
    arr = np.moveaxis(arr, ch_axes[0], -1)
    if arr.dtype != np.uint8:
        if arr.max() <= 1.0:
            arr = arr * 255.0
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.shape != (NUM_FRAMES, HEIGHT, WIDTH, 3):
        raise ValueError(f"unexpected final shape {arr.shape}, in={in_shape} src={src}")
    RESULT.setdefault("frames_layout", []).append({"src": src, "in_shape": list(in_shape), "out_shape": list(arr.shape)})
    return arr


def frames_stats(name, arr):
    """黑帧/NaN/每帧均值统计。arr: uint8 (T,H,W,C)。"""
    f = arr.astype(np.float32)
    nan_count = int(np.isnan(f).sum())
    frame_mean = f.mean(axis=(1, 2, 3))  # 每帧 RGB 均值 0-255
    black_thr = 2.0  # 帧均值 < 2/255 视为黑帧
    black = int((frame_mean < black_thr).sum())
    RESULT.setdefault("quality", {})[name] = {
        "nan_count": nan_count,
        "black_frames_lt2": black,
        "frame_mean_min": round(float(frame_mean.min()), 3),
        "frame_mean_max": round(float(frame_mean.max()), 3),
        "frame_mean_overall": round(float(frame_mean.mean()), 3),
    }
    return arr


def encode_video(arr, path):
    """diffusers export_to_video 固定参数编码，返回 (耗时s, md5)。"""
    from diffusers.utils import export_to_video
    t0 = time.monotonic()
    export_to_video(arr, fps=FPS, output_video_path=path)
    dt = round(time.monotonic() - t0, 3)
    with open(path, "rb") as fp:
        md5 = hashlib.md5(fp.read()).hexdigest()
    return dt, md5


def ffprobe_triple(path):
    p = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=60,
    )
    if p.returncode != 0:
        RESULT["errors"].append(f"ffprobe_failed rc={p.returncode}")
        return {"error": f"rc={p.returncode}"}
    d = json.loads(p.stdout)
    st = d["streams"][0]
    return {
        "codec_name": st.get("codec_name"),
        "pix_fmt": st.get("pix_fmt"),
        "width": st.get("width"),
        "height": st.get("height"),
        "avg_frame_rate": st.get("avg_frame_rate"),
        "nb_frames": st.get("nb_frames"),
        "duration_s": float(d["format"].get("duration", "nan")) if d["format"].get("duration") else None,
        "bit_rate": d["format"].get("bit_rate"),
        "rc": p.returncode,
    }


def decode_mp4_check(path):
    """端到端回检：ffmpeg 解码 mp4 -> rawvideo，查帧数/黑帧。"""
    p = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=120,
    )
    if p.returncode != 0 or not p.stdout:
        RESULT["errors"].append(f"mp4_decode_failed rc={p.returncode}")
        return None
    raw = np.frombuffer(p.stdout, dtype=np.uint8)
    n_frames = len(raw) // (HEIGHT * WIDTH * 3)
    arr = raw[: n_frames * HEIGHT * WIDTH * 3].reshape(n_frames, HEIGHT, WIDTH, 3)
    mean = arr.astype(np.float32).mean(axis=(1, 2, 3))
    return {
        "decoded_frames": int(n_frames),
        "black_frames_lt2": int((mean < 2.0).sum()),
        "frame_mean_min": round(float(mean.min()), 3),
        "frame_mean_overall": round(float(mean.mean()), 3),
        "decode_rc": p.returncode,
    }


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    RESULT["git_head"] = subprocess.run(
        ["git", "-C", os.path.dirname(BASE), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or "git_unavailable"
    RESULT["model"] = {"path": MODEL, "dtype": "float16"}
    RESULT["params"] = {
        "prompt": PROMPT, "negative_prompt": NEGATIVE,
        "height": HEIGHT, "width": WIDTH,
        "num_frames": NUM_FRAMES, "num_inference_steps": STEPS,
        "guidance_scale": GUIDANCE, "seed": SEED, "fps_out": FPS,
        "resolution_note": "480P（高480x宽704），任务书口径 480x704 按 HxW 解读",
    }
    RESULT["gpu"] = {
        "name": torch.cuda.get_device_name(0),
        "capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
        "bf16_supported": torch.cuda.is_bf16_supported(),
    }
    log(f"GPU: {RESULT['gpu']['name']} cc={RESULT['gpu']['capability']} bf16={RESULT['gpu']['bf16_supported']}")

    sampler = NvidiaSampler().start()
    t_all = time.monotonic()

    # ---- 加载 ----
    from diffusers import LTXPipeline
    t0 = time.monotonic()
    pipe = LTXPipeline.from_pretrained(MODEL, torch_dtype=torch.float16)
    pipe.to("cuda")
    load_s = time.monotonic() - t0
    load_peak_mib = torch.cuda.max_memory_allocated() / 2**20
    torch.cuda.reset_peak_memory_stats()
    log(f"模型加载完成 load_s={load_s:.1f} load_peak={load_peak_mib:.0f}MiB")

    def gen_once(tag):
        g = torch.Generator(device="cuda").manual_seed(SEED)
        t = time.monotonic()
        with torch.inference_mode():
            out = pipe(
                prompt=PROMPT, negative_prompt=NEGATIVE,
                height=HEIGHT, width=WIDTH,
                num_frames=NUM_FRAMES,
                num_inference_steps=STEPS,
                guidance_scale=GUIDANCE,
                generator=g,
            )
        dt = time.monotonic() - t
        torch.cuda.synchronize()
        peak = torch.cuda.max_memory_allocated() / 2**20
        torch.cuda.reset_peak_memory_stats()
        log(f"{tag}: gen_s={dt:.1f} peak={peak:.0f}MiB")
        return out.frames, dt, peak

    # ---- Run A ----
    frames_A_raw, gen1_s, peak1 = gen_once("run1")
    arr_A = to_np_uint8(frames_A_raw)
    frames_stats("run1_raw", arr_A)

    nan_A = RESULT["quality"]["run1_raw"]["nan_count"]
    if nan_A > 0:
        RESULT["errors"].append(f"run1 NaN={nan_A}: fp16 VAE 已知风险，升 VAE fp32 重解码（不重跑 transformer）")
        log("检测到 NaN，VAE 升 fp32 后重解码 latent（预案）")
        pipe.vae.to(torch.float32)
        # 直接重跑一遍生成走预案（记录为 rerun）
        frames_A_raw, gen1_s, peak1 = gen_once("run1_vae_fp32_rerun")
        arr_A = to_np_uint8(frames_A_raw)
        frames_stats("run1_raw_vae_fp32_rerun", arr_A)
        RESULT["vae_fp32_fallback"] = True

    # ---- 编码两遍（确定性验证：同帧同参数两次编码 md5）----
    enc1_s, md5_1 = encode_video(arr_A, OUT_MP4)
    enc2_s, md5_2 = encode_video(arr_A, OUT_MP4_2)
    log(f"encode1={enc1_s}s md5={md5_1} | encode2={enc2_s}s md5={md5_2} equal={md5_1 == md5_2}")

    # ---- Run B（同 seed 二遍生成，帧级一致性）----
    frames_B_raw, gen2_s, peak2 = gen_once("run2")
    arr_B = to_np_uint8(frames_B_raw)
    frames_stats("run2_raw", arr_B)

    a = arr_A.astype(np.float32)
    b = arr_B.astype(np.float32)
    n = min(a.shape[0], b.shape[0])
    mae_samples = {}
    for i in SAMPLE_IDX:
        if i < n:
            mae_samples[str(i)] = round(float(np.abs(a[i] - b[i]).mean()), 4)
    mae_all = round(float(np.abs(a[:n] - b[:n]).mean()), 4)
    log(f"确定性: 5帧抽样MAE={mae_samples} 全帧MAE={mae_all}")

    # ---- 端到端回检 ltx_out.mp4 ----
    e2e = decode_mp4_check(OUT_MP4)

    sampler.stop()
    total_s = time.monotonic() - t_all
    sm = [s for _, s in sampler.samples]
    baseline_mib = sm[0] if sm else None
    max_used_mib = max(sm) if sm else None

    RESULT["timing_s"] = {
        "load": round(load_s, 2),
        "gen_run1": round(gen1_s, 2),
        "gen_run2": round(gen2_s, 2),
        "encode_run1": enc1_s,
        "encode_run2": enc2_s,
        "total": round(total_s, 2),
    }
    RESULT["vram"] = {
        "baseline_used_mib": baseline_mib,
        "nvidia_smi_max_used_mib": max_used_mib,
        "nvidia_smi_delta_mib": (max_used_mib - baseline_mib) if (max_used_mib is not None and baseline_mib is not None) else None,
        "torch_peak_allocated_mib_load": round(load_peak_mib, 1),
        "torch_peak_allocated_mib_run1": round(peak1, 1),
        "torch_peak_allocated_mib_run2": round(peak2, 1),
        "nvidia_smi_samples": len(sm),
    }
    RESULT["output"] = {
        "path": OUT_MP4,
        "size_bytes": os.path.getsize(OUT_MP4),
        "sha256": sha256_of(OUT_MP4),
        "ffprobe": ffprobe_triple(OUT_MP4),
        "second_encode": {"path": OUT_MP4_2, "size_bytes": os.path.getsize(OUT_MP4_2)},
        "end_to_end_decode": e2e,
    }
    RESULT["determinism"] = {
        "encode_md5_run1": md5_1,
        "encode_md5_run2": md5_2,
        "encode_md5_equal": md5_1 == md5_2,
        "frame_sample_indices": SAMPLE_IDX,
        "mae_per_sample": mae_samples,
        "mae_mean_sampled": round(float(np.mean(list(mae_samples.values()))), 4) if mae_samples else None,
        "mae_all_frames": mae_all,
        "note": "MAE=0 表示同 seed 逐比特可复现；>0 表示该硬件/内核路径存在非确定性",
    }
    RESULT["ok"] = len(RESULT["errors"]) == 0

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=2)
    os.chmod(OUT_JSON, 0o644)
    for p in (OUT_MP4, OUT_MP4_2):
        os.chmod(p, 0o644)
    log(f"完成 ok={RESULT['ok']} total_s={total_s:.1f} -> {OUT_JSON}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        RESULT["errors"].append(f"fatal: {e.__class__.__name__}: {e}")
        RESULT["ok"] = False
        try:
            with open(OUT_JSON, "w", encoding="utf-8") as f:
                json.dump(RESULT, f, ensure_ascii=False, indent=2)
            os.chmod(OUT_JSON, 0o644)
        except Exception:
            pass
        traceback.print_exc()
        raise SystemExit(1)
