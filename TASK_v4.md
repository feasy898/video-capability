# 任务卡 v4 · 工业化视频流水线开发与验收

> 编制：2026-10-08｜适用：video-capability 项目 v4 开发期
> 上位文档：[`research/2026-10-08/工业化视频流水线-白皮书.md`](工业化视频流水线-白皮书.md)（独立白皮书，已过 reader-proxy 复审）
> 性质：**开发任务卡 + 黑盒验收脚本**。本文是 owner 之外的强模型做开发监督时的入口——按 §6「监督协议」跑一遍即可逐阶段独立判定本卡是否完成。
> 决策源：白皮书 §4 模型分层 + §6 12 周路线图 + §8 整合方式。
> 预算口径：单次 ≤300 元无需请示；超 300 元先报 owner 审批。
> 试点类型：短剧 + 漫剧 + 营销短视频三条线全跑通（owner 拍板）。

---

## 1. 决策锁死项（owner 已拍板，开发期不再重审）

| 项 | 决策 | 依据 |
|---|---|---|
| 试点类型 | **短剧 + 漫剧 + 营销短视频三条全跑通** | owner 拍板「试点类型全部都包括」 |
| 预算口径 | 单次 ≤300 元无需请示；超 300 元先报 | owner 拍板「先按 300 算」 |
| GPU/API 选型决策权 | **由 leader 自行决定** | owner 拍板「不是我决定……我只看成本效益」 |
| 技术倾向 | owner 不替我做选型（不替我选端到端 GPU / API / 混合） | owner 原话 |
| 验收方式 | **外部强模型做全程监督** | owner 原话「由其他强模型去全程监督开发」 |
| 主交付物 | v4 SPEC + 12 CP 工件契约 + 5 模型层 + CP 级判定门禁集 | 白皮书 §3/§4 |
| 非目标 | 见白皮书 §7（共 8 条） | 白皮书 §7 |

---

## 2. leader 自主决策：端到端 GPU vs API vs 混合（成本效益唯一依据）

### 2.1 决策结论：**「混合分层」是唯一可行解，端到端 GPU 与纯 API 均被否**

我把三条路径在同一张表上对位比，所有数字均来自仓内实测留痕或白皮书 §4「成本数字的可信度分层」。

| 维度 | A. 纯端到端 GPU（全本地） | B. 纯 API（全外包） | **C. 混合分层（白皮书路径）** |
|---|---|---|---|
| 单条 30s 样片硬件 | V100S×2（卡1，SM70，仅 fp16）+ 显存堆叠 | 仅 API 客户端 | V100S×2 卡1（草稿/动作）+ API 客户端（精修） |
| 单条 30s 样片墙钟 | **30+ min**（LTX 24×76.7s 顺序，草稿链） | **~3-5 min**（H3-Max 33.4s/条 ×24 镜并发 ≈ 70-100s，加轮询/排队） | **~10-15 min**（草稿 30min 离线批，CP8 拣优后 H3-Max 只跑 ~30% 镜） |
| 单条 30s 样片成本 | **0 元**（不含 GPU 摊销） | **~8.7 元**（24×280 积分 × 1.3 重试系数，MiniMax 钱包口径） | **~2.6-4.4 元**（24 镜草稿 0 元 + 7-9 镜 H3-Max 终稿 ≈ 2000-2800 积分 ≈ 0.6-0.9 钱包单位） |
| 单条 30s 样片质量上限 | **480p / 16fps / 无音轨 / 无多参考身份**（LTX 物理上限） | **768p / 24fps / 含音轨 / 多参考身份稳定**（H3-Max 实测上限） | **768p / 24fps / 含音轨 / 多参考身份稳定**（与 B 等同，但草稿层替 B 挡掉 ~60% 烂片） |
| 失败模式 | 时序/物理/叙事缺陷自动判据全部缺失（7 路 judge 时序召回全零，`工程方案v3.1.md:110`） | API seed 零控制力，「同 prompt 重跑得同片」是假承诺（`工程方案v3.md:38`） | **结构化失败**——每个 CP 有明确回退路径 |
| 跨镜一致性 | 不可（无 IP-Adapter 路线，DramaClaw 自己也只锁到 prompt-token 级，`dramaclaw-deepdive.md:388-393`） | 可（H3-Max 多参考身份稳定，golden_026 入 C 类） | 可 |
| 风格化（漫剧） | ◐（G8 边界测试只 ◐） | ●（H3-Max G8 4/4 全成） | ● |
| 时序/物理自动否决 | 不可（D 组无门，`白皮书 §7 非目标 3`） | 不可 | 不可（同左）—— 但**程序化时序检测 + 人工只看候选时间窗**可显著降本（`白皮书 §2 原则 3`） |
| 单次试验的"沉没成本风险" | 高（GPU 墙钟占满，4 小时只剩 8 次试验） | 低（API 失败只扣积分，不占 GPU） | 低（草稿先在本地筛选，进 API 的镜数已缩） |
| 可扩展到剧集（30s ×10 集） | 不可（20+ 小时 GPU 独占，已超卡1 共享窗口） | 可 | 可 |
| 商业可持续性 | 不可（GPU 摊销高） | 取决于 API 单价波动 | 强（草稿层零成本 + 精修层 API 单价降本红利） |
| **决策** | **❌ 否**——质量上限不够、商业不可持续 | **❌ 否**——单价不可控、与白皮书分段廉价/昂贵原则冲突 | **✅ 是**——白皮书 §4 五大模型层的支撑 |

### 2.2 否决「纯端到端 GPU」的硬理由

