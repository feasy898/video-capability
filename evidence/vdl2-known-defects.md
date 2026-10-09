# VDL v2 已知缺陷登记（不修）——独立复审两则

> 编制日期：2026-10-09｜编制：已知缺陷登记员（独立复审）｜**主控复验属实**
> 纪律：按「已登记工件状态不回改」，本文只登记、不做追溯性修改；两条缺陷均维持现状运行。
> 除本文档外本次登记未改动任何仓内文件；全部复核命令在 /tmp 落中间产物，仓内零写入。

---

## 缺陷一：comicanime 参照链 cp6 补帧负索引 bug（severity: medium）

- **状态**：登记不修。
- **位置**：`overnight/vpipe/out/m2/comicanime_ep01/build_cp1_cp6.py:493-497`

```python
remainder = [(ideal[i] - alloc[i], -i) for i in range(len(alloc))]   # L493 键存 -i
remainder.sort(reverse=True)                                          # L494 降序
extra = TOTAL - sum(alloc)
for k in range(extra):
    alloc[remainder[k][1]] += 1                                       # L497 -i 被直接当索引用
```

### 机理

L493 把 `-i` 存进排序键做并列破序（设计意图：同余数先到镜优先），但 L497 取 `remainder[k][1]`
（即 `-i`）直接作列表索引。Python 负索引回卷 `alloc[-i] == alloc[N-i]`（N=9），于是补帧没有落在
排序名次对应的镜 i 上，而是对称回卷落到镜 `N-i` 上。四个补帧全部落错。

### 实跑对照数字（2026-10-09 本会话独立复算，非转引）

输入侧：`est=[5.22, 3.48, 3.26, 4.13, 2.39, 2.17, 3.26, 3.04, 2.61]`，Σ=29.56s（4.6 汉字/s 逐段
round 2）；`ideal=d×720/29.56`，floor 后缺 **4** 帧。

| 项 | 值 |
|---|---|
| 排序后 top4 键 (frac, key) | `(0.8552,-5) (0.7632,-1) (0.5954,-3) (0.5724,-8)` |
| 正确 Hamilton 意图落镜 | shot_06 / shot_02 / shot_04 / shot_09（同 `vdl2_project.py:210-220` 的 `hamilton_frames`：同余数按镜序破并列） |
| **实落镜（负索引回卷 N-i）** | **shot_02 / shot_05 / shot_07 / shot_09** |
| 原代码实落向量 | `[127, 85, 79, 100, 59, 52, 80, 74, 64]`（Σ=720，与 `cp6.json` 磁盘实值逐位相等，复算比对=True） |
| 正确 Hamilton 向量 | `[127, 85, 79, 101, 58, 53, 79, 74, 64]`（Σ=720） |
| 逐镜差（原代码−正确） | `[0, 0, 0, -1, +1, -1, +1, 0, 0]` |

**工件自注记失真**：`cp6.json` notes 记「floor 后按小数余数降序补 4 帧（**shot_06/02/04/09**）」——
这是意图落位（正确 Hamilton 名次），与实落 **shot_02/05/07/09** 不符；帧数向量 `[127,85,79,100,59,
52,80,74,64]` 本身则与实跑一致。即自注记的「哪些镜拿到补帧」错、帧数向量对。

**Σ=720 守恒不破**：守恒门（cp6.gate.duration_conservation_frames ±1 帧）当时 exit 0 属实——错在
余数分配落位，不在守恒。该缺陷系独立复审对账时暴露，非门禁漏判。

### 对照组（marketing 参照 builder 无此缺陷）

`overnight/vpipe/out/m2/marketing_ep01/build_cp1_cp6.py:489-493` 以 `shot_id` 为 key 原位加帧
（`frames_map[sid] += 1`），无负索引问题。本会话以现场重生成骨架包往返 marketing 线，其 cp6
payload 指纹**逐位一致**：`972211e4b2f6a32b…acdbe == 972211e4b2f6a32b…acdbe`（实跑比对=True）。

### 后果实跑（comicanime 线往返对账）

```
python3 src/vdl2/vdl2_skeleton.py --dir out/m2/comicanime_ep01 --out /tmp/…/comicanime_fresh_pkg.yaml   # exit 0
python3 src/vdl2/vdl2_project.py --pkg /tmp/…/comicanime_fresh_pkg.yaml \
    --out-dir /tmp/…/comicanime_fresh_proj --reconcile out/m2/comicanime_ep01                            # EXIT=1
```

