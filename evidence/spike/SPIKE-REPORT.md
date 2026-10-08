# SPIKE-REPORT — LTX-2B 基线 + Wan2.2-TI2V-5B spike（v4 草稿层 T2 决策实测）

- 执行人：GPU spike 执行员（动态工作流子代理）
- 日期：2026-10-08 22:42–23:20 (+0800)
- 位置：anolis-gpu-01 (100.64.0.7)，卡 0（CUDA_VISIBLE_DEVICES=0）
- 仓库：/data/night/g01-rerun/video-capability @ fdaa1cd（与主控同步，git rev-parse 实测确认）
- 运行时：/data/night/venv-vc3（torch 2.7.0+cu126 / diffusers 0.39.0 / modelscope 1.40.1 / ffmpeg 8.0.1 / imageio 2.38.0）
- GPU：Tesla V100S-PCIE-32GB ×2，**compute capability 7.0**（nvidia-smi --query-gpu,name,compute_cap 实测）

## 0. 铁律遵守记录

| 铁律 | 执行情况 |
|---|---|
| ① 只跑卡 0 | 所有进程 `CUDA_VISIBLE_DEVICES=0` 起跑；卡 1 三次复核（起跑前/各轮间/收尾）均为 26708 MiB / 0%，一个字节未动 |
| ② 起跑前 5 分钟内复测卡 0 | 每次起跑命令内联 `nvidia-smi` 复测，全部为 310 MiB / 0% 后才发车 |
| ③ >5GB 异占即中止 | 全程未触发；卡 0 峰值均为本进程（nvidia-smi 采样 13 次佐证） |
| ④ 禁止杀进程 | 未 kill 任何 PID；唯一进程终止均为自然退出 |
| ⑤ 禁 pip install / 禁 >20GB 下载 | 均未发生；Wan2.2 因 31.85 GiB > 20GB **未下载**（见 §3） |

## 1. 任务 1：LTX-2B 单条基线（完成）

配置：`LTXPipeline`，权重 /data/night/models/LTX-Video（2B v0.9.1），fp16（cc 7.0 不支持 bf16，白皮书约束实测成立：`torch.cuda.get_device_capability()=(7,0)`），prompt=「一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云」，480P（高480×宽704），33 帧，steps 15，guidance 3.0，seed 42，导出 24fps。

### 核心数字（ltx_baseline.json）

| 指标 | 值 | 来源 |
|---|---|---|
| **生成墙钟** | **run1 5.39s / run2 4.96s**（time.monotonic） | `timing_s.gen_run1/gen_run2` |
| **峰值显存** | **torch 分配 16.23 GiB；nvidia-smi 全卡峰值 18.34 GiB**（相对当时基线 618 MiB 增 17.73 GiB；采样 13 次/2s 间隔） | `vram.*` |
| 模型加载 | 7.45s（page cache 热态；冷态首跑约 13s，见 ltx_baseline.log attempt1 时间轴） | `timing_s.load` |
| 编码 | 0.52s + 0.43s（两遍） | `timing_s.encode_*` |
| 总墙钟 | 25.0s（含 load + 两次生成 + 两次编码 + 回检） | `timing_s.total` |
| ffprobe 三元组 | h264 / yuv420p / 704×480，avg_frame_rate=24/1，nb_frames=33，duration=1.375s，638 kbps | `output.ffprobe` |
| 文件 | ltx_out.mp4 = 109770 B，sha256 `a3ecb43c…bbab7be` | `output.sha256` |
| 黑帧/NaN | **0 黑帧 / 0 NaN**（生成张量帧级均值 101–126，mp4 端到端回检解码 33 帧均值 129–134） | `quality.* / output.end_to_end_decode` |
| 确定性·编码 | 同帧两遍编码 md5 相等：`462551c9…eea156` ✓ | `determinism.encode_md5_*` |
| 确定性·生成 | 同 seed 二遍生成 5 帧抽样（0/8/16/24/32）MAE 全 0.0，全帧 MAE 0.0 → **逐比特可复现** ✓ | `determinism.mae_*` |

