# CP11 校验器测试夹具（tests/fixtures/checkpoints/cp11/）

| 文件 | 作用 | 期望 |
|---|---|---|
| `make_fixture.py` | 唯一权威生成器：ffmpeg 内建 lavfi 源（smptebars/rgbtestsrc/testsrc2/灰底）拼 9s/360x640/30fps/h264+aac 测试片，硬切点恰在 **2.5 / 5.0 / 7.5s**；并写 pass/fail 两份工件（fingerprint 按 checkpoint.schema.json 口径现算） | — |
| `master_9s.mp4` | 测试片本体。**不入 git**（见 `.gitignore`，红线：优先生成器脚本而非二进制入库），克隆后一键再生成 | `make_fixture.py` 重跑字节级复现（ffmpeg 6.1.1 实测二遍 md5 一致） |
| `pass/cp11_fixture.json` | 切点 2.5/5.0/7.5 **全部登记** known_cuts | `validate_cp11.py` 判 pass，exit 0 |
| `fail/cp11_fixture_missing_cut.json` | 故意**漏登记 7.5s**（known_cuts=[2.5,5.0]），`all_cuts_registered` 仍谎报 `true`——TASK_v4 M1-W5 要抓的「声明完备、实测漏登记」形态 | `--probe` 下 fail（exit 1，`known_cuts_registered`）；无 `--probe` 也 fail（`cuts_segments_coherence`：2 点 ≠ 段数 4−1） |

## 一键再生成 + 验证

```bash
cd overnight/vpipe/tests/fixtures/checkpoints/cp11
python3 make_fixture.py
python3 ../../../../src/gate/validate_cp11.py pass/cp11_fixture.json --probe master_9s.mp4   # 期望 exit 0
python3 ../../../../src/gate/validate_cp11.py fail/cp11_fixture_missing_cut.json --probe master_9s.mp4  # 期望 exit 1
```

工件内的 `master_asset.path` 登记为 vpipe 根相对路径
`tests/fixtures/checkpoints/cp11/master_9s.mp4`，故从仓根直接
`--probe`（不带路径）也能解析。