- `RESULT 内容类差异 25 处 / 元数据类差异 30 处（分布 CP: cp2,cp3,cp5,cp6）`，判定「存在内容类差异
  → 语义等价不成立（诚实口径，不放宽）」，**exit 1**。
- 其中 **cp6 内容类 16 处**，逐项 = 指纹不一致 1 + `upstream_refs` 1 + `shots[].duration_frames` 4
  （idx3/4/5/6：101↔100、58↔59、53↔52、79↔80）+ `shots[].start_frame` 2（idx4：392↔391；idx6：
  503↔502）+ `subtitle_segments` 端点 4（[3].end、[4].start、[5].end、[6].start）+
  `rhythm_segments[3..6].duration_s` 4。全部 16 处都是同一 4 帧错位的投影。
- 在「不回改已登记件、不破坏投影器正确算法」两前提下，该线往返对账**永远 exit 1**（诚实口径）：
  参照侧错位向量已随指纹冻结，投影侧 `hamilton_frames` 是正确实现，两侧逐位相等不可能达成。

### 处置结论

1. **登记不追溯修改**。`cp6.json` 是已登记 M2 试点工件（worklog.md:55-60「三线收官」2026-10-09：
   漫剧《头汤面》EP1 30s G8 全 12 CP 链；TASK_v4.md:244/253 M2 三线样片行），指纹
   `7b9da66eb15a1199…` 已被下游 `cp7.json`/`cp9.json`/`cp12.json` 的 upstream_refs 引用（grep 实证
   3 件命中）；回改 cp6 即与下游 cp7/cp9 失同步，代价大于收益。
2. **`vdl2_project --reconcile` 对 comicanime 线 exit 1 为已声明的预期行为**，不作为回归失败处置、
   不放宽对账口径。
3. 若未来立项修复：落点是新轮次新工件（参照链 builder 与投影器共用同一 Hamilton 实现，或 builder
   排序键改 `(frac, i)` 升序等价形），不触动本件。

---

## 缺陷二：cp2/cp6 段 ID 双口径潜伏项（severity: low）

- **状态**：登记为潜伏项（三线现数据未触发；下轮数据出现无台词镜时处理）。
- **位置**：
  - 投影器 cp2（镜序编号、跳号）：`src/vdl2/vdl2_project.py:325-337`——`for i, s in
    enumerate(shots, 1)`，`if not speech: continue` 跳过无台词镜但 `segment_id=f"seg_{i:02d}"`
    仍用镜序 `i`，中间镜无台词即产生跳号；
  - 投影器 cp6（speech 独立连续计数）：`src/vdl2/vdl2_project.py:487-496`——`seg_i` 仅在
    `if speech:` 时自增，字幕 ID 永无跳号；
  - cast 收集同理：`src/vdl2/vdl2_project.py:329-334` 位于 `continue` 之后，只收产段镜的角色，
    无台词镜出场角色不入 `cp2.payload.cast`。

### 机理 + 合成实跑（2026-10-09 本会话，真实投影器函数）

合成包 3 镜、中间镜（shot_02）有角色无 `audio.speech`，直接调用 `build_cp2`/`build_cp6`：

```
cp2 narration_segments: seg_01（第一句）、seg_03（第三句）   ← 镜序编号，跳 seg_02
cp6 subtitle_segments:  seg_01（第一句）、seg_02（第三句）   ← speech 连续计数
同一句台词「第三句台词」: cp2=seg_03 vs cp6=seg_02 → 失配
cast_b（无台词镜出场角色）∉ cp2.cast
```

一旦触发，词锚 `@{…}` 的 segment_id 引用、字幕对账、CP10 字牌对位都可能在 cp2↔cp6 之间错位。

### 未触发实证（本会话实查 `out/m2/*/cp2.json` vs `cp3.json`）

| 线 | cp2 段数 | cp3 镜数 | 段镜相等 |
|---|---|---|---|
| shortdrama_ep01 | 11 | 11 | True |
| marketing_ep01 | 6 | 6 | True |
| comicanime_ep01 | 9 | 9 | True |

逐行一拍一镜形态下段镜相等 ⇔ 每镜均有台词，故双口径现数据下不可区分、未暴露。

### 处置结论

登记为潜伏项，现不改动。下轮数据出现无台词镜时处理，统一口径二选一（建议前者，改动面小）：
cp2 改 speech 连续计数、或 cp6 改镜序跳号并让 cast 收集移到 `continue` 之前；投影器与骨架器同步。

