# -*- coding: utf-8 -*-
"""gen_api 云通道测试（pytest，mock 网关，零真实生成）。

覆盖（2026-10-06 windev→higress 云迁移回归）：
  1. 全链路成功：提交→轮询→取文件→下载→succeeded 记录（sha256/ffprobe 真值）
  2. fail-closed：submit 500 / base_resp.status_code≠0 / 轮询超时 / 下载 URL 指向内网
     —— 服务失败如实记 submit_error/poll_timeout/download_error，不伪造成功
  3. 客户端预检不耗额度：参数越界记 invalid_params、本地参考图记
     reference_unsupported_on_cloud，两情况下 mock 网关均零提交调用
  4. 接口面回归：windev build_payload 冻结契约不变；cloud payload 白名单
  5. 词表归一化：云 success → 旧词表 succeeded（api_results.jsonl 消费方无感）

运行（在 overnight/vpipe/ 下）：  python -m pytest tests/test_gen_api_cloud.py -v
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
VPIPE = HERE.parent
sys.path.insert(0, str(VPIPE / "src"))

import gen_api  # noqa: E402

PY = sys.executable
FFMPEG_OK = subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0


# ---------------------------------------------------------------- mock 网关
class MockMinimaxCloud:
    """higress 云网关三步流的最小 mock：generate/tasks/files + 媒体下载 + 探活。"""

    def __init__(self, mp4_bytes: bytes):
        self.mp4_bytes = mp4_bytes
        self.generate_calls = 0
        self.task_status = {"t_ok": "processing", "t_fail": "failed"}
        self.download_url = None            # None=正常回媒体 URL；str=回恶意内网 URL
        self.submit_status = 200
        self.submit_body = {"task_id": "t_ok", "base_resp": {"status_code": 0}}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def _make_handler(self):
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):     # 静默
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/minimax/v1/models/config":
                    self._json(200, {"videoModels": []})
                elif self.path.startswith("/minimax-cloud/api/v1/video/minimax-v3/tasks/"):
                    tid = self.path.rsplit("/", 1)[-1]
                    self._json(200, {"task_id": tid, "status": mock.task_status.get(tid, "processing"),
                                     "base_resp": {"status_code": 0}})
                elif self.path.startswith("/minimax-cloud/api/v1/video/minimax/files/"):
                    url = mock.download_url or f"{mock.base}/media/fake.mp4"
                    self._json(200, {"file": {"file_id": 1, "download_url": url}})
                elif self.path.startswith("/media/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(mock.mp4_bytes)))
                    self.end_headers()
                    self.wfile.write(mock.mp4_bytes)
                else:
                    self._json(404, {"error": "no route"})

            def do_POST(self):
                if self.path == "/minimax-cloud/api/v1/video/minimax-v3/generate":
                    mock.generate_calls += 1
                    self._json(mock.submit_status, mock.submit_body)
                else:
                    self._json(404, {"error": "no route"})
        return H


def make_mp4(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=0.5:size=128x72:rate=8", str(path)],
                   check=True, capture_output=True)
    return path.read_bytes()


@pytest.fixture(scope="module")
def mp4_bytes():
    if FFMPEG_OK:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = Path(f.name)
        try:
            return make_mp4(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    return b"not-a-real-mp4"            # 无 ffmpeg 环境：只验链路，不验 probe


@pytest.fixture()
def gw(mp4_bytes):
    m = MockMinimaxCloud(mp4_bytes)
    yield m
    m.stop()


def run_cli(shots: Path, out_dir: Path, gw_base: str, extra_env=None):
    env = dict(os.environ)
    env.update(extra_env or {})
    return subprocess.run(
        [PY, str(VPIPE / "src" / "gen_api.py"),
         "--shots", str(shots), "--out-dir", str(out_dir),
         "--backend", "cloud", "--cloud-base-url", gw_base, "--allow-loopback",
         "--skip-seed-probe"],
        capture_output=True, text=True, timeout=120, env=env)


def write_shot(d: Path, **over):
    shot = {"schema_version": "1.0", "shot_id": "s1", "axis": "OTHER",
            "duration_s": 4, "aspect": "16:9", "resolution": "768P",
            "prompt": "mock 测试镜头", "audio": {"generate": False}}
    shot.update(over)
    d.mkdir(parents=True, exist_ok=True)
    (d / "s1.json").write_text(json.dumps(shot, ensure_ascii=False), encoding="utf-8")
    return d


def records(out_dir: Path):
    return [json.loads(x) for x in
            (out_dir / "api_results.jsonl").read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- 1. 全链路成功
def test_full_pipeline_success(gw, tmp_path):
    gw.task_status["t_ok"] = "processing"
    threading.Timer(0.5, lambda: gw.task_status.update(t_ok="success")).start()
    shots = write_shot(tmp_path / "shots")
    out = tmp_path / "out"
    r = run_cli(shots, out, gw.base)
    assert r.returncode == 0, r.stderr[-500:]
    recs = records(out)
    assert len(recs) == 1 and recs[0]["status"] == "succeeded"        # 云 success → 旧词表
    assert recs[0]["channel"] == "cloud" and recs[0]["backend"] == "minimax_cloud_v3"
    assert recs[0]["task_id"] == "t_ok"
    clip = Path(recs[0]["clip_file"])
    assert clip.exists() and clip.stat().st_size == len(gw.mp4_bytes)
    assert recs[0]["sha256"] == hashlib.sha256(gw.mp4_bytes).hexdigest()
    assert recs[0]["credit_before"] is None and recs[0]["est_credit"] == 224   # 56/s × 4s，如实标 est
    state = json.loads((out / "api_state.json").read_text(encoding="utf-8"))
    assert state["cloud_est_credit_spent"] == 224
    if FFMPEG_OK:
        assert recs[0]["probe"]["width"] == 128 and recs[0]["probe"]["height"] == 72


def test_health_check_hits_gateway(gw, tmp_path):
    """云模式健康检查走零消耗 GET /minimax/v1/models/config；网关不可达 → exit 2，零提交。"""
    shots = write_shot(tmp_path / "shots")
    r = run_cli(shots, tmp_path / "out", "http://127.0.0.1:1")        # allow-loopback 已放行环回，但 1 端口无人监听 → 探活失败
    assert r.returncode == 2
    assert gw.generate_calls == 0


# ---------------------------------------------------------------- 2. fail-closed
def test_submit_500_fail_closed(gw, tmp_path):
    gw.submit_status = 500
    gw.submit_body = {"error": "boom"}
    out = tmp_path / "out"
    r = run_cli(write_shot(tmp_path / "shots"), out, gw.base)
    assert r.returncode == 0                                          # 单条失败不致命，与 windev 口径一致
    rec = records(out)[0]
    assert rec["status"] == "submit_error" and "submit_http_500" in rec["error"]
    assert not (out / "s1@MiniMax-H3.mp4").exists()
    assert gw.generate_calls == 1


def test_submit_base_resp_error_fail_closed(gw, tmp_path):
    gw.submit_body = {"base_resp": {"status_code": 1004, "status_msg": "invalid params"}}
    out = tmp_path / "out"
    run_cli(write_shot(tmp_path / "shots"), out, gw.base)
    rec = records(out)[0]
    assert rec["status"] == "submit_error" and "1004" in rec["error"]


def test_poll_timeout_fail_closed(gw, tmp_path):
    gw.task_status["t_ok"] = "processing"                             # 永不 success
    env = {"VPIPE_GENAPI_POLL_INTERVAL": "1", "VPIPE_GENAPI_POLL_TIMEOUT": "2"}
    out = tmp_path / "out"
    r = run_cli(write_shot(tmp_path / "shots"), out, gw.base, extra_env=env)
    assert r.returncode == 0
    rec = records(out)[0]
    assert rec["status"] == "poll_timeout"
    assert not (out / "s1@MiniMax-H3.mp4").exists()


def test_task_failed_normalized(gw, tmp_path):
    gw.task_status["t_ok"] = "failed"
    out = tmp_path / "out"
    run_cli(write_shot(tmp_path / "shots"), out, gw.base)
    rec = records(out)[0]
    assert rec["status"] == "failed" and "cloud task failed" in rec["error"]


def test_download_url_private_rejected(gw, tmp_path):
    """网关被攻破返回内网下载地址 → URL 安全校验拒收，记 download_error，不落盘。"""
    gw.task_status["t_ok"] = "success"
    gw.download_url = "http://10.0.0.1:9/steal.mp4"
    out = tmp_path / "out"
    run_cli(write_shot(tmp_path / "shots"), out, gw.base)
    rec = records(out)[0]
    assert rec["status"] == "download_error" and "private/reserved" in rec["error"]
    assert not (out / "s1@MiniMax-H3.mp4").exists()


# ---------------------------------------------------------------- 3. 预检不耗额度
def test_invalid_params_no_http(gw, tmp_path):
    out = tmp_path / "out"
    r = run_cli(write_shot(tmp_path / "shots", duration_s=2), out, gw.base)
    assert r.returncode == 0
    rec = records(out)[0]
    assert rec["status"] == "invalid_params" and "超出" in rec["error"]
    assert gw.generate_calls == 0                                     # 零提交，不耗额度


def test_local_reference_fail_closed_on_cloud(gw, tmp_path):
    shots = write_shot(tmp_path / "shots",
                       characters=[{"char_id": "a", "ref_image": "/data/refs/a.png"}])
    out = tmp_path / "out"
    run_cli(shots, out, gw.base)
    rec = records(out)[0]
    assert rec["status"] == "reference_unsupported_on_cloud"
    assert "files/upload" in rec["error"] and gw.generate_calls == 0


def test_url_reference_passes_through(gw, tmp_path):
    gw.task_status["t_ok"] = "success"
    shots = write_shot(tmp_path / "shots",
                       characters=[{"char_id": "a", "ref_image": "https://cdn.example.com/a.png"}])
    out = tmp_path / "out"
    r = run_cli(shots, out, gw.base)
    assert r.returncode == 0 and records(out)[0]["status"] == "succeeded"


# ---------------------------------------------------------------- 4. 接口面回归
def test_windev_payload_contract_unchanged():
    """冻结契约回归：windev build_payload 输出与迁移前逐键一致（SPEC §2.2）。"""
    shot = {"shot_id": "x1", "prompt": "p", "duration_s": 5, "aspect": "9:16",
            "resolution": "768P", "seed": 42, "audio": {"generate": True}}
    payload, ignored = gen_api.build_payload(shot, "MiniMax-H3", True, ["a.png"])
    assert list(payload) == ["backend", "model_id", "prompt", "filename",
                             "image_paths", "params", "source_tool"]
    assert payload["params"]["duration"] == "5" and payload["params"]["seed"] == "42"
    assert payload["params"]["aspect_ratio"] == "9:16" and payload["image_paths"] == ["a.png"]


def test_cloud_payload_whitelist():
    shot = {"shot_id": "x1", "prompt": "p" * 8000, "duration_s": 4.0, "aspect": "16:9",
            "resolution": "768P", "audio": {"generate": False}, "negative_prompt": "blur",
            "seed": 7}
    p = gen_api.build_cloud_payload(shot, "MiniMax-H3", ["https://e/1.png"])
    assert set(p) == {"model", "prompt", "duration", "resolution", "ratio",
                      "generate_audio", "reference_images"}
    assert len(p["prompt"]) == 7000 and p["duration"] == 4
    assert p["generate_audio"] is False and p["reference_images"] == ["https://e/1.png"]
