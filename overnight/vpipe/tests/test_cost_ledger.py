# -*- coding: utf-8 -*-
"""test_cost_ledger.py —— src/cost/ledger.py 单测（M2-W9 成本台账）。

标准库 unittest，零第三方（被测模块自身按红线允许 import yaml）。
全部走临时目录夹具（自制最小 model_tiers/thresholds），零仓内产物写入、零真实 API。

覆盖（TASK_v4 §3.1 cost 行 + ask 交付口径）：
  1. record/report 往返：CLI record → report json 字段逐项还原
     （ts/cp_id/channel/wall_clock_s/currency/amount/conversion_basis/episode_id/
       note/thresholds_sha256/cost_confidence/channel_excluded）
  2. 跨币种拒汇总：total_amount 混币种 raise CrossCurrencySumError（exit 3）；
     report 默认输出 cross_currency_total 恒 null、只给 currency_distribution；
     --emit-grand-total tripwire → CLI exit 3
  3. 未知通道拒收：channel 不在 model_tiers channels/excluded_channels → exit 2
     且不落盘
  4. unverified/excluded 通道 amount=null 不进预算基线：无 --amount 可记
     （amount=null, currency 可为 null）；带 --amount 拒收 exit 2；
     report excluded_from_budget_baseline 计数、不进任何求和
  5. JSONL append-only 语义：两行追加、行序保持、首行字节级不变、
     record 绝不改写既有内容；坏行 → report exit 2（fail-fast）
  6. 判定数值单点：单集对照上限 = thresholds 三键乘积（24×280×1.2=8064 由夹具
     实算），代码零硬编码；thresholds 缺键 → report exit 2
  7. 币种词表与 provider 体系绑定：词表外拒；跨体系混填拒；钱包币种缺
     --amount 拒；local 缺省 amount=wall_clock_s

运行：
  cd overnight/vpipe && python3 tests/test_cost_ledger.py -v
  python3 -m unittest tests.test_cost_ledger -v   # 亦可收集
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER_PY = HERE.parent / "src" / "cost" / "ledger.py"

# ---- 被测模块（供守卫函数直测；CLI 走 subprocess 走真路径）----
_spec = importlib.util.spec_from_file_location("cost_ledger_under_test", LEDGER_PY)
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)

# ---------------------------------------------------------------------
# 最小夹具（结构与正式表同形：tiers[].channels[] / excluded_channels[] /
# checkpoints.cp9.gate + checkpoints.cost.episode_budget）
# ---------------------------------------------------------------------
TIERS_YAML = """\
version: "2.0"
cost_confidence_semantics:
  measured: "仓内实跑/实扣留痕"
  reported: "转引记录，本仓未复核"
  unverified: "未确证：不得进任何预算基线，amount 只能为 null"
tiers:
  - tier_id: T0
    channels:
      - channel_id: proc_ffmpeg
        provider: local
        cost_confidence: measured
  - tier_id: T2
    channels:
      - channel_id: local_ltx_2b
        provider: local
        cost_confidence: measured
  - tier_id: T4
    channels:
      - channel_id: api_h3max
        provider: minimax
        cost_confidence: measured
      - channel_id: api_kling_30
        provider: kling
        cost_confidence: unverified
  - tier_id: T5
    channels:
      - channel_id: api_seedance_25
        provider: volcengine
        cost_confidence: unverified
excluded_channels:
  - channel_id: local_wan22_a14b
    model: "Wan2.2-A14B"
    v100s_compatible: false
"""

THRESHOLDS_YAML = """\
version: 5
checkpoints:
  cp9:
    gate:
      credit_cap_per_shot: 280
  cost:
    episode_budget:
      standard_episode_shots: 24
      budget_multiplier: 1.2
"""

THRESHOLDS_NO_COST_YAML = """\
version: 5
checkpoints:
  cp9:
    gate:
      credit_cap_per_shot: 280
