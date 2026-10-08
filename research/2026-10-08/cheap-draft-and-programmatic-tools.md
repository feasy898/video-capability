---
title: 廉价草稿层与程序化视频工具链调研
date: 2026-10-08
author: 工业化视频流水线调研员（ToonFlow / HyperFrames 之外的程序化生成工具链专题）
scope: 只读调研 + WebFetch/gh 只读拉取；**未调用任何模型 API，未下载任何权重，未在本机跑任何视频模型**
owner 硬件前提（引自仓内）：2×Tesla V100S-32GB，SM70（Volta），仅 fp16，无 bf16 / fp8 / flash-attn2 — `INTENT.md:13`、`PM-LEDGER.md:78`
---

# 0. 本次实际做了什么 / 没做什么（先划清证据边界）

**做了**：
- 读仓内 `_probe/toonflow-readme.md`（502 行，完整读完）、`_probe/dramaclaw-readme.md`、`_probe/hyperframes-readme.md`、`_probe/hypit-readme.md` 与 `_probe/hypit-license.txt`、`INTENT.md`、`AI视频生产流水线方案.md` 相关行、`deliverables/reports/FINAL_REPORT.md` 实测数据行。
- 读 `tmp_readme/` 下 mcp-for-blender、mcp-aftereffects、touchdesigner-mcp-server、ComfyUI-GGUF、AnimateDiff-Evolved、moviepy 的 readme 快照（npm/PyPI 元数据自带 readme 全文）。
- 用 `gh api` 只读拉取一手仓库文件：ToonFlow（8 个节点包 + 3D 导演台 readme + MCP README + skills SKILL.md）、LTX-Video、LTX-2、Wan2.2、CogVideo、HunyuanVideo、HunyuanVideo-1.5、MimicMotion、EchoMimicV3、Mochi(THUDM→genmoai)、davinci-resolve-mcp、remotion LICENSE.md、PyTorch `torch/cuda/__init__.py`、Blender `source/creator/creator_args.cc`、Dao-AILab/flash-attention、SamLowe/… 等（命令逐条列在正文引用处）。

**没做（必须声明）**：
- **没有跑过一次视频模型**。本文所有"能跑/跑不动"的判断分两类标注：**[官方一手]**=模型作者 README 原文写明；**[推断]**=由 SM70/bf16 约束 + 作者参数表推导，**必须在 P0 spike 上实测**。
- 没有安装/运行 Blender。本机 `which blender` 无输出（已跑，见 §5 脚注），因此 §5 的成本数字是**纸面推导**，不是实测墙钟。
- WebFetch 在本次会话中对 github.com / docs.blender.org / blackmagicdesign.com 大面积超时或 403；凡因此未取到一手源的，文中直接写"未取到"，不用二手转述冒充一手。
- TouchDesigner 定价、Remotion 5.0 许可变更细节、EchoMimicV3 在 32GB V100S（非 16GB）上的实测：**均未取到一手**，标注为未确证。

---

## 1. ToonFlow 架构与可用借鉴点

### 1.1 它到底是什么（README + 仓库结构核实）

`_probe/toonflow-readme.md:165-175` 的能力表只有六行：本地部署 / 无限画布 / MCP / 插件市场 / 开放 Agent / 自由接入模型。README 通篇**没有列出任何具体节点类型名**——"3D 导演台"只出现在截图说明里（`_probe/toonflow-readme.md:192` `3D 导演台与镜头预演`）。所以下面的节点清单是我从**仓库源码目录**核出来的，不是 README 说的：

```
$ gh api repos/HBAI-Ltd/Toonflow-app/contents/packages/nodes --jq '.[].name'
audioGenerationNode  audioNode  director3dNode  imageGenerationNode
imageNode  textNode  videoGenerationNode  videoNode
```

**内置节点只有 8 类**（4 个媒体生成 + 4 个载体：text/image/video/audio）。对比 DramaClaw README `_probe/dramaclaw-readme.md:165` 自称"**18 node types on one canvas**… upload, image generation / edit, storyboard, script, beat context, video, video compose, video story, audio, style, skill, group, text annotation, 360° panorama viewer, 3D world, export"。**ToonFlow 的画布节点面比 DramaClaw 薄一半**，它的编排能力不在节点里，在 **Skill（Markdown 提示词包）+ Agent** 里。

packages 结构（`gh api .../contents/packages`）暴露了它的分层：
`assets / ext / extScaffold / ffmpeg / file / i18n / mcp / modelIcons / nodeScaffold / nodes / providers / skills / startup / teamScaffold / teams / toolScaffold / tools`

即 **四个脚手架**：`nodeScaffold`（节点）、`extScaffold`（文档扩展/画布扩展）、`toolScaffold`、`teamScaffold`——这是"全自由度插件系统"（`_probe/toonflow-readme.md:403-406`）的落地形态。

### 1.2 编排机制：Skill 即工作流，节点只是被调度的算子

`packages/skills/` 只有两个：`canvas` 和 `workflow`。读它们的 SKILL.md（`gh api .../contents/packages/skills/workflow/SKILL.md`）可以确认 ToonFlow 的编排真相：

- **canvas SKILL.md v2.1.0** 定义了 5 个只读工具 + 若干写工具：`getCanvas` / `findCanvasNodes` / `getCanvasNodes` / `getCanvasEdges` / `getNodeTools` / `nodeTools` / `fitCanvas` / `arrangeCanvas`。它对 agent 有非常硬的上下文纪律：「每次响应最多 64 KiB，不提供全图快照」「`limit` 默认 30、最多 100」「节点筛选和连线查询每次最多扫描 2000 项」「不要累计全部详情」。**这是一份为大画布写的分页协议**。
- **workflow SKILL.md v2.7.0** 是导演知识库，并且**把 Seedance 焊死了**：入口表里写「**无论用户是否提到"Seedance""提示词"或具体模型，都立即进入本文件内嵌的「SEEDANCE EPISODE DIRECTOR · PART A」执行**」，还有一整节「Seedance 路由锁存（最高优先级入口规则）」和「Seedance 阶段硬隔离（强制）」，明令执行期内**不得读取其他 references、不得二次规则**。

> **判断**：ToonFlow 的"编排"= 一堆高强度、互相锁死的 Markdown 规约。它对**单模型、单流程**（剧本→Seedance 提示词→出片）的收敛质量很高，但它是**不可移植的**：SKILL.md 里写死了 `Seedance 2.0 还是 2.5` 的提问话术、写死了 A0–A12 编号、写死了"以本文件内嵌 PART A 为准"的优先级。owner 若要把模型换成 Wan/LTX/可灵，这套文件要重写，不是配置能解决的。

### 1.3 3D 导演台：可直接抄的数据结构（本次最硬的收获）

`gh api repos/HBAI-Ltd/Toonflow-app/contents/packages/nodes/director3dNode/readme.md` 是**纯中文技术文档**，细节密度远超 README。要点（原文摘录）：

