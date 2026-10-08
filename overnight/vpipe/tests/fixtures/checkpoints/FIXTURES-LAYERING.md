# CP 夹具双层覆盖设计说明（2026-10-08 主控验收补档）

> 背景：M1 第一批校验器验收时发现，部分 fail 夹具会被 **schema 结构层**先拦下（根本到不了
> 规则门）。本文件固定这一设计的口径，防止后续维护者误以为"夹具没被规则门拦到"是 bug。

## 两层拦截的定位

| 层 | 位置 | 职责 | 拦截形态 |
|---|---|---|---|
| **结构层** | `contracts/v2/checkpoint.schema.json` | 工件的形状合法性（类型/枚举/必填/additionalProperties） | schema 校验拒收（jsonschema ValidationError） |
| **规则层** | `src/gate/validate_cpN.py` | 判定语义（阈值从 `thresholds.yaml` 读，fail-closed） | exit 1 + verdict JSON |

生产流：工件产出 → 结构层校验 → 规则门判定。结构层拒收的工件**永远到不了规则门**。
因此"规则门能拦" ⊂ "结构层能拦"的并集才是完整覆盖。

## fail 夹具的两类（都是有意设计）

1. **仅规则层可拦**（结构合法、语义缺陷）：如 cp2 的时长偏差 13.3%（schema 无总量
   约束）、cp3 的词锚词面不存在、cp6 的字幕对齐超差。这类夹具 schema-valid、
   rule-fail——是规则门回归的主力。
2. **双层覆盖**（结构缺陷、规则层同题也会拦）：如 cp3_over_duration（duration_s=16
   同时违反 schema `maximum:15` 结构兜底与规则门 ②）、cp5 fail_01/04/07（非法关节/
   帧含 scale/bone_length_constant=false，schema const/additionalProperties 先拦）、
   cp6_fail_negative_lead_in（schema minimum:0）。这类夹具证明"结构层和规则层对同一
   缺陷有一致判断"，属纵深防御，不是冗余。

## 结构层数值的纪律边界

schema 内的结构兜底数值（如 storyboard.shots.items.duration_s 的 `maximum:15`）须同时
满足：① 与 v1 契约同值（shot_v2.schema.json 同字段 15，VDL_v2_草案 R3 H3 实测 4–15s）；
② 其 description 必须注明"逐通道上限仍以 params_ref 判定"；③ **判定权威永远在
thresholds.yaml**（SPEC_v2 §0 纪律 3）。新增结构兜底数值须在白皮书/任务卡有出处。

## fail-closed 口径（CP3，主控验收修订 2026-10-08）

CP3 工件按契约不带 cast/props 注册表（storyboard `additionalProperties:false`），
词锚存在性/镜头数一致性/引用完整性只能经 `--script` 解析：
- 带词锚或 refs 而不传 `--script` → 拒（③/⑦）
- 任何 CP3 工件不传 `--script` → ⑥ 拒（`source_script_fingerprint` 必填，结构上依赖 CP2）
- 专用夹具：`fail/cp3_fail_refs_without_script.json`（无 script 拒、配 `cp2_pass.json` 转 pass）

## 回归入口

```bash
bash overnight/vpipe/tests/run_gate_regression.sh
# 预期末行：回归结果: 判对 42 / 错判 0
# 覆盖：5 校验器 × 4 示例 × pass/fail 夹具全组（cp3 含配对 script 与 fail-closed 专项）
```
