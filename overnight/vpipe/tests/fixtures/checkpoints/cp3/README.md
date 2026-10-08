# CP3 门禁校验器夹具（validate_cp3.py）

配套校验器：`overnight/vpipe/src/gate/validate_cp3.py`（校验器七条，判定数值只读
`eval/thresholds.yaml` 的 `checkpoints.cp3.gate.*`）。出处：白皮书 §3 CP3「客观验收
门禁」行 + AI视频生产流水线方案.md §3.2 校验器七条 + SPEC_v2.md §1 CP3 行。

## 运行口径

```bash
cd overnight/vpipe
# pass 组：exit 0
python3 src/gate/validate_cp3.py tests/fixtures/checkpoints/cp3/pass/cp3_pass.json --script tests/fixtures/checkpoints/cp3/pass/cp2_pass.json
# fail 组：exit 1（verdict=fail）
python3 src/gate/validate_cp3.py tests/fixtures/checkpoints/cp3/fail/cp3_over_duration.json --script tests/fixtures/checkpoints/cp3/fail/cp2_over_duration.json
```

**fail-closed 口径（主控验收修订 2026-10-08，取代早期 SKIP 语义）**：CP3 工件按契约
不带 cast/props 注册表（storyboard `additionalProperties:false`），词锚存在性/镜头数
一致性/引用完整性只能经 `--script` 解析。因此：① 工件带词锚或 refs 而不传 `--script`
→ 拒（③/⑦）；② 任何 CP3 工件不传 `--script` → ⑥ 拒（`source_script_fingerprint`
是必填字段，工件结构上依赖 CP2）。不带 `--script` 的合法用途只有一种：验证「缺源即拒」
本身（见 fail 组 `cp3_fail_refs_without_script.json`）。

## pass 组（预期 exit 0）

| 文件 | 覆盖 |
|---|---|
| `cp3_pass.json` + `cp2_pass.json` | 全七条：3 镜/3 台词；`@{信}` 剥壳与裸词「推门」两种词锚形态 |
| `cp3_pass_during.json` + `cp2_pass_during.json` | ④⑤ 正路径：during 同场景（`s01` 前缀约定）、已定义、编译序在前；含列表形式与 `@<shot_id>` 整镜形式 |
| （已改判）`fail/cp3_fail_refs_without_script.json` | 带 refs+词锚但无 `--script` → 拒；配对 `cp2_pass.json` 后转 pass（证明拒因是缺源而非工件损坏） |

## fail 组（预期 exit 1；命名即目标校验条）

| 文件（cp3_*.json 配同名 cp2_*.json） | 目标校验 | 预期 failed |
|---|---|---|
| `cp3_missing_element` | ① 五要素 | 仅 `five_elements_complete`（refs=[]，schema 容许、rule 门拒） |
| `cp3_over_duration` | ② 单段上限 | 仅 `max_shot_duration_s`（16.0s > 15.0） |
| `cp3_anchor_text` | ③ 词锚定 | 仅 `word_anchor_valid`（@老地方 不在本镜台词） |
| `cp3_anchor_segment` | ③ 词锚定 | 仅 `word_anchor_valid`（segment_id=seg_09 悬空） |
| `cp3_during_cross_scene` | ④ 跨镜 during | 仅 `during_reference_valid`（s01→s02 跨场景） |
| `cp3_circular` | ⑤ 循环引用 | `no_circular_reference`（ep1-a01→ep1-a02→ep1-a01 成环）**和** `during_reference_valid`（ep1-a01 后向引用编译序违例——环必然伴随 ④，属结构性后果） |
| `cp3_count_mismatch` | ⑥ 镜头数=台词条数 | 仅 `shot_line_count_match`（3 镜 vs 4 台词） |
| `cp3_dangling_ref` | ⑦ 引用完整 | 仅 `reference_integrity`（ghost_char 不在 cast/props） |
| `cp3_fail_refs_without_script` | fail-closed（主控修订新增） | ③⑥⑦ 全 fail（无 `--script`）；配 `cp2_pass.json` 后转 pass |

## 已知口径说明（诚实边界）

1. **during 为规则层字段**：现行 `checkpoint.schema.json` 的 `storyboard` 分支
   （additionalProperties:false）未含 `during` 键；白皮书 §3 CP3 与方案 §3.2 的七条
   中「跨镜 during」是规则门职责，故夹具 B / fail 组的 during 夹具在 schema 层不合法、
   在本规则门下按七条判定。二者不冲突：结构归 schema，规则归校验器。
2. **场景判定约定**：shot_id 首个 `-`/`_`/`.` 分隔符前的段为场景段（`s01-03`→`s01`；
   无分隔符自成一段）。`shot_01` 风格的 id 全片同场景，同场景判定因此保守放行。
3. **SKIP≠pass 判定造假**：无 `--script` 时 ③⑥⑦ 只做可执行部分，verdict JSON 的
   `skipped` 数组逐条明示；exit 0 只表示「已判各条全过」。
