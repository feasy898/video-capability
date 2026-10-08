# vpipe SPEC v2 — 工业化视频流水线（12 CP 谱）增量规范（v2.0，2026-10-08 首版）

> 定位：本文是 `SPEC.md`（v1.0，2026-09-30 冻结）的 **v2 增量规范**，不是替代。
> 上位基座：[`research/2026-10-08/工业化视频流水线-白皮书.md`](../../research/2026-10-08/工业化视频流水线-白皮书.md)
> （生产函数 + §3 检查点谱 12 CP + §4 模型分层 T0–T5 + §5 利旧盘点 + §8 整合方式）；
> 任务契约：[`TASK_v4.md`](../../TASK_v4.md)（§3.1 新增清单 + §4 M0 周表）。
> 本文只写增量。v1 的契约、模块、eval 资产、验收基线（E10：R=1.000 / FPR=0.250 /
> F1=0.9143）一字不改；v1 SPEC 的重生成规程（SPEC.md §6）继续有效。

---

## 0. 纪律与 v2 目录

纪律（承接 v1 三条并加两条）：

1. **v1 契约零修改**：`contracts/*.schema.json`（v1 三份）、`SPEC.md`、`eval/thresholds.yaml`
   v3 段、`eval/eval_run.py`、`tests/run_v3_checks.py` 全部只读（TASK_v4 §3.2「直接利旧」）。
   v2 的全部新增走**并行目录 + 文件级版本判定**：工件以 `schema_version` 字段值区分
   （`"1.0"/"1.1"` = v1，`"2.0"` = v2），防错放目录；v1 引擎读到 2.0 即 fail-fast 拒收。
2. **v2 并行不混线**：v2 模块（gate 包 / orchestrator / cost 包）互不 import，只靠契约
   JSON/YAML 通信（SPEC.md §0 纪律 2 继承）。
3. **判定数值单点**：一切判定数值只存 `eval/thresholds.yaml`（v4 起增 CP 级段，v3 段一字
   不改）；v2 契约与模型分层表内**零门禁数值**，只存 `params_ref` 引用（SPEC.md §0 纪律 3
   的 v2 形态）。
4. **通道枚举单点**：`engine.channel` 枚举唯一来源 = `contracts/v2/model_tiers.yaml`
   （白皮书 §8 铁律 2）；模型名字不进意图层（VDL not-pattern 实测拒 "Wan2.1"）。
5. **失败是数据**：CP 工件 `status=rejected` 不删除不静默；回退目标 CP 由白皮书 §3 各 CP
   「失败回退」行定义，写进 stage 状态机转移表，不靠异常处理（白皮书 §5.4 编排器重写）。

```
vpipe/
├── SPEC.md                          ← v1（冻结不动）
├── SPEC_v2.md                       ← 本文
├── contracts/
│   ├── *.schema.json                ← v1 三份（冻结不动）
│   └── v2/
│       ├── vdl_package.schema.json  ← VDL v2 第一批（既有，VDL_v2_草案.md §7.1）
│       ├── shot_v2.schema.json      ← VDL v2 第一批（既有，v1 纯超集）
│       ├── checkpoint.schema.json   ← ★ 本文 §1：12 CP 工件契约（M0-W1 新增）
│       ├── model_tiers.yaml         ← ★ 本文 §2：T0–T5 分层表 / channel 枚举唯一来源（M0-W1 新增）
│       ├── qc_report_v2.schema.json ← 计划位：增 checkpoint{cp_id,artifact_ref} 与 episode_verdict
│       │                              （P1，M2 落地，TASK_v4 §3.1；未落地前 v1/v2 clip 级
│       │                                报告按 qc_report.schema.json 1.0/1.1 继续合法）
│       └── examples/                ← ★ cp1.json … cp12.json：12 个示例工件（M0-W1 新增，
│                                       全部过 checkpoint.schema 校验，验收命令见 §4）
├── src/
│   ├── gate/                        ← 计划位（P1，M1–M2）：五段流水线判定器，按 CP 分派门禁类型
│   ├── orchestrator/                ← 计划位（P1，M1）：stage 状态机（pending/running/gated/passed/rejected）
│   ├── cost/                        ← 计划位（P1，M2）：每 CP 成本台账 {cp_id,通道,墙钟,币种,金额,折算口径}
│   └── qc_orch*.py 等               ← v1/v3 既有（与 v1 的关系见 §3）
└── eval/thresholds.yaml             ← v3 现行；v4 升版时增 CP 级段（P0，M0-W2，走 G0-3 规程）
```

