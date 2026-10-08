# 卡 1 显存窗口观测（M0-W2 GPU spike 选窗）

- 观测人：GPU 窗口探查员（ZCode 子代理）
- 观测日期：2026-10-08 20:44–21:02 (+0800)
- 目标机：root@100.64.0.7（anolis-gpu-01，2× Tesla V100S-PCIE-32GB）
- spike 需求：Wan2.2-5B 峰值 <30GB；LTX-Video ~16GB
- 红线合规：全程 SSH 只读命令（ConnectTimeout=10, BatchMode=yes）；未在 GPU 机写任何文件、未杀进程、未装包、未跑任何 GPU 计算（仅 nvidia-smi 查询与 localhost GET /health）；无下载。采样循环在本机 sleep 分段，每样本独立短连接，未挂长 SSH。

## 1. 观测方法

本机后台循环：每 60 秒向 GPU 机发一条只读查询，共 16 个样本、跨度 15 分 09 秒，16/16 成功（rc=0）：

```
$ ssh -o ConnectTimeout=10 -o BatchMode=yes root@100.64.0.7 \
    "nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits"
```

## 2. 时间序列（16 样本，2026-10-08 +0800）

| # | 采样时刻 | 卡0 used (MiB) | 卡0 util | 卡1 used (MiB) | 卡1 util |
|---|---|---|---|---|---|
| 1 | 20:44:57 | 310 | 0% | 27286 | 31% |
| 2 | 20:45:58 | 310 | 0% | 27668 | 0% |
| 3 | 20:46:58 | 310 | 0% | 27668 | 0% |
| 4 | 20:47:59 | 310 | 0% | 27668 | 0% |
| 5 | 20:48:59 | 310 | 0% | 27668 | 0% |
| 6 | 20:50:00 | 310 | 0% | 27668 | 0% |
| 7 | 20:51:01 | 310 | 0% | 27668 | 0% |
| 8 | 20:52:01 | 310 | 0% | 27668 | 0% |
| 9 | 20:53:02 | 310 | 0% | 27668 | 0% |
| 10 | 20:54:02 | 310 | 0% | 27668 | 0% |
| 11 | 20:55:03 | 310 | 0% | 27668 | 0% |
| 12 | 20:56:04 | 310 | 0% | 27668 | 0% |
| 13 | 20:57:04 | 310 | 0% | 27668 | 0% |
| 14 | 20:58:05 | 310 | 0% | 27668 | 0% |
| 15 | 20:59:05 | 310 | 0% | 27668 | 0% |
| 16 | 21:00:06 | 310 | 0% | 27668 | 0% |

收尾复测（21:01:40，同命令）仍为：卡 0 = 310 MiB / 0%；卡 1 = 27668 MiB / 0%。

### 卡 1 统计

| 指标 | 值 |
|---|---|
| 峰值（used） | **27668 MiB**（样本 2–16，含收尾复测） |
| 谷值（used） | 27286 MiB（仅样本 1，1 分钟内即被抬回平台值） |
| 均值（used） | 27644 MiB |
| 对应空闲 | 峰值时 **5100 MiB**，谷值时 5482 MiB，均值 5124 MiB（总 32768 MiB） |
| utilization | 16 样本中 15 个为 0%（仅样本 1 为 31%），均值 ≈1.9% |
| 卡 0 全程 | 310 MiB 恒定，util 0% |

**曲线判读：不是"波动曲线"，是平台线。** 显存在 1 分钟内从 27286 抬到 27668 后 15 分钟纹丝不动；utilization 接近全零。即：**三个服务计算上空闲，但显存 7×24 满驻不释放**——"空显存窗口"永远不会自然出现，能出现的只是"util=0 但显存仍被占"的假空闲。

### 对照早前证据的增长趋势

- `evidence/env/gpu-machine-check.md`（今日 19:45 前后核查）：卡 1 = 26716 MiB，TTS(pid 1287345) 在卡 1 占 7514 MiB；
- 本次 20:44 起：27286 → 27668（平台），收尾复测进程级：TTS 在卡 1 = **8466 MiB**（7514→8094→8466，单调爬升）；
- 全卡占用 1 小时 +952 MiB。趋势向上，与「一剧N国」今晚有作业在跑一致（见 §4）。

## 3. 卡 1 三服务进程：启动时间与常驻性质

```
$ ssh ... "ps -o pid,user,lstart,etime,cmd -p 1284244,1287345,1689965"
1284244 anuser  Sat Oct  3 10:18:42 2026  5-10:26:30  /data/xdng/venv-asr/bin/python -u /data/xdng/asr_align/service.py --port 9001
1287345 anuser  Sat Oct  3 10:25:53 2026  5-10:19:19  /data/xdng/venv/bin/python -u /data/xdng/tts/service.py --port 9002
1689965 root    Tue Oct  6 17:06:58 2026  2-03:38:14  /data/xdng/venv/bin/python -u /data/xdng/services/lip/service.py --port 9003
```

