# regen_fixtures — J6v2 检测器回归夹具重建（19 片）

> **诚实性声明（必读）**
> **原片灭失，本目录产物为检测器回归夹具，不是 Vidu / StepFun / MiniMax 原物，不冒充原物。**
> 依据 g01 GPU 复锁报告（`视频能力-archive/g01-gpu-rerun.json`，2026-10-06）：B/C/D 三组红
> 全部可归因素材缺口——dh 数字人原片（avatar_out 15 条 + digital_human/dh_final_30s.mp4）灭失、
> j6_v2/synthetic 4 条合成片"无生成器入仓、归档无、GPU 本地无——全域核实"。
> 本工具链按仓内锁定的基线判定**确定性重建**这 19 片，专用于 `tests/run_v3_checks.py`
> 的 B/C/D 组检测器回归；任何"这条视频长什么样"层面的用途都不成立。

## 为什么 fresh Vidu 再生成对不上基线

基线判定（检出/类型/置信度 0.001 精度/弃权键）是**内容指纹的函数**：160px 缩略图上的
逐帧 Pearson 相关、帧差 MAD、Laplacian 方差的时序统计由逐像素内容唯一决定。g01 实测已证：
用 avatar_demo 截段顶替 dh 原片后，判定从 `ghosting conf 0.766` 变为 `clean conf 1.0`
（g01 报告 D-avatar 条目："内容指纹实质被校验，替代物如实红"）。同通道 fresh 再生成即便
提示词一致，采样噪声也使逐帧指纹不可复现——这不是工程瑕疵，是判据性质。因此唯一出路是
把"判定"本身作为重建目标：**夹具 = 按基线声明特征确定性注入伪影的重建物**。

## 基线（锁在仓内，一个字节未改）

`out/j6v2_syn_v3base/*.qc2.json`（4 片）与 `out/j6v2_dh_v3base/*.qc2.json`（16 片），
判定目标（judgment_of 五元组）：

| 组 | 目标 |
|---|---|
| syn | flicker **0.95**；freeze **0.70**+swap 0.614；ghost **0.802**；swap **0.663** |
| avatar | buA_120s ghosting **0.771**；dh_stepfun **0.766**；dh_design **0.643**；dh_final ghosting+swap **0.821**（swap 0.72@13.917s）；buA_30s **0.685**；buA_60s **0.911**；buC_id2 **0.846**；vidu_b **0.837**；vidu_c **0.870**；buB_turn/buB_walk/buC_id1/buD_clone/vidu_a/vidu_b2 干净（1.0）；g9a_intro_60s_vidu 原物在仓（0.623，本会话实测复现，免重建） |

注意：任务背景将 buA_30s/60s、buC_id2、vidu_b、vidu_c 描述为"干净"，与仓内基线 qc2.json
不符（这 5 片基线均为 ghosting 检出）。**以仓内 qc2.json 为准**，夹具按实录判定校准。

## 生成器原理（gen_fixtures.py）

基座：seeded 正弦场画布（`numpy.random.RandomState(seed)`，48 个 λ∈[40,120]px 分量、
Σamp=200、确定性）匀速亚像素平移（`cv2.warpAffine` INTER_LINEAR）→ gray8 →
libx264 yuv420p，精确 n 帧 @24fps。判定只依赖时序统计结构（160px 特征缩略图，内容
不敏感）。选择合成基座的原因：仓内真实素材（golden ~5-10s、g9a 61s 单条）无法提供
6-120s **无切点连续单镜头**，而循环/拼接真实素材必然制造硬切+后向重入 = 结构性
temporal_swap 误报，与"干净片零候选零弃权"基线矛盾。

注入机理与原误报机理一一对应（工程方案v3.1.md §3.4）：

| kind | 机理 | 对应原片故事 |
|---|---|---|
| `ghost` | 时间重映射慢速窗：位置函数在 [f1, f1+win] 内减速 r 倍（连续 kink，无跳变）→ 帧差矩形凹窗（dip_ratio≈r），laplacian 不塌（不触发 lap 支）、窗内中位保持 ≥~0.9（不落 frame_freeze 的 0.8 长跑）；dh 三片 in_med<2.0 落**低运动平台**口径 | 口播自然停顿被 rect_dip 误读为混叠 |
| `freeze` | 采样位置定格 49 帧（48 对帧差≈0）+ 回放跳切 | 定格 2s 注入 |
| `flicker` | 亮度 ±8 全通道等量逐帧符号交替（饱和度不变，50 帧 → ~50 事件/2.1s） | 恒定曝光偏移注入 |
| `swap` | 硬切回放：切点后以速度 s 回放自 t_r 的内容，y 向偏移 d0 压后向相似度（长 λ 画布上 y 移位须避开主导 fy 分量反相位带，dh_final 用 x 向 + 长波长画布） | 同人物 A/B 拼接回放（dh_final 13.917s） |

