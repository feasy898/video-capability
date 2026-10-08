# DramaClaw 深度拆解（面向 owner「工业化确定性生产」）

> 编制：工业化视频流水线调研员 · 2026-10-08
> 目标读者：owner（video-capability / v3 vpipe 线）
> 仓内已有材料：`_probe/dramaclaw-readme.md`（仓库 README 快照，本次全部结论以源码复核为准）

---

## 0. 取证方法与口径声明（先读这一节）

| 项 | 内容 |
|---|---|
| 仓内材料 | `_probe/dramaclaw-readme.md`（482 行，本次逐行读过；行号引用格式 `readme:L<行号>`） |
| 线上复核 | `gh api repos/dramaclaw/dramaclaw/...` 只读拉取 docs/ + src/ + frontend/ + `.hermes/` |
| 代码基线 | commit `9822d6fd9ff6d9d2d47d725209b88af75140f676`（2026-10-08T07:16:07Z，`fix(images): default gateway image models to LingShan-G2 (#781)`） |
| 最新 release | `v2.0.6`，发布于 2026-09-28T11:07:10Z（`gh api repos/dramaclaw/dramaclaw/releases/latest`） |
| 仓库规模 | 6,758★（本次实测；仓内 `AI视频生产流水线方案.md:L686` 记录的 6,559★ 是 2026-09-28 快照，未复核，本次更新） |
| **未做的事** | ① `git clone` 被网络策略拒绝（`Failed to connect to github.com port 443`，132s 超时），故全部源码走 `gh api contents` 逐文件拉取，**没有跑过一行 DramaClaw 代码、没有起过服务、没有看过官方样片**；② 未核实官方样片是否达「70 分可用」；③ README 的 `pipeline.png` 是图片，未做视觉判读，四段命名以 zh 架构文档与代码为准。 |

**引用约定**：下文 `dc:<路径>:<行号>` = 上游仓库 dramaclaw/dramaclaw 的文件路径与行号；`readme:L<行号>` = 仓内 `_probe/dramaclaw-readme.md` 行号。

---

## 1. 项目定位与四段流水线边界

### 1.1 定位：双轨，一个资产库，一个 agent

DramaClaw CE 不是 SaaS，是**单机 source-available 生产线**：一个 FastAPI 进程 + 本地 SQLite + 本地文件，一个 OpenAI 兼容网关接模型，无需 Postgres/Redis/Celery/Ray（`dc:docs/zh/concepts/architecture.md:L6, L65`；`readme:L277`）。

它有**两张脸**共用**一个资产库**和**一个 agent**（`readme:L145-L152`）：

- **XiaHua（虾画）** — 无限画布，自由探索；
- **Series（虾记）** — 剧本 → 成片的固定流水线；
- **Xia Director（虾导）** — 跨两者的 agent。

官方自己的定位句是"不是二选一，是双轨 over one asset library"（`readme:L235`）。

### 1.2 四段的边界：文档里的四段 vs 代码里的 30 个 task type

**文档层**：架构文档只有一张图，四个词「摄取、规划、生产、交付」（`dc:docs/zh/concepts/architecture.md:L17`）。README 的四段名 Ingest/Plan/Produce/Deliver（`readme:L184`）。

**代码层**：真实边界不是 4 个，而是 **30 个 task_type + 5 个 episode stage + 21 个 asset slot**。

| 层 | 定义位置 | 内容 |
|---|---|---|
| 异步工作单元 | `dc:frontend/src/lib/task-types.ts:L13-L52` | 30 个 canonical `task_type` 字符串（项目级 7 + 剧本 6 + 草图 5 + 音频 2 + 视频 3 + 合成 1 + ingest 等） |
| 每集阶段 | `dc:frontend/src/lib/episode-stage-registry.ts:L7, L22-L80` | `script → sketch → audio → video → compose`，每阶段声明 `taskTypes` + 硬前置 `dependsOn` |
| 流水线聚合状态机 | `dc:src/novelvideo/api/routes/pipeline.py:L18-L35, L206-L224` | 16 步 `_STEP_MAP`，逐键判定完成度，输出 `next_step` |
| 资产槽位 | `dc:src/novelvideo/freezone/slots.py:L35-L215` | 21 种 `SlotTarget`，画布写回主线的唯一合法通道 |

**四段 → 具体步骤的映射**（据 `pipeline.py` `_STEP_MAP` + `pipeline-details.md` + `episode-stage-registry.ts` 交叉得出）：

| 段 | 步骤（`pipeline.py` 的 `next_step` 键） | 产物落点 |
|---|---|---|
| **Ingest 摄取** | `ingest` → `configure` → `characters` → `episodes` → `portraits` | `novel.txt`、characters 表、episodes 表、肖像图 |
| **Plan 规划** | `identity_plan` → `identity_images` → `script` →（scenes/props） | `beats` 表（VisualBeat）、identity 参考图、场景/道具库 |
| **Produce 生产** | `sketches` → `coloring` → `global_optimize` → `first_frames` → `tts` → `video` | grids/sketch、frames/epNNN、audio/epNNN、videos/beats/epNNN |
| **Deliver 交付** | `compose` → `done` | `videos/episodes/epNNN_final.mp4` + SRT + zip 素材包 |

### 1.3 段间数据 schema（这是本节最硬的部分）

**核心中间表示 = `VisualBeat`**（`dc:src/novelvideo/models.py:L828-L936`）。全流水线只有这一个结构在段间流动：

```
VisualBeat:
  beat_number            int          节拍序号（从 1）
  narration_segment      str          这段解说词/台词（中文）
  visual_description     str          画面描述（中文）—— 内嵌 {{identity_id}} 标记
  time_of_day            str          独立时间条件，不拼进 scene 名
  scene_ref              SceneRef?    { scene_id, variant_id, render_anchor_id, ... }
  audio_type             str          silence | narration | dialogue | action
  speaker / speaker_kind str          character | non_character（广播/画外音/字幕）
  shot_order / duration_seconds / is_manual_shot   手工插入分镜（fractional ordering）
  frame_pool_id          str?         选中的池图 ID，格式 "{mode}_{grid_idx:02d}_{cell_idx:02d}"
  video_versions         [str]        历史版本路径
  video_pool_id          str?
  video_mode             str          first_frame | keyframe（首尾帧过渡）
  video_prompt / keyframe_prompt / action_description
```

关键设计取舍（值得 owner 注意）：

1. **`narration_segment` 与 `visual_description` 强制成对**，一对一绑定（`models.py:L829-L842`）。这是"文案长度直接决定 TTS 时长→决定镜头时长"的锚，比自由分镜更容易确定性排期。
2. **`scene_ref` 拆成 `scene_id` + `variant_id` + `render_anchor_id` 三个正交维度**（`models.py:L132-L145`）。场景 = 空间基底，变体 = 外观/状态，anchor = 渲染锚。这三者的分离是"同一场景跨镜头一致"能成立的**结构前提**。
3. **`time_of_day` 明确不拼进场景名**（`models.py:L844-L847` 注释"独立时间条件"），避免"夜晚_客厅"这种组合爆炸。

**其他段间契约**：

- **剧本 schema**（`models.py:L807-L826`）：`NarrationScript = { episode_number, title, beats[], total_duration_seconds }`，**扁平 beat 列表**，总时长 = Σ`estimated_duration`。
- **分集 schema**（`models.py:L782-L804`）：`EpisodeNode = { number, title, chapter_start, chapter_end, summary, key_events[], characters[], cliffhanger, script_generated, images_generated, audio_generated, video_generated }`。注意 `chapter_start/chapter_end` —— 分集是**章节区间映射**，不是自由创作。
- **摄取契约**（`dc:src/novelvideo/structured_ingest.py:L29-L31, L150-L169`）：新项目走 `structured_v1`，**不建知识图谱、不做 embedding、不建向量索引**，只做「读原文 → 确定性切块 → 记录分析计划 → 落盘」。返回 `{char_count, status, pipeline, run_id, chunks, section_type}`。**`novel.txt` 最后写**——它是"导入成功"的公共标记符，导入还可能失败时不能出现（`structured_ingest.py:L9-L12, L150`）。这是很干净的 failure-atomic 设计。

