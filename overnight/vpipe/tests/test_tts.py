# -*- coding: utf-8 -*-
"""tts.py 单测（CP10 字幕音轨 StepFun TTS 客户端）——mock 本地网关，零真实 API 调用。

覆盖（TASK_v4 CP10 交付口径）：
  1. 请求构造：/audio/speech URL+DTO（model/input/voice/response_format/speed/
     instruction）、官方上限校验（input≤1000、speed 0.5~2、格式枚举）扣费前拦截
  2. 密钥掩码：前 6 字符+len；meta/日志/请求预览中完整 key 0 命中
  3. meta 结构：text_len / duration_s(ffprobe 实测，本地 mock 网关回真实 wav 字节) /
     credits_or_cost_estimate / request_id / latency_s / sha256 / errors
  4. dry-run：零 HTTP（mock 计数=0）、不落音频、meta 带 request_preview 且掩码
  5. fail-closed：HTTP 401 / 200+JSON 软错误 → status=failed、不伪造音频、退出码 1；
     凭据缺失退出码 2、零 HTTP
  6. 克隆闭环：/v1/files(multipart purpose=storage) → /audio/voices(file_id) →
     voice_id 参与本次合成；--voice-name 仅本地标签不入 API 体
  7. 成本红线：预估 >¥1 → exit 4、零 HTTP

运行（零第三方依赖，unittest 标准库；pytest 亦可收集）：
  cd overnight/vpipe && python3 tests/test_tts.py -v
  python -m pytest tests/test_tts.py -v        # 有 pytest 的环境
"""
import io
import json
import math
import contextlib
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
VPIPE = HERE.parent
sys.path.insert(0, str(VPIPE / "src"))

import tts  # noqa: E402

FFPROBE_OK = subprocess.run(["ffprobe", "-version"], capture_output=True).returncode == 0

FAKE_KEY = "sk-test-abc123def456"           # 假 key，仅测试域
FAKE_MASK = "sk-tes****(len=%d)" % len(FAKE_KEY)


