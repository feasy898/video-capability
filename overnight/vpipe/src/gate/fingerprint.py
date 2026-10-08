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
    python3 src/gate/fingerprint.py relink <dir> [--write] [--remap OLD=NEW ...]
                                                               # 重算目录树内全部工件的
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


def cmd_relink(directory: Path, write: bool, remaps: list[str] | None = None) -> int:
    """重算目录树内全部工件的 fingerprint，并按「旧指纹→新指纹」映射重写 upstream_refs。

    目录树语义（2026-10-09 主控修订）：relink 递归遍历 directory 下所有子目录的
    *.json 工件（episode 树形态：根级 cpN.json 聚合件 + cpN/ 子目录逐镜件）。
    引用重指向按**声明指纹匹配**（ref.fingerprint == 目标工件的 declared
    fingerprint）解析到该工件当前的实算指纹——逐镜工件（cp8_shot_01→cp7_shot_01）
    由此无歧义解析；按 cp_id 首匹配对一父多子形态是错的，已废弃。
    payload.source_script_fingerprint 同样参与重指向。

    --remap OLD=NEW（可重复）：显式身份转换。回炉工作流中目标工件的声明指纹可能
    已被更新（旧身份从树内丢失），此时 relink 无法反查旧身份——用本参数把已知的
    旧指纹映射到新指纹（如回炉报告记录的 3ea3bf92…→ca1f0a7e…）。
    """
    files = sorted(directory.rglob("*.json"))
    arts = {}
    skipped = []
    for f in files:
        try:
            a = load(f)
        except Exception:
            skipped.append(f.name)
            continue
        if not isinstance(a, dict) or "payload" not in a:
            skipped.append(f.name)
            continue
        arts[f] = a
    if skipped:
        print(f"跳过非 CP 工件（无 payload/不可解析）: {skipped}")
    # 声明指纹（旧身份）→ 实算指纹（新身份）；声明指纹缺失的工件不入映射
    old_to_new = {}
    for f, a in arts.items():
        declared = a.get("fingerprint")
        computed = compute_fingerprint(a)
        if declared:
            old_to_new.setdefault(declared, computed)
    # 显式身份转换（--remap OLD=NEW）
    for spec in remaps or []:
        if "=" not in spec:
            print(f"--remap 参数缺 '='：{spec!r}（忽略）")
            continue
        old, new = spec.split("=", 1)
        old, new = old.strip(), new.strip()
        if old in old_to_new and old_to_new[old] != new:
            print(f"--remap 冲突：{old[:12]}… 树内已映射到 {old_to_new[old][:12]}…，显式值 {new[:12]}… 不覆盖")
            continue
        old_to_new[old] = new
        print(f"--remap 已登记：{old[:12]}… → {new[:12]}…")
    changed = 0
    unmatched = []
    for f, art in arts.items():
        new_fp = compute_fingerprint(art)
        for r in art.get("upstream_refs") or []:
            if not isinstance(r, dict):
                continue
            fp = r.get("fingerprint")
            if fp in old_to_new:
                if r["fingerprint"] != old_to_new[fp]:
                    r["fingerprint"] = old_to_new[fp]
                    changed += 1
            else:
                unmatched.append(f"{f.name}→{r.get('cp_id')}")
        ssf = (art.get("payload") or {}).get("source_script_fingerprint")
        if ssf and ssf in old_to_new and old_to_new[ssf] != ssf:
            art["payload"]["source_script_fingerprint"] = old_to_new[ssf]
            changed += 1
        if art.get("fingerprint") != new_fp:
            art["fingerprint"] = new_fp
            changed += 1
    if not write:
        for f in sorted(arts):
            print(f"[dry-run] {f.relative_to(directory)}: fingerprint={compute_fingerprint(arts[f])[:16]}…")
        print(f"[dry-run] 将改动 {changed} 处（--write 落盘）")
        return 0
    for f, a in arts.items():
        f.write_text(json.dumps(a, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已重算并落盘 {len(arts)} 个工件（目录树 {directory}），改动 {changed} 处")
    if unmatched:
        print(f"未匹配引用（声明指纹不在树内且无 --remap，保持原值）: {unmatched}")
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
        rest = argv[3:]
        remaps = [a[len("--remap="):] for a in rest if a.startswith("--remap=")]
        return cmd_relink(path, write="--write" in rest, remaps=remaps)
    print(f"未知命令: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
