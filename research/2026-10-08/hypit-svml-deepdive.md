# hypit / SVML / HyperFrames 深度拆解（面向 owner「工业化确定性生产」）

> 编制：工业化视频流水线调研员 · 2026-10-08

## 0. 取证口径

| 项 | 内容 |
|---|---|
| 仓内材料 | `_probe/hypit-readme.md`(305行)、`_probe/hyperframes-readme.md`(363行)、`_probe/ranking-football.svml`(329行)、`_probe/hypit-license.txt`，均逐行读过 |
| 线上复核 | 只读拉取 hypit-ai/hypit 与 heygen-com/hyperframes 的 docs/examples/packages 源码（raw.githubusercontent.com）。`_probe/ranking-football.svml` 与上游 `examples/ranking-football/reference.svml` **逐字节相同**（`diff` 无输出） |
| **未做的事** | ① **一行 hypit/hyperframes 代码未跑**：`which hypit hyperframes` 仅返回 `npx`，CLI 未安装，且无凭据；② **成本未实证**：官方未公布 $1.15 的拆解，`hypit pricing` 需凭据，本次未运行；③ 仓库 `git clone` 与 tarball 下载反复超时（14.4MB 只拿到 4.36MB，续传无效），全部走逐文件 raw 拉取；④ 官方样片未观看。 |

---

## 1. 项目定位与承诺

hypit 不是渲染器，是**给 Coding Agent 的一套「视频源格式 + 依赖图」**：Claude Code/Codex 读一份 SVML，编译成图，调用若干模型 Endpoint，最后用 HyperFrames 出片（`hypit-readme.md:L51,L149`）。三条承诺：① 丢一个视频进去，agent 克隆出完整 workflow；② **锚定在词而非秒**；③ 生成模型可选，可纯代码渲染（`L51,L53`）。

关键约束：**不是 Apache 2.0**。`_probe/hypit-license.txt:L7,L10,L15` 明确——多租户 SaaS、商业再分发、去 LOGO 都要商业授权；产出物归用户（`L22`）。HyperFrames 才是干净的 Apache 2.0（`hyperframes-readme.md:L285`）。

## 2. 核心架构：SVML 源格式 + HyperFrames 渲染 + 模块导入

SVML 是 **XML 的三段式**：`<script>`（纯台词，无时间码/无样式/无参数）→ 组件（模型请求、空间、轨道、字幕）→ `render:Video`。以仓内足球样例为例，24 条 import（L4–L27）后依次是 Script（L32–39）、图片生成（L68,L135–150）、视频生成（L164–175）、Normalize→WhisperX 对齐（L221–228）、Timeline（L230–233）、TierBoard（L252–270）、B-roll track（L274–307）、Caption（L312–315）、Film 叠轨（L317–326）、Render（L327）。

**词锚定的机制**是可验证的三段：`pipeline:Normalize` 把每条 take 归一到同一 30fps 时钟域 → `whisperx:SemanticTake` 把音频词级时间**对齐回 Script 的某一个 Segment** → `time:Timeline` 顺序装配。此后字幕/B-roll/贴纸只引用 `{story.selection.xxx}`、`{story.moment.xxx}`、`during={story.segment.x}`，**组件自己不做找帧**（上游 `docs/quickstart/timing.md:L1-L16`；样例 L266–306 直接把语义选择绑到窗口）。

模块化是**逻辑地址 + npm 实现**双层：`@your-studio/scoreboard@1` 里 `@1` 是作者接口版本，实现由锁定的 npm 版本决定（上游 `docs/guide/packages.md`「Installation and Source imports」）。协议层 `packages/protocol/src/module.ts` 定义 `hypit.module@1`：types + capabilities + producers，每个 producer 是**带类型的端口声明**（inputs/outputs/needs），模块闭包可解析。所以「组件」不是插件约定，是有 manifest 的依赖图节点。

## 3. 成本结构与「model 可选」实证