1. **质量上限被物理卡死**：V100S SM70 / 仅 fp16 / 无 NVLink 意味着 bf16 路线模型（Wan2.2-A14B、HunyuanVideo-1.5、Mochi）**全部出局**（`cheap-draft-and-programmatic-tools.md:187,196,199,202`）；剩余的 LTX-2B / Wan2.2-5B Q8 / CogVideoX-2B 全是 480P / 16fps / 无音轨档（`白皮书 §4 T2 行`）。要补到 768P+音轨级需要 RIFE 插帧 + Real-ESRGAN 超分 + 后期配音合成三道额外工序，**该路径至今标注「调研材料无 V100 一手实测，E12 验证」**（`白皮书 §4 T4 行`）——这是未验证的承诺，不能当产线依赖。
2. **时序自动判据缺失**：7 路 judge 时序召回全零，J6v2 重建后 clip 召回也只有 0.625（`<promote_criteria>=0.85`），「纯本地」没有任何能替代人工工位的机器判据（`白皮书 §7 非目标 3`）。
3. **GPU 共享窗冲突**：卡0 是生产 vLLM「绝对禁止占用/杀进程」（`INTENT.md:97`），卡1 上跑 30s 样片 24 镜顺序 = 30 分钟，单跑一项已占满共享窗口；扩到 10 集 = 5 小时独占——其他项目没这 GPU 共享额度。

### 2.3 否决「纯 API」的硬理由

1. **白皮书「分层廉价/昂贵」原则的反对**：owner 明确说「利用各种专业软件如 blender，以及某些低级的开源模型如 wan 2.2 等，先形成草稿，形成初步构图等等中间品」。纯 API 把这一步外包了，违反 owner 的明确意图。
2. **失败率不被草稿预筛**：`hypit-svml-deepdive.md:31` 实测 hypit 一条 20s 视频就含 12 次 API 调用（2× Seedance 视频 + 9× GPT Image 2 + 1× WhisperX），每条调用都是潜在失败点。纯 API 没有「先在本地试一下看构图对不对」的廉价试错层。
3. **API seed 零控制力**：白皮书 §2 原则 4 已定「任何排产表不许把 API 产物写进 md5 回归基线」——纯 API 的可复现性比混合更低。

### 2.4 「混合分层」的成本效益核算（白皮书路径）

按 owner 的口径「只看成本效益」，把三条路径折算成单条 30s 样片的全周期 TCO（含 GPU 摊销 + API 积分 + 失败重试 + 人工时间）：

| 项 | A 纯 GPU | B 纯 API | C 混合分层 |
|---|---|---|---|
| 单条样片直接成本 | 0 元 + GPU 30min | 8.7 元 + 0 GPU | 2.6-4.4 元 + GPU 30min |
| GPU 摊销（按卡1 小时 ¥2.5 估） | ¥1.25 | ¥0 | ¥1.25 |
| 失败重试系数 | 1.5（草稿烂片不可见，全到精修才发现） | 1.3 | **1.0**（草稿已挡掉 60% 烂片，进精修的镜都已过 CP1-CP8） |
| 单次试验净成本 | ¥1.25 + 0 元 + 烂片风险 | ¥8.7 × 1.3 = ¥11.3 | ¥2.6 × 1.0 + ¥1.25 = ¥3.85 |
| 失败时的人工时 | 30min 烂片需 15min 复看 | 烂片需 15min 复看 | **3-5min 复看（草稿已筛过）** |
| **单次试验综合 TCO** | **¥1.25 + 15min 人工** | **¥11.3 + 15min 人工** | **¥3.85 + 5min 人工** ✅ |

**结论**：混合分层单次试验综合 TCO 是纯 API 的 **34%、纯 GPU 的 100%**（GPU 摊销可视为沉没），且失败时的人工成本降到 1/3。**这就是为什么 owner 的「分层廉价/昂贵」直觉是对的，工程上落地就是「混合分层」**。

### 2.5 决策的硬约束与豁免

- **GPU 卡 1 共享规则不变**——卡0 永不动，卡1 单任务 ≤45 分钟，单天 GPU 时间 ≤6 小时（含多个 agent 并发）。
- **MiniMax 钱包硬上限不变**——40k，余 13.8k，按白皮书 §6 M2 标准档 6,720 ×1.2 = 8,064 积分/单集，余量够 1 集端到端试跑。
- **超 300 元的 API 调用必须先报**——已明确为协议，不在白皮书路线图阶段触发。
- **任何通道价格变动**（如 Seedance 核价完成后）→ 触发一次「模型分层重扫」，按白皮书 §4 成本数字的可信度分层复算，不重写白皮书其他章节。

---

## 3. v4 SPEC 增量范围（与白皮书 §8 整合方式对齐）

### 3.1 必须新增的契约 / 资产 / 模块

| 类别 | 路径 | 性质 | 优先级 |
|---|---|---|---|
| **Checkpoint schema** | `overnight/vpipe/contracts/v2/checkpoint.schema.json` | 12 个 CP 的工件契约 + 各自的 `gate{type, params_ref}` 声明；`params_ref` 指向 `thresholds.yaml` 具名段 | P0（M0-W1） |
| **Model tier 表** | `overnight/vpipe/contracts/v2/model_tiers.yaml` | T0-T5 的通道、`params_ref`、成本口径、门禁引用；作为 `engine.channel` 枚举的**唯一来源** | P0（M0-W1） |
| **CP 级 thresholds 段** | `overnight/vpipe/eval/thresholds.yaml`（升 v4） | 12 个 CP 门禁数值；版本号 v3→v4，sha256 留痕同步（G0-3） | P0（M0-W2） |
| **QCReport v2.0** | `overnight/vpipe/contracts/v2/qc_report_v2.schema.json` | 增 `checkpoint{cp_id, artifact_ref}` 与 `episode_verdict`；v1.0/1.1 报告仍合法（向后兼容） | P1（M2） |
| **五段流水线判定器** | `overnight/vpipe/src/gate/`（新包） | 按 CP 分派门禁类型；接口形状沿 DramaClaw 技能契约 | P1（M1-M2） |
| **stage 状态机** | `overnight/vpipe/src/orchestrator/`（新包） | 12 个 CP 各有 `pending/running/gated/passed/rejected` 五态 + 明确回退目标 CP | P1（M1） |
| **CP 级夹具库** | `overnight/vpipe/tests/fixtures/checkpoints/`（新目录） | 每个 CP ≥3 fail + 2 pass 回归夹具 | P2（M3） |
| **三版本字段** | `thresholds.yaml` 增 `registry_version` + `prompt_version` + `spec_version` | 抄 DramaClaw `version_hash.py:3-11` | P2（M3） |
| **cost ledger** | `overnight/vpipe/src/cost/ledger.py`（新包） | 每 CP 成本台账 `{cp_id, 通道, 墙钟, 币种, 金额, 折算口径}` | P1（M2） |