### 1.4 契约之外的三条工程铁律

| 铁律 | 出处 | 内容 |
|---|---|---|
| **每步独立异步 + 可跳步 + 可续跑** | `readme:L187, L237`；`architecture.md:L20` | "the toolchain itself is the product, with no hidden black box" |
| **前置校验在入队前** | `readme:L195` | "prerequisites are validated before a job is queued" |
| **未知 task_type 一律判为需 home node** | `dc:src/novelvideo/task_backend/registry.py:L63-L72` | 注释写明："the answer that keeps today's behaviour is 'check it', not 'wave it through'"。**这是防未知任务静默放行的 fail-safe 默认值** |

---

## 2. XiaHua 画布 + 节点 + Director agent 协作机制

### 2.1 18 种节点类型（实测确认，非 README 转述）

`dc:frontend/src/features/canvas/domain/canvasNodes.ts:L10-L29` 的 `CANVAS_NODE_TYPES` 常量**恰好 18 项**（本次用脚本数过）：

| # | key | 磁盘类型串 | 菜单可见 | 性质 |
|---|---|---|---|---|
| 1 | upload | `uploadNode` | ✅ | 素材入口 |
| 2 | imageEdit | `imageNode` | ❌ | 由 imageGen 面板 spawn |
| 3 | imageGen | `imageGenNode` | ✅ | 生图 + 10 项图像工具 |
| 4 | exportImage | `exportImageNode` | — | 结果出口 |
| 5 | beatContext | `beatContextNode` | — | **主线节拍投影** |
| 6 | textAnnotation | `textAnnotationNode` | ✅ | 文本/审片报告 |
| 7 | group | `groupNode` | ✅ | 分组 |
| 8 | storyboardSplit | `storyboardNode` | — | 宫格切分 |
| 9 | storyboardGen | `storyboardGenNode` | — | 分镜生成 |
| 10 | video | `videoNode` | ✅ | 视频生成 + 剪辑/擦除/超分 |
| 11 | audio | `audioNode` | ✅ | TTS + 音乐 |
| 12 | videoStory | `videoStoryNode` | — | 视频故事 |
| 13 | videoCompose | `videoComposeNode` | ✅ | 合成 |
| 14 | script | `scriptNode` | — | 剧本 |
| 15 | pano360Viewer | `pano360ViewerNode` | ✅ | 360 全景查看器（可截图） |
| 16 | threeDWorld | `threeDWorldNode` | ✅ | **Director World 3DGS** |
| 17 | skill | `skillNode` | — | 画布技能 |
| 18 | style | `styleNode` | ❌ | 风格投影，**对账规则驱动，用户不能从菜单创建**（`canvasNodes.ts:L700-L707`） |

**边契约极简**（`canvasNodes.ts:L732-L737`）：`CanvasEdgeData` 只有一个业务字段 `keyframeSlot: 'first' | 'last'`。其余全部靠"哪个节点的哪个 slot 接了谁"隐式表达——这正是 §4 要讲的槽位制。

### 2.2 8 个画布技能：真正的协作协议

`dc:src/novelvideo/freezone/skill_registry.py:L222-L600` 注册了**恰好 8 个**技能（实测），分三类 provider：

| provider | 技能 | 能力位 |
|---|---|---|
| `freezone_mainline` | `sketch_from_context`、`sketch_from_director_combined`、`frame_from_context`、`set_selected_background`、`set_director_combined`、`scene_360` | `can_read_project_state=True` |
| `agent` | `review_frame` | 无（空能力） |
| `workflow` | `plan_beat_graph` | `can_read_canvas` + `can_read_project_state` + `can_propose_canvas_patch`（**`can_apply_canvas_patch=False`**） |

技能契约是 pydantic 化的（`skill_registry.py:L15-L152`）：

- **能力位** `SkillCapabilities`：5 个布尔权限（读画布 / 读项目状态 / 联网 / **提议**画布补丁 / **应用**画布补丁）；
- **输入接受** `SkillInputAcceptSpec`：不是"任意上游节点"，而是**按 `canonical_slot_kinds` + `candidate_origin_skill_ids` + `has_field` 三重白名单**收窄（`skill_registry.py:L23-L38, L186-L198`）；
- **输出** `SkillOutputSpec`：`media_type ∈ {image, text, json, node_patch, graph_patch}`，`node_type` 指定产物落到哪个节点类型，`pushable` 声明能否写回主线；
- **幂等**：`SkillRunRequest` 带 `idempotency_key`（`skill_registry.py:L81`）。

**协作协议的关键在于 `canonical_slot_kinds` 这一层。** 例：`frame_from_context` 的 5 个输入位是 `beat_context`(必需单) + `sketch`(必需单) + `background`(可选单) + `identity`(可选多) + `prop`(可选多)（`skill_registry.py:L317-L396`）。身份位只接受 canonical slot kind 为 `identity`/`portrait` 的图，**不接受随便连上来的任何图片**。这让"这一步到底吃了什么"是**可静态校验**的，而不是靠 prompt 祈祷。

### 2.3 Director agent：33 个工具 + 33 条硬边界

**能力面**（`dc:.hermes/plugins/dramaclaw/__init__.py:L1691+` 的 `TOOLS` 元组，实测 33 个具名工具）：

- 4 个裸 HTTP 动词：`dramaclaw_get/post/patch/delete`；
- 1 个状态：`dramaclaw_pipeline_status`；
- 1 个任务：`dramaclaw_list_tasks` + `dramaclaw_get_task`；
- 27 个业务专用工具：`dramaclaw_build_characters` / `dramaclaw_plan_episodes` / `dramaclaw_generate_script` / `dramaclaw_plan_identities` / `dramaclaw_generate_identity_image` / `dramaclaw_generate_scene_master` / `dramaclaw_generate_scene_reverse` / `dramaclaw_generate_sketches` / `dramaclaw_detect_sketch_identities` / `dramaclaw_render_first_frames` / `dramaclaw_generate_audio` / `dramaclaw_start_single_video` / `dramaclaw_compose_episode` / `dramaclaw_get_final_video` …

SKILL 文档反复强调"**触发用专用工具，不要自己拼路径**"（`dc:.hermes/skills/dramaclaw/references/pipeline-details.md:L50-L52`）。

**约束面——这是全仓最有工程价值的一份文档**：

| 约束 | 出处 | 内容 |
|---|---|---|
| **一轮最多 1 个写任务** | `run-modes.md:L3-L4, L117` | "两种模式都不能在一轮里连续启动多个写任务" |
| **大任务先拆解确认** | `run-modes.md:L11-L19` | 用户说"做完这一集"→ 先拆解、再读状态、只问一个下一步 |
| **启动即收口，不轮询到完成** | `run-modes.md:L45, L118-L119` | ❌ "启动异步任务后继续轮询到 completed，再自动进入下一步" |
| **失败不许收口成成功** | `pipeline-details.md:L282` | 启动成功但状态 failed → "不要把失败收口成'已重做完成'" |
| **不许交付技术痕迹** | `delivery-boundaries.md:L3-L19` | 可交付：业务产物 / 状态 / 接口返回的相对路径；不可交付：API 端点 / JSON 参数 / 调试路径 / **伪造或猜测出来的结果链接** |
| **不许拼 URL、不许探测路径** | `delivery-boundaries.md:L23-L32, L56-L68` | "`generated: true` 不等于返回了新视频路径"；"没有 `result.video_path` 时不要探测 `/files`" |
| **不许依赖不存在的接口** | `pipeline-details.md:L155, L176, L250, L268` | 反复声明"当前后端没有 `/literal-script/generate`""不要要求 `script_mode == 'literal_source'`""不要调用不存在的 `/videos/generate`" |