**$1.07–1.15 无官方拆解，只能验到「构成」而非「金额」。** 三个数字全部出自 README 卡片（`hypit-readme.md:L95,$1.15 / L117,$1.07 / L139,$1.09`），无逐项账单。而官方 Skill 明确写着 **「Hypit itself calculates no total」**（`skills/hypit/references/production/builds.md:L121`），`hypit pricing <run>` 只是把各 Provider 的价格文档与请求计数并排展示（L105–L114）。

按 SVML 静态清点的付费请求（本次实测计数，`_probe/ranking-football.svml`）：

| 请求 | 次数 | 规格 |
|---|---|---|
| `gpt:Image` | 9 | 1×9:16 2K 主播 + 8 张 2K B-roll（L68,L135–150） |
| `seedance:ReferenceVideo` | 2 | 各 10s / 720p / 9:16，带音频（L164–175） |
| `fish:VoiceDesign` | 1 | 一次音色设计，两条 take 复用（L70–73） |
| `whisperx:SemanticTake` | 2 | 对齐 |
| `asset:Image/Audio` | 11+3 | **本地供给，零调用费**（L74–88） |

结论：**成本几乎全在 2 条视频 + 9 张 2K 图**，字幕/排行榜/B-roll 动效/混音/渲染是纯本地。真实占比无法给出——HypiHub/Seedance/GPT Image 单价在凭据侧，本次未取到。可复现的是「请求清单」这一层，不是金额。

「model 可选」是**真的，有铁证**：上游 `examples/semantic-composition/chat.svml`（26 行全文）只 import `timeline-author / spatial / fonts-open / @example/chat-scene / film / render-hyperframes`，**零生成模型**，却能出一条 8s 成片。仓内 `_probe/ranking-football.svml` 的排行榜、字幕、动效同样是纯 HTML/CSS 组件。

## 4. 模块化与「换角色不换结构」

用上游四个变体做了 diff 实证：

| 变体 | diff 行数 | Film 叠轨块 md5 | 组件条目 |
|---|---|---|---|
| reference | — | `77d1ae36…` | 11 TierItem + 8 broll |
| swap-host（换主播） | +49 / −80 | **完全相同** | 11 + 8 不变 |
| swap-topic（换题材） | +203 / −193 | 仅 `football-tiers`→`tech-tiers` | 9 TierItem + 13 broll |
| swap-effect（换效果） | — | 仅换 `football-column` | TierBoard→Column |

即：**换角色只改 prompt/音色/icon 资产，Film、Timeline、Caption、轨道结构一行不动**（`md5sum` 实测）。这正是短剧模板化最值钱的部分——结构是**声明式依赖图**，`@import` 换的是节点实现，不是改时间轴。

HyperFrames 侧的对应物是 catalog：`docs/catalog/` 下 **171 个 blocks + 223 个 components**（本次对 GitHub tree 计数），`npx hyperframes add <name>` 直接装（`_probe/hyperframes-readme.md:L268–276`）。

## 5. 「克隆爆款」的工艺流程拆解

**真正的 AI 决策只有两步**（都在上游 `skills/hypit/references/creation/reference-video.md`）：
1. **读片→语义账本**：整片看 + `hypit transcribe --language zh/en` 词级时间 + `media tiles/frames --every-frame` 抽帧比对（L68–L107），产出 `ANALYSIS.md`（整体解释）与 `TIMELINE.md`（按源时间定位的系统与行为，L176–L198）。
2. **写 SVML**：把「哪个视觉系统挂在哪些词上」翻译成 Selection/Moment + 组件树；台词与 B-roll prompt 是模型写作。

**其余全是程序化**（无模型参与，可重跑）：Normalize → WhisperX 对齐 → Timeline 装配 → 轨道投影 → HyperFrames 逐帧渲染 → ffmpeg 混音编码。而且有**费用闸门**：`check`（只编译不调用）→ `measure`（本地估算时长）→ `plan`（本地，不需账单账号）→ `pricing`（只读网络）→ 人授权 → `build`（`builds.md:L96–L114`）。改字幕/改 MG 可复用旧媒体，「换 footage 才需重新测量」（`examples/interview/README.md`「Add head-following Caption」）。