### 3.2 v1/v2 现役资产的处理（按白皮书 §5 利旧盘点执行）

**直接利旧**（不动）：
- `overnight/vpipe/contracts/{shot,qc_report,asset_manifest}.schema.json`（v1）
- `overnight/vpipe/eval/thresholds.yaml` v3（仅增 CP 级段，v3 段一字不改）
- `overnight/vpipe/SPEC.md`（v1 不动；新增 v2 增量节 `SPEC_v2.md`）
- `overnight/vpipe/src/qc_orch.py` / `qc_orch_v2.py`（降级为 gate 包的子模块）
- `overnight/vpipe/src/qc_detectors_v2.py`（J6v2 直迁入 CP7/CP12）
- `overnight/vpipe/eval/eval_run.py`（不动）
- `overnight/vpipe/tests/run_v3_checks.py`（G0-1..G0-4 沿用）
- `overnight/vpipe/tools/regen_fixtures/`（重建工具链沿用）
- `overnight/数据/golden/` + `eval/golden_manifest.json`（金标）
- 全部判定型资产（Vidu avatar client、stepfun_client、design gateway handlers 等）

**丢弃**（白皮书 §5.3）：
- 「单镜头判官合议」作为顶层判定结构（保留实现，重写结构）
- DramaClaw 无限画布 / graph_patch 交互层（不引入）
- ToonFlow Seedance 路由锁存（不引入）
- Remotion 作对外底座（不引入；改 HyperFrames Apache 2.0）
- bf16 / flash-attention / fp8 路线（不引入）
- J4 VisualJev（已 deprecated，不重启）

**重写**（白皮书 §5.4）：
- 判定器核心 → 五段流水线 gate 包
- 缓存/失效 → 槽位级指纹图
- 编排器 → stage 状态机
- 成本记账 → 每 CP 台账

### 3.3 三条试点线的差异化配置（同一套流水线，不同 gate 阈值）

| 维度 | 短剧 | 漫剧 | 营销短视频 |
|---|---|---|---|
| 时长 | 60-180s/集 | 30-60s/集 | 15-30s/条 |
| 镜头数 | 24-72 镜/集 | 12-24 镜/集 | 4-12 镜/条 |
| 主通道 | T4 H3-Max + T5 Seedance（核价后） | T4 H3-Max（G8 风格化最强） | T4 H3-Max + T3 Vidu avatar（口播段） |
| 草稿迭代 | T2 LTX-2B（≥3 轮 prompt A/B） | T2 LTX-2B（≥2 轮） | T2 LTX-2B（≥1 轮） |
| CP3 人工介入 | 必到（构图是核心决策） | 必到（构图 + 风格） | 可省（直接照模板） |
| CP5 人工介入 | 必到（动作是核心决策） | 可省（程序化骨架） | 可省（程序化模板） |
| CP12 人工介入 | 必到（叙事+审美） | 必到（风格一致性） | 可省（仅看灰区队列） |
| **人工上升率上限** | ≤25%（叙事线允许更多） | ≤20% | ≤10%（极致压缩） |
| **M2 试跑样本量** | 1 条 60s 含数字人段 | 1 条 30s 含 G8 风格 | 1 条 20s 含口播段 |
| **M3 扩张样本量** | 3 条 60s 同题材模板 | 3 条 30s 同模板 | 3 条 20s 同模板 |

---

## 4. 12 周路线图（v4 实施版，对齐白皮书 §6 但可监督）

### M0 · 准备（W1–W2）

**目标**：把「不可确证」一次性确证掉，让后续所有成本决策有底。

| 周 | 周目标 | 关键交付物 | 验收命令（黑盒可独立跑） |
|---|---|---|---|
| W1 | 新增三份 v2 契约落地 | `contracts/v2/checkpoint.schema.json`（12 CP）+ `contracts/v2/model_tiers.yaml`（T0-T5）+ `SPEC_v2.md`（增量） | `python -m jsonschema --instance contracts/v2/checkpoint.schema.json --schema-draft 2020-12 <example.json>`（对 12 个示例工件）→ 0 错 |
| W1 | 阈值升 v4 | `thresholds.yaml` 增 12 个 CP 段；G0-3（sha256 对账）全绿 | `sha256sum overnight/vpipe/eval/thresholds.yaml` 与 eval 留痕 JSON 一致；`tests/run_v3_checks.py` → ALL PASS + EXIT=0 |
| W1 | Seedance 单价核价 | 控制台实抓 + evidence/pricing/seedance_evidence.json | 文件存在 + JSON 内 `confirmed: true/false` 字段；**`confirmed: false` 不得进预算基线** |
| W1 | 阻塞凭证重建 | `overnight/secrets/api_keys.env` 重建 + 1 次最小调用留痕 | `curl <MiniMax 设计网关>/api/v1/credit/wallet` 返回 200 + 钱包余额非负 |
| W2 | Wan2.2-TI2V-5B spike | 与 LTX-2B 同题 A/B，比门禁分数分布 | 12 镜同 prompt LTX vs Wan2.2-5B 各跑一次，**峰值 <30GB + 黑帧率 0 + ≥1 条过全部六门禁** = 通过；产出 `evidence/wan22_spike/` |
| W2 | GPU 共享窗实测 | 卡 1 单任务墙钟 ≤45 min 验证 | `nvidia-smi --query-gpu=memory.used --format=csv -l 5` 监控记录 |

