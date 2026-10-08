# 可控视频生成学术调研（2026-10-08）

> 面向 owner「廉价草稿 + 高级精渲」分段流水线的可控生成前沿调研。
> 仓内依据：`AI视频生产流水线方案.md`（§2.1 选型总表 / §2.2 混合渲染 / §2.3「70 分」标定 / §3.1 VDL schema / §4.1–4.3 质检）、`arxiv_vbench.xml`、`CONTEXT.md`、`TASK.md`。

## 0. 取证方式与已知缺口（先声明，避免把推断当实据）

- **`WebFetch` 工具本次全程不可用**：5 次调用（3× `arxiv.org/abs`、1× `arxiv.org/abs` 重试、1× `vchitect.github.io`）全部返回 `Provider rejected the model request`。因此全部联网材料改用 `curl` 直取一手源，与 WebFetch 取的是同一批 URL。
- 实际执行的取数命令（示例，可复跑）：
  - `curl -sS -m 90 "https://export.arxiv.org/api/query?id_list=...&max_results=40"`（arXiv API 取摘要）
  - `curl -sSL -m 90 -A "Mozilla/5.0" "https://arxiv.org/html/2507.16869v3"`（取论文全文 HTML）
  - 注：`http://export.arxiv.org`（80 端口）在本机超时，`https` 正常。
- **本机未跑任何 GPU 实验**：本文所有「能不能上 2×V100S」的判断来自论文自述 + 仓内已有实测台账（`AI视频生产流水线方案.md:129,673`），**没有一条是本次实测**。
- 未核实项（不猜）：这些控制器论文的**显存占用/推理耗时/许可证**一律未取；MimicMotion / ConsisID / Animate Anyone 2 / V-Express / WorldModelBench 等**只经综述论文二次引用**读到，未读原文；Wan 系底座上的相机控制变体未穷举检索。

---

## 1. 可控生成学术全景与可控轴分类

### 1.1 权威分类法

最完整的一手分类来自综述 **《Controllable Video Generation: A Survey》(arXiv:2507.16869v3)**，它把控制信号切成 6 大类 + 通用控制（`/tmp/survey.txt`，章节号即下表来源）：

| 综述分类 | 子类 | 轴 |
|---|---|---|
| **5.1 Structure Control** | Pose / Depth / Landmark / Sketch / BBox | 结构、姿态 |
| **5.2 ID Control** | Person / Subject | 身份 |
| **5.3 Image Control** | 参考图 / 首帧 | 图像条件 |
| **5.4 Temporal Control** | Flow / Trajectory / Camera / Motion | 时间、轨迹、相机、动作 |
| **5.5 Audio Control** | Voice / Sound | 口型、音画 |
| **5.6 Other Control** | Text Rendering / Style / Point / BEV | 风格、点拖拽、BEV |
| **5.7 Universal Control** | 条件统一编排 | 通用 |

### 1.2 按 owner 的轴重新归并 + 成熟度

成熟度判据三条：**①接口是否参数化（非 prompt-only）②是否有公开权重/代码 ③是否有专属基准或指标**。每格都注明证据来源。

