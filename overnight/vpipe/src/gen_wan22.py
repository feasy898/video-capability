#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_wan22.py — vpipe Wan2.2-TI2V-5B 质轨生成模块（T2 双轨制·质轨）。

TASK_v4 §8 决策 g（2026-10-09-g）上线前置条件：把 spike 脚本
（evidence/spike/wan22_baseline.py）内 4 处 diffusers 0.39.0 不兼容内存补丁固化为仓内模块。
spike 实测基准：evidence/spike/wan22_baseline.json（ok=true / 同 seed MAE=0 逐比特 /
峰值 25.04GiB / 1280x704@24fps 原生直出）；不兼容明细：SPIKE-REPORT §7.2。

契约: --prompt / --prompt-file 一条文本 → <out>/wan22_out.mp4 + <out>/wan22_meta.json。
      单文件，不 import 任何 vpipe 兄弟模块。
铁律: 只卡 0——启动即强制 CUDA_VISIBLE_DEVICES=0（env VPIPE_WAN22_CUDA_DEVICES 可覆盖）；
      发车前 nvidia-smi 复测卡 0 已用显存 ≤1024MiB，超限 fail-closed 拒发；卡 1 只读观测。
      不 kill / 不 pip install / 不下载（HF_HUB_OFFLINE=1 + TRANSFORMERS_OFFLINE=1，
      权重只读 /data/night/models/Wan2.2-TI2V-5B）；全部产物 chmod 644。
      补丁全部是内存态（类属性/组件注入），零 site-packages / 零模型目录改动。
确定性: torch.Generator(device="cuda").manual_seed(--seed，缺省 42)；guidance 缺省不显式
      下发（guider 组件配置默认 5.0，与 spike/官方一致）；--determinism-runs ≥2 时同 seed
      二跑并记录帧级 MAE（spike 实测 MAE=0 逐比特复现）。
四处补丁（diffusers 0.39.0 × Wan2.2，SPIKE-REPORT §7.2，本模块唯一事实源是
apply_compat_patches + load_components_manual）:
  #1 ModularPipeline.from_pretrained 对仅有 model_index.json 的 legacy 仓崩溃
     （UnboundLocalError: blocks_class）→ load_components_manual(): 按声明类手动加载
     5 组件（全 fp16）+ update_components 注入
  #2 Wan22LoopDenoiser 按 A14B MoE 双专家写死，t<boundary 取 transformer_2=None 崩
     → patch_boundary_ratio(0.0): t>=0 恒走 transformer + guider(CFG 5.0)，官方单模型等价语义
  #3 vae_scale_factor_spatial 用 Wan2.1 启发式 2**len(temperal_downsample)=8 ≠ Wan2.2 VAE
     config scale_factor_spatial=16（latents 算大 4 倍 → 输出 1408x2560、denoise 慢 9.15 倍）
     → patch_vae_scale_factor_spatial(): 运行时类属性 property 读 VAE config
  #4 VideoProcessor from_config 默认 vae_scale_factor=8（与 #3 同源的后处理缩放错误）
     → patch_video_processor(16): 显式构造 VideoProcessor(vae_scale_factor=16)
  另: 720P 全帧 fp16 VAE 解码 OOM（spike 实测需 1.72GiB 仅剩 220MiB）→ vae.enable_tiling()
     （tile 256x256，Wan 类模型产线标准配置，属性能配置非兼容性补丁）。

用法（GPU 机 anolis-gpu-01，/data/night/venv）:
  python3 src/gen_wan22.py --dry-run --model /data/night/models/Wan2.2-TI2V-5B
  python3 src/gen_wan22.py --prompt "一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云" --zh \
      --seed 42 --frames 33 --steps 50 --out /tmp/wan22_out
  python3 src/gen_wan22.py --prompt-file p.txt --determinism-runs 2   # 同 seed 二跑 MAE
自测: python3 tests/test_gen_wan22.py   （mock 级，零 GPU，无 pytest 依赖）
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

# 铁律：只卡 0（默认物理卡 0；VPIPE_WAN22_CUDA_DEVICES 可显式覆盖；卡 1 共享常驻，不碰）
os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.environ.get("VPIPE_WAN22_CUDA_DEVICES", "0"))
# 不下载：权重本地目录直读，任何 hub 回源都视为事故（spike 同款双保险）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent          # overnight/vpipe/src
REPO_ROOT = HERE.parents[2]                     # 仓根

DEFAULT_MODEL_DIR = "/data/night/models/Wan2.2-TI2V-5B"
REQUIRED_SUBDIRS = ("transformer", "text_encoder", "tokenizer", "vae", "scheduler")
HEIGHT, WIDTH = 704, 1280   # 官方 README 720P 档：「720P resolution is 1280*704 or 704*1280」
DEFAULT_FRAMES = 33         # 33 = 8*4+1，满足 Wan2.2 VAE 时间压缩 4x 约束 (F-1)%4==0
DEFAULT_STEPS = 50          # 官方 diffusers 用例值
GUIDANCE_DEFAULT = 5.0      # guider 组件配置默认（ti2v-5B 官方值；缺省不显式下发）
DEFAULT_SEED = 42
FPS = 24
BOUNDARY_RATIO = 0.0        # 补丁 #2
VAE_SCALE_SPATIAL = 16      # 补丁 #3 / #4（Wan2.2 VAE 16x16 空间压缩，README 实证）
CARD0_LIMIT_MIB = 1024      # 发车前复测门槛：卡 0 已用显存 ≤1GiB 才发

