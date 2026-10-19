# JUDGES-RERUN.md — 40 条 golden 三判官输出重建（J1 glm8 / J3 omnijev / J5 videochat3）

执行：判官重跑工程师（动态工作流子代理），2026-10-06 19:55–21:40（GPU 机 root@100.64.0.7，tailnet）。
任务：原夜判官输出灭失（见 archive g01-gpu-rerun.json gaps[2]），按原夜同配方重建 `数据/judges/{omnijev,glm8,videochat3}/` 各 40 条 + run_metadata.json，使 qc_orch_v2 回放可跑通。

## 0. 验收结论（先读）

- **E 组 qc_orch_v2 回放子项 exit=0 ✅**（仓内测试入口实测）：
  `cd /data/night/g01-rerun/video-capability/overnight/vpipe && /data/night/venv-vc3/bin/python tests/run_v3_checks.py`
  → `  [PASS] E qc_orch_v2 回放 exit=0 :: exit=0`
  独立直跑同一命令亦 `EXIT=0`：`clips=40 含降级 errors 的报告=0 契约校验失败=0 检出 28/40 {manual_review:15, auto_reject:13, pass:12}`。
- 三判官 数据/judges/ 各 40 条协议 JSON + 40 条 raw + run_metadata.json，无 FAILED 占位（脚本核验输出 ALL-CLEAN）。
- 测试套件整体仍 EXIT=1（8 项 FAIL）：B×3/C/D-syn/D-avatar 为替代素材缺口（与 archive 报告一致，非本轮范围）；E eval_run ACCEPT ×2 因重跑后 E10 集测 FPR=0.3333(4/12) 超准入线 0.30 被 REJECT（recall 1.0、F1 0.8889、B_flag 0.6667、schema 全过）——这是新判官数据的诚实实测，非格式/链路问题，见 §4/§5。

## 1. glm8 是什么（先查结论）

qc_orch_v2.py:633-636 J1 读取 `judges/glm8/<clip_id>.json` 六字段协议；thresholds.yaml judges.J1_glm8 注释「GLM-5.3-Flash 8帧 rubric, role=review_parallel」。仓内无 J1 batch 脚本——judge基准报告.md §1.2 记载「J1/J2 无运行记录…写盘为 8 批并行交错」、工程方案v3.md:38 记载 J1=「GLM-5.3-Flash 子代理 Read 8 帧 rubric」：**原夜 J1 是编码代理子代理读帧+rubric 的 API 判官，非本地权重**。故按任务指令用 zhipu 凭据（agent-tools/llm-env → BIGMODEL_API_KEY / BIGMODEL_BASE_URL=`https://open.bigmodel.cn/api/coding/paas/v4`）对 `glm-5.3-flash` 40 条真调（+4 条重试=44 次调用）。

## 2. 三判官运行命令（原样复刻）

### J3 omnijev（本地权重，原夜脚本原样）
脚本：/data/night/scripts/judges_batch/omnijev_batch.py（与仓 overnight/vpipe/judges_src/omnijev_batch.py diff 为零；launcher 复刻原夜 /data/night/judge_rerun/watch_launch_j35.sh 的参数）
```bash
CUDA_VISIBLE_DEVICES=0 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
/data/night/venv-judge/bin/python /data/night/scripts/judges_batch/omnijev_batch.py \
  --clips-dir /data/night/golden/clips \
  --out-dir /data/night/g01-rerun/video-capability/overnight/数据/judges/omnijev \
  --raw-dir /data/night/g01-rerun/video-capability/overnight/数据/judges/omnijev/raw \
  --src-dir /data/night/src/OmniJev-main \
  --ckpt /data/night/models/OmniJev-4B-v1.1 --base /data/night/models/Qwen3.5-4B \
  --meta /data/night/g01-rerun/video-capability/overnight/数据/judges/omnijev/run_metadata.json
```
结果：load 58.6s（chunk=9），40/40 ok 0 fail，lat avg 81.3s/clip，finished 2026-10-06 20:55:10。日志 /data/night/g01-rerun/logs_omnijev.txt。
注：transformers 提示 causal_conv1d / flash-linear-attention 未装、走 reference 慢实现——与本机 venv-judge 原状一致，未动环境。

### J5 videochat3（本地权重，原夜脚本原样）
```bash
CUDA_VISIBLE_DEVICES=0 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
/data/night/venv-vc3/bin/python /data/night/scripts/judges_batch/videochat3_batch.py \
  --clips-dir /data/night/golden/clips \
  --out-dir /data/night/g01-rerun/video-capability/overnight/数据/judges/videochat3 \
  --raw-dir /data/night/g01-rerun/video-capability/overnight/数据/judges/videochat3/raw \
  --frames-dir /data/night/g01-rerun/vc3_frames --model /data/night/models/VideoChat3-4B \
  --meta /data/night/g01-rerun/video-capability/overnight/数据/judges/videochat3/run_metadata.json
```
结果：input_mode=video(decord)（未退帧列表），load 30.2s，40/40 ok 0 fail，~3s/clip，finished 2026-10-06 21:26:01。日志 /data/night/g01-rerun/logs_vc3.txt。

