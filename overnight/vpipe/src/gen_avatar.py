#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_avatar.py — Vidu S2 avatar 非实时档（offline avatar）客户端（vpipe v4）
=====================================================================================

定位（vpipe SPEC §2 家族风格：单文件、零兄弟 import、纯 stdlib、CLI、fail-closed、
失败写 errors 不静默）：

契约来源（2026-10-09 官方提取，全文见 evidence/vidu_s2_avatar_contract.md）：
  - 官方文档 https://platform.vidu.cn/vidu-stream/doc 的 s2-avatar/async/{introduction,
    parameters,quick-start} 三页（Next.js RSC payload 内嵌 markdown 原文，与浏览器渲染同源）。
  - 创建：POST {base}/ent/s_avatar/offline，Authorization: Token <key>（官方 Token 方案，
    非 Bearer），Content-Type: application/json
  - 查询：GET  {base}/ent/v2/tasks/{task_id}/creations
    state: created/queueing/processing 中间态；success/failed 终态。success 后才读
    creations[]（url/cover_url/watermarked_url，均 24h 有效须即时落盘）。
    credits 字段=实扣积分=duration（1 积分/秒）。progress 会长期停在 99，勿作卡死判据。
  - 计费（官方「定价信息」）：1 积分/秒（0.03125 元），按输入音频实际时长向上取整；
    text 模式按合成语音时长计费（约 2-3 字/秒）；余额<45 不能发起任务；创建只预检不扣费，
    排队时一次性预扣，失败退还，最终以查询 credits 为准。
  - watermark：官方默认【加水印】，须显式传 false 才出无水印 url——本客户端默认显式 false。
  - model：创建默认 vidu-s1（可省略），查询返回 vidus1（无连字符），官方明示两者写法不同。

未文档化 / 未确证项（不编造，逐条注明来源）：
  - 余额端点 GET /ent/v2/credits 不在 S2 文档站内：端点与响应结构来自 v3 期实测
    （工程方案v3.1.md §0.2 V6 / §2.4①，vidu_avatar_client.py 口径：general_remains[]/
    exclusive_remains[] 数组、元素含 credit_remain）+ 主控 2026-10-09 实测 200。
    认证方案官方未提，本客户端 Token 优先、同 key 401/403 时降级试 Bearer，实试结果记入输出。
  - 并发限 5 是主控运营口径（两把 key 各配 avatar 专属池 5000 积分）；官方仅有
    QuotaExceeded（超并发）错误语义，无预查端点，故「并发满」守卫只能在提交后被动发现。
  - 走通用池还是专属池：官方文档无池概念；v3 期实测 avatar 任务扣的是通用池。本客户端
    守卫取两池最大值，任务前后双池差值全部留痕，以实测为准。

CLI:
  python3 src/gen_avatar.py balance [--env-file F]          # 双 key 轮询余额（掩码打印）
  python3 src/gen_avatar.py create --image REF.png --audio A.wav
            [--resolution 720p] [--actions '{"actions":[...]}'] [--text "口播文本"]
            [--voice V] [--out-dir D] [--timeout S] [--env-file F] [--dry-run]
  python3 src/gen_avatar.py status --task-id ID [--out-dir D] [--env-file F]

素材传入：本地文件读为 base64 data URI（官方支持形式之一，须含 MIME 前缀）；http(s) URL
直接透传。image 官方仅支持 1 张单人图。

行为要点：
  - 双 key 故障转移：仅 401/403（Unauthorized/Forbidden）自动换第二把，两把都败 fail-closed。
  - 积分守卫：提交前必查 /ent/v2/credits；预估积分 = ceil(音频时长)（text 模式 ceil(字符/2)）；
    max(通用池,专属池) < 预估+45 → exit 3 不提交；余额端点探测失败也 fail-closed（exit 3）。
  - 轮询：官方建议 3~5s 起步退避、不低于 2s、总超时 5 分钟——本客户端 3s 起 ×1.3 退避
    （上限 8s），默认总超时 420s，只认终态不认 progress。
  - 成功后即时下载 mp4（24h 纪律）+ sha256 + ffprobe + .meta.json（credits 实读/估算、
    task_id、latency、repro 口径）；产物一律 chmod 644。
  - --dry-run 零 HTTP：校验输入、ffprobe 音频估积分、打印将提交的 DTO 后退出。
  - 密钥纪律：key 只从 env（VIDU_API_KEY_1/VIDU_API_KEY_2）或 --env-file 读；
    日志只出掩码（前 6 字符 + 长度），本文件与产物无密钥字面量。