PROMPT_ZH_CANONICAL = "一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云"   # spike 金标准中文 prompt
# 官方 README 用例中文负向词（Wan 官方推荐值，两语种统一，与 spike 逐字节一致）
NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，"
    "JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，"
    "形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)

# 四处补丁登记表：meta 兜底记录 + 单测断言来源（明细：SPIKE-REPORT §7.2 表格）
COMPAT_PATCHES_SPEC = {
    "1": {
        "name": "manual_component_load",
        "defect": ("diffusers 0.39.0 ModularPipeline.from_pretrained 对仅有 model_index.json 的 legacy 仓"
                   "（无 modular_model_index.json）崩溃：load_config 把 model_index.json 当 modular config "
                   "读回，_blocks_class_name 分支未赋值 → UnboundLocalError: blocks_class"),
        "fix": ("按 model_index.json 声明的类手动加载 5 组件（WanTransformer3DModel/UMT5EncoderModel/"
                "AutoTokenizer/AutoencoderKLWan/UniPCMultistepScheduler，全 fp16）+ update_components 注入；"
                "guider（CFG 5.0）/video_processor 由 blocks spec from_config 自动创建"),
    },
    "2": {
        "name": "boundary_ratio_zero",
        "defect": ("Wan22LoopDenoiser 按 A14B MoE 双专家写死：t<boundary 取 transformer_2"
                   "（TI2V-5B 单模型 model_index 中 transformer_2=null）→ 首个低噪步 "
                   "'NoneType' object is not callable（默认 boundary 0.875 实崩）"),
        "fix": ("update_components(boundary_ratio=0.0) 使 t>=0 恒走 transformer 分支 + guider(CFG 5.0)，"
                "等价官方 TI2V-5B 单模型全步 CFG5.0 语义（spike 首试误设 1.1 方向反即崩，已修正并如实记录）"),
    },
    "3": {
        "name": "vae_scale_factor_spatial_config",
        "defect": ("ModularPipeline.vae_scale_factor_spatial 属性用 Wan2.1 启发式 "
                   "2**len(temperal_downsample)=8，而 Wan2.2 VAE config 显式 scale_factor_spatial=16 "
                   "→ latents 算大 4 倍（88x160 而非 44x80）：解码出 1408x2560（目标 2 倍边长）、"
                   "denoise 慢 9.15 倍（38.3→4.19 s/it）"),
        "fix": ("运行时改类属性 property：优先读 vae.config.scale_factor_spatial，回退启发式 "
                "2**len(temperal_downsample)（内存补丁，零 site-packages / 零模型目录改动）"),
    },
    "4": {
        "name": "video_processor_scale16",
        "defect": ("VideoProcessor 由 blocks spec from_config 创建时默认 vae_scale_factor=8"
                   "（Wan2.1 值），与 #3 同源的后处理缩放错误"),
        "fix": "update_components(video_processor=VideoProcessor(vae_scale_factor=16)) 显式覆盖",
    },
}


class CompatPatchError(RuntimeError):
    """补丁应用失败——fail-closed，绝不允许带病发车。"""

    def __init__(self, patch_id, cause):
        super().__init__(f"compat patch #{patch_id} 应用失败: {cause}")
        self.patch_id = patch_id


def log(msg):
    print(f"[gen_wan22 {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def git_head():
    try:
        p = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=15)
        return p.stdout.strip() or "git_unavailable"
    except Exception:
        return "git_unavailable"


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- 显存观测（spike 同款）

class NvidiaSampler:
    """每 2s 采样 nvidia-smi 物理卡 0/卡 1 已用显存（MiB）。卡 1 只读观测，不碰。"""

    def __init__(self, meta, interval=2.0):
        self.interval = interval
        self.meta = meta
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
            self.meta["errors"].append(f"nvidia_smi_query_failed: {e}")
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


def preflight_card0(meta, limit_mib=CARD0_LIMIT_MIB):
    """铁律复测：发车前卡 0 已用显存必须 ≤ limit。返回 (ok, card0_mib, card1_mib)。"""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
        )
        used = {}
        for line in p.stdout.strip().splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 2 and parts[0].isdigit():
                used[int(parts[0])] = int(parts[1])
        c0, c1 = used.get(0), used.get(1)
        meta["gpu_preflight"] = {"card0_used_mib": c0, "card1_used_mib": c1,
                                 "limit_mib": limit_mib, "at": now_iso()}
        if c0 is None:
            meta["errors"].append("preflight_fail: nvidia-smi 读不到卡 0 显存，拒发（fail-closed）")
            return False, c0, c1
        if c0 > limit_mib:
            meta["errors"].append(
                f"preflight_fail: 卡 0 已用 {c0}MiB > {limit_mib}MiB（只卡 0 且跑前复测红线），拒发")
            return False, c0, c1
        return True, c0, c1
    except Exception as e:  # noqa: BLE001
        meta["errors"].append(f"preflight_fail: nvidia-smi 不可用: {e}")
        meta["gpu_preflight"] = {"limit_mib": limit_mib, "at": now_iso()}
        return False, None, None


# ---------------------------------------------------------------- 补丁 #1：手动组件加载

