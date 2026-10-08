# -*- coding: utf-8 -*-
"""vpipe gate 包——五段流水线判定器（TASK_v4 §3.1：按 CP 分派门禁类型）。

每个 validate_cpN.py 是一个自包含 CLI 校验器：吃一个 CP 工件 JSON + --thresholds
（eval/thresholds.yaml），输出 JSON verdict 到 stdout，exit 0=pass / 1=fail / 2=error。
一切判定数值只从 thresholds.yaml 读（schema 红线①：判定数值不进契约不进代码）。
"""
