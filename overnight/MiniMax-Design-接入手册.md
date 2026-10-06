# MiniMax Design（桌面客户端会员通道）接入手册

> 产出：MiniMax接入探索员（overnight 任务），2026-10-06。
> 所有端点均在本会话实测（curl 实跑），标注 ✅ 的为验证通过；标注「未实测」的仅静态提取自客户端代码，未产生生成调用。
> **安全纪律**：本手册不含任何 token/JWT。鉴权头由 higress 网关注入，调用方零凭据。

## 0. 总览：两条通道

| 通道 | 网关入口 | 上游 | 承载 |
|---|---|---|---|
| chat（OP5.5） | `http://100.64.0.6:8080/minimax/` | hub.minimaxi.com（旧域名，路径改写 `/minimax/`→`/api/`） | Anthropic Messages 协议文本对话 |
| 云能力（本手册新增） | `http://100.64.0.6:8080/minimax-cloud/` | design.minimax.cn（路径透传 `/minimax-cloud/`→`/`） | 视频/音乐/TTS/图像/音色 等 |
| （既有，不动） | `http://100.64.0.6:8080/minimax-design/` | hub.minimaxi.com 根 | hub 根路径 API |

- 网关注入头：`token`（JWT）、`device_id`、`version_code: 3.0.21`；cloud 通道另注入 `Authorization: Bearer <JWT>`。
- JWT 有效期至 2026-11-13；续期 cron：治理机 `minimax_token_renew.py`（每日 05:50，临期<7天自动续）。
  ⚠️ 续期脚本目前只更新 hub 两个 ingress 文件，`minimax-design-cloud.internal.yaml` 需手工同步（见 risks）。

---

## 1. OP5.5 文本对话（chat）✅

- **端点**：`POST http://100.64.0.6:8080/minimax/v1/messages`
- **协议**：Anthropic Messages。body `{"model":"alpha","max_tokens":N,"messages":[{"role":"user","content":"..."}]}`；`x-api-key`/`anthropic-version` 由网关处理（占位值即可）。
- **模型名真相**：`"model":"alpha"` 是 hub 侧别名，**实际后端为 `claude-opus-5-5`**（响应体 `"model":"claude-opus-5-5"` 实证）。任务书里的 "OP5.5" 即此。
- **服务端文本模型目录**（GET `/minimax/v1/models/config` 的 `textModels`，默认 `minimaxHub/MiniMax-M3`）：
  - `minimaxHub/MiniMax-M3`（MiniMax M3，低延迟 3-8s）
  - `gamma/gamma`（显示名 "OAI 5.5"，8-15s）
  - `omega/omega-3.1-pro`（"Gemi 3.1 Pro"，5-10s）
  - 实测：以上目录 id 直接作为 `model` 传 `/v1/messages` 会 400 `client_error`；**目前唯一验证通过的 chat 模型名是 `alpha`**。
- **响应**：Anthropic 格式（`content[].text`、`stop_reason`、`usage.input_tokens/output_tokens`，含 cache/iterations 细分）。
- **复跑示例**（chat 消耗会员额度，勿刷）：
  ```bash
  curl -sS http://100.64.0.6:8080/minimax/v1/messages \
    -H 'Content-Type: application/json' \
    -d '{"model":"alpha","max_tokens":32,"messages":[{"role":"user","content":"回复OK"}]}'
  ```
- **限制**：会员并发/额度未知；网关日志口径 2026-10-05~06 已有 ~190 次 200（历史 agent 调用）。

---

## 2. 视频生成（T2V / I2V / 首尾帧 / 续写）✅

模型（服务端目录 `videoModels` 中 backend=`minimax_v3` 的 MiniMax 系）：

| 模型 id | 时长 | 分辨率 | 模式 | 备注 |
|---|---|---|---|---|
| `MiniMax-H3` | 4–15s 整数 | `768P`/`2K` | reference（参考图）/first-last-frame（首尾帧）/video-extension（续写，仅768P） | 默认视频模型，prompt≤7000字，refs≤9 |
| `MiniMax-H3-Max` | 5–15s | `480P`/`768P` | reference/first-last-frame/text-to-video | `prompt_expansion_mode`: disabled/balanced/quality |
| `MiniMax-H3-Max-Turbo` | 同 Max | 同 Max | 同 Max | refs≤2，快 |

比例：`adaptive`/`16:9`/`4:3`/`1:1`/`3:4`/`9:16`/`21:9`（纯文生默认 16:9；首尾帧强制 adaptive）。`generate_audio`: true/false（H3 系支持带音轨，实测产物含 aac）。