---

## 1. checkpoint.schema.json — 12 CP 工件契约表

结构：顶层 `oneOf` 按 `cp_id` 分派到 12 个自包含分支；公共头字段
（`schema_version="2.0"` / `cp_id` / `artifact_type` / `fingerprint`(sha256) /
`produced_by` / `produced_at` / `upstream_refs[]` / `status` 五态 / `gate{type,
params_ref}` / 可选 `aux_gates[]`）+ CP 专属 `payload`。门禁类型词表：
`schema / rule / hard_verify / judge_rank / judge_absolute / human / composite`；
一切判定数值经 `gate.params_ref` 引用 `thresholds.yaml` 键路径（v4 CP 级段命名
`cpN.gate.*`；既有段直接引用，如 `l0_preflight.*`、`J6_detectors_v2.*`）。

| CP | 工件（artifact_type） | 生产者 → 消费者 | payload 必填要点 | 门禁类型（主门） |
|---|---|---|---|---|
| CP1 意图单 | intent_card | agent.director / human.owner → cp2 + 全链回读 | theme、selling_point、forbidden_zones[]（≥1，每条映射已注册缺陷码）、deliverable{pixel_map, encode_contract}、budget.credit_cap_total(≥1) | rule（禁区注册表可查）；禁区无缺陷码 → human 裁决（全链唯一死胡同） |
| CP2 剧本 | script | agent.writer → human.owner（异常才上升）→ cp3 | narration_segments[]（narration/visual 一对一、estimated_duration_s、tts_safe、cast/props_refs）、cast[]、props[]、Σ时长 | rule（时长偏差、台词/镜头比、TTS 字符集、悬空引用；`cp2.gate.duration_dev_max`） |
| CP3 分镜表 | storyboard | agent.boardArtist → human.owner（设计内介入①）→ cp4/cp5 | shots[]（五要素 shot_scale/move/duration_s/action/refs、word_anchors、channel_hint）、source_script_fingerprint | rule（五要素齐全、单段上限、词锚定、循环引用、镜头数一致；`cp3.gate.max_shot_duration_s`） |
| CP4 关键帧 | keyframes | agent.keyframePainter → human.owner（圈改）→ cp7/cp9 | frames[]（asset、pixel 实测、black_frame_ratio、expected/detected_identities、identity_cosine 逐身份）、small_text_policy（小字一律后期字牌） | hard_verify（零 VLM：在场检测、ArcFace 余弦、黑图率；`cp4.gate.identity_cosine_min`） |
| CP5 动作脚本 | blocking | agent.blockingCompiler → human.owner（设计内介入②）→ T3 动作层 | sequences[]（16 关节穷举、rotation-only 骨长恒定、tracks[{joint,frames[{time,rotation}]}]、speech_mode、frame_count、known_cuts） | rule（关节合法、帧时间单调、帧数上限、口型层路径；`cp5.gate.pose_frame_max`） |
| CP6 时间线 | timeline | orchestrator.cp6_timeline_builder → human.owner（设计内介入③）→ cp7/cp9/cp10/cp11 全链复用 | fps、total_frames、shots[{start_frame,duration_frames}]、subtitle_segments、subtitle_align_max_dev_ms、sound_lead_in_frames、rhythm_segments、duration_conservation_dev_frames | rule（Σ==集时长 ±1 帧、词级对齐阈、循环引用；`cp6.gate.duration_conservation_frames`） |
| CP7 草稿视频 | draft_clip | gen_local → cp8 择优器 | shot_id、channel、asset、pixel/fps、declared/actual_duration_s、black_mono_ratio、nan_detected、seed、l0_preflight | hard_verify（L0 预检，阈值沿既有段 `l0_preflight.*`，拒收 exit 4；草稿层不做 aesthetic 判定） |
| CP8 择优 | selection | agent.selector → cp9 | candidates[]（draft_fingerprint、hard_verify 向量、judge_scores）、top1_candidate_id、pareto_dominant、veto_defects[] | composite（① 相对线 judge_rank 只排序；② Pareto 支配 + A/B 否决一票出局；`cp8.gate.pareto_rule`） |
| CP9 终稿渲染 | final_render | gen_api → cp10/cp11 | channel、asset、resolution(≥768P)、repro_level、submit_params_fingerprint、credit_spent/credit_cap_per_shot、draft_task_id(Seedance) | rule（参数级复现留痕 + 单镜成本闸门 exit 3；`cp9.gate.credit_cap_per_shot`） |
| CP10 字幕音轨 | subtitle_audio | tts.py + 字幕链 → human.owner（听音色）→ cp11 | tts{channel, voice_id, gender_match_confirmed}、subtitles{ass, verbatim, cer 双口径}、loudness_lufs、duration_conservation | composite（ffprobe 守恒 + ASS 零错字 + whisper CER + 响度；`cp10.gate.cer_max`） |
| CP11 合成 | composite | synth → cp12 | master_asset、container/codec 三元组、duration_s、master_shot_segments vs storyboard_shot_count、known_cuts[]、all_cuts_registered | hard_verify（ffprobe 全项 + 切镜数 + 切点全登记，容差沿 `J6_detectors_v2.known_cuts_tol_s`） |
| CP12 质检成片 | qc_master | gate 包 → human.owner（设计内介入④：灰区队列 + D 类 + 签字）→ 交付 | master_fingerprint、episode_verdict{score=0.7×mean+0.3×worst, verdict}、gate_groups{a/b/c/d}、human_escalation_rate、shot_qc_refs[]、routed_reworks[] | composite（成片绝对门 judge_absolute + 四组 + 人工上升率；`cp12.gate.a_group_recall_min` 等） |

