# Vidu S2 Avatar 非实时档（offline avatar）官方契约提取

- 提取日期：2026-10-09
- 提取人：vpipe v4 M2 avatar 客户端任务（Vidu avatar 客户端工程师 subagent）
- 文档来源（owner 指定）：https://platform.vidu.cn/vidu-stream/doc
- 提取方法与诚实声明：
  - 按 ask 要求先走 `browser-use/control-browser` skill：其内核（`mcp__node_repl__js`）对本次
    subagent 会话反复报 `Session is not active: sess_dwf-dwfrun-bd3c15fe-b9f6-48a0-871f-d74d61fc036d-actor_1_1`
    （该内核属主工作流会话；小调用可通，凡 `agent.browsers.*` 调用必失败），浏览器渲染路径不可用。
  - 改用等价渲染提取：该站是 Next.js App Router SPA，对页面 URL 带 `RSC: 1` 头请求可取回
    **服务端渲染的原始 flight payload，内嵌整页 markdown 原文**（与浏览器渲染内容同源同文，且保真度更高）。
    页面路由 slug 从 `/_next/static/chunks/app/vidu-stream/doc/layout-6c0c48265dd7c5de.js` 的导航树提取。
  - 已核对三个非实时档子页全部取回（HTTP 200）：
    - https://platform.vidu.cn/vidu-stream/doc/s2-avatar/async/introduction
    - https://platform.vidu.cn/vidu-stream/doc/s2-avatar/async/parameters
    - https://platform.vidu.cn/vidu-stream/doc/s2-avatar/async/quick-start
  - 结论：**官方契约完整提取成功**（端点/DTO/轮询/计费/错误码五项俱全），无需历史口径补丁；
    仅余额端点 `/ent/v2/credits` 不在本文档页内（沿用主控实测 + v3 期实测口径，见 §6）。

## 1. 产品定位（概述页原文）

> | Avatar 非实时版 | 异步生成：一张角色图 + 一段音频（或文本）生成口型与动作对齐的说话视频 | REST 提交任务 → 轮询任务状态（或回调）→ 下载生成物 | `POST /ent/s_avatar/offline` |

> | 费用 | Avatar 实时版 1.5 积分/秒 | 组件版 1 积分/秒 | **非实时版 1 积分/秒** | Editing 版 1 积分/秒 |

> | 输出（非实时版）| MP4 视频文件 | | TTS | 你管理 | | 实时性 | 异步文件 |

## 2. 接入约定（概述页原文）

| 项目 | 约定（原文关键片段） |
|---|---|
| Base URL | 「国内环境 `https://api.vidu.cn`，海外环境 `https://api.vidu.com`。WebSocket 对应使用 `wss://`。`{host}` 为域名，不含协议」 |
| 认证 | 「所有 HTTP 与 WebSocket 接口统一使用 `Authorization: Token vda_xxx`」——**注意是 `Token` 方案，不是 `Bearer`**（本仓两把 key 前缀均为 `vda_`，与之匹配） |
| JSON 字段 | 「请求与响应字段统一 snake_case，例如 `call_mode`、`live_id`、`editing_type`、`reference_image`」 |
| ID 处理 | 「`live_id`、`task_id`、`stream_id` 等 int64 字段**请一律按字符串处理**，避免 JavaScript number 精度丢失」 |
| 素材传入 | 「`image` 与 `audio` 均支持公网 URL、base64（需含 MIME 前缀）和 `ssupload:?id=<素材ID>` 三种形式，任选其一」 |
| 生成物时效 | 「`creations[]` 中的 `url`、`cover_url`、`watermarked_url` 均为 24 小时有效期，需自行转存」 |

## 3. ① 创建任务端点

```
POST https://{host}/ent/s_avatar/offline        # {host} = api.vidu.cn（国内）
Authorization: Token vda_xxx
Content-Type: application/json
```

响应（原文示例）：

```json
{
  "task_id": "123456789",
  "state": "created",
  "model": "vidu-s1",
  "resolution": "540p",
  "created_at": "2026-08-03T03:00:00Z"
}
```

> 原文：「本接口不返回积分消耗；积分的预扣与退还时机见『定价信息』。」
> 原文：「创建成功只代表任务已受理，**不代表视频已生成**。必须用返回的 `task_id` 轮询查询接口，或配置 `callback_url` 等待回调。」