### 2.1 三步工作流（异步任务）
```
① 提交  POST /minimax-cloud/api/v1/video/minimax-v3/generate   → {"task_id": "...", "base_resp":{"status_code":0}}
② 轮询  GET  /minimax-cloud/api/v1/video/minimax-v3/tasks/{task_id} → status: processing→success, estimated_remaining_wait_seconds
③ 取文件 GET /minimax-cloud/api/v1/video/minimax/files/{task_id}    → {"file":{"download_url":"https://cdn.hailuoai.com/...mp4","file_id":...}}
```
- 轮询间隔建议：提交响应即含预估秒数（实测 4s 视频约 5.5 分钟出片）。

### 2.2 复跑示例（本次验证用例，T2V 最短 4s）
```bash
# ① 提交（生成类调用——注意会员额度，实测只跑了这一次）
curl -sS http://100.64.0.6:8080/minimax-cloud/api/v1/video/minimax-v3/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"MiniMax-H3","prompt":"一只橘猫趴在洒满阳光的窗台上打盹，镜头缓慢推近","duration":4,"resolution":"768P","generate_audio":false,"ratio":"16:9"}'
# ② 轮询 / ③ 取文件同上；产物示例：h264 1344x768 + aac，4.46s，1.1MB
```
I2V：body 加 `first_frame_image`（+`last_frame_image`），值为 URL；本地图先传 `POST /minimax-cloud/api/v1/files/upload`（客户端逻辑，未实测）。参考图数组用 `reference_images`；续写用 `POST .../minimax-v3/continuation/generate`（body: model/prompt/video_url/duration，源片 2–15s，总长≤20s，未实测）。

### 2.3 客户端目录里的其他视频 backend（未实测）
`seedance2.0/2.5/fast/mini`、`wan3.0-video(-prime)`、`kling-v3-omni`、`kling-avatar`——第三方 provider，是否含在本会员额度内未知，路径形如 `/api/v1/video/seedance/generate`+`/tasks`。

---

## 3. 音乐生成 ✅

- **端点**：`POST http://100.64.0.6:8080/minimax-cloud/api/v1/audio/music/minimax`（**同步**返回，实测约数十秒）
- **body**：`{"prompt":"...","model":"music-3.0","is_instrumental":true}`；非纯器乐时可传 `lyrics`（不传则客户端会先调 `POST /api/v1/audio/lyrics/generate` `{mode:"write_full_song",prompt}` 生成词，未实测）
- **响应**：`{"audio_url":"https://cdn.hailuoai.com/...mp3","duration":162.324,"base":{"message":"success"}}`（实测产出 162s mp3）
- **翻唱**：`POST /api/v1/audio/music/cover/generate` `{prompt, model:"music-cover", lyrics?, cover_feature_id?|audio_url?}`（未实测）
- 复跑示例（消耗额度，最小验证只跑了 1 次）：
  ```bash
  curl -sS http://100.64.0.6:8080/minimax-cloud/api/v1/audio/music/minimax \
    -H 'Content-Type: application/json' \
    -d '{"prompt":"轻快的钢琴小曲，清晨的心情","model":"music-3.0","is_instrumental":true}'
  ```

---

## 4. TTS / 语音 ✅

- **TTS**：`POST http://100.64.0.6:8080/minimax-cloud/api/v1/audio/tts`（同步）
  - body：`{"model":"speech-2.8-hd","text":"...","voice_id":"Friendly_Person","speed":1,"language_boost":"auto","subtitle_enable":false}`；可选 `emotion`(calm/happy/sad/angry/fearful/disgusted/surprised/fluent)、`vol`、`pitch`、`pronunciation_dict`、`voice_modify`
  - 响应：`{"audio_url":"https://cdn.hailuoai.com/....mp3","subtitle_url":...}`（实测秒级返回）
- **音色列表**：`GET http://100.64.0.6:8080/minimax-cloud/api/v1/audio/voices` ✅（全量音色含 voice_id/风格描述/语言/性别）
  - 常用 voice_id（服务端目录默认六项）：Friendly_Person、Calm_Woman、Energetic_Male、Professional_Female、Deep_Male、Young_Female
- **未实测**（客户端有路径，静态提取）：`/api/v1/audio/tts/batch`、`/api/v1/audio/voice_clone`（≤20MB mp3/m4a/wav）、`/api/v1/audio/voice_design`、`/api/v1/audio/voice_isolation`（≤500MB/300s）、H3 音频续写 `/api/v2/audio/minimax-v3/continuation`
- 复跑示例：
  ```bash
  curl -sS http://100.64.0.6:8080/minimax-cloud/api/v1/audio/tts \
    -H 'Content-Type: application/json' \
    -d '{"model":"speech-2.8-hd","text":"你好，这是接入验证。","voice_id":"Friendly_Person","speed":1,"language_boost":"auto","subtitle_enable":false}'
  ```

---

## 5. 图像生成 ✅