退出码：0 成功 / 2 输入或契约校验失败 / 3 积分守卫拦截 / 1 运行或生成失败。
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------- 控制台编码（跨平台兜底） ----------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MODULE_ID = "gen_avatar.py@vpipe-v4-1.0"

# ---------- 官方契约常量（evidence/vidu_s2_avatar_contract.md §3-§7） ----------
DEFAULT_BASE = "https://api.vidu.cn"          # 官方国内环境；海外 api.vidu.com
ENV_CREATE = "/ent/s_avatar/offline"          # POST 创建任务（官方）
ENV_QUERY = "/ent/v2/tasks/{task_id}/creations"  # GET 查询任务（官方）
ENV_CREDITS = "/ent/v2/credits"               # GET 余额（未文档化，v3 实测口径）
MIN_BALANCE = 45                              # 官方：余额<45 积分不能发起任务
RESOLUTIONS = ("540p", "720p")                # 官方可选值，默认 540p
CONTRACT_SOURCE = ("https://platform.vidu.cn/vidu-stream/doc/s2-avatar/async/"
                   "{introduction,parameters,quick-start} (2026-10-09)")
TERMINAL_STATES = {"success", "failed"}

IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp"}
AUDIO_MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
              ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg"}

TEXT_CHARS_PER_SEC_EST = 2.0   # 官方口径 text 模式约 2-3 字/秒；守卫取保守下限 2 字/s


