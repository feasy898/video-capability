# cp5_gltf — CP5 blocking → glTF 2.0 armature 往返验证夹具（v4 · M1-W4）

TASK_v4.md:197（W4）+ §8 决策记录 2026-10-08-b（TASK_v4.md:525）：双机无 Blender，
M1-W4 Blender 连通性验证改判 **glTF 2.0 armature 往返**。验收等价物：往返后关节层级 +
关键帧时间/弧度零丢失。工具：`src/gate/blocking_to_gltf.py`（纯标准库，只写 JSON .gltf，
不做 .glb；schema 16 关节词表唯一来源 `contracts/v2/checkpoint.schema.json`）。

## 文件清单

| 文件 | 作用 |
| --- | --- |
| `roundtrip.gltf` | 由 `contracts/v2/examples/cp5.json` 导出的合法 glTF 2.0（17 节点 = 16 关节 + 臂架根；1 animation / 3 sampler / 8 关键帧；LINEAR；buffer 为 base64 data URI 内嵌） |
| `roundtrip_check.json` | 上一步的往返校验 verdict（`verdict=pass / lossless=true`，逐关键帧 max&#124;Δ弧度&#124;=7.1e-08 rad） |
| `negative_broken_joint_ref.json` | 负控制源：唯一注入缺陷 = `tracks[1].joint="leftThigh"`（16 关节词表外，断链） |
| `negative_broken_joint_check.json` | 负控制实跑 verdict（`verdict=fail / exit_code=1`，problems 指明断链轨道；目标 .gltf 未落盘） |
| `cp5_lip_fixture.json` | 口型层分支源：`speech_mode=independent_lip_layer`（validate_cp5 ⑤ warn+pass，exit 0 已实测） |
| `lip_layer_jaw.json` | 口型层 keyframe（ToonFlow track 形状，`--lip-layer` 消费；jaw 张合绕 x 轴） |
| `cp5_lip.gltf` / `cp5_lip_check.json` | 口型层分支产物：18 节点（+`{shot}:jaw` 挂 head 下）/ 3 通道 / 11 关键帧零丢失 |

## 复现命令（cwd = `overnight/vpipe/`，实跑退出码见各行注释）

```bash
# 正件：示例工件 → glTF + 往返校验（exit 0，lossless=true）
python3 src/gate/blocking_to_gltf.py contracts/v2/examples/cp5.json \
  --out tests/fixtures/checkpoints/cp5_gltf/roundtrip.gltf \
  --report tests/fixtures/checkpoints/cp5_gltf/roundtrip_check.json          # exit 0

# 负控制：断链 blocking 必须 exit≠0 且 errors 说清原因，不落盘任何 .gltf
python3 src/gate/blocking_to_gltf.py \
  tests/fixtures/checkpoints/cp5_gltf/negative_broken_joint_ref.json \
  --out /tmp/cp5_neg.gltf \
  --report tests/fixtures/checkpoints/cp5_gltf/negative_broken_joint_check.json  # exit 1

# 口型层分支：--lip-layer 提供 jaw 轨道 → 额外写 {shot}:jaw 节点 + 轨道
python3 src/gate/blocking_to_gltf.py tests/fixtures/checkpoints/cp5_gltf/cp5_lip_fixture.json \
  --out tests/fixtures/checkpoints/cp5_gltf/cp5_lip.gltf \
  --lip-layer tests/fixtures/checkpoints/cp5_gltf/lip_layer_jaw.json \
  --report tests/fixtures/checkpoints/cp5_gltf/cp5_lip_check.json            # exit 0

# 回归：CP5 门禁校验器对示例/lip 夹具均应仍 exit 0（未被本批改动影响）
python3 src/gate/validate_cp5.py contracts/v2/examples/cp5.json             # exit 0
python3 src/gate/validate_cp5.py tests/fixtures/checkpoints/cp5_gltf/cp5_lip_fixture.json  # exit 0
```

## 断言要点（roundtrip_check.json 结构）

- `verdict=pass / exit_code=0 / lossless=true`；
- `checks[].id`：`input_blocking_valid` / `gltf_structure`（节点数、父子层级 = mannequin 拓扑、
  最大深度 6）/ `animations_samplers`（input=output 等长、时间严格单调、缓冲字节对账）/
  `keyframe_lossless`（时间 float32 容差、单位四元数、弧度往返 ≤1e-5 rad）/
  `lip_layer`（written / skipped+原因，如实记录）；
- 负控制：`negative_broken_joint_check.json` 的 `problems[0]` 必须点名
  `tracks[1].joint='leftThigh'` 断链。

生成时间：2026-10-08（M1 第二批，CP5 glTF 往返工程师实跑留痕）。