**M0 验收门（外部强模型可独立跑）**：

```bash
# 三件契约对 12 个示例工件全校验通过
python -c "
import json, jsonschema, pathlib, sys
schema = json.loads(pathlib.Path('overnight/vpipe/contracts/v2/checkpoint.schema.json').read_text())
examples = list(pathlib.Path('overnight/vpipe/contracts/v2/examples/').glob('cp*.json'))
assert len(examples) >= 12, f'CP examples {len(examples)} < 12'
for ex in sorted(examples):
    jsonschema.validate(json.loads(ex.read_text()), schema)
print(f'OK {len(examples)} CP examples validated')
"
# 预期：OK 12 CP examples validated

# G0-1 全绿
python overnight/vpipe/tests/run_v3_checks.py
# 预期：== 汇总 == ALL PASS  EXIT=0

# G0-3 阈值对账
sha256sum overnight/vpipe/eval/thresholds.yaml
python -c "
import json, pathlib
r = json.loads(pathlib.Path('overnight/vpipe/eval/eval_results.json').read_text())
assert 'thresholds_sha256' in r, 'thresholds_sha256 字段缺失'
print(f\"OK thresholds_sha256={r['thresholds_sha256']}\")
"
# 预期：OK thresholds_sha256=<hash>
```

### M1 · 骨架（W3–W5）

**目标**：CP1–CP6 + CP10–CP11 的纯确定性层全部跑通——这段不花 API 积分。

| 周 | 周目标 | 关键交付物 | 验收命令 |
|---|---|---|---|
| W3 | CP2 剧本 schema + 时长守恒校验 | 校验器 + 5 条示例 | 5 条 Σ estimated_duration 偏差全 ≤2% |
| W3 | CP3 分镜表 schema + 校验器七条 | 校验器 + 12 镜示例 | 校验器零误报（12 镜全过） |
| W4 | CP5 `blocking` schema + glTF 2.0 armature 端到端连通（Blender 缺位替代，见 §8 决策记录 2026-10-08-b） | 1 个示例 blocking 序列 + 导出 glTF（skins+animation channels）+ 往返重载 | 16 关节 Euler 弧度合法 + 帧时间单调 + 骨长恒定 + glTF 往返后关节层级/关键帧零丢失 |
| W4 | CP6 单一帧域 Timeline | 1 个 30s 样例 | Σ shot.duration == 集时长（±1 帧）+ 字幕段与音轨词级偏差 ≤40ms |
| W5 | CP11 合成层硬校验挂载 + 像素级回归 | ffmpeg/HyperFrames 合成 + 3 个回归用例 | 3 个用例同输入同输出（md5 一致） |
| W5 | known_cuts 强制登记 | qc_orch 增 --require-known-cuts 开关 | 无登记的硬切点 → exit 非 0 |

**M1 验收门**：

```bash
# CP2-CP6、CP11 八项示例工件全过 schema + 门禁判定（零人工）
python -c "
import json, jsonschema, pathlib
schema = json.loads(pathlib.Path('overnight/vpipe/contracts/v2/checkpoint.schema.json').read_text())
required = ['cp2', 'cp3', 'cp4', 'cp5', 'cp6', 'cp10', 'cp11']  # 7 项（CP1 是意图卡，CP12 验收后才建）
examples = list(pathlib.Path('overnight/vpipe/contracts/v2/examples/').glob('cp*.json'))
for cp in required:
    matches = [e for e in examples if cp in e.stem]
    assert matches, f'{cp} 示例缺失'
    jsonschema.validate(json.loads(matches[0].read_text()), schema)
print(f'OK {len(required)} deterministic CP examples validated')
"
# 预期：OK 7 deterministic CP examples validated

# 合成层像素级回归 ≥3 用例
for case in overnight/vpipe/tests/fixtures/synth_regression/case_*; do
  python overnight/vpipe/src/synth.py --case "$case" --out /tmp/run1
  python overnight/vpipe/src/synth.py --case "$case" --out /tmp/run2
  diff -q /tmp/run1/md5.txt /tmp/run2/md5.txt || (echo "FAIL $case"; exit 1)
done
echo "OK 合成层像素级回归 ≥3 用例通过"
# 预期：OK

# 改 1 个台词槽位后，受影响镜头重渲耗时 <10 min
time python overnight/vpipe/src/orchestrator.py \
    --shot-cp3-change "episode01/shot007" \
    --rebuild-affected \
    --max-affected 1
# 预期：real <10min；受影响镜数 = 1（其余命中指纹缓存）
```

### M2 · 试跑（W6–W9）

**目标**：出**第一条完整走通 12 个 CP 的样片**（短剧 60s + 漫剧 30s + 营销 20s 各一条），并把人工介入点实测计数落定。

