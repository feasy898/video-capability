#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_gen_wan22.py — gen_wan22 Wan2.2 适配层自测（mock 级，零 GPU，零模型加载）。

运行：
    cd overnight/vpipe && python3 tests/test_gen_wan22.py     # 独立运行（本机无 pytest 依赖）
    python3 -m pytest tests/test_gen_wan22.py -q              # pytest 亦可

覆盖：
  A. 补丁幂等性：apply_compat_patches 双调无副作用——boundary 恒 0.0、VideoProcessor
     config 恒 16、#3 类属性双调后行为不变（property 恒活读 config，无包裹叠加/无缓存）
  B. 补丁 #3 property 两分支：vae.config.scale_factor_spatial 优先；缺失/None config
     回退 Wan2.1 启发式 2**len(temperal_downsample)（真值 16 ≠ 启发式 8 的缺陷前提）
  C. 补丁 #1：validate_model_dir fail-closed（目录缺失/缺 model_index.json/缺子目录）；
     fake diffusers/transformers 注入下手动加载 5 组件，from_pretrained 的
     subfolder/torch_dtype 逐项与 spike 一致（tokenizer/scheduler 不带 torch_dtype）
  D. 补丁失败路由：update_components 抛错 → CompatPatchError 且带补丁号；逐项核验
     verify_pipeline_state 对「补丁未生效」判 fail
  E. CLI 参数构造：默认 42/33/50、(F-1)%4==0 帧约束、--prompt-file 读取、--zh、
     --determinism-runs、guidance 缺省 None（不显式下发=spike 语义）
  F. --dry-run 零加载（子进程）：预检通过 meta 结构；权重目录缺失 → exit 1 + errors
     落 meta 不静默；坏帧数 → exit 2；dry-run 进程不 import torch/diffusers（结构保证：
     零加载分支只走 stdlib，meta 记 dry_run=true）
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent            # overnight/vpipe/tests
VPIPE = HERE.parent                               # overnight/vpipe
TOOL = VPIPE / "src" / "gen_wan22.py"

_spec = importlib.util.spec_from_file_location("gen_wan22", TOOL)
gen_wan22 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_wan22)


class T:
    def __init__(self):
        self.fails = []

    def check(self, name, ok, detail=""):
        detail = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               (" :: " + detail) if detail else ""))
        if not ok:
            self.fails.append((name, detail))


# ---------------------------------------------------------------- mock 设施

def install_fake_diffusers():
    """向 sys.modules 注入 fake diffusers（video_processor.VideoProcessor），隔离真实库。"""
    diff = types.ModuleType("diffusers")
    vp_mod = types.ModuleType("diffusers.video_processor")

    class FakeVideoProcessor:
        def __init__(self, vae_scale_factor=8, **kw):
            self.config = {"vae_scale_factor": vae_scale_factor}

    vp_mod.VideoProcessor = FakeVideoProcessor
    diff.video_processor = vp_mod
    sys.modules["diffusers"] = diff
    sys.modules["diffusers.video_processor"] = vp_mod
    return FakeVideoProcessor


def make_pipe_cls():
    """模拟 ModularPipeline：update_components 覆盖组件（setattr），boundary 默认 0.875
    （diffusers 0.39.0 对 A14B 的默认值，即 spike 首崩点）。"""
    class FakeWanModularPipeline:
        boundary_default = 0.875

        def __init__(self):
            self.vae = FakeVAE()
            self.update_calls = []
            self.boundary_ratio = 0.875
            self.video_processor = None

        def update_components(self, **kw):
            self.update_calls.append(dict(kw))
            for k, v in kw.items():
                setattr(self, k, v)

    return FakeWanModularPipeline


class FakeVAE:
    """模拟 AutoencoderKLWan：config 带 scale_factor_spatial=16（Wan2.2 真值）+
    temperal_downsample 长度 3（Wan2.1 启发式 2**3=8 的缺陷来源）。"""

    def __init__(self):
        self.config = {"scale_factor_spatial": 16}
        self.temperal_downsample = [1, 2, 2]
        self.tiling_calls = 0
        self.use_tiling = False

    def enable_tiling(self):
        self.tiling_calls += 1
        self.use_tiling = True


