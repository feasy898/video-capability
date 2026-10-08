# CP11 校验器测试夹具（tests/fixtures/checkpoints/cp11/）

M3 标准：**2 pass + 3 fail**。全部测试片由 `make_fixture.py` 用 ffmpeg 内建
lavfi 源程序生成（零下载素材、零模型调用）；mp4 一律不入 git（见 `.gitignore`，
红线：优先生成器脚本而非二进制入库），克隆后一键再生成；JSON 工件入 git。

| 文件 | 作用 | 期望 |
|---|---|---|
| `make_fixture.py` | 唯一权威生成器（spec 驱动）：一次产出下列 4 个 mp4 + 5 份工件（fingerprint 按 checkpoint.schema.json 口径现算）；重跑字节级复现（ffmpeg 6.1.1 实测） | — |
| `master_9s.mp4` | 主测试片：9s / 360x640 竖版 / 30fps / h264+aac，4 段内建源拼接（smptebars→rgbtestsrc→testsrc2→灰底），硬切点恰在 **2.5 / 5.0 / 7.5s**（实测场景分 0.69/0.81/0.62） | — |
| `pass/cp11_fixture.json` | 切点 2.5/5.0/7.5 **全部登记** known_cuts | `--probe` 判 pass，exit 0 |
| `fail/cp11_fixture_missing_cut.json` | 故意**漏登记 7.5s**（known_cuts=[2.5,5.0]），`all_cuts_registered` 仍谎报 `true`——TASK_v4 M1-W5 要抓的「声明完备、实测漏登记」形态 | `--probe` 下 fail（`known_cuts_registered`）；无 `--probe` 也 fail（`cuts_segments_coherence`：2 点 ≠ 段数 4−1） |
| `master_black_9s.mp4` | 黑场超限片：**全黑 9s**，仅 4.5s 处嵌 1 帧白板作换本锚点（known_cuts 非空铁律与切镜数道需要可复现实测切点，纯全黑无切点会让切镜数道附带误伤、判因不干净）。blackdetect 实测黑场占比 **0.9926 > 0.50** | — |
| `fail/cp11_fixture_black_overrun.json` | 声明侧自认 pass（`black_ratio` 谎报 0.0）——「声明无黑场、实测黑场超限」形态 | `--probe` fail（**`black_ratio_cradle` 独家裁决**）；无 `--probe` 声明道全过（`black_ratio` 声明侧仅 warn 不否决——黑场是实测道） |
| `master_12s.mp4` | 时长超差片：**实际 12s** / 360x640 / 30fps，4 段拼接（rgbtestsrc→testsrc2→灰底→smptebars，源序与主片错开），切点 3.0/6.0/9.0s（实测场景分 0.81/0.62/0.53） | — |
| `fail/cp11_fixture_duration_overrun.json` | 声明 `duration_s=10s`，实测 12s，**偏差 2s > cp11.gate.duration_tol_s=1s** | `--probe` fail（**`duration_tol` 独家裁决**）；无 `--probe` 声明道全过（时长是 ffprobe 实测道） |
| `master_8s_alt.mp4` | 参数错开合规片：**8s / 320x240 横版 / 24fps**，smptehdbars/testsrc 两内建源交替成 4 段（2 段源 + 3 硬切点 2.0/4.0/6.0，实测场景分 0.93/0.95/0.93）；分辨率/帧率/时长/切点与主 pass 全错开 | — |
| `pass/cp11_fixture_alt_format.json` | 3 切点全登记；证明门禁**不吃主夹具参数特例** | `--probe` 判 pass，exit 0 |

## 一键再生成 + 全量验证

```bash
cd overnight/vpipe/tests/fixtures/checkpoints/cp11
python3 make_fixture.py
# 判定数值只从 thresholds.yaml 读（duration_tol_s=1.0 / shot_count_match=true /
# l0_preflight.black_frame_ratio_max=0.50 / known_cuts_tol_s=0.5）
python3 ../../../../src/gate/validate_cp11.py pass/cp11_fixture.json --probe master_9s.mp4          # 期望 exit 0
python3 ../../../../src/gate/validate_cp11.py fail/cp11_fixture_missing_cut.json --probe master_9s.mp4   # 期望 exit 1
python3 ../../../../src/gate/validate_cp11.py fail/cp11_fixture_black_overrun.json --probe master_black_9s.mp4  # 期望 exit 1
python3 ../../../../src/gate/validate_cp11.py fail/cp11_fixture_duration_overrun.json --probe master_12s.mp4    # 期望 exit 1
python3 ../../../../src/gate/validate_cp11.py pass/cp11_fixture_alt_format.json --probe master_8s_alt.mp4       # 期望 exit 0
```

`--probe` 省略路径时取各工件 `payload.master_asset.path`（vpipe 根相对登记，
如 `tests/fixtures/checkpoints/cp11/master_black_9s.mp4`），故从仓根或
overnight/vpipe 下 `--probe`（不带路径）也能解析。全仓回归入口
`bash overnight/vpipe/tests/run_gate_regression.sh` 的 cp11 段即按此
probe 模式实跑（mp4 在场时；缺 mp4 先 `make_fixture.py` 再生并提示 SKIP）。