---

## 复核环境注记（如实）

- 本会话实跑时 `src/vdl2/vdl2_project.py`、`vdl2_skeleton.py` 存在未提交工作区改动（notes 元数据
  边界声明 + fingerprint 导入拦截 + 骨架器登记位）；`git diff -U0` 全部 hunk（projector @@ -96/-130/
  -770，skeletonizer @@ -32/-47/-175/-188/-237）不触及 `build_cp2`/`build_cp6`/`hamilton_frames`，
  上述对账数字与已登记逻辑一致。
- comicanime 对账所用包为现场重生成骨架包；仓内 `out/vdl2/skeleton/comicanime_ep01/pkg.yaml`（缺
  `cp2_target_duration_s` 登记位，对账得 92/24 处）与 `examples/vdl2/50_comicanime_ep01.yaml`（缺
  `cp3_shot_scale`，投影 9×CP3.field_missing FAIL）均为相对当前投影器的陈旧包——属复现路径注记，
  不在本登记两缺陷范围内。
- marketing 线往返在当前态整体 exit 1（内容类 8 处：cp2 `cast_refs` 投影保真差异及连带
  upstream_refs/fingerprint，非本登记两缺陷范畴）；其 **cp6 payload 指纹逐位一致**的结论不受影响。
- 引用的 `out/m2/` 三线工件均 git 干净（`git status --porcelain` 对 cited 路径零输出）。

---

## 追记一（2026-10-09 18:5x，主控实跑写死——上文注记的中间态数字已被后续工具修复取代，按「加注不静改」追加而非回改）

上文「复核环境注记」写于工具修复中间态（17:0x）。当日后续修复（两工具新增 `cp2_cast_refs`/
`cp2_props_refs` 登记位回读 + 短剧/漫剧骨架包按终态工具重生）改变了三线对账数字，主控逐一实跑
复核后的**终态口径**如下（`tests/test_vdl2_tools.py` 已按此写死）：

| 线 | 往返 exit | 内容类差异 | 分布 | 说明 |
|---|---|---|---|---|
| shortdrama | 0 | 0 处（元数据 30） | — | cp1/cp2/cp3/cp5/cp6 五件 payload/指纹/upstream_refs 与参照链位级相等 |
| marketing | 0 | 0 处（元数据 30） | — | 原 8 处 cast_refs 保真差异被登记位回读全消；cp6 payload 指纹逐位一致（972211e4…） |
| comicanime | 1 | 15 处（元数据 30） | 仅 cp6 | 即缺陷一的 4 帧错位投影（原 25 处跨 cp2/cp3/cp5/cp6，其中 10 处经登记位回读消除） |

- 缺陷一（comicanime cp6）本身**未修也不修**：exit 1 是该线对已登记参照缺陷的诚实预期，
  `test_vdl2_tools.py::test_projector_comicanime_reconcile_honest_exit1` 锁定该行为。
- 上文注记中「marketing exit 1/8 处」「comicanime 25 处跨 4 CP」及「仓内 comicanime 包陈旧
  （缺 cp2_target_duration_s）」均为中间态陈述：终态下 marketing exit 0，comicanime 内容类
  收敛至 15 处全在 cp6；仓内 comicanime/shortdrama 骨架包已于 18:5x 用终态工具重生
  （`d3_split_declared` 按 cp5 known_cuts 实读：短剧 03/04/05/11 与漫剧 04 为 true）。

## 追记二（2026-10-09 18:5x，主控登记——示例包 40/50 不可被投影器消费，已知形状延伸）

- `examples/vdl2/40_marketing_ep01.yaml` 与 `50_comicanime_ep01.yaml` 各镜 notes 无
  `cp3_shot_scale` 登记位 → `vdl2_project.py --pkg <两包>` 报 6/9 条 `CP3.field_missing` 拒收
  （exit 1）。validate/compile 面不受影响（两包均 PASS / exit 0）。
- 定性：已知注记形状的延伸（登记文件已将 examples/50 此形状列为「复现路径注记」范围），非回归；
  示例包的职责是 validate/compile 示范与回归夹具，投影器消费的是骨架器产物（out/vdl2/skeleton/）。
- 处置：登记备查，不修改两示例包（补登记位会改变示例的示范形态；若下轮需要「示例包→投影」
  全链示范，再立项补位并同步测试）。