## 有效参数的关键发现

`load_params()`（qc_detectors_v2.py:122-131）只读 `judges.J6_detectors_v2` 的**平铺键**，
而 thresholds.yaml 该节只有 `role/rule_params/measured_on_golden` 三个子键——**yaml 实际
零覆盖，检测器始终跑 DEFAULT_PARAMS（ghost_min_s=1.2 等）**；yaml rule_params 的
1.5 是文档注记不生效。这解释了基线 qc2 录得 1.2、g01 D-golden 40/40 零偏差。
校准按 DEFAULT_PARAMS 解析。

## 校准（calibrate.py）

对每片闭环：渲染 → `qc_detectors_v2.analyze_clip`（与 CLI 同一代码路径，CPU 秒级）
→ 读 temporal_candidates 证据（out_med/in_med/dur_s/dip_ratio/back_score）→ 修正参数 →
直至 `judgment_of` 五元组与基线一致。要点：

- **conf 解析**：ghost conf = `0.55 + 0.25·min(1,(dur−1.2)/1.2) + 0.15·(0.65−dip)/0.65`
  （qc_detectors_v2.py:430，有效参数）。
- **win 不动点**：dur 由 win+尾部（端部跨窗滑窗的中位翻转，±3-16 帧随 r/win 漂移）决定，
  不可解析——用不动点 `win += round((dur_target−dur_measured)·24)` 把 dur 持在目标值，
  want dip 由此恒定，r 二分稳定收敛。
- **r 二分**：dip(r) 单调（深→浅），None 有两义（越可检出墙=过浅 / 短窗 dur<ghost_min_s
  被拒=过深），用最近一次检出 r 消歧方向。
- **d0 轴**：y 向移位在长 λ 画布会命中主导 fy 分量的反相位带（corr 变负且非单调，
  dh_final 实测 back 0.24-0.43 恒定）→ dh_final 用 x 向移位 + 长波长画布
  （λ 120-240px，漂移 0.165 thumb-px 处相关≈1）。
- **out_min 交互**：ghost_out_min=1.2 地板 vs swap 块均值天花板（回放段内容过快则
  非对齐对去相关、back<0.85）——dh_final 取 out≈1.35 折中（v 1.5）。
- **安全带**：基底运动量 out_med 使窗内中位 ≥0.9（不落 frame_freeze 0.8 长跑）、
  <cut_free 15（不破坏 ghost_cut_free 检查）、dh 三片 in_med<2.0（B 组 plateau 豁免）。
- 校准轨迹全录 `manifest.json`（每片 final knobs + 逐迭代判定 + baseline 目标 + match）。

## 产物落位（run_v3_checks.py 断言路径；gitignore `overnight/数据/` 域，不入库）

```
overnight/数据/j6_v2/synthetic/syn_{flicker,freeze,ghost,swap}.mp4          # D-syn
overnight/数据/avatar_out/{bu*,vidu_*,dh_*}.mp4 (15) + g9a_intro_60s_vidu.mp4  # D-avatar
overnight/数据/digital_human/dh_final_30s.mp4                               # B/C（与 avatar_out 同字节）
```

`数据/golden/`、`数据/judges/detectors/raw` 自归档
`视频能力-archive/night-data-assets-20261005.tar.gz`（sha256 7935d096…，与 g01 报告一致）
恢复：解压至 `数据/_archive-20261005/` 后软链。g9a 原物取自仓内 tracked
`out/avatar_demo/g9a_intro_60s@vidu-s1.mp4`（本会话实测判定 0.623 与基线零偏差，原样拷贝）。

## 复跑

```bash
.venv/bin/python overnight/vpipe/tools/regen_fixtures/calibrate.py    # 全量 19 片（约 40-60 分钟）
.venv/bin/python overnight/vpipe/tests/run_v3_checks.py               # B/C/D 断言
```

## 已知边界

- 夹具重建的是**判定行为**，不是原片内容——J3/J1/J5 等判官层、E 组 eval（judge 输出灭失，
  g01 同因红）不在本工具射程内。
- bu/vidu 系分辨率时长按基线 clip_meta 对齐（时长精确到帧，fps=24）；原始宽高文档未全载，
  统一采用 1280×720（vidu 540p 档 960×540、dh 竖屏档 826×1114，对齐 g01 报告所载 dh 口径），
  判定对该口径不敏感（160px 特征缩略图）。
- 基线 `dh_final_30s.mp4` 原 md5 289f96f3…（工程方案v3.1.md:323）——本夹具为重建物，
  内容指纹必然不同，如实声明。