| # | 可控轴 | 成熟度 | 证据（均本次读到） |
|---|---|---|---|
| A1 | **相机/镜头（camera）** | **高**（唯一全绿） | 接口标准化为 6-DoF 位姿序列：CameraCtrl(2404.02101) 明确 K(3×3) + E=[R;t](3×4)、主条件用 **Plücker 嵌入**（`/tmp/CameraCtrl.txt` §3.2）；ShotDirector(2512.10286)「6-DoF poses + intrinsics」；Track2View(2606.15534) 用成对 3D 点轨迹；CETCAM(2512.19020) 用 VGGT 估计的 geometry token。有基准：VBench-2.0 的 **Camera Motion** 维度（9 类，CoTracker-v2 判别）。商用侧 Kling 1.6 在该维相对强（VBench-2.0 §V-A） |
| A2 | **姿态（pose，人体）** | **高（限人体）** | 综述 §5.1.1：输入是 COCO 2D 骨架 / 3D 坐标 / DensePose 序列，可由 MoCap 或**算法生成**。方法成群：MimicMotion、Champ、Animate Anyone 2、Follow Your Pose、DirectorLLM。**但综述 §5.1.6 明确警告**：「Current methods often prioritize visual alignment over kinematic plausibility, leading to physically impossible deformations, and remain limited to specific domains (e.g., humans)」——即运动学合理性是已知短板 |
| A3 | **姿态（非人体 / 手持物交互）** | **低** | 同上综述 §5.1.6 的 domain-limited 判定；owner 仓内把 InterMimic 列为「P0 spike 通过后才排产」(`AI视频生产流水线方案.md:131`) 与此判断一致 |
| A4 | **轨迹（trajectory / 点拖拽）** | **中高** | Motion Prompting(2412.02700) 用**时空稀疏点轨迹**（N×T，含可见性掩码）当条件，一个模型同时覆盖相机运动/物体运动/拖拽编辑；DragAnything(2403.07420) 用拖拽轨迹 + 实体表示，人评超 DragNUWA **26%**（摘要原文）；Trajectory Attention(2405.14864) 走 training-free 路线 |
| A5 | **结构（depth/edge/sketch/bbox/landmark）** | **中** | SparseCtrl(2311.16933) 摘要直接点破成本结构：「dense structure signals … whose collection accordingly increases the burden of inference」，因此它改用**时间稀疏**的关键帧锚定。综述 §5.1.6：范式已从 UNet+ControlNet Adapter 转向 DiT |
| A6 | **身份（identity）** | **中高（单人）/ 低（多人）** | 综述 §5.2.3：路线正从「慢微调」转向 tuning-free（ConsisID），主干预点是 **multi-subject 的解耦与冲突**未解决。owner 侧对应 VACE + 角色资产包 (`AI视频生产流水线方案.md:126`) |
| A7 | **时间（时长/速度/重定时/插值）** | **低** | 综述把 Temporal Control 定义为 flow/trajectory/camera/motion 的**时空引导**，而非「时间轴调制」；真正的时间控制（变速、关键帧插值）只在 SparseCtrl 的应用列表里以副产品形式出现 |
| A8 | **动作概念定制（motion concept）** | **中低** | MotionDirector(2310.08465)：需要给定一组同动作视频做适配，dual-path LoRA 解耦外观与运动。**不是实时参数接口**，属于「训练一次再用」 |
| A9 | **口型/音频驱动** | **中高（单人特写）/ 低（多人·全身）** | 综述 §5.5.3：从 UNet 管线（EchoMimic）转向 DiT 统一生成（V-Express、MegActor-Σ）；两个已知短板——「dominant visual features frequently suppress subtle audio cues」的控制失衡，以及语音结构与语义音效控制未分离 |
| A10 | **风格** | **高（但对短剧价值低）** | VBench/VBench++ 有 Appearance Style 与 Temporal Style 两个独立维度（`/tmp/vbp.txt`）；技术路线同结构控制 |
| A11 | **多镜头 / 转场 / 镜头语义** | **低（最新、最缺）** | CineOrchestra(2606.13768)：「no prior framework jointly integrates all four」(主体/事件/相机/转场)；ShotDirector(2512.10286) 专门做转场；VBench-2.0 §V-B 判定「current foundation video generative models typically produce single-shot videos under 10 seconds」，**复杂剧情维度 SOTA 全部吃力** |
| A12 | **世界模型式无提示生成** | **中** | ChronoEdit(2510.04290) 把图像编辑重构为视频生成（首尾帧当视频两端）+ 推理 token 做时序推理，目标是「physically viable transformations」；配 PBench-Edit 基准 |

