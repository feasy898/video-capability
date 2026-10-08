# 凭据重建记录（TASK_v4 A-3 / TASK.md A-3）

> 2026-10-08｜重建执行：主控（leader）｜存放位置：GPU 机 `/data/night/g01-rerun/video-capability/overnight/secrets/api_keys.env`（0600，`.gitignore` 覆盖 `overnight/secrets/`，从未入 git）

## 1. 背景

原 `overnight/secrets/api_keys.env` 随 windev-01 销毁（2026-10-07 前后）灭失。owner 2026-10-08 指示：**所有密钥在 governance 机器（tailnet）的 OpenBao 里面**。

## 2. OpenBao 访问路径（实测）

| 项 | 值 |
|---|---|
| 主机 | governance-machine `100.64.0.6`（tailnet edgenet，OpenBao 容器 `company-bao-1`，监听 8200，docker-proxy 暴露在 tailnet 面） |
| 版本 | OpenBao 2.6.2，shamir 封护，**unsealed** |
| CLI | `/usr/local/bin/bao` |
| 寻址 | `BAO_ADDR=http://127.0.0.1:8200`（机内）或 `http://100.64.0.6:8200`（tailnet） |
| 认证 | broker 的 `ADMIN_TOKEN`（`/etc/vault-broker/broker.env`，vaultbroker 用户 600）实测为 **root 级 token**（`bao token lookup` → policies=['root']） |
| KV 布局 | kv v2，`kv/company/` 根（WO-0005 布局 `kv/company/gpu/` 为公司 GPU 面约定） |

**纪律声明**：root token 只在治理机上以环境变量形式瞬用于取数，未落任何文件、未进入本机 shell 历史之外的位置；所有密钥值从未在终端/日志/报告中回显（上述探查命令一律脱敏输出）。

## 3. 取到的密钥（路径与字段名，值不回显）

| 通道 | bao 路径 | 字段 | 元数据（bao 记录） |
|---|---|---|---|
| MiniMax | `kv/company/LLM-upstream/MiniMax` | `Token` / `base_url` | plan=token-plan，source=owner 2026-09-30 direct，window=5h+weekly，video-quota=[unverified] |
| StepFun | `kv/company/LLM-upstream/stepfun/step-plan-1` | `api_key` / `base_url` | step plan 套餐，OpenAI 兼容 `/step_plan/v1/chat/` |
| Zhipu | `kv/company/LLM-upstream/Zhipu/zhipu-bigmodel-CodingPlan-1` | `api_key` / `base_url` | CodingPlan |
| kimi | `kv/company/LLM-upstream/kimi/kimi-1` | `api_key` / `base_url` | coding plan 通道 |
| Higress consumer | `kv/company/gpu/models/higress-consumer` | `consumer` / `key` | purpose=模型入口鉴权 |

## 4. 未取到的（如实）

- **Vidu**：对 `kv/company/` 全量递归（50 个叶子路径）搜索 `vidu/video/avatar` 关键词 **0 命中**。Vidu avatar 通道（数字人口播专线）无 key 可重建 → **M2 数字人段依赖 owner 另行提供 Vidu key**（或确认放弃该段）。
- MiniMax 的 `video-quota` 与 `window` 字段为 `[unverified]` 标注，按不可进预算基线处理（与白皮书 §4 成本可信度分层口径一致）。

## 5. 落盘与环境变量名（api_keys.env 格式）

```
MINIMAX_TOKEN / MINIMAX_BASE_URL
STEPFUN_API_KEY / STEPFUN_BASE_URL
ZHIPU_API_KEY / ZHIPU_BASE_URL
KIMI_API_KEY / KIMI_BASE_URL
HIGRESS_CONSUMER / HIGRESS_KEY
# VIDU_API_KEY= （占位注释：owner 待提供）
```

注意：vpipe `gen_api.py` 云通道（`/minimax-cloud/` 三步流）**零本地凭据**（token/Authorization 由 higress 网关注入，SPEC.md §2.2），MiniMax 视频生成不依赖本文件；本文件主要供 StepFun TTS、判官（Zhipu/StepFun/kimi）与备用通道使用。

## 6. 复现步骤（任何人按此可重放）

```bash
# 1. 治理机上（root）：
export BAO_ADDR=http://127.0.0.1:8200
export BAO_TOKEN=$(grep '^ADMIN_TOKEN=' /etc/vault-broker/broker.env | cut -d= -f2-)
bao kv get -format=json kv/company/LLM-upstream/MiniMax      # 字段结构核实
# 2. 取数写文件（0600）→ scp 到 GPU 机 overnight/secrets/（gitignore 域）
# 3. GPU 机上最小真实调用留痕（不含值）：如 StepFun GET /accounts 余额、Zhipu chat 冒烟
```

## 7. 红线

- 本文件与任何密钥值不得入 git/日志/报告/遥测（v3.1 密钥纪律延续）。
- token 轮换：bao root token 如有轮换，按 §6 重新执行，不得长期驻留文件。
- 判官调用（Zhipu/StepFun/kimi）产生的消耗记入每 CP 成本台账（`src/cost/`，M2 落地）。
