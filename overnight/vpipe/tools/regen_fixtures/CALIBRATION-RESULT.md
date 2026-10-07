# CALIBRATION-RESULT — 19 片全量校准复核终值（2026-10-07 收尾验收）

> **夹具性质声明（与 README.md 同口径，必读）**
> **原片灭失。本批 19 片为检测器回归夹具——按仓内基线判定特征确定性注入伪影的重建物，
> 不是 Vidu / StepFun / MiniMax 原物，不冒充原物。** 重建目标是"判定行为"（检出/类型/
> 置信度/弃权键五元组），不是画面内容；基线 `out/j6v2_{syn,dh}_v3base/*.qc2.json`
> 一个字节未改（本次收尾 `git status` 干净可证）。唯一例外：g9a_intro_60s_vidu 为
> 仓内 tracked 原物直接拷贝（`out/avatar_demo/g9a_intro_60s@vidu-s1.mp4`），免重建。

## 复核方法（本会话实测）

1. **全量重校准**：`cd overnight/vpipe && .venv/bin/python tools/regen_fixtures/calibrate.py`
   ——19 片逐片闭环重渲+重判，**19/19 FINAL MATCH，mismatches: none**（EXIT=0）。
   实际耗时 418.4 s（≈7 分钟，远低于 README 估计的 40–60 分钟；未触及 90 分钟降级线）。
2. **独立对照**（不复用 calibrate.py 的内部 match，按 `tests/run_v3_checks.py` D 组口径）：
   对 `数据/j6_v2/synthetic` 与 `数据/avatar_out` 批量重跑
   `src/qc_detectors_v2.py --batch`（与 D 组同一代码路径），逐片以
   `judgment_of`（run_v3_checks.py:58-67）五元组——clip_id / detected / types /
   confidence / rejected_keys——对基线 qc2.json **精确相等**比对（D 组无数值容差）。
   **20/20 MATCH（19 重建片 + g9a 原物），零差异。**

## 逐片终值表（目标=基线 qc2.json；实测=独立批量重跑 2026-10-07）

| # | 片名 | 目标判定（检出/类型/conf） | 实测判定 | 差值 |
|---|------|--------------------------|----------|------|
| 1 | syn_flicker | flicker / **0.95** / rej=[] | 同 | 0.000，全同 |
| 2 | syn_freeze | frame_freeze+temporal_swap / **0.7** / rej=[] | 同 | 0.000，全同 |
| 3 | syn_ghost | ghosting / **0.802** / rej=[] | 同 | 0.000，全同 |
| 4 | syn_swap | temporal_swap / **0.663** / rej=[] | 同 | 0.000，全同 |
| 5 | dh_stepfun_720p | ghosting / **0.766** / rej=[] | 同 | 0.000，全同 |
| 6 | dh_design_720p | ghosting / **0.643** / rej=[] | 同 | 0.000，全同 |
| 7 | dh_final_30s | ghosting+temporal_swap / **0.821**（swap 切点 13.917s±0.5） | 同（切点恰 13.917） | 0.000，全同 |
| 8 | buA_120s | ghosting / **0.771** / rej=[] | 同 | 0.000，全同 |
| 9 | buA_30s | ghosting / **0.685** / rej=[] | 同 | 0.000，全同 |
| 10 | buA_60s | ghosting / **0.911** / rej=[] | 同 | 0.000，全同 |
| 11 | buB_turn | 干净（未检出 / conf 1.0 / 零候选零弃权） | 同 | 全同 |
| 12 | buB_walk | 干净 | 同 | 全同 |
| 13 | buC_id1 | 干净 | 同 | 全同 |
| 14 | buC_id2 | ghosting / **0.846** / rej=[] | 同 | 0.000，全同 |
| 15 | buD_clone | 干净 | 同 | 全同 |
| 16 | vidu_a_talk_540p | 干净 | 同 | 全同 |
| 17 | vidu_b2_text_novoice | 干净 | 同 | 全同 |
| 18 | vidu_b_timeline_720p | ghosting / **0.837** / rej=[] | 同 | 0.000，全同 |
| 19 | vidu_c_walk_object_540p | ghosting / **0.87** / rej=[] | 同 | 0.000，全同 |
| — | g9a_intro_60s_vidu（原物拷贝，免重建） | ghosting / **0.623** | ghosting / 0.623 | 0.000，全同 |

实测证据（ghost 候选：dur_s/dip_ratio/in_med/out_med；swap：cut_t/back_score）：