def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[gen_avatar {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def mask_key(key: str) -> str:
    """日志掩码：前 6 字符 + 长度（零回显纪律）。"""
    return f"{key[:6]}…(len={len(key)})" if key else "<empty>"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def chmod644(path: Path) -> None:
    try:
        os.chmod(path, 0o644)
    except OSError as e:
        log(f"[warn] chmod 644 失败 {path}: {e}")


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    chmod644(path)


# =====================================================================
# 1) 凭据装载（只从 env / --env-file；零回显）
# =====================================================================
def load_keys(env_file: str | None) -> list[dict]:
    """返回 [{"label": "VIDU_API_KEY_1", "key": "..."}]；顺序 = 故障转移顺序。"""
    env: dict[str, str] = {}
    if env_file:
        p = Path(env_file)
        if not p.is_file():
            raise FileNotFoundError(f"--env-file 不存在: {p}")
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    else:
        env = dict(os.environ)
    keys = []
    for name in ("VIDU_API_KEY_1", "VIDU_API_KEY_2"):
        v = env.get(name, "")
        if v:
            keys.append({"label": name, "key": v})
    if not keys:
        raise ValueError("未找到凭据：环境变量/ env 文件中无 VIDU_API_KEY_1/VIDU_API_KEY_2"
                         "（key 零入 git，只从 env 或 --env-file 读）")
    return keys


# =====================================================================
# 2) HTTP（stdlib urllib；无兄弟依赖）
# =====================================================================
class ApiError(Exception):
    """携带 HTTP 状态与响应体的 API 错误（fail-closed 材料体）。"""

    def __init__(self, status: int, body: str, url: str, auth_label: str = ""):
        super().__init__(f"HTTP {status} {url} [{auth_label}]: {body[:500]}")
        self.status = status
        self.body = body
        self.url = url
        self.auth_label = auth_label

    @property
    def reason(self) -> str:
        """官方：请求级错误在响应体 reason 字段。"""
        try:
            return str(json.loads(self.body).get("reason", ""))
        except Exception:
            return ""


def http_json(method: str, url: str, key: str, scheme: str = "Token",
              body: dict | None = None, timeout: int = 60) -> tuple[int, dict | str]:
    """一次 HTTP JSON 调用。返回 (status, parsed_json_or_text)；非 2xx 抛 ApiError。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"{scheme} {key}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", errors="replace"), url,
                       f"{scheme}/{mask_key(key)}") from None
    except urllib.error.URLError as e:
        raise ApiError(0, f"URLError: {e.reason}", url, f"{scheme}/{mask_key(key)}") from None
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


def api_call(method: str, url: str, keys: list[dict], body: dict | None = None,
             timeout: int = 60, scheme_fallback: bool = False,
             log_ctx: str = "") -> tuple[dict | str, dict]:
    """官方 Token 方案优先；401/403 时（可选）同 key 降级试 Bearer（scheme_fallback，
    仅用于未文档化端点），再换下一把 key；两把都败 fail-closed。
    返回 (resp, call_info)；call_info 记录命中的 key 掩码与方案（留痕用）。"""
    attempts: list[str] = []
    schemes = ("Token", "Bearer") if scheme_fallback else ("Token",)
    for kd in keys:
        for scheme in schemes:
            attempts.append(f"{kd['label']}:{scheme}")
            try:
                status, resp = http_json(method, url, kd["key"], scheme=scheme,
                                         body=body, timeout=timeout)
                info = {"auth": f"{kd['label']}:{scheme}", "key_masked": mask_key(kd["key"]),
                        "status": status, "attempts": attempts}
                if log_ctx:
                    log(f"[api] {log_ctx} ← {status} via {kd['label']}:{scheme}")
                return resp, info
            except ApiError as e:
                if e.status in (401, 403):
                    log(f"[api] {log_ctx} ← 401/403 via {kd['label']}:{scheme}，"
                        f"{'降级/换 key 重试' if len(attempts) < len(keys) * len(schemes) else '两把皆败'}")
                    continue
                raise  # 非 401/403：如实上抛（不换 key——官方 Forbidden 之外无换 key 语义）
    raise ApiError(0, f"双 key 全败（attempts={attempts}）", url, "all-keys")


# =====================================================================
# 3) 余额 / 积分守卫
# =====================================================================
def parse_pools(resp) -> dict | None:
    """/ent/v2/credits → {"general": int|None, "exclusive": int|None}
    （响应结构为 v3 期实测口径：general_remains[]/exclusive_remains[]、元素含 credit_remain；
    端点未文档化，解析失败返回 None 如实降级，不猜字段。）"""
    if not isinstance(resp, dict):
        return None

    def first(sec: str):
        arr = resp.get(sec) or []
        if arr and isinstance(arr[0], dict) and arr[0].get("credit_remain") is not None:
            return int(arr[0]["credit_remain"])
        return None

    if "general_remains" not in resp and "exclusive_remains" not in resp and "remains" not in resp:
        return None
    pools = {"general": first("general_remains"), "exclusive": first("exclusive_remains")}
    if pools["general"] is None and pools["exclusive"] is None:
        legacy = first("remains")
        if legacy is not None:
            pools["general"] = legacy
    return pools


def fetch_pools(keys: list[dict]) -> tuple[dict | None, dict]:
    url = f"{DEFAULT_BASE}{ENV_CREDITS}"
    resp, info = api_call("GET", url, keys, scheme_fallback=True, log_ctx="credits")
    return parse_pools(resp), {"endpoint": ENV_CREDITS, **info, "resp_keys":
                               sorted(resp.keys()) if isinstance(resp, dict) else str(type(resp))}


def credit_guard(keys: list[dict], est_credits: int) -> tuple[bool, dict]:
    """提交前必查余额；通用池 < est+45 → 拒绝；探测失败 fail-closed。
    守卫口径（2026-10-10 smoke 实测修正）：/ent/s_avatar/offline 的提交校验按【通用池】，
    avatar 专属池（exclusive=5000）不被 offline 任务采纳——实证：key 专属池 5000 但通用池空，
    提交返回 HTTP 400 reason=CreditInsufficient；与 v3 期实证一致（工程方案v3.1 §0.2 V6 期，
    avatar 任务实扣通用池 683→622、专属池不动）。专属池数值仍记录在案供对账。"""
    pools, info = fetch_pools(keys)
    guard = {"est_credits": est_credits, "min_required": est_credits + MIN_BALANCE,
             "credits_probe": info, "pools": pools, "rule":
             f"general >= est+{MIN_BALANCE}（官方：余额<45 不能发起任务；2026-10-09 smoke 实测："
             f"提交校验走通用池，专属池不被 offline 任务采纳）"}
    if pools is None:
        guard["verdict"] = "probe_failed_fail_closed"
        log("[guard] 余额探测失败（端点未文档化，结构不合预期）→ fail-closed exit 3")
        return False, guard
    if pools["general"] is None:
        guard["verdict"] = "insufficient_general_pool_absent"
        guard["note"] = "通用池余额缺失/为空；专属池存在也不放行（2026-10-09 smoke 实测 CreditInsufficient）"
        log(f"[guard] 通用池缺失（专属池={pools['exclusive']} 不被采纳）→ 拒绝提交（exit 3）")
        return False, guard
    if pools["general"] < est_credits + MIN_BALANCE:
        guard["verdict"] = "insufficient"
        log(f"[guard] 通用池 {pools['general']} < 预估 {est_credits}+{MIN_BALANCE} → 拒绝提交（exit 3）")
        return False, guard
    guard["verdict"] = "pass"
    guard["available"] = pools["general"]
    log(f"[guard] 通用={pools['general']} 专属={pools['exclusive']}(不参与) 预估={est_credits} → 放行")
    return True, guard


# =====================================================================
# 4) 输入校验 / 素材编码
# =====================================================================
def is_remote(s: str) -> bool:
    return bool(re.match(r"^https?://", s or ""))


def to_data_uri(path: Path, mime_table: dict, kind: str) -> tuple[str, dict]:
    if not path.is_file():
        raise FileNotFoundError(f"{kind} 文件不存在: {path}")
    mime = mime_table.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"{kind} 格式不支持（{tuple(mime_table)}）: {path.suffix}")
    raw = path.read_bytes()
    info = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw), "transport": "base64_data_uri",
            "mime": mime}
    if kind == "image" and len(raw) > 10 << 20:
        raise ValueError(f"图片超 10MB（base64 请求体上限风险，官方建议大文件走 URL）: {path}")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", info


def validate_actions(actions_json: str) -> list[dict]:
    """官方 timeline 契约：actions[].text + time_range(2×uint32)；返回解析后的列表。"""
    try:
        obj = json.loads(actions_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"--actions 不是合法 JSON: {e}")
    if not (isinstance(obj, dict) and isinstance(obj.get("actions"), list) and obj["actions"]):
        raise ValueError('--actions 须为 {"actions":[...]} 非空结构（官方 timeline 格式）')
    for i, a in enumerate(obj["actions"]):
        if not (isinstance(a, dict) and isinstance(a.get("text"), str) and a["text"].strip()):
            raise ValueError(f"actions[{i}].text 须为非空字符串")
        tr = a.get("time_range")
        if not (isinstance(tr, list) and len(tr) == 2
                and all(isinstance(x, int) and 0 <= x <= 0xFFFFFFFF for x in tr)):
            raise ValueError(f"actions[{i}].time_range 须为 2 个 uint32（官方约束）")
        if tr[0] >= tr[1]:
            raise ValueError(f"actions[{i}].time_range 起始须小于结束: {tr}")
    return obj["actions"]


def ffprobe_audio(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"音频不存在: {path}")
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr[:300]}")
    meta = json.loads(r.stdout)
    dur = float((meta.get("format") or {}).get("duration") or 0)
    a = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), None)
    return {"duration_s": round(dur, 3), "acodec": (a or {}).get("codec_name"),
            "sample_rate": (a or {}).get("sample_rate"), "channels": (a or {}).get("channels")}


def ffprobe_av(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr[:300]}")
    meta = json.loads(r.stdout)
    v = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), None)
    return {"duration_s": round(float((meta.get("format") or {}).get("duration") or 0), 3),
            "vcodec": (v or {}).get("codec_name"), "acodec": (a or {}).get("codec_name"),
            "width": (v or {}).get("width"), "height": (v or {}).get("height"),
            "fps": (v or {}).get("avg_frame_rate"), "has_audio": a is not None}


# =====================================================================
# 5) create：提交 → 轮询 → 即时落盘
# =====================================================================
def poll_task(task_id: str, keys: list[dict], timeout_s: int) -> tuple[dict, dict]:
    """官方轮询协议：3s 起步 ×1.3 退避（上限 8s，不低于 2s），只认终态。"""
    url = f"{DEFAULT_BASE}{ENV_QUERY.format(task_id=task_id)}"
    t0 = time.time()
    interval, polls, last = 3.0, 0, None
    while True:
        polls += 1
        last, info = api_call("GET", url, keys, log_ctx=f"poll#{polls}")
        if not isinstance(last, dict):
            raise ApiError(0, f"查询响应非 JSON: {str(last)[:300]}", url)
        state = str(last.get("state", ""))
        if state in TERMINAL_STATES:
            return last, {"polls": polls, "elapsed_s": round(time.time() - t0, 1),
                          "query_call": info}
        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"轮询超时 {timeout_s}s（polls={polls}），最后 state={state} "
                               f"progress={last.get('progress')} task_id={task_id}"
                               f"（官方：progress 停 99 属正常，勿作判据）")
        time.sleep(interval)
        interval = min(8.0, interval * 1.3)


def download(url: str, dest: Path, timeout: int = 300) -> dict:
    t0 = time.time()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        nbytes = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            nbytes += len(chunk)
    chmod644(dest)
    return {"size_bytes": nbytes, "elapsed_s": round(time.time() - t0, 2),
            "note": "产物 URL 24h 有效，已即时落盘（官方纪律）"}


def cmd_create(a) -> int:
    errors: list[str] = []
    out_dir = Path(a.out_dir)
    image_p, audio_p = Path(a.image), Path(a.audio) if a.audio else None

    # ---- 输入校验（fail-fast，0 成本） ----
    if a.resolution not in RESOLUTIONS:
        print(f"[validate] resolution 须为 {RESOLUTIONS}（官方可选值），got {a.resolution!r}")
        return 2
    if not audio_p and not (a.text or "").strip():
        print("[validate] --audio 与 --text 至少传一个（官方约束；双传以 audio 为准）")
        return 2
    actions = None
    if a.actions:
        try:
            actions = validate_actions(a.actions)
        except ValueError as e:
            print(f"[validate] {e}")
            return 2
    try:
        keys = load_keys(a.env_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"[validate] {e}")
        return 2

    mode = "audio" if audio_p else "text"
    est_credits, audio_probe = 0, None
    image_uri = image_info = audio_uri = audio_info = None
    try:
        if is_remote(a.image):
            image_uri, image_info = a.image, {"path": a.image, "transport": "url"}
        else:
            image_uri, image_info = to_data_uri(image_p, IMAGE_MIME, "image")
        if audio_p:
            audio_probe = ffprobe_audio(audio_p)
            est_credits = max(1, math.ceil(audio_probe["duration_s"]))  # 官方：ceil(音频时长)
            if is_remote(a.audio):
                audio_uri, audio_info = a.audio, {"path": a.audio, "transport": "url"}
            else:
                audio_uri, audio_info = to_data_uri(audio_p, AUDIO_MIME, "audio")
        else:
            est_credits = max(1, math.ceil(len(a.text.strip()) / TEXT_CHARS_PER_SEC_EST))
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[validate] {type(e).__name__}: {e}")
        return 2
    est_basis = audio_probe["duration_s"] if audio_probe else f"text {len((a.text or '').strip())}字"
    log(f"[validate] mode={mode} est_credits={est_credits} "
        f"basis={est_basis} image_sha={image_info['sha256'][:12]}…")

    dto: dict = {
        "image": image_uri,
        "resolution": a.resolution,
        "watermark": False,   # 官方默认加水印，须显式 false 才出无水印 url
    }
    if audio_p:
        dto["audio"] = audio_uri
    else:
        dto["text"] = a.text.strip()
        if a.voice:
            dto["voice"] = a.voice   # 官方：voice 仅 text 模式生效
    if actions:
        dto["timeline"] = json.dumps({"actions": actions}, ensure_ascii=False)  # 序列化 JSON 串
    if a.payload:
        dto["payload"] = a.payload

    repro = {
        "module": MODULE_ID,
        "command": " ".join(["gen_avatar.py", "create", "--image", str(image_p)]
                            + (["--audio", str(audio_p)] if audio_p else [])
                            + (["--text", a.text.strip()] if not audio_p else [])
                            + (["--resolution", a.resolution])
                            + (["--actions", a.actions] if a.actions else [])
                            + (["--voice", a.voice] if a.voice else [])),
        "base_url": DEFAULT_BASE, "create_endpoint": ENV_CREATE, "query_endpoint": ENV_QUERY,
        "contract_source": CONTRACT_SOURCE,
        "billing_rule": "1 积分/s × ceil(输入音频时长)；text 模式按合成语音时长（约 2-3 字/s）",
        "key_labels": [k["label"] for k in keys],
        "image": image_info,
        "audio": audio_info,
        "audio_probe": audio_probe,
        "mode": mode,
    }

    if a.dry_run:
        dry = {"status": "dry_run", "est_credits": est_credits,
               "dto_preview": {k: (v[:60] + f"…({len(v)} chars)" if k in ("image", "audio")
                                   and isinstance(v, str) else v)
                               for k, v in dto.items()},
               "repro": repro, "note": "--dry-run 零 HTTP：未查余额、未提交"}
        print(json.dumps(dry, ensure_ascii=False, indent=1))
        return 0

    # ---- 积分守卫（提交前必查；不通过 exit 3 不提交） ----
    try:
        ok, guard = credit_guard(keys, est_credits)
    except ApiError as e:
        print(f"[guard] 余额探测 API 失败 → fail-closed: {e}")
        write_meta(out_dir, {"status": "credit_guard_probe_failed", "errors": [str(e)],
                             "repro": repro})
        return 3
    pools_before = guard.pop("pools")
    if not ok:
        write_meta(out_dir, {"status": "credit_guard_rejected",
                             "errors": [f"credit_guard: {guard.get('verdict')} "
                                        f"avail={guard.get('available_max')} "
                                        f"need>={guard.get('min_required')}"],
                             "guard": guard, "pools_before": pools_before, "repro": repro})
        return 3

    # ---- 提交（401/403 双 key 转移；官方创建只预检不扣费） ----
    t0 = time.time()
    try:
        resp, submit_info = api_call("POST", f"{DEFAULT_BASE}{ENV_CREATE}", keys,
                                     body=dto, timeout=120, log_ctx="create")
    except ApiError as e:
        if e.reason == "QuotaExceeded":
            errors.append(f"QuotaExceeded: 超并发限制（官方 reason；并发限 5 为运营口径）")
        elif e.reason == "CreditInsufficient":
            errors.append("CreditInsufficient: 积分不足（官方任务 err_code 同名语义）")
        errors.append(f"submit_failed: {e}")
        write_meta(out_dir, {"status": "submit_failed", "errors": errors,
                             "pools_before": pools_before, "guard": guard, "repro": repro})
        log(f"[FAIL] 提交失败: {e}")
        return 1
    if not isinstance(resp, dict) or not resp.get("task_id"):
        errors.append(f"create 响应无 task_id: {json.dumps(resp, ensure_ascii=False)[:300]}")
        write_meta(out_dir, {"status": "submit_invalid_response", "errors": errors,
                             "response": resp, "repro": repro})
        return 1
    task_id = str(resp["task_id"])   # 官方：int64 按字符串处理
    log(f"[create] task_id={task_id} state={resp.get('state')} model={resp.get('model')}")

    # ---- 轮询 → 终态 ----
    try:
        final, poll_info = poll_task(task_id, keys, timeout_s=a.timeout)
    except (TimeoutError, ApiError) as e:
        errors.append(f"poll_failed: {type(e).__name__}: {e}")
        write_meta(out_dir, {"status": "poll_failed", "task_id": task_id, "errors": errors,
                             "pools_before": pools_before, "repro": repro,
                             "submit_response": resp})
        log(f"[FAIL] {errors[-1]}")
        return 1

    state = str(final.get("state"))
    err_code, err_msg = str(final.get("err_code") or ""), str(final.get("err_msg") or "")
    credits = final.get("credits")
    latency_s = round(time.time() - t0, 1)

    if state != "success":
        # 官方：failed 时 credits 应为 0（未实际消耗退还）；如实留痕
        errors.append(f"task_failed: state=failed err_code={err_code!r} err_msg={err_msg!r} "
                      f"credits={credits}（官方：以查询接口为准，failed 不扣费）")
        write_meta(out_dir, {"status": "failed", "task_id": task_id, "state": state,
                             "err_code": err_code, "err_msg": err_msg,
                             "credits": credits, "latency_s": latency_s,
                             "poll": poll_info, "pools_before": pools_before,
                             "submit_response": resp, "repro": repro, "errors": errors})
        log(f"[FAIL] task failed err_code={err_code} err_msg={err_msg}")
        return 1

    # ---- success：即时落盘（24h 纪律） + sha256 + ffprobe ----
    creations = final.get("creations") or []
    if not creations or not creations[0].get("url"):
        errors.append(f"success 但 creations 空/无 url: {json.dumps(final, ensure_ascii=False)[:300]}")
        write_meta(out_dir, {"status": "success_no_creation", "task_id": task_id,
                             "errors": errors, "final": final, "repro": repro})
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / f"avatar_{task_id}.mp4"
    dl = download(creations[0]["url"], mp4)
    probe = ffprobe_av(mp4)
    digest = sha256_file(mp4)

    # ---- 任务后余额差值（走通用池/专属池以实测为准） ----
    try:
        pools_after, _ = fetch_pools(keys)
    except ApiError as e:
        pools_after, errors = None, errors + [f"pools_after_probe_failed: {e}"]
    pools_delta = None
    if pools_before and pools_after:
        pools_delta = {k: (pools_before[k] - pools_after[k])
                       if pools_before.get(k) is not None and pools_after.get(k) is not None
                       else None for k in ("general", "exclusive")}

    meta = {
        "module": MODULE_ID, "status": "ok", "generated_at": now_iso(),
        "task_id": task_id, "type": final.get("type"), "state": state,
        "model_create": "vidu-s1(默认,未显式传)", "model_reported": final.get("model"),
        "resolution": final.get("resolution", a.resolution),
        "mode": mode,
        "credits": {"reported": credits, "estimated": est_credits,
                    "source": "GET /ent/v2/tasks/{id}/creations .credits（官方：实扣以此为准，"
                              "1 积分/s×ceil(音频秒)；failed 时为 0）",
                    "pools_before": pools_before, "pools_after": pools_after,
                    "pools_delta": pools_delta,
                    "delta_note": "官方文档无池概念；v3 期实测走通用池，本轮以差值实测为准"},
        "duration_s": final.get("duration"),
        "err_code": err_code, "err_msg": err_msg,
        "progress_note": final.get("progress"),
        "creations": [{"id": c.get("id"), "url_present": bool(c.get("url")),
                       "cover_url_present": bool(c.get("cover_url")),
                       "watermarked_url_present": bool(c.get("watermarked_url")),
                       "url_note": "临时 URL 24h 失效，不入留痕；视频已落盘 clip.path"}
                      for c in creations],
        "clip": {"path": str(mp4), "sha256": digest, **dl, **probe},
        "latency": {"submit_to_terminal_s": latency_s, "poll": poll_info,
                    "total_timeout_s": a.timeout},
        "submit_response": resp, "submit_call": submit_info,
        "guard": guard, "repro": repro, "errors": errors,
    }
    meta_path = write_meta(out_dir, meta)
    log(f"[done] {mp4.name} {probe['width']}x{probe['height']} {probe['duration_s']}s "
        f"credits={credits} latency={latency_s}s sha256={digest[:12]}… → {meta_path.name}")
    return 0


def write_meta(out_dir: Path, meta: dict) -> Path:
    """meta 落盘；无 task_id 时用时间戳命名（失败留痕纪律：errors 不静默）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = str(meta.get("task_id") or datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    path = out_dir / f"avatar_{stem}.meta.json"
    write_json(path, meta)
    return path


# =====================================================================
# 6) status / balance
# =====================================================================
def cmd_status(a) -> int:
    try:
        keys = load_keys(a.env_file)
        url = f"{DEFAULT_BASE}{ENV_QUERY.format(task_id=a.task_id)}"
        resp, info = api_call("GET", url, keys, log_ctx="status")
    except (ValueError, FileNotFoundError) as e:
        print(f"[validate] {e}")
        return 2
    except ApiError as e:
        print(f"[FAIL] {e}")
        return 1
    out = {"queried_at": now_iso(), "task_id": a.task_id, "endpoint": ENV_QUERY.format(
        task_id=a.task_id), "auth": info.get("auth"), "response": resp}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.out_dir:
        write_json(Path(a.out_dir) / f"status_{a.task_id}.json", out)
    return 0


def cmd_balance(a) -> int:
    try:
        keys = load_keys(a.env_file)
    except (ValueError, FileNotFoundError) as e:
        print(f"[validate] {e}")
        return 2
    report = {"queried_at": now_iso(), "endpoint": ENV_CREDITS,
              "endpoint_note": "未文档化端点（v3 实测口径 + 主控 2026-10-09 实测 200）；"
                               "Token 优先，401/403 同 key 降级试 Bearer", "keys": []}
    rc = 0
    for kd in keys:
        try:
            pools, info = fetch_pools([kd])
            entry = {"label": kd["label"], "key_masked": mask_key(kd["key"]),
                     "auth_used": info.get("auth"), "http_status": info.get("status"),
                     "pools": pools, "resp_keys": info.get("resp_keys")}
            if pools is None:
                entry["note"] = "响应结构不合 v3 实测口径（general/exclusive_remains），如实降级"
                rc = 1
        except ApiError as e:
            entry = {"label": kd["label"], "key_masked": mask_key(kd["key"]),
                     "error": str(e), "reason": e.reason}
            rc = 1
        report["keys"].append(entry)
        log(f"[balance] {kd['label']} {mask_key(kd['key'])} → {entry.get('pools', entry.get('error'))}")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return rc


# =====================================================================
# CLI
# =====================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="gen_avatar.py",
        description="Vidu S2 avatar 非实时档客户端（官方契约见 evidence/vidu_s2_avatar_contract.md）")
    ap.add_argument("--env-file", dest="env_file_global", default=None,
                    help="凭据文件（KEY=VALUE 行，读 VIDU_API_KEY_1/_2）；缺省读进程环境变量。"
                         "子命令前或后均可（两处都接受）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("balance", help="双 key 轮询余额（掩码打印，0 成本）")
    b.add_argument("--env-file", dest="env_file_sub", default=None)

    c = sub.add_parser("create", help="提交 avatar 任务并轮询到终态，产物即时落盘")
    c.add_argument("--image", required=True, help="参考图（本地文件或 http(s) URL；官方仅 1 张单人图）")
    c.add_argument("--audio", default=None, help="驱动音频（本地文件或 URL）；与 --text 至少一个")
    c.add_argument("--text", default=None, help="口播文本（text 模式，系统合成语音）")
    c.add_argument("--voice", default=None, help="音色（仅 text 模式生效，官方 voice-list）")
    c.add_argument("--resolution", default="540p", help="540p（官方默认）| 720p")
    c.add_argument("--actions", default=None,
                   help='timeline 动作 JSON：{"actions":[{"text":"比个心","time_range":[2,10]}]}')
    c.add_argument("--payload", default=None, help="透传参数（官方 payload 字段，原样返回）")
    c.add_argument("--out-dir", default=None, help="产物目录（默认 out/m2/<脚本相对>/avatar 惯例由调用方给）")
    c.add_argument("--timeout", type=int, default=420,
                   help="轮询总超时秒（官方建议 5 分钟量级；实测出片 40s~2min）")
    c.add_argument("--dry-run", action="store_true", help="零 HTTP：校验+估算+打印 DTO，不提交")
    c.add_argument("--env-file", dest="env_file_sub", default=None)

    s = sub.add_parser("status", help="按 task_id 查询一次任务状态")
    s.add_argument("--task-id", required=True, help="任务 ID（int64，按字符串处理）")
    s.add_argument("--out-dir", default=None, help="状态快照落盘目录（可选）")
    s.add_argument("--env-file", dest="env_file_sub", default=None)

    a = ap.parse_args(argv)
    a.env_file = getattr(a, "env_file_sub", None) or getattr(a, "env_file_global", None)
    if a.cmd == "balance":
        return cmd_balance(a)
    if a.cmd == "create":
        if not a.out_dir:
            a.out_dir = str(Path.cwd() / "avatar_out")
        return cmd_create(a)
    if a.cmd == "status":
        return cmd_status(a)
    return 2


if __name__ == "__main__":
    sys.exit(main())