最后一条尤其值得 owner 注意：**agent skill 文档里大量篇幅在纠正"以为自己知道后端有什么"的幻觉**。这是用语言模型当编排器必然付的税，DramaClaw 的做法是**把"接口真相"写进 skill 并反复声明禁止猜测**，而不是靠运行时校验。

### 2.4 与 hypit / HyperFrames 的本质差异

> **口径纠正（重要）**：本次在两个上游都做了核查——
> - hypit 的技能树是**单技能**：`skills/hypit/SKILL.md`（321 行）+ `references/` 下的分册（`creation/` `environment/` `playbooks/` `production/`）。README 也只写一个 `/hypit` skill（`_probe/hypit-readme.md:L143-L158`）。**hypit 没有「router skill」**。
> - 「router skill + 按需安装的领域技能」是 **HyperFrames** 的架构：21 个技能，`/hyperframes` 是 router + capability map，按需 `npx hyperframes skills update <workflow>` 安装单个 workflow，核心集保持精简（`_probe/hyperframes-readme.md:L55, L67, L71, L93`）。
>
> 下面对照 hypit（单体 skill + 文本语言）与 HyperFrames（router + 技能市场）两条线。

| 维度 | DramaClaw XiaHua + Director | hypit（SVML） | HyperFrames（router skill） |
|---|---|---|---|
| **控制流的载体** | **图**（18 类节点 + 边 + 21 槽位） | **文本**（SVML 源文件） | **文本**（HTML + `data-*` 时序属性） |
| **谁决定拓扑** | agent 生成 `graph_patch`，`requires_apply=True`，人工在浏览器批准（`skill_registry.py:L104-L126`：Operation L104 / Patch L122；`readme:L225, L382`） | 编译期固定，用户/agent 手写 | router 按意图选 workflow，用户/agent 编辑 |
| **agent 的权限模型** | 显式 5 位能力表；`can_apply_canvas_patch=False` 给 workflow provider | skill 自述"你是导演兼制片"，无显式权限位 | router 显式"confirm every creation brief up front" |
| **是否可静态校验** | **可**：输入接受有 slot-kind 白名单 + node_type 白名单，非法连线在服务端被拒（`fz_routes.py:L3495-L3502`，错误码 `skill_input_node_type_rejected`） | 可（编译器），但语义自由度大 | 可（lint 阶段） |
| **重入/复现** | 节点带 `generationDurationMs`、`skillIdempotencyKey`、`skillInputSignature`（`canvasNodes.ts:L684-L698`） | 一个 workflow 文件 = 一个可重跑合成 | 同左 |
| **本质分歧** | **图 = 可被机器增删改的状态**；拓扑是数据 | **文本 = 人可读可 fork 的源码**；拓扑是代码 | 同 hypit |

**一句话结论**：DramaClaw 把「编排」从**文本程序**降维成了**可被 agent 直接改写的数据结构**，代价是引入了图编辑的全部复杂度（幂等、并发、撤销、审批）；hypit/HyperFrames 把编排留在文本里，agent 只是写手。**owner 的两条产线（剧集线 + 模板线）恰好各站一边**——剧集线更接近 DramaClaw 的图+槽位，模板线天生属于 hypit 的 SVML。这不是二选一。

---

## 3. Director World 空间一致性方案

### 3.1 3DGS 到底在解决什么

README 的表述（`readme:L172`）："image → 3D Gaussian Splat set and scene-360 panoramas as canvas nodes: a framable virtual set that **locks spatial structure, character blocking and camera placement**, so the same location stays consistent across shots; frame the shot in the 3D viewer, **capture it, and use it as the background for the next generation**."

拆成三件事：
1. **锁空间结构**：场景是一个已存在的 3D 表示，不是每镜重新想象；
2. **锁走位与机位**：角色 actor 与相机在 3D 里有坐标；
3. **输出为 2D 控制帧**，喂给下游 2D 生成当背景。

### 3.2 生产链路（代码实测）

`dc:src/novelvideo/director_world/scene_360_builder.py:L1-L8` 写得很清楚：

> "The production route is **master/text → pano_360.png → pano_sharp PLY → 3GS**. Voxel worlds are generated from the separate `spatial_layout` asset, not from this rendered panorama."

```
scene master.png ──┐
                   ├─→ spatial contract (VLM) ──→ pano_360.png (2:1 equirect) ──→ pano_sharp ──→ 3GS SOG/PLY
scene reverse.png ─┘                                                        └─→ voxel spatial_layout ──→ BlockWorld (Node.js)
```

**资产清单由 manifest 管理**（`dc:src/novelvideo/director_world/stage_manifest.py:L1-L42, L54`）：

```
output/<user>/<project>/director_worlds/<scene>/v1/stage_manifest.json
  schema_version = "stage_manifest_v1"
  source ∈ {custom_scene, uploaded_360, uploaded_master, text_to_360, single_face_master, single_face_reverse}
  pano_path / ply_path / pano_ply_path / pano_depth_ply_path
  master_ply_path / reverse_ply_path / custom_scene_path
  collision_glb_path / voxel_json_path
  pano_correction = { front_yaw_deg, sphere_correction_deg{roll,pitch,yaw} }
  *_sharp_args / scene_360_args / splat_transform_args   ← 全链路参数留档
```

`has_3gs_assets()` 要求 **PLY 存在 + collision GLB 存在**才算入口可用（`stage_manifest.py:L140-L158`）——没有碰撞体就没有走位约束，直接挡住 3D 编辑器入口。

### 3.3 真正的技术核心：`scene_spatial_contract`

这是全仓最有借鉴价值的一份设计。`dc:src/novelvideo/director_world/scene_spatial_contract.py`（1137 行），schema 版本 `scene_spatial_contract_v8_topology_only_locks`（`L29`）。

**它解决的问题**：把"master 正视图 + reverse 背视图"两张图缝成一张 360 全景，最容易出的错是**接缝处穿帮**和**前后墙错位**。DramaClaw 的做法是：

1. **先定接缝安全布局**（`L189-L207`）：明确 x 轴契约——
   - `x=0%/100%` = 低细节侧边接缝（MASTER 左 = REVERSE 右）
   - `x=25%` = MASTER 正中
   - `x=50%` = 右侧接缝（MASTER 右 = REVERSE 左）
   - `x=75%` = REVERSE 背面正中
   - **"接缝处必须是普通连续墙/地/顶，不能是门、走廊、展示板或柜子"**
   - "REVERSE 屏幕左 → x=50%..75%；REVERSE 屏幕右 → x=75%..100%；REVERSE 正中 → x=75%，**不是跨接缝**"（"non-negotiable"）

2. **先跑 overlap 分析，再跑 contract**（`dc:scene_overlap_analyzer.py:L1-L3`）。`dc:scene_spatial_contract.py:L146-L174` 把分析结果注入 contract prompt，并明确区分三类语义：
   - `overlap anchors / MERGE ONCE`（两个视图里都出现 → 合并成一个，别造两个）
   - `continuation zones`（延续区）
   - `GLOBAL DO NOT DUPLICATE / WARNINGS ONLY`（**重复警告，不是自动锚点**）

3. **输出 schema 是纯拓扑，不含坐标**（`L208-L289`）：
   ```json
   {
     "schema_version": "scene_spatial_contract_v8_topology_only_locks",
     "coverage_assessment": { master_coverage, reverse_coverage, coverage_gaps[{area, inference_rule}] },
     "walls": {
       front/back/left/right: {
         panorama_position, source,
         must_preserve: [{ name, type, count, source_view, source_side,
                          panorama_zone, placement, size_lock,
                          visual_identity, must_not_become[] }],
         inferred_fill: [], shared_overlap: []
       }
     },
     "joins": [{ id, panorama_position, source_pair,
                 merge_once[], continue_smoothly[], do_not_duplicate[] }],
     "must_not_transform": [{ source_object, forbidden_transform, reason }],
     "direction_exclusion_locks": [{ name, required_direction, required_panorama_zone,
                                     must_not_appear_in, reason }],
     "pano_prompt_insert": "给 360 生图 prompt 的硬约束"
   }
   ```
   提示词末尾明确写死：**"Do not output bbox or original-image coordinates. The downstream topology guide is coordinate-free."** 并且限制每面墙最多 8 个 `must_preserve`，"看不全的地方放 coverage_gaps + inferred_fill，而不是编一面自信的墙"（`L274-L289`）。