设计内人工介入点：**CP1 / CP3 / CP5 / CP6 / CP12**（白皮书 §3 谱首段；M2 实测计数
≤2 次，TASK_v4 §4）。其余 CP 默认零人工，不许因「保险」加人——加人必须回答补的是
哪个已知失效模式（白皮书 §3 谱使用规则 2）。

谱的使用规则（白皮书 §3，防退化成官僚流程）：CP 是工件的位置，不是审批的次数；
每个 CP 的门禁必须能被一条命令判定，判不了就不是门禁，是文档。

---

## 2. model_tiers.yaml — 六层模型分层表

文件即 `engine.channel` 枚举唯一来源（白皮书 §8 铁律 2）。成本三级置信度：
`measured`（仓内实跑/实扣留痕，evidence_ref 指向 文件:行号）/ `reported`（文档转引）/
`unverified`（不得进预算基线，cost_value 为 null 或区间）。

| 层 | 定位（一句话） | 通道（channel_id） | 单条成本与置信度 | V100S |
|---|---|---|---|---|
| T0 确定性层 | 字幕/花字/排行榜/转场全是纯函数，唯一能承诺像素级复现 | proc_ffmpeg / proc_hyperframes / proc_blender | ¥0（measured，工程方案v3.1.md:218 同参数二遍 md5 一致） | ✓ |
| T1 关键帧层 | 构图在被想象之前先被钉死；CP4 局部返修来源 | local_vace_1_3b / local_qwen_image_edit_2509 / local_flux_kontext_dev | 0 积分（VACE reported，墙钟待实测；两备选 unverified） | ✓ |
| T2 廉价草稿层 | owner 的「本地先形成草稿」；480P/16fps 预演，不是交付物 | local_ltx_2b（首选）/ local_wan22_ti2v_5b（次选）/ local_cogvideox_2b（兜底） | 0 积分（measured：LTX 76.7s/条 42/42，工程方案v3.md:35；Wan Q8 212–214s/33 帧，方案 :129） | ✓（Wan 须降 fp16） |
| T3 动作与口播层 | 动作可编程（姿态序列驱动）+ 口播最省路径 | local_mimicmotion / local_echomimicv3 / local_latentsync / api_kling_lipsync / api_vidu_avatar / api_stepfun_tts | Vidu avatar 1 积分/s（measured，工程方案v3.1.md:93）；StepFun ¥5.8/万字符（measured，:101）；可灵 Lipsync unverified | ✓ |
| T4 精修层 | API 买 768P/音轨/多参考身份/零本地占用——本地做不出终稿 | api_h3max（现役默认）/ api_h3（两类回退）/ api_kling_30 / api_kling_25_turbo | 280 积分/条 = 56 积分/s（measured，工程方案v3.md:125，07 手册 8 折未生效）；可灵 unverified | ✓ |
| T5 上限层 | owner 点名 Seedance 2.5；Draft 机制与 CP7→CP9 天然同构 | api_seedance_25 / api_seedance_20_edit / api_vidu_q3 | Seedance 2.5 **unverified 不进预算基线**；2.0 编辑档 28 元/M token（reported，方案 :130）；Vidu Q3 unverified | ✓ |

