#!/usr/bin/env bash
# M2/M3 验收门统一跑（TASK_v4 §4 M2/M3 验收项的全量确定性对账）
# 任何人按本脚本跑一遍即可判定 v4 试点三线是否达成任务卡要求。
# 用法：bash overnight/vpipe/tests/run_m2m3_acceptance.sh
# 退出码：0=全部达标；1=有未达标项（明细见输出）
set -u
cd "$(dirname "$0")/../../.."   # 仓根（tests→vpipe→overnight→root）
V=overnight/vpipe/src/gate
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  [PASS] $1"; }
bad() { FAIL=$((FAIL+1)); echo "  [FAIL] $1"; }

echo "=== M2/M3 验收门统一跑（$(date '+%Y-%m-%d %H:%M')）==="

# ── 门 0：工程底线（G0-1..G0-4）────────────────────────────
echo "── 门 0：工程底线"
timeout 300 python3 overnight/vpipe/tests/run_v3_checks.py >/tmp/g01.log 2>&1
[ $? -eq 0 ] && ok "G0-1 v3 确定性自检 ALL PASS/EXIT=0" || bad "G0-1 自检未过（见 /tmp/g01.log）"
python3 overnight/vpipe/eval/eval_run.py --qc-dir overnight/vpipe/out/qc_reports_v3post >/tmp/eval.log 2>&1
grep -q "验收结论: ACCEPT" /tmp/eval.log && ok "G0-2 eval_run ACCEPT" || bad "G0-2 eval 非 ACCEPT"
A=$(sha256sum overnight/vpipe/eval/thresholds.yaml 2>/dev/null | cut -d' ' -f1)
B=$(python3 -c "import json;print(json.load(open('overnight/vpipe/eval/eval_results.json'))['thresholds_sha256'])" 2>/dev/null)
if [ -n "$A" ] && [ -n "$B" ] && [ "$A" = "$B" ]; then ok "G0-3 thresholds sha256 对账一致"; else bad "G0-3 sha256 不一致或读取失败（A=${A:0:8} B=${B:0:8}）"; fi
[ -z "$(git ls-files | grep -iE 'secret|api_key' | grep -v '\.md$')" ] && ok "G0-4 密钥零入库" || bad "G0-4 疑似密钥入库"

# ── 门 1：三线样片三件齐 ─────────────────────────────────
echo "── 门 1：三线样片（样片+QCReport+门禁）"
check_line() {  # $1=目录 $2=线名 $3=目标秒 $4=人工率上限
  local D="overnight/vpipe/out/m2/$1"
  [ -f "$D/cp11/master.mp4" ] || [ -f "$D/cp11/master_v2.mp4" ] || { bad "$2 样片缺失"; return; }
  local M="$D/cp11/master.mp4"; [ -f "$D/cp11/master_v2.mp4" ] && M="$D/cp11/master_v2.mp4"
  local dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$M" 2>/dev/null)
  local spec=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name -of csv=p=0 "$M" 2>/dev/null)
  echo "h264,1080,1920" | grep -q "$spec" && ok "$2 样片规格 1080x1920 h264（${dur}s）" || bad "$2 样片规格异常：$spec"
  [ -f "$D/qc_report_v2.json" ] && ok "$2 QCReport v2 在位" || bad "$2 QCReport v2 缺失"
  python3 $V/validate_cp12.py "$D/cp12.json" >/dev/null 2>&1 && ok "$2 CP12 四维门 exit 0" || bad "$2 CP12 门禁未过"
  local rate=$(python3 -c "import json;print(json.load(open('$D/cp12.json'))['payload'].get('human_escalation_rate'))" 2>/dev/null)
  python3 -c "import sys;sys.exit(0 if float('$rate' or 0) <= $4 else 1)" && ok "$2 人工上升率 $rate ≤ $4" || bad "$2 人工上升率 $rate 超 $4"
  # 成本对账（同币种）
  local cost=$(python3 overnight/vpipe/src/cost/ledger.py report --episode-id "$1" --format json 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin)['minimax_credit_by_episode'].get('$1','n/a'))" 2>/dev/null)
  local cap=$(python3 -c "import yaml;v=yaml.safe_load(open('overnight/vpipe/eval/thresholds.yaml'))['checkpoints']['cost']['episode_budget'];print(int(v['standard_episode_shots']*280*v['budget_multiplier']))" 2>/dev/null)
  python3 -c "import sys;sys.exit(0 if '$cost'!='n/a' and float('$cost')<=float('$cap') else 1)" && ok "$2 MiniMax 积分 $cost ≤ cap $cap" || echo "  · $2 MiniMax 积分合计：$cost（cap $cap）"
}
check_line shortdrama_ep01  "短剧线" 64 0.25
check_line marketing_ep01  "营销线" 20 0.10
check_line comicanime_ep01 "漫剧线" 30 0.20