**这是 owner 项目里可以直接搬走的一块**：它把"跨镜头空间一致性"从一个 prompt 技巧，变成了 **①坐标契约 + ②语义锚点清单 + ③负向锁 + ④显式的不确定性声明** 四件套的 JSON。

### 3.4 从 3D 到 2D：控制帧合成

`dc:src/novelvideo/director_world/control_frame_compose.py:L1-L20, L69-L104`：PlayCanvas 从实时渲染器直出三层——

```
env_only.png             3GS 场景（无 actor/prop）
actor_overlay_black.png  黑底 + actor/prop 网格
actor_mask.png           白-on-黑 遮罩
   ↓ combined = paste(overlay, into=env_only, mask=actor_mask)
combined.png             合成帧 → 下游 sketch/frame 生成的背景
selected_background.png  env_only 的镜像 = 本 beat 对外唯一"当前背景槽"
```

`selected_background.png` 的注释是全仓设计意图的浓缩（`L90-L97`）："cropper 路径（master/reverse/360-snap/3GS-导演台 export）和 director compose 路径都写**同一个 canonical slot**，避免两份并存导致的一致性问题。"

**3D 侧的数据模型**（`dc:src/novelvideo/director_world/models.py:L20-L76`）：
- `DirectorActor`：`identity_id` + `marker_color` + `position(xyz)` + `yaw` + `state` + `seat_id` / `attached_to` / `gaze_target`
- `DirectorProp`：`prop_id` + `marker_color` + `position` + `scale` + `shape_hint`（8 种白名单：box / generic_large / quadruped_mount / wheeled_artillery / long_vehicle / sports_car / flying_craft / pile）+ `affordances` + `attachment_points` + `tracking` + `asset_scope(global)` + `preserve_marker_color`

### 3.5 是不是 owner 想要的关键基础设施？

**判断：是"之一"，但不是唯一，也不是最优先的那一个。**

支持"是"：
- 它是**唯一**能把"同场景跨镜头一致性"从概率问题变成工程问题的机制——其余手段（角色 tag、参考图）只解决**人/物**的一致，Director World 解决的是**空间**的一致。
- 它是**确定性资产**：3GS + manifest + collision GLB 一旦建好，后续所有镜头共用，成本摊薄到零边际。
- 它把机器可检查性带进来了：位置、yaw、scale 都是数值。

反对"现在就该做"：
- **它是整条线上最重的一环**。README 明说只有可选的 `world` extra 需要 GPU+CUDA 镜像（`readme:L272`），体素生成还需要 Node.js 运行时（`dc:director_world/block_world_builder.py:L16-L27`，错误码 `BLOCK_WORLD_UNAVAILABLE`）。owner 的硬件是 2×V100S-32GB / SM70 / 仅 fp16（`INTENT.md` §1）——**这个栈跑不动主流 3DGS 重建**。
- **它解决的痛点排序低于身份一致性**。短剧"70 分"被拉下来的第一大类是人物跨镜变脸，不是空间穿帮。
- **它没有进入 release**。Director World 在 README 的"Core Capabilities"里（`readme:L172`）有明确条目，但 `xia-director-canvas` 那条 17 节点 32 边的能力被放在 "**In Development** — 这些在公开构建中，尚未进入任何 release"（`readme:L378-L385`）。

**更准确的定位**：Director World 是 owner 剧集线的 **P2 之后的差异化上限**，不是 P0/P1。当前应该抄的是它的**契约层**（§3.3 的 spatial contract JSON + §3.4 的 canonical slot），不是它的**实现层**（3DGS / PlayCanvas / voxel）。

---

## 4. XiaTang 资产库与身份一致性机制

### 4.1 库的组织：三层 + 21 个 canonical slot

**三层划分**（`dc:src/novelvideo/freezone/slots.py:L186-L212`）：

| 层 | kinds |
|---|---|
| `GLOBAL_ASSET_KINDS`（跨集复用） | identity, identity_costume, identity_portrait, portrait, prop_ref + 全部 scene_* |
| `SCENE_ASSET_KINDS`（11 种） | scene_master, scene_360, scene_reverse_master, scene_spatial_layout, scene_director_pano_360, scene_3gs_active_ply, scene_3gs_master_ply, scene_3gs_reverse_ply, scene_3gs_pano_ply, scene_3gs_custom_scene, scene_3gs_collision_glb |
| `BEAT_SCOPED_KINDS`（单镜） | frame, sketch, director_render, selected_background, video, beat_audio |

**每个 slot 是 `kind` + 定位键** 的判别联合（`slots.py:L35-L215`），例如 `SceneMasterTarget{kind, scene_id}`、`FrameTarget{kind, episode, beat}`、`IdentityTarget{kind, character, identity_id}`。

`slots.py:L1-L4` 的模块 docstring 是整套设计的宪法：

> "A slot is not a canvas node and not a recipe. It is **the controlled canonical write target shared by the main pipeline and Freezone's Commit to Asset flow**."

**这就是"双轨"的真正实现**：主线和画布不是两套存储，是**两套生产者写同一个 sink**。画布上的满意候选通过 slot 写回主线（`readme:L171`），反向则用 preset 从主线投影出初始画布（`dc:src/novelvideo/freezone/presets.py:L1-L6`）。

### 4.2 身份的粒度：identity 才是本质

`dc:src/novelvideo/models.py:L960-L1020+` 的 `CharacterIdentity` docstring 直接写着"**核心理念：身份才是本质**。同一角色可以有多个身份，每个身份有独立的外貌、服装、Prompt、参考图"，例子是同一个"谢铮"的"和尚"与"皇帝"。

字段：`identity_id`（`谢铮_皇帝`）、`character_name`、`identity_name`、`character_tag`、`appearance_details`、`reference_images[]`、`face_prompt`、`age_group`、`body_type`、`fish_voice_id`、`reference_audio_path`。

**这直接对应短剧的现实**：主角不是一个人，是一个**跨集复用 58 集的身份集合**（README 的样例《天命不可欺》出到第 58 集，`readme:L120`）。

### 4.3 身份一致性的四道锁（这是本节的核心答案）

| 锁 | 机制 | 出处 | 强度 |
|---|---|---|---|
| **① 文本身份锁** | `character_tag = [TRY_a1b2]`：拼音首字母 + **identity_id 的 md5 前 4 位**。同一角色不同身份 → 不同 tag | `dc:src/novelvideo/utils/identity_resolver.py:L165-L190` | 中：本质是把身份变成一个稳定 token，交给下游模型的 "Identity Locking"。**依赖下游模型认这个 tag，不是 IP-Adapter 级硬约束** |
| **② 参考图锁** | 每身份独立 `reference_images[]`；`face_prompt` 身份级（幼年/老年面部差异大时），fallback 到角色级 | `models.py:L988-L998` | 中高：本质是 per-identity 参考图集 = 手工版 IP-Adapter |
| **③ 颜色锁（本仓最巧的一招）** | 每个 identity 在每集分配一个**唯一 hex 标记色**（HSV 色相最小间隔 60°），**分配后不可变** | `dc:src/novelvideo/generators/episode_optimizer.py:L58-L118` | 高：**机器可验证** |
| **④ 检出锁** | 草图生成后跑 AI 检测 / 像素检测，读回"这一格里实际有谁"，写进 `detected_identities` | `dc:src/novelvideo/api/routes/generation.py:L6128-L6144`；`dc:src/novelvideo/generators/sketch_color_detector.py:L27-L60` | 高：**闭环** |