出局通道（`excluded_channels`，v100s_compatible=false 或降档存档）：Wan2.2-A14B、
HunyuanVideo-1.5、Mochi、CogVideoX1.5-5B（bf16 路线——`is_bf16_supported()` 要求
major≥8，V100S 是 SM70/major 7，物理事实不是调优问题，cheap-draft-and-programmatic-tools.md:187）、
Remotion（LICENSE 禁售自有衍生物，cheap-draft-and-programmatic-tools.md:337）、
Wan2.1-1.3B（硬件可跑但 567s/条 降档存档）。

两条分层纪律（白皮书 §4）：bf16/flash-attention/fp8 路线一律不进 owner 硬件产线；
模型名字不进意图层——换引擎改 `engine.channel`，不改语义。

---

## 3. 与 v1 的关系（降级 / 直迁 / 不变）

按白皮书 §8「扩展不是替代」+ §5.4 重写表落位：

| v1/v3 资产 | v2 处置 | 落位 |
|---|---|---|
| `src/qc_orch.py` / `src/qc_orch_v2.py` | **降级为 gate 包的子模块**：输入 clip+判官输出→clip 级 QCReport 的合议实现保留，但不再是顶层判定结构；顶层判定骨架是五段流水线 gate 包按 CP 分派（CP12 的合议只是 composite 门的一个子门） | `src/gate/`（P1，M1–M2）调用之；白皮书 §5.3「单镜头判官合议不作顶层」 |
| `src/qc_detectors_v2.py`（J6v2） | **直迁 CP7/CP12 作时序 signal 层**：CP7 草稿信号 + CP12 四组门的时序支；角色仍是 signal_only，升否决层须金标扩样（时序四类 n≥5 + 口播正例）复测 promote_criteria（召回≥0.85 且 FPR≤0.15；当前 clip 召回 0.625 不升） | thresholds.yaml `J6_detectors_v2` 段原样引用；白皮书 §5.1 利旧行 |
| `contracts/shot.schema.json` 等三份 v1 | 不动；v2 工件不流入 v1 管线（schema_version 文件级判定） | SPEC.md §0 |
| `eval/eval_run.py` + 金标 40 条 | 不动；检出口径 `verdict.defect_detected` 不变；金标永不入调参 | SPEC.md §3 |
| `tests/run_v3_checks.py`（G0-1..G0-4） | 不动；白皮书路线的每周必过门 | 白皮书 §5.1 |
| `gen_local.py` / `gen_api.py` | 不动；分别是 CP7（T2 层）与 CP9（T4/T5 层）的生产者实现 | 白皮书 §8 投影图 |
| VDL v2（vdl_package/shot_v2 契约 + R1–R6） | 并行同目录；CP1–CP6 工件即 vdl_package 的 intents/shots/post_ops 段的检查点投影；R2（api 通道禁 fix_for_iteration/content_fingerprint）在 CP9 生效 | VDL_v2_草案.md §3.4 |
| 编排器（Prefect 计划）/ 缓存指纹 / 成本记账 | **重写**（白皮书 §5.4）：stage 状态机五态 + 回退目标 CP；槽位级指纹图（upstream_refs）；每 CP 成本台账 | `src/orchestrator/`、`src/cost/`（计划位） |

缓存/失效语义（checkpoint.schema `upstream_refs` 的效力）：CP1–CP6 任一工件 payload
变更 → 其 fingerprint 变更 → 依赖它的 CP7+/CP9 产物失效；CP11 重跑永远最便宜
（编码不达标只重跑合成，零 API 成本）；跨镜重排必须验证「不伪失效」（白皮书 §5.4）。

---

## 4. 验收记录（模板——M0/M1 填写，本版未执行）