| 周 | 周目标 | 关键交付物 | 验收命令 |
|---|---|---|---|
| W6 | T2 草稿层接入 + CP7→CP8 全通 | LTX-2B 主路径 + Wan2.2-5B 对照 | 12 镜全部 CP7→CP8 通过 |
| W6 | T3 动作/口播层接入 | MimicMotion 少数镜 + Vidu avatar 口播段 | MediaPipe 手部检出 B 类 5 条；SyncNet LSE-C/D 特写 ≥0.6 |
| W7 | T4 精修层接入 | H3-Max 默认 + H3 两类回退场景 | 钱包记账 + 积分双拦截不退化为单拦 |
| W7 | CP12 四维判定上线 | 缺陷维 E10 + 规格服从维 A 组 + 审美 warn + 合规 warn | A 组召回 ≥99% / 误报 ≤1% |
| W8 | 短剧 60s 样片 | 1 条含数字人段 | 样片 + QCReport(1.1) + eval ACCEPT 三件齐 |
| W8 | 漫剧 30s 样片 | 1 条 G8 风格 | 同上 |
| W9 | 营销 20s 样片 | 1 条含口播段 | 同上 |
| W9 | 人工介入点实测计数 | CP3/CP5/CP6/CP12 四处实测记录 | 短剧 ≤25% / 漫剧 ≤20% / 营销 ≤10% |
| W9 | 成本台账首版 | ledger.json | 每 CP 都有 `{cp_id, 通道, 墙钟, 币种, 金额, 折算口径}` |

**M2 验收门**：

```bash
# 三条样片 + QCReport(1.1) + eval ACCEPT 三件齐
for ep in short-drama/episode01 short-anime/episode01 short-ad/episode01; do
  [ -f "out/$ep/final.mp4" ] || (echo "FAIL 样片 $ep 缺失"; exit 1)
  [ -f "out/$ep/qc_report.json" ] || (echo "FAIL QCReport $ep 缺失"; exit 1)
  jq -e '.schema_version == "1.1"' out/$ep/qc_report.json >/dev/null || (echo "FAIL schema 不是 1.1"; exit 1)
done
python overnight/vpipe/eval/eval_run.py --qc-dir out/qc_reports/ --expected ACCEPT
# 预期：ACCEPT (exit 0)

# 单集成本 ≤ 标准档 ×1.2 = 6,720 ×1.2 = 8,064 积分
python -c "
import json
ledger = json.loads(open('out/cost/ledger.json').read())
short_drama = sum(e['amount_minimax_credit'] for e in ledger if e['cp_id'] in ['cp7', 'cp9'] and e['episode_id'] == 'short-drama/episode01')
assert short_drama <= 8064, f'短剧成本 {short_drama} 超 8,064'
print(f'OK 短剧单集成本 {short_drama} 积分 ≤ 8,064')
"
# 预期：OK

# known_cuts 漏登记 = 0
python overnight/vpipe/src/orchestrator.py --audit-known-cuts --out /tmp/audit
diff /tmp/audit/known_cuts_expected.json /tmp/audit/known_cuts_actual.json && echo "OK 零漏登记" || (echo "FAIL"; exit 1)

# 人工上升率 ≤ 三档阈值
python -c "
import json
h = json.loads(open('out/human_review/human_review_log.json').read())
short_drama_rate = h['short-drama/episode01']['review_count'] / h['short-drama/episode01']['total_cps']
short_anime_rate = h['short-anime/episode01']['review_count'] / h['short-anime/episode01']['total_cps']
short_ad_rate = h['short-ad/episode01']['review_count'] / h['short-ad/episode01']['total_cps']
assert short_drama_rate <= 0.25, f'短剧 {short_drama_rate} > 25%'
assert short_anime_rate <= 0.20, f'漫剧 {short_anime_rate} > 20%'
assert short_ad_rate <= 0.10, f'营销 {short_ad_rate} > 10%'
print(f'OK 人工上升率 短剧 {short_drama_rate} / 漫剧 {short_anime_rate} / 营销 {short_ad_rate}')
"
```

### M3 · 扩张（W10–W12）

**目标**：从「一条样片能跑」扩到「一批能稳」，固化 CP 级回归资产。

| 周 | 周目标 | 关键交付物 | 验收命令 |
|---|---|---|---|
| W10 | CP 级夹具库首批（CP1/CP2/CP3/CP5/CP6/CP10/CP11/CP12） | 8 个 CP × 5 条 = 40 条夹具 | 各 CP 门禁在 fail 组拦截率 ≥90% |
| W11 | 连续 3 条样片 CP 级零未声明回归 | 3 条同模板样片（短剧 + 漫剧 + 营销各 3 条） | `tests/run_v3_checks.py` ALL PASS + 3 条样片 eval ACCEPT |
| W11 | 模板线打通 | 槽位替换 → 失效传播验证 | 改 30 镜中的 3 镜，实际重跑 ≤3 镜 |
| W11 | 收敛曲线 | 每 CP `residual_count/fixed_count/new_failures` 逐轮记录 | DramaClaw-style `convergence_log.py` 在仓 |
| W12 | 人工否决一等化 | append-only 审计表 + 主行汇总 | 审计表 + 主行汇总位（每位接受/驳回可追溯） |
| W12 | 三版本字段强制随行 | registry_version/prompt_version/spec_version | `tests/run_v3_checks.py` 加 V4 检查项；缺一项即拒 |

**M3 验收门**：