## 4. ② 请求 DTO 全字段（「详细参数」页原文表格）

| 字段 | 类型 | 必填 | 说明（原文摘录/紧缩） |
|---|---|---|---|
| `model` | string | 否 | 默认值 `vidu-s1`。注意查询接口返回 `vidus1`（无连字符），两种写法不同 |
| `image` | string | **是** | 角色图片，三种形式任选：公网 URL / base64（须含 MIME 前缀 `data:image/png;base64,{...}`）/ `ssupload:?id=<素材ID>`。**仅支持 1 张单人图片**；人体或人脸检测不通过会失败（`ImageCheckBodyJointsFailed`/`ImageCheckFaceFailed`/`ImageObjectsUndetected`） |
| `image_recaption` | string | 否 | 图生文结果，≤ 8192 字符；不传时系统基于图片自动生成 |
| `audio` | string | 条件必填 | 语音音频，URL/base64/ssupload。与 `text` **至少传一个**；两者都传时以 `audio` 为准 |
| `text` | string | 条件必填 | 说话文本，UTF-8 ≤ 10000 字符；传 `text` 时系统合成语音。**计费按合成语音时长（约 2-3 个字/秒）** |
| `voice` | string | 否 | 音色，仅 text 模式（未传 `audio`）生效；可选值见官方 voice-list 页。示例 `female-shaonv` |
| `timeline` | string | 否 | 动作时间轴，**序列化后的 JSON 字符串**（不是对象），格式 `{"actions":[{"text":"比个心","time_range":[2,10]}]}`；`actions[].text` 动作描述文本，`actions[].time_range` 必须是 2 个 uint32（开始/结束秒），**建议动作间隔不小于 5 秒**。不传时系统基于音频自动生成 |
| `resolution` | string | 否 | `540p`（默认）/ `720p` |
| `callback_url` | string | 否 | 状态变化回调，HMAC-SHA256 签名（本客户端不使用回调，走轮询） |
| `payload` | string | 否 | 透传参数，原样返回 |
| `watermark` | bool | 否 | **「不传时默认加水印（传 `false` 才不加水印）」**；无水印视频取查询结果的 `url` 字段 |
| `wm_position` | enum | 否 | top_left/top_right/bottom_left/bottom_right，仅 watermark=true 生效，默认 bottom_right；控制的是「内容由 AI 生成」合规标识位置，Vidu 品牌水印固定右下角；**枚举名不合法返回 400** |
| `wm_url` | string | 否 | 自定义水印图片 URL |
| `meta_data` | string | 否 | 透传元数据 JSON 字符串 |

创建请求示例（官方 audio 模式原文）：

```bash
curl -X POST "https://api.vidu.cn/ent/s_avatar/offline" \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Token {your_api_key}' \
  -d '{
    "image": "https://scene.vidu.zone/media-asset/084945-xpk47RWYcBgJ27nJ.png",
    "audio": "https://scene.vidu.zone/media-asset/085244-FrJjNf5tKjiZHQkf.mp3",
    "timeline": "{\"actions\":[{\"text\":\"女主播面带微笑看向镜头,...\",\"time_range\":[0,4]}]}"
  }'
```

## 5. ③ 查询端点与轮询协议

```
GET https://{host}/ent/v2/tasks/{task_id}/creations
Authorization: Token vda_xxx
```

响应关键字段（原文示例 + 字段表）：

| 字段 | 说明 |
|---|---|
| `id` | 任务 ID（按字符串处理） |
| `state` | 枚举：`created`/`queueing`/`processing`（中间态，继续轮询）；`success`（终态，读 `creations[]`）；`failed`（终态，读 `err_code`/`err_msg`） |
| `progress` | **可能为小数；非线性推进，会长时间停在 99，仅终态变 100——原文「不要用它判断任务是否卡死」，超时判断用挂钟时间** |
| `err_code` / `err_msg` | 失败原因；「排障时以 err_msg 为准」 |
| `credits` | **该任务实际消耗积分，数值等于 `duration`（1 秒 1 积分）。实际扣费以本接口为准**（failed 时为 0） |
| `duration` | 生成视频时长（秒），计费依据 |
| `type` | 非实时数字人固定 `offline_avatar` |
| `model` | 实际模型标识，查询返回 `vidus1`（无连字符） |
| `resolution` | 实际输出分辨率 |
| `blocked_resources` | 风控拦截资源列表，正常为空数组 |
| `creations[]` | **仅 `state=success` 后读取**（提前读可能空数组）：`id`、`url`（无水印视频）、`cover_url`、`watermarked_url`；三者均 **24 小时有效**须即时转存 |

