# worklog — video-capability（append-only：每日做了什么/决策/下一步）

- 2026-10-01 迁移完成：windev-01 D:/workspace/video-capability-research → anolis-gpu-01:/opt/gpumachine/projects/video-capability（线1-2B 迁移批；sha256=12807145 两端核对过；验证：tar 成员 5644=磁盘 5644，锚点 FINAL_REPORT_V2.md/judge基准报告.md/overnight/数据 在位）。secrets/api_keys.env 未迁（GPU 端重跑前需重建凭据）。接续卡：continue-cards/video-capability.md。下一步：CONFIRMATION.md（A13+B4）呈 owner 人工确认。

- 2026-10-01 worker-B（ztough926/video-understanding 纯代码视频理解借鉴，轮1）：架构研究完成（GitHub API 全树取证+四件套 sha256 存档 research/ztough926_src/，GPL-3.0）；接入方案落 research/ztough926_接入方案.md（B1 帧差时间线确定性 QC 信号/B2 变化感知选帧/B3 模型可读分张纪律/B4 Skill 化，关键思想落地不整仓照搬）。最小原型 research/proto/sheetframe.py（cleanroom 独立实现 ~260 行）：P1 定格检出 EXIT=0——golden_017/028 检出冻结 1.562-3.500s vs 注入 1.531-3.531s（端点误差 0.031s），干净对照 golden_001/006 零误报（judge报告 §0.5 实锤 J1 漏检洞被确定性修掉）；P2 总览图可读性 Higress 2 次调用 EXIT=0（glm-plan→glm-5.3-flash，golden_002 乱码逐字读出+定位 3.38s，golden_001 零误报；配额 2/5，key 经 OpenBao gpu/models/higress-consumer 内存态零打印，windev 侧代理执行因 GPU→srv-1 无密钥）。设计发现：变化感知选帧会抹掉定格信号→时序缺陷走帧差时间线（P1）、内容缺陷走总览图+VLM（P2）分工。已知瑕疵如实记录：模型误读格序号 #004→#055（时间戳正确，正式版格标签需加大）；阈值口径仅在 2+2 clips 初验，全 40 金标重校准前不得当生产阈值。模型配额合计：worker-B 2 次。


# worklog append — worker-A v3 首批（2026-10-01 夜班轮）

- 2026-10-01 worker-A v3 首批（依据 工程方案v3.1 §7.2 P0 清单；模型调用 0、积分 0）：
  ① P0-2 L0 确定性预检挂进 qc_orch_v2 在线模式（黑屏/时长双检查；--profile avatar_talk 垫尾豁免窗=[expect×0.98, ceil(expect)+1.0s]；拒收 exit 4 + <clip>.l0.json 证据）；注入超差样本验收：拒 3/3、放 2/2（tests/run_v3_checks.py A 组）。
  ② P0-1 机理回填：qc_detectors_v2 增低运动平台豁免（diff 支 in_med<2.0 标注；--profile 声明制豁免，实测依据：9/15 avatar 误报 in_med=0.71-1.64 与真混叠 golden_034/028 交叠，绝对阈不可分）+ known_cuts 切点白名单（tol 0.5s）；QCReport 契约 1.1（enum[1.0,1.1] + qc_context{profile,known_cuts,l0_preflight}，向后兼容）。dh 三片 ghosting+swap 误报归零；avatar 15 片误报 9→1（残留 vidu_b_timeline lap 支 1 例，如实披露）。
  ③ 基准对比（同口径）：E10 复算改动前后与 judge基准报告基线零偏差（R 1.000/FPR 0.250/F1 0.9143/B_flag 0.8333，误报仍 010/025/032）；J6v2 时序 7/8、C-FPR 0/12、合成 4/4 判定级逐条一致（59 条回归）；eval 双模块 ACCEPT exit 0。
  ④ thresholds.yaml v2（E10 判定阈未动）；SPEC.md 变更记录 1.1 行；新自检脚本 tests/run_v3_checks.py（exit 0 ALL PASS）。
  未做如实报：P0-3 MediaPipe（新依赖+独立调参，留下一轮）、P0-4 kimi 终裁（两路径均超 worker 权限：API 需未随迁密钥/降级属策略裁定）；CONFIRMATION.md 仍待 owner。
  证据：deliverables_v3/V3_BATCH1_WORKER_A.md；eval_results_v3base*/v3post*.json；out/v3_selftest/。

