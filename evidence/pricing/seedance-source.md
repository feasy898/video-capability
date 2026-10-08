# Seedance 2.5 核价——已抓取页面原文摘录（≤500 字/处）

抓取日期：2026-10-08。仅收录实际抓到原文的页面。

## 1. Atlas Cloud 模型页（唯一拿到逐字价格的页面）

URL: https://www.atlascloud.ai/models/seedance-2.5 （WebFetch 成功，非登录态）

原文摘录（各端点单价，含 -20% 折扣标注）：

> Draft Complete: "From $0.329/SEC $0.263/SEC -20%"
> Reference-to-Video: "From $0.167/SEC $0.134/SEC -20%"
> Image-to-Video: "From $0.167/SEC $0.134/SEC -20%"
> Text-to-Video: "From $0.167/SEC $0.134/SEC -20%"

对比表：Seedance 2.5 "From $0.134"（Native Audio，最高 4K）；Seedance 2.0 "From $0.112"。
FAQ: "See the Seedance 2.5 model page on Atlas Cloud for current per-generation rates by resolution."
（分 480p/720p/1080p 档位的单价该页未列出。）

性质：第三方中转平台公示价，非官方价。

## 2. 官方渠道尝试记录（均未拿到价格数字）

| 渠道 | URL | 结果 |
|---|---|---|
| 火山方舟模型价格 | https://www.volcengine.com/docs/82379/1544106 → 301 → https://docs.volcengine.com/docs/82379/1544106 | WebFetch 与 web_reader 各抓一次：页面为『模型价格--火山方舟』（更新时间 2026.06.10），正文 JS 渲染，抓到的只有骨架，无价目表 |
| 火山方舟模型列表 | https://www.volcengine.com/docs/82379/1330310 | 抓取成功；视频生成能力清单（快照 2026.05.29）含 doubao-seedance-2-0-260128、2-0-fast、1-5-pro、1-0-pro、1-0-pro-fast，**无 Seedance 2.5 条目** |
| 即梦官网 | https://jimeng.jianying.com/ | 套餐区块仅显示『正在加载套餐』，需登录；页面无 Seedance 字样、无价格 |
| OpenRouter | https://openrouter.ai/bytedance/seedance-2.5 | 页面存在但静态内容无单价 |

## 3. 仅搜索摘要出现、未获原文、不采信的数字（记录备考，禁止引用）

- 火山方舟 Seedance 2.5：480p 30s 约 20.16 元/条、720p 30s 约 45.36 元/条；输入 42 元/M token、输出 70 元/M token
- kie.ai $0.085/秒；RunningHub 720P 约 0.49 元/秒；OpenRouter 约 $0.1028/秒；中转渠道 US$6–12/条
- Seedance 2.0 对照（与白皮书既有记录一致）：含视频输入 28 元/百万 tokens、不含 46 元/百万 tokens

**最终判定：Seedance 2.5 官方单价仍未确证（confidence: unverified）。确证路径 = owner 登录火山方舟控制台人工抄录价目页。**