def make_wav_bytes(seconds=1.0, rate=8000):
    """stdlib wave 生成真 wav 字节 → mock 网关回它 → ffprobe 可实测时长。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))))
    return buf.getvalue()


class MockStepFun:
    """本机 mock 网关：/v1/files、/audio/voices、/audio/speech 三端点，请求全记录。"""

    def __init__(self, wav_bytes: bytes):
        self.wav_bytes = wav_bytes
        self.calls = []                      # [(path, headers dict, body bytes)]
        self.speech_status = 200
        self.speech_soft_json = False        # True: 200 但回 JSON（软错误）
        self.files_status = 200
        self.voices_status = 200
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def calls_to(self, path):
        return [c for c in self.calls if c[0] == path]

    def _handler(self):
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):     # 静默访问日志
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                mock.calls.append((self.path, dict(self.headers.items()), body))
                if self.path == "/v1/files":
                    if mock.files_status != 200:
                        return self._json(mock.files_status, {"error": {"message": "upload denied"}})
                    return self._json(200, {"id": "file-mock1", "object": "file",
                                            "purpose": "storage", "status": "processed"})
                if self.path == "/audio/voices":
                    if mock.voices_status != 200:
                        return self._json(mock.voices_status, {"error": {"message": "voices denied"}})
                    return self._json(200, {"id": "voice-mock1", "object": "audio.voice",
                                            "duplicated": False})
                if self.path == "/audio/speech":
                    if mock.speech_status != 200:
                        return self._json(mock.speech_status,
                                          {"error": {"message": "invalid api key",
                                                     "request_id": "req-err-1"}})
                    if mock.speech_soft_json:
                        return self._json(200, {"error": {"message": "soft failure"}})
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("X-Api-Request-Id", "req-mock-123")
                    self.send_header("Content-Length", str(len(mock.wav_bytes)))
                    self.end_headers()
                    self.wfile.write(mock.wav_bytes)
                    return
                self._json(404, {"error": {"message": "no such path"}})

            def _json(self, code, doc):
                payload = json.dumps(doc).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Api-Request-Id", "req-mock-123")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return H


class TTSBase(unittest.TestCase):
    def setUp(self):
        self.mock = MockStepFun(make_wav_bytes(1.0))
        self.tmp = Path(tempfile.mkdtemp(prefix="tts_test_"))
        self.env_file = self.tmp / "api_keys.env"
        self.env_file.write_text(f"# mock env\n{tts.KEY_ENV}={FAKE_KEY}\n", encoding="utf-8")
        self.out = self.tmp / "test.wav"

    def tearDown(self):
        self.mock.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tts(self, extra_args, env_key_absent=True):
        """进程内跑 main()；清掉进程环境里的 key（只走 --env-file），捕获 stdout。
        安全网：包裹 tts.http_post*，任何非 127.0.0.1 的请求直接炸——测试永不外呼。"""
        old = __import__("os").environ.pop(tts.KEY_ENV, None)
        real_post, real_multipart = tts.http_post, tts.http_post_multipart

        def guard(url):
            host = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).hostname
            assert host in ("127.0.0.1", "localhost"), f"测试请求越出本机 mock: {url}"

        def guarded_post(url, key, **kw):
            guard(url)
            return real_post(url, key, **kw)

        def guarded_multipart(url, key, *a, **kw):
            guard(url)
            return real_multipart(url, key, *a, **kw)

        tts.http_post, tts.http_post_multipart = guarded_post, guarded_multipart
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = tts.main(["--text", "你好世界，这是测试台词。",
                                 "--out", str(self.out),
                                 "--base-url", self.mock.base,
                                 "--env-file", str(self.env_file)] + extra_args)
        finally:
            tts.http_post, tts.http_post_multipart = real_post, real_multipart
            if old is not None:
                __import__("os").environ[tts.KEY_ENV] = old
        return code, buf.getvalue()

    def read_meta(self):
        return json.loads(tts.meta_path_for(self.out).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 掩码 / env
class TestMaskAndEnv(TTSBase):
    def test_mask_key(self):
        self.assertEqual(tts.mask_key(FAKE_KEY), FAKE_MASK)
        self.assertNotIn(FAKE_KEY, tts.mask_key(FAKE_KEY))
        self.assertEqual(tts.mask_key(""), "(empty)")

    def test_parse_env_file(self):
        p = self.tmp / "e.env"
        p.write_text("# 注释\nexport A=1\nB = 'two words'\nC=\"d\"\n\nBAD LINE\n", encoding="utf-8")
        d = tts.parse_env_file(p)
        self.assertEqual(d, {"A": "1", "B": "two words", "C": "d"})

    def test_missing_credentials_exit2_no_http(self):
        empty_env = self.tmp / "empty.env"
        empty_env.write_text("# 无 key 的 env 文件\nOTHER=x\n", encoding="utf-8")
        n0 = len(self.mock.calls)
        code, out = self.run_tts(["--env-file", str(empty_env)])
        self.assertEqual(code, 2)
        self.assertEqual(len(self.mock.calls), n0)          # 零 HTTP
        m = self.read_meta()
        self.assertEqual(m["status"], "failed")
        self.assertTrue(any("STEPFUN_API_KEY" in e for e in m["errors"]))


# ---------------------------------------------------------------- 请求构造
class TestRequestBuild(unittest.TestCase):
    def test_build_ok(self):
        url, body = tts.build_speech_request("你好", "stepaudio-2.5-tts", "cixingnansheng",
                                             "wav", 1.0, "口播风格",
                                             "https://api.stepfun.com/step_plan/v1")
        self.assertEqual(url, "https://api.stepfun.com/step_plan/v1/audio/speech")
        self.assertEqual(body, {"model": "stepaudio-2.5-tts", "input": "你好",
                                "voice": "cixingnansheng", "response_format": "wav",
                                "speed": 1.0, "instruction": "口播风格"})

    def test_no_instruction_field_when_absent(self):
        _, body = tts.build_speech_request("你好", "stepaudio-2.5-tts", "v", "mp3",
                                           1.0, None, "http://x")
        self.assertNotIn("instruction", body)

    def test_validations_fail_before_http(self):
        cases = [
            ("", dict(response_format="mp3")),                       # 空 text
            ("x" * 1001, dict(response_format="mp3")),               # 超 1000
            ("你好", dict(response_format="aac")),                   # 非法格式
            ("你好", dict(response_format="mp3", speed=2.5)),        # speed 越界
            ("你好", dict(response_format="mp3", voice="")),         # 空 voice
        ]
        for text, kw in cases:
            with self.assertRaises(tts.InputError):
                base = kw.pop("base_url", "http://x")
                tts.build_speech_request(text, "m", kw.pop("voice", "v"),
                                         kw.get("response_format", "mp3"),
                                         kw.get("speed", 1.0), kw.get("instruction"),
                                         base)

    def test_cost_redline(self):
        with self.assertRaises(tts.CostRedlineError):
            tts.speech_cost_redline("字" * 2000)      # 2000 单元 ≈ ¥1.16 > ¥1
        tts.speech_cost_redline("你好世界。")          # 正常量级不拦


# ---------------------------------------------------------------- dry-run
class TestDryRun(TTSBase):
    def test_dry_run_zero_http_no_audio(self):
        code, out = self.run_tts(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.mock.calls), 0)           # 零 HTTP
        self.assertFalse(self.out.exists())                 # 不落音频
        m = self.read_meta()
        self.assertEqual(m["status"], "dry_run")
        self.assertTrue(m["dry_run"])
        self.assertIsNone(m["sha256"])
        self.assertIsNone(m["duration_s"])
        self.assertIn("request_preview", m)
        self.assertEqual(m["request_preview"]["url"], f"{self.mock.base}/audio/speech")
        self.assertEqual(m["request_preview"]["body"]["input"], "你好世界，这是测试台词。")
        self.assertIn("credits_or_cost_estimate", m)
        self.assertIn("text_len", m)
        # 掩码：预览与 meta 不出现完整 key
        self.assertNotIn(FAKE_KEY, json.dumps(m, ensure_ascii=False))
        self.assertIn("****", m["request_preview"]["headers"]["Authorization"])


# ---------------------------------------------------------------- 正常合成
class TestSpeechOk(TTSBase):
    @unittest.skipUnless(FFPROBE_OK, "ffprobe 不可用")
    def test_speech_ok_meta_contract(self):
        code, out = self.run_tts(["--voice-id", "cixingnansheng", "--speed", "1.0"])
        self.assertEqual(code, 0)
        self.assertTrue(self.out.exists())
        self.assertEqual(self.out.read_bytes(), self.mock.wav_bytes)  # 字节原样落盘
        m = self.read_meta()
        # meta 契约六字段（TASK 口径）
        for k in ("text_len", "duration_s", "credits_or_cost_estimate",
                  "request_id", "latency_s", "sha256"):
            self.assertIn(k, m)
        self.assertEqual(m["status"], "ok")
        self.assertEqual(m["errors"], [])
        self.assertEqual(m["text_len"], len("你好世界，这是测试台词。"))
        self.assertEqual(m["request_id"], "req-mock-123")
        self.assertIsInstance(m["latency_s"], float)
        import hashlib
        self.assertEqual(m["sha256"],
                         hashlib.sha256(self.mock.wav_bytes).hexdigest())
        self.assertAlmostEqual(m["duration_s"], 1.0, delta=0.1)       # ffprobe 实测
        self.assertEqual(m["ffprobe"]["acodec"], "pcm_s16le")
        est = m["credits_or_cost_estimate"]
        self.assertGreater(est["cny_doc_rate_est"], 0)
        self.assertIn("估算", est["basis"])
        self.assertNotIn(FAKE_KEY, json.dumps(m, ensure_ascii=False)) # key 0 命中
        self.assertNotIn(FAKE_KEY, out)                               # 日志 0 命中
        self.assertIn(FAKE_MASK, out)                                 # 日志有掩码
        # 请求体 DTO 核对
        path, headers, body = self.mock.calls_to("/audio/speech")[0]
        self.assertEqual(headers.get("Authorization"), f"Bearer {FAKE_KEY}")
        self.assertEqual(json.loads(body)["voice"], "cixingnansheng")
        self.assertEqual(json.loads(body)["response_format"], "wav")

    def test_http_401_fail_closed(self):
        self.mock.speech_status = 401
        code, out = self.run_tts([])
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())                 # 不伪造成功
        m = self.read_meta()
        self.assertEqual(m["status"], "failed")
        self.assertTrue(m["errors"])
        self.assertIn("speech_http_401", m["errors"][0])
        self.assertEqual(m["http_status"], 401)
        self.assertNotIn(FAKE_KEY, json.dumps(m, ensure_ascii=False))
        self.assertNotIn(FAKE_KEY, out)

    def test_soft_json_200_fail_closed(self):
        self.mock.speech_soft_json = True
        code, out = self.run_tts([])
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())
        m = self.read_meta()
        self.assertEqual(m["status"], "failed")
        self.assertTrue(any("soft_error" in e for e in m["errors"]))


# ---------------------------------------------------------------- 克隆闭环
class TestCloneFlow(TTSBase):
    @unittest.skipUnless(FFPROBE_OK, "ffprobe 不可用")
    def test_clone_full_loop(self):
        ref = self.tmp / "ref.wav"
        ref.write_bytes(make_wav_bytes(6.0))                # 官方口径 5-10s
        code, out = self.run_tts(["--clone", "--ref-audio", str(ref),
                                  "--voice-name", "磁性男声v1", "--clone-text", "转写文本"])
        self.assertEqual(code, 0)
        # ① 上传：multipart purpose=storage
        f_calls = self.mock.calls_to("/v1/files")
        self.assertEqual(len(f_calls), 1)
        self.assertIn(b'name="purpose"', f_calls[0][2])
        self.assertIn(b"storage", f_calls[0][2])
        self.assertIn(b"ref.wav", f_calls[0][2])
        # ② 注册：file_id 关联
        v_calls = self.mock.calls_to("/audio/voices")
        self.assertEqual(len(v_calls), 1)
        vbody = json.loads(v_calls[0][2])
        self.assertEqual(vbody["file_id"], "file-mock1")
        self.assertEqual(vbody["model"], "stepaudio-2.5-tts")
        self.assertEqual(vbody["text"], "转写文本")
        self.assertNotIn("voice_name", vbody)               # --voice-name 不入 API 体
        # ③ 合成用克隆 voice_id
        s_calls = self.mock.calls_to("/audio/speech")
        self.assertEqual(len(s_calls), 1)
        self.assertEqual(json.loads(s_calls[0][2])["voice"], "voice-mock1")
        # meta 记录
        m = self.read_meta()
        self.assertEqual(m["clone"]["voice_id"], "voice-mock1")
        self.assertEqual(m["clone"]["file_id"], "file-mock1")
        self.assertEqual(m["clone"]["duplicated"], False)
        self.assertEqual(m["voice_name"], "磁性男声v1")
        self.assertEqual(m["voice_id"], "voice-mock1")
        self.assertNotIn(FAKE_KEY, json.dumps(m, ensure_ascii=False))

    def test_clone_missing_ref_exit2(self):
        code, out = self.run_tts(["--clone", "--voice-name", "x"])
        self.assertEqual(code, 2)
        m = self.read_meta()
        self.assertEqual(m["status"], "failed")
        self.assertFalse(self.out.exists())


# ---------------------------------------------------------------- 成本红线
class TestCostRedline(TTSBase):
    def test_redline_exit4_zero_http(self):
        """把红线阈值临时调到极小 → 正常文本也必须被红线拦（exit 4、零 HTTP）。
        官方 input≤1000 上限下牌价最多 ¥0.58，红线本身是纵深防御（价格/上限变化时兜底）。"""
        old = tts.COST_REDLINE_CNY
        tts.COST_REDLINE_CNY = 0.000001
        try:
            code, out = self.run_tts([])
        finally:
            tts.COST_REDLINE_CNY = old
        self.assertEqual(code, 4)
        self.assertEqual(len(self.mock.calls), 0)
        m = self.read_meta()
        self.assertEqual(m["status"], "failed")
        self.assertTrue(any("红线" in e for e in m["errors"]))

    def test_oversize_text_exit2_zero_http(self):
        """官方 input≤1000 上限在扣费前拦截（exit 2）——优先于成本红线。"""
        code, out = self.run_tts(["--text", "字" * 1001])
        self.assertEqual(code, 2)
        self.assertEqual(len(self.mock.calls), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