> 本节是留空模板。M0-W1 交付日（本文落地日）只完成第 1 项自检，其余等对应周验收时
> 回填「实跑输出 + 退出码 + 证据路径」。回填纪律：只填实跑结果，禁止预填期望值冒充。

### 4.1 M0-W1：12 CP 契约自检（本文件落地时已执行，见 4.5）

```
python -c "import json,jsonschema,pathlib; s=json.loads(pathlib.Path('overnight/vpipe/contracts/v2/checkpoint.schema.json').read_text()); exs=list(pathlib.Path('overnight/vpipe/contracts/v2/examples').glob('*.json')); [jsonschema.validate(json.loads(e.read_text()), s) for e in exs]; print('OK', len(exs))"
# 预期：OK 12（exit 0）
python -c "import yaml; d=yaml.safe_load(open('overnight/vpipe/contracts/v2/model_tiers.yaml')); print('OK', len(d['tiers']))"
# 预期：OK 6（exit 0）
```

### 4.2 M0 验收门（TASK_v4 §4，等 W2 末回填）

```
python overnight/vpipe/tests/run_v3_checks.py        # 预期：== 汇总 == ALL PASS  EXIT=0
sha256sum overnight/vpipe/eval/thresholds.yaml       # 预期：与 eval 留痕 JSON 的 thresholds_sha256 一致（G0-3）
```
另含 Seedance 核价落痕（`evidence/pricing/`，`confirmed` 二值无第三态）与
Wan2.2-5B spike（峰值 <30GB + 黑帧率 0 + ≥1 条过全部六门禁）。结果：_待填_。

### 4.3 M1 验收门（等 W5 末回填）

CP1–CP6/CP10/CP11 八项示例工件过 schema + 门禁判定（零人工）；合成层像素级回归
≥3 用例同输入同输出；改 1 个台词槽位受影响镜头重渲 <10min、其余指纹不变。
结果：_待填_。

### 4.4 M2/M3 验收门

三线样片 + QCReport(1.1) + eval ACCEPT 三件齐；单集成本 ≤8,064 积分；known_cuts
漏登记=0；CP 级夹具库 fail 组拦截率 ≥90%。命令全文见 TASK_v4 §4。结果：_待填_。

### 4.5 本文交付日自检实跑（2026-10-08）

| 检查 | 命令（仓根执行） | 实跑结果 | 退出码 |
|---|---|---|---|
| checkpoint schema 编译合法（draft-07 自检） | `jsonschema.Draft7Validator.check_schema(s)` | 通过 | 0 |
| 12 示例工件全过校验 | §4.1 第 1 条 | `OK 12`（12/12 PASS） | 0 |
| model_tiers 六层可解析 | §4.1 第 2 条 | `OK 6` | 0 |
| v3 既有检查不回归 | `python overnight/vpipe/tests/run_v3_checks.py` | `ALL PASS`（A 7/7、B 3/3、C 1/1、D 40+4+16 零 diff、E 双契约 ACCEPT） | 0 |

环境排障留痕（如实记录，首跑 EXIT=1 后修复，未动任何 v1/受保护文件）：

1. **opencv-python 缺失**（本机 ml venv）：A1 黑屏检查弃权不拦截、B/C/D 检测器 exit 1
   → `python -m pip install opencv-python`（5.0.0.93）后全部转绿。模块自身的修复指引
   （"需要 opencv-python: pip install opencv-python"），纯环境操作。
2. **判官原始输出缺失**（`overnight/数据/judges/` 本机只有 detectors/，glm8/omnijev/
   videochat3 不存在——`overnight/数据/` 整体 gitignore，2026-10-07 ALL PASS 复锁
   （g01-full-relock.json，commit 073a6ed）是在 GPU 机 clone 上执行的，判官线产物
   未同步回本机）→ 按 JUDGES-RERUN.md 数据来源从 GPU 机
   `root@100.64.0.7:/data/night/g01-rerun/video-capability/overnight/数据/judges/`
   tar 流恢复（3 判官各 41 json + raw/40，与该文档验收口径一致；数据/ 为 gitignore
   的本地数据目录，非仓内受保护文件）。恢复后 E 组双契约回放 ACCEPT，
   E10 与 thresholds.yaml v3 实测基线一致（R=1.000 / FPR=0.250 / F1=0.9143）。