def make_fake_model_cls(name, calls):
    class FakeFromPretrained:
        @classmethod
        def from_pretrained(cls, path, subfolder=None, torch_dtype=None):
            calls.append((name, str(path), subfolder, torch_dtype))
            return f"<{name} instance>"

    FakeFromPretrained.__name__ = name
    return FakeFromPretrained


def install_fake_loaders(model_dir):
    """注入 fake torch/diffusers 模型类/transformers，捕获 load_components_manual 的加载参数。"""
    calls = []
    torch_mod = types.ModuleType("torch")
    torch_mod.float16 = "float16-SENTINEL"
    diff = sys.modules.get("diffusers") or types.ModuleType("diffusers")
    diff.WanTransformer3DModel = make_fake_model_cls("WanTransformer3DModel", calls)
    diff.AutoencoderKLWan = make_fake_model_cls("AutoencoderKLWan", calls)
    diff.UniPCMultistepScheduler = make_fake_model_cls("UniPCMultistepScheduler", calls)
    tf_mod = types.ModuleType("transformers")
    tf_mod.UMT5EncoderModel = make_fake_model_cls("UMT5EncoderModel", calls)
    tf_mod.AutoTokenizer = make_fake_model_cls("AutoTokenizer", calls)
    sys.modules["torch"] = torch_mod
    sys.modules["diffusers"] = diff
    sys.modules["transformers"] = tf_mod
    return calls, torch_mod


# ---------------------------------------------------------------- A 幂等性

def _case_idempotent(t: T):
    FakeVideoProcessor = install_fake_diffusers()
    cls = make_pipe_cls()
    pipe = cls()
    ev1 = gen_wan22.apply_compat_patches(pipe, wan_modular_cls=cls)
    t.check("A 首调返回 3 份补丁证据", sorted(ev1) == ["2", "3", "4"], sorted(ev1))

    def snapshot(p):
        return (p.boundary_ratio,
                p.video_processor.config["vae_scale_factor"],
                p.vae_scale_factor_spatial)

    def normalize(calls):
        """VP 实例按身份不同（每次新建），归一为其 config 再比较。"""
        return [{k: (dict(v.config) if hasattr(v, "config") else v) for k, v in c.items()}
                for c in calls]

    s1 = snapshot(pipe)
    t.check("A 单调后 boundary=0.0", pipe.boundary_ratio == 0.0, str(pipe.boundary_ratio))
    t.check("A 单调后 VP scale=16", pipe.video_processor.config["vae_scale_factor"] == 16)
    t.check("A 单调后 property=16", pipe.vae_scale_factor_spatial == 16)

    ev2 = gen_wan22.apply_compat_patches(pipe, wan_modular_cls=cls)
    s2 = snapshot(pipe)
    t.check("A 双调幂等：状态快照一致", s1 == s2, f"{s1} != {s2}")
    t.check("A 双调幂等：update_components 调用序列逐字重放（VP 归一为 config）",
            normalize(pipe.update_calls)[2:] == normalize(pipe.update_calls)[:2],
            json.dumps(normalize(pipe.update_calls), ensure_ascii=False, default=str))
    t.check("A 双调证据一致", ev1["2"]["boundary_ratio"] == ev2["2"]["boundary_ratio"]
            and ev1["4"]["vae_scale_factor"] == ev2["4"]["vae_scale_factor"])
    # 无包裹叠加：property 恒活读 config（改 config 值立即反映），非首次求值的缓存
    pipe.vae.config["scale_factor_spatial"] = 8
    t.check("A property 恒活读（无缓存叠加）", pipe.vae_scale_factor_spatial == 8)
    pipe.vae.config["scale_factor_spatial"] = 16
    # update_components 恰好每次 2 个键（boundary_ratio / video_processor），双调共 4 次
    t.check("A 双调共 4 次 update_components", len(pipe.update_calls) == 4,
            str(len(pipe.update_calls)))
    t.check("A 类型仍为 property", type(cls.__dict__["vae_scale_factor_spatial"]) is property)
    t.check("A VP config 恰为显式构造值", pipe.video_processor.config == {"vae_scale_factor": 16},
            str(pipe.video_processor.config))