父进程核查：三者父进程均归 systemd(PID 1)（口型的直接父是 `bash run_gpu.sh start`，其父亦为 PID 1）→ **全是脱离终端的守护进程，已连续驻留 5 天 10 小时 / 5 天 10 小时 / 2 天 3 小时，不会自然退出让卡**。

本机健康端点核验（GPU 机上 `curl -sf -m 3 http://127.0.0.1:<port>/health`，只读 GET，服务仅监听其 127.0.0.1）：

| 服务 | 卡 1 占用 | 装载状态（/health 实测） |
|---|---|---|
| ASR :9001 | 6994 MiB | device cuda:1，asr-core/align-core/emo-tag 三引擎 loaded:true |
| TTS :9002 | 8466 MiB（爬升中） | device cuda:1，dub-tts loaded:true（fp32）；懒加载备选 alt-tts-b **loaded:false**——占用增长是主引擎运行时缓存，非备选引擎 |
| 口型 :9003 | 12204 MiB | physical cuda:1，lip-fast fp16 loaded:true |

三服务合计卡 1 ≈ 27664 MiB，与全卡 27668 MiB 吻合（卡 1 无其他占用者）。

**可否让出：可让、但只能人工让。** 服务由「一剧N国」仓内脚本管理，有现成优雅停启手段：
`chengmai-drama-dub/gpu-services/{asr_align,tts,lip}/run_gpu.sh`，用法 `bash run_gpu.sh [start|stop|restart|status]`（nohup + pidfile /data/xdng/logs/*.pid，stop 即 `kill $pid`，无 systemd 单元、无自动拉起）。文档装载耗时：dub-tts fp32 装载 35.4s（docs/tts_service_deps.md:35）；lip 引擎 28.1s、首载就绪 40–90s（docs/lip_service_deps.md:53、gpu-services/lip/run_gpu.sh start 注释）。

## 4. 是否存在可预期的大片空闲窗口？——**不存在**

三个方向都查了，结论一致：

1. **观测窗内无空闲**：曲线平台化，15 分钟内显存零回落（§2）。
2. **GPU 机无服务启停类定时任务**：
   - `crontab -l`（root）：无 crontab；`crontab -l -u anuser`：仅 4 条 gpumachine 平台自身任务（reap.sh / wake-gate.py 每 5 分 / pm-loop.sh 每 5 分错峰 / patrol 每 2 小时）——读其脚本头注释确认：PM 唤醒门只"读数据+写本目录报告"，不碰 GPU 服务；
   - `systemctl list-timers --all`：仅 sysstat/dnf-makecache/token-renew/tmpfiles 等 8 个系统计时器，无一涉及 GPU 服务；
   - `/etc/cron.d`：仅 0hourly。
   即：**没有任何机制会在某时段自动停服让卡**。
3. **姊妹项目「一剧N国」文档与作业节奏——晚间到凌晨是活跃期，夜间不是空窗**：
   - 作业目录 mtime（本地 `jobs/`）：dy01v2 昨晚 21:20 起跑、**跨零点**（09_lip 口型阶段 00:00–00:15、12_out 00:01）；dy01v3 昨夜 00:15 跑完口型、今天 17:09 出过 12_out、**今晚 20:32 又起新一轮**（03_ocr 20:32 → 07_synth 20:37），截至 21:01 其 09_lip（卡 1 大户口型阶段）**尚未触发、今晚仍会落卡 1**；
   - `jobs.db`/`metrics.db` mtime 20:45（流水线活跃中）；
   - INTENT.md:56,111,140,156：该项目 GPU 任务本就走「等 GPU 窗口事件」的窗口制（auto-wait 等 "asr_align 健康 + V100 空闲 ≥8GB"），GPU 是两项目共同争抢资源，**无固定时段表**；INTENT.md:30 还显示 10-08（今日）是其报名材料截止日，晚间活跃度只增不减；
   - 口型服务被部署矩阵钉死物理 cuda:1（`gpu-services/lip/run_gpu.sh: export CUDA_VISIBLE_DEVICES=1`）。

## 5. 结论

### 建议 spike 执行窗口

**首选：卡 0，即刻可跑，零协调。** 全程观测卡 0 = 310 MiB / util 0% 恒定（仅 TTS 进程的一个 ~306 MiB 侧上下文，且口型/ASR 主负载均钉在卡 1）：
- LTX spike（~16GB）：卡 0 空闲 32458 MiB ≈ 31.7GB，从容；
- Wan2.2-5B spike（峰值 <30GB）：可容（30GB + 0.31GB ≈ 30.3GB < 32GB），但**余量仅 ~2.4GB，偏紧**——建议执行前 5 分钟复测 `nvidia-smi` 确认卡 0 仍 ≤ 数百 MiB 再起；若 OOM 则转备选。
- 顺序建议：先跑 LTX（稳），再试 Wan；Wan 是紧约束，结果存疑时直接走协调窗。
- 风险声明：卡 0 目前无 vLLM 等其他占用者（实测），但 `evidence/env/gpu-machine-check.md:79` 曾记载"卡 0 生产 vLLM"的预期表述——卡 0 存在被其他负载征用的可能，**每次 spike 前必须复测**，本报告只保证观测窗内事实。

**备选：卡 1 协调停服窗（Wan 若在卡 0 放不下时走此路）。** 推荐时段 **10-09（周四）上午 10:00–12:00**：姊妹项目作业集中在晚间与凌晨（昨晚 21:20→00:15、今晚 20:32 起），上午是其作业间隔；且避开其 PM 晨会强制唤醒（wake-gate.py 每日 08:00 force 规则）。流程：owner（或经 owner 授权）在 GPU 机上依次
`bash gpu-services/{asr_align,tts,lip}/run_gpu.sh stop` → 释放 ~27.7GB（卡 1 变 32GB 全空）→ spike（Wan/LTX 均从容）→ `run_gpu.sh start` 逆序重启（装载 35s/28–90s 量级，合计 <5 分钟）。停服期间客户端隧道 health 探测失败属预期。今晚（10-08）**不要**约停服窗：dy01v3 口型阶段随时触发，且今日是其报名截止日。

### 需 owner 协调的事项

1. **与「一剧N国」owner 约定停服窗**（若走卡 1 路线）：具体到小时的窗口承诺 + 停/启由谁执行（红线：video-capability 侧不得代杀进程）；停服期间其隧道/用例会瞬时失败，需其知悉；
2. **卡 0 使用报备**（即使零协调）：向其 owner 打招呼"卡 0 将跑 <30GB 峰值的生成 spike"，避免其 PM 在 spike 进行中向卡 0 派新负载（其窗口制任务正 WAITING_EVENT 等 GPU）；
3. **vLLM 历史表述澄清**：evidence 中"卡 0 生产 vLLM"当前不存在（实测无此进程），需 owner 确认卡 0 是否仍被规划保留，决定 Wan spike 走卡 0 还是等协调窗；
4. **dy01v3 口型阶段避让**：今晚其 09_lip 将落卡 1（util 会打高、TTS/口型占用还会涨），video-capability 侧今晚对卡 1 不做任何动作；
5. 复测义务：任一 spike 启动前 5 分钟复测 `nvidia-smi --query-gpu=index,memory.used --format=csv`（本报告结论仅覆盖 2026-10-08 20:44–21:02 观测窗）。

## 附：证据命令与文件

- 采样循环命令：见 §1；原始样本留痕 `/tmp/gpu1_window_samples.log`（本机）。
- 进程核查：`ps -o pid,user,lstart,etime,cmd -p 1284244,1287345,1689965`；父进程 `ps -o pid,ppid,user,lstart,cmd -p <ppids>`。
- 健康端点：GPU 机上 `curl -sf -m 3 http://127.0.0.1:{9001,9002,9003}/health`（只读 GET）。
- 定时任务：`crontab -l`、`crontab -l -u anuser`、`ls -la /etc/cron.d`、`systemctl list-timers --all --no-pager`；`head -30 /opt/gpumachine/projects/pm/{wake-gate.py,pm-loop.sh}`。
- 本地文档（只读）：`澄迈杯/一剧N国/chengmai-drama-dub/gpu-services/{lip,tts,asr_align}/run_gpu.sh`、`gpu/setup_{tts,lip}_service.sh`、`ops/tunnel_gpu.sh`、`docs/{tts_service_deps,lip_service_deps,gpu_asr_align_deps}.md`、`INTENT.md`、`jobs/dy01v{2,3}/` 目录 mtime。
- 对照基线：`视频能力/evidence/env/gpu-machine-check.md`（今日 19:45 前后核查，HEAD 073a6ed 时代产物）。

---

## 6. 主控裁决（2026-10-08，leader 验收本报告后追加）

**§5「首选卡 0」建议被否决。** 依据 `INTENT.md:97` 项目红线：「GPU 机卡0 跑生产 vLLM『绝对禁止占用/杀进程』，本项目一切 GPU 作业限卡 1」。该红线约束的是**资源护界**而非某个具体进程——卡 0 当前 310 MiB（xdng TTS 侧上下文）属于兄弟项目 xdng 服务栈，随时可能被新负载征用；「实测空闲」不是使用授权。本报告 §5 备选方案（卡 1 协调停服窗）升为**唯一路径**。

**裁决内容**：

1. **Wan2.2-5B / LTX spike 只在卡 1 执行**，窗口取 §5 备选：10-09（周四）10:00–12:00，由 owner 与「一剧N国」owner 约定停服窗后按其 run_gpu.sh 停启流程执行；video-capability 侧**不得代杀进程、不得自行停服**（红线）。
2. **今晚（10-08）不碰卡 1**：dy01v3 口型阶段在即，且为其报名截止日。
3. **spike 执行前 5 分钟复测卡 1 显存**（本报告结论仅覆盖 20:44–21:02 观测窗）。
4. 若 10-09 上午协调窗拿不到：spike 顺延，**M1 骨架期（W3–W5，纯确定性层零 GPU）先行**，不受影响——这是白皮书 §6 路线图设计的天然解耦点。
5. 本裁决同步登记入 `TASK_v4.md` §7 风险表 R3（卡 1 共享窗被挤压：概率「高」、缓解「owner 协调停服窗」）。