def validate_model_dir(model_dir):
    """权重目录预检（fail-closed 第一道）。返回 (present: bool, missing: list[str])。"""
    d = Path(model_dir)
    if not d.is_dir():
        return False, ["<model_dir>"]
    missing = [n for n in ("model_index.json", *REQUIRED_SUBDIRS) if not (d / n).exists()]
    return (not missing), missing


def load_components_manual(model_dir, dtype=None):
    """补丁 #1：按 model_index.json 声明类手动加载 5 组件（spike wan22_baseline.py:281-285 逐行等价）。

    缺陷见 COMPAT_PATCHES_SPEC["1"]。diffusers 0.39.0 的 ModularPipeline.from_pretrained
    对 legacy 仓（仅 model_index.json，无 modular_model_index.json）UnboundLocalError，
    load_components 的 spec 无 repo 路径会空载——故绕开官方加载路径，手动加载后 update_components 注入。
    """
    import torch
    from diffusers import (
        WanTransformer3DModel,
        AutoencoderKLWan,
        UniPCMultistepScheduler,
    )
    from transformers import UMT5EncoderModel, AutoTokenizer

    if dtype is None:
        dtype = torch.float16   # fp16 全组件：V100S cc7.0 bf16 禁用（白皮书结论），等效官方 --convert_model_dtype

    ok, missing = validate_model_dir(model_dir)
    if not ok:
        raise FileNotFoundError(f"权重目录不完整: {model_dir} 缺 {missing}")

    # 加载次序与 spike 逐行一致（transformer→text_encoder→tokenizer→vae→scheduler）
    return {
        "transformer": WanTransformer3DModel.from_pretrained(model_dir, subfolder="transformer", torch_dtype=dtype),
        "text_encoder": UMT5EncoderModel.from_pretrained(model_dir, subfolder="text_encoder", torch_dtype=dtype),
        "tokenizer": AutoTokenizer.from_pretrained(model_dir, subfolder="tokenizer"),
        "vae": AutoencoderKLWan.from_pretrained(model_dir, subfolder="vae", torch_dtype=dtype),
        "scheduler": UniPCMultistepScheduler.from_pretrained(model_dir, subfolder="scheduler"),
    }


# ---------------------------------------------------------------- 补丁 #2/#3/#4

def patch_boundary_ratio(pipe, ratio=BOUNDARY_RATIO):
    """补丁 #2：boundary_ratio=0.0（spike wan22_baseline.py:292 等价）。

    Wan22LoopDenoiser 按 A14B MoE 双专家设计：t>=boundary → transformer，t<boundary →
    transformer_2（TI2V-5B 为 None → 'NoneType' object is not callable）。
    boundary_ratio=0.0 使 t(≥0) 恒 >= boundary_timestep(0) → 全程走 transformer + guider(CFG 5.0)，
    等价官方 TI2V-5B 单模型全步 CFG5.0 语义。
    """
    pipe.update_components(boundary_ratio=ratio)
    ev = {"patch_id": "2", "name": COMPAT_PATCHES_SPEC["2"]["name"], "applied": True,
          "boundary_ratio": ratio}
    ev.update(COMPAT_PATCHES_SPEC["2"])
    return ev


def patch_vae_scale_factor_spatial(cls=None):
    """补丁 #3：运行时类属性 property 修正 vae_scale_factor_spatial（spike wan22_baseline.py:303-312 逐行等价）。

    ModularPipeline 原属性用 2**len(temperal_downsample)（Wan2.1 启发式 =8），Wan2.2 VAE config
    显式 scale_factor_spatial=16 → latents 被算大 4 倍。此处仅内存改类属性：
    优先读 vae.config.scale_factor_spatial，缺失时回退原启发式（行为保守降级，不掩盖真值）。
    零 site-packages / 零模型目录改动。
    """
    if cls is None:
        from diffusers.modular_pipelines.wan.modular_pipeline import WanModularPipeline as cls

    def _vae_scale_factor_spatial(self):
        cfg = getattr(self.vae, "config", None)
        v = cfg.get("scale_factor_spatial") if cfg is not None and hasattr(cfg, "get") else None
        if v:
            return v
        return 2 ** len(getattr(self.vae, "temperal_downsample", []))

    cls.vae_scale_factor_spatial = property(_vae_scale_factor_spatial)
    return {"patch_id": "3", "name": COMPAT_PATCHES_SPEC["3"]["name"], "applied": True,
            "target_class": f"{cls.__module__}.{cls.__qualname__}",
            "expected_value": VAE_SCALE_SPATIAL}
    # 注意：返回前不读属性（实例此时可能缺 vae），实际落地值由 verify_pipeline_state 核验


def patch_video_processor(pipe, vae_scale_factor=VAE_SCALE_SPATIAL):
    """补丁 #4：显式 VideoProcessor(vae_scale_factor=16)（spike wan22_baseline.py:298-299 等价）。

    VideoProcessor 由 blocks spec from_config 创建时默认 vae_scale_factor=8（Wan2.1 值），
    与补丁 #3 同源的后处理缩放错误——显式构造 16 覆盖。
    """
    from diffusers.video_processor import VideoProcessor
    vp = VideoProcessor(vae_scale_factor=vae_scale_factor)
    pipe.update_components(video_processor=vp)
    ev = {"patch_id": "4", "name": COMPAT_PATCHES_SPEC["4"]["name"], "applied": True,
          "vae_scale_factor": vae_scale_factor}
    ev.update(COMPAT_PATCHES_SPEC["4"])
    return ev


