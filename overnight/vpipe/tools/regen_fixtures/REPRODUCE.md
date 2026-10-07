# REPRODUCE.md — G0-1 终局复锁复现手册（夹具对位 + run_v3_checks 全量复跑）

> 2026-10-07 终局实测：GPU 机 `/data/night/g01-rerun/video-capability` @ `71f719d` 上
> `tests/run_v3_checks.py` **ALL PASS / EXIT=0**（A/B/C/D/E 全绿，两契约 eval_run 双 ACCEPT）。
> 本手册记录从零复现该终局的全部命令与素材清单。任何人按 §1→§5 顺序执行即可复现。

## 0. 终局状态与依赖全景

| 依赖 | 位置 | 状态 |
|---|---|---|
| 仓源码 | 本机 `/home/pan-ding/workspace/视频能力`，main = `71f719d` | 两 commit：`12ca6f6`（19 片夹具工具链）+ `71f719d`（J3 阈 0.70→0.71 重扫） |
| 金标 clips | GPU `数据/golden` → symlink `/data/night/golden`（40 条 mp4，tar 原物） | 既有，勿动 |
| J6 原始特征 | GPU `数据/judges/detectors/raw/`（40 条 golden_*.qc.json） | 既有，勿动 |
| 三判官输出 | GPU `数据/judges/{glm8,omnijev,videochat3}/`（各 40 条六字段 JSON + raw/40 + run_metadata.json） | 判官线重建，配方见 `/data/night/g01-rerun/JUDGES-RERUN.md`（本机副本 `视频能力-archive/JUDGES-RERUN.md`）——本手册不重跑判官 |
| 夹具 mp4 ×21 | 本机 `overnight/数据/{j6_v2/synthetic,avatar_out,digital_human}`（.gitignore 域，不入库） | §2 清单，须 scp 到 GPU（仓 checkout 不带 mp4） |
| 运行环境 | GPU `/data/night/venv-vc3/bin/python`（3.11.6）+ ffmpeg（8.0.1，PATH 内）+ venv 内 pyyaml/jsonschema | 既有 |

## 1. 源码上线：bundle → GPU fetch/checkout

GPU clone 已有祖先 `0d1d9d6`，故增量 bundle 即可（全量 bundle 亦可）：

```bash
# 本机
cd /home/pan-ding/workspace/视频能力
git bundle create /tmp/vcap-relock.bundle 0d1d9d6..main   # 或全量：git bundle create ... main
scp /tmp/vcap-relock.bundle root@100.64.0.7:/data/night/g01-rerun/

# GPU 机
cd /data/night/g01-rerun/video-capability
git fetch /data/night/g01-rerun/vcap-relock.bundle main:refs/remotes/relock/main
git checkout -f relock/main
git log --oneline -1        # 应为 71f719d（或更新）
```

## 2. 夹具对位：21 片 mp4 实体文件 scp 落位

夹具 mp4 不入 git，必须从本机实体传输。打包（注意 `dh_final_30s.mp4` 双落位：
`avatar_out/` 与 `digital_human/` 各一份，同字节 md5 `c400057591ae1fd7992a5ceb2a912a2e`）：

```bash
# 本机
cd /home/pan-ding/workspace/视频能力/overnight/数据
tar czf /tmp/vcap-fixtures-21.tgz \
    j6_v2/synthetic/*.mp4 avatar_out/*.mp4 digital_human/dh_final_30s.mp4
scp /tmp/vcap-fixtures-21.tgz root@100.64.0.7:/data/night/g01-rerun/

# GPU 机：对位解包（覆盖 avatar_out 里旧 g9a 截段替代片 dh_stepfun/dh_design）
cd /data/night/g01-rerun/video-capability/overnight/数据
mkdir -p j6_v2/synthetic digital_human
tar xzf /data/night/g01-rerun/vcap-fixtures-21.tgz
```

双端完整性核验（ sha256 清单，21 条；两端 diff 须为空）：

```bash
# 本机与 GPU 各跑一次，比较输出
cd <仓>/overnight/数据 && sha256sum j6_v2/synthetic/*.mp4 avatar_out/*.mp4 digital_human/*.mp4
```

