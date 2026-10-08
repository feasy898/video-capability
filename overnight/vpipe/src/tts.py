#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tts.py — CP10 字幕音轨：StepFun stepaudio-2.5-tts 客户端（合成 + 零样本克隆闭环）
====================================================================================

定位（vpipe SPEC.md §2 家族风格：单文件、零 vpipe 兄弟依赖、CLI、失败写 errors 不静默）：
  CP10 字幕音轨的台词→语音合成。旧 `overnight/数据/stepfun_client.py` 随 windev-01 销毁
  （docs/credentials-rebuild.md §1），本模块按官方文档重写，纯标准库 urllib 实现（不依赖
  requests/openai——GPU 机依赖情况不可假设，红线「不 pip install」）。

端点与 DTO（2026-10-08 抓官方文档核实，非猜测）：
  - TTS 合成   POST {base}/audio/speech，二进制音频流响应
      base 默认 https://api.stepfun.com/step_plan/v1（bao STEPFUN_BASE_URL 记录 +
      官方 step-plan 音频接入指南 step-plan/integrations/audio-api，示例即
      https://api.stepfun.com/step_plan/v1/audio/speech）
      DTO: model(必填)/input(必填,≤1000字)/voice(必填)/response_format(默认mp3,枚举
      wav|mp3|flac|opus|pcm)/speed(0.5~2,默认1.0)/instruction(仅 stepaudio-2.5|3-tts,
      全局语气指导)/sample_rate(默认24000)。行内括号语气控制（input 内 (…)）为模型行为
      （工程方案v3.1 §2.2 TTS 行实测生效）。
  - 克隆上传   POST {origin}/v1/files，multipart，purpose="storage"，mp3/wav 5-10s
      （官方 files/create-file 页；step_plan 音频页未给 files 的 step_plan 路径，故取
      文档明示的平台通道 /v1/files——与旧客户端 account_base 实测组合一致，可用
      --files-url 覆盖）
  - 克隆注册   POST {base}/audio/voices，JSON {model(必填), file_id(必填), text(选填,
      转写，缺省服务端 ASR)} → 响应 {id, object:"audio.voice", duplicated}（官方
      audio/create-voice 页）。服务端对重复克隆按 duplicated=true 幂等去重，无需本地缓存。
      注意：文档 DTO 无 name 字段——CLI 的 --voice-name 是本地别名标签（记入 meta/日志），
      不发往 API（如实记录该映射决定）。
  - 鉴权       Authorization: Bearer $STEPFUN_API_KEY（两页一致）

凭据纪律（docs/credentials-rebuild.md §5/§7、工程方案v3.1 §8）：
  STEPFUN_API_KEY / STEPFUN_BASE_URL 只从进程环境变量或 --env-file（api_keys.env 格式，
  解析后只进内存）读取；绝不打印/入日志/入 meta/入提交；日志一律掩码（前 6 字符+len）。

成本口径（credits_or_cost_estimate）：牌价 ¥5.8/万字符（工程方案v3.1 §2.4② 行、
  stepfun_smoke_20260930.json pricing_doc）；计费单元估算=汉字 1/两字母 1（同
  gen_avatar.py _sf_billing_units 口径）；step_plan 实扣拆分 API 不可得（工程方案v3.1
  §4.1「无 API 查询端点，计费拆分不可得」），实测 64 字实扣 ¥0.01 更低于牌价
  （数字人实验报告.md §2.1）——故 meta 只记牌价估算并注明口径。单次预估 >¥1 硬拦
  （红线，任单一调用预估超限直接 exit 4 上报，不发请求）。

确定性：TTS 同输入两遍一致性未测（工程方案v3.1 §5），本模块不承诺字节复现；sha256
  与 ffprobe 实测时长逐次落 meta 供对账。

CLI:
  python3 src/tts.py --text "台词" --out out/tts/test.wav [--voice-id cixingnansheng]
                     [--speed 1.0] [--model stepaudio-2.5-tts] [--instruction "..."]
                     [--response-format wav] [--dry-run] [--env-file FILE]
                     [--base-url URL] [--files-url URL] [--timeout 120]
                     [--clone --ref-audio FILE --voice-name NAME [--clone-text "..."]]

