#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_cp7_drafts.py — CP7 草稿生成员：短剧 EP1 全 11 镜 LTX-2B 草稿批量生成（v4 T2 层首次实跑）。

改编自 evidence/spike/ltx_baseline.py（SPIKE-REPORT.md 验收范式：LTXPipeline/fp16/指标记录/确定性验证）。
硬条件（SPIKE-REPORT §4 结论）：
  ① 英文 prompt 层——中文直喂 100% 废片（T5-XXL 不支持中文，发现 A），本表全部英文；
  ② 色偏为 checkpoint 固有（发现 B）——只记录不修，草稿仅表示构图/运动/节奏；
  ③ 确定性：同 seed 逐比特复现——本跑对 shot_03 做二遍生成复证（全帧 MAE 须=0.0）。
参数（任务书固定）：33 帧 / 480x704（HxW）/ 15 步 / guidance 3.0 / 24fps 导出 / 每镜 seed=42+镜序号（1 基）。

红线：只卡 0（CUDA_VISIBLE_DEVICES=0 由启动命令注入，起跑前内联复测 ≤1024MiB 才发车）；
不 kill 进程、不 pip install、不下载（HF_HUB_OFFLINE=1）；
本机只写 out/m2/（本目录）。生成失败逐镜如实记 errors，不冒充。
"""
import hashlib
import json
import os
import subprocess
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))  # <gpu-repo>/out/m2/shortdrama_ep01/cp7
MODEL = "/data/night/models/LTX-Video"
HEIGHT, WIDTH = 480, 704   # 480P，HxW（任务书口径，ltx_baseline.py 同解读）
NUM_FRAMES = 33            # 33 = 8*4+1，满足 LTX 时间压缩约束
STEPS = 15
GUIDANCE = 3.0
FPS = 24
SEED_BASE = 42             # seed = 42 + 镜序号（1 基）：shot_01→43 … shot_11→53
NEG = ("worst quality, inconsistent motion, blurry, jittery, distorted, "
       "text, watermark, subtitles")
DECLARED_S = NUM_FRAMES / FPS  # 1.375 s（33 帧 @ 24fps，资产规格声明值）

RESULT = {
    "task": "cp7-draft-generation-shortdrama_ep01",
    "host": os.uname().nodename,
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "model": {"path": MODEL, "dtype": "float16", "pipeline": "LTXPipeline"},
    "params": {
        "height": HEIGHT, "width": WIDTH, "num_frames": NUM_FRAMES,
        "num_inference_steps": STEPS, "guidance_scale": GUIDANCE,
        "seed_rule": "42 + shot ordinal (1-based): shot_01->43 ... shot_11->53",
        "fps_out": FPS, "declared_duration_s_per_clip": DECLARED_S,
        "negative_prompt": NEG,
    },
    "shots": [],
    "errors": [],
}

# ---- 11 镜 prompt 表（action_zh 摘自 CP3 工件 payload.shots[].action，逐字未改；
#      prompt_en 为翻译层产出：短句、具体、含构图与运动；negative 全镜一致）----
PROMPT_ROWS = [
    {"shot_id": "shot_01", "seed": 43,
     "action_zh": "雨夜旧宅门厅，小满推门而入，背后雨幕逆光勾出剪影，低机位仰拍小满面部大特写，水珠沿发梢滴落",
     "prompt_en": ("Extreme close-up at a low angle: a young woman pushes open a heavy wooden door "
                   "of an old mansion on a rainy night and steps into the foyer, her face filling the "
                   "frame, backlit by the glowing rain curtain behind her, water droplets dripping "
                   "from her hair, static camera, shallow depth of field")},
    {"shot_id": "shot_02", "seed": 44,
     "action_zh": "林父举杯的手停在半空，杯中酒晃出涟漪；镜头缓推越过杯沿，他抬手示意门口保安，宾客回头",
     "prompt_en": ("Medium shot at a crowded banquet: an elderly man in a dark suit freezes with a "
                   "raised wine glass, red wine rippling in the bowl, the camera slowly pushing in "
                   "over the rim of the glass as he lifts his other hand to beckon a guard at the "
                   "door, guests turning their heads")},
    {"shot_id": "shot_03", "seed": 45,
     "action_zh": "小满把修车扳手放上白桌布，金属反光划过扳手轮廓特写，镜头缓推但不离开扳手，扳手金属体不形变",
     "prompt_en": ("Close-up: a young woman places a steel wrench on a white tablecloth, light "
                   "glinting along the rigid metal body, the camera slowly pushing in while staying "
                   "locked on the wrench, the banquet hall melted into soft bokeh behind")},
    {"shot_id": "shot_04", "seed": 46,
     "action_zh": "林父把合约文件拍在桌面，手指重重点在签名栏，合约纸面特写压住半个画面，纸面文字不作为可读元素呈现",
     "prompt_en": ("Close-up: an elderly man slams a contract dossier onto the table and presses his "
                   "finger hard on the signature line, the paper sheet dominating half of the frame "
                   "with soft illegible printed lines, static camera, dramatic side light")},
    {"shot_id": "shot_05", "seed": 47,
     "action_zh": "小满与林父隔桌对坐同框，小满指尖把合约最后一页推过去，双人近景一镜不切",
     "prompt_en": ("Medium close-up two-shot, one static take: a young woman and an elderly man sit "
                   "facing each other across a banquet table, she slides the last page of a contract "
                   "across the table with one fingertip, both in frame, no cuts")},
    {"shot_id": "shot_06", "seed": 48,
     "action_zh": "林父瞳孔骤缩的面部大特写，捏着纸页的手指微微发颤，背景宾客全部虚化，镜头缓推压向瞳孔",
     "prompt_en": ("Extreme close-up: an elderly man's eyes widen and his pupil contracts in shock, "
                   "his fingers trembling as they pinch the paper page, guests behind him blurred "
                   "into round bokeh, the camera slowly pushing in toward his eye")},
    {"shot_id": "shot_07", "seed": 49,
     "action_zh": "同机位前后对切：左半幅五年前汽修工装沾油渍，右半幅今日董事西装笔挺，眼神不变",
     "prompt_en": ("Medium shot, fixed camera, split composition: on the left the same young woman "
                   "in oil-stained mechanic overalls from years ago, on the right she stands today "
                   "in a sharp tailored business suit, the same steady unwavering gaze in both halves")},
    {"shot_id": "shot_08", "seed": 50,
     "action_zh": "林父踉跄半步扶住桌沿，酒杯倾倒酒渍洇开桌布，手持微晃低机位拍他失神的脸",
     "prompt_en": ("Handheld medium close-up from a low angle with a slight shake: an elderly man "
                   "staggers half a step and grips the table edge, his wine glass topples and red "
                   "wine soaks into the white tablecloth, his face draining into blank shock")},
    {"shot_id": "shot_09", "seed": 51,
     "action_zh": "小满缓步逼近镜头，竖屏面部大特写逐渐占满画面，身后满堂宾客虚成光斑，跟移不脱焦",
     "prompt_en": ("Extreme close-up tracking shot: a young woman walks slowly straight toward the "
                   "camera, her face gradually filling the frame while a hall full of guests "
                   "dissolves into glowing bokeh behind her, the camera gliding backward with her, "
                   "focus locked on her eyes")},
    {"shot_id": "shot_10", "seed": 52,
     "action_zh": "林父颓然坐回椅子，白发垂下来，抬手抹了一把脸，肩膀垮掉，固定机位不给他镜头遮羞",
     "prompt_en": ("Medium shot, fixed camera, no cutaway: an elderly man slumps back into his "
                   "chair defeated, white hair falling across his forehead, he drags a hand down "
                   "his face, his shoulders collapsing")},
    {"shot_id": "shot_11", "seed": 53,
     "action_zh": "小满举杯一饮而尽杯底朝天，转身走出大门背影定格，镜头拉出至门厅全景，雨幕重新合拢",
     "prompt_en": ("Wide shot: a young woman downs her drink in one gulp with the glass tilted "
                   "fully vertical, turns and walks out through the front door, the camera pulling "
                   "back and rising to reveal the whole mansion foyer as the rain curtain closes "
                   "behind her silhouette")},
]
for r in PROMPT_ROWS:
    r.update({"negative": NEG, "duration_frames": NUM_FRAMES,
              "guidance": GUIDANCE, "steps": STEPS})

DETERMINISM_SHOT = "shot_03"  # 确定性抽验镜（任选其一，同参数二遍生成）


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

    # ---- 逐镜生成 ----
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
                       duration_dev=round(dev, 6) if dev is not None else None)

            # ---- L0 预检等价物（thresholds.yaml:178-181 既有段口径）----
            l0 = {
                "shot_id": sid, "asset": os.path.basename(mp4),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "thresholds_ref": "eval/thresholds.yaml:178-181 l0_preflight",
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
            l0["accepted"] = bool(
                stats["black_frames_lt2"] == 0 and e2e["black_frames_lt2"] == 0
                and stats["nan_count"] == 0 and dev is not None and dev <= 0.02
                and probe["codec_name"] == "h264" and probe["pix_fmt"] == "yuv420p"
                and probe["width"] == WIDTH and probe["height"] == HEIGHT
                and probe["nb_frames"] == NUM_FRAMES)
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
    try:
        row = next(r for r in PROMPT_ROWS if r["shot_id"] == DETERMINISM_SHOT)
        if determinism_first_arr is None:
            raise RuntimeError("first-pass array unavailable (shot failed)")
        frames_b, gen_s, _ = gen_once(row)
        arr_b = to_np_uint8(frames_b, expect_shape)
        a = determinism_first_arr.astype(np.float32)
        b = arr_b.astype(np.float32)
        mae = float(np.abs(a - b).mean())
        det.update(gen2_s=round(gen_s, 2), mae_all_frames=round(mae, 6),
                   frames_compared=int(a.shape[0]), equal_bits=(mae == 0.0))
        log(f"确定性抽验 {DETERMINISM_SHOT}: MAE={mae}")
    except Exception as e:  # noqa: BLE001
        det["error"] = f"{e.__class__.__name__}: {e}"
        RESULT["errors"].append(f"determinism_check_failed: {e}")
        log(f"确定性抽验失败: {e}")
    RESULT["determinism"] = det

    sampler.stop()
    RESULT["timing_s"] = {
        "load": round(load_s, 2),
        "total": round(time.monotonic() - t_all, 2),
        "gen_sum": round(sum(r.get("gen_s", 0) for r in RESULT["shots"]), 2),
        "encode_sum": round(sum(r.get("encode_s", 0) for r in RESULT["shots"]), 2),
        "gen_s_min": min((r["gen_s"] for r in RESULT["shots"] if "gen_s" in r), default=None),
        "gen_s_max": max((r["gen_s"] for r in RESULT["shots"] if "gen_s" in r), default=None),
        "shot_wall_min": min((r["shot_wall_s"] for r in RESULT["shots"] if "shot_wall_s" in r), default=None),
        "shot_wall_max": max((r["shot_wall_s"] for r in RESULT["shots"] if "shot_wall_s" in r), default=None),
    }
    sm = [s for _, s in sampler.samples]
    RESULT["vram"] = {
        "baseline_used_mib": (sm[0] if sm else None),
        "nvidia_smi_max_used_mib": (max(sm) if sm else None),
        "nvidia_smi_samples": len(sm),
    }
    RESULT["ok"] = (len(RESULT["errors"]) == 0
                    and all(r.get("l0_accepted") for r in RESULT["shots"])
                    and det.get("mae_all_frames") == 0.0)

    # ---- prompt 表落盘（cp7_prompts.json 行结构按任务书）----
    prompts_doc = {
        "schema": "cp7_prompts/1.0",
        "work_id": "shortdrama_ep01",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": {"path": MODEL, "pipeline": "LTXPipeline", "dtype": "float16"},
        "params": {"height": HEIGHT, "width": WIDTH, "fps": FPS,
                   "duration_frames": NUM_FRAMES, "steps": STEPS, "guidance": GUIDANCE,
                   "seed_rule": "42 + shot ordinal (1-based): shot_01->43 ... shot_11->53"},
        "hard_conditions_ref": "evidence/spike/SPIKE-REPORT.md §1 发现A(英文层)/发现B(色偏固有)",
        "shots": [{k: r[k] for k in ("shot_id", "action_zh", "prompt_en", "negative",
                                     "seed", "duration_frames", "guidance", "steps")}
                  for r in PROMPT_ROWS],
    }
    with open(os.path.join(BASE, "cp7_prompts.json"), "w", encoding="utf-8") as f:
        json.dump(prompts_doc, f, ensure_ascii=False, indent=2)
    os.chmod(os.path.join(BASE, "cp7_prompts.json"), 0o644)

    report = os.path.join(BASE, "cp7_run_report.json")
    with open(report, "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=2)
    os.chmod(report, 0o644)
    for p in ("cp7_prompts.json", "cp7_run_report.json"):
        log(f"written: {os.path.join(BASE, p)}")
    log(f"完成 ok={RESULT['ok']} total_s={RESULT['timing_s']['total']} "
        f"errors={len(RESULT['errors'])}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        RESULT["errors"].append(f"fatal: {e.__class__.__name__}: {e}")
        RESULT["ok"] = False
        try:
            with open(os.path.join(BASE, "cp7_run_report.json"), "w", encoding="utf-8") as f:
                json.dump(RESULT, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        traceback.print_exc()
        raise SystemExit(1)