---

## 5. 已知边界（如实抄录，防止误当已完成）

| # | 边界 | 出处 |
|---|---|---|
| 1 | **J6v2 不升否决层**：clip 召回 0.625 < promote_criteria 0.85，时序金标 n=2/类不足；扩样前不得升否决层（扩样 n≥5 + 口播类正例后方可复测） | 白皮书 §5.1/§5.2；工程方案v3.1.md §3.3 |
| 2 | **D 组（物理/时序/叙事/整体观感）默认 warn-only，不做自动否决**：物理类 GPT-4V ROC-AUC≈53≈随机；7 路 judge 时序召回全零（工程方案v3.1.md:110）；schema 以 `d_group.warn_only const true` 固化，不许出现自动拦截形态 | 白皮书 §3 CP12 / §7 非目标 3 |
| 3 | **审美维与合规维先 warn-only**：70 分人评锚定（120 片段）12 周内不做（P3 级投入）；在此之前 70 只作 warn 阈与人工队列排序依据，不作自动放行绝对门；CP12 schema 的 `master_score_min` 引用不影响该边界 | 白皮书 §7 非目标 8 / §6 M2 风险 |
| 4 | **Seedance 2.5 未核价不进预算基线**：单价 unverified（2.0 编辑档 28 元/M token 为文档记录；46 元/M token 媒体转述明文未确证；hypit 案例无逐项账单）；核不出就明文标未确证，confirmed=false 不得进预算基线 | 白皮书 §4 成本可信度表 / §6 M0-W1；TASK_v4 §4 |
| 5 | **API 层无像素级复现承诺**：API seed 零控制力（同 prompt+seed 两片 aHash 汉明 102.75 > 无 seed 51.75，工程方案v3.md:38）；任何排产表不许把 API 产物写进 md5 回归基线；CP9 `repro_level=submit_params` 是诚实上限 | 白皮书 §2 原则 4；SPEC.md §2.2 |
| 6 | **bf16/flash-attention/fp8 路线不进产线**：SM70 major=7 物理不支持；Wan2.2-5B 必须 `--convert_model_dtype` 降 fp16 | 白皮书 §4 T2 / §5.3 |
| 7 | **CP4 身份锁止边界**：在场检测 + ArcFace 身份级余弦（≥0.60 统一口径），不是 IP-Adapter 级像素同一性；「跨镜变脸已解决」的说法不许出现在任何 v2 工件 | 白皮书 §3 CP4 边界说明 |
| 8 | **人工介入只减不增**：设计内介入点 CP1/CP3/CP5/CP6/CP12，其余 CP 零人工；加人必须回答「补的是哪个已知失效模式」；owner 介入形态仅三种（文字反馈/圈改/给参考），不引入第四种 | 白皮书 §3 谱使用规则 2 / §7 非目标 2 |
| 9 | **跨币种只许同体系比较**：MiniMax 积分 / Vidu 积分 / StepFun ¥ / 本地墙钟四套货币不可换算，成本台账须显式声明折算口径，不许给出无依据的 ¥ 汇总 | 白皮书 §5.4 成本记账重写行 |
| 10 | **qc_report_v2.schema.json 未落地**：P1（M2）计划位；落地前 CP12 工件的 shot_qc_refs 引用 v1/v2 clip 级 QCReport（1.0/1.1 仍合法）；CP12 成片级判定暂由 checkpoint.schema 的 qc_master payload 承载 | TASK_v4 §3.1；SPEC.md 变更记录 1.1 行 |

---

## 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-08 | 2.0 | 首版增量（M0-W1）：新增 `contracts/v2/checkpoint.schema.json`（12 CP 工件契约 + gate{type, params_ref} 声明，数值全引用 thresholds.yaml）、`contracts/v2/model_tiers.yaml`（T0–T5 六层 + excluded_channels，engine.channel 枚举唯一来源）、`contracts/v2/examples/cp1..cp12.json`（12 示例全过校验）；§3 落定 v1 资产降级/直迁关系（qc_orch*→gate 包子模块、qc_detectors_v2→CP7/CP12 signal 层）；v1 契约与 E10 基线零改动，`run_v3_checks.py` ALL PASS 复验通过 |