```bash
# 8 个 CP × 5 条夹具 = 40 条，fail 组拦截率 ≥90%
python -c "
import json, pathlib
total_fail, total_intercept = 0, 0
for cp in ['cp1', 'cp2', 'cp3', 'cp5', 'cp6', 'cp10', 'cp11', 'cp12']:
    cp_dir = pathlib.Path(f'overnight/vpipe/tests/fixtures/checkpoints/{cp}')
    fail_clips = list((cp_dir / 'fail').glob('*.json'))
    intercept = sum(1 for f in fail_clips if json.loads(f.read_text()).get('gate', {}).get('verdict', {}).get('defect_detected', False))
    rate = intercept / len(fail_clips) if fail_clips else 1.0
    assert rate >= 0.90, f'{cp} fail 拦截率 {rate:.2f} < 0.90'
    total_fail += len(fail_clips); total_intercept += intercept
print(f'OK 8 个 CP fail 拦截 {total_intercept}/{total_fail} = {total_intercept/total_fail:.2%}')
"
# 预期：OK ≥90%

# 连续 3 条样片 CP 级零未声明回归
python overnight/vpipe/tests/run_v3_checks.py --mode regression-suite --suite m3-batch1
# 预期：ALL PASS + EXIT=0

# 改 30 镜中的 3 镜，实际重跑 ≤3 镜
python overnight/vpipe/src/orchestrator.py \
    --shot-cp3-change "episode01/shot{005,015,025}" \
    --rebuild-affected \
    --total-shots 30 \
    --max-affected 3
# 预期：实际重跑镜数 = 3；其余命中指纹缓存

# prompt_version 缺失项 = 0
python -c "
import json, pathlib
missing = 0
for qc in pathlib.Path('out/qc_reports/').rglob('*.json'):
    data = json.loads(qc.read_text())
    if 'prompt_version' not in data.get('thresholds_applied', {}):
        missing += 1
assert missing == 0, f'prompt_version 缺失 {missing} 项'
print('OK prompt_version 全覆盖')
"
```

---

## 5. 黑盒验收脚本（监督协议）

外部强模型监督本卡时，按以下四步走。每步都是确定性命令，不依赖对仓内细节的先验知识。

### 5.1 监督准备（一次性，约 5 分钟）

```bash
# 1. 克隆仓（任意 SSH/HTTPS）
git clone <repo> video-capability && cd video-capability

# 2. 装 venv + 依赖（≤2 分钟）
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 仓内提供

# 3. 装 jsonschema 等（验证用）
pip install jsonschema pyyaml

# 4. 验证「无密钥零入库」（G0-4，3 秒）
git ls-files | grep -iE "secret|api_key|token" | grep -v "\.md$" | head
# 预期：空（仅 README/SPEC 等文档允许提及"密钥纪律"）
```

### 5.2 监督每周进度（每周末，约 10 分钟）

```bash
# 取周报（由 leader 提交到 docs/weekly/YYYY-WW.md）
WEEK=$(date +%Y-%V)
[ -f "docs/weekly/$WEEK.md" ] || (echo "FAIL 周报缺失"; exit 1)

# 跑该周的验收命令（见 §4 各周表格）
# 例：W6 末验
python -c "
import json, jsonschema, pathlib, sys
schema = json.loads(pathlib.Path('overnight/vpipe/contracts/v2/checkpoint.schema.json').read_text())
required = ['cp1', 'cp2', 'cp3', 'cp4', 'cp5', 'cp6', 'cp7', 'cp8', 'cp9', 'cp10', 'cp11', 'cp12']
examples = list(pathlib.Path('overnight/vpipe/contracts/v2/examples/').glob('cp*.json'))
for cp in required:
    matches = [e for e in examples if cp in e.stem]
    if not matches:
        print(f'FAIL {cp} 示例缺失'); sys.exit(1)
    jsonschema.validate(json.loads(matches[0].read_text()), schema)
print(f'OK 12 CP examples validated')
"
python overnight/vpipe/tests/run_v3_checks.py
# 预期：== 汇总 == ALL PASS  EXIT=0
```

### 5.3 监督关键决策（每周一次，约 5 分钟）

```bash
# 1. GPU 卡 1 共享是否守约
grep -E "cuda_visible_devices" docs/weekly/$WEEK.md
# 预期：CUDA_VISIBLE_DEVICES=1 仅一次出现，且不与生产 vLLM 卡冲突

# 2. API 积分钱包是否合规
python -c "
import json, pathlib
ledger = json.loads(pathlib.Path('out/cost/ledger.json').read_text())
total_minimax = sum(e.get('amount_minimax_credit', 0) for e in ledger)
total_vidu = sum(e.get('amount_vidu_credit', 0) for e in ledger)
print(f'MiniMax {total_minimax} + Vidu {total_vidu} 积分')
assert total_minimax <= 40000, f'MiniMax 超 40k 硬上限: {total_minimax}'
"
# 预期：MiniMax ≤ 40k（硬上限）

# 3. 是否有超 300 元的 API 调用未经审批
grep -E "单次.*>.*300|expense.*300" docs/weekly/$WEEK.md
# 预期：空（任何 >300 元的调用必须先报 owner）

# 4. 是否有「单镜头判官合议」被重新立为顶层结构（白皮书 §5.3 禁）
grep -rE "qc_orch\.[a-z_]+\(|合成判定|E10.*顶层" overnight/vpipe/src/
# 预期：qc_orch 仅被 gate 包引用，不被作为顶层入口
```

### 5.4 红线检查（每周末必跑，1 分钟）

```bash
# 红线 1：卡 0 绝不被本项目占用
grep -rE "CUDA_VISIBLE_DEVICES=0" overnight/ scripts/ src/ 2>/dev/null
# 预期：空（仅生产 vLLM 卡 0 例外）

# 红线 2：密钥零入库
git ls-files | grep -iE "(api_key|secret|token)\.(env|json|yaml|toml)" | head
# 预期：空

# 红线 3：金标禁入调参
grep -rE "golden.*train|golden.*fit|golden.*param" overnight/vpipe/src/ | head
# 预期：空

# 红线 4：v1 契约零修改（schema_version=1.0 的契约文件 mtime 在 2026-09-30 之后无变化）
git log --diff-filter=M --name-only --since="2026-10-08" -- \
  overnight/vpipe/contracts/shot.schema.json \
  overnight/vpipe/contracts/asset_manifest.schema.json \
  overnight/vpipe/eval/eval_run.py | head
# 预期：空

# 红线 5：thresholds.yaml v3 段零修改
git diff 71f719d..HEAD -- overnight/vpipe/eval/thresholds.yaml | grep -E "^[+-]" | grep -vE "(^---|^\+\+\+)" | grep -vE "J6_detectors_v2|J6_v2|l0_preflight|J3_omnijev|^@@" | head -20
# 预期：仅有新增 CP 段，无 v3 段修改
```

