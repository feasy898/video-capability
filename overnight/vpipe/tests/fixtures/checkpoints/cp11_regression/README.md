# CP11 合成层像素级回归（tests/fixtures/checkpoints/cp11_regression/）

TASK_v4 M1-W5 验收（白皮书 §3 CP11 + §4 T0）：**3 个用例同输入各跑两遍，6 次全部
exit 0 且 master.mp4 md5 两两一致**；case 声明 `cp11` 块的另过
`validate_cp11.py --probe` 实测门。素材全部 ffmpeg lavfi 内建源程序生成——零模型
调用、零下载；mp4 产物落 `out/`（本目录 `.gitignore` 排除，不入 git）。

| 文件 | 作用 | 期望 |
|---|---|---|
| `../../src/gate/synth.py` | 合成器：`--case <case.json> --out <dir>`，ffmpeg 子进程确定性合成（concat / xfade / drawtext / ass 烧录 / loudnorm 两遍归一），产 `master.mp4` + `synth_meta.json`（每步 argv/退出码/md5）+ `md5.txt`；case 声明 `cp11` 块时另产 `cp11_artifact.json` | 同输入同机重跑 master.mp4 md5 必须一致 |
| `case1_solid_concat_drawtext.json` | 用例 1：2 段纯色（亮黄 0xEEDD22 → 暗靛 0x222266，Luma 205→42 保证 select 场景分 >0.3）concat + 1 条 drawtext 字幕，9s，切点 4.5s | 2 遍 md5 一致 + CP11 门 pass |
| `case2_testsrc_ass.json` | 用例 2：testsrc→rgbtestsrc→testsrc2 三段 concat + ASS 字幕烧录（libass + DejaVu Sans），9s，切点 3.0/6.0s | 2 遍 md5 一致 + CP11 门 pass |
| `case3_xfade_loudnorm.json` | 用例 3：testsrc2 4s + 纯色 4s，xfade 过渡成片 6s（重叠 2s）+ 音轨 loudnorm 两遍归一（I=-16/TP=-1.5/LRA=11） | 2 遍 md5 一致；CP11 门**不适用**（xfade 无硬切缝，见下「诚实边界」） |
| `run_regression.py` | 验收驱动：每用例 ×2 遍 synth → exit 0 + `md5.txt` 逐字节 diff + master md5 比对 + validate_cp11 --probe；汇总写 evidence JSON | exit 0 = 全部通过 |
| `out/` | 产物（mp4/工件/meta），程序生成不入 git | 克隆后一键再生成 |

## 一键验收（TASK_v4 §3.1 M1-W5）

```bash
cd overnight/vpipe/tests/fixtures/checkpoints/cp11_regression
python3 run_regression.py            # 缺省：产物 → out/，汇总 → <仓根>/evidence/synth-regression-20261008.json
```

单独复跑某用例（比对两遍 md5）：

```bash
CASE=case2_testsrc_ass
python3 ../../src/gate/synth.py --case $CASE.json --out /tmp/r1
python3 ../../src/gate/synth.py --case $CASE.json --out /tmp/r2
diff /tmp/r1/md5.txt /tmp/r2/md5.txt && echo DETERMINISTIC
```

## 确定性口径（诚实边界）

- **承诺范围**：同机 + 同 ffmpeg 版本 + 固定参数（`threads=1` 钉死线程数，消除
  x264 帧级并行对宿主核数的耦合）+ lavfi 程序源（零墙钟注入）→ master.mp4 字节级
  一致。本机 ffmpeg 6.1.1 实测 mov muxer 不写墙钟 creation_time，无需 bitexact。
  跨机/跨版本不承诺（编码器版本差异）——与 `validate_cp11.py --self-check` 口径一致。
- **比对载体**：`md5.txt`（md5sum 格式，只含确定性产物 master.mp4 与 .ass、只有
  相对文件名）——TASK_v4 §4 M1 验收脚本 `diff md5.txt` 口径。
  `synth_meta.json` / `cp11_artifact.json` 含时间戳与绝对路径，天然跨遍不同，
  **不入比对**。
- **字幕文本限安全 ASCII 子集**（不含 `\ ' : ; , [ ] %`）：ffmpeg 滤图对选项值有
  两层转义语义，夹具只放行无歧义字符；全量转义器归 M2。ASS 文本用 DejaVu Sans
  （无 CJK 字形），中文逐字硬校验归 CP10 门、像素级字幕道归 CP12 D 组/人工
  （白皮书 §4 T0 边界）。
- **case3 与 CP11 门禁**：xfade 过渡 ≠ 硬切拼接缝，`known_cuts` 登记铁律与切镜数
  等式对其无对象；校验器要求 known_cuts 非空数组，空登记册必 fail——故 case3 不
  声明 `cp11` 块、不产工件，其确定性由 md5 比对覆盖（evidence 里如实记
  `not_applicable` + 理由）。响度归一道（loudnorm 两遍）由 synth 的测量遍+
  linear 归一遍两步 ffmpeg 构成，实测入 `synth_meta.json.steps`。

## 产物树（run_regression.py 运行后）

```
out/<case>/run{1,2}/
  master.mp4            成片（md5 比对对象）
  md5.txt               确定性产物清单（跨遍 diff 载体）
  synth_meta.json       每步 ffmpeg argv/rc/stderr 尾 + master md5/sha256 + ffprobe 复测
  <case_id>.ass         仅 case2（ass 模式）
  cp11_artifact.json    仅 case1/case2（挂 validate_cp11.py 实测门）
```
