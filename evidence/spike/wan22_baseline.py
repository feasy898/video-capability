#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wan2.2-TI2V-5B 单条基线 spike（v4 草稿层 T2 升级裁决实测数据）。

铁律执行环境：仅卡 0（CUDA_VISIBLE_DEVICES=0 由启动命令注入）。
产物：本目录 wan22_baseline.json / wan22_out.mp4 / wan22_out_encode2.mp4 / wan22_out_zh.mp4 / preview PNG。
参数：官方 README 720P 档口径 height=704 x width=1280（README「720P resolution is 1280*704 or 704*1280」，
      diffusers 用例 height=704,width=1280,num_frames=121,fps=24）/ 33 帧 / 50 步（官方用例值）/
      guidance_scale=5.0（guider 组件配置默认，与官方一致）/ seed 42 / fp16 全组件
      （torch_dtype=float16，等效官方 --convert_model_dtype；V100S cc7.0 bf16 禁用，白皮书结论）。
prompt：中英对照各一条（LTX 教训：T5 系中文出糊斑，Wan 的 UMT5 中文支持未知，需人检裁决）；
      negative_prompt 取官方 README 用例的中文负向词（Wan 官方推荐值，两语种统一）。
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
MODEL = "/data/night/models/Wan2.2-TI2V-5B"
OUT_MP4 = os.path.join(BASE, "wan22_out.mp4")
OUT_MP4_2 = os.path.join(BASE, "wan22_out_encode2.mp4")
OUT_MP4_ZH = os.path.join(BASE, "wan22_out_zh.mp4")
OUT_JSON = os.path.join(BASE, "wan22_baseline.json")
PREVIEW_EN = os.path.join(BASE, "preview_wan22_en_mid.png")
PREVIEW_ZH = os.path.join(BASE, "preview_wan22_zh_mid.png")

PROMPT_EN = "An orange cat sits on a windowsill basking in the sun, with slow-moving clouds outside the window."
PROMPT_ZH = "一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云"
NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，"
    "JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，"
    "形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)
HEIGHT, WIDTH = 704, 1280  # 720P 档，官方 README: height=704 width=1280（HxW）
NUM_FRAMES = 33            # 33 = 8*4+1，满足 Wan2.2 VAE 时间压缩 4x 约束 (F-1)%4==0
STEPS = 50                 # 官方 diffusers 用例值
GUIDANCE = 5.0             # guider 组件配置默认（ti2v-5B 官方值）
SEED = 42
FPS = 24
SAMPLE_IDX = [0, 8, 16, 24, 32]

RESULT = {
    "task": "wan22-ti2v-5b-spike",
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
    """每 2s 采样 nvidia-smi 卡 0/卡 1 已用显存（MiB）。卡 1 只读观测。"""

    def __init__(self, interval=2.0):
        self.interval = interval
        self.samples = []  # (t_offset_s, card0_mib, card1_mib)
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _query(self):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            vals = [int(x) for x in out.stdout.strip().splitlines()]
            return vals[0], vals[1] if len(vals) > 1 else None
        except Exception as e:  # noqa: BLE001
            RESULT["errors"].append(f"nvidia_smi_query_failed: {e}")
            return None, None

    def _run(self):
        while not self._stop.is_set():
            c0, c1 = self._query()
            if c0 is not None:
                self.samples.append((round(time.monotonic() - self._t0, 2), c0, c1))
            self._stop.wait(self.interval)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=15)


def to_np_uint8(videos):
    """pipeline 输出 -> np.uint8 (T,H,W,C)。布局自适应：找出 size==3 的通道轴移到最后。"""
    if isinstance(videos, (list, tuple)):
        videos = videos[0]
    if isinstance(videos, torch.Tensor):
        arr = videos.detach().float().cpu().numpy()
        src = "torch_tensor"
    else:
        arr = np.asarray(videos)
        src = type(videos).__name__
    in_shape = arr.shape
    arr = np.squeeze(arr)
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
    frame_mean = f.mean(axis=(1, 2, 3))
    black_thr = 2.0  # 帧均值 < 2/255 视为黑帧
    black = int((frame_mean < black_thr).sum())
    RESULT.setdefault("quality", {})[name] = {
        "nan_count": nan_count,
        "black_frames_lt2": black,
        "black_frame_ratio": round(black / arr.shape[0], 4),
        "frame_mean_min": round(float(frame_mean.min()), 3),
        "frame_mean_max": round(float(frame_mean.max()), 3),
        "frame_mean_overall": round(float(frame_mean.mean()), 3),
    }
    return arr


