#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_cp7_drafts.py — CP7 草稿生成员：营销线 marketing_ep01 LTX-2B 草稿批量生成（v4 T2 层）。

复刻 shortdrama_ep01/cp7/run_cp7_drafts.py 验收范式（SPIKE-REPORT 硬条件同源），营销线差异：
  - 只生成叙事/产品镜 5 镜（shot_02..shot_06）——口播镜 shot_01 不跑 LTX 草稿：它走 G9a
    数字人专线（TTS→avatar，CP9 由 gen_avatar.py 直出，短剧线钩子段已验证该链路），
    prompts 内以 channel=api_vidu_avatar_planned 登记，reason 在案；
  - seed 规则同款：42 + 镜序号（1 基）→ shot_02→44 … shot_06→48；
  - l0 accepted 判定修正 shortdrama 首跑的 str/int 比较恒 False 缺陷（nb_frames 显式转 int），
    证据项与阈值零改动（thresholds.yaml l0_preflight 段口径）。

硬条件（SPIKE-REPORT §4）：① 英文 prompt 层；② 色偏为 checkpoint 固有只记录不修；
③ 确定性：DETERMINISM_SHOT 同参数二遍生成全帧 MAE 须=0.0。
参数：33 帧 / 480x704（HxW）/ 15 步 / guidance 3.0 / 24fps 导出。