def apply_compat_patches(pipe, boundary_ratio=BOUNDARY_RATIO,
                         vae_scale_factor=VAE_SCALE_SPATIAL, wan_modular_cls=None):
    """四处补丁中 pipe 级的三处（#2 → #4 → #3）统一入口；#1 在 build_pipeline 的加载步。

    任一失败抛 CompatPatchError（带补丁号）→ 调用方 fail-closed。
    幂等：全部操作是「赋值型」（组件覆盖/类属性覆盖），双调结果与单调一致（单测 A 组断言）。
    """
    steps = (
        ("2", lambda: patch_boundary_ratio(pipe, boundary_ratio)),
        ("4", lambda: patch_video_processor(pipe, vae_scale_factor)),
        ("3", lambda: patch_vae_scale_factor_spatial(wan_modular_cls)),
    )
    evidence = {}
    for pid, fn in steps:
        try:
            evidence[pid] = fn()
        except CompatPatchError:
            raise
        except Exception as e:  # noqa: BLE001
            raise CompatPatchError(pid, f"{type(e).__name__}: {e}") from e
    return evidence


def enable_vae_tiling(vae):
    """VAE 解码 tiling（非兼容性补丁）：720P 全帧 fp16 解码实测 OOM（需 1.72GiB、
    denoise 峰值后仅剩 220MiB）；tile 256x256 为 Wan 类模型产线标准配置（官方 4090 口径同样依赖），
    同配置下确定性不变（spike 编码 md5 两遍相等 + 同 seed MAE=0 实证）。"""
    vae.enable_tiling()
    return {"applied": True, "note": "性能配置（非四处兼容补丁），spike 同款"}


def verify_pipeline_state(pipe):
    """补丁落地核验：四补丁+tiling 的期望值逐项回读，任何一项不符 → fail-closed 拒发。"""
    checks = []

    boundary = getattr(pipe, "boundary_ratio", None)
    checks.append(("boundary_ratio==0.0（补丁#2）", boundary == BOUNDARY_RATIO, boundary))

    try:
        spatial = pipe.vae_scale_factor_spatial
    except Exception as e:  # noqa: BLE001
        spatial = f"unreadable: {e}"
    checks.append(("vae_scale_factor_spatial==16（补丁#3）", spatial == VAE_SCALE_SPATIAL, spatial))

    vp = getattr(pipe, "video_processor", None)
    vp_cfg = getattr(vp, "config", None) or {}
    vp_scale = vp_cfg.get("vae_scale_factor") if hasattr(vp_cfg, "get") else None
    checks.append(("video_processor.vae_scale_factor==16（补丁#4）", vp_scale == VAE_SCALE_SPATIAL, vp_scale))

    vae = getattr(pipe, "vae", None)
    use_tiling = getattr(vae, "use_tiling", None)
    checks.append(("vae.use_tiling is True", use_tiling is True, use_tiling))

    failed = [c for c in checks if not c[1]]
    record = [{"check": name, "ok": bool(ok), "observed": observed} for name, ok, observed in checks]
    if failed:
        raise CompatPatchError("verify", "; ".join(f"{n} (observed={o!r})" for n, _, o in failed))
    return record


# ---------------------------------------------------------------- pipeline 组装（spike 逐行等价）

def build_pipeline(model_dir, dtype=None):
    """组装 Wan22ModularPipeline。次序对应 spike wan22_baseline.py:280-317：
    建 pipe → 补丁#1 手动加载 5 组件 → update_components → #2 → tiling → #4 → #3 → to(cuda)。
    本模块把 #2/#4/#3 归组进 apply_compat_patches（赋值型配置互不依赖，次序无行为影响），
    与 spike 的行为逐字节等价由 GPU 同参 sha256 复现闭环证明（evidence/wan22_compat_verify_*.json）。
    返回 (pipe, build_info)。"""
    import torch
    from diffusers import Wan22ModularPipeline, Wan22Blocks

    if dtype is None:
        dtype = torch.float16

    t0 = time.monotonic()
    pipe = Wan22ModularPipeline(blocks=Wan22Blocks())
    components = load_components_manual(model_dir, dtype=dtype)          # 补丁 #1
    pipe.update_components(**components)
    patch_evidence = apply_compat_patches(pipe)                          # 补丁 #2 #4 #3
    tiling_evidence = enable_vae_tiling(pipe.vae)
    patch_evidence["tiling"] = tiling_evidence
    pipe.to("cuda")

    load_s = time.monotonic() - t0
    load_peak_mib = torch.cuda.max_memory_allocated() / 2 ** 20
    torch.cuda.reset_peak_memory_stats()

    guider = getattr(pipe, "guider", None)
    guider_cfg = getattr(guider, "config", None) or {}
    build_info = {
        "load_s": round(load_s, 2),
        "load_peak_allocated_mib": round(load_peak_mib, 1),
        "compat_patches": patch_evidence,
        "pipeline": {
            "class": type(pipe).__name__,
            "adapter": ("gen_wan22 固化适配层：手动组件加载 + update_components + "
                        "apply_compat_patches（diffusers 0.39.0 from_pretrained 对 legacy 仓崩溃，"
                        "SPIKE-REPORT §7.2）"),
            "boundary_ratio": getattr(pipe, "boundary_ratio", None),
            "guidance_scale_config": guider_cfg.get("guidance_scale") if hasattr(guider_cfg, "get") else None,
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
            "video_processor_scale": (getattr(getattr(pipe, "video_processor", None), "config", {}).get("vae_scale_factor")
                                      if hasattr(getattr(pipe, "video_processor", None), "config") else None),
        },
        "vae_scale_factors": {
            "spatial": pipe.vae_scale_factor_spatial,
            "temporal": pipe.vae_scale_factor_temporal,
        },
    }
    return pipe, build_info