def save_preview(arr, path):
    """存中间帧 PNG（人检用）。"""
    from PIL import Image
    mid = arr[arr.shape[0] // 2]
    Image.fromarray(mid).save(path)
    os.chmod(path, 0o644)


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
        capture_output=True, timeout=300,
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


def l0_precheck(ffprobe_info, quality_info):
    """L0 预检替代口径（vpipe L0 未接入本次 spike，任务书允许替代）：
    黑场占比 <=50%（黑帧率替代黑场时长占比）+ 时长偏差 <=2%（期望 33/24=1.375s）。"""
    expect_dur = NUM_FRAMES / FPS
    dur = ffprobe_info.get("duration_s")
    dur_dev = None if dur is None else abs(dur - expect_dur) / expect_dur
    black_ratio = quality_info.get("black_frame_ratio", 1.0)
    passed = (black_ratio <= 0.5) and (dur_dev is not None and dur_dev <= 0.02)
    return {
        "criterion": "black_frame_ratio<=0.5 (替代黑场时长占比) AND duration_dev<=2% (expect 33/24=1.375s)",
        "black_frame_ratio": black_ratio,
        "duration_s": dur,
        "duration_dev": None if dur_dev is None else round(dur_dev, 5),
        "passed": bool(passed),
    }


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    RESULT["git_head"] = subprocess.run(
        ["git", "-C", os.path.dirname(BASE), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or "git_unavailable"
    RESULT["model"] = {"path": MODEL, "repo_downloaded": "Wan-AI/Wan2.2-TI2V-5B-Diffusers", "dtype": "float16"}
    RESULT["params"] = {
        "prompt_en": PROMPT_EN, "prompt_zh": PROMPT_ZH, "negative_prompt": NEGATIVE,
        "height": HEIGHT, "width": WIDTH,
        "num_frames": NUM_FRAMES, "num_inference_steps": STEPS,
        "guidance_scale": GUIDANCE, "seed": SEED, "fps_out": FPS,
        "resolution_note": "720P 档：官方 README「720P resolution of the Text-Image-to-Video task is 1280*704 or 704*1280」diffusers 用例 height=704,width=1280",
        "steps_note": "官方 diffusers 用例 num_inference_steps=50 / guidance_scale=5.0",
    }
    RESULT["gpu"] = {
        "name": torch.cuda.get_device_name(0),
        "capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
        "bf16_supported": torch.cuda.is_bf16_supported(),
        "bf16_used": False,
        "bf16_note": "torch 报 is_bf16_supported=True 为模拟路径（主控修正后口径），V100S 实跑仍全程 fp16",
    }
    log(f"GPU: {RESULT['gpu']['name']} cc={RESULT['gpu']['capability']}")

    sampler = NvidiaSampler().start()
    t_all = time.monotonic()

    # ---- 加载（全组件 fp16，手动构造 + update_components 注入）----
    # 注：diffusers 0.39.0 的 ModularPipeline.from_pretrained 对「仅有 model_index.json 的 legacy 仓」
    # 存在 UnboundLocalError（modular_model_index.json 缺失时 _blocks_class_name 分支未赋值），
    # 且 load_components 的 spec 无 repo 路径会空载——即 SPIKE-REPORT §3(a) 预警的「需适配层」。
    # 本适配：按 model_index.json 声明的类手动加载 5 组件（全 fp16），update_components 注入；
    # guider（CFG 5.0）/video_processor 由 blocks spec from_config 自动创建；transformer_2=null（TI2V 单模型官方形态）。
    from diffusers import (
        Wan22ModularPipeline,
        Wan22Blocks,
        WanTransformer3DModel,
        AutoencoderKLWan,
        UniPCMultistepScheduler,
    )
    from transformers import UMT5EncoderModel, AutoTokenizer

    t0 = time.monotonic()
    pipe = Wan22ModularPipeline(blocks=Wan22Blocks())
    transformer = WanTransformer3DModel.from_pretrained(MODEL, subfolder="transformer", torch_dtype=torch.float16)
    text_encoder = UMT5EncoderModel.from_pretrained(MODEL, subfolder="text_encoder", torch_dtype=torch.float16)
    tokenizer = AutoTokenizer.from_pretrained(MODEL, subfolder="tokenizer")
    vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float16)
    scheduler = UniPCMultistepScheduler.from_pretrained(MODEL, subfolder="scheduler")
    pipe.update_components(
        transformer=transformer, text_encoder=text_encoder, tokenizer=tokenizer, vae=vae, scheduler=scheduler
    )
    # TI2V-5B 单模型适配：Wan22LoopDenoiser 按 A14B MoE 双专家设计，t>=boundary→transformer，t<boundary→transformer_2（None→崩溃）。
    # boundary_ratio=0.0 使 t(≥0) 恒 >= boundary_timestep(0) → 全程走 transformer + guider(CFG 5.0)，
    # 等价官方 TI2V-5B 单模型全步 CFG5.0 语义。（首版误设 1.1 使条件恒假即崩，已修正——如实记录）
    pipe.update_components(boundary_ratio=0.0)
    # VAE 解码 tiling：720P 全帧 fp16 解码实测 OOM（需 1.72GiB 仅剩 220MiB，denoise 峰值 27.81GiB 分配后）。
    # enable_tiling 为 Wan 类模型产线标准配置（官方 4090 口径同样依赖），同配置下确定性不变。
    pipe.vae.enable_tiling()
    # VideoProcessor 显式 vae_scale_factor=16（Wan2.2 VAE 16x16 空间压缩，README 实证）：
    # from_config 默认 8（Wan2.1 值）→ latents 算大 4 倍，实跑输出 1408x2560（目标 2 倍边长），已修正。
    from diffusers.video_processor import VideoProcessor
    pipe.update_components(video_processor=VideoProcessor(vae_scale_factor=16))
    # vae_scale_factor_spatial 属性修正：ModularPipeline 用 2**len(temperal_downsample)=2**3=8（Wan2.1 启发式），
    # 而 Wan2.2 VAE config 显式 scale_factor_spatial=16 → latents 被算大 4 倍（88x160 而非 44x80），
    # 解码出 1408x2560 且 denoise 多耗 ~4x。此处仅运行时改类属性（内存补丁，不改 site-packages / 不改模型目录）。
    from diffusers.modular_pipelines.wan.modular_pipeline import WanModularPipeline as _WanMod

    def _vae_scale_factor_spatial(self):
        cfg = getattr(self.vae, "config", None)
        v = cfg.get("scale_factor_spatial") if cfg is not None and hasattr(cfg, "get") else None
        if v:
            return v
        return 2 ** len(getattr(self.vae, "temperal_downsample", []))

    _WanMod.vae_scale_factor_spatial = property(_vae_scale_factor_spatial)
    RESULT["vae_scale_factors"] = {
        "spatial": pipe.vae_scale_factor_spatial,
        "temporal": pipe.vae_scale_factor_temporal,
    }
    pipe.to("cuda")
    load_s = time.monotonic() - t0
    load_peak_mib = torch.cuda.max_memory_allocated() / 2**20
    torch.cuda.reset_peak_memory_stats()
    RESULT["pipeline"] = {
        "class": type(pipe).__name__,
        "adapter": "manual component load + update_components (diffusers 0.39.0 from_pretrained 对 legacy 仓崩溃，见脚本头注)",
        "boundary_ratio": 0.0,
        "boundary_note": "TI2V-5B 单模型适配：t>=0 恒真 → 恒走 transformer 分支（官方单模型 CFG5.0 等价语义）",
        "guidance_scale_config": (getattr(pipe, "guider").config.get("guidance_scale") if hasattr(pipe, "guider") and getattr(pipe, "guider", None) is not None else None),
        "scheduler_class": type(getattr(pipe, "scheduler", None)).__name__,
        "transformer_class": type(getattr(pipe, "transformer", None)).__name__,
        "transformer_dtype": str(getattr(getattr(pipe, "transformer", None), "dtype", "n/a")),
        "text_encoder_dtype": str(getattr(getattr(pipe, "text_encoder", None), "dtype", "n/a")),
        "vae_dtype": str(getattr(getattr(pipe, "vae", None), "dtype", "n/a")),
        "vae_tiling": bool(getattr(getattr(pipe, "vae", None), "use_tiling", False)),
        "vae_tiling_config": {
            k: getattr(getattr(pipe, "vae", None), k, None)
            for k in ("tile_sample_min_height", "tile_sample_min_width", "tile_sample_stride", "use_tiling")
        },
        "video_processor_scale": getattr(getattr(pipe, "video_processor", None), "config", {}).get("vae_scale_factor") if hasattr(getattr(pipe, "video_processor", None), "config") else None,
    }
    log(f"模型加载完成 load_s={load_s:.1f} load_peak={load_peak_mib:.0f}MiB pipeline={RESULT['pipeline']}")

    def gen_once(tag, prompt):
        g = torch.Generator(device="cuda").manual_seed(SEED)
        t = time.monotonic()
        with torch.inference_mode():
            videos = pipe(
                prompt=prompt, negative_prompt=NEGATIVE,
                height=HEIGHT, width=WIDTH,
                num_frames=NUM_FRAMES,
                num_inference_steps=STEPS,
                generator=g,
                output="videos",
            )
        torch.cuda.synchronize()
        dt = time.monotonic() - t
        peak = torch.cuda.max_memory_allocated() / 2**20
        torch.cuda.reset_peak_memory_stats()
        log(f"{tag}: gen_s={dt:.1f} peak={peak:.0f}MiB")
        return videos, dt, peak

    # ---- Run A：英文 prompt 主跑 ----
    videos_A, gen_en_s, peak_en = gen_once("run_en", PROMPT_EN)
    arr_A = to_np_uint8(videos_A)
    frames_stats("run_en", arr_A)
    save_preview(arr_A, PREVIEW_EN)

    nan_A = RESULT["quality"]["run_en"]["nan_count"]
    if nan_A > 0:
        RESULT["errors"].append(f"run_en NaN={nan_A}: fp16 风险，VAE 升 fp32 重解码（不重跑 transformer）")
        log("检测到 NaN，VAE 升 fp32 后重跑同 seed 生成（预案，记录为 rerun）")
        pipe.vae.to(torch.float32)
        videos_A, gen_en_s, peak_en = gen_once("run_en_vae_fp32_rerun", PROMPT_EN)
        arr_A = to_np_uint8(videos_A)
        frames_stats("run_en_vae_fp32_rerun", arr_A)
        save_preview(arr_A, PREVIEW_EN)
        RESULT["vae_fp32_fallback"] = True

    # ---- 编码两遍（确定性验证）----
    enc_en1_s, md5_en1 = encode_video(arr_A, OUT_MP4)
    enc_en2_s, md5_en2 = encode_video(arr_A, OUT_MP4_2)
    log(f"encode1={enc_en1_s}s md5={md5_en1} | encode2={enc_en2_s}s md5={md5_en2} equal={md5_en1 == md5_en2}")

    # ---- Run B：同 seed 二遍生成（确定性）----
    videos_B, gen_en2_s, peak_en2 = gen_once("run_en_2nd", PROMPT_EN)
    arr_B = to_np_uint8(videos_B)
    frames_stats("run_en_2nd", arr_B)

    a = arr_A.astype(np.float32)
    b = arr_B.astype(np.float32)
    n = min(a.shape[0], b.shape[0])
    mae_samples = {}
    for i in SAMPLE_IDX:
        if i < n:
            mae_samples[str(i)] = round(float(np.abs(a[i] - b[i]).mean()), 4)
    mae_all = round(float(np.abs(a[:n] - b[:n]).mean()), 4)
    log(f"确定性: 5帧抽样MAE={mae_samples} 全帧MAE={mae_all}")

    # ---- Run C：中文 prompt 对照 ----
    videos_C, gen_zh_s, peak_zh = gen_once("run_zh", PROMPT_ZH)
    arr_C = to_np_uint8(videos_C)
    frames_stats("run_zh", arr_C)
    save_preview(arr_C, PREVIEW_ZH)
    enc_zh_s, md5_zh = encode_video(arr_C, OUT_MP4_ZH)

    # ---- 端到端回检 ----
    e2e = decode_mp4_check(OUT_MP4)

    sampler.stop()
    total_s = time.monotonic() - t_all
    sm0 = [s for _, s, _ in sampler.samples]
    sm1 = [s for _, _, s in sampler.samples if s is not None]
    baseline_mib = sm0[0] if sm0 else None
    max_used_mib = max(sm0) if sm0 else None

    RESULT["timing_s"] = {
        "load": round(load_s, 2),
        "gen_run_en": round(gen_en_s, 2),
        "gen_run_en_2nd": round(gen_en2_s, 2),
        "gen_run_zh": round(gen_zh_s, 2),
        "encode_en_run1": enc_en1_s,
        "encode_en_run2": enc_en2_s,
        "encode_zh": enc_zh_s,
        "total": round(total_s, 2),
    }
    RESULT["vram"] = {
        "baseline_used_mib": baseline_mib,
        "nvidia_smi_max_used_mib_card0": max_used_mib,
        "nvidia_smi_delta_mib_card0": (max_used_mib - baseline_mib) if (max_used_mib is not None and baseline_mib is not None) else None,
        "card1_max_used_mib_untouched": max(sm1) if sm1 else None,
        "torch_peak_allocated_mib_load": round(load_peak_mib, 1),
        "torch_peak_allocated_mib_run_en": round(peak_en, 1),
        "torch_peak_allocated_mib_run_en_2nd": round(peak_en2, 1),
        "torch_peak_allocated_mib_run_zh": round(peak_zh, 1),
        "nvidia_smi_samples": len(sm0),
    }
    RESULT["output"] = {
        "path": OUT_MP4,
        "size_bytes": os.path.getsize(OUT_MP4),
        "sha256": sha256_of(OUT_MP4),
        "ffprobe": ffprobe_triple(OUT_MP4),
        "second_encode": {"path": OUT_MP4_2, "size_bytes": os.path.getsize(OUT_MP4_2)},
        "zh_output": {"path": OUT_MP4_ZH, "size_bytes": os.path.getsize(OUT_MP4_ZH), "md5": md5_zh, "ffprobe": ffprobe_triple(OUT_MP4_ZH)},
        "end_to_end_decode": e2e,
    }
    RESULT["determinism"] = {
        "encode_md5_run1": md5_en1,
        "encode_md5_run2": md5_en2,
        "encode_md5_equal": md5_en1 == md5_en2,
        "frame_sample_indices": SAMPLE_IDX,
        "mae_per_sample": mae_samples,
        "mae_mean_sampled": round(float(np.mean(list(mae_samples.values()))), 4) if mae_samples else None,
        "mae_all_frames": mae_all,
        "note": "MAE=0 表示同 seed 逐比特可复现；>0 表示该硬件/内核路径存在非确定性",
    }
    RESULT["l0_precheck_substitute"] = l0_precheck(RESULT["output"]["ffprobe"], RESULT["quality"]["run_en"])
    RESULT["ok"] = len(RESULT["errors"]) == 0

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=2)
    os.chmod(OUT_JSON, 0o644)
    for p in (OUT_MP4, OUT_MP4_2, OUT_MP4_ZH):
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
