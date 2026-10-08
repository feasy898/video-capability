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