**③ 的"不可变"注释值得逐字引用**（`episode_optimizer.py:L64-L68`）：

> "Existing assignments are immutable: script edits may add or remove identities, but already assigned colors must not drift **because old sketches use those marker colors as part of their content contract**."

**④ 的完整闭环**（这是 owner 关心的"怎么知道没跑偏"的答案）：

```
① assign-colors    → 每 identity/全局道具分配唯一 hex（不可变）
② 草图生成         → stick-figure 风格，人物用**色块身体**表达，颜色即身份
③ detect-identities → AI 视觉 或 HSV 像素检测（threshold 0.008）
                     返回 { expected[], detected[], missing[], extra[] }
④ 下游过滤         → render 前必须有检测态，否则拒绝（error_code =
                     RENDER_IDENTITY_DETECTION_REQUIRED）
```

第 ④ 步的强制门在 `dc:src/novelvideo/generators/render_identity_guard.py:L26-L54`：任何 beat 没有显式身份检测态（含 `__NO_CHARACTER__` 哨兵）就**不允许 render**，报错信息还会告诉用户去哪个 UI 点哪个按钮。

**颜色分配变更的连锁处理**（`generation.py:L6099-L6115`）：如果重新分配后 marker 色集合变了，`clean_sketches()` 全清重来——因为旧草图的内容契约已经失效。**这是正确但粗暴的失效传播，owner 抄的时候要意识到代价。**

### 4.4 角色/场景/道具的完整管理面

| 对象 | 规划 | 参考图 | 变体 | 检测 |
|---|---|---|---|---|
| 角色 | `identity_planner`（Pass A 找默认身份 / Pass B 找非默认身份，`dc:agents/identity_planner.py:L1-L12`） | portrait + per-identity image | per-episode 变体 | `consistency_verifier` 分 8 维打分 |
| 场景 | `scene_planner` / `scenes` CRUD | master / reverse / 360 / spatial_layout / 3GS × 5 | `variant_id` + `time_of_day` | `scene_anchor_drift` failure mode |
| 道具 | `prop_planner`，生成**道具三视图**（`dc:docs/zh/concepts/features.md:L17`） | `prop_ref` | `owner_identity_id` + `marker_color` | `detected_props` + `NO_PROP_MARKER` |

一致性校验的维度定义（`dc:src/novelvideo/verification/models.py:L41-L66`）：
`face, hair, skin_tone, gender, clothing_style, clothing_color, accessories, body_type`，每维 0-10 分，
`face_score = mean(face, hair, skin_tone)`，`clothing_score = mean(clothing_style, clothing_color, accessories)`，
**`passed = face_score ≥ 7.0 AND clothing_score ≥ 7.0 AND 无 critical`**。

### 4.5 身份一致性的真实天花板（必须说清）

**它不是 IP-Adapter 级别的。** 证据：
- 锁①是**把一个 token 塞进 prompt**，指望下游图像模型认出来（`character_tag` 注释自称 "用于 Nano Banana Pro Identity Locking"）；
- 锁②是**per-identity 参考图**（手工管理，不是训练出来的 embedding）；
- 锁③④只保证"**该出现的人出现了、不该出现的没出现**"——是**在场检测**，不是**同一性检测**。颜色检测读的是 HSV 色相（`sketch_color_detector.py:L67-L90`），它测的是色块，不是脸。

换句话说：**DramaClaw 把"身份"做成了一个贯穿全链路的、可寻址的、可机器检出的 ID，但最后一跳的像素级同一性仍然外包给了生图模型。** 这跟 owner 现有认知一致——仓内 `AI视频生产流水线方案.md` 已经写明角色一致性依赖外部模型能力。

---

## 5. 三种剧本模式 + review-and-repair 循环

### 5.1 三种模式的官方表述与实际状态

`dc:docs/zh/concepts/features.md:L14`：

> "把小说生成结构化剧本，自动分集、分场，按统一剧本格式（集数-场景、人物、画面描述、台词、音效/特效/系统音）组织。支持**改编 / 直译 / 分镜稿**多种模式，带审校与修复循环。"

README 英文侧对应 "adaptive / literal / staged script modes with review-and-repair loops"（`readme:L191`）。

| 模式 | 中文 | 推测语义 | 代码实证 |
|---|---|---|---|
| adaptive | 改编 | LLM 重写叙事以适配短剧节奏 | — |
| literal | 直译 | **一行原文 = 一个 beat，保留原行文本，LLM 只补 beat 元数据** | ✅ `dc:src/novelvideo/workflows/literal_script_writing.py` |
| staged | 分镜稿 | 先出分镜再合成 | — |

**重要的口径警告（不要引用错）**：虽然 `workflows/literal_script_writing.py` 在源码树里，但**当前后端没有把它接成主线路由**。agent skill 文档三处明写：

- `dc:.hermes/skills/dramaclaw/references/pipeline-details.md:L155-L172`："当前后端没有 `/literal-script/generate`……**不要要求 `script_mode == "literal_source"`；当前后端不保证该字段**"
- `dc:.hermes/skills/dramaclaw/playbooks/episode.md:L45` 重复同一条
- `dc:.hermes/skills/dramaclaw/references/api-reference.md:L57` 同样标注

而且 `dc:src/novelvideo/workflows/script_writing.py:L1-L26` 显示 **2.0 当前默认走"逐行剧本模式"，旧的 screenplay-first 复杂链路已退出默认主路径**，`ScriptWritingWorkflow` 现在只是 `LiteralScriptWritingWorkflow` 的向后兼容薄壳。

**结论**：三种模式是**产品口径上的**，不是当前 CE 主线路径上的三个可切换开关。owner 若要引用，应当说"DramaClaw 宣传三模式，CE 代码里只有 literal/逐行 一条实装，另两条未见独立路由"。

### 5.2 review-and-repair 循环：真正在跑的是三层

**第一层：分集规划评审（LLM + 规则双轨）**

`dc:src/novelvideo/agents/episode_reviewer.py`：
- 问题类型枚举（L24-L49）：`chapter_gap` / `chapter_overlap` / `chapter_out_of_range`（critical）+ `invalid_character`（warning）+ 5 个 LLM 评估类（叙事断裂/节奏/人物弧线/弱悬念/差标题）；
- **格式类问题已前置到 Pydantic 校验层**（L27-L33 注释）：`missing_title` → `Field(min_length=2)`、`missing_summary` → `min_length=10`、`missing_cliffhanger` → `min_length=5`。**能规则化的绝不交给 LLM。**
- 评分维度与权重（L119-L125）：叙事连贯 30% / 节奏 25% / 人物弧线 20% / 悬念 15% / 格式 10%
- **通过判据**（L86-L97）：`score >= 8.0 AND 无 critical issue`
- 规则检查器保留为兜底（L225-L279）：章节连续性 0.35 / 章节覆盖 0.25 / 角色名有效性 0.20 / 结构 0.20

修复侧是 `dc:agents/episode_fixer.py`（694 行）。

**第二层：剧本逐行韧性（retry → 降级 → 留痕）**

`dc:src/novelvideo/workflows/literal_script_writing.py:L807-L862`：

```
模型结构化输出
  ↓ UnexpectedModelBehavior 且判定为 retry 耗尽
重试 1 次（L824-829）
  ↓ 仍失败
本地兜底 Beat（L864-874：只做 speaker/speech 拆分 + 标记 degraded，不编造剧情）
  ↓
整体标记 last_review_passed = False，summary 列出 degraded 行号（L783-789）
```

注意兜底函数的 docstring：**"Build a minimal usable beat without inventing story information."** 且被内容审核拒的行会用占位 `"[上一行因内容审核未提供]"` 进历史窗口（`L777-780`），**不复用被拒内容**。