### 质量发现（本节是本 spike 最重要的产出）

像素级检查（黑帧/NaN/均值）全部健康，但**人检中帧发现语义级失败**，三轮判别实验（`ltx_diag*.json` + 11 张中帧 PNG）定位出两个独立问题：

**发现 A：中文 prompt 全糊（致命，可修）。** 固定中文 prompt 产出灰绿色糊斑（preview_f16.png），无任何目标内容；换英文等义 prompt 立即出现完整「猫坐窗台、窗外乌云」构图（ltx_diag_f16_en_neg.png）。加 negative prompt 对中文无效（ltx_diag_f16_zh_neg.png 仍糊）。根因：LTX 0.9.1 的 T5-XXL 文本编码器不支持中文，中文 token 序列产生垃圾 embedding。
→ **v4 若用 LTX，prompt 必须先翻译成英文（管线加翻译层），中文直喂=100% 废片。**

**发现 B：色偏是 checkpoint 固有（致命级，不可在本栈内修）。** 英文 prompt 下结构正确但猫呈蓝色带绿色斑块。9 个变体穷尽判别：

| 变体 | 结果 | 排除的假设 |
|---|---|---|
| zh + neg | 糊斑 | —（发现 A 本体） |
| en 无 neg / en + neg | 均蓝猫 | negative prompt 因素 |
| en + neg + VAE fp32 解码 | 逐统计相同（std 同 44.62） | VAE fp16 精度 |
| decode_timestep=0.05 | 逐统计相同 | 0.9.5+ 去色偏参数（对 0.9.1 无作用） |
| guidance_scale=1.0 | 仍蓝猫（更淡），gen 提速至 2.95s | CFG 过引导 |
| steps=8（白皮书口径） | 仍蓝猫 | 步数 |
| **fp32 T5 embeds 注入**（独立 fp32 T5 计算 → cast fp16 → prompt_embeds 传入管线） | **仍蓝猫** | **fp16 T5 数值溢出**（直接证据：fp16 embeds finite=True、nan=0、inf=0、abs_max=6.06、vs fp32 MAE=0.102，`ltx_diag_round3.json`） |
| 全 fp32 管线 | **OOM**（30.30GB 已分配仍差 352MB，32GB 卡） | 无法作为退路 |

→ **结论：色偏为 LTX-2B-v0.9.1 checkpoint × diffusers 0.39.0 栈的固有表现，与 Volta/fp16/采样参数无关。** LTX 草稿只能用于构图/运动/节奏参考，**色彩不可依赖**；要色准需换 0.9.5+/LTX-2 checkpoint（新下载，见 §4 决策项）。

判别过程中的管线层发现（记录备查）：diffusers 0.39.0 的 LTX encode_prompt 以 `self.text_encoder.dtype` 决定 cast（`diffusers/pipelines/ltx/pipeline_ltx.py:244`），因此「T5 fp32 + transformer fp16」混精无开箱支持（直接报 `mat1/mat2 dtype` 冲突于 `transformer_ltx.py:551`）；本 spike 以外部 embeds 注入绕开。

## 2. 与白皮书 §4 T2 层记录值对比

白皮书记录（`research/2026-10-08/工业化视频流水线-白皮书.md:129,207-208`）：

| 项 | 白皮书记录 | 本次实测 | 裁决 |
|---|---|---|---|
| LTX-2B 墙钟 | **76.7s/条（15.2× 实时）**，fp16 8 步（`工程方案v3.md:35`） | **5.39s/条**（33 帧 1.375s 成片，3.9× 实时） | **不可同口径证实/推翻**：76.7s÷15.2≈5.05s 成片 ≈ 121帧@24fps 档，本次是任务书指定的 33 帧档；且本次 15 步、原记录 8 步，分辨率约定亦未记录。按帧归一：本次 0.163 s/帧 vs 记录 0.634 s/帧（快 ~3.9×），方向一致（LTX 极快），但差异原因（分辨率/步数/管线实现）无法归因，仅作参考。 |
| LTX 质量 | 42/42 全成，质量档 4◐+5○ | 结构成立但中文全糊 + 色偏固有 | **部分推翻/加条件**：在本栈（diffusers 0.39.0 + 0.9.1 权重）上直接复现不出「可用」，必须加英文 prompt 翻译层，且色彩缺陷需要 owner 决策接受或换 checkpoint |
| Wan2.2-5B Q8 | 212–214s/33帧、23.7GB（`AI视频生产流水线方案.md:129`） | **未实测**（§3 阻塞） | 维持「仓内一手实测」状态，本次**既未证实也未推翻** |