**成熟度一句话总结**：**相机轴是唯一「接口标准化 + 有基准 + 商用模型都支持」的轴；人体姿态轴次之但受限于运动学合理性；结构/身份/口型是「够用但有已知缺陷」；时间控制、多镜头转场、非人体交互是空白**。

---

## 2. 已有「程序化接口」的可控轴与代表方法

判据：接口输入是**张量/数值序列**，而不是自然语言。凡满足即列出接口原样。

| 轴 | 输入接口（原样） | 代表方法 | 证据 |
|---|---|---|---|
| **相机** | 逐帧外参 E=[R;t]∈R^{3×4} + 内参 K∈R^{3×3} → **Plücker 嵌入** | CameraCtrl (2404.02101) | `/tmp/CameraCtrl.txt` §3.2 + 附录 D.1「camera encoder Φc architecture」 |
| **相机** | 相机位姿序列 + 物体轨迹，**两轴解耦独立控制** | MotionCtrl (2312.03641) | 摘要：「Its motion conditions are determined by camera poses and trajectories, which are appearance-free」 |
| **相机** | **标量** pan / zoom（无需位姿标注，自监督增广训练） | Direct-a-Video (2402.03162) | 摘要：「new temporal cross-attention layers to interpret quantitative camera movement parameters」 |
| **相机** | 任意复杂轨迹（用户可迭代指定轨迹做场景探索） | CameraCtrl II (2503.10592) | 摘要：「iteratively specify camera trajectories for generating coherent video sequences」 |
| **相机** | 6-DoF 位姿 + 内参（多镜头/转场） | ShotDirector (2512.10286) | 摘要：「parameter-level camera control … 6-DoF poses and intrinsic settings」 |
| **相机** | 成对 3D 点轨迹（源/目标视角投影） | Track2View (2606.15534) | 摘要；报告相对基线旋转误差降 30–65%、平移误差降 61–72% |
| **相机** | 几何 token（VGGT 估深度+相机，**免相机标注**） | CETCAM (2512.19020) | 摘要：「eliminates the need for camera annotations through a consistent and extensible tokenization scheme」 |
| **相机** | 显式相机运动，**training-free**，改写中间噪声 latent 的 3D 点云重排 | CamTrol (2406.10126) | 摘要：「does not require any supervised finetuning … or self-supervised training via data augmentation」 |
| **轨迹/运动** | 时空稀疏点轨迹 p[n,t]=(x,y) + 可见性 v∈{0,1}^{N×T}；**任意条数、物体专属或全局、时间稀疏** | Motion Prompting (2412.02700) | §3.1 符号定义原文；附「motion prompt expansion」把高层请求编译成轨迹 |
| **轨迹/运动** | 用户拖一条线（轨迹）+ 实体框 | DragAnything (2403.07420) | 摘要：「Users only need to draw a line (trajectory)」 |
| **轨迹/运动** | 无需训练的 MOFT 特征编辑 | Trajectory Attention (2405.14864) | 摘要「training-free video motion control framework」 |
| **姿态** | 逐帧 2D 骨架(COCO)/3D 坐标/DensePose 序列 | MimicMotion、Champ、Animate Anyone 2 等 | 综述 §5.1.1；关键：**「generated algorithmically」**——即 mocap/Blender 程序化产出 |
| **结构** | 时间稀疏的 sketch / depth / RGB 关键帧锚点 | SparseCtrl (2311.16933) | 摘要；SparseCtrl-HOI(2607.05994) 已把该思路扩到人-物交互 |
| **身份** | 参考图（可多张），conditional encoder，无需微调 | ConsisID；VACE 的 reference 通道 | 综述 §5.2.3「transitioning from slow fine-tuning to Tuning-free approaches」 |
| **局部重做 / 遮罩** | **Video Condition Unit (VCU)**：把 editing / reference / mask 统一成一个接口，Context Adapter 注入 | VACE (2503.07598) | 摘要原文；owner 已把「一致性注入」与「反馈局部重做」统一到这条通道 (`AI视频生产流水线方案.md:52`) |
| **音频** | 音频波形 → 唇形/表情驱动 | EchoMimic 系列、V-Express | 综述 §5.5.3 |
| **多主体+相机+转场** | 统一「实体×时间区间」条件基元 | CineOrchestra (2606.13768) | 摘要：「each is an entity acting over a specific temporal interval … all be expressed through one shared structure」 |

