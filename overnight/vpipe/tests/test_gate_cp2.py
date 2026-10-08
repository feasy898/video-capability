#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_gate_cp2.py — CP2 rule 门禁校验器自测（M1）。

四件事，全过才 exit 0：
1. examples/cp2.json 过 checkpoint.schema 且 validate_cp2 判 pass（exit 0）；
2. tests/fixtures/checkpoints/cp2/pass/ 全部判 pass（exit 0）；
3. tests/fixtures/checkpoints/cp2/fail/ 全部判 fail（exit 1），且
   —— 关键前提 —— 全部夹具（含负例）先过 checkpoint.schema：
   负例被拦只能因 rule 门，不能因形状（否则证明不了 rule 门有效）；
4. 读取/用法错误路径 exit 2（工件不存在 / 工件非 JSON / thresholds 不存在）。

用法：python3 tests/test_gate_cp2.py
依赖：标准库 + PyYAML（被测件）+ jsonschema（仅本测试用，红线白名单内）。
"""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

VPIPE = Path(__file__).resolve().parents[1]
SCHEMA = VPIPE / "contracts" / "v2" / "checkpoint.schema.json"
VALIDATOR = VPIPE / "src" / "gate" / "validate_cp2.py"
CP2DIR = VPIPE / "tests" / "fixtures" / "checkpoints" / "cp2"
EXAMPLE = VPIPE / "contracts" / "v2" / "examples" / "cp2.json"

failures: list[str] = []


def note(ok: bool, msg: str) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def run_validator(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *argv],
        capture_output=True, text=True,
    )


def schema_ok(path: Path, validator) -> bool:
    try:
        validator.validate(json.loads(path.read_text(encoding="utf-8")))
        return True
    except Exception as e:  # jsonschema.ValidationError / JSON 解析错误
        print(f"         ({type(e).__name__}: {str(e).splitlines()[0][:120]})")
        return False


def main() -> int:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)

    print(f"== CP2 门禁自测（校验器 {VALIDATOR.name}，阈 {SCHEMA.name}）==")

    # 1. 官方示例必须 pass
    print("[1] examples/cp2.json")
    note(schema_ok(EXAMPLE, validator), "过 checkpoint.schema（cp2_script 分支）")
    p = run_validator(str(EXAMPLE))
    note(p.returncode == 0, f"validate_cp2 判 pass（exit 0，实得 {p.returncode}）")

    # 2+3. 夹具：pass/ 全过、fail/ 全拦，且全部夹具形状合法
    for group, want in (("pass", 0), ("fail", 1)):
        print(f"[2/3] fixtures/checkpoints/cp2/{group}/（期望 exit {want}）")
        for f in sorted((CP2DIR / group).glob("*.json")):
            name = f.name
            note(schema_ok(f, validator), f"{name}: 过 checkpoint.schema（负例形状合法才作数）")
            p = run_validator(str(f))
            note(p.returncode == want, f"{name}: validate_cp2 exit {want}（实得 {p.returncode}）")
            if group == "fail" and p.returncode == 1:
                verdict = json.loads(p.stdout)
                bad = [c["name"] for c in verdict["checks"] if not c["ok"]]
                note(len(bad) == 1,
                     f"{name}: 恰好只拦一项 {bad}（单缺陷归因，实得 {bad}）")
                print(f"         原因: {next(c['detail'] for c in verdict['checks'] if not c['ok'])[:160]}")

    # 4. 读取/用法错误 → exit 2
    print("[4] 读取/用法错误路径（期望 exit 2）")
    p = run_validator(str(VPIPE / "no_such_artifact.json"))
    note(p.returncode == 2, f"工件不存在 → exit 2（实得 {p.returncode}）")
    p = run_validator("/dev/null")  # 空文件 = 非 JSON
    note(p.returncode == 2, f"工件非 JSON → exit 2（实得 {p.returncode}）")
    p = run_validator(str(EXAMPLE), "--thresholds", str(VPIPE / "no_such_thresholds.yaml"))
    note(p.returncode == 2, f"thresholds 不存在 → exit 2（实得 {p.returncode}）")

    print("== 汇总 ==")
    if failures:
        print(f"FAIL（{len(failures)} 项未过，见上）")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