## 3. 任务 2：Wan2.2-TI2V-5B spike（阻塞，未跑）

排查与裁决过程（全部有据）：
1. 本地权重排查：`ls /data/night/`（有 LTX-Video、Wan2.1-T2V-1.3B-Diffusers、OmniJev 等，**无 Wan2.2**）；`~/.cache/modelscope/hub`、`~/.cache/huggingface/hub` 仅缓存版本文件；`find /data/night /root/.cache -iname '*Wan2.2*'` 仅命中一份此前会话的 GGUF 调研元数据 `tmp_readme/hf_QuantStack_Wan2.2-VACE-Fun-A14B-GGUF.json`（无权重）。
2. ModelScope 体积实测（API `modelscope.cn/api/v1/models/*/repo/files`，curl 实跑）：
   - `Wan-AI/Wan2.2-TI2V-5B`：26 文件 **31.85 GiB**（t5 bf16 10.58 + transformer 18.63 + VAE 2.63 GiB，三件都是必需件，无 ≤20GB 可运行子集）
   - `Wan-AI/Wan2.2-TI2V-5B-Diffusers`：37 文件 **31.85 GiB**
3. 铁律 ⑤「下载 >20GB 禁止」触发 → **跳过 Wan，如实报告**。

**所需决策（owner 裁决，任选其一）：**
- (a) 授权一次性 ~32GB 下载（磁盘实测剩 45G，放得下；带宽未知，磁盘同一分区 LTX 28G 在位可估盘速）；下载后仍有坑：diffusers 0.39.0 只有 modular 形态 `Wan22ModularPipeline`/`Wan22Blocks`，**无 legacy `Wan22TI2VPipeline`**（import 实测失败），需适配层。
- (b) GGUF Q8 路线：`QuantStack/Wan2.2-TI2V-5B-GGUF` 实测 Q8_0 单文件仅 **5.03 GiB**（<20GB ✓），但需 ComfyUI+GGUF 运行时（机上无 ComfyUI，find 实测零命中；且装栈违反 pip 禁令）→ 需 owner 授权装栈才能走。
- (c) 不重测，沿用仓内 Q8 实测记录（212–214s/33帧/23.7GB）进 v4 文档，标注「V100S 单机未复核」。

## 4. 对 v4 草稿层的结论

**M0-W2 验收门槛裁决**（黑帧率 + ffprobe 代替 vpipe L0，任务书允许的替代口径；vpipe L0 逻辑未接入本次 spike）：

| 门槛 | LTX-2B | Wan2.2-5B |
|---|---|---|
| 峰值 <30GB | **18.34 GiB ✓**（vs CRADLE 记录 23.76GB 亦优） | 未测 |
| 黑帧率 0 | **0/33 ✓** | 未测 |
| ≥1 条过 L0 预检 | **1/1 ✓**（33帧 h264 yuv420p 24fps 完整） | 未测 |