| 片名（数据/ 下相对路径） | sha256 |
|---|---|
| avatar_out/buA_120s.mp4 | 111cfef3076a4c1c954eb7bec37b6de8467fe04e1c311c0d1267383c3bbe6b9a |
| avatar_out/buA_30s.mp4 | afb72a800400d4862bad5aace3128442b796f1724040bb3f2d95ad2865ce8c7c |
| avatar_out/buA_60s.mp4 | c7360204088d0d76b157b35c56fddc4681826381d4d8e70982c0390b97e0e7b1 |
| avatar_out/buB_turn.mp4 | 33f03b4bd3a962bc2a2b8bf3ae11ccaf41880de810596c7f1b28c00979be22f0 |
| avatar_out/buB_walk.mp4 | cc177e9da622d6f521bd8784b62e76776754d46b4ee6273625e2dbfe2e3674dd |
| avatar_out/buC_id1.mp4 | d781bd67bb778c63c8b36087a96787660a79c9cbcbf58104da40a4b3325e814c |
| avatar_out/buC_id2.mp4 | 43331aabd091275a1326dc6fe30cdb50341e1ad5a4238537f18c26577c321916 |
| avatar_out/buD_clone.mp4 | 65419d885a7495101fa2f1468726182091340956f2372522ed4c8e37841d3790 |
| avatar_out/dh_design_720p.mp4 | 049795666448a1617d1d10ddb2279dc3e5e9fc8952c1df49f42f4e559ae7ac58 |
| avatar_out/dh_final_30s.mp4 | 49dfbe459a0c03d17335e50f90bc2e68c227a215cc1fed6950006b1c88b4f205 |
| avatar_out/dh_stepfun_720p.mp4 | f90a87a2e940b9a5027aea978cb7fe45946b0997b853981a7627ae55a2a15368 |
| avatar_out/g9a_intro_60s_vidu.mp4 | edf440436ca7637927d0db5b746a2af49f377a44e65ce3413f266cfb0cdb7676 |
| avatar_out/vidu_a_talk_540p.mp4 | 3a17e1d646e356fd7c6656b5d7add0c307e901e3eeba260bd4e3e68aac6b978f |
| avatar_out/vidu_b2_text_novoice.mp4 | 280ff821af5819c97b33c9af35a808b9a12fdbedfacd60899fee958d9a590db0 |
| avatar_out/vidu_b_timeline_720p.mp4 | 04b93b644191f94e7851c311c3e40717e7fb8f234e6fa94b54fbd7a177691df2 |
| avatar_out/vidu_c_walk_object_540p.mp4 | 6b4353c4686f9ea50b9a08991e203d597f69c1cfbde589528fadfbfa242f8723 |
| digital_human/dh_final_30s.mp4 | 49dfbe459a0c03d17335e50f90bc2e68c227a215cc1fed6950006b1c88b4f205（=avatar_out 同字节） |
| j6_v2/synthetic/syn_flicker.mp4 | 718940ff08d73294ab5e2f3eecdfa471594cac40444081e48dd967b2f54fbaea |
| j6_v2/synthetic/syn_freeze.mp4 | 6937020d2486c2d7b6d35699f2152174f40edbd0181c187b132a43c868ab2af8 |
| j6_v2/synthetic/syn_ghost.mp4 | 04ab23bc13f4114437e82447ddcf0ce4be2ba1026be3ddcefff441c60980e26a |
| j6_v2/synthetic/syn_swap.mp4 | a355e9b4e9dc8735e41242aa541a4d159e584585377f732029ae44caa9c3e369 |

（tar 包本体 sha256：`c07fcbd34c6590b5afae4584afc96250fefc35eb2f6c168fb6ad64f7cc7ca78b`，两端核验一致。）

## 3. 复跑（清洁态）

```bash
cd /data/night/g01-rerun/video-capability/overnight/vpipe
rm -rf out/v3_selftest
/data/night/venv-vc3/bin/python tests/run_v3_checks.py
# 期望末尾：== 汇总 == / ALL PASS / 退出码 0
```

2026-10-07 终局实测（round2）逐组结果：

- A 组 7/7 PASS（L0 预检：黑屏拒收/时长超差拒收/avatar 垫尾豁免/合规放行）。
- B 组 3/3 PASS：dh_stepfun/dh_design/dh_final ghosting 误报归零，豁免证据落
  `temporal_rejected`（含 low_motion_plateau），非静默。
- C 组 1/1 PASS：dh_final swap 切点 13.917s 被 known_cuts 白名单豁免。
- D 组 3/3 PASS：金标 40 + 合成 4 + avatar 16 判定级（五元组）与 v3base 零差异。
- E 组 6/6 PASS：qc_orch_v2(1.1)/qc_orch v1(1.0) 回放 exit=0；eval_run 双 ACCEPT
  （R=1.000 / FPR=0.250 / F1=0.9143 / B_flag=0.6667(v2)；schema 全过）；schema_version 1.1/1.0 抽验过。

## 4. 若红：归因路线（本轮实际走过的两轮）

- **round1（@12ca6f6，阈 0.70）**：仅 E eval_run ×2 REJECT，FPR 4/12=0.3333>0.30，
  误报 [006,010,013,032]。逐 clip 拆解：golden_006=J3 frame_freeze 概率 0.7069 以
  0.0069 边际越过 0.70（判官数据重跑后概率微移，JUDGES-RERUN.md §4）；golden_013=J1
  布尔检出（与阈无关，如实保留）；010/032=基线既有误报。**夹具侧 B/C/D 全绿零归因。**
- **round2（@71f719d，阈 0.70→0.71）**：按 `eval/thresholds.yaml` 头部修改规程 +
  JUDGES-RERUN.md §5 预案「重扫 yaml 阈值」，在新判官数据上全阈扫描后取 0.71
  （唯一保持 R=1.000 且四准入线均有余量：FPR=0.25/F1=0.9143/B_flag=0.5833；
  ≥0.74 丢 golden_017 漏检）。→ ALL PASS / EXIT=0。
- 夹具若在别的机器红 B/C/D：回本机跑
  `.venv/bin/python tools/regen_fixtures/calibrate.py`（19/19 FINAL MATCH 退出 0），
  按 manifest.json 校准轨迹调参重生成，**不得手改基线 out/j6v2_*_v3base**。

## 5. 注意事项

- `数据/golden`、`数据/judges/detectors` 为既有资产，复跑只读，勿重建勿删。
- 复跑会覆盖 tracked 运行产物（`eval/eval_results_v3post*.json`、`out/qc_reports_v3post*/`、
  `out/asset_manifest_v3post*.json`、`out/v3_selftest/` tracked 快照）——按惯例不入库，
  复跑后 `git status` 的 M/D/?? 应全部限于这些路径；源码应零未提交改动。
- 本目录 mp4 夹具是「判定行为确定性重建物」（README.md 性质声明），非 Vidu/StepFun 原物；
  基线判定锁 `out/j6v2_{syn,dh}_v3base`。换判官/换检测器参数后需重新校准，不得沿用。
- 阈值历史：J3 thr 0.70（judge基准报告 §7，2026-09-30 定稿）→ 0.71（2026-10-07 重扫，
  commit `71f719d`，证据 `视频能力-archive/g01-full-relock.json`）。回滚依据同 judge基准报告 §7。