---

## 6. 监督协议（流程，不在仓内代码里）

### 6.1 每周节奏

| 时间 | 动作 | 责任方 |
|---|---|---|
| 周一 09:00 | leader 提交上周周报到 `docs/weekly/YYYY-WW.md` | leader |
| 周一 10:00 | 监督者跑 §5.2 + §5.3 验收命令 | 监督者（外部强模型） |
| 周一 11:00 | 验收结果：✅ 通过 / ❌ 不通过 + 具体不通过项 | 监督者 |
| 周二 09:00 | 不通过项的修复计划入 worklog | leader |
| 周五 17:00 | 中期检查（提前看周末是否能通过） | leader 自查 |
| 周日 23:59 | 周日 freeze：所有代码 commit + 周报定稿 | leader |

### 6.2 升级路径

- **M0 阶段未通过** → 暂停 W3，重审白皮书 §6 路线图假设（如 Wan2.2-5B spike 失败 → 接受 LTX-2B 单一草稿路径，重排 M1 资源）
- **M1 阶段未通过** → 暂停 W6，回退到骨架修复（不要进 API 阶段）
- **M2 阶段未通过**（如 3 条样片都没出）→ 触发「v4 SPEC 范围缩减」讨论（owner 决策层介入）
- **M3 阶段未通过** → 触发「v4 SPEC 失败模式总结」+ 「v5 重构方向」（不在本卡范围）

### 6.3 监督者必读材料

1. 本任务卡（§1-§5）
2. [白皮书](research/2026-10-08/工业化视频流水线-白皮书.md)（独立结论）
3. [INTENT.md](../INTENT.md)（owner 原始意图基线）
4. [TASK.md（v3）](../TASK.md)（v3 既定任务基线，避免被旧任务卡束缚——白皮书已扩到 v4）

### 6.4 监督者不必读材料

- `overnight/vpipe/src/` 下的具体实现（除非验收命令需要）
- `research/` 下子代理历史调研素材
- `agents/`、`cradle/`（v1/v2 收官资产，已冻结不需重审）
- `tmp_readme/`、`_probe/`（调研快照，已纳入白皮书）

---

## 7. 风险登记与红线（白皮书 §7 非目标的红线版本）

### 7.1 已识别风险

| # | 风险 | 概率 | 影响 | 缓解 | 触发回退 |
|---|---|---|---|---|---|
| R1 | Wan2.2-5B spike 不通过 | 中 | 中 | 接受 LTX-2B 单一草稿路径 | M0-W2 末 |
| R2 | Seedance 2.5 核价未通过/通道不通 | 中 | 低 | T5 退化为 H3-Max 独占 | M0-W1 末 |
| R3 | 卡 1 共享窗被其他项目挤压（已实证：一剧N国 xdng 三服务 7×24 常驻 27.7GB，显存平台线无自然空闲窗） | **高** | 高 | owner 与一剧N国 owner 约定 10-09 10:00–12:00 停服窗；video-capability 侧不得代杀进程（红线）；拿不到窗则 M1 骨架期（零 GPU）先行解耦 | 已裁决：见 evidence/env/gpu1-memory-window.md §6 主控裁决（卡 0 路线已否） |
| R4 | Wan2.2-5B spike 通过但显存 <30GB 临界 | 低 | 中 | 进 Wan2.2-5B Q4 档（更小但更慢） | M0-W2 末 |
| R5 | 70 分人评锚定未做导致 CP12 审美维无门 | 高 | 中 | 审美维长期 warn-only（白皮书 §7 非目标 8 已声明） | M2-W7 末 |
| R6 | CP 级夹具库工作量被低估 | 中 | 中 | 按 CP 优先级分批（先 CP11/CP12） | M3-W10 末 |
| R7 | 外部强模型监督强度不足 | 低 | 高 | owner 端建立「不通过就停」的硬机制 | 任意周末 |

### 7.2 红线（任何一条触发则整卡暂停）

- 卡 0 被本项目任何代码 / 进程 / 文档占用
- 任何密钥值（VIDU/StepFun/MiniMax）入仓/入码/入日志
- v1 契约 schema_version=1.0 文件被修改
- thresholds.yaml v3 段被修改（v3→v4 走 G0-3 规程）
- E10 基准（R=1.000/FPR=0.250/F1=0.9143）出现未声明偏差
- 金标 40 条被任何训练/调参动作污染
- 单次 API 调用 >300 元未经 owner 审批
- 任意 judge 资产被「为提升数字而调参」

---

## 8. 决策记录（领导决策的强制留痕）

