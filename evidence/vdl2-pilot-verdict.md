# VDL v2 试点裁决（TASK_v4 §2.4 D-2）——**继续（continue）**

> 裁决日期：2026-10-09｜裁决人：主控（leader）｜证据基础：本会话实跑（非转引）

## 1. 裁决结论

**继续（continue）**——VDL v2 作为编排语言层保留并推进，不调整、不终止。

## 2. 证据（本会话实跑，命令+退出码）

| 证据 | 命令 | 结果 |
|---|---|---|
| 双闸门校验 | `python src/vdl2/vdl2_validate.py --pkg examples/vdl2/10_shortdrama_ep01.yaml` | PASS：gateA=0err gateB=0err rules+cross=0err warnings=0 |
| 编译投影 | `python src/vdl2/vdl2_compile.py --pkg examples/vdl2/10_shortdrama_ep01.yaml --out-dir …` | OK：v1_shots=2、acceptance_records=3、errors=0——VDL v2 包成功投影为 v1 shot JSON（v1 引擎零修改消费） |
| 测试套件 | `pytest tests/test_vdl2.py -q`（默认 VPO root，jsonschema≥4.18） | **20 passed**（正例 3 包 validate+compile、负例全预期码拒收、v1 投影过冻结契约、prompt hash 可复算、槽位与执行计划） |
| 负例防线 | `99_negative_must_reject.yaml` | 全部预期错误码命中（R1 悬空引用/R6 模型名 not-pattern 等） |

环境注记（如实）：本会话早期 9 failed 系两个环境问题——VDL2_VPO_ROOT 被误指到 `vpo`（正确默认 `vpo/schemas`）与系统 jsonschema 4.10.3 过旧（`registry=` 参数需 ≥4.18，已升级 4.26.0 并复跑 20/20）。非 VDL v2 自身缺陷。

## 3. 裁决依据

1. **层位价值被三线实证间接验证**：三条试点线的 CP1-CP6 工件链（意图单→剧本→分镜→动作→时间线）与 VDL v2 的 intents/shots/post_ops/acceptance 结构同构；短剧线的 VDL v2 示例包（10_shortdrama_ep01.yaml：两镜、camera intent 外置文件形态、acceptance_ref 挂接）validate+compile 全过，证明「意图→镜头 spec」的编排语言在真实剧集数据上可编译、可投影、可被 v1 冻结契约消费。
2. **投入产出比成立**：vdl2 工具集（validate/compile）已存在且测试全绿，剩余工作明确且有限——营销/漫剧两线的 VDL v2 包建设（照短剧线示例包形态）+ 反向骨架器（扫描存量 CP 工件成包，白皮书 §6 VDL v2 行）。终止将报废已建资产且失去「包级预算/验收前置冻结」能力。
3. **与白皮书 §8 整合方式一致**：白皮书裁定 VDL v2 = 编排语言层（CP1-CP6 工件即其投影），裁决「继续」与该整合方式不冲突。

## 4. 继续的下一步（纳入 v4 剩余工作）——**三事项已全部达成（2026-10-09）**

| # | 事项 | 验收 | 状态 |
|---|---|---|---|
| 1 | 营销线/漫剧线 VDL v2 包建设（照 10_shortdrama_ep01.yaml 形态，含 acceptance_ref） | 两包 validate+compile 0err | **达成**：examples/vdl2/40_marketing_ep01.yaml（6 镜/2016 积分）与 50_comicanime_ep01.yaml（9 镜/3360 积分），validate+compile 双 0err 并纳入 pytest POS |
| 2 | 反向骨架器：扫描 out/m2/<line>/ 的 CP 工件生成 VDL v2 包 | 三线各出一包，validate 0err | **达成**：src/vdl2/vdl2_skeleton.py，三线成包 validate+compile 全 0err（out/vdl2/skeleton/） |
| 3 | vdl_project.py（白皮书 §6 投影器）：包→CP 工件链直接投影（替代手写 build 脚本） | 短剧线包投影产物与现有 cp1-cp6 工件语义等价（指纹可对账） | **达成**：src/vdl2/vdl2_project.py，短剧/营销两线往返 exit 0（cp1/cp2/cp3/cp5/cp6 五件 payload/指纹/upstream_refs 位级相等，主控独立复核）；漫剧线 exit 1 为已登记参照缺陷（evidence/vdl2-known-defects.md 缺陷一，cp6 补帧负索引 bug，登记不修） |

执行留痕：提交 bfd9a5d（三卡建成）+ af8bb3f（独立复审 9 发现之修复轮：七修两登记）；
tests/test_vdl2_tools.py 6 例锁往返行为；终态门禁 pytest 28 passed、五包 validate 0、
run_m2m3_acceptance 25 PASS/0 FAIL。

## 5. 风险与边界

- ~~VDL v2 当前只有 2 镜级示例包跑通全链；11 镜级（短剧线实际规模）的包尚未建——事项 1/2 的首要验证点。~~ **已解除**（2026-10-09）：11 镜级短剧线往返对账 exit 0 位级相等；营销 6 镜/漫剧 9 镜级包已建。
- 判官/生成执行仍走 vpipe v1 引擎（gen_api/gen_local/qc_orch），VDL v2 不替代执行层（白皮书 §8 投影图不变）。