### 2.1 对 owner 的判定：分段流水线能不能成立

**部分成立，但有一个结构性缺口。**

- **已经成立的三条轴**：身份/参考（VACE reference + 资产包）、局部重做（VACE mask）、人体姿态（MimicMotion/Blender 程序化骨架，`AI视频生产流水线方案.md:131`）。这三条都已有**端到端自持的参数接口**。
- **缺口在相机轴**：owner 的 VDL 现在只有符号枚举 —— `camera: {shot: medium, move: dolly-in}`（`AI视频生产流水线方案.md:239`）。这个枚举**不是程序化接口**，它最终落到 prompt 文本或闭源 API 的一个参数（Seedance 的 `camera_fixed` 等，`AI视频生产流水线方案.md:148`）。也就是说：**owner 分段流水线目前唯一没有可编程控制的是分镜表里最结构化的一栏（shot/move）**。
- **结论**：「廉价草稿 + 高级精渲」在成本上成立（L0 本地草稿 = Wan2.1-1.3B fp16，212–214s/33 帧/卡，`:129`），但在**控制力上目前只有 L0 段是程序化的**；要把它升级成真正的「程序化分段流水线」，必须先给相机轴一个位姿接口（见 §6）。

---

## 3. 程序化 vs prompt-only：成本/质量边界

### 3.1 质量侧：prompt-only 的天花板有硬证据

- **VBench-2.0 §V-B 原文**：`Surprising Weakness: Controllability in Simple Dynamics. Most models perform poorly in capturing Dynamic Spatial Relationships and Dynamic Attributes. Even in relatively simple cases … models fail in about 80% of the time.`（`/tmp/vbench2.txt`）
  → **prompt-only 在最简单的时间动态指令上，约 80% 失败率**。这不是「差一点」，是量级差。
- **prompt 级别的相机控制只有离散枚举**：CameraCtrl 附录 E 指出 AnimateDiff「supports only eight base camera movements」，因此他们**无法**为其计算 RotErr/TransErr，只能退回人评（`/tmp/CameraCtrl.txt`）。
- **程序化控制的相对优势有对照实验**：
  - CameraCtrl vs MotionCtrl，复杂 RealEstate10K 轨迹人评偏好 **72.4% vs 27.6%**（CameraCtrl 附录 B/E）。
  - CameraCtrl 相对底座 AnimateDiff/SVD **不牺牲画质与动态度**（FVD/CLIPSIM/FC/ODD 持平或更好）→ 控制增益不是拿画质换的。
  - Motion Prompting 2AFC 人评（各列 N=103/103/115）：Motion Adherence **74.3%**、Motion Quality 80.5%、Visual Quality 77.3%（§5.2）。
  - DragAnything 对 DragNUWA 物体运动控制人评 **+26%**。

### 3.2 成本侧

- **边际生成成本 ≈ 0**：程序化控制的输入是一段位姿/轨迹张量，与文本 prompt 同量级，不增加扩散步数。真正的成本在**一次性训练**或**条件编码器**，不是每次生成。
- **training-free 家族把一次性成本也砍掉**：CamTrol、Trajectory Attention 明确「无需任何微调/自监督训练」，可直接插到预训练扩散模型上。**这在 owner 的硬件上是决定性的**：`AI视频生产流水线方案.md:673` 记录 14B 模型在 V100 社区唯一实跑约 **7 小时/条**，且 V100 fp16 下的行为全网无公开数据。
- **对照的 prompt-only 成本**：prompt 写不准就要 best-of-N 抽卡。owner 的机制是把成本花在 L0 双卡 N=4 → L1 API ¥0.14/s → L2 精修 ¥0.3–0.8/s（`:142–144`）。这是**用采样次数换命中率**，且命中不可控、不可复现（可灵无 seed，`:149`）。