- **端点（同步）**：`POST http://100.64.0.6:8080/minimax-cloud/api/v1/image/nano_banana/generate`
  - body：`{"prompt":"...","model_name":"nano_banana_2_flash","image_paths":[],"aspect_ratio":"1:1","resolution":"1K"}`
  - `model_name`：`nano_banana_2_flash`（General Image 2，快）/ `nano_banana_2`（General Image Pro）；`resolution`：1K/2K/4K
  - 响应：`{"image_url":"https://cdn.hailuoai.com/....png","width":1024,"height":1024,"base":{"message":"success"}}`（实测 1 张）
  - 异步变体：`POST /api/v2/image/nano_banana/generate` + `GET /api/v2/image/nano_banana/tasks/{id}`（未实测）
- **目录里其他图像 backend（未实测）**：`g-image-2.5-sunburst/flare/2`（openai backend，"Design Image 2.5 Pro/Fast"）、seedream 5.0 Pro/4.5、midjourney-8.2——路径 `/api/v2/image/{openai,qwen,seedream}/generate`、`/api/v1/image/{kling,midjourney}/generate`。
- 工具类：`POST /api/v1/tool/analyze_media`、`/api/v1/tool/super-resolution/generate`+`/tasks`（hailuo03-super-resolution，未实测）。

---

## 6. 模型目录与元信息端点 ✅（GET，零消耗）

- 全目录：`GET http://100.64.0.6:8080/minimax/v1/models/config`（经 hub 通道；`audioModels[4] imageModels[8] textModels[3] videoModels[9]` + `defaultTextModelId`）
- 并发/额度：`/minimax-cloud/api/v1/models/concurrency/limits`、`/usage`（未实测）
- 活动信息：`GET /minimax-cloud/api/v1/client_config` → 如 seedance 限时折扣（未实测其含义）

## 7. 计费 / 积分线索

- 模型按 `pricingId` 计费：视频 `MiniMax-H3` / `MiniMax-H3-Max` / `MiniMax-H3-Max-Turbo`，TTS `speech-2.8-hd`，音乐 `music-3.0`；第三方 backend 各自 pricing（如 `midjourney-8.2`）。
- 单价、会员积分余额接口**未探明**（未找到余额查询端点；concurrency/limits 未实测）。生成类调用走的是桌面端会员通道同一账号，额度与客户端共享，**请节约使用**。

## 8. 证据清单（本会话实测）

- 视频：task `APEze2kOmOyb`（provider_task_id 449354874577202），status=success，产物 mp4 h264 1344×768+aac 4.46s 已存 `/tmp/mm/hailuo_h3_test.mp4`（临时目录）
- TTS/音乐/图像：各 1 次同步成功（audio_url/image_url 均 CDN 直链）
- chat：`alpha` 1 次成功，响应 model=claude-opus-5-5
- chat 非法模型名 400（错误体为 Anthropic error JSON，不泄露可用模型列表）
- higress 日志：route `minimax-design-cloud.internal` 200/400 记录；旧路由 `/minimax/v1/models/config` 回归 200

## 9. Risks / 待办

1. **续期脚本不同步**：`minimax_token_renew.py` 只更新 hub 两个 yaml；token 续期后 `/minimax-cloud/` 会 401/403，需把新 token 行同步进 `minimax-design-cloud.internal.yaml`（建议后续让脚本同时更新，本次未改动该脚本）。
2. JWT 2026-11-13 到期；保活依赖治理机 cron（owner 已布）。
3. 会员额度/单价未见查询端点——大量生成前先小批量验证。
4. 第三方 backend（seedance/wan/kling/midjourney/openai 系图像）未验证是否在会员内。
5. ~~既有 `vpipe/src/gen_api.py` 走的是 windev 本机客户端 gateway（127.0.0.1:8001），与本手册的网关云通道并存；建议迁移到网关通道（免 windev 依赖）。~~
   **✅ 已迁移（2026-10-06）**：`gen_api.py` 默认 `--backend cloud` 走本手册 §2.1 三步流（同接口面，windev 通道降为可选后端）；实测证据 `vpipe/out/cloud_migration_smoke/`（4s/768P 云通道直出）。残留：`gen_avatar.py:99` 的 TTS 备用通道 `DESIGN_GATEWAY=127.0.0.1:8001`（design-seedaudio，默认走 StepFun 不受影响）未迁——云 TTS 端点见本手册 §4，后续同法可迁。


## 勘误（2026-10-06 主会话）

§9-1 所述 minimax_token_renew.py 不同步 minimax-design-cloud.internal.yaml 的问题**已于 2026-10-06 修复**：脚本扩展为 hub / hub-short / cloud 三 ingress 文件同步更新（备份 .bak-20261006-minimax-cloud，语法与三文件 token 行命中已验证）。token 续期后无需手工同步。
