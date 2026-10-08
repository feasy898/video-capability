#!/usr/bin/env python3
"""fingerprint.py — 工件内容指纹计算与核验（v4 CP 契约的执行工具）

算法（唯一口径，与 contracts/v2/checkpoint.schema.json definitions.fingerprint
的 description 一致）：
    fingerprint = sha256( canonical_json(payload) )
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode("utf-8")
即：**只对 payload 做规范化 JSON 的 sha256**；schema_version/cp_id/fingerprint/
upstream_refs/status/gate 等信封字段不参与（信封变、内容不变 = 指纹不变）。

失效传播语义（白皮书 §5.4）：上游工件 payload 变更 → 其 fingerprint 变更 →
所有 upstream_refs 指向它的下游工件失效（缓存/重算判定以此为准）。

CLI：
    python3 src/gate/fingerprint.py compute <artifact.json>     # 打印计算值
    python3 src/gate/fingerprint.py verify <artifact.json>      # 与声明值比对，exit 0/1
    python3 src/gate/fingerprint.py relink <dir> [--write]      # 重算目录内全部工件的
                                                               # fingerprint 与 upstream_refs
                                                               # （--write 才落盘，否则 dry-run）
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def canonical(obj) -> str:
    """规范化 JSON：键排序、紧凑分隔符、保留 UTF-8 字符（不转义）。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_fingerprint(artifact: dict) -> str:
    """工件指纹 = payload 规范化 JSON 的 sha256（十六进制小写）。"""
    payload = artifact.get("payload")
    if payload is None:
        raise ValueError("工件缺少 payload")
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_compute(path: Path) -> int:
    art = load(path)
    print(compute_fingerprint(art))
    return 0


def cmd_verify(path: Path) -> int:
    art = load(path)
    declared = art.get("fingerprint", "")
    actual = compute_fingerprint(art)
    if declared == actual:
        print(f"OK {path.name}: fingerprint 与声明一致 ({actual[:16]}…)")
        return 0
    print(f"MISMATCH {path.name}: 声明 {declared[:16]}… != 实算 {actual[:16]}…")
    return 1


def cmd_relink(directory: Path, write: bool) -> int:
    """重算目录内全部 *.json 工件的 fingerprint，并按实算值重写 upstream_refs 引用。

    upstream_refs 条目形如 {cp_id, fingerprint}——这里按「被引用工件的主名/id」匹配
    目录内其它工件的实算指纹。匹配不到的引用保持原值并在输出中标注。
    """
    files = sorted(directory.glob("*.json"))
    arts = {}
    skipped = []
    for f in files:
        a = load(f)
        if not isinstance(a, dict) or "payload" not in a:
            skipped.append(f.name)
            continue
        arts[f.name] = a
    if skipped:
        print(f"跳过非 CP 工件（无 payload）: {skipped}")
    # 主名（如 cp2.json / cp3.json）→ 实算指纹
    fp_by_stem = {name: compute_fingerprint(a) for name, a in arts.items()}
    # 兼容按 work_id 引用：建立 work_id → 指纹
    fp_by_work = {}
    for a in arts.values():
        wid = (a.get("payload") or {}).get("work_id")
        if wid:
            fp_by_work.setdefault(wid, compute_fingerprint(a))
    changed = 0
    unmatched = []
    for name, art in arts.items():
        new_fp = fp_by_stem[name]
        old_fp = art.get("fingerprint")
        refs = art.get("upstream_refs") or []
        for r in refs:
            if not isinstance(r, dict):
                continue
            # 引用目标：优先按 cp_id+work_id 同链匹配
            cp = r.get("cp_id")
            hit = None
            for other_name, other in arts.items():
                if other_name == name:
                    continue
                if other.get("cp_id") == cp:
                    hit = fp_by_stem[other_name]
                    break
            if hit is None:
                unmatched.append(f"{name}→{cp}")
                continue
            if r.get("fingerprint") != hit:
                r["fingerprint"] = hit
                changed += 1
        if old_fp != new_fp:
            art["fingerprint"] = new_fp
            changed += 1
    if not write:
        for name, a in sorted(arts.items()):
            print(f"[dry-run] {name}: fingerprint={fp_by_stem[name][:16]}…")
        print(f"[dry-run] 将改动 {changed} 处（--write 落盘）")
        return 0
    for f in files:
        if f.name not in arts:
            continue  # 跳过的非 CP 工件原样不动
        f.write_text(json.dumps(arts[f.name], ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print(f"已重算并落盘 {len(files)} 个工件，改动 {changed} 处")
    if unmatched:
        print(f"未匹配引用（保持原值）: {unmatched}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, path = argv[1], Path(argv[2])
    if cmd == "compute":
        return cmd_compute(path)
    if cmd == "verify":
        return cmd_verify(path)
    if cmd == "relink":
        return cmd_relink(path, write="--write" in argv[3:])
    print(f"未知命令: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