**第三层：视觉门禁 + 收敛日志（这层最重要）**

`dc:src/novelvideo/verification/` 是一个完整的小型 eval 系统：

| 组件 | 内容 |
|---|---|
| `failure_registry.py` | **10 个种子 failure mode**，分 `generator` / `correction` / `director` 三层，每条带 `detection`(英文提问) + `prevention_rule` + `correction_template` + `negative_prompt_clause` + `gate_enabled`。**实测 4 条 gate_enabled=1**（dialogue_text_overlay / panel_index_text_overlay / style_drift_to_rendered / generic_image_text）；另 6 条 gate_enabled=0（含 `cross_beat_blocking_drift` / `scene_anchor_drift` / `shot_scale_angle_mismatch` 三条 director 层） |
| DB 分层 | 定义在**用户共享** `verification.db`（唯一真源 + 决定 `registry_version`）；命中在**项目私有** `data.db`。注释明确：legacy fallback 的行**不参与** hash，否则"两个项目 legacy 状态不同 → 同一 run 算出不同 registry_version → 训练数据静默中毒"（`failure_registry.py:L4-L16`；`version_hash.py:L3-L11`） |
| `sketch_visual_gate.py` | 逐格问 VLM 是否命中任一 gate_enabled 模式；**`unsure` 判 pass** |
| `convergence_log.py` | `convergence_rounds(episode, phase, round_num, residual_count, fixed_count, new_failures_json)` —— 每轮修复的**残量曲线** |
| `training_db.py` | 5 张表：`sketch_format_versions` / `accepted_sketch_samples` / `live_edit_traces` / `reject_buffer` / `human_override_events` |
| `version_hash.py` | 三个强制版本字段，**都不许手填**：`registry_version`（failure 定义 hash）/ `prompt_version`（**实际发给模型的 prompt 字节** sha256[:12]，不是代码模板）/ `sketch_format_version` |
| `replay_capture.py` | 4 段握手：`begin_trace_for_beat` → `record_prompt_and_response` → `record_gate` → `finalize`。**best-effort：training DB 拔掉，草图照生成** |
| `cli/run_gate.py` | CLI 输出 JSON 汇总 + 写审计文件 + 记一轮 convergence；**有失败时 exit code 3** |
| `cli/emit_human_override.py` | 人工 accept/veto 写 `human_override_events`，docstring：*"This is the capture point that turns tacit human judgments into first-class training data — without this, nobody can tell the difference between 'gate passed and human accepted' vs. 'gate passed and human silently overrode'."* |

### 5.3 对 owner「70 分」的启发

**① 最值得抄的是 `failure_registry` 的数据结构，不是它的内容。**
每条 failure mode = `{code, layer, detection, prevention_rule, correction_template, negative_prompt_clause, gate_enabled}`。这个七元组把"我们知道会犯什么错"变成**可版本化、可 hash、可注入 prompt 的资产**。`registry_version` 一变，所有历史 trace 就自动分代。owner 的 v3 夹具库（`overnight/数据/golden/`）目前是缺陷**样本**，DramaClaw 是缺陷**规则 + 样本 + 门 + 轮次曲线**四件套。

**② "gate_enabled" 开关是承认"知道自己还不可靠"的工程表达。**
10 条模式只开 4 条门。开了 3 条 director 层的（`cross_beat_blocking_drift` / `scene_anchor_drift` / `shot_scale_angle_mismatch`）恰好是**跨镜头**类问题——说明团队认为 VLM 在这类判断上**现在还不可信**。

**③ ⚠️ 最重要的一条：DramaClaw 的门禁哲学与 owner 相反。**

`dc:src/novelvideo/verification/sketch_visual_gate.py:L9-L11`：

> "`unsure` is treated as pass: the gate is intentionally conservative while its real-world error rate is still unknown — **better to let a suspect cell through than to drop a good one onto the floor**."

这与 owner 09-08 21:53 立的不对称代价原则（「宁可误杀，不可漏网」，误杀率上限 25%、漏网率目标 0，`INTENT.md` §2.1）**方向完全相反**。

这不必然是谁对谁错——**前提不同**：
- owner 的场景是**餐饮营销**：变形食物 = 主动品牌伤害，代价不对称，所以宁可误杀；
- DramaClaw 的场景是**小说改编**：漏一个坏 beat = 重新生成一次，误杀一个 = 白花一次生成 + 阻塞整集队列。所以宁可放过。

**owner 的结论应该是**：这不是"谁更先进"的分歧，而是**门禁参数必须按缺陷组的代价不对称性分别设定**——这正是 owner `AI视频生产流水线方案.md` §2.3「阈值/样本量登记表」表 2-1 已经做的事。DramaClaw 用一个全局 `gate_enabled` 布尔位表达，粒度更粗。

**④ 70 分目标本身，DramaClaw 没有给出任何可对标的数字。** README 通篇没有量化产出指标（`readme` 全文无分数/阈值/良率数字）。仓内 `AI视频生产流水线方案.md:L686` 已经记过这一条，本次复核**结论不变**。

---

## 6. 对 owner「工业化确定性生产」的借鉴清单

按"可直接抄 / 需改造 / 仅供理解"三档排，每条都带 DramaClaw 的落点行号。

### A. 可直接抄（低成本、高确定性、与 owner 现有栈无冲突）

| # | 借鉴项 | DramaClaw 落点 | 为什么适合 owner |
|---|---|---|---|
| A1 | **`registry_version` / `prompt_version` / `spec_version` 三版本强制随行** | `verification/version_hash.py:L1-L76` | `prompt_version` = **实际发给模型的字节** hash，不是代码模板 hash——这一条就能堵住"改了 prompt 模板但数据集没分代"的静默污染。owner 的 `deliverables_v2` 台账体系可直接挂上去 |
| A2 | **`convergence_rounds` 残量曲线** | `verification/convergence_log.py:L29-L61` | `(episode, phase, round_num, residual_count, fixed_count, new_failures)` —— **修复循环的收敛性是可测的**。owner 现在只记拦截率/误杀率，没有"第 N 轮还剩几个缺陷"这条曲线 |
| A3 | **门禁 CLI 输出 JSON + 非零 exit code** | `verification/cli/run_gate.py:L154-L167`（有 failed → exit 3） | 让门禁能被外部编排器/agent 调用，而不是只能在 UI 里点 |
| A4 | **`gate_enabled` 开关 + 分层 failure mode** | `verification/failure_registry.py`（10 条 / 3 层 / 4 开） | owner 的夹具库目前只有"缺陷样本"，补上 `detection / prevention_rule / correction_template / negative_prompt_clause` 四列就变成可注入资产 |
| A5 | **人工否决是一等数据** | `verification/cli/emit_human_override.py:L1-L14` | owner 的 `CONFIRMATION.md`（A 组 13 + B 组 4）是 Markdown 台账；DramaClaw 把它落成 append-only 审计表 + 回写到主行的汇总位。**owner 的 A/B 确认可以直接升级成这个结构** |
| A6 | **`unsure` 显式建模为第三态** | `sketch_visual_gate.py:L41-L48`（`hits` / `unsure` / `error` 三列分开） | owner 的 E10 判据 `J1∨J3@0.7`（`INTENT.md` §2.1）在 0.3–0.7 的灰区目前怎么处理？DramaClaw 把灰区单独记一笔，是很便宜的做法 |
| A7 | **导入的失败原子性：成功标记符最后写** | `structured_ingest.py:L9-L12, L150` | 一行注释的工程量，省掉一整类"半导入项目"的脏状态 |
| A8 | **未知枚举 fail-safe 默认** | `task_backend/registry.py:L63-L72` | "未知 task type 一律判为需检查"——可直接搬进 owner 的 vpipe 契约校验器 |
| A9 | **可复用分析运行的内容寻址** | `structured_ingest.py:L113-L130`（`source_sha256 + schema_version + pipeline_version + spine_template` 四元组命中即复用） | owner 的"缓存键统一为内容寻址唯一规范"（`AI视频生产流水线方案.md` 修订⑨）在这一行有现成实现 |