- 「人形角色使用**内置低多边形关节人偶**，布景与道具可使用基础几何体」——不依赖任何外部角色资产。
- 「人偶身高约 1.8，原点在脚底，+Y 向上、+Z 朝前…**内部保留 16 个关节**」，可用关节名穷举：`hips, spine, neck, head, leftShoulder, leftElbow, leftWrist, rightShoulder, rightElbow, rightWrist, leftHip, leftKnee, leftAnkle, rightHip, rightKnee, rightAnkle`。
- 层级：「hips → spine → neck → head；spine 下有左右肩 → 肘 → 腕，hips 下有左右髋 → 膝 → 踝」。
- **姿态数据结构极简**：`{"threeJsonId":"person1","name":"人物","objType":"mannequin","geometry":{},"position":{...},"material":{...},"pose":{"rightElbow":{"x":-1.2,"y":0,"z":0}}}`——pose 是**相对父关节的 XYZ 欧拉角，单位弧度**。
- **动画轨道**：`{"objectId":"person1","joint":"rightElbow","frames":[{"time":0,"rotation":{...}},{"time":1,"rotation":{...}}]}`，「帧只填写 rotation，**保留固定骨长**」。
- 「省略 joint 的轨道控制整体移动、旋转或缩放」——**根轨道与关节轨道可并存**。
- 支持 `hiddenParts: ["leftShoulder","rightKnee"]` 做**遮挡裁剪**（「Shoulder 是整臂，Elbow 是前臂含手，Wrist 仅手」）。
- 导出：「关键帧可导出为 PNG 图片节点，选中的动画可导出为 MP4 视频节点」——**导演台的产物直接落回画布成为媒体节点**。
- AI 局部编辑有硬上限：「每次生成最多调用模型 40 次，模型与工具调用超过 10 分钟会取消」，且「工具循环与草稿均在节点侧，服务端只代理单次模型请求，不维护导演台会话」。

> **可借鉴点 ①（高价值）**：这个 `objType:"mannequin"` + 16 关节 + `joint`/`frames`/`rotation` 的 schema，是**把 3D 预演接进生成流水线最省事的接口**。它和 MimicMotion 需要的 DWPose 骨架、Blender armature 是同一类中间表示——一份 `joint + 三轴弧度 + 时间戳` 的数据，三端都能吃。owner 的 VDL 槽位 schema 可以直接加一个 `blocking` 字段用这套结构。

### 1.4 MCP 与插件市场

`packages/mcp/README.md`（一手）：
- 「官方 MCP TypeScript SDK v2 的 Streamable HTTP 会话传输，兼容 2025 年版客户端协议」，已验证 `2025-03-26 / 2025-06-18 / 2025-11-25` 三个协议版本，「**未启用 2026 年版无会话 HTTP 协议**」。
- 默认地址 `http://127.0.0.1:10588/mcp`，仅监听回环；stdio 入口通过 `data/mcpRuntime{port}.json`（`{pid,url,token}`，权限 0600）连接正在运行的实例。
- 端口占用会**向后顺延**（10588 → 3002…），多开实例各占一个。
- **安全边界要抄这句**：「MCP 凭证只保护 MCP 入口。现有 Web 页面及其接口本身就是管理端，**不属于全站认证方案**」——与 `_probe/toonflow-readme.md:334`「固定端口 3000，业务页面与 API **没有独立登录鉴权**」一致。

`packages/nodeScaffold/readme.md` 的节点运行时契约值得抄：`defineOptions({ handles })` 声明端口数组（id/type/dataType/label），「UMD 组件直接暴露该数组，供画布在创建节点前过滤可连接的节点列表」——**端口类型是运行时可发现的，不需要 agent 猜 socket 顺序**。

> **可借鉴点 ②**：owner 若自研画布/编排层，直接采纳「端口声明用 `defineOptions`/manifest 暴露，编排只读不改」+「大画布分页协议（64KiB 响应上限 + 游标 + path 投影）」这两条。这正是 DramaClaw「Xia Director 在画布上建图」最难的那部分。

### 1.5 ToonFlow vs DramaClaw vs owner 已有底座：差异表

| 维度 | ToonFlow | DramaClaw | owner 现状（引仓内） |
|---|---|---|---|
| 定位 | AI 短剧/漫剧创作平台，**以 Seedance 为导演内核** | 双轨：XiaHua 画布 + XiaJi 流水线 + Xia Director agent | vpipe spec 驱动的 QC 流水线；DramaClaw/ToonFlow 都只是"参考对象"（`INTENT.md:44`） |
| 画布节点 | **8 类**（源码核实） | **18 类**（README 自称） | 无自研画布 |
| 3D 能力 | **3D 导演台 + 16 关节人偶 + 关键帧导出为图/视频节点** | Director World（3DGS 布景）+ scene-360 + Previz stage（`In Development`，分支 `feat/previz-canvas-node`） | 仅在方案里写了「Blender 程序化骨架经 mcp-for-blender」（`AI视频生产流水线方案.md:297`） |
| 编排机制 | **Skill(Markdown) + Agent**，规则锁死 Seedance | 每阶段独立异步任务 + 断点续跑（README:187） | Prefect 编排 + 内容寻址缓存键（`AI视频生产流水线方案.md:482`） |
| 对外接口 | 本机 MCP（10588），默认关 | 本机 MCP server，loopback-only + 显式信任开关 | 无 |
| 许可证 | **MIT**（`_probe/toonflow-readme.md:478`，v1.0.8 起，含不追溯条款） | **Elastic 2.0**（`_probe/dramaclaw-readme.md:51`：可商用、可卖你做的东西，**唯一禁令是"不得作为托管 SaaS 提供给他人"**） | — |
| 部署形态 | Bun 1.3.14 + Vue3 + Electrobun 桌面端 / Docker | Python 3.11-3.12 + uv + pnpm，Docker 三服务 | anolis-gpu-01（Linux） |

**owner 真正用得上的三点**：
1. **3D 导演台的 `mannequin` JSON schema**（§1.3）——这是唯一可以直接搬进 VDL 的东西，16 关节 + Euler 弧度 + `hiddenParts` 遮挡，正好补上"生成模型动作生硬"的前置：让**动作先在确定性层被指定**，再交给 MimicMotion/Wan-Animate 渲染。ToonFlow 自己给的量级是"一条方案 = 若干关键帧 + 一段运镜"，30s 内完全够。
2. **Skill 分层 + 大画布分页协议**（§1.2）——owner 的 agent 现在没有"操作画布"的语言，这是 DramaClaw 也没做完（`In Development`）的空白。
3. **不借鉴的**：Seedance 路由锁存那一整套。它是"把一个模型做透"的产物，与 owner 的"模型中立 + 本地草稿 + 闭源精修"双轨路线直接冲突。

**架构事实补充**：`gh api repos/HBAI-Ltd/Toonflow-app` → stars 16710、license MIT、language Vue、created 2026-01-29、pushed 2026-10-05。README 信里自述 130 天/20 版本/800+ commits/213,765 行代码。

---

## 2. 程序化视频工具链全景（Blender/AE/Remotion/TouchDesigner）

### 2.0 一句话定位

这些工具**不生成内容**，它们做三件事：**(a) 确定性排版与合成**（字幕/花字/图形/图表，可内容寻址、可回归）→ **(b) 姿态与相机的可执行预演**（3D 骨架→驱动序列）→ **(c) 素材归一化**（分辨率/帧率/色彩空间/去抖）。它们是**廉价草稿层的"程序化中段"**，但**不能替代生成模型**——owner 的 CRADLE 已经在做 (a)，`AI视频生产流水线方案.md:99` 的架构图里 F 节点写的就是「【程序】HyperFrames/Remotion 渲染 / 同输入像素级同输出」。

### 2.1 Blender（脚本化，唯一可无头、唯一开源可自动化）

**CLI 契约（一手源码核实，不用文档推测）**：
```
$ gh api repos/blender/blender/contents/source/creator/creator_args.cc   # grep 后：
3400:  BLI_args_add(ba, "-f", "--render-frame",   CB(arg_handle_render_frame), C);
3401:  BLI_args_add(ba, "-a", "--render-anim",    CB(arg_handle_render_animation), C);
3403:  BLI_args_add(ba, "-s", "--frame-start",    CB(arg_handle_frame_start_set), C);
3404:  BLI_args_add(ba, "-e", "--frame-end",      CB(arg_handle_frame_end_set), C);
3413:  BLI_args_add(ba, "-o", "--render-output",  CB(arg_handle_output_set), C);
3414:  BLI_args_add(ba, "-E", "--engine",         CB(arg_handle_engine_set), C);
3183:  BLI_args_add(ba, "-b", "--background",     CB(arg_handle_background_mode_set), nullptr);
3106:  BLI_args_add(ba, "-t", "--threads",        CB(arg_handle_threads_set), nullptr);
```
同一文件 875–883 行给出官方示例，且**特意警告参数顺序**：
> `# blender --background test.blend --render-frame 1 --render-output "/tmp"` … `...will not render to '/tmp' because '--render-frame 1' renders before the output path ...`

