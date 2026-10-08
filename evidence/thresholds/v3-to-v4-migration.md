# thresholds.yaml v3→v4 升版说明（CP 级门禁段落地）

- 日期：2026-10-08
- 执行：阈值管理员（TASK_v4 §3.1 P0-M0-W2）
- 对象：`overnight/vpipe/eval/thresholds.yaml`
- 性质：**只增不改**——`version: 3→4` 一行替换 + 文末新增 `checkpoints:` 段；v3 段
  （`ensemble` / `judges` / `eval_admission` / `l0_preflight` / `source_report`）一字未动。

## 1. 变更动机与键清单来源

`contracts/v2/checkpoint.schema.json` 红线①：**一切判定数值不进契约**，一律经
`gate.params_ref` 引用 `eval/thresholds.yaml` 的具名键（"CP 级新段由 thresholds v4 增补，
命名 cpN.gate.*"）。本升版把 schema 与 `examples/cp1..12.json` 引用的全部键逐个 grep
盘点后落实：

- 盘点范围：`checkpoint.schema.json` 全文 + 12 个示例工件每个 `gate`/`aux_gates[].params_ref`。
- 盘点结果（去重后 **39 个引用**，其中示例工件实引 31 处）：
  - **36 个新键**落在 `checkpoints.cpN.gate.*`（含 schema 正文 `cp12.gate.b_group_*` /
    `c_group_*` 通配按 a_group 命名法具名化为 `b_group_recall_min` / `b_group_fpr_max` /
    `c_group_recall_min` / `c_group_fpr_max`）；
  - **8 处既有段引用**不改不复制：`l0_preflight.black_frame_ratio_max`（0.50）、
    `l0_preflight.duration_dev_max`（0.02）、`l0_preflight.avatar_tail_max_s`（1.0）、
    `J6_detectors_v2.known_cuts_tol_s`（0.5）、`ensemble.E10`——全部在 v3 段原位可解析，
    防第二套判定数值。
- CP7 特例：schema CP7 主门定义原文「全部数值沿既有段 l0_preflight.* 引用（拒收 exit 4
  已实装）」，示例 cp7.json 实证只引既有键 → **cp7 不立任何新数值键**，仅留
  `uses_existing_keys` 引用清单作机读登记。

## 2. 解析口径（M1 门禁校验器实现依据）

- `cpN.gate.*` 形式的 params_ref → 以 `checkpoints:` 为根按点路径解析
  （`checkpoints.cpN.gate.<key>`）；
- 既有段引用（`l0_preflight.*` / `J6_detectors_v2.*` / `ensemble.*`）→ 沿 v3 现行消费方式
  解析：段定位（`l0_preflight` 在文件根；`J6_detectors_v2` 在 `judges:` 下——见
  `src/qc_detectors_v2.py:122-129` 的 `load_params` 取段方式；`ensemble.E10` 在
  `ensemble.definitions` 下），段内按键名解析。两段式根，与既有消费者零冲突。

## 3. 逐键数值口径 / 初值理由 / M2 校准计划

数值来源总口径：白皮书 `research/2026-10-08/工业化视频流水线-白皮书.md` §3 各 CP
「客观验收门禁」行 + §4 各 T 层门禁行/成本可信度表；白皮书未给数值的键标
「**v4 初值，M2 校准**」（M2=§6 试跑 W6–W9）。布尔强制键（`true`/`required`）不是数值阈，
是「规则生效且违例即拒」的声明位。

### CP1 意图单（白皮书 §3 CP1）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `forbidden_defect_code_registry` | 8 码注册表（G1_手部…G8_风格化） | schema：defect_code 必须能在 thresholds.yaml 查到；白皮书 CP1「禁区无对应缺陷码→拒收并要求 owner 裁决（全链唯一死胡同）」 | 码表=工程方案v3.md §1.1 G1–G8 边界轴 + SPECS_V2.md §3 G7 物体恒存门禁定名；示例 cp1.json 引用 G7/G2。M2：随金标扩样队列新增缺陷码时扩表（每码须先有 fail/pass 夹具再入表，M3 夹具库口径） |
| `owner_confirmation` | `required` | cp1.json aux_gates（type=human）；白皮书 §3 谱首段 CP1=设计内人工介入点 | 非数值键；确认动作不设阈。M2：人工介入点实测计数（§6 M2 交付物 5），只计数不改键 |

