# PROVENANCE — vendored VPO schemas

本目录 `vpo/schemas/` 是 **video-Ontology（VPO）仓 `schemas/` 全树的只读 vendored 副本**，
供 VDL2 闸门 B（2020-12 深校验）在 windev 原路径灭失后于本仓内自足解析。

| 项 | 值 |
|---|---|
| 来源 | windev 抢救 git bundle：`~/workspace/windev-salvage/video-Ontology.bundle`（master 分支，2026-10-06 抢救带回） |
| 上游仓 | feasy898 体系 `video-Ontology`（VPO — Video Production Ontology 本地实现，M1–M7；上游自述"不推远程"） |
| 上游 commit | `master@21b56093525bd8e3599599e3b6e5f906a86f2438`（2026-09-23 02:34:22 +0800，"Handoff: record CE-31 kimi weekly-quota block…"） |
| 获取日期 | 2026-10-06 |
| 提取范围 | 仅 `schemas/` 全树：`common/`(6) + `l1/`(6) + `l2/`(19) + `l3/`(4) + `l4/`(2) + `l5/`(1)，共 38 个文件，368 KB |
| 完整性 | `git clone` bundle 后逐文件 `sha256sum` 比对，38/38 与 bundle checkout 一致 |
| 内容改动 | 零——逐字节原样拷贝，未改写任何 schema 文本 |

## 用途与解析顺序

`src/vdl2/vdl2_validate.py::DEFAULT_VPO_ROOT` 按以下优先级解析 VPO schema 根目录：

1. 环境变量 `VDL2_VPO_ROOT`（显式覆盖，指向任意 video-Ontology `schemas/` 根，如本机另有完整 checkout）；
2. 缺省：本目录 `vpo/schemas/`（vendored 副本）。

## 红线状态变更（草案 §7.1）

原红线"不复制任何 VPO schema 文本进 vpipe"建立于 windev 共享路径 `D:/workspace/video-Ontology/schemas`
始终可用的前提之上。该路径随 windev 灭失（W5 工单，2026-10-06），VDL2 闸门 B 因此 fail-fast。
经 W5 工单裁定，改为仓内 vendored 只读副本 + 本 PROVENANCE 追溯。**VPO schema 文本本身零改动**；
若本机恢复了上游 video-Ontology checkout，用 `VDL2_VPO_ROOT` 指回原版即可回到零复制形态。

## 更新方式

上游 video-Ontology 有新版本时：重新从 bundle/checkout 提取 `schemas/` 覆盖本目录，
逐文件 sha256 比对，并更新上表 commit 与日期。