# ---------------------------------------------------------------- 帧处理/质检（spike 逐行等价）

def to_np_uint8(videos, num_frames, height, width, meta, tag):
    """pipeline 输出 → np.uint8 (T,H,W,C)。布局自适应：找出 size==3 的通道轴移到最后。"""
    import numpy as np
    import torch
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
    if arr.shape != (num_frames, height, width, 3):
        raise ValueError(f"unexpected final shape {arr.shape}, in={in_shape} src={src}")
    meta.setdefault("frames_layout", []).append(
        {"run": tag, "src": src, "in_shape": list(in_shape), "out_shape": list(arr.shape)})
    return arr


def frames_stats(name, arr, meta):
    """黑帧/NaN/每帧均值统计。arr: uint8 (T,H,W,C)。"""
    import numpy as np
    f = arr.astype(np.float32)
    nan_count = int(np.isnan(f).sum())
    frame_mean = f.mean(axis=(1, 2, 3))
    black_thr = 2.0  # 帧均值 < 2/255 视为黑帧
    black = int((frame_mean < black_thr).sum())
    rec = {
        "nan_count": nan_count,
        "black_frames_lt2": black,
        "black_frame_ratio": round(black / arr.shape[0], 4),
        "frame_mean_min": round(float(frame_mean.min()), 3),
        "frame_mean_max": round(float(frame_mean.max()), 3),
        "frame_mean_overall": round(float(frame_mean.mean()), 3),
    }
    meta.setdefault("quality", {})[name] = rec
    return rec


def save_preview(arr, path):
    """存中间帧 PNG（人检用）。"""
    from PIL import Image
    mid = arr[arr.shape[0] // 2]
    Image.fromarray(mid).save(path)
    os.chmod(path, 0o644)


def encode_video(arr, path, fps=FPS):
    """diffusers export_to_video 固定参数编码（与 spike 同一函数同一参数），返回 (耗时s, md5, sha256)。"""
    from diffusers.utils import export_to_video
    t0 = time.monotonic()
    export_to_video(arr, fps=fps, output_video_path=str(path))
    dt = round(time.monotonic() - t0, 3)
    with open(path, "rb") as fp:
        data = fp.read()
    return dt, hashlib.md5(data).hexdigest(), sha256_file(path)


def ffprobe_triple(path, meta):
    p = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if p.returncode != 0:
        meta["errors"].append(f"ffprobe_failed rc={p.returncode}")
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


def decode_mp4_check(path, num_frames, height, width, meta):
    """端到端回检：ffmpeg 解码 mp4 → rawvideo，查帧数/黑帧。"""
    import numpy as np
    p = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=300,
    )
    if p.returncode != 0 or not p.stdout:
        meta["errors"].append(f"mp4_decode_failed rc={p.returncode}")
        return None
    raw = np.frombuffer(p.stdout, dtype=np.uint8)
    n_frames = len(raw) // (height * width * 3)
    arr = raw[: n_frames * height * width * 3].reshape(n_frames, height, width, 3)
    mean = arr.astype(np.float32).mean(axis=(1, 2, 3))
    return {
        "decoded_frames": int(n_frames),
        "black_frames_lt2": int((mean < 2.0).sum()),
        "frame_mean_min": round(float(mean.min()), 3),
        "frame_mean_overall": round(float(mean.mean()), 3),
        "decode_rc": p.returncode,
    }


def l0_precheck(ffprobe_info, quality_info, num_frames, fps=FPS):
    """L0 预检替代口径（vpipe L0 未接入，任务书允许替代，与 spike/LTX 同口径）：
    黑帧占比 ≤50%（黑帧率替代黑场时长占比）+ 时长偏差 ≤2%。"""
    expect_dur = num_frames / fps
    dur = ffprobe_info.get("duration_s")
    dur_dev = None if dur is None else abs(dur - expect_dur) / expect_dur
    black_ratio = quality_info.get("black_frame_ratio", 1.0)
    passed = (black_ratio <= 0.5) and (dur_dev is not None and dur_dev <= 0.02)
    return {
        "criterion": f"black_frame_ratio<=0.5 (替代黑场时长占比) AND duration_dev<=2% (expect {num_frames}/{fps}={expect_dur}s)",
        "black_frame_ratio": black_ratio,
        "duration_s": dur,
        "duration_dev": None if dur_dev is None else round(dur_dev, 5),
        "passed": bool(passed),
    }