**这就是无人值守管线要的**：`blender -b scene.blend -a -s <start> -e <end> -o //out/#### -E BLENDER_EEVEE_NEXT`。逐帧文件序列由脚本出图、再由 FFmpeg 编码，是最稳的确定性路径（与 owner 现有 "FFmpeg 子进程 + MoviePy v2" 合成层（`AI视频生产流水线方案.md:135`）天然衔接）。

**MCP 通道（`tmp_readme/ahujasid_mcp-for-blender.md` + PyPI 元数据）**：
- PyPI 包已改名 **`blender-mcp` → `mcp-for-blender`**，`uvx mcp-for-blender` 仍可用；仓内快照版本 **2.1.1**，`requires_python >=3.10`，Blender **3.0+**（`tmp_readme/pypi_mcpforblender.json`）。
- 工具能力（README "Capabilities" 节）：场景/物体信息、增删改形状、材质、**任意 Python 执行**、**导出 GLB/FBX**（`export_scene`）、查 node schema 与 bpy API（防猜 socket 顺序）、Poly Haven（≈2,400 个 CC0 HDRI/贴图/模型）、Sketchfab、Poly Pizza（≈10,600 low-poly，约 **69% CC-BY 需署名**，非 CC0 的会写 `polypizza_attribution` 自定义属性）。
- **三个必须知道的运行约束**：
  1. 容器化时 Linux **必须用 `--network=host` + `-e BLENDER_HOST=localhost`**——因为「`host.docker.internal` 不存在且 addon 只监听 localhost」（README "Run with Docker" 节）。**这条对 anolis-gpu-01 部署是硬约束。**
  2. `BLENDER_MCP_SAFE_MODE=1` 只做脚本静态校验，不执行。
  3. **遥测默认开**（匿名 install ID + 工具名 + 耗时 + 版本），要彻底关掉须设 `DISABLE_TELEMETRY=true`。README 自己写「Content collection is off by default」，但**匿名使用记录是默认开的**——企业合规口径 owner 要自己确认（`AI视频生产流水线方案.md:696` 已列此条，本次在 README 原文核对，**一致**）。
- 硬限制（README "Limitations"）：「`execute_blender_code` 允许在 Blender 里运行任意 Python 代码…**ALWAYS save your work**」「复杂操作需要拆成更小的步骤」。→ **它不适合做无人值守批处理的唯一入口**，适合做人机共驾的预演台。

### 2.2 After Effects（表达式 + MCP，但要正版、要 GUI、要 Windows/macOS）

`tmp_readme/npm__kumoproductions%2Fmcp-aftereffects.json`（一手 npm 元数据 + readme）：
- 版本 0.2.0，**首发 2026-08-09，末次 2026-08-12**（三个月内 5 个版本，**项目非常新**）。MIT。
- 硬需求：**Windows / macOS + After Effects 2024–2026 + Node.js ≥24**；AE 侧「无需装插件或面板」，但**必须开** Preferences → Scripting & Expressions → 「Allow Scripts to Write Files and Access Network」。
- 能力：检视工程/合成/图层、改属性、**加改关键帧**、效果与遮罩、文本与形状、**设置表达式**、保存/备份、**单帧渲染预览**。
- 三个安全开关做得很规矩：`AE_MCP_READONLY=1`（只读审计模式，仍可渲染预览帧）、`AE_MCP_ALLOW_CATEGORIES`（按操作类别白名单，如"只允许关键帧操作"）、`AE_MCP_ENABLE_EVAL=1`（**默认关**，开启后可执行任意 ExtendScript，README 警告「可能影响整台计算机」）。
- 支持 `AE_MCP_EXE` 指定非标准安装路径；默认按 2026→2025→2024 顺序探测。

> **对 owner 的判定**：AE 的**表达式引擎**（wiggle / linear() / posterizeTime）是无头渲染的工业标准语言，值得学；但 AE 本身是 **GUI + 闭源 + 正版订阅 + 无 Linux**。anolis-gpu-01 是 Linux，**AE 不进产线**。这个 MCP 的价值在于它是"LLM 驱动 GUI 商业软件"的**参考实现**——那三个分级开关（readonly / 类别白名单 / eval 默认关）就是 owner 任何 agent 调外部软件时都该抄的权限模型。

### 2.3 DaVinci Resolve / Fusion（免费版有坑，Studio 才是正路）