- 2026-10-06 genapi 迁移：MiniMax 视频生成通道 windev 本机客户端网关 → higress 云直通（windev 10-07 销毁前摘依赖）。方案：`vpipe/src/gen_api.py` 新增 cloud 通道并设为默认（`--backend cloud|windev`，windev 127.0.0.1:8001 降为可选后端），走 `/minimax-cloud` 三步流 generate→tasks/{id}→files/{id}→CDN 下载（端点依据 overnight/MiniMax-Design-接入手册.md §2，2026-10-06 实测）；**同接口面**：CLI 参数/退出码 0/1/2/3、api_results 终态词表（云 success→succeeded 归一化）、SPEC §2.2 冻结签名均不变，poll_task 按 sess.backend 分派；配置集中模块头 + `VPIPE_GENAPI_*` 环境变量覆盖（风格沿 gen_local 的 VPIPE_*）；fail-closed 不变（探活失败 exit 2，服务失败如实抛）。云通道如实降级不伪造：无钱包端点→56 积分/s 估算守卫（est_credit 记录、实扣字段如实 null，超 --credit-cap 仍 exit 3）；云 DTO 无 seed→不发送不探测；参考图 URL 直传 reference_images，本地路径 fail-closed reference_unsupported_on_cloud（files/upload 手册标注未实测，不盲调）；参数按手册 §2 模型表本地预检（越界 invalid_params 零 HTTP 不耗额度）；CDN 下载 URL 过既有 validate_base_url 拒内网/环回。验证：①真实最小生成 1 次（duration=4/768P/16:9/无声）91.9s 出片 1344×768 h264+aac 4.458s、764,108B、sha256 381eb4a4fc17…5ef，task voE3vDyZ8Wqp——与手册 §8 实测产物（h264 1344×768+aac 4.46s）同特征，ffprobe 证据 `vpipe/out/cloud_migration_smoke/ffprobe_evidence.json`；②mock 网关单测 `tests/test_gen_api_cloud.py` 12/12（全链路成功+fail-closed×5+预检零提交×2+windev 契约回归×2，零真实生成）；③test_vdl2 的 gen_api dry-run 用例通过，其余 10 失败为环境缺 `referencing` 模块的既有问题（stash 对照实证与本次改动无关；其回放副写的 eval/qc 产物已 git 还原）。文档：SPEC.md §2.2 双通道化、接入手册 §9-5 迁移销项。残留如实记：`gen_avatar.py` DESIGN_GATEWAY(127.0.0.1:8001) 仅 TTS 备用通道（默认 StepFun）未迁，云 TTS 端点手册 §4 后续可同法迁。生成类调用 1 次，金标/阈值未动。

# worklog append — v4 工业化流水线（2026-10-08）

- v4 立项与 M0 收官：owner 批准 TASK_v4（混合分层路线：廉价草稿+高端精渲，12 CP 谱+T0-T5 模型层）。
  M0-W1（df5d96c/c8882db）：12 CP 契约三件套（checkpoint.schema.json/model_tiers.yaml/examples×12）
  + SPEC_v2.md + evidence 5 份（GPU 机/凭据/核价/墙钟）；样片短剧 4 条从一剧N国 搬运（sha256 核验）。
  M0-W2（3d7f283/fdaa1cd）：thresholds.yaml v3→v4（+172/-1，v3 段深比较相等；37 个 cpN.gate.* 键；
  32/32 params_ref 可解析——主控抓到并修复子代理两处短路径缺陷）；qc_report_v2.schema.json（v1 兼容+
  checkpoint/episode_verdict/human_review）；样片补齐 8 条（漫剧 2+营销 2，B 站源如实标注，
  抖音新下载因强制登录态全败未绕过）；GPU 卡 1 被兄弟项目 xdng 三服务 27.7GB 常驻，15 分钟观测
  无自然空闲窗。