退出码：0 成功/dry-run / 1 API 调用或合成失败（fail-closed，不伪造成功）/
  2 输入校验或凭据缺失 / 4 单次预估成本 >¥1 红线拦截。
失败时同样落 <out 主名>.meta.json（status=failed + errors[]），不静默。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MODULE_ID = "tts.py@vpipe-cp10-1.0"

DEFAULT_BASE_URL = "https://api.stepfun.com/step_plan/v1"
DEFAULT_MODEL = "stepaudio-2.5-tts"
DEFAULT_VOICE = "cixingnansheng"      # 数字人实验报告.md §2.1 实测默认音色（磁性男声）
SUPPORTED_FORMATS = ("wav", "mp3", "flac", "opus", "pcm")   # 官方 create-audio 页枚举
SUPPORTED_CLONE_EXTS = (".mp3", ".wav")                     # 官方 create-voice 页：mp3/wav
MAX_INPUT_CHARS = 1000                # 官方 create-audio 页 input 上限
MAX_SPEED, MIN_SPEED = 2.0, 0.5       # 官方 create-audio 页 speed 范围
PRICE_CNY_PER_10K_UNITS = 5.8         # 牌价 ¥5.8/万字符（工程方案v3.1 §2.4②）
COST_REDLINE_CNY = 1.0                # 红线：单次预估 >¥1 立即停
CHARS_PER_SEC_EST = 4.6               # 数字人实验报告.md §2.1 实测语速（估时用）
KEY_ENV = "STEPFUN_API_KEY"
BASEURL_ENV = "STEPFUN_BASE_URL"


class InputError(Exception):
    """输入校验失败（退出码 2）。"""


class CredentialsError(Exception):
    """凭据缺失（退出码 2）。"""