## 6. 对「工业化确定性生产」的借鉴清单

1. **词→帧的单一收敛口**：语义锚点只投影一次为帧域，之后全链路复用同一 Timeline——这正是我们要消灭的「多套时间轴互相漂移」。
2. **先 measure 再定长**：`hypit measure --language zh` 按汉字计音节估时长（`script-and-time.md:L184–L205`），把「拍多少秒」从剪辑决策变成生成参数。
3. **费用闸门四段式**：check/plan/pricing/授权分离，本地步骤不碰网络。
4. **组件 = 带类型端口的 producer**，不是一个渲染函数；换内容换实现不换接口。
5. **纯代码图层与生成图层解耦**：图层里排行榜/字幕/字幕条零成本，占成本大头的是 A-roll。

## 7. 不能照搬的部分 + 自研空间

- **授权红线**：`_probe/hypit-license.txt:L7,L10,L15`——多租户、商业再分发、必须保留 LOGO 三条限制。如果 vpipe 要对外做平台化服务，hypit 只能「自用后端」形态。**HyperFrames（Apache 2.0）可以整体照搬，hypit 不能。**
- **示例档位不适合中文短剧**：足球样例 9 张 2K 图 + 2 条 10s 720p，密度是欧美 UGC；中文竖屏短剧通常角色固定、多机位、少 B-roll，成本结构会反过来（音频/对齐占比上升）。
- **A-roll 仍是黑盒**：Seedance/GPT Image 的角色一致性靠 reference 图 + kit prompt 拼（`ranking-football.svml:L167,L174`），跨集一致性没有工程保证——这是自研可切的口子（自建角色 LoRA/参考图资产库 + 一致性回归）。
- **自研空间**：① 直接采用 HyperFrames 作渲染层（Apache 2.0、逐帧 seek、确定性），不必背 hypit 授权；② 只借鉴 SVML 的**词锚定语义层**（Script → Selection/Moment → 帧域），用自研 schema 实现；③ 移植成本最低的先行军是「无模型的图层」（字幕/贴纸/排行榜/片头），它们已经证明零成本可跑通全链。

---

## 附录：本次未验证 / 明确未知

| 项 | 状态 |
|---|---|
| $1.15 / $1.07 / $1.09 的模型级金额拆解 | **不存在于官方材料**。仅验到请求清单与规格；`hypit pricing` 未运行（CLI 未安装、无凭据） |
| 「64 个 headless Chromium 进程」 | **未验证**。示例 `hypit.runtime.json` 实为 `hyperframes.local workers: 2`；并发由 `packages/provider-hyperframes-local/src/concurrency.ts:L9-L14` 的 `min(cpu-2, floor(mem/2/1.5GB))` 与在线吞吐自适应决定，64 是特定大机器的产物 |
| 官方样片质量 | **未观看**（只有外链） |
| hypit/hyperframes 运行时行为 | **一行未跑**，全部为静态文档/源码分析 |
| 中文短剧下的对齐质量（WhisperX `language="zh"`） | 文档明确支持（`timing.md:L60-L62`；`script.md:L168` 汉字切字级词元），但**未实测** |

## 对 owner 的行动建议

1. **渲染层直接评估 HyperFrames（Apache 2.0），不碰 hypit 本体**——授权三条限制会卡死平台化；HyperFrames 的 `data-*` + 逐帧 seek + `--docker` 固化（`docs/concepts/determinism.mdx`）已满足「确定性生产」定义。
2. **把「词锚定」当作自有 schema 的第一性约束**：Script（纯台词）+ Selection/Moment（语义范围/时刻）+ 单一 Timeline 帧域，这三件套与渲染层解耦，可脱离 hypit 单独实现，中文侧官方已支持汉字字级切分。
3. **先立零成本图层再谈 A-roll**：字幕/排行榜/贴纸/片头全部是纯 HTML 组件，可在没有模型凭据的情况下跑通整条流水线并做回归；付费大头（A-roll 一致性）留作独立课题。