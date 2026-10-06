#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_api.py — vpipe API 生成模块：MiniMax 视频（默认 higress 云通道，可选 windev 客户端通道）
（vpipe SPEC.md 模块 2；云通道 2026-10-06 迁移自 windev 本机客户端网关 127.0.0.1:8001——
 windev 2026-10-07 销毁后本机客户端网关即断；端点依据 overnight/MiniMax-Design-接入手册.md §2，
 2026-10-06 实测验证。windev 通道逻辑原样保留为 --backend windev 可选后端。）

契约: 输入=contracts/shot.schema.json 合规的镜头 JSON（--shots 传目录/*.json 或 .jsonl）；
      输出=clip mp4 + 每条终态记录（api_results 式 jsonl）+ contracts/asset_manifest 登记条目。
      不 import 任何 vpipe 兄弟模块。
接口面（对调用方冻结，双通道一致）: CLI 参数/退出码 0成功 1无Shot 2网关或契约 3守卫拦截、
      api_results.jsonl 终态词表（succeeded/failed/submit_error/poll_error/poll_timeout）、
      build_payload/validate_base_url/probe_seed/poll_task/load_shots 签名均不变。

【云通道（默认，--backend cloud）】higress 网关直通 design.minimax.cn，调用方零凭据
  （token/device_id/Authorization 由网关注入，见接入手册 §0）：
  ① 提交  POST {cloud_base}/minimax-cloud/api/v1/video/minimax-v3/generate
          {model, prompt, duration, resolution, ratio, generate_audio, reference_images?/first_frame_image?}
          → {"task_id","base_resp":{"status_code":0}}
  ② 轮询  GET  {cloud_base}/minimax-cloud/api/v1/video/minimax-v3/tasks/{task_id}
          → status: processing→success（本模块归一化为旧词表 succeeded/failed）
  ③ 取片  GET  {cloud_base}/minimax-cloud/api/v1/video/minimax/files/{task_id}
          → file.download_url（CDN 直链，下载前过 validate_base_url 拒内网/环回）
  云通道差异（如实降级，不伪造）:
  - 健康检查 = 零消耗 GET /minimax/v1/models/config（手册 §6）；无应用可拉起。
  - 积分: 云通道无钱包端点（手册 §7 单价/余额未探明）→ 守卫降级为「估算累计」
    （56 积分/s 口径，按提交累计进 state，超 --credit-cap 即 exit 3）；
    credit_before/after/cost 如实记 null，另记 est_credit。
  - seed: 云 DTO 白名单无 seed 字段 → 一律不发送，probe_seed 不跑（windev 专属）。
  - 参考图: http(s) URL 直传 reference_images；本地路径需 /api/v1/files/upload
    （手册标注未实测）→ fail-closed 记 reference_unsupported_on_cloud，不盲调不伪造。
  - 参数预检: 按手册 §2 模型表（时长整数区间/分辨率档）本地校验，越界记 invalid_params
    不发 HTTP（不消耗额度试参）。

【windev 通道（可选，--backend windev）】原 MiniMax Design 本机客户端网关（历史，2026-10-07 后不可用）。
DTO 白名单（D:/agent-knowledge/07-minimax-design-api.md，实测勘误已吸收）:
  - 顶层仅 backend/model_id/prompt/filename/image_paths/params/source_tool；
    多传字段逐个报 "property X should not exist"（一次列全）。
  - 参考图走【顶层 image_paths】（首图=人物参考）；params.reference_images 被静默忽略！
  - params 全字符串；漏 resolution → 500；校验发生在扣费前，可安全试参。
积分守卫(windev): --credit-cap（默认 40000）硬上限；baseline 首跑记入 state；每条提交前查钱包，
  「已耗>上限」与「已耗+预估>上限」双重拦截，触发即 exit 3。
断点续跑: results jsonl 里已有终态的 rid 跳过（--retry-failed 可重跑失败条）。
URL 安全（发请求前校验）: 默认基址（云网关/windev 网关）为架构内授权端点，精确匹配默认值即放行
  内网地址；--base-url/--cloud-base-url 覆盖时强制 http/https 且拒绝环回/私有/保留地址，
  内网部署须显式 --allow-private / --allow-loopback 放行。

用法:
  python gen_api.py --shots shots/ --out-dir out/ [--backend cloud] [--credit-cap 40000]
                    [--dry-run] [--only S1] [--retry-failed]
  python gen_api.py make-shots --prompts ../数据/prompts.json --out-dir shots/   # 历史矩阵→Shot 契约适配器
"""
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
SHOT_SCHEMA = HERE.parent / "contracts" / "shot.schema.json"

# ---------------- 配置（集中于此；环境变量 VPIPE_GENAPI_* 可覆盖，风格沿 gen_local 的 VPIPE_* 前缀） ----------------
DEFAULT_BACKEND = os.environ.get("VPIPE_GENAPI_BACKEND", "cloud")      # cloud | windev
DEFAULT_CLOUD_BASE = os.environ.get("VPIPE_GENAPI_CLOUD_BASE",
                                    "http://100.64.0.6:8080")          # higress 网关（接入手册 §0/§2）
DEFAULT_BASE = os.environ.get("VPIPE_GENAPI_WINDEV_BASE",
                              "http://127.0.0.1:8001")                 # windev 本机客户端网关（保留通道）
CLOUD_GENERATE_PATH = "/minimax-cloud/api/v1/video/minimax-v3/generate"
CLOUD_TASK_PATH = "/minimax-cloud/api/v1/video/minimax-v3/tasks"       # + /{task_id}
CLOUD_FILES_PATH = "/minimax-cloud/api/v1/video/minimax/files"         # + /{task_id}
CLOUD_HEALTH_PATH = "/minimax/v1/models/config"                        # 零消耗探活（手册 §6，2026-10-06 实测 200）
APP_EXE = r"D:\d\MiniMax Design\current\MiniMax Design.exe"            # windev 通道应用
BACKEND = "minimax_v3"                                                 # windev DTO backend 字段（历史通道）
SOURCE_TOOL = "hub_generate_video:vpipe:gen_api"
BASE_PARAMS = {                                  # windev 07 手册 §三 已验证参数集；全字符串
    "image_mode": "reference",
    "duration": "5",
    "resolution": "768P",
    "aspect_ratio": "9:16",
    "generate_audio": "true",
}
MODEL_WH = {"480P": (480, 832), "768P": (768, 1344), "2K": (1088, 1920)}
# 云通道模型参数表（MiniMax-Design-接入手册 §2 实测目录；越界本地预检，不发 HTTP）
CLOUD_MODEL_CONSTRAINTS = {
    "MiniMax-H3":          {"duration": (4, 15), "resolutions": ("768P", "2K")},
    "MiniMax-H3-Max":      {"duration": (5, 15), "resolutions": ("480P", "768P")},
    "MiniMax-H3-Max-Turbo": {"duration": (5, 15), "resolutions": ("480P", "768P")},
}
EST_CREDITS_PER_SEC = 56     # 56 积分/s（windev /api/v1/billing/pricing 实测口径，云通道按此估算）
EST_PER_CLIP = 280           # EST_CREDITS_PER_SEC × 5s（windev 守卫沿用值）
TIMEOUT = int(os.environ.get("VPIPE_GENAPI_TIMEOUT", "30"))
CLOUD_DOWNLOAD_TIMEOUT = int(os.environ.get("VPIPE_GENAPI_DOWNLOAD_TIMEOUT", "300"))
POLL_INTERVAL = int(os.environ.get("VPIPE_GENAPI_POLL_INTERVAL", "15"))
POLL_TIMEOUT = int(os.environ.get("VPIPE_GENAPI_POLL_TIMEOUT", "900"))
POLL_ERR_LIMIT = 5
SUBMIT_RETRY_DELAY = 20
# 架构内授权端点（精确匹配默认值即放行内网地址；用户覆盖值仍走严格校验）
TRUSTED_DEFAULT_BASES = {DEFAULT_BASE, DEFAULT_CLOUD_BASE}


def log(msg):
    print(f"[gen_api {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ffprobe_clip(path):
    """本地 ffprobe 取产物真值（宽/高/时长/fps/编码）；不可得如实返回 None，不伪造。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        fmt = data.get("format", {})
        fps = v.get("avg_frame_rate") or v.get("r_frame_rate")
        try:
            num, den = fps.split("/")
            fps = round(float(num) / float(den), 3) if float(den) else None
        except Exception:
            pass
        return {"width": v.get("width"), "height": v.get("height"),
                "duration": (float(fmt["duration"]) if fmt.get("duration") else None),
                "fps": fps, "video_codec": v.get("codec_name"),
                "audio_codec": next((s.get("codec_name") for s in data.get("streams", [])
                                     if s.get("codec_type") == "audio"), None)}
    except Exception:
        return None


# ---------------- URL 安全校验（发请求前） ----------------
def _ip_allowed(ip, allow_private, allow_loopback):
    x = ipaddress.ip_address(ip)
    if x.is_loopback:
        return allow_loopback, "loopback"
    if x.is_private or x.is_link_local or x.is_reserved or x.is_multicast or x.is_unspecified:
        return allow_private, "private/reserved"
    return True, "global"


def validate_base_url(url, allow_private=False, allow_loopback=False):
    """http/https 白名单 + host 校验（拒绝环回/私有/保留，除非显式放行）。
    返回 (ok, reason)。默认网关（windev/云）的放行发生在调用点（授权端点，非用户输入）。"""
    try:
        u = urlparse(url)
    except Exception as e:
        return False, f"URL 解析失败: {e}"
    if u.scheme not in ("http", "https"):
        return False, f"scheme 必须是 http/https，得到 {u.scheme!r}"
    if u.username or u.password:
        return False, "不允许携带 userinfo"
    host = u.hostname
    if not host:
        return False, "缺少 host"
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"host 解析失败: {e}"
    for info in infos:
        ip = info[4][0]
        # IPv6 数组尾部的 %scope 去掉
        ip = ip.split("%", 1)[0]
        ok, kind = _ip_allowed(ip, allow_private, allow_loopback)
        if not ok:
            return False, f"host {host} → {ip} 是{kind}地址（未显式放行）"
    return True, "ok"


def make_session(base_url, allow_private, allow_loopback, trusted_default=True, backend=DEFAULT_BACKEND):
    """构造已校验的 HTTP session。默认网关是架构内授权端点（trusted_default=True 且精确匹配
    TRUSTED_DEFAULT_BASES 时放行内网地址；覆盖值一律严格校验）。"""
    ok, reason = validate_base_url(base_url, allow_private,
                                   allow_loopback or (trusted_default and base_url in TRUSTED_DEFAULT_BASES))
    if not ok:
        raise ValueError(f"--base-url 校验失败: {reason}")
    import requests
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    s.base_url = base_url.rstrip("/")
    s.backend = backend
    s.url_allow_private = allow_private
    s.url_allow_loopback = allow_loopback
    return s


# ---------------- windev 网关基础（run_api_matrix.py 已验证逻辑；--backend windev 专用） ----------------
def health_ok(sess):
    try:
        r = sess.get(sess.base_url + "/api/health", timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def ensure_app(sess):
    if health_ok(sess):
        log("[gateway] /api/health ok")
        return True
    log("[gateway] 未响应，尝试启动 MiniMax Design ...")
    try:
        subprocess.Popen(["powershell", "-Command",
                          f"Start-Process '{APP_EXE}' -WindowStyle Minimized"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"[gateway] 启动命令失败: {e}")
    for i in range(12):
        time.sleep(10)
        if health_ok(sess):
            log(f"[gateway] 已恢复（等待 {(i + 1) * 10}s）")
            return True
    return False


def wallet_credit(sess):
    r = sess.get(sess.base_url + "/api/v1/credit/wallet", timeout=TIMEOUT)
    r.raise_for_status()
    vals = []
    for w in r.json().get("wallets") or []:
        try:
            vals.append(int(str(w.get("total_credit", "0"))))
        except Exception:
            pass
    if not vals:
        raise RuntimeError("wallet 解析失败")
    return max(vals)


def get_workspace_dir(sess):
    fallback = Path(r"D:/d/MiniMax Design Data/output_files")
    try:
        r = sess.get(sess.base_url + "/api/workspace", timeout=TIMEOUT)
        d = r.json()
        if isinstance(d, dict):
            for k in ("dir", "workspace", "workspace_dir", "output_dir"):
                if d.get(k):
                    return Path(d[k])
    except Exception:
        pass
    return fallback


# ---------------- 云通道基础（MiniMax-Design-接入手册 §2，2026-10-06 实测端点） ----------------
def cloud_health_ok(sess):
    """零消耗探活：GET /minimax/v1/models/config（手册 §6，同网关 hub 路由）。"""
    try:
        r = sess.get(sess.base_url + CLOUD_HEALTH_PATH, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def est_credit_clip(duration_s):
    """云通道单条估算积分（56/s 口径）。是估算值，记录时标 est_，不冒充实扣。"""
    return int(EST_CREDITS_PER_SEC * float(duration_s))


def validate_cloud_params(shot, model_id):
    """按手册 §2 模型表本地预检（不发 HTTP、不耗额度）。返回 (ok, reason)。"""
    cons = CLOUD_MODEL_CONSTRAINTS.get(model_id)
    if cons is None:
        return True, None                      # 目录外模型交服务端裁决（fail-closed 于响应）
    d = shot["duration_s"]
    if float(d) != int(d):
        return False, f"duration_s={d} 非整数（H3 系要求整数秒）"
    lo, hi = cons["duration"]
    if not (lo <= int(d) <= hi):
        return False, f"duration_s={int(d)} 超出 {model_id} 区间 [{lo},{hi}]"
    res = shot.get("resolution") or "768P"
    if res not in cons["resolutions"]:
        return False, f"resolution={res} 不在 {model_id} 支持档 {cons['resolutions']}"
    return True, None


def build_cloud_payload(shot, model_id, ref_urls):
    """Shot 契约 → 云通道 DTO（手册 §2.1 实测字段白名单；多余字段不传）。"""
    payload = {
        "model": model_id,
        "prompt": shot["prompt"][:7000],
        "duration": int(shot["duration_s"]),
        "resolution": shot.get("resolution") or "768P",
        "ratio": shot["aspect"],
        "generate_audio": bool((shot.get("audio") or {}).get("generate", True)),
    }
    if ref_urls:
        payload["reference_images"] = list(ref_urls)     # 参考图数组（URL）；首帧图另字段 first_frame_image
    return payload


def cloud_submit(sess, payload):
    """① 提交。返回 (task_id, None) 或 (None, error_str)。fail-closed：非 0 status_code/缺 task_id 均报错。"""
    r = sess.post(sess.base_url + CLOUD_GENERATE_PATH, json=payload, timeout=TIMEOUT)
    if r.status_code not in (200, 201):
        return None, f"submit_http_{r.status_code}: {r.text[:300]}"
    try:
        data = r.json()
    except Exception as e:
        return None, f"submit_json_error: {e}: {r.text[:200]}"
    code = (data.get("base_resp") or {}).get("status_code")
    task_id = data.get("task_id")
    if not task_id and isinstance(data.get("data"), dict):
        task_id = data["data"].get("task_id")
    if code not in (0, None):
        return None, f"submit_base_resp_{code}: {(data.get('base_resp') or {}).get('status_msg', '')[:200]}"
    if not task_id:
        return None, f"submit 无 task_id: {r.text[:300]}"
    return task_id, None


def cloud_fetch_file(sess, task_id):
    """③ 取文件：files/{task_id} → {"file":{"download_url","file_id"}}。返回 (download_url, None) 或 (None, err)。"""
    r = sess.get(sess.base_url + f"{CLOUD_FILES_PATH}/{task_id}", timeout=TIMEOUT)
    if r.status_code != 200:
        return None, f"files_http_{r.status_code}: {r.text[:300]}"
    f = r.json().get("file") or {}
    url = f.get("download_url")
    if not url:
        return None, f"files 无 download_url: {r.text[:300]}"
    return url, None


def download_file(sess, url, dst):
    """CDN 下载（download_url 来自网关响应，下载前过 validate_base_url 拒内网/环回/保留地址）。"""
    ok, reason = validate_base_url(url, getattr(sess, "url_allow_private", False),
                                   getattr(sess, "url_allow_loopback", False))
    if not ok:
        return f"download_url 校验失败: {reason}"
    import requests
    with requests.get(url, stream=True, timeout=CLOUD_DOWNLOAD_TIMEOUT) as r:
        if r.status_code != 200:
            return f"download_http_{r.status_code}"
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
    return None


def _poll_task_cloud(sess, task_id):
    """② 轮询云任务：status processing→success/failed。终态词表在 run_generate 归一化。"""
    t0 = time.time()
    errs = 0
    while time.time() - t0 < POLL_TIMEOUT:
        try:
            r = sess.get(sess.base_url + f"{CLOUD_TASK_PATH}/{task_id}", timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            errs = 0
        except Exception as e:
            errs += 1
            if errs >= POLL_ERR_LIMIT:
                return {"status": "poll_error", "error": f"{type(e).__name__}: {e}"}
            time.sleep(POLL_INTERVAL)
            continue
        st = str(data.get("status") or "").lower()
        code = (data.get("base_resp") or {}).get("status_code")
        if st == "success":
            data["status"] = "success"
            return data
        if st in ("failed", "fail", "error") or (code not in (0, None)):
            return {"status": "failed", "raw": data,
                    "error": f"cloud task failed: status={st} base_resp={data.get('base_resp')} {str(data)[:200]}"}
        time.sleep(POLL_INTERVAL)
    return {"status": "poll_timeout", "error": f"超过 {POLL_TIMEOUT}s 未到终态"}


# ---------------- Shot → DTO（白名单） ----------------
def validate_shot(shot):
    try:
        import jsonschema
        schema = json.loads(SHOT_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(shot, schema)
        return True, None
    except ImportError:
        miss = [k for k in ("schema_version", "shot_id", "prompt", "duration_s", "aspect")
                if k not in shot]
        return not miss, f"jsonschema 不可用退回 required 检查，缺 {miss}" if miss else None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def build_payload(shot, model_id, include_seed, refs_resolved):
    """Shot 契约 → windev DTO 白名单 payload（历史通道）。多余信息显式丢弃并返回忽略清单。"""
    params = dict(BASE_PARAMS)
    params["duration"] = str(int(shot["duration_s"]))
    params["aspect_ratio"] = shot["aspect"]
    if shot.get("resolution"):
        params["resolution"] = shot["resolution"]
    params["generate_audio"] = "true" if (shot.get("audio") or {}).get("generate", True) else "false"
    if include_seed:
        params["seed"] = str(shot.get("seed", 42))
    ignored = []
    if shot.get("negative_prompt"):
        ignored.append("negative_prompt(H3 无此参数)")   # 07 手册 DTO 白名单
    payload = {
        "backend": BACKEND,
        "model_id": model_id,
        "prompt": shot["prompt"][:7000],
        "filename": f"{shot['shot_id']}_{model_id.replace('MiniMax-', '')}.mp4",
        "image_paths": list(refs_resolved),
        "params": params,
        "source_tool": SOURCE_TOOL,
    }
    return payload, ignored


def probe_seed(sess, state):
    """0 成本探测 params.seed 是否被 DTO 拒绝（windev 通道专属；run_api_matrix.py:198-256 已验证逻辑）。"""
    if state.get("seed_probe"):
        return state["seed_probe"]
    payload = {"backend": BACKEND, "model_id": "MiniMax-H3",
               "prompt": "[seed-probe] DTO 白名单探测，不应产生真实生成",
               "filename": "seed_probe.mp4", "image_paths": [],
               "params": dict(BASE_PARAMS, seed="42", unknown_probe_key_zzz="1"),
               "source_tool": SOURCE_TOOL}
    r = sess.post(sess.base_url + "/api/generate/video/submit", json=payload, timeout=TIMEOUT)
    probe = {"http": r.status_code, "response": r.text[:500], "at": now()}
    if r.status_code in (200, 201):
        task_id = None
        try:
            task_id = r.json().get("task_id")
        except Exception:
            pass
        probe.update(unexpected_accepted=True, task_id=task_id, dto_rejected=False,
                     decision="send_seed_with_verify(探测意外通过，已尝试取消；扣费风险≤224)")
        try:
            if task_id:
                sess.post(sess.base_url + "/api/generation/cancel",
                          json={"task_id": task_id}, timeout=TIMEOUT)
                probe["cancel_attempted"] = True
        except Exception as e:
            probe["cancel_error"] = str(e)
    else:
        msgs = []
        try:
            m = r.json().get("message")
            msgs = m if isinstance(m, list) else [str(m)]
        except Exception:
            msgs = [r.text]
        unknown = []
        for x in msgs:
            unknown += re.findall(r"property\s+\"?(\S+?)\"?\s+should not exist", str(x))
        probe["unknown_keys"] = unknown
        probe["dto_rejected"] = "seed" in unknown
        probe["decision"] = ("omit_seed(DTO 拒绝 seed → H3 无种子控制)" if probe["dto_rejected"]
                             else "send_seed_with_verify(未知键清单不含 seed)")
    state["seed_probe"] = probe
    state["seed_send_enabled"] = not probe["dto_rejected"]
    log(f"[seed-probe] HTTP {r.status_code} unknown={probe.get('unknown_keys')} 决策={probe['decision']}")
    return probe


def poll_task(sess, task_id):
    """轮询到终态（SPEC §2.2 冻结签名）。按 sess.backend 分派：cloud→三步流②；windev→原逻辑。"""
    if getattr(sess, "backend", "windev") == "cloud":
        return _poll_task_cloud(sess, task_id)
    t0 = time.time()
    errs = 0
    while time.time() - t0 < POLL_TIMEOUT:
        try:
            r = sess.get(sess.base_url + f"/api/generate/tasks/{task_id}/query", timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            errs = 0
        except Exception as e:
            errs += 1
            if errs >= POLL_ERR_LIMIT:
                return {"status": "poll_error", "error": f"{type(e).__name__}: {e}"}
            time.sleep(POLL_INTERVAL)
            continue
        if data.get("status") in ("succeeded", "failed"):
            return data
        time.sleep(POLL_INTERVAL)
    return {"status": "poll_timeout", "error": f"超过 {POLL_TIMEOUT}s 未到终态"}


# ---------------- 断点续跑 + 终态记录 ----------------
def load_done(results_file):
    done = {}
    if results_file.exists():
        for line in results_file.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("terminal"):
                done[rec.get("rid") or rec.get("id")] = rec
    return done


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ---------------- 主流程 ----------------
def run_generate(args):
    backend = args.backend
    shots = load_shots(args.shots)
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        shots = [s for s in shots if s["shot_id"] in want]
    if not shots:
        log("[FATAL] 过滤后没有可跑的 Shot")
        return 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_file = out_dir / "api_results.jsonl"
    state_file = out_dir / "api_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}

    base_url = args.cloud_base_url if backend == "cloud" else args.base_url
    try:
        sess = make_session(base_url, args.allow_private, args.allow_loopback, backend=backend)
    except ValueError as e:
        log(f"[FATAL] {e}")
        return 2

    if backend == "cloud":
        if not cloud_health_ok(sess):
            log(f"[FATAL] 云网关不可用（{base_url}{CLOUD_HEALTH_PATH} 非 200）→ 如实退出")
            return 2
        log("[gateway] 云网关探活 ok（GET /minimax/v1/models/config）")
    else:
        if not ensure_app(sess):
            log("[FATAL] 网关不可用（已尝试重启）→ 按方案§4 降级：API 侧记 N/A")
            return 2

    # 积分守卫：windev=钱包实测值；cloud=估算累计（无钱包端点，如实降级不伪造）
    est_mode = backend == "cloud"
    if est_mode:
        state.setdefault("cloud_est_credit_spent", 0)
        baseline = None
        spent = int(state["cloud_est_credit_spent"])
        log(f"[wallet] 云通道无钱包端点（手册§7 未探明）→ 守卫降级为估算累计: "
            f"已耗(估)={spent} 上限={args.credit_cap}（{EST_CREDITS_PER_SEC}积分/s 口径）")
        if spent > args.credit_cap:
            log("[STOP] 估算累计已超积分上限")
            return 3
    else:
        try:
            cur = wallet_credit(sess)
        except Exception as e:
            log(f"[FATAL] 钱包查询失败: {e}")
            return 2
        if state.get("baseline_credit") is None:
            state["baseline_credit"] = cur
        baseline = state["baseline_credit"]
        spent = baseline - cur
        log(f"[wallet] 当前={cur} baseline={baseline} 已耗={spent} 上限={args.credit_cap}")
        if spent > args.credit_cap:
            log("[STOP] 已超积分上限")
            return 3

    if est_mode:
        state["seed_send_enabled"] = False      # 云 DTO 白名单无 seed，一律不发送
        log("[seed] 云通道不发送 seed（DTO 无此字段）；probe_seed 为 windev 专属，跳过")
    elif not args.skip_seed_probe:
        probe_seed(sess, state)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    ws_dir = None if est_mode else get_workspace_dir(sess)
    done = load_done(results_file)
    processed = ok_cnt = fail_cnt = 0

    for shot in shots:
        sid = shot["shot_id"]
        rid = f"{sid}@{args.model}"
        prev = done.get(rid)
        if prev and (not args.retry_failed or prev.get("status") == "succeeded"):
            log(f"[skip] {rid} 已有终态 {prev['status']}")
            continue

        # 云通道参数预检（不发 HTTP，不耗额度）
        if est_mode:
            ok, reason = validate_cloud_params(shot, args.model)
            if not ok:
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "invalid_params", "error": reason, "at": now()})
                done[rid] = True
                fail_cnt += 1
                log(f"[FAIL] {rid} 参数预检拒绝: {reason}")
                continue

        # 参考图解析
        refs = []
        ref_fail = False
        for ch in shot.get("characters") or []:
            ref = ch.get("ref_image")
            if not ref:
                continue
            if est_mode:
                # 云通道：仅接受 URL（reference_images）；本地路径需 /api/v1/files/upload（手册：未实测）→ fail-closed
                if re.match(r"^https?://", str(ref)):
                    refs.append(ref)
                    continue
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "reference_unsupported_on_cloud",
                                            "error": f"参考图 {ref} 为本地路径；云通道需 URL 或 "
                                                     f"/minimax-cloud/api/v1/files/upload（手册标注未实测，不盲调）",
                                            "at": now()})
                done[rid] = True
                ref_fail = True
                break
            src = Path(ref)
            if not src.exists():
                src = Path(args.refs_dir) / Path(ref).name
            if not src.exists():
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "reference_unavailable",
                                            "error": f"定妆照 {ref} 不可得", "at": now()})
                done[rid] = True
                ref_fail = True
                break
            dst = ws_dir / src.name
            if not dst.exists():
                shutil.copyfile(src, dst)
            refs.append(src.name)
        if ref_fail:
            continue

        # 积分守卫（每条提交前）
        est_credit = est_credit_clip(shot["duration_s"]) if est_mode else None
        if est_mode:
            if spent + est_credit > args.credit_cap:
                log("[STOP] 预估下一条将越上限，保守停止")
                state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                return 3
        else:
            try:
                cb = wallet_credit(sess)
                if baseline - cb + EST_PER_CLIP > args.credit_cap:
                    log("[STOP] 预估下一条将越上限，保守停止")
                    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                    return 3
            except Exception as e:
                log(f"[wallet] 查询失败（继续，不阻塞）: {e}")
                cb = None

        t0 = time.time()
        if est_mode:
            payload = build_cloud_payload(shot, args.model, refs)
            log(f"[run] {rid} channel=cloud model={args.model} duration={payload['duration']} "
                f"resolution={payload['resolution']} ratio={payload['ratio']} "
                f"audio={payload['generate_audio']} refs={len(refs)}")
            try:
                task_id, err = cloud_submit(sess, payload)
            except Exception as e:
                task_id, err = None, f"{type(e).__name__}: {e}"
            if err:
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "submit_error", "error": err[:300], "at": now()})
                fail_cnt += 1
                continue
            state["cloud_est_credit_spent"] = int(state.get("cloud_est_credit_spent", 0)) + est_credit
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            payload, ignored = build_payload(shot, args.model, bool(state.get("seed_send_enabled")), refs)
            if ignored:
                log(f"[dto] {rid} 忽略字段: {ignored}")
            log(f"[run] {rid} seed={shot.get('seed', 42)} seed_sent={bool(state.get('seed_send_enabled'))} refs={refs}")
            try:
                r = sess.post(sess.base_url + "/api/generate/video/submit", json=payload, timeout=TIMEOUT)
            except Exception as e:
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "submit_error", "error": str(e)[:300], "at": now()})
                fail_cnt += 1
                continue
            if r.status_code not in (200, 201):
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "submit_error",
                                            "error": f"submit_http_{r.status_code}: {r.text[:300]}",
                                            "at": now()})
                fail_cnt += 1
                continue
            try:
                task_id = r.json().get("task_id")
            except Exception:
                task_id = None
            if not task_id:
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "submit_error", "error": "no task_id", "at": now()})
                fail_cnt += 1
                continue

        fin = poll_task(sess, task_id)
        elapsed = round(time.time() - t0, 1)
        # 终态词表归一化：云 success → 旧词表 succeeded（其余词表双通道一致）
        status = ("succeeded" if fin.get("status") == "success"
                  else fin.get("status"))
        if est_mode:
            cb = ca = None
            cost = None
        else:
            try:
                ca = wallet_credit(sess)
            except Exception:
                ca = None
            cost = (cb - ca) if (cb is not None and ca is not None) else None
        rec = {"terminal": True, "rid": rid, "shot_id": sid, "model": args.model,
               "backend": ("minimax_cloud_v3" if est_mode else BACKEND),
               "channel": ("cloud" if est_mode else "windev"),
               "seed": shot.get("seed", 42),
               "seed_sent": (False if est_mode else bool(state.get("seed_send_enabled"))),
               "task_id": task_id,
               "status": status, "elapsed_s": elapsed,
               "credit_before": cb, "credit_after": ca, "credit_cost": cost,
               "est_credit": est_credit, "ignored_fields": ignored if not est_mode else [], "at": now()}
        if status == "succeeded":
            if est_mode:
                url, err = cloud_fetch_file(sess, task_id)
                if err:
                    rec.update(status="file_fetch_error", error=err[:300])
                    fail_cnt += 1
                    log(f"[FAIL] {rid} 取文件失败: {err[:200]}")
                    append_jsonl(results_file, rec)
                    done[rid] = rec
                    processed += 1
                    continue
                rec["download_url"] = url
                dst = out_dir / f"{rid}.mp4"
                err = download_file(sess, url, dst)
                if err:
                    rec.update(status="download_error", error=err[:300])
                    fail_cnt += 1
                    log(f"[FAIL] {rid} 下载失败: {err[:200]}")
                    append_jsonl(results_file, rec)
                    done[rid] = rec
                    processed += 1
                    continue
                rec.update(clip_file=str(dst), sha256=sha256_file(dst),
                           size_bytes=dst.stat().st_size, probe=ffprobe_clip(dst))
            else:
                result = fin.get("result") or {}
                src = ws_dir / result.get("path", "")
                if src.exists():
                    dst = out_dir / f"{rid}.mp4"
                    shutil.copyfile(src, dst)
                    rec.update(clip_file=str(dst), sha256=sha256_file(dst),
                               size_bytes=dst.stat().st_size,
                               probe={k: result.get(k) for k in ("width", "height", "duration", "fps")})
                else:
                    rec.update(status="file_missing", error=f"工作区产物缺失: {src}")
                    fail_cnt += 1
                    append_jsonl(results_file, rec)
                    done[rid] = rec
                    processed += 1
                    continue
            ok_cnt += 1
            log(f"[ok ] {rid} -> {rec.get('clip_file')} ({elapsed}s, "
                f"{rec.get('size_bytes')}B, probe={rec.get('probe')})")
        else:
            rec["error"] = str(fin.get("error"))[:500]
            fail_cnt += 1
            log(f"[FAIL] {rid} {status}: {str(fin.get('error'))[:200]}")
        append_jsonl(results_file, rec)
        done[rid] = rec
        processed += 1

    log(f"[done] 本次处理 {processed}（成功 {ok_cnt}/失败 {fail_cnt}）；结果: {results_file}")
    return 0


def load_shots(spec):
    """--shots：目录(*.json) 或 .jsonl。逐条契约校验，坏条目拒绝并计数。"""
    p = Path(spec)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    shots, bad = [], []
    for f in files:
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            if f.suffix == ".jsonl":
                s_list = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            else:
                bad.append(f.name)
                continue
        else:
            s_list = [s]
        for s in s_list:
            ok, err = validate_shot(s)
            if ok:
                shots.append(s)
            else:
                bad.append(f"{f.name}: {err}")
    if bad:
        log(f"[WARN] {len(bad)} 条未过契约校验被拒: {bad[:5]}")
    return shots


# ---------------- 适配器：历史 prompts.json → Shot 契约 JSON ----------------
def cmd_make_shots(args):
    """一次性适配器（非契约组件）：把历史 9 轴矩阵 prompts.json 转成 Shot JSON 目录。
    字段映射：id→shot_id, axis→axis, prompt_zh→prompt, seed→seed, axis→G7 的
    reference_characters 映射 characters[].ref_image（references_api/ 本地归档）。"""
    data = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chars = {c.get("filename"): c for c in data.get("reference_characters", [])}
    n = 0
    for p in data.get("prompts", []):
        characters = []
        for ref in p.get("references") or []:
            fn = ref["filename"]
            local = Path(args.refs_dir) / fn
            characters.append({"char_id": chars.get(fn, {}).get("char_id", Path(fn).stem),
                               "desc": chars.get(fn, {}).get("desc", ""),
                               "ref_image": str(local) if local.exists() else None})
        shot = {"schema_version": "1.0", "shot_id": p["id"], "axis": p.get("axis", "OTHER"),
                "duration_s": 5, "aspect": "9:16", "resolution": "768P",
                "prompt": p["prompt_zh"], "seed": int(p.get("seed", 42)),
                "characters": characters,
                "audio": {"generate": True},
                "engine_hint": {"preferred": "api", "model": "MiniMax-H3"}}
        (out_dir / f"{p['id']}.json").write_text(
            json.dumps(shot, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
    log(f"[make-shots] {n} 条 Shot 契约 JSON → {out_dir}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "make-shots":
        ap = argparse.ArgumentParser(description="历史 prompts.json → Shot 契约适配器")
        ap.add_argument("--prompts", required=True)
        ap.add_argument("--out-dir", required=True)
        ap.add_argument("--refs-dir", default="../数据/references_api")
        return cmd_make_shots(ap.parse_args(sys.argv[2:]))
    ap = argparse.ArgumentParser(description="vpipe gen_api：MiniMax 视频生成（默认云通道，可选 windev）")
    ap.add_argument("--shots", required=True, help="Shot 契约目录(*.json)或 .jsonl")
    ap.add_argument("--out-dir", default="./out_api")
    ap.add_argument("--refs-dir", default="../数据/references_api", help="定妆照本地归档目录")
    ap.add_argument("--model", default="MiniMax-H3")
    ap.add_argument("--backend", default=DEFAULT_BACKEND, choices=("cloud", "windev"),
                    help=f"生成通道（默认 {DEFAULT_BACKEND}；windev 为本机客户端网关历史通道）")
    ap.add_argument("--credit-cap", type=int, default=40000, help="本次测试积分硬上限（云通道按估算累计执行）")
    ap.add_argument("--cloud-base-url", default=DEFAULT_CLOUD_BASE,
                    help=f"云网关基址（默认 {DEFAULT_CLOUD_BASE}；覆盖时强制 http/https 且拒内网/保留地址）")
    ap.add_argument("--base-url", default=DEFAULT_BASE,
                    help=f"windev 网关基址（默认 {DEFAULT_BASE}；覆盖时强制 http/https 且拒内网/保留地址）")
    ap.add_argument("--allow-private", action="store_true", help="允许私有网段基址（内网部署显式放行）")
    ap.add_argument("--allow-loopback", action="store_true", help="允许环回基址（默认网关外的本机端口）")
    ap.add_argument("--dry-run", action="store_true", help="只构建 payload 不发 HTTP（打印第一条）")
    ap.add_argument("--skip-seed-probe", action="store_true", help="跳过 seed DTO 探测（沿用 state 结论；windev 专属）")
    ap.add_argument("--only", default="", help="只跑指定 shot_id，逗号分隔")
    ap.add_argument("--retry-failed", action="store_true", help="失败条目重跑")
    args = ap.parse_args()
    if args.dry_run:
        shots = load_shots(args.shots)
        if not shots:
            return 1
        if args.backend == "cloud":
            ok, reason = validate_cloud_params(shots[0], args.model)
            payload = build_cloud_payload(shots[0], args.model, [])
            if not ok:
                payload["__precheck_rejected__"] = reason
            print(json.dumps({"note": "dry-run：未发任何 HTTP", "backend": "cloud",
                              "n_shots": len(shots), "sample_payload": payload},
                             ensure_ascii=False, indent=2))
        else:
            payload, ignored = build_payload(shots[0], args.model, False, [])
            print(json.dumps({"note": "dry-run：未发任何 HTTP", "backend": "windev",
                              "n_shots": len(shots), "sample_payload": payload, "ignored": ignored},
                             ensure_ascii=False, indent=2))
        return 0
    return run_generate(args)


if __name__ == "__main__":
    sys.exit(main())