def mae_record(arr_a, arr_b, sample_idx):
    """同 seed 两跑帧级 MAE（spike determinism 口径）。"""
    import numpy as np
    a = arr_a.astype(np.float32)
    b = arr_b.astype(np.float32)
    n = min(a.shape[0], b.shape[0])
    per = {str(i): round(float(np.abs(a[i] - b[i]).mean()), 4) for i in sample_idx if i < n}
    return per, round(float(np.abs(a[:n] - b[:n]).mean()), 4)


def sample_indices(num_frames):
    """5 帧抽样位：{0, F//4, F//2, 3F//4, F-1}；F=33 → [0,8,16,24,32]（与 spike 一致）。"""
    return sorted({0, num_frames // 4, num_frames // 2, (3 * num_frames) // 4, num_frames - 1})


# ---------------------------------------------------------------- CLI

def build_parser():
    ap = argparse.ArgumentParser(
        description="gen_wan22：Wan2.2-TI2V-5B 质轨生成（diffusers 0.39.0 四处不兼容固化补丁；只卡 0）")
    ap.add_argument("--prompt", default=None, help="prompt 文本；缺省用 spike 中文金标准 prompt")
    ap.add_argument("--prompt-file", dest="prompt_file", default=None,
                    help="从 UTF-8 文本文件读 prompt（覆盖 --prompt）")
    ap.add_argument("--zh", action="store_true",
                    help="标记 prompt 为中文（meta lang=zh；UMT5 中文直喂可用，SPIKE-REPORT §7.4）")
    ap.add_argument("--out", default="./wan22_out", help="输出目录（默认 ./wan22_out）")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"随机种子（默认 {DEFAULT_SEED}）")
    ap.add_argument("--frames", type=int, default=DEFAULT_FRAMES,
                    help=f"帧数，须满足 (F-1)%%4==0（默认 {DEFAULT_FRAMES}）")
    ap.add_argument("--steps", type=int, default=DEFAULT_STEPS, help=f"去噪步数（默认 {DEFAULT_STEPS}）")
    ap.add_argument("--guidance", type=float, default=None,
                    help="显式 guidance_scale；缺省不下发（guider 组件配置默认 5.0，与 spike/官方一致）")
    ap.add_argument("--determinism-runs", dest="determinism_runs", type=int, default=1,
                    help=">=2 时同 seed 二跑并记录帧级 MAE（默认 1）")
    ap.add_argument("--model", default=DEFAULT_MODEL_DIR, help="权重目录（本地只读）")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="只做参数与权重目录预检，零模型加载零 GPU")
    return ap


def read_prompt(args):
    """prompt 解析：--prompt-file > --prompt > spike 中文金标准。返回 (text, source, err)。"""
    if args.prompt_file:
        try:
            text = Path(args.prompt_file).read_text(encoding="utf-8").strip()
        except Exception as e:  # noqa: BLE001
            return None, None, f"prompt_file_unreadable: {type(e).__name__}: {e}"
        if not text:
            return None, None, "prompt_file_empty: 文件无有效文本"
        return text, "file", None
    if args.prompt:
        return args.prompt, "arg", None
    return PROMPT_ZH_CANONICAL, "default_canonical_zh", None


def validate_params(args):
    """参数校验，返回错误列表（空=通过）。exit 2 通道。"""
    errs = []
    if args.frames < 5 or (args.frames - 1) % 4 != 0:
        errs.append(f"frames={args.frames} 不满足 (F-1)%4==0 且 F>=5（Wan2.2 VAE 时间压缩 4x 约束）")
    if args.steps < 1:
        errs.append(f"steps={args.steps} 须 >=1")
    if args.determinism_runs < 1:
        errs.append(f"determinism_runs={args.determinism_runs} 须 >=1")
    if args.guidance is not None and args.guidance <= 0:
        errs.append(f"guidance={args.guidance} 须 >0")
    return errs