轮询协议（原文）：「轮询间隔建议 **3～5 秒**起步并逐步退避，不要低于 2 秒，否则可能触发 `TooManyRequests`」；
「实测出片耗时约 40 秒～2 分钟……建议总超时设为 5 分钟」。

## 6. ④ 计费规则（「定价信息」章节原文）

- 「按视频时长计费，每秒 1 积分（0.03125 元），时长按输入音频实际时长向上取整；传 `text` 时按合成语音的时长计费（约 2-3 个字/秒）。」
- 「余额低于 45 积分（约 1.4 元）就不能发起任务」
- 「积分扣除时机：创建接口只做余额预检，不扣积分；任务进入排队时按预估时长一次性预扣。任务失败或未产出生成物时，未实际消耗的部分会自动退还；最终扣减结果以查询接口返回的 `credits` 为准（`failed` 时为 0）。」
- 概述页能力矩阵：非实时版 1 积分/秒（与上条一致）。
- **余额端点 `/ent/v2/credits` 不在本 S2 文档站内**（属平台未文档化端点）。口径沿用：
  主控实测 2026-10-09 `GET https://api.vidu.cn/ent/v2/credits`（Bearer）→ 200；
  v3 期实测（工程方案v3.1.md §0.2 V6，2026-09-30）：返回 `general_remains[]/exclusive_remains[]`
  数组、元素含 `credit_remain`，当日读数通用 893 + avatar 专属 5000。
  注意历史趣事：v3 期 avatar 任务实扣走的是**通用池**（683→622，专属池 5000 不动，
  out/avatar_demo/g9a_intro_60s__vidu_avatar.gen_meta.json:avatar.pools_delta）；本轮双 key
  是否改走专属池，以本次真实生成的两池差值实测为准（客户端双池都记）。

## 7. ⑤ 错误码（原文全表）

**任务失败 `err_code`**（查询接口返回）：

| 错误码 | 处理建议（原文紧缩） |
|---|---|
| `FieldInvalid` | 检查 `resolution`、`timeline` 等字段取值与格式 |
| `ImageDownloadFailure` | 确认图片地址服务端可访问、未鉴权、未过期 |
| `ImageFormatInvalid` | 改用 PNG/JPG/JPEG/WEBP |
| `ImageSizeInvalid` | 调整图片尺寸后重试 |
| `ImageCheckFaceFailed` | 更换正面清晰、人脸完整的单人图 |
| `ImageCheckBodyJointsFailed` | 更换人体关键部位可见的角色图 |
| `ImageObjectsUndetected` | 更换无遮挡的角色图 |
| `NoFaceDetected` | 更换含清晰人脸的角色图 |
| `MultiFaceDetected` | 仅支持单人图，裁剪为单人后重试 |
| `AuditSubmitIllegal` | 输入没有通过安全审核 |
| `CreationPolicyViolation` | 生成物触发风控 |
| `CreditInsufficient` | 积分不足，充值后重试 |
| `UserCancelled` | 用户手动终止，无需处理 |
| `InternalServiceFailure` | 可短暂重试；持续失败带 task_id 反馈 |

**请求错误 HTTP 响应体 `reason` 字段**（不是任务 err_code）：

| reason | 说明 |
|---|---|
| `BadRequest` | 不合法的请求 |
| `FieldLacking` | 缺少字段（注意 audio/text 至少传一个） |
| `QuotaExceeded` | **超过并发限制** |
| `TooManyRequests` | 请求太频繁（轮询退避） |
| `TaskNotFound` | task_id 没找到或不属于当前 key |
| `Unauthorized` | 未鉴权（检查 `Authorization: Token vda_xxx`） |
| `Forbidden` | 请求没有权限（须用创建任务时的同一 key） |