- 凭据重建（A-3 结）：owner 指路 governance 机 OpenBao。实测 vault-broker 的 ADMIN_TOKEN 即 bao
  root token；kv/company/LLM-upstream/{MiniMax,stepfun/step-plan-1,Zhipu,kimi/kimi-1} 五通道 key
  取到并落 GPU 机 overnight/secrets/api_keys.env（0600，值零回显）；Vidu 全量搜 50 叶子 0 命中，
  avatar 线待 owner 提供。详见 docs/credentials-rebuild.md。
- GPU 解锁：owner 授权「GPU 没在跑就直接用」。卡 0 当前 310MiB/util 0%，spike 改卡 0 执行
  （跑前复测纪律保留；卡 1 不碰）。M1 第一批规则校验器（CP2/CP3/CP5/CP6/CP11，纯代码零 GPU）
  与 GPU spike（LTX 基线+Wan2.2-5B）双工作流并行派发（GLM-5.3-Flash 工作代理，主控验收模式）。

# worklog append — v4 M1 收官与 M2 开工（2026-10-08 深夜~10-09）

- M1 三段全部验收入库：批一 5 校验器（1c93987，主控修 4 处：CP3 fail-closed/指纹口径/
  schema during/gate.result pending，全量回归 42→51/0）；批二 glTF 往返+像素回归
  （410820b/a6d39a4，3 用例两遍 md5 逐字节一致）；M3-a CP11 夹具 2+3/validate_cp12/
  收敛曲线（638644d，79 单测）。验收方法论备忘：shell `$?` 不得置于 `$(...)` 命令替换
  之后（三次误报均因此），回归脚本 ec=$? 先存口径为正解。
- M2-a 短剧线 CP1→CP6 工件链验收通过（c533e8b）：《雨夜合约》EP1，11 镜/60s/1440 帧守恒，
  5 工件指纹实算+链式引用逐环核对+4 门禁 exit 全 0；cp1 的 owner 确认 pilot pending。
- spike 与判据修正：LTX-2B 5.39s/条/18.34GiB/MAE=0（决策 f：英文 prompt 层+色偏限草稿用途）；
  bf16 判据修正（b72ca96：torch2.7 SM70 is_bf16_supported=True 模拟路径，四模型出局真因显存）；
  Wan2.2-TI2V-5B 31.83GiB 下载授权（决策 e）后 spike 进行中。
- TTS（38bd887：15 单测+真实调用 200+401 负控制；延迟 122.7s/次→CP10 需并行化）、
  判官收编（e322c37 glm8_batch.py+Zhipu key 闭环）、成本台账（476fea1：28 单测+thresholds
  v5+8064 三键乘积推导）、样片结构（3 条 structure.json+Σ 时长对账）。
- 累计提交 20 笔；进行中：Wan2.2 spike、M2-b CP7 草稿（11 镜英文 prompt）。待 owner：Vidu key。

# worklog append — v4 三线收官与验收门（2026-10-09）

- 三线全部跑通 12 CP 全链：短剧《雨夜合约》EP1（64s 含数字人段，D-1 完整态——
  avatar 钩子段+Vidu S2 真实生成+CP12 重判 pass）；营销《雪松晚安香》EP1（20s
  带货样片，口播镜触发预留降级路径：参考图缺位→no-talking-head 变体，不伪造
  人物图）；漫剧《头汤面》EP1（30s G8 风格化，CP9 风格强约束人检 9/9 成立）。
- 关键实证：①T2 草稿层 ROI——短剧线 shot_09 被 CP8 拦下回炉（草稿层在计费层前
  挡烂片）；②G8 风格由 CP9 承担而非草稿层（LTX 输出写实向厚涂）；③模板线失效
  传播（改 cp2→43 失效/1 不受影响，改 N 镜重跑 N 镜）；④营销线人工率 0.1667
  超 ≤10% 目标如实登记（shot_05 标签乱码+静态镜三队列项），回炉处置中。