### CP2 剧本（白皮书 §3 CP2）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `duration_dev_max` | 0.02 | 白皮书 §3 CP2「Σ estimated_duration 与目标集时长偏差 ≤2%」原文 | 白皮书明数，非初值；M1-W3 交付物 1 同口径。M2：若汉字计音节估算系统性偏差大，调估算器不改阈 |
| `line_shot_ratio.min/max` | 1.0 / 1.5 | 白皮书 §3 CP2「比值在 [1.0, 1.5]（台词过少或过碎都拒）」原文 | 白皮书明数。M2：按题材分布观察越界率，越界率异常高先怀疑估算器 |

### CP3 分镜表（白皮书 §3 CP3）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `max_shot_duration_s` | 15.0 | 白皮书 §3 CP3「duration_s ≤ 引擎单段上限（H3 实测 4–15s，VDL_v2_草案 R3）」 | 与 schema `duration_s.maximum:15` 结构兜底同值；换引擎（H3→Seedance 等）若单段上限变化，改本键不改契约。M2：T5 通道核价/实测后复核 |
| `word_anchor_valid` | true | 白皮书 §3 CP3「词锚定合法（@{} 引用必须存在于本镜台词内）」引 AI视频生产流水线方案.md §3.2 校验器七条 | 布尔强制键。无需校准 |
| `shot_line_count_match` | true | 白皮书 §3 CP3「镜头数与 CP2 台词条数一致」 | 布尔强制键；与 cp2 `line_shot_ratio` 同源两侧。无需校准 |

### CP4 关键帧（白皮书 §3 CP4 + §4 T1）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `pixel_map_rule` | true | 白皮书 §3 CP4「分辨率/比例符合 deliverable」 | 布尔强制键，对照 CP1 `deliverable.pixel_map` 判等。无需校准 |
| `black_frame_ratio_max` | 0.0 | 白皮书 §3 CP4「黑图率=0（fp16 NaN 是 V100 已知失败模式）」+ §4 T1 门禁行同文 | 白皮书明数（静帧无豁免，严于视频 L0 的 0.50）。M2：Wan2.2-5B 对照跑（§6 M0 交付物 5）若出现解码级假黑帧再议豁免口径，当前 0 不动 |
| `identity_coverage` | true | 白皮书 §3 CP4「detected_identities ⊇ expected_identities」（DramaClaw 唯一标记色+检出态思路） | 布尔强制键。无需校准 |
| `identity_cosine_min` | 0.60 | 白皮书 §3 CP4「ArcFace 跨身份余弦 ≥ 0.60（统一口径，AI视频生产流水线方案.md 表 2-1）」 | 白皮书明数；示例实测 0.68–0.71 有余量。M2：按身份库扩样复测分布，如余弦整体上移可收紧（收紧走 thresholds 修改规程，先复跑 eval） |

### CP5 动作脚本（白皮书 §3 CP5）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `pose_frame_max` | 72 | 白皮书 §3 CP5「帧数 ≤ 上限（MimicMotion 上限 72 帧 @576×1024，cheap-draft-and-programmatic-tools.md:219）」 | 引擎能力值；超限走分段+progressive latent fusion（缝登记 known_cuts）。M2：T3 层接入实测后复核 |
| `frame_time_monotonic` | true | 白皮书 §3 CP5「帧时间单调」 | 布尔强制键。无需校准 |
| `speech_fullbody_lip_layer` | true | 白皮书 §3 CP5「motion.speech=full-body 时必须存在独立口型层路径（否则拆镜）」引 AI视频生产流水线方案.md §3.3 | 布尔强制键；分镜层规避，禁止质检环节自动改景别。无需校准 |

### CP6 时间线（白皮书 §3 CP6）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `duration_conservation_frames` | 1 | 白皮书 §3 CP6「Σ shot.duration == 集时长（±1 帧）」原文 | 帧域整数容差。无需校准 |
| `subtitle_align_ms_max` | 40 | 白皮书 §3 CP6「字幕段与音轨词级时间偏差 ≤ 40ms」（whisperx SemanticTake 口径） | 白皮书明数；示例实测 32ms。M2：whisperx 实跑分布复核 |
| `rhythm_segment_s.warn_min/warn_max` | 0.8 / 12.0 | 白皮书 §3 CP6「无长度 <0.8s 或 >12s 的段落（warn-only 起）」 | warn-only 不否决；超限上升人类一次带三个候选方案，不自动改。M2：按样片节奏分布复核 warn 带宽度 |

### CP7 草稿视频——无新键