### 3.3 边界与反面证据（必须写出来）

- **程序化控制会引入自己的缺陷**：Motion Prompting §5.1 指出 DragAnything 的 latent warping 模块「虽然能让运动更准，但也产生视觉伪影，表现为 PSNR/SSIM/LPIPS/FVD 全面落后」。→ **控制保真度与画面保真度不是同一个指标，流水线必须同时量两条。**
- **多条件会互相打架**：综述 §7.1「enforcing one constraint often degrades others」，点名结构/时间/风格各自为政的现状。owner 的 VDL 天然是多条件（camera + action + motion + refs + vace.mask 同时存在，`:239–247`），这是结构性风险，不是实现细节。
- **控制精度与分辨率/时长负相关**：CameraCtrl 附录 E 明确「COLMAP 无法在短视频（T2V 16 帧、I2V 14 帧）上稳定提取相机位姿」→ **短镜头上轨迹对齐指标本身不可靠**，需要够长的镜头或改用点轨迹法（Track2View 路线）。

**结论**：程序化控制在 owner 场景里是**净收益**（质量 +2~3 个数量级的差距，成本近乎为零），但必须配一个**控制保真度指标**（轨迹/姿态对齐），否则修好了控制会砸画质。

---

## 4. 评测基准（VBench/EvalCrafter 等）对 owner 70 分目标的适用性

### 4.1 三个基准的覆盖面

| 基准 | 维度 | 与 owner 相关的事实 |
|---|---|---|
| **VBench (2311.17982)** | 16 维（`arxiv_vbench.xml` 摘要：subject identity inconsistency、motion smoothness、temporal flickering、spatial relationship 等） | 全是**无参考的质量/一致性**维度，没有「是否服从外部规格」这一类 |
| **VBench++ (2411.13503)** | 增 I2V 三维 + Trustworthiness（Culture Fairness / Human Bias / Safety） | Temporal Quality 五维：Subject Consistency(DINO)、Background Consistency(CLIP)、Temporal Flickering、Motion Smoothness（插帧模型先验）、Dynamic Degree(RAFT) |
| **VBench-2.0 (2503.21755)** | 5 大维 18 子维：Human Fidelity / Creativity / **Controllability** / Physics / Commonsense | Controllability 七个子维（原文）：Entity-Dynamic Attribute、Entity-Dynamic Spatial Relationship、Event-Motion Order Understanding、Event-Human Interaction、Content-Complex Plot、Content-Complex Landscape、**Camera Motion** |
| **EvalCrafter (2310.11440)** | 700 prompts × 17 客观指标，拟系数对齐人类意见 | **不评可控性**，只评视觉/内容/运动/图文对齐 |
| **ChronoEdit 自带 PBench-Edit (2510.04290)** | 物理一致性编辑 | 域窄（图像编辑），非成片评测 |

### 4.2 结论：作为「验收门」不够用，作为「选型仪器」够用

四条硬缺口，逐条有据：