# ---------------------------------------------------------------- B property 两分支

def _case_property_branches(t: T):
    cls = make_pipe_cls()
    gen_wan22.patch_vae_scale_factor_spatial(cls)          # 显式传 cls，不触真实 diffusers
    pipe = cls()
    t.check("B config 真值 16 优先", pipe.vae_scale_factor_spatial == 16)
    pipe.vae.config = {}                                   # 无该键 → 回退启发式
    t.check("B 缺键回退 2**len(temp)=8", pipe.vae_scale_factor_spatial == 8,
            str(pipe.vae_scale_factor_spatial))
    pipe.vae.config = {"scale_factor_spatial": 0}          # 假值按缺失处理（if v: 语义，与 spike 一致）
    t.check("B 假值 0 回退启发式", pipe.vae_scale_factor_spatial == 8)
    pipe.vae.config = None                                 # 无 config → 回退启发式
    t.check("B None config 回退启发式", pipe.vae_scale_factor_spatial == 8)
    pipe.vae.config = {"scale_factor_spatial": 16}
    t.check("B 恢复 config 后读回 16", pipe.vae_scale_factor_spatial == 16)


# ---------------------------------------------------------------- C 补丁 #1 手动加载

def _case_manual_load(t: T):
    with tempfile.TemporaryDirectory() as td:
        # 缺目录
        ok, missing = gen_wan22.validate_model_dir(Path(td) / "nope")
        t.check("C 目录缺失 → present=False", ok is False and missing == ["<model_dir>"], str(missing))
        # 缺 model_index.json
        d = Path(td) / "m1"
        (d / "transformer").mkdir(parents=True)
        ok, missing = gen_wan22.validate_model_dir(d)
        t.check("C 缺 model_index.json 被点名的 fail-closed", ok is False and "model_index.json" in missing,
                str(missing))
        # 完整目录
        d = Path(td) / "m2"
        d.mkdir()
        (d / "model_index.json").write_text("{}", encoding="utf-8")
        for n in gen_wan22.REQUIRED_SUBDIRS:
            (d / n).mkdir()
        ok, missing = gen_wan22.validate_model_dir(d)
        t.check("C 完整目录通过", ok is True and missing == [], str(missing))

        # fake 库注入：加载参数逐项断言
        calls, torch_mod = install_fake_loaders(d)
        comps = gen_wan22.load_components_manual(str(d))   # dtype=None → fake torch.float16
        want = [("WanTransformer3DModel", str(d), "transformer", "float16-SENTINEL"),
                ("UMT5EncoderModel", str(d), "text_encoder", "float16-SENTINEL"),
                ("AutoTokenizer", str(d), "tokenizer", None),
                ("AutoencoderKLWan", str(d), "vae", "float16-SENTINEL"),
                ("UniPCMultistepScheduler", str(d), "scheduler", None)]
        t.check("C from_pretrained 5 次调用与 spike 逐项一致", calls == want,
                json.dumps(calls, ensure_ascii=False))
        t.check("C 返回 5 组件键序正确",
                list(comps) == ["transformer", "text_encoder", "tokenizer", "vae", "scheduler"],
                str(list(comps)))
        t.check("C tokenizer/scheduler 不带 torch_dtype",
                all(c[3] is None for c in calls if c[0] in ("AutoTokenizer", "UniPCMultistepScheduler")))
        # 缺子目录时 fail-closed（fake 库已就位，验证异常类型）
        bad = Path(td) / "m3"
        bad.mkdir()
        (bad / "model_index.json").write_text("{}", encoding="utf-8")
        try:
            gen_wan22.load_components_manual(str(bad))
            t.check("C 缺子目录抛 FileNotFoundError", False, "未抛异常")
        except FileNotFoundError as e:
            t.check("C 缺子目录抛 FileNotFoundError", "vae" in str(e) or "缺" in str(e), str(e))


