# GPU 机可达性与运行区核查（M0-W1）

- 核查人：环境核验员（ZCode 子代理）
- 核查日期：2026-10-08
- 核查方式：SSH 只读命令（ConnectTimeout=10, BatchMode=yes），未做任何写操作/杀进程/装包
- 参考依据：`overnight/vpipe/tools/regen_fixtures/REPRODUCE.md`（root@100.64.0.7 / /data/night/g01-rerun/video-capability / venv-vc3 / golden symlink）

## 1. 可达性

```
$ ssh -o ConnectTimeout=10 -o BatchMode=yes root@100.64.0.7 'echo OK; uptime'
OK
 19:45:13 up 11 days,  6:22,  9 users,  load average: 0.11, 0.07, 0.07
EXIT_CODE=0
```

**结论：可达（退出码 0）。** 负载极低（load 0.11），机器已连续运行 11 天。

## 2. 磁盘 / 运行区目录 / 显存

```
$ ssh ... 'df -h /data; echo ===; ls /data/night/; echo ===; nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv'
Filesystem      Size  Used Avail Use% Mounted on
/dev/vdb1       295G  235G   45G  85% /data
===
clips
frames
g01-relock-round1.log
g01-relock-round2.log
g01-relock-round3-final.log
g01-rerun
golden
judge_rerun
logs
models
results
scripts
src
tmp
venv
venv-judge
venv-qc
venv-vc3
===
index, memory.used [MiB], memory.total [MiB]
0, 310 MiB, 32768 MiB
1, 26716 MiB, 32768 MiB
EXIT_CODE=0
```

- `/data`：295G 总量，已用 235G，**剩 45G（85% 占用）**——大批量生成前需关注余量。
- `/data/night/golden`（金标 symlink 指向物）、`venv-vc3`、`g01-rerun/` 均在位。
- 卡 0：310 MiB / 32768 MiB（近乎全空）；卡 1：26716 MiB / 32768 MiB（**仅剩约 6.0 GB 余量**）。

## 3. 卡 0 / 卡 1 进程占用（只读 ps + nvidia-smi query-compute-apps）

```
gpu_uuid, pid, process_name, used_gpu_memory [MiB]
GPU-3eb00f64-...（=卡0）, 1287345, /data/xdng/venv/bin/python, 306 MiB
GPU-12f8ba8b-...（=卡1）, 1284244, /data/xdng/venv-asr/bin/python, 6994 MiB
GPU-12f8ba8b-...（=卡1）, 1287345, /data/xdng/venv/bin/python, 7514 MiB
GPU-12f8ba8b-...（=卡1）, 1689965, /data/xdng/venv/bin/python, 12204 MiB
```

```
$ ps -o pid,etime,user,args -p <pid> | cut -c1-220
1287345  5-09:20:11  anuser  /data/xdng/venv/bin/python -u /data/xdng/tts/service.py --port 9002
1284244  5-09:27:22  anuser  /data/xdng/venv-asr/bin/python -u /data/xdng/asr_align/service.py --port 9001
1689965  2-02:39:06  root    /data/xdng/venv/bin/python -u /data/xdng/services/lip/service.py --port 9003
```

| 卡 | 进程 | 说明 |
|---|---|---|
| 卡 0 | pid 1287345 `/data/xdng/tts/service.py --port 9002`（anuser，306 MiB） | TTS 服务（跨卡 0/卡 1 同时占用：306 MiB + 7514 MiB） |
| 卡 1 | pid 1284244 `/data/xdng/asr_align/service.py --port 9001`（anuser，6994 MiB） | ASR 对齐服务 |
| 卡 1 | pid 1287345 同上 TTS（7514 MiB） | — |
| 卡 1 | pid 1689965 `/data/xdng/services/lip/service.py --port 9003`（root，12204 MiB） | 口型服务，占卡 1 最大头 |

**事实备注**：核查时刻两卡上均为 xdng 的 ASR/TTS/口型三个常驻服务；**未观察到 vLLM 进程**（任务红线提到的「卡 0 生产 vLLM」在本时刻不存在，按实测如实记录）。未做任何触碰。

## 4. 运行区 git HEAD

```
$ ssh ... 'cd /data/night/g01-rerun/video-capability && git log --oneline -3 && git log -1 --format="%H %ci"'
073a6ed docs(regen_fixtures): REPRODUCE.md——G0-1 终局复锁复现手册（夹具对位+全量复跑，任何人可复现）
71f719d calib(eval): J3 工作点重扫 0.70→0.71——判官三件套重跑后按 thresholds 修改规程重定阈
12ca6f6 test(j6v2): 19 片检测器回归夹具重建工具链入库——原片灭失，判定行为确定性重建（非 Vidu 原物）
073a6edf8478462d49401ed95824b69c86f1a404 2026-10-07 10:37:57 +0800
EXIT_CODE=0
```

**结论：HEAD = `073a6ed`，是 `71f719d` 的直接后继（多一个 REPRODUCE.md 文档提交），满足「= 71f719d 或更新」。**

## 5. 附加环境事实（与 REPRODUCE.md 对照）

- `/data/night/venv-vc3`：torch 2.7.0+cu126、diffusers 0.39.0、CUDA available（python import 实测通过）。
- `/data/night/models/LTX-Video/` 在位（28G：text_encoder 18G / transformer 7.2G / vae 1.6G，diffusers 目录结构）。
- 上述两项为后续 W2 LTX spike 的就绪度证据，详见同目录 `gpu-timing-baseline.md`。

## 6. 汇总判定

| 检查项 | 结果 |
|---|---|
| SSH 可达 | PASS（exit 0） |
| /data 空间 | 45G 可用（85% 已用，够单轮 spike，批量需扩容或清理） |
| 金标/venv/运行区在位 | PASS |
| git HEAD ≥ 71f719d | PASS（073a6ed） |
| 卡 1 空闲显存 | **仅 5.9 GB**（生产服务占用，spike 需另约窗口） |