class CostRedlineError(Exception):
    """单次预估成本超红线（退出码 4）。"""


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg):
    print(f"[tts {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def mask_key(key: str) -> str:
    """日志/落盘专用掩码：前 6 字符 + ****(len=N)（工程方案v3.1 §8 实测合规口径）。"""
    if not key:
        return "(empty)"
    return f"{key[:6]}****(len={len(key)})"


# =====================================================================
# 1) 凭据：env / --env-file（解析后只进内存）
# =====================================================================
def parse_env_file(path: Path) -> dict:
    """api_keys.env 格式：KEY=VALUE / export KEY=VALUE；# 注释与空行忽略；
    值两端成对引号剥掉。返回 dict 只在内存，调用方不得打印/落盘。"""
    out = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def load_credentials(env_file: str | None) -> tuple[str, str]:
    """返回 (api_key, base_url)。--env-file 优先于进程环境（显式指定更可信），
    二者皆无 key → CredentialsError。key 绝不出现在返回值之外的任何输出。"""
    file_env = {}
    if env_file:
        p = Path(env_file)
        if not p.is_file():
            raise CredentialsError(f"--env-file 不存在: {p}")
        file_env = parse_env_file(p)
    key = file_env.get(KEY_ENV) or os.environ.get(KEY_ENV) or ""
    base = (file_env.get(BASEURL_ENV) or os.environ.get(BASEURL_ENV)
            or DEFAULT_BASE_URL).rstrip("/")
    if not key:
        raise CredentialsError(
            f"缺 {KEY_ENV}（进程环境与 --env-file 均未提供）——fail-closed，不发请求")
    return key, base


# =====================================================================
# 2) 估算：计费单元 / 成本 / 时长
# =====================================================================
def billing_units(text: str) -> int:
    """计费单元估算：汉字 1 字符、两字母 1 字符（stepfun_smoke pricing_doc 口径，
    同 gen_avatar._sf_billing_units）。仅供成本参考，实扣以钱包差值为准。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return cjk + math.ceil(letters / 2)


def cost_estimate_cny(units: int) -> float:
    """牌价估算（¥5.8/万字符）。step_plan 无逐调用账单 API，如实只给估算。"""
    return round(units * PRICE_CNY_PER_10K_UNITS / 10000, 6)


def cost_estimate_meta(text: str) -> dict:
    units = billing_units(text)
    return {
        "billing_units_est": units,
        "cny_doc_rate_est": cost_estimate_cny(units),
        "basis": (f"牌价 ¥{PRICE_CNY_PER_10K_UNITS}/万字符（工程方案v3.1 §2.4②）；"
                  "step_plan 实扣拆分 API 不可得（§4.1），实测低于牌价"
                  "（数字人实验报告 §2.1：64字实扣¥0.01）——此值为估算非实扣"),
    }


def duration_estimate_s(text: str) -> float:
    """无音频实长时的估时（dry-run 用）：实测 4.6 字/s（数字人实验报告 §2.1）。"""
    return round(billing_units(text) / CHARS_PER_SEC_EST, 2)


# =====================================================================
# 3) HTTP 层（urllib，单次尝试不重试——失败如实记录）
# =====================================================================
def _scan_request_id(headers) -> str | None:
    """响应头里找 request id（名称含 request-id，大小写不敏感）；无则 None，如实。"""
    try:
        for name, value in headers.items():
            if "request-id" in name.lower():
                return value
    except Exception:
        pass
    return None


def http_post(url: str, key: str, *, json_body: dict | None = None,
              multipart: bytes | None = None, multipart_ctype: str | None = None,
              timeout: float = 120.0) -> dict:
    """POST 一次，返回 {status, headers, body(bytes), request_id}。
    HTTP ≥400 也原样返回（不抛），由调用方 fail-closed 裁决——错误体也是数据。
    单次尝试、零重试：失败不静默重放（红线：端点不确定时只试 1 次）。"""
    headers = {"Authorization": f"Bearer {key}"}
    data = b""
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif multipart is not None:
        data = multipart
        headers["Content-Type"] = multipart_ctype
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"status": resp.status, "headers": resp.headers,
                    "body": resp.read(), "request_id": _scan_request_id(resp.headers)}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "headers": e.headers,
                "body": e.read() if hasattr(e, "read") else b"",
                "request_id": _scan_request_id(e.headers)}
    # URLError/timeout 等直接上抛，由上层记 errors（网络层失败也是失败，不吞）


def http_post_multipart(url: str, key: str, field: str, filename: str,
                        content: bytes, content_type: str, extra_fields: dict,
                        timeout: float) -> dict:
    """手工 multipart（纯标准库）：extra_fields + 单文件字段。"""
    boundary = "vpipe" + uuid.uuid4().hex
    parts = []
    for name, value in extra_fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
            .encode("utf-8"))
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
         f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n").encode("utf-8"))
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return http_post(url, key, multipart=b"".join(parts),
                     multipart_ctype=f"multipart/form-data; boundary={boundary}",
                     timeout=timeout)


def parse_json_response(step: str, res: dict) -> dict:
    """JSON 响应解析（files/voices 步）；非 200 或解析失败 → InputError 带上下文。"""
    if res["status"] != 200:
        raise RuntimeError(f"{step} HTTP {res['status']}: {res['body'][:300]!r}")
    try:
        return json.loads(res["body"].decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"{step} 响应非 JSON: {e}; body[:200]={res['body'][:200]!r}")


# =====================================================================
# 4) ffprobe（duration_s 实测是 meta 的承载字段）
# =====================================================================
def ffprobe_audio(path: Path) -> dict:
    """ffprobe 实测；ffprobe 缺失或解析失败抛 RuntimeError（上层记 errors，
    duration_s=null，绝不拿估算冒充实测）。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败 {path}: {(r.stderr or '')[:300]}")
    doc = json.loads(r.stdout)
    a = next((s for s in doc.get("streams", []) if s.get("codec_type") == "audio"), None)
    if a is None:
        raise RuntimeError(f"ffprobe 未发现音频流 {path}")
    dur = doc.get("format", {}).get("duration") or a.get("duration")
    return {"duration_s": round(float(dur), 3) if dur is not None else None,
            "acodec": a.get("codec_name"),
            "sample_rate": a.get("sample_rate"),
            "channels": a.get("channels")}


# =====================================================================
# 5) 请求构造（可单测的纯函数）
# =====================================================================
def build_speech_request(text: str, model: str, voice: str, response_format: str,
                         speed: float, instruction: str | None,
                         base_url: str) -> tuple[str, dict]:
    """合成请求 (url, body)。校验失败抛 InputError（扣费前拦截，SPEC §2.2 实证价值）。"""
    text = (text or "").strip()
    if not text:
        raise InputError("--text 为空")
    if len(text) > MAX_INPUT_CHARS:
        raise InputError(f"--text 超官方上限 {MAX_INPUT_CHARS} 字符（got {len(text)}）")
    if response_format not in SUPPORTED_FORMATS:
        raise InputError(f"response_format 须为 {'|'.join(SUPPORTED_FORMATS)}，got {response_format!r}")
    if not (MIN_SPEED <= speed <= MAX_SPEED):
        raise InputError(f"speed 须在 {MIN_SPEED}~{MAX_SPEED}，got {speed}")
    if not voice:
        raise InputError("voice 为空（--voice-id 或 --clone 产出）")
    body = {"model": model, "input": text, "voice": voice,
            "response_format": response_format, "speed": speed}
    if instruction:
        body["instruction"] = instruction
    return f"{base_url.rstrip('/')}/audio/speech", body


def speech_cost_redline(text: str):
    """红线：单次预估成本 >¥1 → CostRedlineError（exit 4），不发请求。"""
    est = cost_estimate_cny(billing_units(text))
    if est > COST_REDLINE_CNY:
        raise CostRedlineError(
            f"单次预估 ¥{est} > ¥{COST_REDLINE_CNY} 红线——立即停，需人工上报后拆分文本")


def sniff_audio(body: bytes) -> str:
    """轻量魔数嗅探（仅供 meta 记录，真伪由 ffprobe 实测裁决）。"""
    if body[:4] == b"RIFF":
        return "riff_wave"
    if body[:3] == b"ID3" or (len(body) > 2 and body[0] == 0xFF and (body[1] & 0xE0) == 0xE0):
        return "mpeg_audio"
    if body[:4] == b"fLaC":
        return "flac"
    if body[:4] == b"OggS":
        return "ogg"
    return "unknown"


# =====================================================================
# 6) 克隆闭环：/v1/files(purpose=storage) → /audio/voices → voice_id
# =====================================================================
def clone_voice(key: str, base_url: str, files_url: str, ref_audio: Path,
                model: str, clone_text: str | None,
                timeout: float) -> tuple[str, dict]:
    """返回 (voice_id, clone_meta)。任一步失败抛 RuntimeError（上层 fail-closed）。"""
    if not ref_audio.is_file():
        raise InputError(f"--ref-audio 不存在: {ref_audio}")
    if ref_audio.suffix.lower() not in SUPPORTED_CLONE_EXTS:
        raise InputError(f"克隆音频格式须为 {'|'.join(SUPPORTED_CLONE_EXTS)}（官方口径），"
                         f"got {ref_audio.suffix!r}")
    content = ref_audio.read_bytes()
    log(f"[clone] 上传 {ref_audio.name}（{len(content)}B）→ {files_url} purpose=storage")
    res = http_post_multipart(files_url, key, "file", ref_audio.name, content,
                              "audio/wav" if ref_audio.suffix.lower() == ".wav"
                              else "audio/mpeg",
                              {"purpose": "storage"}, timeout=max(timeout, 300))
    fdoc = parse_json_response("/v1/files", res)
    file_id = fdoc.get("id")
    if not file_id:
        raise RuntimeError(f"/v1/files 未返回 id: {str(fdoc)[:300]}")
    log(f"[clone] file_id={file_id} → {base_url}/audio/voices")

    vbody = {"model": model, "file_id": file_id}
    if clone_text:
        vbody["text"] = clone_text        # 转写选填；缺省服务端 ASR（官方 create-voice 页）
    res2 = http_post(f"{base_url.rstrip('/')}/audio/voices", key, json_body=vbody,
                     timeout=max(timeout, 300))
    vdoc = parse_json_response("/audio/voices", res2)
    voice_id = vdoc.get("id") or vdoc.get("voice_id")
    if not voice_id:
        raise RuntimeError(f"/audio/voices 未返回 voice_id: {str(vdoc)[:300]}")
    meta = {"voice_id": voice_id, "file_id": file_id,
            "duplicated": vdoc.get("duplicated"), "object": vdoc.get("object"),
            "ref_audio": str(ref_audio),
            "ref_audio_sha256": hashlib.sha256(content).hexdigest(),
            "clone_text": clone_text,
            "files_request_id": res.get("request_id"),
            "voices_request_id": res2.get("request_id"),
            "endpoints": {"files": files_url, "voices": f"{base_url}/audio/voices"}}
    log(f"[clone] voice_id={voice_id} duplicated={vdoc.get('duplicated')}")
    return voice_id, meta


# =====================================================================
# 7) 主流程
# =====================================================================
def meta_path_for(out_path: Path) -> Path:
    """同主名 meta：<out 主名>.meta.json（test.wav → test.meta.json）。"""
    return out_path.with_suffix(".meta.json")


def write_meta(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[meta] → {path}")


def base_meta(out_path: Path, status: str, key_masked: str, base_url: str,
              errors: list[str], **extra) -> dict:
    m = {"module": MODULE_ID, "generated_at": now_iso(), "status": status,
         "key_masked": key_masked, "endpoint_base": base_url,
         "out_path": str(out_path), "errors": errors}
    m.update(extra)
    return m


def run(args) -> int:
    t0 = time.time()
    out_path = Path(args.out)
    mpath = meta_path_for(out_path)
    errors: list[str] = []

    # ---- 输入静态校验（不触凭据、不发请求） ----
    fmt = args.response_format or out_path.suffix.lower().lstrip(".")
    if not fmt:
        fmt = "mp3"
    try:
        url, body = build_speech_request(args.text, args.model, args.voice_id, fmt,
                                         args.speed, args.instruction, "(base_url)")
        speech_cost_redline(args.text)
    except (InputError, CostRedlineError) as e:
        write_meta(mpath, base_meta(out_path, "failed", "(n/a)", "(n/a)",
                                    [f"{type(e).__name__}: {e}"], text_len=len((args.text or "").strip())))
        log(f"[FAIL] {e}")
        return 4 if isinstance(e, CostRedlineError) else 2

    # ---- 凭据 ----
    try:
        key, base_url = load_credentials(args.env_file)
    except CredentialsError as e:
        write_meta(mpath, base_meta(out_path, "failed", "(n/a)", "(n/a)", [str(e)],
                                    text_len=len(body["input"])))
        log(f"[FAIL] {e}")
        return 2
    if args.base_url:
        base_url = args.base_url.rstrip("/")   # CLI 显式覆盖 > env-file/env > 默认
    masked = mask_key(key)
    url, body = build_speech_request(args.text, args.model, args.voice_id, fmt,
                                     args.speed, args.instruction, base_url)
    files_url = args.files_url or (urllib.parse.urlsplit(base_url)._replace(
        path="/v1/files").geturl())
    log(f"[cfg] base={base_url} model={args.model} voice={args.voice_id} "
        f"format={fmt} speed={args.speed} key={masked}")

    # ---- dry-run：请求全构造、零 HTTP、不落音频 ----
    if args.dry_run:
        est = cost_estimate_meta(args.text)
        preview = {"method": "POST", "url": url,
                   "headers": {"Authorization": f"Bearer {masked}",
                               "Content-Type": "application/json"},
                   "body": body}
        write_meta(mpath, base_meta(
            out_path, "dry_run", masked, base_url, errors,
            dry_run=True, text_len=len(body["input"]),
            credits_or_cost_estimate=est,
            duration_s=None, duration_estimate_s=duration_estimate_s(args.text),
            request_id=None, latency_s=round(time.time() - t0, 3),
            sha256=None, request_preview=preview,
            clone=args.clone and {"would": "/v1/files → /audio/voices（dry-run 不发）",
                                  "ref_audio": args.ref_audio,
                                  "voice_name": args.voice_name}))
        log("[dry-run] 零 HTTP 调用（请求构造见 meta.request_preview），不落音频")
        return 0

    # ---- 克隆闭环（如启用） ----
    clone_meta = None
    voice = args.voice_id
    try:
        if args.clone:
            if not args.ref_audio:
                raise InputError("--clone 需要 --ref-audio")
            voice, clone_meta = clone_voice(key, base_url, files_url,
                                            Path(args.ref_audio), args.model,
                                            args.clone_text, args.timeout)
            body["voice"] = voice
            log(f"[tts] 使用克隆音色 voice_id={voice} voice_name={args.voice_name!r}")
    except (InputError, RuntimeError, urllib.error.URLError, TimeoutError) as e:
        errors.append(f"clone_failed: {type(e).__name__}: {e}")
        write_meta(mpath, base_meta(out_path, "failed", masked, base_url, errors,
                                    text_len=len(body["input"]), clone=clone_meta,
                                    latency_s=round(time.time() - t0, 3)))
        log(f"[FAIL] clone: {e}")
        return 2 if isinstance(e, InputError) else 1

    # ---- 合成（单次尝试） ----
    log(f"[tts] POST {url} input_len={len(body['input'])} → {out_path}")
    try:
        res = http_post(url, key, json_body=body, timeout=args.timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        errors.append(f"http_failed: {type(e).__name__}: {e}")
        write_meta(mpath, base_meta(out_path, "failed", masked, base_url, errors,
                                    text_len=len(body["input"]), request_url=url,
                                    voice_id=voice, clone=clone_meta,
                                    latency_s=round(time.time() - t0, 3),
                                    request_id=None,
                                    credits_or_cost_estimate=cost_estimate_meta(args.text)))
        log(f"[FAIL] http: {e}")
        return 1

    latency = round(time.time() - t0, 3)
    if res["status"] != 200:
        # 200 以外一律失败：错误体（含服务端 request_id/error 信息）原样进 meta，不伪造成功
        err_body = res["body"][:500]
        snippet = err_body.decode("utf-8", "replace")
        errors.append(f"speech_http_{res['status']}: {snippet}")
        write_meta(mpath, base_meta(
            out_path, "failed", masked, base_url, errors,
            text_len=len(body["input"]), request_url=url, http_status=res["status"],
            voice_id=voice, clone=clone_meta, request_id=res["request_id"],
            latency_s=latency,
            credits_or_cost_estimate=cost_estimate_meta(args.text),
            response_body_snippet=snippet))
        log(f"[FAIL] HTTP {res['status']}（key={masked}）: {snippet[:200]}")
        return 1

    # 200 但返回 JSON = 服务端软错误（fail-closed：不把 JSON 当音频落盘）
    if res["body"][:1] == b"{":
        snippet = res["body"][:500].decode("utf-8", "replace")
        errors.append(f"speech_soft_error_json: {snippet}")
        write_meta(mpath, base_meta(out_path, "failed", masked, base_url, errors,
                                    text_len=len(body["input"]), request_url=url,
                                    http_status=200, voice_id=voice, clone=clone_meta,
                                    request_id=res["request_id"], latency_s=latency,
                                    credits_or_cost_estimate=cost_estimate_meta(args.text),
                                    response_body_snippet=snippet))
        log(f"[FAIL] HTTP 200 但响应为 JSON（疑似软错误）: {snippet[:200]}")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(res["body"])
    log(f"[tts] 落盘 {out_path}（{len(res['body'])}B sniff={sniff_audio(res['body'])}）")

    # ---- ffprobe 实测（失败→status=failed，时长 null，不拿估算冒充） ----
    duration = None
    probe = None
    try:
        probe = ffprobe_audio(out_path)
        duration = probe["duration_s"]
    except Exception as e:  # noqa: BLE001 — ffprobe 缺失/非音频都是失败证据
        errors.append(f"ffprobe_failed: {e}")
        log(f"[WARN] ffprobe 失败: {e}")

    meta = base_meta(out_path, "failed" if errors else "ok", masked, base_url, errors,
                     dry_run=False, model=args.model, voice_id=voice,
                     voice_name=args.voice_name if args.clone else None,
                     instruction=args.instruction, response_format=fmt,
                     speed=args.speed, text_len=len(body["input"]),
                     billing_note="credits_or_cost_estimate 为牌价估算（见其 basis 字段）",
                     credits_or_cost_estimate=cost_estimate_meta(args.text),
                     request_id=res["request_id"], latency_s=latency,
                     sha256=hashlib.sha256(res["body"]).hexdigest(),
                     size_bytes=len(res["body"]), audio_sniff=sniff_audio(res["body"]),
                     duration_s=duration, ffprobe=probe, clone=clone_meta)
    write_meta(mpath, meta)
    if errors:
        log(f"[FAIL] 合成完成但存在错误项（status=failed）: {errors}")
        return 1
    log(f"[done] duration={duration}s cost_est=¥{meta['credits_or_cost_estimate']['cny_doc_rate_est']} "
        f"latency={latency}s request_id={res['request_id']}")
    return 0


# =====================================================================
# CLI
# =====================================================================
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="CP10 字幕音轨 StepFun TTS（stepaudio-2.5-tts 合成+克隆，纯标准库）")
    ap.add_argument("--text", required=True, help="台词文本（≤1000 字符，官方上限）")
    ap.add_argument("--out", required=True, help="输出音频路径（后缀决定 response_format：wav|mp3|flac|opus|pcm）")
    ap.add_argument("--voice-id", default=DEFAULT_VOICE,
                    help=f"官方音色或克隆 voice_id（默认 {DEFAULT_VOICE}）")
    ap.add_argument("--speed", type=float, default=1.0, help="0.5~2.0（官方范围，默认 1.0）")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"默认 {DEFAULT_MODEL}")
    ap.add_argument("--instruction", default=None,
                    help="全局语气指导（仅 stepaudio-2.5/3-tts；行内括号控制直接写在 --text 里）")
    ap.add_argument("--response-format", default=None,
                    help=f"覆盖输出格式枚举 {'|'.join(SUPPORTED_FORMATS)}（默认按 --out 后缀）")
    ap.add_argument("--dry-run", action="store_true",
                    help="构造请求但不发任何 HTTP、不落音频（meta 记 request_preview）")
    ap.add_argument("--env-file", default=None,
                    help="api_keys.env 路径（解析后只进内存；缺省读进程环境 STEPFUN_API_KEY）")
    ap.add_argument("--base-url", default=None,
                    help=f"覆盖 API base（默认 env STEPFUN_BASE_URL 或 {DEFAULT_BASE_URL}）")
    ap.add_argument("--files-url", default=None,
                    help="覆盖克隆上传端点（默认 <origin>/v1/files，官方 files 页口径）")
    ap.add_argument("--timeout", type=float, default=120.0, help="单请求超时秒")
    ap.add_argument("--clone", action="store_true",
                    help="零样本克隆闭环：/v1/files 上传→/audio/voices 注册→voice_id 参与本次合成")
    ap.add_argument("--ref-audio", default=None, help="克隆参考音频（mp3/wav，官方口径 5-10s）")
    ap.add_argument("--voice-name", default=None,
                    help="克隆音色的本地别名标签（官方 DTO 无 name 字段，仅记 meta/日志）")
    ap.add_argument("--clone-text", default=None,
                    help="克隆音频文字转写（/audio/voices 的选填 text；缺省服务端 ASR）")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except SystemExit:
        raise
    except Exception as e:  # 最后兜底：失败也是数据，落 meta 不静默
        try:
            write_meta(meta_path_for(Path(args.out)),
                       {"module": MODULE_ID, "generated_at": now_iso(),
                        "status": "failed", "errors": [f"{type(e).__name__}: {e}"]})
        except Exception:
            pass
        log(f"[FAIL] {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