# ---------------------------------------------------------------- D 失败路由

def _case_failure_routing(t: T):
    install_fake_diffusers()

    class BoomPipe(make_pipe_cls()):
        def update_components(self, **kw):
            raise RuntimeError("boom")

    boom = BoomPipe()
    try:
        gen_wan22.apply_compat_patches(boom, wan_modular_cls=BoomPipe)
        t.check("D update_components 抛错 → CompatPatchError", False, "未抛异常")
    except gen_wan22.CompatPatchError as e:
        t.check("D update_components 抛错 → CompatPatchError", True)
        t.check("D 补丁号可定位（首个失败=#2）", e.patch_id == "2", e.patch_id)

    # verify_pipeline_state：补丁未生效的 pipe 判 fail
    cls = make_pipe_cls()
    raw = cls()   # 不打补丁：boundary 0.875 / 无 VP / 无 property / 未 tiling
    try:
        gen_wan22.verify_pipeline_state(raw)
        t.check("D 未打补丁 → verify 拒绝", False, "未抛异常")
    except gen_wan22.CompatPatchError as e:
        t.check("D 未打补丁 → verify 拒绝", "boundary_ratio" in str(e), str(e)[:120])
    # 打全补丁 + tiling → verify 通过
    good = cls()
    gen_wan22.apply_compat_patches(good, wan_modular_cls=cls)
    gen_wan22.enable_vae_tiling(good.vae)
    rec = gen_wan22.verify_pipeline_state(good)
    t.check("D 打全补丁 → verify 全过", all(c["ok"] for c in rec) and len(rec) == 4,
            json.dumps(rec, ensure_ascii=False)[:200])


# ---------------------------------------------------------------- E CLI 参数构造