回调协议（本客户端不用，仅登记）：POST 回调 + HMAC-SHA256 签名（`X-HMAC-SIGNATURE` 等头），
success/failed 回调失败重试最多 4 次（3s/5s/10s）。

## 8. 与历史口径（工程方案v3.1.md §2.4①）比对

| 项 | 历史口径（v3 实测） | 官方文档（本轮提取） | 裁决 |
|---|---|---|---|
| 端点 | `s_avatar/offline`（vidu_avatar_client.py 文档口径） | `POST /ent/s_avatar/offline` | 一致，官方坐实 |
| 查询 | 平台 tasks/creations | `GET /ent/v2/tasks/{task_id}/creations` | 官方坐实 |
| 计价 | 1 积分/s × ceil(音频秒)，失败不扣 | 1 积分/s（0.03125 元），ceil(音频时长)；text 模式 ceil(合成语音时长)；预扣-退还机制 | 一致（官方补充 text 模式计费基准 2-3 字/s 与预扣细则） |
| model | `vidus1`（查询返回实测） | 创建传 `vidu-s1`（可省略），查询返回 `vidus1` | 一致，写法差异官方明示 |
| timeline | `{"actions":[{"text":"比个心","time_range":[5,10]}]}` 序列化串 | 同左；`time_range` 须 2 个 uint32，动作间隔建议 ≥5s | 一致 |
| 分辨率 | 540p=618×836 / 720p=826×1114 竖屏随参考图 | `540p`（默认）/`720p` | 一致（官方未列像素尺寸，像素实测仍以 v3 V7 为准） |
| URL 时效 | 24h 即时落盘 | 24h（url/cover_url/watermarked_url 全部） | 一致 |
| 认证 | （v3 实测 Bearer 亦通余额端点） | **`Authorization: Token vda_xxx`** | 以官方 Token 为准；Bearer 作降级备选 |
| watermark | 历史传 false 无水印 | **不传默认加水印，须显式 false** | 官方口径更精确，客户端默认显式 false |
| 并发 | 未文档化 | `QuotaExceeded`=超过并发限制（ask 给的并发限 5 与此对应） | 官方给出错误码 |
| 余额端点 | `/ent/v2/credits`（探测端点，非文档） | 不在本文档站 | 沿用实测口径，客户端标注来源 |

**未确证项（如实登记）**：① avatar 专属池与通用池在 ent API 计费时走哪一个——官方文档未提池概念，
本轮以生成前后双池差值实测；② 本轮双 key 的并发限 5 是主控给的运营口径，文档仅有 QuotaExceeded 语义；
③ 540p/720p 的像素尺寸官方未列（沿用 v3 实测值）；④ `/ent/v2/credits` 的认证方案 Bearer/Token
两者是否皆通——本轮 balance 命令实测（Token 优先，失败自动换 Bearer，结果记入 smoke 留痕）。

### 8.1 smoke 实测关账（2026-10-09，真实生成 2 次）

- **未确证项①关账**：avatar offline 走【通用池】。正证：key_2 任务 1005863650101063680 前后
  general 565→562（delta=3=credits）、exclusive 5000 不动；反证：key_1 专属池 5000 但通用池空，
  提交即 HTTP 400 `reason=CreditInsufficient`。与 v3 期实证（工程方案v3.1 §0.2 V6 期通用池
  683→622、专属池不动）双重吻合。gen_avatar.py 积分守卫已按此修正为通用池主判。
- **未确证项④部分关账**：`/ent/v2/credits` 与全部 create/query 调用本轮全部 `Authorization: Token`
  直连 200，未触发 Bearer 降级路径（该路径保留作兜底，未实测）。
- **未确证项③补充实测**：本轮参考图 768×1354 → 540p 输出 548×944（24fps h264+aac）。
  与 v3 的 618×836 并不同——确认「540p/720p 输出尺寸随参考图比例变化」，官方未列固定像素表。

## 9. 原文留存

RSC flight 原文快照（提取自上述三个页面 URL 的 HTTP 200 响应体，UTF-8 markdown 全文）：
本文件 §1-§7 所有表格与引用块均为原文或紧缩摘录；完整 markdown 快照在提取会话 /tmp/md_{introduction,parameters,quick-start}.md，
关键内容已全文誊入本文件，未做语义增删。