| 片 | 证据 |
|---|---|
| buA_120s | ghost dur=2.0 dip=0.416 in=1.329 out=3.191 |
| buA_30s | ghost dur=1.75 dip=0.56 in=0.736 out=1.315 |
| buA_60s | ghost dur=3.0 dip=0.171 in=1.61 out=9.411 |
| buC_id2 | ghost dur=3.0 dip=0.45 in=1.522 out=3.386 |
| dh_design_720p | ghost dur=1.5 dip=0.518 in=1.678 out=3.237（in_med<2.0 低运动平台口径 ✓） |
| dh_final_30s | ghost dur=2.25 dip=0.423 in=0.705 out=1.667；swap cut=13.917 back=0.9452 |
| dh_stepfun_720p | ghost dur=2.042 dip=0.472 in=0.903 out=1.914（in_med<2.0 ✓） |
| vidu_b_timeline_720p | ghost dur=2.25 dip=0.353 in=1.054 out=2.989 |
| vidu_c_walk_object_540p | ghost dur=3.25 dip=0.345 in=1.441 out=4.179 |
| syn_ghost | ghost dur=2.25 dip=0.506 in=3.097 out=6.117 |
| syn_freeze | freeze conf=0.7 dur=2.0；swap cut=7.167 back=0.8522 |
| syn_swap | swap cut=2.5 back=0.9349 |
| 干净 6 片（buB_turn/walk、buC_id1、buD_clone、vidu_a/b2） | 零候选零弃权 |
| syn_flicker | flicker conf=0.95（无时序候选，flicker 通道检出） |

### 证据级（非锁定字段）与基线的已知差异——不影响五元组，如实列出

五元组锁定"判定"；候选证据内**不进判定公式锁定量**的字段允许浮动（D 组口径：判定未变
即行为未变）。实测 4 处：

| 片·候选 | 基线 | 夹具实测 | 判定影响 |
|---|---|---|---|
| syn_freeze·temporal_swap conf | 0.614 | 0.553 | 无（整体 conf=0.7 由 freeze 候选决定；swap 同为 emit 型候选） |
| dh_final_30s·temporal_swap conf/back | 0.72 / 0.9775 | 0.677 / 0.9452 | 无（整体 conf=0.821 由 ghost 候选决定；cut_t 恰 13.917 锁定） |
| dh_final_30s·ghosting dip_ratio | 0.425 | 0.423 | 无（conf 公式同输出 0.821） |
| syn_swap·temporal_swap back_score | 0.8396 | 0.9349 | 无（conf 公式同输出 0.663——夹具按 BACK_WIN 窗 0.9344-0.9351 反解） |

## 收尾断言（`rm -rf out/v3_selftest` 后全量跑 `tests/run_v3_checks.py`，2026-10-07）

- **A 组 6/6 PASS**（L0 预检接线）。
- **B 组 3/3 PASS**：dh_stepfun / dh_design / dh_final ghosting 误报归零，豁免证据落
  `temporal_rejected`（含 low_motion_plateau），非静默。
- **C 组 1/1 PASS**：dh_final swap 切点 13.917s 被 known_cuts 白名单豁免。
- **D 组 3/3 PASS**：金标 40 条 + 合成 4 条 + avatar 16 条判定级比对，diffs=[]。
- **E 组 2 FAIL（预期红，如实记录）**：eval_run v2(1.1) 与 v1(1.0) 均 REJECT——
  recall 0.0 / F1 None vs 报告 E10 基线 recall 1.0 / F1 0.9143。原因与夹具无关：
  E 组回放依赖 GPU 机产出的 judge 原始输出，该数据已灭失（README.md"已知边界"
  所载"J3/J1/J5 判官层、E 组 eval judge 输出灭失，g01 同因红"）。fixture 射程内的
  B/C/D 全绿，无需动任何注入参数（迭代轮数 0/3）。
- 汇总 EXIT=1（仅 E 组两红；A/B/C/D 全绿）。

## 收尾处置记录

- **vdl2_tests/ 运行残留**：9 个改动文件（compile_report/execution_plan/slots）diff
  全部为 `compiled_at` 时间戳（2026-10-06T15:05→15:11，前任跑 test_vdl2.py 重编译
  所致），判定为运行产物，已 `git checkout` 还原，不入库。
- **out/v3_selftest/**：按验收规程 rm -rf 后由本次 run_v3_checks.py 重新生成。目录在
  HEAD 有 2026-10-01 旧机时期的 tracked 快照，本次刷新属运行产物，按提交范围
  （工具+README+manifest）不入库、留待下次提交裁量。
- **calibrate.py 一处收尾修复（不涉注入参数/基线）**：g9a 分支原逻辑
  `if not g9a_dst.exists()` 同时把持"拷贝"与"manifest 落记录"，文件已存在的机器上
  重跑会丢失 g9a 的 provenance/验证记录（前后两版 manifest 均缺该条，已核实）。改为
  拷贝按需、验证与落记录必做；复跑后 manifest 20 片（19 重建 + g9a original_copy）
  全 match。
- **dh_final 双落位同字节**：avatar_out 与 digital_human 两份 md5 一致
  （c400057591ae1fd7992a5ceb2a912a2e）。

## 产物与入库

- mp4 夹具落 `数据/`（`.gitignore` 覆盖 `overnight/数据/`，不入库）——与仓内惯例一致：
  `git ls-files` 核实金标 clips（数据/golden/clips）无 tracked mp4。
- 入库范围：本目录 `gen_fixtures.py` + `calibrate.py` + `README.md` +
  `manifest.json`（20 片最终 knobs、判定、基线目标、match、校准轨迹）+ 本文件。
- 基线 `out/j6v2_syn_v3base/`、`out/j6v2_dh_v3base/` 一个字节未改。
- 不 push。