def _case_cli(t: T):
    ap = gen_wan22.build_parser()
    a = ap.parse_args([])
    t.check("E 默认 seed=42", a.seed == 42, str(a.seed))
    t.check("E 默认 frames=33", a.frames == 33, str(a.frames))
    t.check("E 默认 steps=50", a.steps == 50, str(a.steps))
    t.check("E 默认 guidance=None（不下发=spike 语义）", a.guidance is None)
    t.check("E 默认 determinism_runs=1", a.determinism_runs == 1)
    t.check("E 默认非 dry-run", a.dry_run is False)
    t.check("E 默认 --zh 未开", a.zh is False)

    with tempfile.TemporaryDirectory() as td:
        pf = Path(td) / "p.txt"
        pf.write_text("一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云\n", encoding="utf-8")
        a = ap.parse_args(["--prompt-file", str(pf), "--zh", "--seed", "7",
                           "--frames", "41", "--steps", "30", "--determinism-runs", "2",
                           "--dry-run"])
        prompt, source, err = gen_wan22.read_prompt(a)
        t.check("E --prompt-file 读取（strip 尾换行）",
                prompt == "一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云" and source == "file", repr(prompt))
        t.check("E --zh 标记", a.zh is True)
        t.check("E 覆盖 seed/frames/steps", (a.seed, a.frames, a.steps) == (7, 41, 30))
        t.check("E --determinism-runs 2", a.determinism_runs == 2)
        t.check("E --dry-run 标记", a.dry_run is True)

        # prompt-file > prompt 优先级
        a2 = ap.parse_args(["--prompt", "EN text", "--prompt-file", str(pf)])
        p2, s2, _ = gen_wan22.read_prompt(a2)
        t.check("E prompt-file 优先于 prompt", p2.startswith("一只橘猫") and s2 == "file")

        # 缺省 prompt → spike 中文金标准
        a3 = ap.parse_args([])
        p3, s3, e3 = gen_wan22.read_prompt(a3)
        t.check("E 缺省 prompt=spike 中文金标准",
                p3 == gen_wan22.PROMPT_ZH_CANONICAL and s3 == "default_canonical_zh" and e3 is None)

        # 坏文件
        a4 = ap.parse_args(["--prompt-file", str(Path(td) / "nope.txt")])
        _, _, e4 = gen_wan22.read_prompt(a4)
        t.check("E 坏 prompt-file 报错", bool(e4) and "prompt_file_unreadable" in e4, str(e4))

    # 校验器：帧约束 / steps / determinism-runs / guidance
    def ns(**kw):
        base = dict(frames=33, steps=50, determinism_runs=1, guidance=None)
        base.update(kw)
        return types.SimpleNamespace(**base)

    t.check("E 合参零错误", gen_wan22.validate_params(ns()) == [])
    t.check("E frames=32 违反 (F-1)%4==0", any("frames=32" in e for e in gen_wan22.validate_params(ns(frames=32))))
    t.check("E frames=33 通过", gen_wan22.validate_params(ns(frames=33)) == [])
    t.check("E frames=41 通过（41=8*5+1）", gen_wan22.validate_params(ns(frames=41)) == [])
    t.check("E steps=0 拒绝", any("steps=0" in e for e in gen_wan22.validate_params(ns(steps=0))))
    t.check("E determinism_runs=0 拒绝",
            any("determinism_runs=0" in e for e in gen_wan22.validate_params(ns(determinism_runs=0))))
    t.check("E guidance<=0 拒绝", any("guidance" in e for e in gen_wan22.validate_params(ns(guidance=0.0))))
    # 常量与 spike 对齐
    t.check("E 720P 档 704x1280", (gen_wan22.HEIGHT, gen_wan22.WIDTH) == (704, 1280))
    t.check("E BOUNDARY_RATIO=0.0", gen_wan22.BOUNDARY_RATIO == 0.0)
    t.check("E VAE_SCALE_SPATIAL=16", gen_wan22.VAE_SCALE_SPATIAL == 16)
    t.check("E 帧抽样位 33→[0,8,16,24,32]",
            gen_wan22.sample_indices(33) == [0, 8, 16, 24, 32],
            str(gen_wan22.sample_indices(33)))
    t.check("E 负向词与 spike 一致（非空且中文）",
            len(gen_wan22.NEGATIVE) > 100 and not gen_wan22.NEGATIVE.isascii())


# ---------------------------------------------------------------- F dry-run 子进程

def _run_cli(*argv):
    return subprocess.run([sys.executable, str(TOOL), *[str(a) for a in argv]],
                          capture_output=True, text=True, timeout=180)