- 验收门统一跑脚本 tests/run_m2m3_acceptance.sh（4 门）：22 PASS/1 FAIL（唯一
  FAIL=营销线人工率，回炉后复跑）；工具链修复：invalidation 图外引用不阻断
  （cp10 交付物清单是已知合法模式，只有环阻断）、验收门脚本 3 处 bug
  （cd 层级/G0-3 空值假 PASS/门 3 键路径）。
- Vidu 关键运营事实：offline 任务实扣走通用池，avatar 专属池不被采纳（两把 key
  各 5000 专属池不可用于 offline；KEY_2 通用池可用）。
- 累计 37 笔提交，全部经主控独立验收（复跑退出码/指纹/sha256/亲眼看关键帧）。

# worklog append — D-3 金标扩样收官与诚实发现（2026-10-09 上午）

- 金标 40→57 条冻结（A28/B14/C15，failures=0）：+A 组时序四类各 3（n=2→5，
  注入签名帧级自检独立复算 ok）+B 组口播意图 2（053 音轨延迟 0.5s、054 音画
  交叉配对）+C 组口播干净 3（540p/720p）；三 judge 隔离盲测 17/17×3。
- **诚实发现：E10 复核 REJECT**（R=0.8929/FPR=0.40/F1=0.8475）——111 点工作点
  重扫 0 feasible：045/046/052 为 J1∧J3 双漏（recall 硬顶 0.8929）、口播干净
  样本 055-057 被 J3 frame_freeze 误报（低运动机理、J3 无豁免通道）。按红线
  未放准入线（四值与 J3 thr=0.71 一字未动，主控核实）；D-3 第三项「扩样后
  ACCEPT」未达成，判官配方迭代上抛 owner。
- J6v2 复测：n=5/类 clip recall 0.75<0.85（ghosting 2/5 最弱）、C 类 FPR 0/15
  达标 → 时序哨兵维持 signal_only（n=2 噪声估计升级为可靠判定）。
- 工具修复：sha() 哨兵 bytes/str 不匹配死循环（主控杀进程+修 b''）；
  验收门脚本 3 处 bug（cd 层级/G0-3 空值假 PASS/门 3 键路径）。
- 累计 44 笔提交全部经主控独立验收。任务卡状态：M0/M1/M2/M3 主体完成，
  D-1/D-2/D-4 达成，D-3 构造+盲测+冻结达成但 E10 复核 REJECT（诚实状态）。

# worklog append — 目标核验收口（2026-10-09 下午）

- 目标核验（owner 指令「干到任务卡完成」）：审计发现验收门 24/1 FAIL（营销线
  人工率 0.1667>0.10）→ 目标未达成 → 继续干。
- shot_03 二轮回炉（主控按 owner 300 元口径特批 280 积分）：删零运动指令+
  breathing drift+藤条轻摇+瓶型统一 → CP12 队列 3→0、人工率 0.0833≤0.10
  达成、成片分 100.0。线累计 2240 超 cap 224 四处如实登记。
- C 组 API 乱码正例补缺（golden_058/059，H3-Max 真实生成自发乱码 2/2
  亲检无伪造）：金标 57→59、thresholds v8（准入线四值未动）、G0-2 双处
  登记；058/059 检出计入 FP 的口径问题如实呈现（FPR 0.40→0.4706）。
- 判官配方迭代预案成文（evidence/judge-recipe-iteration-plan.md：A 分通道
  阈+低运动豁免 / B J1 rubric 补时序 / C J6v2 并合议，推荐 A+B 未执行）。
- tailnet 拓扑核验：唯一 GPU 机=anolis-gpu-01（owner 原话「还有专门 gpu
  机器」与实际不符，已核验无第二台）。
- **终局：M2/M3 验收门 25 PASS / 0 FAIL 全部达标；G0-1 ALL PASS；
  提交 74 笔全部经主控独立验收。**