schema 门禁行原文「全部数值沿既有段 l0_preflight.* 引用」；引用清单
`uses_existing_keys: [l0_preflight.black_frame_ratio_max, l0_preflight.duration_dev_max]`。
NaN/黑帧与帧率/分辨率符合性为布尔/声明判定（白皮书 §3 CP7），无数值阈。
M2 校准：无（随 L0 既有段走，L0 参数改动另走 v3 修改规程）。

### CP8 择优（白皮书 §3 CP8）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `pareto_rule` | `top1_strict_dominance` | 白皮书 §3 CP8「候选集内 top-1 在硬校验向量上 Pareto 支配（无单项比 top-2 差且总分更低）」 | 规则选择符（非数值）；判据实现归 M1 校验器。无需校准 |
| `judge_disagreement_delta` | 0.15 | 白皮书 §3 CP8「judge 间分歧 > δ 或与硬校验方向矛盾时看」——**δ 无数值** | **v4 初值，M2 校准**：初值 0.15 仅由示例 cp8.json 反推下界（panel_disagreement=0.08 未触发上升 → δ>0.08）；M2 以 judge 分歧实测分布定标（分歧直方图取「矛盾上升率≤20%」约束下的分位）。与硬校验方向矛盾=无条件上升，不经本阈 |
| `retry_max` | 2 | 白皮书 §3 CP8 失败回退「单镜重试上限 2 次，超限转人工工单」原文 | 白皮书明数。无需校准 |

相对线说明：judge_rank 键 = 既有段 `ensemble.E10`（示例 cp8.json aux_gates 实证），
只决定次序不设绝对通过线（白皮书 CP8 两层不可混）；E10 定义/阈值在 v3 段，本次零改动。

### CP9 终稿渲染（白皮书 §3 CP9 + §4 T4）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `credit_cap_per_shot` | 280 | 白皮书 §4 成本可信度表「H3-Max 280 积分/条（5s 768P 含音轨）=56 积分/s——仓内实测钱包逐条可对（工程方案v3.md:125）」；超限 exit 3（§6.3 实证 DTO 校验先于扣费零损失） | 仓内实测值；标准档单集预算 6720=24 镜×280（同表）。M2：换通道/换价后按新单价改键并同步预算算式；成本台账（M2 交付物 6）周核 |
| `repro_log_complete` | true | 白皮书 §3 CP9「参数级复现留痕（提交参数、seed、指纹落盘一致）；不做像素级 md5 承诺」 | 布尔强制键，缺任一留痕即拒。无需校准 |

### CP10 字幕与音轨（白皮书 §3 CP10）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `cer_max` | 0.05 | 白皮书 §3 CP10「whisper CER small/medium 双口径 ≤5%（同音字以 pinyin 归一口径分析，不凑数，INTENT.md:89）」原文 | 白皮书明数；示例实测 small 3.1%/medium 4.2%。M2：CER 超标先改分句不改词（回退行），若分句优化后分布仍贴近阈再议 |
| `loudness_lufs_target` | -16.0 | 白皮书 §3 CP10「响度 −16 LUFS」原文 | 目标值判等；判等容差（±LU）白皮书未给——**v4 初值按达标即过（示例 cp10.json 实测 −16.0 恰等）**，M2 出现系统性偏差再立容差带 |

时长守恒（avatar 线=ceil(音频秒)）沿既有段 `l0_preflight.avatar_tail_max_s`
（示例 cp10.json 副门实证），零改动。

### CP11 合成（白皮书 §3 CP11 + §4 T0）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `duration_tol_s` | 1.0 | 白皮书 §3 CP11「ffprobe 校验（总时长 ±1s、竖版 1088×1920、h264+aac）」原文；CRADLE 六道硬校验挂合成产物（§4 T0 门禁行） | 白皮书明数。无需校准 |
| `shot_count_match` | true | 白皮书 §3 CP11「切镜数 == 分镜表镜头数」；CRADLE 六道之一 | 布尔强制键；不符退回定位哪一镜多/少切。无需校准 |

另两道沿既有段（不立新值防第二套数值）：拼接切点白名单容差 =
`J6_detectors_v2.known_cuts_tol_s`=0.5（示例 cp11.json 主门实证；不登记则同人物同构图
硬切后向重入相似度 0.9784>0.85 必误报 temporal_swap，工程方案v3.1.md:170）；
黑场占比 = `l0_preflight.black_frame_ratio_max`=0.50（schema CP11 门禁行「黑场占比」）。
M2 校准：`known_cuts` 漏登记 =0 是 M2 验收门禁⑤，走登记纪律不走阈值。