1. **相机维度测的是 prompt，不是你的规格。** VBench++ §III-A3 原文：Camera Motion 只覆盖 **7 类文本相机运动**（`pan left/right`、`tilt up/down`、`zoom in/out`、`static`），用 **CoTracker 跟踪画面四边点 + 启发式**判别；VBench-2.0 扩到 **9 类**（加 `Orbit`、`Oblique shot, airborne dolly`）。→ owner 若把相机改成 6-DoF 位姿驱动，**VBench 的相机维度就答非所问了**：它问「像不像 dolly-in」，不问「是不是我给的那条位姿曲线」。
2. **VBench-2.0 的 Controllability 全部是文本驱动。** 上述七个子维的 ground truth 全部来自文本 prompt（动态属性/动态空间关系/动作顺序/人际交互/复杂剧情/复杂景观/相机运动）。→ 对**程序化驱动的流水线**，它测的是另一件事。可用作 L2 精修段（闭源 API）的兜底 sanity check，不能作为 L0 草稿段的验收门。
3. **物理/常识维继承 VLM 天花板。** VBench-2.0 Physics 的实现是 video-based multi-QA（LLaVA-Video-7B + Qwen2.5-7B 二值判定，§III-A）。而 owner 仓内调研已实测 GPT-4V 在物理类 ROC-AUC≈53（≈随机）、Gemini 58（`AI视频生产流水线方案.md:353`）。→ **VBench-2.0 的 Physics 只能当 warn-only 信号**，与 owner 把物理归入 D 组「目前只能人检」(`:353`) 的判断一致，不冲突。
4. **没有「镜头/叙事/规格服从」维度。** 最接近的是 VBench-2.0 的 Complex Plot（5 段式、150+ 词），而 §V-B 明说 SOTA 在该维度全部吃力，且基础模型普遍只能出 <10s 单镜头。owner 的 D 组（叙事逻辑、节奏、整体观感）在所有公开基准里**确实没有对应物**。

### 4.3 判定与「是否自建」

> **必须自建，但只自建三样，其余一律复用。**

| 建/复用 | 项 | 理由与证据 |
|---|---|---|
| **自建** | ① **轨迹对齐指标**（RotErr/TransErr 或成对点轨迹误差） | 唯一能验收程序化相机控制的指标；CameraCtrl 给出了 COLMAP 恢复位姿的范式，但也证明 **16 帧短镜头不可靠**（附录 E），owner 需改用点轨迹法或加长镜头 |
| **自建** | ② **VDL-spec adherence 指标**（镜头是否服从 `duration/engine/camera/motion/speech` 各字段） | VBench 全部维度以**文本 prompt** 为 ground truth，owner 的 ground truth 是 VDL 源文件。逐字段做规则校验，零 VLM 成本，落 A 组程序规则（`AI视频生产流水线方案.md:350`） |
| **自建** | ③ **镜头间/转场级指标**（CineOrchestra、ShotDirector 所用的 shot-transition 口径） | 所有公开基准都只评**单条视频**；owner 评的是**多镜成片**。CineOrchestra 在两个新基准上评的正是「dense caption following 与 shot-transition timing」(`2606.13768` 摘要) |
| **复用** | 时间一致性（DINO/CLIP/RAFT/插帧先验）、美学（LAION/MUSIQ）、人体解剖异常（VBench-2.0 的 ViT anomaly detector） | 已在 owner 的 L2 硬校验清单里 (`:136,351`)，无需重造 |
| **复用但降权** | VBench-2.0 Controllability / Physics | 作 warn-only，不进门 |

**这与仓内既有结论不冲突，反而加强它**：`AI视频生产流水线方案.md:156` 已写明「调研确认生态空白：无任何开源流水线公布 judge 选型/阈值/人工上升率」。本次调研进一步收紧了空白边界 —— **不仅阈值没公布，可控性验收本身也没有现成基准，因为现有基准的 ground truth 是 prompt，不是规格**。

---

## 5. 推荐的 3-5 个方向 + 理由

排序原则：先补 owner 流水线唯一的结构性缺口，再补成本最低的增量。

### ① 相机轴：从枚举升级为 6-DoF 位姿序列 + 内参（**最高优先级**）