def write_meta(out_dir, meta, name="wan22_meta.json"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    meta["generated_at"] = now_iso()
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(p, 0o644)
    return p


def new_meta():
    return {
        "task": "wan22-ti2v-5b-gen",
        "module": "gen_wan22",
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "host": os.uname().nodename,
        "git_head": git_head(),
        "errors": [],
        "ok": False,
    }


def build_params_record(args, prompt, prompt_source):
    return {
        "prompt": prompt,
        "prompt_source": prompt_source,
        "lang": "zh" if args.zh else ("en" if prompt and prompt.isascii() else "unknown"),
        "negative_prompt": NEGATIVE,
        "negative_note": "官方 README 用例中文负向词（Wan 官方推荐值，与 spike 逐字节一致）",
        "height": HEIGHT, "width": WIDTH,
        "num_frames": args.frames,
        "num_inference_steps": args.steps,
        "guidance_scale": args.guidance if args.guidance is not None else GUIDANCE_DEFAULT,
        "guidance_explicit": args.guidance is not None,
        "seed": args.seed,
        "fps_out": FPS,
        "dtype": "float16",
        "determinism_runs": args.determinism_runs,
        "model_dir": args.model,
        "resolution_note": ("720P 档：官方 README「720P resolution of the Text-Image-to-Video task "
                            "is 1280*704 or 704*1280」diffusers 用例 height=704,width=1280"),
    }


# ---------------------------------------------------------------- 真实生成

def generate_once(pipe, prompt, args, torch, tag):
    """单次生成（与 spike gen_once 逐行等价：新 Generator + inference_mode + output="videos"）。
    注意 guidance_scale 不显式下发（args.guidance is None 时），与 spike 一致。"""
    g = torch.Generator(device="cuda").manual_seed(args.seed)
    t = time.monotonic()
    extra = {"guidance_scale": args.guidance} if args.guidance is not None else {}
    with torch.inference_mode():
        videos = pipe(
            prompt=prompt, negative_prompt=NEGATIVE,
            height=HEIGHT, width=WIDTH,
            num_frames=args.frames,
            num_inference_steps=args.steps,
            generator=g,
            output="videos",
            **extra,
        )
    torch.cuda.synchronize()
    dt = time.monotonic() - t
    peak = torch.cuda.max_memory_allocated() / 2 ** 20
    torch.cuda.reset_peak_memory_stats()
    log(f"{tag}: gen_s={dt:.1f} peak={peak:.0f}MiB")
    return videos, round(dt, 2), round(peak, 1)


def run_real(args, meta, prompt):
    import numpy as np
    import torch
    from diffusers.utils import export_to_video  # noqa: F401（与 spike 同一编码入口，提前暴露缺失）

    meta["gpu"] = {
        "name": torch.cuda.get_device_name(0),
        "capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
        "bf16_supported": torch.cuda.is_bf16_supported(),
        "bf16_used": False,
        "bf16_note": "V100S cc7.0 全程 fp16（spike 口径：torch is_bf16_supported=True 为模拟路径）",
    }
    sampler = NvidiaSampler(meta).start()
    t_all = time.monotonic()

    pipe, build = build_pipeline(args.model, dtype=torch.float16)
    state_checks = verify_pipeline_state(pipe)   # 补丁落地核验，不符即抛 → fail-closed
    build["pipeline_state_checks"] = state_checks
    meta["compat_patches"] = build["compat_patches"]
    meta["pipeline"] = build["pipeline"]
    meta["pipeline_state_checks"] = state_checks   # verify_pipeline_state 逐项记录（fail-closed 证据）
    meta["vae_scale_factors"] = build["vae_scale_factors"]
    meta["timing_s"] = {"load": build["load_s"]}
    meta["vram"] = {"torch_peak_allocated_mib_load": build["load_peak_allocated_mib"]}
    log(f"模型加载完成 load_s={build['load_s']:.1f} peak={build['load_peak_allocated_mib']:.0f}MiB "
        f"pipeline={meta['pipeline']}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    arrs = {}
    for i in range(1, args.determinism_runs + 1):
        tag = f"run_{i}"
        arr, rec = None, None
        videos, gen_s, peak = generate_once(pipe, prompt, args, torch, tag)
        arr = to_np_uint8(videos, args.frames, HEIGHT, WIDTH, meta, tag)
        q = frames_stats(tag, arr, meta)
        rec = {"tag": tag, "gen_s": gen_s, "torch_peak_allocated_mib": peak,
               "quality": q, "dtype_status": "ok_fp16"}
        if q["nan_count"] > 0:
            # 降级：fp16 NaN → VAE 升 fp32 重解码重跑（不重跑 transformer；gen_local 家族同款降级）
            nan_first = q["nan_count"]
            meta["vae_fp32_fallback"] = True
            meta["errors"].append(
                f"{tag} NaN={nan_first}: fp16 风险，已 VAE 升 fp32 同 seed 重解码重跑（不重跑 transformer）")
            log(f"{tag} NaN={nan_first} → VAE 升 fp32 重跑同 seed（预案）")
            pipe.vae.to(torch.float32)
            tag2 = f"{tag}_vae_fp32_rerun"
            videos, gen_s, peak = generate_once(pipe, prompt, args, torch, tag2)
            arr = to_np_uint8(videos, args.frames, HEIGHT, WIDTH, meta, tag2)
            q = frames_stats(tag2, arr, meta)
            rec = {"tag": tag2, "gen_s": gen_s, "torch_peak_allocated_mib": peak, "quality": q,
                   "dtype_status": "ok_with_vae_fp32_fallback",
                   "nan_count_first_attempt": nan_first}
        arrs[tag] = arr
        mp4_path = out_dir / ("wan22_out.mp4" if i == 1 else f"wan22_out_{tag}.mp4")
        enc_s, md5, sha = encode_video(arr, mp4_path)
        os.chmod(mp4_path, 0o644)
        rec.update({
            "mp4": {"path": str(mp4_path), "size_bytes": os.path.getsize(mp4_path),
                    "md5": md5, "sha256": sha},
            "encode_s": enc_s,
        })
        if i == 1:
            png = out_dir / "wan22_preview_mid.png"
            save_preview(arr, png)
            rec["preview"] = str(png)
        runs.append(rec)
        log(f"{tag}: sha256={sha} gen_s={gen_s} peak={peak}MiB")

    meta["runs"] = runs

    # 同 seed 确定性 MAE（>=2 跑时）
    if len(arrs) >= 2:
        keys = sorted(arrs)
        idx = sample_indices(args.frames)
        per, all_mae = mae_record(arrs[keys[0]], arrs[keys[1]], idx)
        meta["determinism"] = {
            "runs_compared": keys[:2],
            "seed": args.seed,
            "frame_sample_indices": idx,
            "mae_per_sample": per,
            "mae_mean_sampled": round(float(np.mean(list(per.values()))), 4) if per else None,
            "mae_all_frames": all_mae,
            "encode_sha256_equal": runs[0]["mp4"]["sha256"] == runs[1]["mp4"]["sha256"],
            "note": "MAE=0 表示同 seed 逐比特可复现；>0 表示该硬件/内核路径存在非确定性",
        }

    # 端到端回检 + L0（对主输出）
    e2e = decode_mp4_check(runs[0]["mp4"]["path"], args.frames, HEIGHT, WIDTH, meta)
    meta["output"] = {
        "path": runs[0]["mp4"]["path"],
        "size_bytes": runs[0]["mp4"]["size_bytes"],
        "sha256": runs[0]["mp4"]["sha256"],
        "ffprobe": ffprobe_triple(runs[0]["mp4"]["path"], meta),
        "end_to_end_decode": e2e,
    }
    meta["l0_precheck_substitute"] = l0_precheck(
        meta["output"]["ffprobe"], runs[0]["quality"], args.frames)

    sampler.stop()
    meta["timing_s"]["total"] = round(time.monotonic() - t_all, 2)
    sm0 = [s for _, s, _ in sampler.samples]
    sm1 = [s for _, _, s in sampler.samples if s is not None]
    baseline_mib = sm0[0] if sm0 else None
    max_used_mib = max(sm0) if sm0 else None
    meta["vram"].update({
        "baseline_used_mib": baseline_mib,
        "nvidia_smi_max_used_mib_card0": max_used_mib,
        "nvidia_smi_delta_mib_card0": (max_used_mib - baseline_mib)
        if (max_used_mib is not None and baseline_mib is not None) else None,
        "card1_max_used_mib_untouched": max(sm1) if sm1 else None,
        "nvidia_smi_samples": len(sm0),
    })
    return meta


def main(argv=None):
    args = build_parser().parse_args(argv)
    meta = new_meta()

    prompt, prompt_source, err = read_prompt(args)
    if err:
        meta["errors"].append(err)
        p = write_meta(args.out, meta)
        log(f"[FATAL] {err}；meta={p}")
        return 2

    perr = validate_params(args)
    if perr:
        meta["errors"].extend(perr)
        p = write_meta(args.out, meta)
        for e in perr:
            log(f"[FATAL] {e}")
        log(f"meta={p}")
        return 2

    meta["dry_run"] = bool(args.dry_run)
    meta["params"] = build_params_record(args, prompt, prompt_source)
    ok, missing = validate_model_dir(args.model)
    meta["model"] = {"path": args.model, "present": ok, "missing": missing}

    if args.dry_run:
        # --dry-run 零加载：本分支之前/之后都不 import torch/diffusers，不触碰 GPU
        if not ok:
            meta["errors"].append(f"model_dir_missing: {args.model} 缺 {missing}")
            p = write_meta(args.out, meta)
            log(f"[FATAL] 权重目录不完整: {args.model} 缺 {missing}；meta={p}")
            return 1
        meta["plan"] = {
            "would_load": "补丁#1 手动加载 5 组件（全 fp16）+ update_components + apply_compat_patches(#2 #4 #3) + vae.enable_tiling() + pipe.to(cuda)",
            "would_generate": {"frames": args.frames, "steps": args.steps, "seed": args.seed,
                               "height": HEIGHT, "width": WIDTH, "fps": FPS,
                               "guidance": "guider 默认 5.0（不显式下发）" if args.guidance is None else args.guidance,
                               "determinism_runs": args.determinism_runs},
            "outputs": ["wan22_out.mp4", "wan22_preview_mid.png", "wan22_meta.json"],
        }
        p = write_meta(args.out, meta)
        log(f"[dry-run] 预检通过 prompt={prompt[:40]}... model={args.model}；meta={p}")
        meta["ok"] = True
        p = write_meta(args.out, meta)
        return 0

    if not ok:
        meta["errors"].append(f"model_dir_missing: {args.model} 缺 {missing}")
        p = write_meta(args.out, meta)
        log(f"[FATAL] 权重目录不完整: {args.model} 缺 {missing}；meta={p}")
        return 1

    # 铁律：发车前复测卡 0 ≤1GiB（不通过拒发，fail-closed）
    ok0, _, _ = preflight_card0(meta)
    if not ok0:
        p = write_meta(args.out, meta)
        log(f"[FATAL] 卡 0 预检未过，拒发；meta={p}")
        return 1

    try:
        run_real(args, meta, prompt)
    except Exception as e:  # noqa: BLE001
        meta["errors"].append(f"fatal: {type(e).__name__}: {e}")
        meta["fatal_traceback_tail"] = traceback.format_exc()[-2000:]
        meta["ok"] = False
        p = write_meta(args.out, meta)
        log(f"[FATAL] {type(e).__name__}: {e}；meta={p}")
        traceback.print_exc()
        return 1

    meta["ok"] = len(meta["errors"]) == 0
    p = write_meta(args.out, meta)
    if meta["ok"]:
        log("GEN_WAN22_OK " + json.dumps(
            {"sha256": meta["output"]["sha256"], "gen_s": meta["runs"][0]["gen_s"],
             "peak_vram": meta["vram"].get("nvidia_smi_max_used_mib_card0"),
             "l0": meta["l0_precheck_substitute"]["passed"]}, ensure_ascii=False))
        log(f"META {p}")
        return 0
    log(f"[FAIL] errors={meta['errors']}；meta={p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