"""


class LedgerTestBase(unittest.TestCase):
    """临时目录 + 三路径覆盖 + CLI subprocess 助手。"""

    def setUp(self):
        import subprocess
        self._subprocess = subprocess
        self.tmp = Path(tempfile.mkdtemp(prefix="cost_ledger_test_"))
        self.ledger = self.tmp / "out" / "cost" / "ledger.jsonl"
        self.tiers = self.tmp / "model_tiers.yaml"
        self.thr = self.tmp / "thresholds.yaml"
        self.tiers.write_text(TIERS_YAML, encoding="utf-8")
        self.thr.write_text(THRESHOLDS_YAML, encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args, expect=0):
        proc = self._subprocess.run(
            [sys.executable, str(LEDGER_PY), *args,
             "--ledger", str(self.ledger),
             "--tiers", str(self.tiers),
             "--thresholds", str(self.thr)],
            capture_output=True, text=True)
        self.assertEqual(
            proc.returncode, expect,
            f"expect exit {expect}, got {proc.returncode}\n"
            f"cmd={args}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return proc

    def report_json(self, *extra):
        return json.loads(self.cli("report", "--format", "json", *extra).stdout)

    def entries(self):
        return [json.loads(ln) for ln in
                self.ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestRecordReportRoundTrip(LedgerTestBase):
    """1. record → report 往返（含缺省推断与显式全字段两条路径）。"""

    def test_roundtrip_all_fields(self):
        self.cli("record", "--cp-id", "cp7", "--channel", "local_ltx_2b",
                 "--wall-clock-s", "76.7",
                 "--episode-id", "short-drama/episode01",
                 "--note", "LTX 首镜草稿")
        self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                 "--wall-clock-s", "33.4", "--currency", "minimax_credit",
                 "--amount", "280",
                 "--episode-id", "short-drama/episode01",
                 "--note", "钱包实扣 280",
                 "--conversion-basis", "钱包逐条实扣可对（工程方案v3.md:125 口径）")
        rep = self.report_json()
        self.assertEqual(rep["entry_count"], 2)
        by_ch = {e["channel"]: e for e in self.entries()}
        # 本地通道：币种推断 local_wall_s，amount 缺省=墙钟（0 积分、76.7s/条 口径）
        ltx = by_ch["local_ltx_2b"]
        self.assertEqual(ltx["cp_id"], "cp7")
        self.assertEqual(ltx["currency"], "local_wall_s")
        self.assertEqual(ltx["amount"], 76.7)
        self.assertEqual(ltx["wall_clock_s"], 76.7)
        self.assertTrue(ltx["conversion_basis"].strip())
        self.assertEqual(ltx["cost_confidence"], "measured")
        self.assertFalse(ltx["channel_excluded"])
        self.assertEqual(ltx["episode_id"], "short-drama/episode01")
        self.assertEqual(ltx["note"], "LTX 首镜草稿")
        # API 通道：显式币种+金额+折算口径逐字还原
        h3 = by_ch["api_h3max"]
        self.assertEqual(h3["currency"], "minimax_credit")
        self.assertEqual(h3["amount"], 280.0)
        self.assertEqual(h3["conversion_basis"],
                         "钱包逐条实扣可对（工程方案v3.md:125 口径）")
        # thresholds_sha256 与夹具文件实算一致（同 gate/eval 口径）
        import hashlib
        want = hashlib.sha256(self.thr.read_bytes()).hexdigest()
        for e in self.entries():
            self.assertEqual(e["thresholds_sha256"], want)
        # report 聚合位
        self.assertEqual(rep["wall_clock_by_cp"]["cp7"]["wall_clock_s_total"], 76.7)
        self.assertEqual(rep["wall_clock_by_cp"]["cp7"]["calls"], 1)
        self.assertEqual(rep["calls_by_channel"]["api_h3max"]["calls"], 1)
        self.assertTrue(rep["calls_by_channel"]["api_h3max"]["enters_budget_baseline"])
        self.assertEqual(rep["minimax_credit_by_episode"]["short-drama/episode01"], 280.0)

    def test_report_episode_filter(self):
        self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                 "--wall-clock-s", "30", "--amount", "280",
                 "--episode-id", "ep1")
        self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                 "--wall-clock-s", "30", "--amount", "280",
                 "--episode-id", "ep2")
        rep = self.report_json("--episode-id", "ep1")
        self.assertEqual(rep["entry_count"], 1)
        self.assertEqual(rep["episode_filter"], "ep1")
        self.assertEqual(rep["minimax_credit_by_episode"], {"ep1": 280.0})
        self.assertNotIn("ep2", rep["wall_clock_by_cp"].values()
                         if isinstance(rep["wall_clock_by_cp"], list) else [])
        self.assertNotIn("ep2", rep["minimax_credit_by_episode"])

    def test_cp_id_normalized_case(self):
        self.cli("record", "--cp-id", "CP9", "--channel", "api_h3max",
                 "--wall-clock-s", "30", "--amount", "280")
        self.assertEqual(self.entries()[0]["cp_id"], "cp9")

    def test_bad_cp_id_rejected(self):
        proc = self.cli("record", "--cp-id", "cp13", "--channel", "local_ltx_2b",
                        "--wall-clock-s", "10", expect=2)
        self.assertIn("cp1..cp12", proc.stderr)
        self.assertFalse(self.ledger.exists())  # 拒收不落盘


class TestCrossCurrencyForbidden(LedgerTestBase):
    """2. 跨币种拒汇总：守卫函数 / report 恒不给总额 / tripwire exit 3。"""

    def seed_mixed(self):
        self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                 "--wall-clock-s", "30", "--amount", "280", "--episode-id", "ep1")
        self.cli("record", "--cp-id", "cp10", "--channel", "proc_ffmpeg",
                 "--wall-clock-s", "12.5", "--episode-id", "ep1")

    def test_guard_raises_on_mixed(self):
        self.assertEqual(ledger.CrossCurrencySumError.exit_code, 3)
        mixed = [{"amount": 280.0, "currency": "minimax_credit"},
                 {"amount": 12.5, "currency": "local_wall_s"},
                 {"amount": None, "currency": None}]
        with self.assertRaises(ledger.CrossCurrencySumError) as cm:
            ledger.total_amount(mixed)
        self.assertIn("四套货币不可换算", str(cm.exception))
        # 同币种（显式指定或天然单一）合法
        self.assertEqual(ledger.total_amount(mixed, currency="minimax_credit"), 280.0)
        self.assertEqual(
            ledger.total_amount([{"amount": 1, "currency": "vidu_credit"},
                                 {"amount": 2, "currency": "vidu_credit"}]), 3.0)

    def test_report_json_never_carries_grand_total(self):
        self.seed_mixed()
        rep = self.report_json()
        self.assertIsNone(rep["cross_currency_total"])
        self.assertIn("不可换算", rep["cross_currency_note"])
        dist = rep["currency_distribution"]
        self.assertEqual(dist["minimax_credit"]["sum"], 280.0)
        self.assertEqual(dist["local_wall_s"]["sum"], 12.5)
        self.assertNotIn("total", rep)          # 顶层无任何跨币种总额字段
        md = self.cli("report", "--format", "md").stdout
        self.assertIn("不给总额", md)

    def test_tripwire_exit3(self):
        self.seed_mixed()
        proc = self.cli("report", "--format", "json", "--emit-grand-total", expect=3)
        self.assertIn("跨币种", proc.stderr)

    def test_tripwire_same_currency_passes(self):
        self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                 "--wall-clock-s", "30", "--amount", "280")
        proc = self.cli("report", "--format", "json", "--emit-grand-total")
        rep = json.loads(proc.stdout)
        self.assertEqual(rep["cross_currency_total"], 280.0)  # 同体系内比较才可达


class TestUnknownChannelRejected(LedgerTestBase):
    """3. 未知通道拒收（通道枚举单点 = model_tiers.yaml）。"""

    def test_unknown_channel_exit2_no_write(self):
        proc = self.cli("record", "--cp-id", "cp7", "--channel", "local_sora",
                        "--wall-clock-s", "10", expect=2)
        self.assertIn("model_tiers", proc.stderr)
        self.assertIn("excluded_channels", proc.stderr)   # 提示含两处合法来源
        self.assertFalse(self.ledger.exists())

    def test_excluded_channel_is_known(self):
        # excluded_channels 里的通道名是「已知」的：可记（出局历史），但 amount 恒 null
        self.cli("record", "--cp-id", "cp7", "--channel", "local_wan22_a14b",
                 "--wall-clock-s", "25200")
        e = self.entries()[0]
        self.assertTrue(e["channel_excluded"])
        self.assertIsNone(e["amount"])


class TestUnverifiedNoBaseline(LedgerTestBase):
    """4. unverified/excluded 通道 amount=null、不进任何预算基线。"""

    def test_unverified_without_amount_ok(self):
        # volcengine 无默认币种映射 + unverified → currency=null, amount=null
        self.cli("record", "--cp-id", "cp9", "--channel", "api_seedance_25",
                 "--wall-clock-s", "60", "--note", "未核价试跑")
        e = self.entries()[0]
        self.assertIsNone(e["amount"])
        self.assertIsNone(e["currency"])
        self.assertEqual(e["cost_confidence"], "unverified")
        self.assertTrue(e["conversion_basis"].strip())  # 折算口径仍须显式声明

    def test_unverified_with_amount_rejected(self):
        proc = self.cli("record", "--cp-id", "cp9", "--channel", "api_seedance_25",
                        "--wall-clock-s", "60", "--amount", "1.15", expect=2)
        self.assertIn("不进任何预算基线", proc.stderr)
        self.assertIn("null", proc.stderr)
        self.assertFalse(self.ledger.exists())

    def test_excluded_with_amount_rejected(self):
        proc = self.cli("record", "--cp-id", "cp7", "--channel", "local_wan22_a14b",
                        "--wall-clock-s", "25200", "--amount", "0", expect=2)
        self.assertIn("出局通道", proc.stderr)
        self.assertFalse(self.ledger.exists())

    def test_unverified_never_enters_sums_or_baseline(self):
        self.cli("record", "--cp-id", "cp9", "--channel", "api_seedance_25",
                 "--wall-clock-s", "60")
        self.cli("record", "--cp-id", "cp9", "--channel", "api_kling_30",
                 "--wall-clock-s", "40")  # unverified 但 provider=kling 同样无映射
        rep = self.report_json()
        self.assertEqual(rep["minimax_credit_by_episode"], {})
        self.assertEqual(rep["episode_budget"]["by_episode"], {})
        for ch in ("api_seedance_25", "api_kling_30"):
            self.assertFalse(rep["calls_by_channel"][ch]["enters_budget_baseline"])
        self.assertEqual(rep["excluded_from_budget_baseline"],
                         {"api_seedance_25": 1, "api_kling_30": 1})
        self.assertEqual(rep["currency_distribution"]["null_unverified"]["entries"], 2)
        self.assertIsNone(rep["currency_distribution"]["null_unverified"]["sum"])

    def test_tampered_unverified_amount_detected(self):
        # 篡改场景：measured+带 amount 的历史行被改成 unverified（档位漂移/手改），
        # report 端按「不进任何预算基线」红线 fail-fast
        self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                 "--wall-clock-s", "30", "--amount", "280")
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        bad = json.loads(lines[0])
        bad["cost_confidence"] = "unverified"
        lines[0] = json.dumps(bad, ensure_ascii=False)
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        proc = self.cli("report", expect=2)
        self.assertIn("不进任何预算基线", proc.stderr)


class TestAppendOnlySemantics(LedgerTestBase):
    """5. JSONL append-only：整行追加、行序保持、既有内容字节级不变、坏行 fail-fast。"""

    def test_append_only_two_records(self):
        self.cli("record", "--cp-id", "cp7", "--channel", "local_ltx_2b",
                 "--wall-clock-s", "76.7")
        before = self.ledger.read_bytes()
        first_line = before.splitlines()[0]
        self.assertEqual(len(before.splitlines()), 1)
        self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                 "--wall-clock-s", "33.4", "--amount", "280")
        after = self.ledger.read_bytes()
        lines = after.splitlines()
        # 行数 +1、行序保持、首行字节级不变（绝无改写/重排）
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], first_line)
        self.assertTrue(after.startswith(before))
        self.assertTrue(after.endswith(b"\n"))              # 每记录整行落盘
        # 两条记录解析后按行序还原
        es = self.entries()
        self.assertEqual([e["cp_id"] for e in es], ["cp7", "cp9"])

    def test_report_survives_only_with_intact_lines(self):
        self.cli("record", "--cp-id", "cp7", "--channel", "local_ltx_2b",
                 "--wall-clock-s", "76.7")
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write("{not-json\n")                          # 模拟外部截断/坏行
        proc = self.cli("report", expect=2)
        self.assertIn("第 2 行", proc.stderr)
        self.assertIn("append-only", proc.stderr)

    def test_missing_ledger_report_exit2(self):
        proc = self.cli("report", expect=2)
        self.assertIn("台账不存在", proc.stderr)
        self.assertIn("record", proc.stderr)


class TestBudgetBaseline(LedgerTestBase):
    """6. 单集对照行：上限=thresholds 三键乘积实算（24×280×1.2），零硬编码。"""

    def test_cap_derived_not_hardcoded(self):
        self.assertEqual(ledger.load_budget(self.thr)["episode_cap"], 8064)
        # 改夹具键值 → 上限跟随变化（证明不是写死的 8064）
        self.thr.write_text(THRESHOLDS_YAML.replace(
            "budget_multiplier: 1.2", "budget_multiplier: 1.5"), encoding="utf-8")
        self.assertEqual(ledger.load_budget(self.thr)["episode_cap"], 10080)

    def test_within_and_over_budget_rows(self):
        for _ in range(3):  # 3 镜 × 280 = 840 ≤ 8064
            self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                     "--wall-clock-s", "33.4", "--amount", "280",
                     "--episode-id", "short-drama/episode01")
        rep = self.report_json()
        row = rep["episode_budget"]["by_episode"]["short-drama/episode01"]
        self.assertEqual(row["spent_minimax_credit"], 840.0)
        self.assertEqual(row["cap_minimax_credit"], 8064)
        self.assertEqual(row["usage_pct"], 10.4)
        self.assertTrue(row["within_budget"])
        # 超 24 镜口径（30×280=8400 > 8064）→ 对照行判超限
        for _ in range(30):
            self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                     "--wall-clock-s", "33.4", "--amount", "280",
                     "--episode-id", "short-anime/episode01")
        rep = self.report_json()
        row = rep["episode_budget"]["by_episode"]["short-anime/episode01"]
        self.assertEqual(row["spent_minimax_credit"], 8400.0)
        self.assertFalse(row["within_budget"])
        md = self.cli("report", "--format", "md").stdout
        self.assertIn("8400", md)
        self.assertIn("超限", md)
        self.assertIn("8064", md)  # 对照行展示三键乘积结果

    def test_report_exit2_when_thresholds_missing_keys(self):
        self.cli("record", "--cp-id", "cp7", "--channel", "local_ltx_2b",
                 "--wall-clock-s", "76.7")
        self.thr.write_text(THRESHOLDS_NO_COST_YAML, encoding="utf-8")
        proc = self.cli("report", expect=2)
        self.assertIn("不许硬编码", proc.stderr)


class TestCurrencyRules(LedgerTestBase):
    """7. 币种词表 + provider 体系绑定 + amount 缺省规则。"""

    def test_local_defaults_to_wall(self):
        self.cli("record", "--cp-id", "cp11", "--channel", "proc_ffmpeg",
                 "--wall-clock-s", "5.2")
        e = self.entries()[0]
        self.assertEqual(e["currency"], "local_wall_s")
        self.assertEqual(e["amount"], 5.2)

    def test_wallet_currency_requires_amount(self):
        proc = self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                        "--wall-clock-s", "30", expect=2)
        self.assertIn("显式 --amount", proc.stderr)
        self.assertFalse(self.ledger.exists())

    def test_currency_vocab_enforced(self):
        proc = self.cli("record", "--cp-id", "cp9", "--channel", "api_h3max",
                        "--wall-clock-s", "30", "--amount", "280",
                        "--currency", "dollar", expect=2)
        self.assertIn("词表", proc.stderr)

    def test_cross_system_binding_rejected(self):
        # minimax_credit 只属于 minimax 体系；本地通道混填即拒（两钱包不可换算）
        proc = self.cli("record", "--cp-id", "cp7", "--channel", "local_ltx_2b",
                        "--wall-clock-s", "10", "--amount", "280",
                        "--currency", "minimax_credit", expect=2)
        self.assertIn("体系绑定不符", proc.stderr)
        self.assertIn("minimax_credit", proc.stderr)

    def test_unmapped_provider_with_amount_needs_currency(self):
        # CLI 层：kling 在夹具里是 unverified，更严的「不进基线」守卫先触发
        proc = self.cli("record", "--cp-id", "cp9", "--channel", "api_kling_30",
                        "--wall-clock-s", "40", "--amount", "12", expect=2)
        self.assertIn("不进任何预算基线", proc.stderr)
        # kling 正确用法=不带 amount（amount=null 不进基线）
        self.cli("record", "--cp-id", "cp9", "--channel", "api_kling_30",
                 "--wall-clock-s", "40")
        self.assertIsNone(self.entries()[0]["amount"])
        # 模块层：measured+无映射 provider 带 amount 缺币种 → 「无默认币种映射」
        # （合成夹具只为触达该分支；正式表 unmapped provider 均 unverified）
        synthetic = {"api_x_measured": {"provider": "kling", "cost_confidence": "measured",
                                        "excluded": False}}
        with self.assertRaises(ledger.LedgerError) as cm:
            ledger.build_entry("cp9", "api_x_measured", 40.0, currency=None,
                               amount=12.0, episode_id=None, note=None,
                               conversion_basis=None, channels=synthetic,
                               thr_sha="0" * 64)
        self.assertIn("无默认币种映射", str(cm.exception))

    def test_bad_wall_clock_rejected(self):
        for bad in ("-1", "nan"):
            proc = self.cli("record", "--cp-id", "cp7", "--channel", "local_ltx_2b",
                            "--wall-clock-s", bad, expect=2)
            self.assertIn("wall_clock_s", proc.stderr)
        self.assertFalse(self.ledger.exists())

    def test_empty_conversion_basis_rejected(self):
        proc = self.cli("record", "--cp-id", "cp7", "--channel", "local_ltx_2b",
                        "--wall-clock-s", "10", "--conversion-basis", "   ",
                        expect=2)
        self.assertIn("折算口径", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
