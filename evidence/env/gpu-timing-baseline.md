# 卡 1 单任务墙钟基线（LTX smoke）——M0-W1

- 核查日期：2026-10-08
- 结论先行：**GPU 机可达、LTX 推理环境全部就绪，但卡 1 空闲显存不足以承载最小 smoke（会触发逐层 offload，墙钟数字无基线意义且有挤压生产服务风险），按事实记录，W2 spike 延后，待显存窗口重测。**

## 1. 环境就绪度（全部实测通过）

```
$ ssh root@100.64.0.7 '/data/night/venv-vc3/bin/python -c "import diffusers, torch; ..."'
diffusers 0.39.0
torch 2.7.0+cu126
cuda True

$ /data/night/venv-vc3/bin/python -c "from diffusers import LTXPipeline; print('LTXPipeline OK')"
LTXPipeline OK

$ ls /data/night/models/LTX-Video/
model_index.json  scheduler/  text_encoder/  tokenizer/  transformer/  vae/  （+2 个 license 文件）
$ du -sh .../text_encoder .../transformer .../vae
18G    text_encoder   （T5 族文本编码器）
7.2G   transformer    （DiT 主干）
1.6G   vae
共 28G，权重已全部在本地，零下载需求。
```

- venv-vc3 = diffusers 0.39.0 + torch 2.7.0+cu126 + LTXPipeline 原生支持：**无需装任何包**（红线遵守）。
- 权重在本地 `/data/night/models/LTX-Video`：**无 >1GB 下载**（红线遵守）。

## 2. 为什么不能在本窗口跑

```
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
0, 310 MiB, 32768 MiB
1, 26716 MiB, 32768 MiB     ← 卡 1 仅剩 32768-26716 = 6052 MiB ≈ 5.9 GB
```

- 卡 1 被三个常驻生产服务占用：ASR 对齐（pid 1284244，6994 MiB，:9001）、TTS（pid 1287345，7514 MiB，:9002，跨卡）、口型（pid 1689965，12204 MiB，:9003）。
- smoke 最小要件 LTX transformer 单件就 7.2G（盘面 bf16），**已超卡 1 全部空闲显存**；文本编码器 18G 更不可能。可行路径只剩 SequentialCPUOffload 逐层搬——得到的墙钟是 I/O 瓶颈数字，对 480P/33 帧基线**无规划价值**，且峰值分配有挤压同卡生产服务显存的风险。
- 红线遵守：未动卡 0（其上有 xdng TTS 常驻；核查时刻两卡均未见 vLLM 进程），未杀进程、未改文件、未装包。smoke 产物属临时写文件，一并避免。

## 3. 判定与重测条件

**GPU 机可达 ≠ 可跑：本窗口不跑 smoke。W2 spike 延后。**

重测触发条件（满足其一）：
1. 卡 1 空闲显存 ≥ 10 GB（够 transformer bf16 常驻 + 激活；文本编码器仍走 CPU/offload，记录为「半 offload 基线」）；
2. 维护窗口拿到卡 1 独占（31 GB 全量，text_encoder 可载入，得「全 GPU 基线」）；
3. 若必须用卡 0：需 owner 确认 xdng TTS 属可共存负载并书面放行（默认不动卡 0）。

预计重测命令骨架（届时执行，非本次）：
`CUDA_VISIBLE_DEVICES=1 /data/night/venv-vc3/bin/python` + `LTXPipeline.from_pretrained("/data/night/models/LTX-Video")` + 480P×33 帧 1 步/少步推理，`time.perf_counter()` 计墙钟。