### J1 glm8（API 真调，重建脚本）
脚本：/data/night/g01-rerun/glm8_batch.py（新建于仓外，未入仓未改仓源码；单 clip=1 次调用，8 帧 base64 随文，8 workers=原夜「8 批并行」口径，失败重试×3）
```bash
BIGMODEL_API_KEY=*** BIGMODEL_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4 \
/data/night/venv-vc3/bin/python /data/night/g01-rerun/glm8_batch.py \
  --manifest /data/night/g01-rerun/video-capability/overnight/vpipe/eval/golden_manifest.json \
  --out-dir /data/night/g01-rerun/video-capability/overnight/数据/judges/glm8 \
  --raw-dir /data/night/g01-rerun/video-capability/overnight/数据/judges/glm8/raw \
  --meta /data/night/g01-rerun/video-capability/overnight/数据/judges/glm8/run_metadata.json --workers 8
# 4 条推理超 token 失败后重试（max_tokens 4096→12000，workers 2）：
#   ... --meta /data/night/g01-rerun/glm8_retry_meta.json --workers 2 --max-tokens 12000 \
#       --only golden_005,golden_017,golden_019,golden_029
```
结果：主跑 36 ok / 4 fail（wall 1850.5s，prompt 260,716 + completion 62,676 tok）+ 重试 4 ok / 0 fail（39,092 + 28,737 tok）；合计 44 次调用、339,808 prompt + 91,413 completion ≈ 431k tokens。日志 /data/night/g01-rerun/logs_glm8.txt / logs_glm8_retry.txt。

### J1 prompt 模板（忠实重建依据，glm8_batch.py RUBRIC 常量）
- 协议=边界测试方案.md §2.3 盲测六字段 {"clip_id","defect_detected","defect_types","confidence","spans","notes"}；
- 8 类缺陷定义逐字取 judge_common.py DEFECT_ZH（原夜三判官共享的冻结文案）；
- B 类词表（hand_anomaly/count_error/physics_error/identity_drift/other）按原夜 glm8 输出实证词表——原夜 40 条已从仓内 tracked 的 out/qc_reports_v2/ 40 份报告 judges.J1 字段一字不差提取（判官输出嵌入报告时一字不改，qc_orch_v2.py 回放语义），存 /data/night/g01-rerun/reference/orig_judges_extracted/{glm8,omnijev,videochat3}/；
- rubric 含「盲测 / 相邻帧定性对比禁止口算数值 / 结论引用帧号 / 无缺陷如实判干净」纪律（对齐 judge基准报告 §10 forbidden=mental_math_frame_diff 与 B 类维度）；
- 幅面元数据只给 clip_id/时长/帧序时间戳（(i-0.5)·dur/8），不给金标标签。

## 3. 输出落位（qc_orch_v2.py:601-655 断言全满足）

```
数据/judges/omnijev/    golden_001..040.json（六字段）+ raw/40 + run_metadata.json（clips[].probs 供回放 J3 通道）
数据/judges/glm8/       golden_001..040.json（六字段）+ raw/40 + run_metadata.json（模型/耗时/token 留档）
数据/judges/videochat3/ golden_001..040.json（六字段）+ raw/40 + run_metadata.json
```
（数据/judges/detectors/raw/ 原夜 J6 特征未灭失，未动。）

## 4. 重建 vs 原夜对照（诚实差异）

| 项 | 原夜（reference/ 提取） | 本轮重跑 | 说明 |
|---|---|---|---|
| J5 videochat3 检出/类型 | 6/40 {pixelate2,face_blur2,flicker1,ghosting1} | 6/40 {pixelate2,face_blur2,ghosting2} | 几乎复现（do_sample=False 同权重同卡型） |
| J3 omnijev 协议检出(阈0.5) | 40/40 全 flag | 38/40 | 概率整体略移（torch 2.7/reference 实现/驱动代次差）；回放判定走 yaml thr=0.70，不受协议阈影响 |
| J1 glm8 检出 | 22/40 | 17/40（36+4） | 重建 rubric 的真实再判，非逐条复刻；golden_028 本轮抓到 freeze（原夜漏）、017/029 仍 clean、005 报 flicker+garble（原夜 garble）、019 本轮 clean（原夜检出） |
| E10 回放指标 | R1.000/FPR0.250/F1 0.9143/B_flag 0.8333 | R1.000/FPR0.3333(4/12)/F1 0.8889/B_flag 0.6667 | eval_run REJECT 仅因 fpr_max 0.3333>0.30（误报 3→4 条；明细见 eval/eval_results_v3post.json） |

原夜判官 JSON 从 tracked 报告提取仅作对照/词表依据，**未拷贝进 数据/judges/**——数据/judges/ 全部为本轮真跑产物。

## 5. 遗留红项（非本轮范围）

- E eval_run ACCEPT ×2 REJECT：FPR 4/12=0.3333 超准入线 0.30。按 SPEC 修改规程，要么重扫 yaml 阈值要么迭代 J1 rubric 后复测——属判官配方迭代，不属于「重建数据」。
- B/C/D-syn/D-avatar：替代素材缺口（dh 原片/j6_v2 合成片灭失），同 archive g01 报告，本轮未触。
- 仓内 tracked 运行产物被回放覆盖（eval_results_v3post*、out/qc_reports_v3post/、out/asset_manifest_v3post* —— git status M 全部限于 eval/、out/ 运行产物）：**源码零改动**（src/、judges_src/、contracts/、eval/thresholds.yaml 等未触）。

## 6. 环境

GPU 0 = Tesla V100S-PCIE-32GB（开跑时卡0 空闲 310MiB；卡1 被占 26.8GiB 未触）。venv-judge / venv-vc3（transformers 4.57.6, decord, qwen_vl_utils, torch 2.7.0+cu126, py3.11.6）。仓 clone @0d1d9d6。
凭据来源：本机 /home/pan-ding/workspace/agent-tools/llm-env（zhipu → company/LLM-upstream/Zhipu/zhipu-bigmodel-CodingPlan-1），以环境变量注入远端进程，未落盘 key。