def _case_dry_run(t: T):
    with tempfile.TemporaryDirectory() as td:
        # 完整假权重目录
        model = Path(td) / "Wan2.2-TI2V-5B"
        model.mkdir(parents=True)
        (model / "model_index.json").write_text("{}", encoding="utf-8")
        for n in gen_wan22.REQUIRED_SUBDIRS:
            (model / n).mkdir(parents=True)
        out = Path(td) / "out_ok"
        p = _run_cli("--dry-run", "--model", model, "--out", out,
                     "--prompt", "一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云", "--zh")
        t.check("F dry-run exit 0", p.returncode == 0, f"rc={p.returncode} {p.stderr[:300]}")
        mp = out / "wan22_meta.json"
        t.check("F meta 落盘", mp.exists())
        meta = json.loads(mp.read_text(encoding="utf-8"))
        t.check("F meta.dry_run=true", meta.get("dry_run") is True)
        t.check("F meta.ok=true", meta.get("ok") is True)
        t.check("F meta.errors=[]", meta.get("errors") == [], str(meta.get("errors")))
        # meta 结构
        for k in ("task", "module", "schema_version", "generated_at", "host",
                  "errors", "ok", "params", "model", "plan"):
            t.check(f"F meta 含 {k}", k in meta)
        prm = meta.get("params", {})
        for k in ("prompt", "negative_prompt", "height", "width", "num_frames",
                  "num_inference_steps", "guidance_scale", "seed", "fps_out",
                  "determinism_runs", "lang", "model_dir"):
            t.check(f"F params 含 {k}", k in prm)
        t.check("F params 默认 704x1280/33/50/42/24",
                (prm.get("height"), prm.get("width"), prm.get("num_frames"),
                 prm.get("num_inference_steps"), prm.get("seed"), prm.get("fps_out"))
                == (704, 1280, 33, 50, 42, 24))
        t.check("F params.lang=zh", prm.get("lang") == "zh")
        t.check("F model.present=true", meta.get("model", {}).get("present") is True)
        t.check("F plan 记录 would_generate", "would_generate" in meta.get("plan", {}))
        # 零加载结构证据：dry-run 分支只走 stdlib，无任何加载/GPU 字段
        t.check("F 零加载（无 pipeline/vram 字段）",
                "pipeline" not in meta and "vram" not in meta and "runs" not in meta)
        t.check("F 产物 644", oct(mp.stat().st_mode)[-3:] == "644", oct(mp.stat().st_mode))

        # 权重目录缺失 → exit 1 + errors 落 meta 不静默
        out2 = Path(td) / "out_missing"
        p2 = _run_cli("--dry-run", "--model", Path(td) / "nope", "--out", out2)
        t.check("F 目录缺失 exit 1", p2.returncode == 1, f"rc={p2.returncode}")
        meta2 = json.loads((out2 / "wan22_meta.json").read_text(encoding="utf-8"))
        t.check("F 目录缺失 errors 落 meta", any("model_dir_missing" in e for e in meta2["errors"]),
                str(meta2["errors"]))
        t.check("F 目录缺失 ok=false", meta2["ok"] is False)

        # 坏帧数 → exit 2
        out3 = Path(td) / "out_badframes"
        p3 = _run_cli("--dry-run", "--model", model, "--out", out3, "--frames", "32")
        t.check("F frames=32 exit 2", p3.returncode == 2, f"rc={p3.returncode}")
        meta3 = json.loads((out3 / "wan22_meta.json").read_text(encoding="utf-8"))
        t.check("F frames=32 errors 落 meta", any("frames=32" in e for e in meta3["errors"]),
                str(meta3["errors"]))

        # 真 CLI（非 dry-run）目录缺失同样 fail-closed（不触 GPU，预检在前）
        out4 = Path(td) / "out_real_missing"
        p4 = _run_cli("--model", Path(td) / "nope", "--out", out4)
        t.check("F 非 dry-run 目录缺失 exit 1（先于 GPU 触碰）", p4.returncode == 1, f"rc={p4.returncode}")
        meta4 = json.loads((out4 / "wan22_meta.json").read_text(encoding="utf-8"))
        t.check("F 非 dry-run 目录缺失 errors 落 meta",
                any("model_dir_missing" in e for e in meta4["errors"]))


# ---------------------------------------------------------------- runner

def _t():
    return T()


def test_idempotent():
    t = _t(); _case_idempotent(t); assert not t.fails, t.fails

def test_property_branches():
    t = _t(); _case_property_branches(t); assert not t.fails, t.fails

def test_manual_load():
    t = _t(); _case_manual_load(t); assert not t.fails, t.fails

def test_failure_routing():
    t = _t(); _case_failure_routing(t); assert not t.fails, t.fails

def test_cli():
    t = _t(); _case_cli(t); assert not t.fails, t.fails

def test_dry_run():
    t = _t(); _case_dry_run(t); assert not t.fails, t.fails


def main() -> int:
    print(f"gen_wan22 适配层自测（tool={TOOL}）")
    t = _t()
    _case_idempotent(t)
    _case_property_branches(t)
    _case_manual_load(t)
    _case_failure_routing(t)
    _case_cli(t)
    _case_dry_run(t)
    n = len(t.fails)
    print(f"结论：{'ALL PASS' if n == 0 else f'{n} FAIL'}（{n} 条失败）")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