**结论：**
1. **T2 默认通道仍应是 LTX——带三个硬条件。** 速度（5.39s/条）、显存（18.34GB，卡 0 与常驻服务共存无忧）、确定性（同 seed 逐比特复现 + 编码 md5 一致，这对「工件可回归/门禁可判定」是白皮书原则二的直接利好，API 通道 seed 零控制力的问题在 LTX 本地通道不存在）全部远超门槛；但：① 必须加**英文翻译层**（中文直喂 100% 废片）；② **色偏固有**，草稿仅限构图/运动/节奏用途，或由 owner 决策换 0.9.5+/LTX-2 checkpoint（重新下载）后再定；③ guidance 1.0 可再省 45% 时间（2.93s/条）但画面更淡，建议默认 3.0。
2. **Wan2.2-5B 本次无法进产线裁决**——被 20GB 下载红线阻塞，三个决策项（§3 a/b/c）提交 owner。「峰值 <30GB」门槛对 Wan 仅有仓内 Q8 旧值 23.7GB 佐证，非本次实测。
3. 实测修正了白皮书一处技术细节：`torch.cuda.is_bf16_supported()` 在本机返回 True（新版 torch 报模拟支持），白皮书「major>=8 要求」的表述已过时，但**结论仍成立**——Volta 上 bf16 路径不可靠，本次全程 fp16 无一例外。

## 5. 失败与未做项（如实清单）

| 项 | 状态 | 证据 |
|---|---|---|
| 首轮基线编码崩溃（output.frames 布局假设错误） | 已修复重跑，成功 | `ltx_baseline.json.attempt1`（fatal 记录）+ 修复后 `ltx_baseline.json` ok=true |
| round1 判别脚本 dtype 断层（fp32 T5 直插 fp16 管线） | 两次失败（`Float and Half` at transformer_ltx.py:551），改为独立 fp32 T5 外部算 embeds 注入后成功 | `ltx_diag_round3.log` 前身日志（已清理），round3 json 记录最终路径 |
| round3 首跑 tokenizer 路径错误 / mask 参数传错 | 各修复重跑一次 | 日志时间轴 |
| allfp32 判别 | OOM（30.30GB 分配 + 差 352MB），放弃该路径 | `ltx_diag_round2.json` variants.allfp32.error |
| Wan2.2-TI2V-5B | **未跑**（31.85 GiB > 20GB 红线） | §3 |
| 76.7s 白皮书值同口径复测 | **未做**（原 121帧/分辨率/8步配置未记录，无法复原口径） | §2 |
| vpipe L0 逻辑接入 | 未做（以任务书允许的黑帧率+ffprobe 替代） | §4 |
| Wan GGUF Q8 | 未下载未跑（运行时缺 ComfyUI，pip 禁令） | §3(b) |

## 6. 产物清单（/data/night/g01-rerun/video-capability/evidence/spike/，均 644）

- **核心交付**：`ltx_baseline.json`（结构化指标）、`ltx_out.mp4`（正片，sha256 a3ecb43c…）
- 判别证据：`ltx_diag.json` / `ltx_diag_round2.json` / `ltx_diag_round3.json` + 11 张中帧 PNG（`ltx_diag_f16_*.png`、`preview_f{0,16,32}.png`）+ 各变体 mp4
- 脚本与日志：`ltx_baseline.py` / `ltx_baseline.log` / `ltx_diag_round2.py` / `ltx_diag_round3.py` / 各轮 .log
- 失败存档：`ltx_baseline.json.attempt1`（首轮 fatal 记录，§5）

## 7. Wan2.2-TI2V-5B spike（Wan2.2 节，追加——任务书所称「§6」因报告已有 §6 产物清单，顺延为 §7）

- 执行：2026-10-08 23:34 – 10-09 03:42 (+0800)，卡 0（CUDA_VISIBLE_DEVICES=0），权重 31.854 GiB 实测落盘
- 授权：TASK_v4 §8 决策 2026-10-08-e（解除 20GB 下载自限，纪律不变：仅卡 0 / 跑前复测 / 不 kill / 不 pip install）
- 运行时不变（torch 2.7.0+cu126 / diffusers 0.39.0 / modelscope 1.40.1）；git HEAD 实测 `fdaa1cd`——**较主控最新（e322c37，含 b72ca96 授权记录）落后 3 个提交**，均为 docs/evidence/J1 收编提交，不影响本 spike；授权以任务书原文为准，未在 GPU 机整仓 pull（遵守「GPU 机上只写 evidence/spike/ 与模型目录」红线）