### CP12 质检与成片（白皮书 §3 CP12 五条 + §6 M2 验收②③）

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `master_score_min` | 70 | 白皮书 §3 CP12「judge 标定分 ≥70（≙ 人评 7.0/10），且必须是人评锚定后的映射值」 | 70 当前**仅作 warn 阈与人工队列排序依据，不作自动放行**（锚定未完成：120 片段人评未做；白皮书 §7 非目标 8；schema episode_verdict.score 行同口径）。**M2 校准=完成人评锚定后回填映射值**——这是本段最重要的一个待校准键 |
| `a_group_recall_min` | 0.99 | 白皮书 §3 CP12「A 组：程序规则，召回 ≥99%」；§6 M2 验收②「规格服从维 A 组召回 ≥99%」同值互证 | 白皮书明数。M2：M2 验收②即为该键的首轮实测点 |
| `a_group_fpr_max` | 0.01 | 白皮书 §3 CP12「误报 ≤1%」；§6 M2 验收②同值 | 白皮书明数。M2 同上 |
| `b_group_recall_min` | 0.95 | 白皮书 §3 CP12「B 组：专用小模型，召回 ≥95%」 | 白皮书明数。M2：B 组小模型（LSE-D 等）接入后实测复核 |
| `b_group_fpr_max` | 0.15 | 白皮书 §3 CP12「误报 ≤15%」 | 白皮书明数；LSE-D 硬门仅特写/近景、全身降 warn-only 是 profile 逻辑非阈值（归校验器实现）。M2 同上 |
| `c_group_recall_min` | 0.80 | 白皮书 §3 CP12「C 组：VLM judge，类内召回 ≥80%」 | 白皮书明数；judge 缺陷不允许自动否决（C 组不入 veto_groups）。M2：E10 判官族类内口径实测后复核 |
| `c_group_fpr_max` | 0.15 | 白皮书 §3 CP12「误报 ≤15%」 | 白皮书明数。M2 同上 |
| `veto_groups` | [a_group, b_group] | 白皮书 §3 CP8「任一 A/B 组否决缺陷存在→候选直接出局」+ CP12「任一镜头存在 A/B 组否决缺陷→成片门直接不通过」 | 组名册（非数值）；与 cp8 `veto_defects` 同源防两套（schema veto_defects 行）。D 组恒 warn-only 已由 schema `d_group.warn_only` const:true 固化，非阈值。M2：若某 C 组类误报实测长期≤1% 可议升否决（须 owner 裁决，默认不动） |
| `human_escalation_rate_max` | 0.20 | 白皮书 §3 CP12「人工上升率 ≤20%（周复核误杀/漏放并回滚权重）」；§6 M2 验收③同值 | 白皮书明数。M2：人工介入点实测计数（M2 交付物 5）即为实测点；周复核回滚机制即校准机制 |
| `retry_round_max` | 2 | 白皮书 §3 CP12 失败回退「重试 ≤2 轮仍不过→人工工单+标记结构性困难+进金标扩样队列」原文 | 白皮书明数。无需校准 |

## 4. 红线自证（本次实跑记录）

| # | 红线/验收 | 命令 | 结果 |
|---|---|---|---|
| 0 | 改前留底 | `git diff overnight/vpipe/eval/thresholds.yaml`（改前） | 空 diff，exit 0 |
| 1 | v3 段零修改 | `git diff overnight/vpipe/eval/thresholds.yaml`（改后） | `1 file changed, 172 insertions(+), 1 deletion(-)`；**删除行仅 `version: 3 …` 一行**（grep `'^-'` 输出仅此行）；另以 python 深比较 HEAD 版 vs 现版：`ensemble`/`judges`/`eval_admission`/`l0_preflight`/`source_report` 五段**语义逐键相等 = True**；`eval_admission` 准入线未动（recall 0.90 / fpr 0.30 / f1 0.85 / b_flag 0.50） |
| 1b | 全键可解析 | python 自检：schema+examples 全部 params_ref（去重 39 个，`b_group_*`/`c_group_*` 通配具名化）逐个解析 | 全部可解析，一个不漏（exit 0） |
| 2 | 全量自检 | `python overnight/vpipe/tests/run_v3_checks.py` | **ALL PASS，EXIT=0**（A1–A5 L0、B/C 豁免+known_cuts、D 无声明回归金标 40/合成 4/avatar 16 条判定零 diffs、E 双契约 eval ACCEPT） |
| 3 | eval 准入 | `python overnight/vpipe/eval/eval_run.py --qc-dir overnight/vpipe/out/qc_reports_v3post` | **ACCEPT，EXIT=0**；R=1.0 / FPR=0.25 / F1=0.9143 / B_flag=0.5833，与 E10 基线偏差 dR=0.0 dFPR=0.0 dF1=0.0（误报仍为 010/013/032 三条，即 v3 注记的 J3@0.71 工作点原 trio——判定行为零变化） |
| 4 | G0-3 哈希锚定 | `sha256sum overnight/vpipe/eval/thresholds.yaml` vs `eval_results.json.thresholds_sha256` | 双方均为 `79820b50cea74b248c25e54967568bc54f650f02b389f33051cc8948a8bb3813`，一致 |