### B. 需改造（架构值得抄，实现要重写）

| # | 借鉴项 | DramaClaw 落点 | 改造点 |
|---|---|---|---|
| B1 | **canonical slot 制** | `freezone/slots.py`（21 个判别联合 + GLOBAL/SCENE/BEAT 三层） | owner 的 VDL_v2 意图段可以加一层同构的 slot 定义，让"每个字段唯一合法写入口"成为可校验事实 |
| B2 | **身份 = ID + 唯一标记色 + 参考图集 + 在场检测** | `episode_optimizer.py` + `sketch_color_detector.py` + `render_identity_guard.py` | 四道锁里 ①②要换成更强的方案（IP-Adapter/参考图权重），③④可以近乎照搬——**颜色唯一性 + 渲染前强制检测态**在 2D 生成链路上是通用的 |
| B3 | **技能契约 = 能力位 + 输入白名单 + 输出类型 + 幂等键** | `freezone/skill_registry.py:L15-L152` | owner 若要做"可被 agent 编排的模块"，这套 pydantic 契约是现成模板。`canonical_slot_kinds` 三重白名单尤其值得抄 |
| B4 | **`graph_patch` + `requires_apply`（agent 提议，人批准）** | `skill_registry.py:L104-L126`（`CanvasGraphPatchOperation` L104 / `CanvasGraphPatch` L122）；`readme:L225, L382` | owner 的"上升人类"节点可以做成同一形状：**agent 只能提议、不能应用**。注意 DramaClaw 这条仍在 In Development |
| B5 | **`spatial_contract` JSON 四件套** | `scene_spatial_contract.py:L189-L289` | 坐标契约 + 语义锚点 + 负向锁 + 显式 gap。**不含 3DGS**，纯文本拓扑。owner 可以先用 2D 的 master/reverse 双图版本 |
| B6 | **agent skill 文档里的"反幻觉禁令"** | `delivery-boundaries.md`（整篇）+ `pipeline-details.md` 的 4 处"不要调用 X" | owner 若用 LLM 当编排器，这套"接口真相写进 skill + 反复禁止猜测 + 不许伪造链接"是现成的防御文案 |

### C. 仅供理解（不宜照抄）

| # | 项 | 理由 |
|---|---|---|
| C1 | 3DGS / PlayCanvas / voxel 全链路 | 需 GPU+CUDA（`readme:L272`）+ Node.js（`block_world_builder.py:L16-L27`）；owner 的 2×V100S-32GB / SM70 / 仅 fp16 跑不动 |
| C2 | 无限画布本身 | owner 的两条线都是"确定性生产"，画布的人机协同成本与"无人干预"目标冲突。**抄它的契约层（B1/B3/B4），不抄它的交互层** |
| C3 | Cognee 知识图谱旧路径 | 新项目已明确不用（`readme:L189`；`structured_ingest.py:L1-L7`），且 owner 自己已有 Video_Ontology 资产 |
| C4 | 依赖 bundled gateway | `dramaclaw-gateway` 是 **AGPL-3.0** 的 New API fork（本次 `gh api repos/dramaclaw/dramaclaw-gateway/license` 实测 = AGPL-3.0），与 CE 的 ELv2 不同。owner 自己的网关链路（MiniMax Design / StepFun / Vidu）不要引入它 |

---

## 7. 不能照搬的部分 + 自研空间

### 7.1 商业定位：Elastic-2.0 禁止 hosted SaaS —— 对 owner 是否可行？

**先复述 DramaClaw 的规则（`readme:L50-L55, L459`；`dc:docs/en/license.md:L12-L27`）**：

- **可以做**：本地/自托管跑、改源码、在其上做产品、给客户交片、集成进自己产品、**部署到客户自己的服务器收部署维护费**；
- **唯一限制**：**不得把 DramaClaw 本身作为托管/管理服务提供给第三方**；
- 附加要求：保留版权声明 + UI 角落一行 "Powered by DramaClaw"；
- 官方明确：这是 **source available，不是 OSI 开源**（`docs/en/license.md:L8-L10`，且专门标注了 "never call it open source" 的用词禁令）。

**判断标准（issue #475 原文，`gh api repos/dramaclaw/dramaclaw/issues/475`，2026-09-04 创建，open）**：

> "**The test is where DramaClaw runs, not whether you have sign-ups or payments.** If the software is installed on the user's own machine and you only handle accounts, top-ups, and updates, or you run your own model gateway that proxies external model APIs and charges for compute, that is standalone commercial use, not SaaS."

不开 SaaS 授权的理由只有一条：**"we cannot guarantee, on someone else's behalf, that your work will not be taken hostage"**——即怕自己的平台变成当初他们反对的那种平台。

**对 owner 的可行性判断：**

| owner 的可能模式 | 合规？ | 判断 |
|---|---|---|
| 自己机器/自己 GPU 机上跑 DramaClaw，为自家短剧/营销线生产内容 | ✅ | 完全合规。这也是 DramaClaw 的主推用法 |
| 改源码做成自有产品，卖给**客户在客户自己机器上部署** | ✅ | 合规（需保留 "Powered by DramaClaw" + 版权声明） |
| 把它接到 owner 现有的模型网关上，按算力/生成量收费 | ✅ | 合规——原文明确点名这种是 standalone commercial use |
| **owner 部署一套，多个外部客户通过网页访问** | ❌ | **直接违反 ELv2 核心限制** |
| **owner 想做「营销类短视频订阅服务」并托管运营** | ⚠️ **高风险** | 这取决于**订阅服务交付的是什么**。如果交付的是**成片**（服务），DramaClaw 不在服务里，ELv2 管不着；如果订阅服务里包含**让客户登录并使用 DramaClaw 本体**，那就是 SaaS，被禁止 |

**结论与三条判断依据：**

1. **owner 的既有定位（INTENT.md §1：一人软件公司 / 未来承载营销短视频订阅服务）在"卖成片"这一层不受限。** 真正受限的是"把 DramaClaw 当平台卖"。owner 若走"卖成片 + 不暴露工具本体"，ELv2 不是障碍。
2. **但 DramaClaw 自己未必愿意。** #475 说"SaaS licensing is not open, **for now**……Not never, just not yet"，并留了 `business@dramaclaw.ai` 商务口子。owner 若真需要 SaaS 形态，得**单独谈商业授权**，成本不可控。
3. **即使拿到授权，还有一层是 owner 拿不到的：DRAMACLAW 官方说 CE 覆盖"完整的个人创作能力"，多租户/团队协作/计费配额/规模化执行属于企业版 EE，不在本仓**（`dc:docs/zh/concepts/features.md:L34-L36`）。**owner 要做订阅服务，必须自己补齐多租户、认证、计费、配额、分布式执行——而 CE 的 TaskBackend 是进程内 inline**（`architecture.md:L63-L65`），架构上就是单机单用户。这意味着：**owner 真正要自研的不是流水线，是 EE 那层**。

**自研空间就在这里**：多租户 / 认证 / 计费 / 配额 / 分布式 task backend。DramaClaw 用 Ports & Adapters 把这层预留好了（`architecture.md:L43-L61` 的 9 个端口表：Auth / ProjectRegistry / ProjectAccess / TaskBackend / CancellationStore / UsageMeter / Lifecycle / AuditSink / CreditQuote），CE 默认全部是单机/no-op 实现。**owner 如果要商业化，替换的正是这 9 个端口的默认实现。**

### 7.2 其他不能照搬的部分