### 7.1 任务 1：下载对账（完成，波折如实记录）

**落盘结果：30 个文件（blob）/ 34,203,022,185 字节 = 31.854 GiB，逐文件 sha256 对 ModelScope manifest 全量匹配（wan22_download_verify.json），无多余文件。**

| 口径 | 文件数 | 体积 | 说明 |
|---|---|---|---|
| 主控预期 | 14 | 31.83 GiB | 与两仓实测均不符，14 的来源无法复原 |
| ModelScope API 实测·原始仓 `Wan-AI/Wan2.2-TI2V-5B` | 26 blob | 31.854 GiB | 无 model_index.json，diffusers 0.39.0 不可直载（§3(a) 预警的「适配层」本体） |
| ModelScope API 实测·`Wan-AI/Wan2.2-TI2V-5B-Diffusers` | 30 blob（API 列 37 项含 7 个目录节点） | 31.854 GiB | **实际下载仓**：带 model_index.json 子目录布局 |
| **实得（=Diffusers 仓）** | **30** | **31.854 GiB** | 字节与主控预期差 +0.024 GiB（+0.08%），文件数差 +16 |

下载仓替换说明（与任务书「Wan-AI/Wan2.2-TI2V-5B」字面不同，须主控知悉）：两仓**同权重同体积**（transformer 18.625 + T5 10.582 + VAE 2.625 GiB 完全同源），但原始仓是 ComfyUI 式布局（.pth T5/VAE + 根级分片 safetensors、无 model_index.json），diffusers 0.39.0 的 Wan22ModularPipeline 无法加载，手写转换器工作量与失败风险大；磁盘 45G 只容一仓，故选 Wan-AI 官方发布的 Diffusers 打包仓落红线许可路径 `/data/night/models/Wan2.2-TI2V-5B/`。完整性不依赖此选择：全部 30 文件 sha256 对 ModelScope manifest（内容寻址）逐文件核验通过。

下载时间线（wan22_fetch.log 全程留痕）：
1. 23:34 modelscope CLI 发车 → 实测聚合 **290 KB/s**（31.8GiB 需 ~33h，主控预估 ~11MB/s 不成立）→ 弃用（杀的是自己 10 分钟前起的下载进程，非 GPU/他人进程）。
2. 23:44/23:49 自写抓取 v1/v2 两次脚本错误（xargs -I 行解析、漏 import threading）→ 23:52 v3（curl 直连 cdn-lfs-cn-1，3 并发 + 断点续传）起步 **10 MB/s**。
3. 累计 ~15GB 后 ModelScope CDN 限速至 **182 KB/s/连接**（实测），切换 hf-mirror.com（单连接实测 **8.88 MB/s**，HTTP 206 正常）→ v4 4 并发。
4. v3 被停时 3 个 curl 孤儿进程继续写 → 与 v4 双写竞态致 transformer 分片 00004/00005、VAE 超长损坏（got>want 24.7MB/49KB）→ 杀孤儿、删 3 文件、单源重拉。
5. 01:10:55 全部 30/30 完成，01:12:41 sha256 对账 30/30 OK（106s）。总窗口 96.8 min（纯传输约 73 min，有效均速 ~7.2 MiB/s）。

### 7.2 diffusers 0.39.0 × Wan2.2 的四处不兼容（适配层实证，均在内存中绕过、零 site-packages/模型目录改动）