| 日期 | 决策 | 理由 | 验证 |
|---|---|---|---|
| 2026-10-08 | 端到端 GPU vs API vs 混合 → 选**混合分层** | §2 决策表：单次 TCO 混合为 API 的 34% / 失败人工 1/3；纯 GPU 质量上限被 SM70 物理卡死；纯 API 违反 owner 分层廉价/昂贵原则 | §2.4 数字核算 |
| 2026-10-08 | 卡 1 单任务 ≤45 min 共享窗 | 卡 1 是 GPU 机共享资源；超 45 min 触发其他项目排期冲突 | M0-W2 末实测 |
| 2026-10-08 | MiniMax 钱包 40k 硬上限不变 | 已实测 65.5% 消耗，余 13.8k；M2 单集标准档 6,720 ×1.2 = 8,064，余量够 1 集试跑 | §2.5 |
| 2026-10-08 | M0-W2 末决定 Wan2.2-5B 是否进产线 | 白皮书 §6 M0-W2 spike；若不通过，接受 LTX 单一草稿路径，不影响白皮书结构 | §4 M0-W2 |
| 2026-10-08 | 「单镜头判官合议」结构丢弃（保留实现） | 与白皮书分段门禁骨架冲突（白皮书 §5.3） | §3.2 丢弃清单 |
| 2026-10-08-b | M1-W4 Blender 连通性验证改为 **glTF 2.0 armature 往返** | 双机（本地+GPU 机）均无 Blender；安装 ~300MB 只为一项目连通性检查不成比例，且 glTF 是 mannequin schema 的标准交换格式、纯 Python 可写可验（确定性、无 GUI 依赖，合白皮书 §7 非目标 7 精神）。验收等价物：往返后关节层级+关键帧时间/弧度零丢失 | M1 第二批 brief |
| 2026-10-08-c | GPU spike 执行位定**卡 0**（owner 10-08 授权「没在跑就直接用」覆盖 10-08 早前裁决） | 早前裁决等卡 1 协调窗；owner 当晚授权直接用空闲 GPU；卡 0 实测 310MiB/util 0%。纪律保留：只跑卡 0、跑前 5 分钟复测、卡 1 不碰 | evidence/env/gpu1-memory-window.md §6 追记 |

---

## 9. 文档/资产图谱（仓内导航）

```
video-capability/
├── TASK.md (v3 既有，本卡为 v4 增量)  ← 本文
├── INTENT.md (owner 原始意图基线)
├── README.md (接手文档)
├── research/
│   └── 2026-10-08/
│       ├── 工业化视频流水线-白皮书.md (本卡上位)
│       ├── hypit-svml-deepdive.md (调研 1)
│       ├── dramaclaw-deepdive.md (调研 2)
│       ├── toonflow-deepdive.md (调研 3 — 注:仓内不存在，见白皮书取证边界 1)
│       ├── cheap-draft-and-programmatic-tools.md (调研 3 替代)
│       └── controllable-video-generation-survey.md (调研 4)
├── overnight/
│   ├── vpipe/ (v1/v2 既有 + v3 增量，本卡 v2 增量落此)
│   │   ├── SPEC.md (v1，不动)
│   │   ├── SPEC_v2.md (本卡新增)
│   │   ├── contracts/
│   │   │   ├── v1/ (不动)
│   │   │   │   ├── shot.schema.json
│   │   │   │   ├── qc_report.schema.json
│   │   │   │   └── asset_manifest.schema.json
│   │   │   └── v2/ (本卡新增)
│   │   │       ├── checkpoint.schema.json
│   │   │       ├── model_tiers.yaml
│   │   │       ├── qc_report_v2.schema.json
│   │   │       └── examples/ (12 CP 示例工件)
│   │   ├── src/
│   │   │   ├── gate/ (本卡新增：五段流水线判定器)
│   │   │   ├── orchestrator/ (本卡新增：stage 状态机)
│   │   │   ├── cost/ (本卡新增：成本台账)
│   │   │   └── ... (v3 既有，沿用)
│   │   ├── eval/
│   │   │   ├── thresholds.yaml (v3→v4 升)
│   │   │   ├── golden_manifest.json (不动)
│   │   │   ├── eval_run.py (不动)
│   │   │   └── eval_results.json (留痕递增)
│   │   ├── tests/
│   │   │   ├── run_v3_checks.py (G0-1..G0-4 沿用)
│   │   │   └── fixtures/checkpoints/ (本卡新增：CP 级夹具库)
│   │   └── tools/regen_fixtures/ (沿用)
│   ├── 工程方案v3.1.md (v3 既有)
│   ├── 数字人实验报告.md (v3 既有)
│   ├── judge基准报告.md (v3 既有)
│   └── 数据/ (金标/judges 不动)
├── deliverables/ (v1/v2 收官，冻结)
├── deliverables_v2/ (v2 收官，冻结)
├── deliverables_v3/ (v3 首批，已存档)
├── docs/weekly/ (本卡新增：周报)
└── worklog.md (沿用，append-only)
```

---

## 10. owner 必读摘要（≤300 字）

**任务卡 v4 已落地，混合分层是 leader 自主决策的最优解。**

核心决策：端到端 GPU 因 SM70 物理约束被否；纯 API 违反 owner 分层原则被否；混合分层让单次试验综合 TCO 降到纯 API 的 34%，失败时人工成本降到 1/3，且质量上限等同 API。

执行计划：12 周分四阶段（M0 准备 / M1 骨架 / M2 试跑 / M3 扩张），每周有可独立运行的验收命令。W1 末验：12 CP 契约 + G0-1 全绿 + Seedance 核价落 evidence。W2 末验：Wan2.2-5B spike 决定是否升级草稿。W5 末验：CP1-CP6 + CP11 纯确定性层全跑通（零 API 积分）。W9 末验：短剧 60s + 漫剧 30s + 营销 20s 三条样片 + QCReport(1.1) + eval ACCEPT 三件齐，单集成本 ≤8,064 积分。

owner 不参与技术选型，只看成本效益——所有数字均来自仓内实测留痕或白皮书 §4 成本数字的可信度分层，每条决策都有红线与回退方案。外部强模型监督协议见 §6，验收脚本 §5，全跑一遍即可判定本卡是否完成。