| # | 不能照搬 | 依据 |
|---|---|---|
| 7.2.1 | **`unsure → pass` 的门禁默认** | `sketch_visual_gate.py:L9-L11` vs owner 的不对称代价原则。**这是方向性冲突，不是参数调优** |
| 7.2.2 | **颜色分配变更 → 全清草图** | `generation.py:L6107-L6115`。正确但粗暴。在 owner 的成本模型（按次计费的 API）下，"重跑一整集草图"的代价可能不可接受，需要做增量失效 |
| 7.2.3 | **身份 = prompt token 的锁①** | `identity_resolver.py:L165-L190`。它把一致性的成败外包给了下游模型对 `[TRY_a1b2]` 这种 tag 的识别能力，**不是硬约束**。owner 若要 IP-Adapter 级，必须自研 |
| 7.2.4 | **把整套内容塞进单个 FastAPI 进程** | CE 的 in-process inline task backend 在 owner 的场景下会撞 V100S 串行资源的天花板。owner 需要的是"时间片互斥 + 双卡分工"，DramaClaw 帮不上 |
| 7.2.5 | **`image-to-3gs` 依赖的模型** | `canvasNodes.ts:L641` 注释"模型当前未对接，前端写死为 'marble-1.1'"——**这条路径本身还没有真模型** |

### 7.3 owner 面前的真实空白（DramaClaw 没有任何答案的地方）

1. **70 分的量化口径**。全仓无任何产出分数/阈值/良率数字。owner 的 judge 基准（E10 = J1∨J3@0.7）+ 120 片段人评回归，**仍然只有 owner 一家在算**。这是 owner 的护城河，不是 DramaClaw 的。
2. **物理/时序类缺陷的自动检出**。DramaClaw 的 10 条 failure mode 全是**视觉表面类**（文字溢出、风格漂移、颜色重复、构图重复），**没有一条是穿模、因果倒置、时序方向、精细计数**——而这恰好是仓内 `AI视频生产流水线方案.md:L353` 记录的 D 类"目前只能人检"。**这块完全空白。**
3. **成本模型**。DramaClaw 只在 `shared/provider_costs.py` 有零散记录，公开文档无成本模型。owner 的晋升制成本模型无参考物。
4. **V100 / SM70 / fp16-only 约束下的可行性**。整个 DramaClaw 是 CUDA-agnostic 的云推理假设（"Nothing runs models on your machine"，`readme:L267`），与 owner 的自有算力路线**正交**。

---

## 8. 对 owner 的行动建议（3 条）

### 建议 1：把 `_probe/dramaclaw-readme.md` 升级为「源码级架构基线」，并冻结三条数字

本次实测纠正/新增了三条仓内可复用的硬数字，建议写进 `AI视频生产流水线方案.md` 的事实登记表：

| 数字 | 值 | 出处 |
|---|---|---|
| 画布节点类型 | **18**（README 声称已复核为真） | `frontend/src/features/canvas/domain/canvasNodes.ts:L10-L29`，脚本计数 |
| 画布技能 | **8**（6 主线 + 1 agent + 1 workflow） | `src/novelvideo/freezone/skill_registry.py:L222-L600` |
| 门禁 failure mode | **10 条 / 3 层 / 仅 4 条 gate_enabled=1** | `src/novelvideo/verification/failure_registry.py` |
| canonical asset slot | **21**（GLOBAL / SCENE 11 / BEAT_SCOPED 6） | `src/novelvideo/freezone/slots.py:L186-L212` |
| task_type | **30**；agent 工具 **33** | `frontend/src/lib/task-types.ts`；`.hermes/plugins/dramaclaw/__init__.py:L1691+` |

同时补三条**口径纠正**进 §附录（避免后续 agent 引用出错）：
1. 6,559★ 是 2026-09-28 快照，**当前实测 6,758★**（基线 commit `9822d6f`，2026-10-08）。
2. **hypit 没有 router skill**；「router + 按需技能」是 **HyperFrames** 的架构。本次两仓都做了核查。
3. DramaClaw 的「三模式」中，**只有 literal/逐行 一条在 CE 主线实装**，另两条无独立路由，且 `script_mode` 字段后端不保证。

### 建议 2：立刻做一件小事——给 v3 的每条 gate verdict 行补三个强制版本字段

这是本报告里**投入产出比最高的一条**。把 owner 现有的夹具门禁产物，按 DramaClaw 的 `version_hash.py` 三字段规范补上：

```python
registry_version  = sha256(canonicalized_golden_defs)[:12]     # 缺陷规则定义集 hash
prompt_version    = sha256(actual_prompt_bytes_sent)[:12]      # 实际发送字节，不是模板
spec_version      = "指向 VDL/judge 规格快照表的稳定常量"
```

理由（`dc:src/novelvideo/verification/version_hash.py:L3-L11` 的原话值得抄进 SPECS）：*"the version fields ... None of them may be hand-entered"*。DramaClaw 花了一整个 `failure_registry.py` 的 DB 分层设计，就为了避免"两个项目 legacy 状态不同 → 同一 run 算出不同 registry_version → **训练数据静默中毒**"。owner 的 `deliverables_v2/fixtures/` + overnight `golden/` 正处在这个危险区——**现在补是零成本，等数据集攒到几千条再补就要重跑全部**。

配套可一并抄的：`convergence_rounds` 残量曲线表（5 个字段），让"修复循环是否收敛"变成 owner 自己的数字。

### 建议 3：把 Director World 当作「契约层」而非「实现层」引进，且排在身份一致性之后

具体做法：从 `scene_spatial_contract.py:L189-L289` 抽出那份 JSON schema，**去掉全部 3DGS/全景依赖**，只保留坐标契约 + 语义锚点 + 负向锁 + `coverage_gaps`，作为 owner VDL 场景段的候选扩展字段。它是纯拓扑、无坐标、可由 VLM 产出、可静态校验——**而且完全不依赖 GPU**。

但**优先级排在身份一致性之后**，理由有三：
1. Director World 的完整实现需要 GPU+CUDA+Node.js，owner 的 2×V100S-32GB（SM70/仅 fp16）跑不动 3DGS 重建；
2. 它现在**没进 release**（README 自己在 In Development 里标注了相关能力）；
3. 短剧被拉离 70 分的**首要**缺陷是人物跨镜变脸，不是空间穿帮——owner 现有的角色一致性投入应该先见底。

**另外提醒一条方向性风险**（见 §5.3）：DramaClaw 的门禁哲学是"宁可放过、不可误杀"，owner 的是"宁可误杀、不可漏网"。**这不是谁更先进，是缺陷组代价不对称性的差异**。抄它任何门禁参数之前，先确认它那条缺陷在自己的业务里代价是否真的对称。

---

## 附录：本次未验证 / 明确未知

| 项 | 状态 |
|---|---|
| DramaClaw 官方样片是否达「70 分可用」 | **未观看**（`readme:L100-L137` 只有链接）。本次复核结论与仓内 `AI视频生产流水线方案.md:L686` 一致：**无法判断** |
| `pipeline.png` 四段图的实际视觉内容 | **未判读**（图片）。四段命名以 `docs/zh/concepts/architecture.md:L17` + 代码 task_type 交叉得出 |
| 「17 节点 32 边一提示词生成」的演示 | **未运行**。README 明确标注该项在 In Development、未进 release（`readme:L378-L385`） |
| Director World 的 3DGS 重建质量 | **未实测**。代码显示依赖可选 `world` extra（GPU+CUDA），本次无 GPU 环境 |
| adaptive / staged 两种剧本模式的实际实现 | **仓内未见独立路由**。中文口径只见于 `docs/zh/concepts/features.md:L14` 与 `readme/README_zh.md`（`gh api search/code` 搜「分镜稿」「直译」只命中这两处文档） |
| Cognee 知识图谱旧路径的实际行为 | **未追查**。已确认新项目不走（`readme:L189`；`structured_ingest.py:L1-L7`），故未深入 |
| 所有 DramaClaw 代码的运行行为 | **一行未跑**。git clone 被网络策略拒绝（github.com:443 连接失败），全部源码经 `gh api contents` 逐文件读取。本报告所有结论均为**静态源码分析**，未经运行时验证 |