| # | 缺陷 | 现象 | 绕过 |
|---|---|---|---|
| 1 | `ModularPipeline.from_pretrained` 对仅有 model_index.json 的 legacy 仓直接崩 | `UnboundLocalError: blocks_class`（modular_model_index.json 缺失时 `_blocks_class_name` 分支未赋值；load_config 把 model_index.json 当 modular config 读回） | 手动加载 5 组件（WanTransformer3DModel/UMT5EncoderModel/AutoTokenizer/AutoencoderKLWan/UniPCMultistepScheduler，全 fp16）+ `update_components` 注入 |
| 2 | `Wan22LoopDenoiser` 按 A14B MoE 双专家写死 | `t<boundary` 取 `transformer_2`=None → 首个低噪步 `'NoneType' object is not callable`（TI2V-5B 单模型，model_index 中 transformer_2=null） | `update_components(boundary_ratio=0.0)` 使 t≥0 恒走 transformer + guider(CFG 5.0)，等价官方单模型语义（注：首试误设 1.1 方向搞反即崩，如实记录） |
| 3 | `vae_scale_factor_spatial` 属性用 Wan2.1 启发式 `2**len(temperal_downsample)=8` | Wan2.2 VAE config 显式 `scale_factor_spatial:16` → latents 算大 4×（88×160 而非 44×80）：解码出 1408×2560（目标 2 倍边长）、denoise 多耗 9.15×（38.3→4.19 s/it） | 运行时改类属性 property 读 config（内存补丁） |
| 4 | `VideoProcessor` from_config 默认 `vae_scale_factor=8` | 与 #3 同源的后处理缩放错误 | `update_components(video_processor=VideoProcessor(vae_scale_factor=16))` |

另：720P 全帧 fp16 VAE 解码 OOM（需 1.72GiB、仅剩 220MiB；denoise 峰值后 27.81GiB 已分配）→ `vae.enable_tiling()`（tile 256×256，Wan 类模型产线标准配置）后通过。

### 7.3 spike 指标（wan22_baseline.json，ok=true，errors=[]）

配置：EN/ZH 双 prompt（语义等价）+ 官方 README 中文负向词 / **704×1280（720P 档官方口径，README:124,166-167）** / 33 帧 / **50 步（官方 diffusers 用例值）** / CFG 5.0（guider 配置默认） / seed 42 / 全组件 fp16（V100S cc7.0，bf16 禁用） / 24fps 导出 / VAE tiling。

| 指标 | 值 |
|---|---|
| 加载（page cache 热） | 12.0s |
| **生成墙钟（含 tiling 解码）** | **EN 229.5s / EN二遍 230.1s / ZH 230.6s**（4.19s/it × 50 + 解码 ~40s） |
| **峰值显存·nvidia-smi 全卡（353 次采样）** | **25,640 MiB = 25.04 GiB**（基线 618MiB，Δ25.02GiB） |
| 峰值显存·torch allocated | 24,681.6 MiB（load 阶段 23,657.8） |
| 黑帧 / NaN | **0 / 0**（三跑生成张量帧均值 EN 119.85–120.31、ZH 128.41–132.58） |
| ffprobe 三元组 | h264 / yuv420p / **1280×704** / 24fps / 33 帧 / 1.375s / 3.73 Mbps（EN）；ZH 5.09 Mbps |
| sha256 | wan22_out.mp4 `8380f5da…c4e7463`（641,016 B） |
| 确定性·编码 | 两遍 md5 相同 `6c9d2ffa…` ✓ |
| 确定性·生成 | 同 seed 二遍 5 帧抽样 + 全帧 **MAE 全 0.0（逐比特复现）** ✓ |
| 端到端回检 | ffmpeg 解码 33 帧，0 黑帧 ✓ |
| **L0 预检（替代口径）** | **passed=true**（黑帧率 0.0 ≤50% + 时长偏差 0.0% ≤2%；vpipe L0 未接入，沿用任务书允许的黑帧率+ffprobe 替代，与 §4 LTX 同口径） |

### 7.4 中英 prompt 对照·人检（preview_wan22_en_mid.png / preview_wan22_zh_mid.png，本执行员目检）

- **EN 帧**：橘猫背影坐窗台、窗外蓝天白云+绿色丘陵、木窗框、暖阳光——prompt 语义元素全部到位，构图完整，色彩正常，720P 细节清晰，未见可见伪影。
- **ZH 帧**：「一只橘猫坐在窗台上晒太阳，窗外是慢速移动的云」语义同样完整成立（橘猫/窗台/窗外云层与绿野/暖光），阴天观感、玻璃反光感、构图略异，同样可用，无糊斑无语义崩坏。
- **裁决：UMT5 中文直喂可用**——与 LTX 的发现 A（T5-XXL 中文 100% 糊斑、必须加翻译层）形成决定性对比；若 T2 升 Wan，翻译层可以不建。