# ── 门 2：CP 级夹具库（M3）────────────────────────────────
echo "── 门 2：M3 CP 级夹具库"
bash overnight/vpipe/tests/run_gate_regression.sh >/tmp/reg.log 2>&1
tail -1 /tmp/reg.log | grep -q "错判 0" && ok "门禁回归全判对（$(tail -1 /tmp/reg.log | grep -oE '判对 [0-9]+')）" || bad "门禁回归有错判（$(tail -1 /tmp/reg.log)）"

# ── 门 3：模板线失效传播（M3-W11）─────────────────────────
echo "── 门 3：模板线失效传播"
(cd overnight/vpipe && python3 tests/test_invalidation.py >/tmp/inv.log 2>&1) && ok "invalidation 自测 ALL PASS（$(grep -c "PASS" /tmp/inv.log) 项）" || bad "invalidation 测试未过"
python3 $V/invalidation.py plan --dir overnight/vpipe/out/m2/shortdrama_ep01 \
  --changed overnight/vpipe/out/m2/shortdrama_ep01/cp2.json >/tmp/inv_plan.json 2>/dev/null
python3 -c "
import json
d = json.load(open('/tmp/inv_plan.json'))
inv, unaff = d['invalidated_count'], d['unaffected_count']
cp1_unaff = any('cp1' in p for p in d['unaffected'])
assert inv > 0 and cp1_unaff, f'闭包异常 inv={inv} cp1_unaffected={cp1_unaff}'
print('  · 改 cp2 → 失效', inv, '/ 不受影响', unaff, '（cp1 不受影响 ✓）')
" && ok "失效传播闭包正确（下游全失效+cp1 不受影响）" || bad "失效传播异常"

# ── 门 4：三版本字段（M3-W12）────────────────────────────
echo "── 门 4：三版本字段"
python3 -c "
import yaml
v = yaml.safe_load(open('overnight/vpipe/eval/thresholds.yaml'))['versioning']
assert all(v.get(k) for k in ('spec_version','registry_version','prompt_version')), '三版本字段缺失'
print('  ·', {k: str(v[k])[:20] for k in v})
" && ok "三版本字段在位（spec/registry/prompt）" || bad "三版本字段缺失"

# ── 门 5：VDL v2 试点裁决（D-2）──────────────────────────
echo "── 门 5：VDL v2 试点"
(cd overnight/vpipe && env -u VDL2_VPO_ROOT timeout 180 /usr/bin/python3 -m pytest tests/test_vdl2.py -q >/tmp/vdl2.log 2>&1)
grep -qE "[0-9]+ passed" /tmp/vdl2.log && ! grep -q "failed" /tmp/vdl2.log \
  && ok "VDL v2 双闸门测试全过（$(grep -oE '[0-9]+ passed' /tmp/vdl2.log)）" || bad "VDL v2 测试未过（见 /tmp/vdl2.log）"
env -u VDL2_VPO_ROOT timeout 120 /usr/bin/python3 overnight/vpipe/src/vdl2/vdl2_validate.py \
  --pkg overnight/vpipe/examples/vdl2/10_shortdrama_ep01.yaml >/tmp/vdl2v.log 2>&1 \
  && ok "短剧线 VDL v2 包 validate PASS（裁决=继续，evidence/vdl2-pilot-verdict.md）" || bad "VDL v2 短剧线包校验失败"

# ── 汇总 ─────────────────────────────────────────────────
echo "=============================="
echo "M2/M3 验收门：PASS $PASS / FAIL $FAIL"
[ $FAIL -eq 0 ] && echo "结论：全部达标" || echo "结论：存在未达标项，见上"
exit $([ $FAIL -eq 0 ] && echo 0 || echo 1)