- **为什么是它**：owner 的 VDL 已经有 `camera: {shot, move}`（`:239`），是分镜表里最该被程序化的字段，却是唯一仍是符号枚举的字段。学术界 2023→2026 的接口已完全收敛到 (R,T,K) 序列（CameraCtrl 2404.02101 → ShotDirector 2512.10286 → Track2View 2606.15534），且 CineOrchestra 证明它能与主体/事件/转场在同一模型里共存。
- **接口范式**：K(3×3) + E=[R;t](3×4) → Plücker 嵌入 → 轻量 camera encoder 插件，底座不动（CameraCtrl §3.2 + 附录 D.1）。
- **收益**：L0 草稿段的运镜从「抽卡碰运气」变成「可声明、可 diff、可回归」；VDL 的 `move: dolly-in` 变成一条可校验的曲线。
- **代价与已知坑**：COLMAP 在 16 帧短镜头上不稳（CameraCtrl 附录 E）→ 验收指标必须换点轨迹路线（Track2View 2606.15534 的 paired 3D point tracks）。

### ② training-free 控制器优先（**成本杠杆最大**）

- **为什么是它**：CamTrol(2406.10126) 与 Trajectory Attention(2405.14864) 明确零训练、可插到预训练扩散模型。owner 的 2×V100S/SM70/fp16/无 NVLink 决定了**任何需要微调的视频控制器都排不进产线**（14B 社区实跑 ≈7h/条，`:673`）。
- **收益**：这是唯一「不新增算力、不新增数据、新增代码量最小」的可控性增量。
- **注意**：Trajectory Attention 的 MOFT 路线依赖模型内部特征（PCA 分析出已有 motion-aware 特征），**在 Wan2.1-1.3B 上是否成立未经验证**——列为 spike 而非结论。

### ③ 统一运动提示（track-conditioned）+ motion prompt expansion（**最贴合 owner 的槽位模型**）

- **为什么是它**：Motion Prompting(2412.02700) 一个模型同时覆盖相机运动、物体运动、拖拽编辑，且其 **motion prompt expansion**（把高层请求编译成半稠密轨迹）正是 owner 需要的形态：**分镜槽位（`move: dolly-in`、`motion.walk: 2steps`）→ 轨迹序列的编译器**。
- **证据**：2AFC 人评 Motion Adherence 74.3%、Motion Quality 80.5%、Visual Quality 77.3%（N=103/103/115，§5.2）。
- **对 owner 的直接映射**：`AI视频生产流水线方案.md:243` 的 `motion: {walk: 2steps, gesture: pickup}` 字段目前只对姿态层有效；若编译成轨迹，可覆盖非人体物体与道具。

### ④ 多镜头 / 转场程序化（**owner 的剧集线独有需求，学术最空白**）

- **为什么是它**：CineOrchestra(2606.13768) 是目前唯一把「主体 + 事件 + 相机 + 转场」四轴统一的框架，且它自建了对应基准与用户研究；ShotDirector(2512.10286) 专攻转场并给出 6-DoF 相机控制。
- **对 owner**：成片聚合函数 `成片分 = 0.7×均值 + 0.3×最差镜头`（`:162`）本身就需要跨镜头量，而 VBench 系全部是单条视频评测。这条轴的基准缺口最值得 owner 提前占位（自建 §4.3-③）。

### ⑤ 稀疏关键帧锚定（SparseCtrl 式）作为「时间轴版 VACE」

- **为什么是它**：SparseCtrl(2311.16933) 的核心洞察是稠密结构序列（逐帧 depth/edge）**增加推理负担**，改用时间稀疏锚点即可获得同等结构控制。owner 已有 VACE 通道承担「先编辑后运动 + 局部返修」(`:52,150`)，稀疏锚定是它在**时间维度**上的对应物。
- **收益**：廉价草稿阶段可用**极少数关键帧**锁定节奏与构图，把自由度留给后续精修段 —— 正是「廉价草稿 + 高级精渲」想要的资源分配形状。

**明确不推荐（本次调研后）**：把 AnimateDiff/Gen-2 motion brush 类 prompt 级运镜（8 类离散运动）作为可控轴 —— CameraCtrl 附录 E 已证明它连轨迹误差都算不出来。