红线：只卡 0（CUDA_VISIBLE_DEVICES=0 由启动命令注入，起跑前内联复测 ≤1024MiB 才发车）；
不 kill 进程、不 pip install、不下载（HF_HUB_OFFLINE=1）；本机只写 out/m2/（本目录）。
生成失败逐镜如实记 errors，不冒充。
"""
import hashlib
import json
import os
import subprocess
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))  # <gpu-repo>/out/m2/marketing_ep01/cp7
MODEL = "/data/night/models/LTX-Video"
HEIGHT, WIDTH = 480, 704   # 480P，HxW（任务书口径，ltx_baseline.py 同解读）
NUM_FRAMES = 33            # 33 = 8*4+1，满足 LTX 时间压缩约束
STEPS = 15
GUIDANCE = 3.0
FPS = 24
SEED_BASE = 42             # seed = 42 + 镜序号（1 基）：shot_02->44 … shot_06->48
NEG = ("worst quality, inconsistent motion, blurry, jittery, distorted, "
       "text, watermark, subtitles")
DECLARED_S = NUM_FRAMES / FPS  # 1.375 s（33 帧 @ 24fps，资产规格声明值）

RESULT = {
    "task": "cp7-draft-generation-marketing_ep01",
    "host": os.uname().nodename,
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "model": {"path": MODEL, "dtype": "float16", "pipeline": "LTXPipeline"},
    "params": {
        "height": HEIGHT, "width": WIDTH, "num_frames": NUM_FRAMES,
        "num_inference_steps": STEPS, "guidance_scale": GUIDANCE,
        "seed_rule": "42 + shot ordinal (1-based): shot_02->44 ... shot_06->48",
        "fps_out": FPS, "declared_duration_s_per_clip": DECLARED_S,
        "negative_prompt": NEG,
    },
    "avatar_planned": {
        "shot_id": "shot_01",
        "channel": "api_vidu_avatar_planned",
        "reason": ("口播主体镜按 G9a 专线在 CP9 由 avatar 直出（TTS→gen_avatar.py image+audio "
                   "模式，口型由 TTS 音频直驱），不经草稿层——短剧线钩子段已验证该链路；"
                   "本程（前半程）只设计不调用。"),
        "generated_here": False,
    },
    "shots": [],
    "errors": [],
}

# ---- 5 镜 prompt 表（action_zh 摘自 CP3 工件 payload.shots[].action，逐字未改；
#      prompt_en 为翻译层产出：短句、具体、含构图与运动；negative 全镜一致）----
PROMPT_ROWS = [
    {"shot_id": "shot_02", "seed": 44,
     "action_zh": "琥珀玻璃香薰瓶特写立于实木底座，藤条呈扇形展开，镜头缓推瓶身，瓶面无可读文字元素，产品几何恒存不形变",
     "prompt_en": ("Close-up with a slow push-in: an amber glass reed diffuser bottle standing "
                   "on a round wooden base, natural rattan reeds fanning out of the bottle neck, "
                   "soft daylight from a bedroom window, background melting into warm bokeh, "
                   "the bottle geometry stays perfectly rigid")},
    {"shot_id": "shot_03", "seed": 45,
     "action_zh": "藤条扩香微距特写，天然藤条自瓶口呈扇面立起，光斑沿玻璃肩部缓慢流转，暗背景，瓶体与藤条几何恒定不形变",
     "prompt_en": ("Extreme close-up, static camera: natural rattan reeds standing in the neck "
                   "of an amber glass diffuser bottle, gentle light glints sliding along the "
                   "glass shoulder, dark soft bedroom background, the bottle and reeds keep a "
                   "perfectly rigid unchanged shape")},
    {"shot_id": "shot_04", "seed": 46,
     "action_zh": "卧室床头暖光台灯旁，一只手轻拨藤条调香，指尖动作缓慢轻柔（G1 手部禁区镜级投影：指部解剖不崩、不融指），香薰瓶几何恒存",
     "prompt_en": ("Medium close-up, static camera: a woman's hand gently swaps and tilts the "
                   "rattan reeds of an amber glass diffuser bottle on a wooden bedside table "
                   "beside a warm glowing lamp, cozy evening bedroom, slow calm motion, five "
                   "distinct fingers")},
    {"shot_id": "shot_05", "seed": 47,
     "action_zh": "暮色卧室全景固定机位，床头柜上香薰瓶与暖灯同框，窗光柔和，画面干净无任何文字元素，产品在画面中体量清晰",
     "prompt_en": ("Wide shot, static camera: a serene minimalist bedroom at dusk, an amber "
                   "glass reed diffuser bottle on the wooden bedside table next to a warm "
                   "glowing lamp, soft linen bedding, gentle window light, calm premium "
                   "lifestyle atmosphere, no people")},
    {"shot_id": "shot_06", "seed": 48,
     "action_zh": "产品近景缓推收尾，暖灯轮廓光勾边，画面上缘留白供后期 CTA 字牌（产品名/价格/链接全部后期字牌，不在生成侧渲染），瓶体几何恒存",
     "prompt_en": ("Medium close-up with a slow push-in: an amber glass reed diffuser bottle "
                   "with a round wooden base on a bedside table, warm lamp rim light, soft "
                   "dusk window glow behind, clean empty space in the upper frame, premium "
                   "calm product showcase, the bottle shape stays rigid")},
]
for r in PROMPT_ROWS:
    r.update({"negative": NEG, "duration_frames": NUM_FRAMES,
              "guidance": GUIDANCE, "steps": STEPS})

DETERMINISM_SHOT = "shot_03"  # 确定性抽验镜（同参数二遍生成）


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
    """每 2s 采样一次卡 0 已用显存（MiB），记录全程峰值（ltx_baseline.py 同款）。"""

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
    """pipeline 输出 -> np.uint8 (T,H,W,C)。布局自适应：唯一 size==3 的轴为通道轴。"""
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
    """黑帧/NaN/每帧均值。arr: uint8 (T,H,W,C)。黑帧口径：帧级 RGB 均值 < 2/255。"""
    import numpy as np
    f = arr.astype(np.float32)
    nan_count = int(np.isnan(f).sum())
    frame_mean = f.mean(axis=(1, 2, 3))
    black = int((frame_mean < 2.0).sum())
    return {
        "frames": int(arr.shape[0]),
        "nan_count": nan_count,
        "black_frames_lt2": black,
        "frame_mean_min": round(float(frame_mean.min()), 3),
        "frame_mean_max": round(float(frame_mean.max()), 3),
        "frame_mean_overall": round(float(frame_mean.mean()), 3),
    }


def encode_video(arr, path):
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
        capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe rc={p.returncode}")
    d = json.loads(p.stdout)
    st = d["streams"][0]
    return {
        "codec_name": st.get("codec_name"),
        "pix_fmt": st.get("pix_fmt"),
        "width": st.get("width"),
        "height": st.get("height"),
        "avg_frame_rate": st.get("avg_frame_rate"),
        "nb_frames": st.get("nb_frames"),
        "duration_s": float(d["format"]["duration"]) if d["format"].get("duration") else None,
        "bit_rate": d["format"].get("bit_rate"),
    }


def decode_mp4_check(path):
    """端到端回检：ffmpeg 解码 mp4 -> rawvideo rgb24，查帧数/黑帧/均值。"""
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
    return {
        "decoded_frames": int(n),
        "black_frames_lt2": int((mean < 2.0).sum()),
        "frame_mean_min": round(float(mean.min()), 3),
        "frame_mean_overall": round(float(mean.mean()), 3),
    }


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import numpy as np
    import torch

    # ---- 红线复测：卡 0 ≤1024MiB 才发车；卡 1 记录基线（不碰）----
    pre = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "card0_used_mib": gpu_used_mib(0), "card1_used_mib": gpu_used_mib(1)}
    if pre["card0_used_mib"] > 1024:
        RESULT["errors"].append(f"preflight_card0_busy: {pre['card0_used_mib']}MiB > 1024MiB，拒发车")
        raise SystemExit("PREFLIGHT_FAIL card0 > 1GiB")
    RESULT["preflight"] = pre
    log(f"preflight card0={pre['card0_used_mib']}MiB card1={pre['card1_used_mib']}MiB -> GO")

    RESULT["gpu"] = {
        "name": torch.cuda.get_device_name(0),
        "capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
        "bf16_supported": torch.cuda.is_bf16_supported(),
    }
    try:
        RESULT["git_head"] = subprocess.run(
            ["git", "-C", os.path.abspath(os.path.join(BASE, "..", "..", "..", "..")),
             "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or "git_unavailable"
    except Exception:  # noqa: BLE001
        RESULT["git_head"] = "git_unavailable"

    sampler = NvidiaSampler().start()
    t_all = time.monotonic()

    from diffusers import LTXPipeline
    from diffusers.utils import export_to_video  # noqa: F401  （与基线同编码路径）

    t0 = time.monotonic()
    pipe = LTXPipeline.from_pretrained(MODEL, torch_dtype=torch.float16)
    pipe.to("cuda")
    load_s = time.monotonic() - t0
    torch.cuda.reset_peak_memory_stats()
    log(f"模型加载完成 load_s={load_s:.1f}")

    expect_shape = (NUM_FRAMES, HEIGHT, WIDTH, 3)
    determinism_first_arr = None

    def gen_once(row):
        g = torch.Generator(device="cuda").manual_seed(row["seed"])
        t = time.monotonic()
        with torch.inference_mode():
            out = pipe(
                prompt=row["prompt_en"], negative_prompt=row["negative"],
                height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
                num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=g)
        dt = time.monotonic() - t
        torch.cuda.synchronize()
        peak = torch.cuda.max_memory_allocated() / 2 ** 20
        torch.cuda.reset_peak_memory_stats()
        return out.frames, dt, peak

    # ---- 逐镜生成（仅叙事/产品镜 5 镜；shot_01 走 avatar 专线不在此生成）----
    for row in PROMPT_ROWS:
        sid = row["shot_id"]
        rec = {"shot_id": sid, "seed": row["seed"]}
        t_shot = time.monotonic()
        try:
            frames_raw, gen_s, peak = gen_once(row)
            arr = to_np_uint8(frames_raw, expect_shape)
            stats = frame_stats(arr)
            rec.update(gen_s=round(gen_s, 2), torch_peak_mib=round(peak, 1), tensor_stats=stats)

            # NaN 预案（ltx_baseline.py 同款）：升 VAE fp32 重解码
            if stats["nan_count"] > 0:
                RESULT["errors"].append(f"{sid}: NaN={stats['nan_count']}，走 VAE fp32 预案重跑")
                pipe.vae.to(torch.float32)
                frames_raw, gen_s, peak = gen_once(row)
                arr = to_np_uint8(frames_raw, expect_shape)
                stats = frame_stats(arr)
                pipe.vae.to(torch.float16)
                rec.update(vae_fp32_fallback=True, gen_s=round(gen_s, 2),
                           torch_peak_mib=round(peak, 1), tensor_stats=stats)

            mp4 = os.path.join(BASE, f"{sid}.draft.mp4")
            enc_s, md5 = encode_video(arr, mp4)
            os.chmod(mp4, 0o644)
            probe = ffprobe_triple(mp4)
            e2e = decode_mp4_check(mp4)
            actual = probe.get("duration_s")
            dev = abs(actual - DECLARED_S) / DECLARED_S if actual else None
            rec.update(encode_s=enc_s, mp4_md5=md5, mp4_sha256=sha256_of(mp4),
                       mp4_size_bytes=os.path.getsize(mp4), ffprobe=probe,
                       end_to_end_decode=e2e,
                       declared_duration_s=DECLARED_S, actual_duration_s=actual,
                       duration_dev=round(dev, 6) if dev is not None else None,
                       cp3_action_zh=row["action_zh"])

            # ---- L0 预检等价物（thresholds.yaml l0_preflight 既有段口径）----
            l0 = {
                "shot_id": sid, "asset": os.path.basename(mp4),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "thresholds_ref": "eval/thresholds.yaml l0_preflight（:224-233 v3 段）",
                "checks": {
                    "black_frames_tensor_lt2": stats["black_frames_lt2"],
                    "black_frames_decoded_lt2": e2e["black_frames_lt2"],
                    "nan_count_tensor": stats["nan_count"],
                    "duration_dev": rec["duration_dev"],
                    "duration_dev_max": 0.02,
                    "black_frame_ratio": (stats["black_frames_lt2"] / stats["frames"]),
                    "black_frame_ratio_max": 0.50,
                    "ffprobe_triple": {"codec": probe["codec_name"], "pix_fmt": probe["pix_fmt"],
                                       "wh": f"{probe['width']}x{probe['height']}",
                                       "fps": probe["avg_frame_rate"], "nb_frames": probe["nb_frames"]},
                },
            }
            nb = int(probe["nb_frames"]) if probe.get("nb_frames") else None  # str/int 显式归一
            l0["accepted"] = bool(
                stats["black_frames_lt2"] == 0 and e2e["black_frames_lt2"] == 0
                and stats["nan_count"] == 0 and dev is not None and dev <= 0.02
                and probe["codec_name"] == "h264" and probe["pix_fmt"] == "yuv420p"
                and probe["width"] == WIDTH and probe["height"] == HEIGHT
                and nb == NUM_FRAMES)
            l0_path = os.path.join(BASE, f"{sid}.draft.l0.json")
            with open(l0_path, "w", encoding="utf-8") as f:
                json.dump(l0, f, ensure_ascii=False, indent=2)
            os.chmod(l0_path, 0o644)
            rec["l0_accepted"] = l0["accepted"]
            rec["l0_evidence"] = os.path.basename(l0_path)
            rec["shot_wall_s"] = round(time.monotonic() - t_shot, 2)
            log(f"{sid}: gen={rec['gen_s']}s enc={enc_s}s wall={rec['shot_wall_s']}s "
                f"black={stats['black_frames_lt2']}/{e2e['black_frames_lt2']} nan={stats['nan_count']} "
                f"dev={rec['duration_dev']} l0={l0['accepted']}")
            RESULT["shots"].append(rec)

            if sid == DETERMINISM_SHOT:
                determinism_first_arr = arr.copy()
        except Exception as e:  # noqa: BLE001
            import traceback
            RESULT["errors"].append(
                {"shot_id": sid, "error": f"{e.__class__.__name__}: {e}",
                 "trace": traceback.format_exc()[-1500:]})
            log(f"{sid}: FAILED {e.__class__.__name__}: {e}")
            RESULT["shots"].append(rec)

    # ---- 确定性抽验：DETERMINISM_SHOT 同参数二遍生成，全帧 MAE 须=0.0 ----
    det = {"shot_id": DETERMINISM_SHOT, "method": "same seed/params second generation, full-frame MAE"}
    row = next(r for r in PROMPT_ROWS if r["shot_id"] == DETERMINISM_SHOT)
    try:
        t = time.monotonic()
        frames2, _gen2_s, _peak2 = gen_once(row)
        arr2 = to_np_uint8(frames2, expect_shape)
        det["gen2_s"] = round(time.monotonic() - t, 2)
        mae = float(np.abs(arr2.astype(np.float32) - determinism_first_arr.astype(np.float32)).mean())
        det["mae_all_frames"] = mae
        det["frames_compared"] = int(arr2.shape[0])
        det["equal_bits"] = bool(np.array_equal(arr2, determinism_first_arr))
        log(f"确定性抽验 {DETERMINISM_SHOT}: MAE={mae}")
    except Exception as e:  # noqa: BLE001
        det["error"] = f"{e.__class__.__name__}: {e}"
        RESULT["errors"].append(f"determinism_check_failed: {det['error']}")
        log(f"确定性抽验失败: {det['error']}")
    RESULT["determinism"] = det

    sampler.stop()
    RESULT["timing_s"] = {
        "load": round(load_s, 2),
        "total": round(time.monotonic() - t_all, 2),
        "gen_sum": round(sum(r.get("gen_s", 0) for r in RESULT["shots"]), 2),
        "encode_sum": round(sum(r.get("encode_s", 0) for r in RESULT["shots"]), 2),
    }
    RESULT["vram"] = {
        "baseline_used_mib": pre["card0_used_mib"],
        "nvidia_smi_max_used_mib": max((v for _, v in sampler.samples), default=None),
        "nvidia_smi_samples": len(sampler.samples),
    }
    l0_all = all(r.get("l0_accepted") for r in RESULT["shots"]) and bool(RESULT["shots"])
    RESULT["ok"] = bool(l0_all and not RESULT["errors"]
                        and det.get("mae_all_frames") == 0.0)

    prompts = {
        "task": RESULT["task"],
        "generated_at": RESULT["generated_at"],
        "params": RESULT["params"],
        "avatar_planned": RESULT["avatar_planned"],
        "shots": PROMPT_ROWS + [{
            "shot_id": "shot_01", "seed": None,
            "action_zh": "明亮卧室窗边，女主播半身近景对镜口播开场，微笑直视镜头，双手开掌自然示意，固定机位带微呼吸感",
            "prompt_en": None,
            "channel": "api_vidu_avatar_planned",
            "note": ("口播主体镜不跑 LTX 草稿：G9a 专线 CP9 由 avatar 直出（TTS→gen_avatar.py "
                     "image+audio，口型由 TTS 音频直驱），短剧线钩子段已验证；本程只设计不调用。"),
        }],
    }
    for path, obj in (("cp7_prompts.json", prompts), ("cp7_run_report.json", RESULT)):
        with open(os.path.join(BASE, path), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.chmod(os.path.join(BASE, path), 0o644)
        log(f"written: {os.path.join(BASE, path)}")
    log(f"完成 ok={RESULT['ok']} total_s={RESULT['timing_s']['total']} errors={len(RESULT['errors'])}")


if __name__ == "__main__":
    main()