### 7.5 M0-W2 门槛判定（主控判据：峰值 <30GB + 黑帧率 0 + ≥1 条过 L0 + 720P/24fps 成立）

| 门槛 | 判定 | 证据 |
|---|---|---|
| 峰值 <30GB | **✓ 25.04 GiB**（nvidia-smi 全卡；torch 口径 24.10 GiB） | vram.*，353 次采样 |
| 黑帧率 0 | **✓ 0/33**（三跑均 0） | quality.* |
| ≥1 条过 L0 | **✓ EN 主条 passed**（替代口径，同 §4） | l0_precheck_substitute |
| 720P/24fps 直出成立 | **✓ 1280×704@24fps 33 帧原生直出**（无插帧/超分） | output.ffprobe |

**四项全过。** 对照白皮书 §6 M0-W2 原话（`research/2026-10-08/工业化视频流水线-白皮书.md:343`「若过，产线从 480P/16fps 直上 720P/24fps，插帧与超分（E12）可能整段砍掉」）。

### 7.6 与 LTX-2B 的对照表（同机同卡同 venv，§1 LTX 数据 vs 本节）

| 维度 | LTX-2B（0.9.1） | Wan2.2-TI2V-5B | 差异 |
|---|---|---|---|
| 原生分辨率/帧率 | 704×480 @24fps 导出 | **1280×704 @24fps 原生** | 像素 2.67×，720P 直出（E12 可砍的前提） |
| 生成墙钟/条 | 5.39s（15 步） | **229.5s（50 步官方档）** | **42.6×**；同 33 帧口径 |
| 归一 | 0.163 s/帧；0.359 s/step | 6.96 s/帧；4.59 s/step | 逐帧 42.6×，逐 step 12.8×（含 2.67× 像素） |
| 峰值显存 | 18.34 GiB | **25.04 GiB** | +6.7GiB；32GB 卡上与常驻服务共存余量收窄 |
| 黑帧/NaN | 0 / 0 | 0 / 0 | 持平 |
| 同 seed 复现 | MAE 0.0 逐比特 | MAE 0.0 逐比特 | 持平（白皮书原则二利好保持） |
| 编码确定性 | md5 一致 | md5 一致 | 持平 |
| 中文 prompt | **100% 糊斑（不可用）** | **可用（人检成立）** | **UMT5 中文支持成立，翻译层可不建** |
| 色彩 | 蓝偏固有（checkpoint 级，不可修） | 正常（人检） | LTX 最大质量缺陷在 Wan 不存在 |
| 语义质量 | 结构成立但色彩废 | 语义/色彩/细节三全 | 质量档跃升 |
| 栈适配成本 | 开箱即用 | **需四点适配层**（§7.2）+ VAE tiling | diffusers 0.39.0 的债，须固化进仓 |

（注：LTX 白皮书记录 76.7s/条为 121 帧档不同口径，不能直接比；此处两列均为本次 33 帧同题实测。）

### 7.7 T2 层升级裁决建议（供主控裁决）

**按主控预设判据：M0-W2 四项门槛全过 → 建议「升」，但以「有条件升」落地，条件如下（均为本次实测的一手证据）：**