---

## 6. 对 owner 的行动建议（3 条）

1. **把 VDL 的 `camera` 字段从枚举升级为 6-DoF + 内参的位姿序列**（`AI视频生产流水线方案.md:239`），接口范式直接抄 CameraCtrl 的 K/E → Plücker → 轻量 encoder；同步新建**轨迹对齐硬指标**（优先点轨迹法，不用 COLMAP —— CameraCtrl 附录 E 已证明 16 帧短镜头恢复不可靠）。理由：这是 owner 流水线唯一「分镜表里有、但还没程序化」的字段，也是唯一没有现成基准的轴；先占位等于同时拿到接口红利与评测定义权。

2. **先做 training-free 控制器 spike，不做任何微调**（CamTrol / Trajectory Attention 路线，挂在 Wan2.1-1.3B + VACE 上）。理由：owner 硬件（2×V100S、SM70 仅 fp16、无 NVLink）使一切需微调的视频控制器在排产线之外（14B 社区实跑 ≈7h/条，`:673`），而这族方法明确零训练可插。**spike 结果无论成败都进 L2 硬校验而不是 judge**，并必须同时量「控制保真度」与「画质保真度」两条曲线（DragAnything latent warping 拖垮 PSNR/SSIM/FVD 是已证实的反面案例）。

3. **评测口径上：把 VBench/VBench-2.0 降级为「选型仪器 + warn-only 信号」，把 70 分验收全部锚到自建的 VDL-spec adherence 上。** 理由：VBench++ 的 Camera Motion 只判 7 类 prompt 相机运动、VBench-2.0 的 Controllability 七个维度 ground truth 全是文本 prompt —— 对程序化流水线**测的不是同一件事**；且所有公开基准均为单条视频评测，owner 评的是多镜成片。建议只自建三样：**①轨迹对齐 ②VDL 逐字段规格服从（纯规则，零 VLM 成本，落 A 组）③跨镜头/转场级指标**；时间一致性、美学、解剖异常检测继续复用现成实现。这与仓内既有结论（`:156` 无任何流水线公布 judge 阈值）一致，本次只是把空白边界收得更紧：**缺的不只是阈值，可控性验收本身就没有现成基准，因为现有基准的 ground truth 是 prompt，不是规格。**

---

### 附：本次实际读到的论文清单（arXiv ID → 用途）

**一手读到全文 HTML**：`2507.16869v3`（分类法与成熟度判断的主干）、`2503.21755v2`（VBench-2.0 维度/人类对齐/80% 失败率）、`2411.13503v1`（VBench++ 维度与 7 类相机运动）、`2404.02101v2`（CameraCtrl 位姿表示与 72.4%/27.6% 人评）、`2412.02700v2`（Motion Prompting 轨迹符号定义与人评）、`2405.14864v3`（Trajectory Attention training-free 主张）。

**读到官方摘要**：`2312.03641`(MotionCtrl)、`2307.04725`(AnimateDiff)、`2403.07420`(DragAnything)、`2310.08465`(MotionDirector)、`2402.03162`(Direct-a-Video)、`2310.11440`(EvalCrafter)、`2510.04290`(ChronoEdit)、`2405.01434`(StoryDiffusion)、`2503.10592`(CameraCtrl II)、`2311.16933`(SparseCtrl)、`2406.10126`(CamTrol)、`2503.07598`(VACE)、`2502.02690`(CoVoGAN)、`2401.15977`(Motion-I2V)、`2504.13074`(SkyReels-V2)、`2512.10286`(ShotDirector)、`2512.19020`(CETCAM)、`2606.15534`(Track2View)、`2606.13768`(CineOrchestra)。

**未读原文、仅经综述二次引用**：`2502.01061`(OmniHuman-1)、MimicMotion、ConsisID、Animate Anyone 2、V-Express、InterMimic、WorldModelBench、PhyGenBench。