**一手证据（第三方 MCP 项目的实测记录，`samuelgursky/davinci-resolve-mcp`，MIT，3406 stars，last push 2026-10-08）**：
- README "Free edition" 节原文：「Blackmagic gates *external* scripting to Studio: on the free edition `scriptapp("Resolve")` refuses a foreign process, whatever the preference says.」
- 绕过路径与它的时限：「Through Resolve 21.0.x the **Workspace ▸ Scripts menu was not gated**…so the server can reach the free edition through a small script that runs *inside* Resolve…**Resolve 21.1 moved Python scripting to Studio.** On free 21.1 the Scripts menu no longer lists `.py` files at all (reported on Fedora 44 in #203; a Lua script in the same folder lists normally). Whether the Console still runs Python there is unconfirmed, so **treat the bridge as a 21.0.x path until that is measured.**」
- 覆盖面（`docs/reference/api-coverage.md`）：**Methods Live Tested 338/361 = 93.6%**；测试基线 19.1.3 Studio + 20.3.2 + 21.0.2 Studio + **21.0.3 free（经 in-app bridge）**。

> **对 owner 的判定**：Resolve 免费版在 21.1 之后连脚本菜单里的 `.py` 都没了。**这条路对"无人值守产线"是死的**——产线不能依赖一个"某版本靠漏洞、某版本被堵"的通道。要用 Resolve 就买 Studio，且仍需 GPU/桌面 GUI，**不进 anolis-gpu-01 产线**。Fusion 的**节点合成思路**可读，代码不可直接复用。

### 2.4 Remotion / HyperFrames / MoviePy（真正能进产线的三件套）

| | HyperFrames | Remotion | MoviePy v2 |
|---|---|---|---|
| 授权 | **Apache 2.0，无 per-render 费用、无商用门槛**（`_probe/hyperframes-readme.md:283,363-364`） | **Source-available 双层**：个人 / ≤3 员工的营利组织 / 非营利 免费；「**It is not allowed to copy or modify Remotion code for the purpose of selling, renting, licensing, relicensing, or sublicensing your own derivate**」——一手取自 `https://raw.githubusercontent.com/remotion-dev/remotion/main/LICENSE.md`「Free License」节 | **MIT**（`tmp_readme/moviepy.md` 末段） |
| 写法 | 纯 HTML + data 属性 + adapter（GSAP/CSS/Lottie/Three.js/WAAPI） | React 组件 | Python API |
| 构建 | **无 build，`index.html` 直接播** | 需 bundler | — |
| 确定性 | 「same input, same frames, same output. Built for CI, regression tests」 | 「Library-clock animations … need care」 | 「**slower than using ffmpeg directly** due to heavier data import/export」 |
| 渲染 | headless Chrome + FFmpeg（Puppeteer 逐帧 seek） | headless Chrome + FFmpeg | numpy 帧数组 + 编码器 |
| 与 owner 现有栈 | `AI视频生产流水线方案.md:135` 已定为模板线确定性镜头引擎 | 同表列为备选 | `AI视频生产流水线方案.md:135` 已定为**合成层默认**（"FFmpeg 位于确定性梯度顶端"） |

- HyperFrames 生态另有 `frame.md`（设计系统反转为镜头语言）与 `catalog`（转场/叠加/字幕/图表/地图/效果的现成 block），以及 AWS Lambda 分布式渲染（`_probe/hyperframes-readme.md:210,264-266,281-295`）。
- 规模证据：hypit 的案例「concurrently rendered in **64 headless Chromium processes**」（`_probe/hypit-readme.md:95`），单条 20s 广告总成本 **$1.15**（三条同结构克隆，每条的成本口径）。

> **判定**：模板线的确定性镜头与字幕花字，**HyperFrames（Apache 2.0）应当升为首选**，Remotion 降为备选（Remotion 的 ≤3 人免费线 owner 作为一人公司**当前合规**，但一旦产品化对外提供渲染即踩 "no selling derivative" 条款）。MoviePy 留在合成层不动。
> ⚠️ 一处**与仓内不一致的发现**：`_probe/hyperframes-readme.md` 的对比表把 Remotion 的许可写作 "Source-available Remotion License"，而我直接取到的 LICENSE.md 首行写着「In **Remotion 5.0, the license will slightly change**」——**5.0 条款变更细节本次未取到，标注未确证**；npm 元数据显示当前 `latest = 4.0.529`（`tmp_readme/npm_remotion.json` dist-tags）。

### 2.5 TouchDesigner（实时视觉，agent 通道已存在，但定位不对）

一手（`tmp_readme/npm_touchdesigner-mcp-server.json`，MIT，2.1.0，末次发布 **2026-09-19**）：
- 12 个工具，含 `create_td_node` / `delete_td_node` / `exec_node_method` / **`execute_python_script`** / `get_td_node_parameters` / `update_td_node_parameters` / `get_td_node_errors` / `get_top_image`（截 TOP 节点输出为图）。
- 三个 Prompts 直接做成 agent 手册：`Search node`（按 name/family/type 模糊搜节点）、`Node connection`、`Check node errors`——且 readme 特意注明「Missing files, dangling references and shader failures are **warnings**, so no errors does not mean healthy」。
- 版本治理双轴：npm 包版本**不**决定兼容性，`.tox` 组件的 **API 版本**才决定（`expectedApiVersion` / `minApiVersion`，当前 min 1.3.0）；MAJOR 跨代直接执行停止。

> **判定**：TouchDesigner 是**实时演出/装置**工具，不是离线产线工具。owner 若要做"数据驱动的大屏/实时预览"，它是好东西；对"30s 成片无人值守渲染"，它没有可脚本化的无头渲染承诺（本次**未取到 TouchDesigner 无头渲染/CI 用法的一手文档**，定价页在 `AI视频生产流水线方案.md:696` 已记为 404 未取数）。**不进产线**。

---

## 3. 廉价草稿模型能力边界矩阵（LTX/Wan2.2/CogVideoX/Mochi/Hunyuan + V100S 兼容性）

### 3.0 先把 V100S 的硬约束钉死（这次取到了源码级证据）

- **bf16 无原生支持**：`torch/cuda/__init__.py` 的 `is_bf16_supported()`（`https://raw.githubusercontent.com/pytorch/pytorch/main/torch/cuda/__init__.py` 第 244–262 行）：`if torch.cuda.get_device_properties(device).major >= 8: return True`——**major 必须 ≥ 8（Ada/Ampere）**，V100S 是 **major 7**。此后走 `_check_bf16_tensor_supported()` 试建 tensor（**模拟路径，慢且可能直接抛异常**）。同理 `is_tf32_supported()` 直接 `return is_bf16_supported(including_emulation=False)`。
- **flash-attention 不覆盖 Volta**：`Dao-AILab/flash-attention` README 第 145–146 行：「**Ampere, Ada, or Hopper GPUs** (e.g., A100, RTX 3090, RTX 4090, H100). For **Turing** GPUs (T4, RTX 2080), see the separate flash-attention-turing repo」——**Volta 连 Turing 分支都没提**。FA3 更严格：「Requirements: H100 / H800 GPU, CUDA >= 12.3」。
- **已有一手佐证**：CRADLE 全程 fp16、峰值 23.76GB/32GB（`deliverables/reports/FINAL_REPORT.md:38`），D-020 明确「LTX T5 用 FLUX fp16 省 9.5G」（`FINAL_REPORT.md:206`）。

### 3.1 矩阵（★=V100S 可行性判断，官方数字均为一手 README 原文）

| 模型 | 参数/规模 | 分辨率·帧率·帧数（官方） | 官方显存口径（原文） | 官方速度（原文） | 精度要求 | **V100S 判定** | 许可 |
|---|---|---|---|---|---|---|---|
| **LTX-Video 2B**（0.9.8-distilled / 0.9.6） | 2B；同系列 13B | 「resolution divisible by 32, frames divisible by 8+1（如 257）」「works best **under 720×1280 and below 257 frames**」；0.9.6 起默认 **1216×704 @30fps** | 无官方 GB 数；仅「Lower VRAM requirement than ltxv-13b」；LoRA 版「Requires only **1GB of VRAM**」；Q8 社区版「**720×480×121 in under a minute on RTX 4060 (8GB)**」 | distilled「**8 (recommended), or less** steps」「**15× faster**」；dev「40+ steps 质量档」 | 无 bf16 强制；**fp8 档只对 Ada 及以后有效**（README 明写 FP8 kernels "Ada architecture and later"） | ★★★★★ **首选**。2B fp16 是 owner 已跑通的档（`FINAL_REPORT.md:134`：LTX 调试 384×512、steps≤12）。**但 fp8 一律别碰** | 0.9.5 起 **OpenRail-M**（README 引 `ltx-video-2b-v0.9.5.license.txt`） |
| **Wan2.2-TI2V-5B** | 5B dense；Wan2.2-VAE 压缩 **T×H×W = 4×16×16**，加 patchify 总压缩 **4×32×32** | **720P = 1280×704，24 FPS** | 「can run on **at least 24GB VRAM (e.g. RTX 4090)**」；单卡命令需 `--offload_model True --convert_model_dtype --t5_cpu`；≥80GB 可去掉这三项提速 | 「**5-second 720P video in under 9 minutes** on a single consumer-grade GPU」 | `attention()` 默认 `dtype=torch.bfloat16`（`wan/modules/attention.py:141`）——**但有 SDPA 兜底分支**：无 flash-attn 时走 `torch.nn.functional.scaled_dot_product_attention` 并 warn「Padding mask is disabled…significant impact on performance」 | ★★★★☆ **第二档**。24GB 门槛 V100S-32GB 满足；但**必须** `--convert_model_dtype` 降 fp16 + 吃 SDPA 性能损失。`AI视频生产流水线方案.md:129` 记的实测是 **Q8 档 212–214s/33 帧、23.7GB**（仓内一手实测，非本次跑） | **Apache 2.0**（README 明文） |
| **Wan2.2-A14B**（T2V/I2V/S2V/Animate） | **27B 总参 / 14B 激活**（高噪专家管布局、低噪专家管细节，按 SNR 阈值 t_moe 切换） | 480P & 720P | 「can run on a GPU with **at least 80GB VRAM**」 | 未给单卡时间表 | bf16 主路径；多卡 FSDP+Ulysses **用 FA3（Hopper only）** | ★☆☆☆☆ **单卡出局**。双卡 V100S 无 NVLink、不能 TP（`AI视频生产流水线方案.md:44` R6）。**Animate-14B 同此**，且仓库方案已实测「fp16+sdpa+blocks_to_swap 23 ≈7 小时/条，流水线不可用」 | Apache 2.0 |
| **HunyuanVideo**（v1，13B） | 13B | 720p = 720×1280 **129 帧**；540p = 544×960 129 帧 | 「**Minimum**: **60GB** for 720px1280px129f and **45G** for 544px960px129f」；「**Recommended**: …80GB」；FP8 权重「saves about **10GB**」 | 「Latency (Sec) for 1280x720 (129 frames 50 steps) on **8×GPU**」 | — | ★☆☆☆☆ **出局**。60GB 最低门槛 + fp8 是 Ada/Hopper 专属 | **`NOASSERTION`**（`gh api repos/Tencent-Hunyuan/HunyuanVideo`），非标准 OSS 许可 |
| **HunyuanVideo-1.5** | **8.3B**（3D causal VAE 压缩 16×空间 / 4×时间；SSTA 剪枝） | `480p` / `720p`，`--video_length` 默认 **121** 帧 | 「**Minimum GPU Memory: 14 GB (with model offloading enabled)**」 | 480p I2V step-distilled：**8 或 12 步（推荐）**，「On RTX 4090, end-to-end generation time is reduced by **75%**, and a single RTX 4090 can generate videos within **75 seconds**」 | `--dtype` 默认 **`bf16`**（或 `fp32`）；attention 默认 `attn_mode="flash"`（可切 `torch`=SDPA / `sageattn` / `flash2` / `flash3` / `flex-block-attn`） | ★★★☆☆ **值得 spike，但有 bf16 坑**。14GB 门槛不是问题；**问题是默认 bf16 在 SM70 走模拟**。code 里 dtype 常量确实注册了 `'fp16'`（`hyvideo/commons/__init__.py:43`），**但 README 未给 fp32/fp16 一手基准**，且 SSTA 稀疏注意力依赖 flex-block-attn。→ 归 P0/E-spike，**不可先上产线** | 未在 README 找到 License 章节（**未确证**） |
| **CogVideoX1.5-5B** | 5B | 1360×768；**frames = 16N+1, N ≤ 10（默认 81）**；**5 or 10 秒**；**16 fps** | diffusers **BF16 from 10GB**；INT8(torchao) **from 7GB**（多卡 BF16 **24GB**） | **Single A100: ~1000s（5 秒视频）；Single H100: ~550s** | **BF16 (Recommended)**，FP16/FP32/FP8*/INT8 可选，**INT4 不支持** | ★★☆☆☆ **慢到不可用**。官方速度基准就是 A100/H100 量级；V100S 只会更慢。**且 README 明确推荐 BF16，而 SM70 无 bf16** | 代码 Apache 2.0；**5B 模型权重是独立的 "CogVideoX LICENSE"**（非 Apache） |
| **CogVideoX-2B** | 2B | 720×480；frames = **8N+1, N ≤ 6（默认 49）**；**6 秒**；**8 fps** | diffusers **FP16 from 4GB minimum**；INT8 **from 3.6GB**（多卡 FP16 10GB） | **Single A100: ~90s / H100: ~45s** | **FP16 (Recommended)** ← 唯一官方推荐 fp16 的 CogVideoX | ★★★★☆ **老将，唯一"官方推荐 FP16"的模型**。4GB 显存、8fps、720×480——画质老但**能真跑**。适合做"能不能出片"的兜底对照，不适合做主力草稿 | **Apache 2.0**（含 Transformers + VAE 模块） |
| **Mochi 1** | — | demo `num_frames=31` | 「requires **approximately 60GB VRAM** when running on a single GPU」；「While **ComfyUI can optimize Mochi to run on less than 20GB VRAM**, this implementation prioritizes flexibility over memory efficiency」 | 「we recommend using **at least 1 H100**」；LoRA 微调「on **one H100 or A100 80GB**」 | 示例代码 `model_dtype="bf16"` | ★☆☆☆☆ **出局**。官方栈 60GB；ComfyUI 优化版 <20GB 但**本次未取到该优化实现的一手文档**，且 bf16 常量 | **Apache 2.0** |
| **CogVideoX-5B VAE 反例** | — | — | — | — | — | ⚠️ 仓内已记录的反例：「**VAE 强转 FP32 反而 decode 坏，禁一刀切**」（`AI视频生产流水线方案.md:561`）——本次**未取到一手 issue**，沿用仓内结论 |

### 3.2 三个结论

1. **V100S 上真正能当"廉价草稿层"的只有两个半**：`LTX-Video 2B`（★★★★★，且 owner 已跑通）+ `Wan2.2-TI2V-5B`（★★★★☆，fp16+offload 档，仓内已有实测）+ `CogVideoX-2B`（★★★★☆，老但唯一官方推荐 FP16、4GB 起）。**其余全部出局**。
2. **"必须 fp32"的模型：一个都没有**。真正的问题是**反过来的**——官方推荐 bf16 而 SM70 没 bf16（HunyuanVideo-1.5、CogVideoX1.5-5B、Mochi 全中招）。正确应对不是 fp32（慢到不可用），而是 **`--convert_model_dtype` / `--dtype fp16` + 吃 SDPA 兜底**（Wan2.2 的 `attention()` 已经内置了这个分支，是可抄的工程范式）。
3. **本地草稿 ≠ 交付**。owner 的 CRADLE 早给了答案：本地直出 480P/16fps，交付规格 1080×1920/24fps，缺口靠 RIFE 插帧 + Real-ESRGAN 超分补（`AI视频生产流水线方案.md:134`），而这两个环节**至今标注"调研材料无 V100 一手实测，E12 验证"**。**便宜草稿层的价值不在"能出片"，在于"能让 judge 跑起来做择优"**——最终镜头仍走 API 精修。

---

## 4. 程序化动作合成（MimicMotion/EchoMimic）

### 4.1 MimicMotion：姿态驱动的全身动作层

一手（`gh api repos/Tencent/MimicMotion/readme`）：

- **分辨率与长度上限**：「supports generating videos with a **maximum of 72 frames at a 576x1024 resolution**. If you encounter insufficient memory issues, you can appropriately reduce the number of frames.」
- **V100 是官方验证过的卡**：「Recommend python 3+ with torch 2.x are **validated with an Nvidia V100 GPU**.」
- **显存与时间**：「the 72-frame model requires **16GB VRAM (4060ti)** and finishes in **20 minutes on a 4090 GPU**.」「The minimum VRAM requirement for the **16-frame U-Net model is 8GB**; however, **the VAE decoder demands 16GB**. You have the option to run the VAE decoder on CPU.」
- **三个技术点**（作者原话）：①「**confidence-aware pose guidance**」提升时序平滑；②「**regional loss amplification based on pose confidence** significantly eases the distortion of image」——**专治手部/肢体扭曲**；③「**progressive latent fusion**」→ 任意长度、显存可控。
- **依赖链**：DWPose（`yolox_l.onnx` + `dw-ll_ucoco_384.onnx`）+ SVD-xt-1-1（自动下载）。
- 许可：Apache-2.0（`gh api repos/Tencent/MimicMotion/contents/LICENSE`：「MimicMotion is licensed under the Apache License Version 2.0 **except for the third-party components listed below**」——注意有例外清单）。

> **判定**：**这是 owner「中段细化层」最该用的一个**。三个理由：① 官方 V100 验证 + 16GB，V100S-32GB 有 2 倍余量；② 输入是**姿态序列**不是文本 → **动作可以被程序指定**，这正是 ToonFlow 导演台人偶 schema 能直接对接的位置；③ 72 帧 ≈ 2.4s@30fps / 4.5s@16fps，**必须靠 progressive latent fusion 拼长镜**，拼接缝是主要风险。
> ⚠️ 时间预算要注意：**4090 上 72 帧 = 20 分钟**。V100S 无 bf16、SDPA、PCIe 直通，**必然更慢**（仓库方案 `:129` 记 14B 在 V100 上 ≈7 小时/条，可作量级参照）。**草稿层可用，产线主力不可用**——它的定位应该是"**只对需要指定动作的少数镜头跑**"。

### 4.2 EchoMimicV3：音频驱动的半身/特写

一手（`gh api repos/antgroup/echomimic_v3/readme` + arXiv:2507.03905 摘要）：

- **1.3B 参数，Apache 2.0**；底模是 `alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP`（与 owner CRADLE 用的 Wan 血统同源，**权重栈可复用**）。
- **V100 是官方测试卡之一**：「Tested GPUs: **A100(80G) / RTX4090D (24G) / V100(16G)**」——注意是 **V100 16G**，不是 V100S 32G。显存口径从 12G（Gradio）→ 16G（ComfyUI）演进：「**12G VRAM is All YOU NEED**」，另有 Flash 版「**8-step High-quality Generation / No Face Mask required / 12G VRAM / up to 768×768**」（2026.01.22）。
- **采样步数分档**：talking head **5 steps**；talking body **15~25 steps**。Audio CFG 最优 **1.8~2**（调高对口型、调高画质反之）；Text CFG 最优 **3~6**。`partial_video_length` 设 81/65 或更小降显存。
- **长视频**：>138 帧用 Long Video CFG。
- 能力（arXiv 摘要原文）：「a **Soup-of-Tasks** paradigm」（用多任务 mask 输入 + 反直觉的任务分配策略，避免多模型）、**Soup-of-Modals**（Coupled-Decoupled Multi-Modal Cross Attention 注入多模态条件）。**即：一个模型同时做音频驱动 + 图像驱动 + 姿态驱动。**
- 许可：Apache 2.0（README 末节原文）。

> **判定**：**解决"口型"问题，不解决"动作"问题**。它的输入是**音频 + 参考图**，输出动作由音频决定——**你无法指定"手要伸向第三个按钮"**。这正是 `AI视频生产流水线方案.md:297` 已经写下的结论：「姿态驱动层读 motion 字段生成驱动序列；音频驱动**不再**作为全身口型兜底」。

### 4.3 能不能解决 hypit 等生成模型的"动作生硬"？—— 分镜回答

| 症状 | MimicMotion / EchoMimic 能否解决 | 依据 |
|---|---|---|
| 肢体/手部**扭曲畸形** | ✅ **能，且是设计目标** | MimicMotion 的 confidence-aware pose guidance + **regional loss amplification based on pose confidence**「significantly eases the distortion of image」 |
| 时序抖动、运动不连贯 | ✅ **能** | 同上「with confidence-aware pose guidance, **temporal smoothness can be achieved**」 |
| 长镜接缝 | ⚠️ **半能** | progressive latent fusion 让任意长度"acceptable resource consumption"，但接缝质量**本次未取到一手评测** |
| **指定一个精确动作**（拿杯子、按键、转身） | ✅ **能，但只在姿态源正确时** | 姿态驱动 = 你给什么它做什么；风险从"模型幻觉"转移到"姿态序列质量" |
| 全身对白的**口型** | ❌ **不能** | EchoMimicV3 是音频驱动=动作由音频定；全身镜头的口型必须**二次对口型层**（仓内方案 `:131`：可灵 Lipsync API / 本地 LatentSync、Wav2Lip，列 E9） |
| 持物交互（拿起东西） | ❌ **不能**，需第三张牌 | `Wan2.2-Animate-14B` 是候选但单卡 80GB 门槛出局；仓内 T10 spike 未过 |

**Wan2.2-Animate 的补充事实（一手）**：`gh api repos/Wan-Video/Wan2.2/readme` 第 297–299 行：「Wan-Animate takes a **video and a character image** as input, and generates a video in either **"animation"** or "replacement" mode.」——**输入是一段视频**，意味着「Blender 渲染一段人偶动画 → Wan-Animate 迁移到角色图」这条链在架构上成立。**但 14B/80GB 门槛把它挡在 V100S 之外**。预处理链（`wan/modules/animate/preprocess/preprocess_data.py`）需要 `pose2d/vitpose_h_wholebody.onnx` + `det/yolov10m.onnx` +（replacement 模式才用）`sam2/sam2_hiera_large.pt` + 可选 FLUX。

> **总判定**：**MimicMotion 是 owner 现有方案里唯一"官方 V100 验证 + 姿态可编程"的动作层，应该从"数字人线的候选"上调为"中段细化层的默认动作引擎"**。但要清醒：它 72 帧 20 分钟@4090 的速度意味着**只能用于需要指定动作的镜头**（产品演示里的手部特写、UI 操作的手），不能全片铺开。

---

## 5. 对 owner「工业化流水线」的廉价草稿层架构建议

### 5.1 核心判断

**程序化工具链当"廉价草稿层的程序化中段"——能，但只在一个窄定义下能。**

- ✅ **能**：所有**镜头内的确定性部分**。字幕/花字/图形/数据可视化（HyperFrames）、排版与转场（MoviePy/FFmpeg）、镜头时长与节奏、色彩与 LUT、**姿态与相机的可执行预演**（Blender + ToonFlow mannequin schema）、素材归一化。
- ❌ **不能**：任何需要"想象出一个不存在的画面"的像素。Blender 渲不出真实材质的产品特写，HyperFrames 渲不出人物。
- ⚠️ **半能**：**镜头运动的中间层**。用 Blender 把"相机从产品左侧 30° 匀速推到右侧，同时光圈从 f/5.6 虚化到 f/2"渲成一条**运动矢量/深度图**，再喂给 i2v 模型当控制信号（LTX 有 Depth/Pose/Canny IC-LoRA，仓库方案 `:127` 的 VACE「先编辑后运动」也是这个思路）——**这条链本次未在 V100S 上验证，列为 spike**。

### 5.2 建议的分层（把 owner 现有 vpipe 架构往下插一层）

```
意图/槽位(VDL)
   │
   ├─[确定性层 · 零生成成本]─────────────────────────── 可寻址、可回归、可缓存
   │   ├ HyperFrames/HTML   → 字幕·花字·图形·图表·转场（同输入像素级同输出）
   │   ├ MoviePy v2 + FFmpeg → 拼装·混音·烧录·转码（确定性梯度顶端）
   │   └ Blender -b -a -s -e -o → 3D 预演：人偶 blocking / 运镜 / 深度图 / 遮挡 mask
   │        ↑ 输入是 ToonFlow 式 {joint, frames, rotation} JSON（§1.3）
   │
   ├─[廉价草稿层 · 本地 V100S]──────────────────────── 目的是让 judge 有东西可打
   │   ├ LTX-Video 2B distilled（fp16，8 步，1216×704@30fps 或 480×832）
   │   ├ Wan2.2-TI2V-5B（fp16 + offload + t5_cpu，1280×704@24fps）
   │   └ 动作镜：MimicMotion（16GB，V100 官方验证，72 帧）
   │      对白镜：EchoMimicV3（12–16GB，V100 官方测试）+ 口型层（E9 未验）
   │
   ├─[择优门]───────────────────────────────────────
   │   L0 预检 / 黑帧(f16 NaN 已知失败模式) / 硬校验 / judge 相对排序
   │   → 只把 top-k 送下一层，其余丢弃（省钱的核心机制）
   │
   └─[精修层 · 闭源 API]───────────────────────────── 出片
       可灵 / MiniMax H3 / Vidu / 即梦 —— 逐镜 i2v 或 v2v
```

**为什么草稿层必须"廉价 + 有 judge + 会丢弃"**：hypit 的成本参照是 **$1.15/条 20s 广告**（`_probe/hypit-readme.md:95`，含 2 条 Seedance A-roll + 1 张 2K 肖像 + 10 张 1K B-roll + WhisperX 对齐）。如果草稿层不能让 judge **少送 30–50% 的镜头**去精修，它就只是多烧一遍时间。**本地草稿层的 ROI 完全等于「它替精修层挡掉的镜头数 × 精修单价 − 本地墙钟成本」**。

### 5.3 30s 内固定机位/固定动作演示镜头：Blender 脚本化的成本/质量边界

**必须先声明：本节没有任何实测。** `which blender` 在本机无输出（已运行），Blender 未安装，以下是纸面推导。

**能做好的（Blender 的甜区）**：
- 产品展示：模型自带的低多边形几何体 + HDRI 环境光，`export_scene` 出 GLB 或直接渲染，**产品形体 100% 准确**（这是生成模型绝对做不到的——owner 的 v2 就是为了修"食物形变"才立的项，`INTENT.md` 2.1 节）。
- UI 操作演示：**UI 本身是 2D 的**——用 HyperFrames/HTML 做屏幕内容，Blender 只渲相机运动 + 反光，或干脆全程 HTML + CSS 3D。**这一类根本不该上 Blender。**
- 固定机位固定动作：正因为"固定"，**关键帧少、场景可缓存、可以只渲一次然后循环/重定时**——这是最省的路径。

**成本边界（纸面推导，需实测校正）**：
| 项 | 估算 | 依据/不确定度 |
|---|---|---|
| 渲染一帧（EEVEE Next，1080p，Simple 场景） | 秒级 | **未实测**。EEVEE 是光栅化，质量换速度；若用 Cycles CPU，30s×24fps=720 帧会是小时级 |
| 30s@24fps = **720 帧** | 若 2s/帧 → ~24 分钟；Cycles CPU → 数小时 | **纯算术，未实测** |
| 显存 | 接近 0（EEVEE 不吃显存推理） | 与 V100S 生成模型（23.76GB 峰值）**不冲突**，可与卡A 生成并行 |
| 工程成本 | 一次写 `build_scene.py()`，之后**换素材只改参数**——这才是关键 | 与 owner 的 spec+eval 方法论一致（`INTENT.md` 2.3） |

**质量边界（明确说清不行的地方）**：
- ❌ **写实材质**：EEVEE 的 PBR 与产品实拍比有可见差距，除非用 Cycles + 精细 HDRI + 材质贴图，成本立刻上一个数量级。
- ❌ **人物**：低多边形人偶（ToonFlow 的 16 关节那套）**只能做剪影/中景/远景/遮挡物**；近景必须走生成模型。
- ❌ **流体/布料/粒子**：Blender 渲得出，但要调物理，成本不可控。
- ✅ **确定性**：同一 `.blend` + 同一 seed → 同输出，**可进内容寻址缓存、可做像素级回归测试**——这是 CRADLE 门禁体系能直接吃的。

### 5.4 与 owner 现有资产的对齐

- CRADLE 已跑通的合成层（FFmpeg 子进程 + MoviePy v2）就是 §5.2 的确定性层，**不用重做**（`AI视频生产流水线方案.md:135`）。
- 三车道门禁 / 黑帧检查 / 降级链（KenBurns 车道 M2 真渲染过 3 次）就是 §5.2 的择优门（`FINAL_REPORT.md:129` L4）。
- **要新建的只有一件事**：把 ToonFlow 的 `mannequin` JSON 接进 Blender 的 armature 导出。这是自研的活，**没有现成开源件**。

---

## 6. 不能照搬的部分 + 自研空间

### 6.1 明确不能照搬

| 来源 | 不能照搬的理由（依据） |
|---|---|
| ToonFlow **workflow SKILL.md** | 「无论用户是否提到"Seedance"…都立即进入本文件内嵌的 SEEDANCE EPISODE DIRECTOR PART A」+「硬隔离（强制）」+「以本文件内嵌 PART A 为准」。**规则与单一模型焊死**，与 owner 的模型中立双轨路线冲突。§1.2 |
| ToonFlow **Web/Server 无鉴权** | `_probe/toonflow-readme.md:334`：「固定端口 `3000`，业务页面与 API **没有独立登录鉴权**」；MCP README 亦承认「MCP 凭证只保护 MCP 入口」。owner 的产线是公网可达的服务器，这条不能抄。 |
| **AE MCP** 路线 | 需正版 AE + **Windows/macOS** + Node 24 + GUI 常驻；`tmp_readme/npm__kumoproductions%2Fmcp-aftereffects.json` 显示该项目 2026-08-09 首版、2026-08-12 末版，**仅 5 个版本、三个月新**。anolis-gpu-01 是 Linux。 |
| **DaVinci Resolve 免费版** | 「on the free edition `scriptapp("Resolve")` refuses a foreign process」；「**Resolve 21.1 moved Python scripting to Studio**…the Scripts menu no longer lists `.py` files at all」——绕过路径随时会被堵。§2.3 |
| **Remotion 作为对外产品底座** | LICENSE.md：「It is not allowed to copy or modify Remotion code for the purpose of **selling…or sublicensing your own derivate**」。owner 现在一人公司**免费合规**（≤3 员工），一旦把模板线做成订阅产品对外提供渲染，即踩条款。→ **HyperFrames(Apache 2.0) 是同类替代品**（`_probe/hyperframes-readme.md` 自称 "Apache 2.0 license, with no per-render fees or commercial-use thresholds"）。 |
| **TouchDesigner MCP** | 实时视觉工具；README 无无头渲染/CI 承诺；且 `.tox` API 版本跨 MAJOR 直接执行停止（`tmp_readme/npm_touchdesigner-mcp-server.json`）。不进产线。 |
| **MimicMotion 作产线主力** | 72 帧 20 分钟@4090（`gh api repos/Tencent/MimicMotion/readme`）。V100S 只会更慢。只能做**指定动作镜头**的中段。 |
| **任何 bf16 默认的模型**（HunyuanVideo-1.5 / CogVideoX1.5-5B / Mochi） | `torch/cuda/__init__.py:259` `if major >= 8: return True` —— V100S major=7。§3.0 |
| **fp8 / fp8-kernels** | LTX README 明写 FP8 kernels "Ada architecture and later"；HunyuanVideo 的 FP8 权重是 Hopper 生态。 |
| **flash-attention** | README:「Ampere, Ada, or Hopper」——**Volta 不在支持列表**。走 SDPA 分支是唯一解，且要接受「Padding mask is disabled…significant impact on performance」的告警。 |

### 6.2 自研空间（没有现成开源件可抄的地方）

1. **`blocking` 中间表示**。把 ToonFlow 的 `mannequin` JSON（`objType/pose/joint/frames/rotation` + `hiddenParts`）**扩展成 owner 自己的 VDL 字段**，一份数据同时喂：Blender armature（渲预演/深度图）、DWPose（MimicMotion 的输入格式）、judge 的姿态硬校验（owner 已有 J6v2 程序化时序检测，`CONTEXT.md:7`）。**这是全链路唯一的真空白**。
2. **草稿层的成本闸门**。本地草稿只有在"挡掉的精修镜头数 × 精修单价 > 本地墙钟"时才赚钱。这个不等式需要 owner 用自己的真实单价（可灵 ¥0.3–0.6/s、H3 ¥0.5/s、Vidu ¥0.625/s，仓内 `:482`）跑一遍才知道拐点在哪。**没有任何现成工具算这个**。
3. **确定性层的像素级回归**。HyperFrames 自称 deterministic，但 owner 的门禁体系（CRADLE 六道门禁 + 三车道）比它严格得多。**把 owner 的硬校验（分辨率/帧率/时长/黑场/字幕≠台词/切镜数）挂到 HTML 合成产物上**，是一件事就能做、且立刻有价值的活。
4. **降级链的程序化分支**。CRADLE 的 KenBurns 车道在 M5 生产中「**0 fallback / 0 blocked**」（`FINAL_REPORT.md:129` L4）——**降级路径至今没有被真实触发过**。要让它可信，得在草稿层**故意注入失败**（仓库的"程序化负样本注入"思路，`AI视频生产流水线方案.md:380`）来逼它走一遍。
5. **口型层**。E9 至今未验。全身对白镜头目前**没有确定方案**（MimicMotion 不管嘴、EchoMimic 管嘴但不管全身动作）。这是数字人线唯一的未解方程。

### 6.3 本次调研的三个诚实缺口

- **Blender 一分钱没测**：无渲染时间、无 VRAM、无 EEVEE/Cycles 质量对比。§5.3 全部为纸面推导。
- **TouchDesigner 无一手**：无头渲染能力、定价（仓内已记定价页 404）、商业许可条款全部未取到。
- **Remotion 5.0 许可变更**：LICENSE.md 只说 "will slightly change"，PR #3750 内容未取。
- **EchoMimicV3 在 32GB V100S 上的表现**：官方只测到 V100 16G，32GB 是加性利好但无数据。
- **LTX-Video 2B 官方显存数字**：README 里没有 GB 数，本文矩阵里所有 LTX 显存表述都来自 Q8 社区项目或 LoRA 的 1GB，不是 2B 主干的官方口径。

---

## 7. 对 owner 的行动建议（3 条）

**① 先把 Wan2.2-TI2V-5B 拉进 P0 spike，与 LTX 2B 做一次同题 A/B——这是本次调研唯一"能立刻改变产线档位"的发现。**
现有产线用的是替代模型 `PAI/Wan2.1-Fun-1.3B-InP`（`FINAL_REPORT.md:205` D-019，官方 I2V-1.3B 不存在）。而官方现已发布 **Wan2.2-TI2V-5B：720P=1280×704 @24fps、原生 T2V+I2V 同一模型、Apache 2.0、24GB 门槛**——V100S-32GB 满足，命令需 `--offload_model True --convert_model_dtype --t5_cpu`。**同题 A/B 就是把 M2 的 12 个 LTX 卡全部换 Wan2.2-5B 重跑一次**，比对新旧门禁分数分布（`FINAL_REPORT.md:147` 已有"换模后门禁分数分布会变、阈值勿直接沿用"的纪律）。**验收门槛：峰值 <30GB + 黑帧率 0 + 至少 1 条过全部六门禁。** 若通过，产线从 480P/16fps 直接上 720P/24fps，**插帧与超分两个环节（E12）可能整段砍掉**——这是本次调研里最大的单笔收益。

**② 把 MimicMotion 从"数字人候选"正式提名为「中段动作引擎」，并用 ToonFlow 的 `mannequin` JSON 定义 VDL 的 `blocking` 字段——一天内可产出 spec，不必等 GPU。**
MimicMotion 是本次核实到的**唯一同时满足「官方 V100 验证」「16GB 显存」「动作可编程」的模型**（`gh api repos/Tencent/MimicMotion/readme`：72 帧 576×1024、validated with an Nvidia V100、16GB VRAM），其"confidence-aware pose guidance + regional loss amplification"是**为治手部扭曲而设计**的。ToonFlow 的 3D 导演台 readme 已经给出一份现成的 16 关节 Euler 弧度 schema。**建议本周只做 spec 不做训练**：在 VDL v2 里加 `blocking: [{objectId, joint, frames:[{time, rotation}]}]`，用 Blender `export_scene`/armature 导出做一次端到端连通性验证（Blender 的 CLI 契约已从源码核实：`-b -a -s -e -o -E`）。**同时明确记录边界**：MimicMotion 不管口型，全身对白镜头仍需独立口型层（E9），不要让这两件事互相阻塞。

**③ 模板线把确定性引擎从 Remotion 换成 HyperFrames，并把确定性层的硬校验挂上去——这是一天的工作量，且规避一条真实的许可风险。**
owner 现在是一人公司，Remotion 的"≤3 员工免费"**当前合规**；但 owner 的终局目标是"营销类短视频订阅服务"（`INTENT.md` §1），一旦对外提供渲染即触碰 LICENSE.md 的 "not allowed to…sublicensing your own derivate"。HyperFrames 是同一技术路线（headless Chrome + FFmpeg 逐帧）但 **Apache 2.0、无商用门槛**，且自带 catalog 与 `frame.md` 设计系统。**验收：把 CRADLE 的六道硬校验（分辨率/帧率/时长/黑场/字幕≠台词/切镜数）接在 HTML 合成产物后，同输入像素级同输出的回归用例 ≥3 个。** 这一步同时把 owner 的门禁体系从"生成层"延伸到"合成层"，而合成层恰恰是目前唯一 100% 良率、最该被守住的那一段。

---

### 附：本次调用的只读命令清单（可复现）

```
gh api repos/HBAI-Ltd/Toonflow-app                      # stars/license/lang/created/pushed
gh api repos/HBAI-Ltd/Toonflow-app/contents/packages/nodes --jq '.[].name'
gh api repos/HBAI-Ltd/Toonflow-app/contents/packages/{ext,extScaffold,nodeScaffold,mcp,skills,tools,providers} --jq '.[].name'
gh api repos/HBAI-Ltd/Toonflow-app/contents/packages/mcp/README.md --jq .content | base64 -d
gh api repos/HBAI-Ltd/Toonflow-app/contents/packages/nodes/director3dNode/{readme.md,src} --jq ...
gh api repos/HBAI-Ltd/Toonflow-app/contents/packages/skills/{workflow,canvas}/SKILL.md --jq .content | base64 -d
gh api repos/Lightricks/LTX-Video/readme --jq .content | base64 -d
gh api repos/Lightricks/LTX-2/readme --jq .content | base64 -d
gh api repos/Wan-Video/Wan2.2/{readme,contents/wan/modules/attention.py} --jq .content | base64 -d
gh api repos/THUDM/CogVideo/readme --jq .content | base64 -d
gh api repos/Tencent-Hunyuan/HunyuanVideo/readme --jq .content | base64 -d
gh api repos/Tencent-Hunyuan/HunyuanVideo-1.5/{readme,contents/hyvideo/commons/__init__.py,
        contents/hyvideo/models/transformers/modules/attention.py} --jq .content | base64 -d
gh api repos/Tencent/MimicMotion/{readme,contents/LICENSE} --jq .content | base64 -d
gh api repos/antgroup/echomimic_v3/readme --jq .content | base64 -d
gh api repos/genmoai/models/readme --jq .content | base64 -d
gh api repos/samuelgursky/davinci-resolve-mcp/{readme,contents/docs/reference/api-coverage.md} --jq .content | base64 -d
curl -sL https://raw.githubusercontent.com/pytorch/pytorch/main/torch/cuda/__init__.py    # is_bf16_supported
curl -sL https://raw.githubusercontent.com/remotion-dev/remotion/main/LICENSE.md
gh api repos/blender/blender/contents/source/creator/creator_args.cc --jq .content | base64 -d | grep -n '"-[abefsoEt]"'
curl -sL https://arxiv.org/abs/2507.03905                                              # EchoMimicV3 摘要
which blender ffmpeg python3 ; nvidia-smi -L ; ffmpeg -version                          # 本机环境
```