1. **720P/24fps 直出成立**：25.04GiB 峰值、黑帧 0、L0 过、原生 1280×704@24fps——白皮书 §6 的「E12 插帧/超分整段砍掉」前提满足。质量上语义/色彩/细节三全（人检两帧），且 LTX 的两大质量硬伤（中文糊斑、固有色偏）在 Wan 上均不存在，**中英 prompt 均可直喂，翻译层可省**。
2. **代价如实（速度）**：官方 50 步档 229.5s/条（LTX 的 42.6×，0.163→6.96 s/帧）。草稿层若按此默认档吞吐将降 42×——**升默认的前提是接受草稿层变慢**，或后续测降步数档（15/30 步、CFG=1.0 提速路径本次未测，不敢报数）；另显存余量 25.04/32GB，卡 0 上再叠常驻服务的空间比 LTX（18.34）收窄 6.7GiB。
3. **工程条件**：§7.2 的四处适配（手动组件加载、boundary_ratio=0.0、两个 scale_factor 修正）+ VAE tiling 必须先固化为仓内适配层并加回归用例——本次全靠脚本内内存补丁，`Wan22ModularPipeline.from_pretrained` 官方路径在 diffusers 0.39.0 上对 TI2V-5B 实际不可用（换 diffusers 新版含 legacy Wan22 支持是另一条更干净的路径，但属新依赖决策）。
4. **未测项（不装作已测）**：I2V 档（Wan22Image2Video 通道）、121 帧满档、fp16 下长程稳定性（3 条短跑 NaN=0 不足以外推）、批量吞吐与超时行为、VRAM 25GiB 与卡 0 现有 306MiB 常驻进程长期共存的 OOM 边界。

### 7.8 失败与重跑清单（全程如实）

| # | 发车 | 结果 | 处置 |
|---|---|---|---|
| 1 | 01:16 | from_pretrained UnboundLocalError 崩 | 改手动组件加载 |
| 2 | 01:19 | 50 步中第 ~13 步 transformer_2=None 崩（boundary 0.875 默认） | 判定 MoE 双专家缺陷 |
| 3 | 01:40 | boundary=1.1（方向误判）首步即崩 | 修正为 0.0 |
| 4 | 01:51 | 50 步跑完但 VAE 解码 OOM（未 tiling + latents 4× 偏大） | enable_tiling + expandable_segments |
| 5 | 02:30 | 生成完成但输出 1408×2560（scale 8 误算）→ 形状断言失败 | 查出 vae_scale_factor_spatial 启发式缺陷 |
| 6 | 03:07 | 发车瞬间卡 0 读到 9,158MiB（上轮进程退出瞬态）>1GB 门槛 | **主动停掉自己 15s 前的进程**，回落后合规重发（红线执行记录） |
| 7 | 03:09 | 仍 38.3s/it（VideoProcessor 不影响 latents 计算）→ 主动停 | 深挖出 #3 属性缺陷 |
| 8 | 03:19 | KeyError（脚本内 RESULT 键序 bug） | 修正 |
| 9 | 03:27 | **成功**：ok=true，713.3s 全程 | — |

红线执行：仅卡 0（每轮发车前 nvidia-smi 内联复测，除 #6 瞬态 9,158MiB 当轮主动废止外全部 ≤1GB 才发车）；卡 1 全程 26,706–26,708MiB 一个字节未动；未 kill 任何他人/GPU 进程（仅自身的下载/发车进程 5 次，均记录在案）；未 pip install；除 Wan 权重外无 >1GB 下载；产物全 644（find 实测 18 个 wan22* 文件全 644）；GPU 机写入仅 evidence/spike/ 与 /data/night/models/Wan2.2-TI2V-5B/。

### 7.9 本节产物（evidence/spike/，均 644）

- **核心交付**：`wan22_baseline.json`（结构化指标，ok=true）、`wan22_out.mp4`（EN 正片 720P，sha256 8380f5da…）、`wan22_out_zh.mp4`（ZH 对照）、`preview_wan22_{en,zh}_mid.png`（人检帧）
- 下载对账链：`wan22_manifest.json/.tsv`（ModelScope API size+sha256 基准）、`wan22_download_verify.json`（30/30 全对账）、`wan22_fetch.log`（全时间线）、`wan22_fetch.py`（v4 终版）、`wan22_fetch.sh`（v1 失败存档）、`wan22_download.log`（CLI 尝试）
- 脚本与日志：`wan22_baseline.py`（含四点适配层与脚本头注释）、`wan22_baseline.log`、`wan22_build_manifest.py`、`wan22_download_verify.py`