运行留痕说明：验收 2/3 的命令按其定义重生成了 `out/qc_reports_v3post*`、
`out/v3_selftest/**`、`out/asset_manifest_v3post*` 与 `eval/eval_results*.json`——
与 HEAD 版相比仅 `generated_at` 时间戳与 `thresholds_sha256` 字段变化，判定内容不变
（D 检查零 diffs 即证明；同仓内 c8882db「运行产物同步」先例）。
contracts/、eval_run.py、golden_manifest.json 本次零改动。

## 5. 遗留与后续

- `cp8.gate.judge_disagreement_delta`（0.15）与 `cp10.gate.loudness_lufs_target` 的判等
  容差是本段仅有的两个非白皮书明数，均已标注「v4 初值，M2 校准」；M2 结束前必须以
  实测分布回填并在本文件追记。
- `cp12.gate.master_score_min=70` 在人评锚定（120 片段）完成前不生效为自动绝对门——
  这是白皮书 §7 非目标 8 的要求，不是阈值管理员的裁量。
- 本段效力对象是 M1 落地的 `src/gate/` 校验器；现行 `qc_orch*`/`qc_detectors_v2`/
  `eval_run.py` 不读 `checkpoints:` 段（本次验收 2/3 通过即为其零影响的实证）。

---

## 6. 追记（v4→v5，2026-10-08）：`checkpoints.cost.episode_budget` 段新增

- 性质：**只增不改**——`version: 4→5` 一行替换 + `checkpoints:` 末尾新增 `cost.episode_budget`
  两键；v3 段与 v4 既有 12 CP 段语义逐键相等（python 深比较实证）。
- 批准：M2-W9 成本台账工程师按红线「判定数值不许硬编码、新键先报告主控」上报，主控
  2026-10-08 当场批准按推导链落地。
- 消费方：`src/cost/ledger.py` report 的「单集成本 vs 标准档 ×1.2」对照行
  （TASK_v4 §4 M2 验收④）。

| 键 | 值 | 来源口径 | 初值理由 / M2 校准 |
|---|---|---|---|
| `standard_episode_shots` | 24 | 白皮书 §4 成本可信度表「标准档 120s 单集 24 镜 × 280」行 | 档位定义非判定魔法数；M2 三样片（60s/30s/20s）实跑镜数≠24 时，对照行仍按标准档 24 镜口径算上限，实耗/上限比值即预算占用率 |
| `budget_multiplier` | 1.2 | TASK_v4 §4 M2 验收④「单集成本 ≤ 标准档 ×1.2」 | 验收明数。M2 校准：×1.3 重试系数（白皮书 §4 同表「含 1.3 重试系数 ≈8,736」）在 M2 实测重试率落定后再议是否拆第二键 |

- 推导口径（**不单存乘积，防第二套数值**）：单集预算上限 =
  `standard_episode_shots × checkpoints.cp9.gate.credit_cap_per_shot × budget_multiplier`
  = 24 × 280 × 1.2。阈值文件内不落总额字面量（新增注释与键值零 `8064`/`6720`）；
  cp9 既有注释中的预算算式文字为 v4 原文，本次零改动。
- 复跑留痕（G0-3 全绿）：
  1. `git diff`：`1 file changed, 20 insertions(+), 1 deletion(-)`，删除行仅 `version: 4 …`；
  2. `python overnight/vpipe/tests/run_v3_checks.py` → **ALL PASS，EXIT=0**；
  3. `python overnight/vpipe/eval/eval_run.py --qc-dir overnight/vpipe/out/qc_reports_v3post`
     → **ACCEPT，EXIT=0**（R=1.0 / FPR=0.25 / F1=0.9143 / B_flag=0.5833，误报仍
     010/013/032 原 trio——判定行为零变化）；
  4. `sha256sum overnight/vpipe/eval/thresholds.yaml` =
     `a7f8808de916ad3edd59be99bef353f0c60ad74186b6b7f1a0d1af53ff303cfa`
     与重生成的 `eval/eval_results.json.thresholds_sha256` 一致。
