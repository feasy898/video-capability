# -*- coding: utf-8 -*-
"""cost 包 —— 每 CP 成本台账（SPEC_v2 §0 目录树计划位，P1/M2）。

ledger.py：record/report CLI + append-only JSONL 台账。
四套货币不可换算（白皮书 §5.4 成本记账重写）：跨币种只许同体系比较，
report 只做同 currency 求和，跨币种只列分布不给总额（违反即 exit 3）。
"""