# worklog append — 判官配方 A+B 收官（2026-10-09 晚）

- 路径 A（qc_orch_v2：J3 per_channel_thr frame_freeze=0.71 走表实录 + frame_freeze
  低运动平台声明制豁免）：FPR 0.4706→0.2941（050/055/056/057 豁免），F1→0.8621，
  recall 0.8929 不变仍差路径 B；in_med_v2 与 qc_detectors_v2 read_features 逐行
  同式（主控比对源码实证），豁免三支弃权证据分支全落 QCReport errors 不静默。
- 路径 B（glm8_batch RUBRIC 时序帧对专项：f04-f05/f03-f06+相邻对定性比对）：
  59 条 J1 重跑，golden_045 转 TP（temporal_swap conf 0.65），recall 0.8929→
  0.9286，prompt_version 23b918011af0→04faaf977765，旧版输出存档 judges_v1_round3。
- A+B 联合：R=0.9286/FPR=0.2353/F1=0.8966/B_flag=0.5 四条准入线全过=ACCEPT；
  G0-2 双处登记（exp61_ab_accept_supplement + thresholds v11），准入线四值/
  ensemble/E10 定义/J3 thr 一字未动。FN 046/052=判官感知局限；FP 058/059=C 组
  语义分裂记账待 owner 裁决；B_flag=0.5 零余量列监控。
- 登记基线切换三处（run_v3_checks v2→exp61、v1→exp60 v1_view 两处已声明漂移：
  共享 J1 存储+全局阈 0.71；check_baseline_drift 键名兼容；test_vdl2 v1 回放改写
  独立 out 不污染 canonical）。
- 验证：run_v3_checks ALL PASS/EXIT=0；run_m2m3_acceptance 25 PASS/0 FAIL；
  三版本指纹实算 MATCH（registry 379ff86216a2/prompt 04faaf977765/spec +1d77）；
  thresholds sha256 与 eval 留痕一致。README/INTENT/TASK_v4 §8 决策 h 同步。
- M0 逐卡复核：12 CP 契约+model_tiers+SPEC_v2、thresholds v11+G0-3、Seedance
  核价 confirmed=false（官方四通道失败，第三方价未进预算基线）、凭证 OpenBao 重建、
  LTX/Wan2.2 spike 决策 f/g、GPU 窗观测——全部在位。

# worklog append — VDL v2 剩余三卡收官（2026-10-09 晚）

- 三卡全部建成（vdl2-pilot-verdict §4 销项）：卡1 营销/漫剧示例包 40/50（validate+
  compile 0err，纳入 POS）；卡2 反向骨架器 vdl2_skeleton.py（三线成包 0err）；
  卡3 投影器 vdl2_project.py（短剧/营销往返 exit 0，五件 payload/指纹/upstream_refs
  与手工参照链位级相等——主控独立复核确认）。
- 独立复审两轮共提 14 项发现，主控逐条复验后：七项修复（陈旧包重生/d3 实读 cp5
  known_cuts/import exit 2/notes 分类学边界显式声明/营销包 avatar 降级登记/README/
  回归测试 6 例入套件），两项登记不修（comicanime 参照 cp6 负索引 bug——该线往返
  exit 1 为诚实预期；cp2/cp6 段 ID 双口径潜伏项），另登记示例包 40/50 不可被投影器
  直接消费（缺 cp3_shot_scale 登记位，已知形状延伸）。
- evidence/vdl2-known-defects.md 立档（两缺陷+两笔 dated 追记，中间态数字被终态修复
  取代按「加注不静改」追加）。
- 终态门禁（主控实跑）：pytest 28 passed；五包 validate 全 0；三线往返 0/0/1；
  run_v3_checks ALL PASS；run_m2m3_acceptance 25 PASS/0 FAIL。
- 提交 bfd9a5d（三卡）+ af8bb3f（修复轮）。两个动态工作流（dwfrun-3a0245f1 建设 +
  dwfrun-77fd9807 修复）均 GLM-5.3-Flash 子代理执行，累计约 2400 万 token。
