# -*- coding: utf-8 -*-
"""VDL v2 骨架器/投影器回归测试（pytest）——把 src/vdl2/vdl2_skeleton.py 与
vdl2_project.py 的往返对账关键行为锁进套件（此前 tests/ 下零引用，全靠人工实跑）。

覆盖（对齐 test_vdl2.py 的既有约定：HERE/VPIPE 路径推导、sys.executable 子进程、
tmp 目录隔离、仓内固定路径零写入、零 API/GPU 调用——两工具均为纯本地文件处理）：
  1. 骨架器往返不丢字段面：shortdrama_ep01 → notes 登记位（cp5_blocking /
     cp1_must_keep / cp2_visual_description 等）出现次数 > 0（F1 修复后的现役行为）；
  2. d3_split_declared 实读：comicanime（cp5 唯一 known_cuts=[3.6] 序列）对应镜
     =true 且 notes 带工件引用；未声明镜（缺键/空表/无序列）=false——预期集合从
     参照 cp5.json 现场实读，不硬编码；
  3. 投影器短剧线往返 exit 0（skeleton → project --reconcile 全链）；
  4. 诚实口径不回退：comicanime --reconcile 必须 exit 1 且输出含 cp6 内容类差异
     明细（已知参照缺陷 build_cp1_cp6.py:493-497 负索引补帧错位，见
     evidence/vdl2-known-defects.md 缺陷一）——防人为放宽对账制造通过；
  5. 登记位护栏：登记值含 ASCII ';' 结构性拒收（REG.semicolon）；
  6. marketing 线往返 exit 1，差异仅限已登记机理（cp2 cast_refs 投影保真及连带
     指纹/upstream 传播；cp6 payload 指纹逐位一致）——evidence/vdl2-known-defects.md
     复核环境注记登记口径，2026-10-09 本会话实跑复核一致后写死。

运行（在 overnight/vpipe/ 下）：
  python -m pytest tests/test_vdl2_tools.py -q
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
VPIPE = HERE.parent
sys.path.insert(0, str(VPIPE / "src" / "vdl2"))

import vdl2_skeleton  # noqa: E402  单元级断言用（_reg/project_shot；模块导入无副作用）

M2 = VPIPE / "out" / "m2"
SKELETON = VPIPE / "src" / "vdl2" / "vdl2_skeleton.py"
PROJECTOR = VPIPE / "src" / "vdl2" / "vdl2_project.py"


def run_tool(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True, cwd=str(VPIPE))


def make_skeleton(line: str, out_pkg: Path) -> dict:
    """对 out/m2/<line> 跑骨架器 → 写 out_pkg（断言 exit 0），返回包 dict。"""
    r = run_tool(SKELETON, "--dir", str(M2 / line), "--out", str(out_pkg))
    assert r.returncode == 0, f"骨架器 exit {r.returncode}: {r.stdout}{r.stderr}"
    assert out_pkg.is_file()
    return yaml.safe_load(out_pkg.read_text(encoding="utf-8"))


def project_and_reconcile(pkg: Path, line: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """投影器 --pkg <pkg> --out-dir <tmp> --reconcile out/m2/<line>。"""
    return run_tool(PROJECTOR, "--pkg", str(pkg), "--out-dir", str(tmp_path / f"{line}_proj"),
                    "--reconcile", str(M2 / line))


def content_paths(stdout: str) -> list:
    """对账输出的内容类差异路径清单（'   [内容类] <path>:' 行）。"""
    return re.findall(r"^\s+\[内容类\] (\S+):$", stdout, re.M)


def declared_shots_from_cp5(line: str) -> set:
    """参照侧实读：cp5.payload.sequences 中 known_cuts 非空的 shot_id 集合。"""
    cp5 = json.loads((M2 / line / "cp5.json").read_text(encoding="utf-8"))
    return {s["shot_id"] for s in cp5["payload"]["sequences"] if s.get("known_cuts")}


# ---------------------------------------------------------------- 1. 骨架器不丢字段面
def test_skeleton_shortdrama_registry_slots_present(tmp_path):
    """shortdrama_ep01：登记位出现次数 > 0（F1 修复后的现役行为——2026-10-09 实测
    cp5_blocking=6/11 镜、cp2_visual_description=11/11、包级登记位寄存首镜）。"""
    pkg = make_skeleton("shortdrama_ep01", tmp_path / "shortdrama_skeleton.yaml")
    assert pkg["work_id"] == "shortdrama_ep01" and len(pkg["shots"]) == 11
    notes = [s.get("notes") or "" for s in pkg["shots"]]
    # 出现次数 > 0（ask 的硬性面）；具体次数为本会话实测值，锁死防静默丢位
    for key, want in (("cp5_blocking", 6), ("cp1_must_keep", 1), ("cp2_visual_description", 11),
                      ("cp2_target_duration_s", 1), ("cp1_theme", 1), ("cp1_selling_point", 1),
                      ("cp1_forbidden_zones", 1), ("cp2_props", 1), ("word_anchor_segment", 11)):
        got = sum(key + "=" in n for n in notes)
        assert got > 0, f"登记位 {key} 出现 0 次：骨架器往返丢字段面（F1 修复回退）"
        assert got == want, f"登记位 {key} 出现 {got} 次 ≠ 实测基线 {want}（登记位静默增损）"
    # shortdrama 参照 cp5 同时覆盖「空表=false」分支（comicanime 只有缺键形态）
    want_declared = declared_shots_from_cp5("shortdrama_ep01")     # {shot_03,04,05,11}
    for s in pkg["shots"]:
        assert s["continuity"]["d3_split_declared"] is (s["shot_id"] in want_declared), s["shot_id"]


# ---------------------------------------------------------------- 2. d3_split_declared 实读
def test_skeleton_d3_split_declared_reads_cp5_known_cuts(tmp_path):
    """comicanime：cp5 序列 known_cuts=[3.6] 的镜（实读=shot_04）d3_split_declared=true
    且 notes 带工件引用；未声明镜（known_cuts 缺键/无 cp5 序列）=false 且不登记。"""
    pkg = make_skeleton("comicanime_ep01", tmp_path / "comicanime_skeleton.yaml")
    assert len(pkg["shots"]) == 9
    want = declared_shots_from_cp5("comicanime_ep01")              # 现场实读 = {shot_04}
    assert want == {"shot_04"}, f"参照 cp5 known_cuts 实读漂移: {want}"
    for s in pkg["shots"]:
        declared = s["continuity"]["d3_split_declared"]
        assert declared is (s["shot_id"] in want), s["shot_id"]
        if declared:
            # notes 工件引用（vdl2_skeleton.py project_shot 的既定记法）
            assert ("d3_split_declared=true(known_cuts=[3.6]←cp5 blocking 工件实值)"
                    in s["notes"]), s["notes"]
        else:
            assert "d3_split_declared=" not in s["notes"], s["shot_id"]


# ---------------------------------------------------------------- 3. 短剧线往返 exit 0
def test_projector_shortdrama_roundtrip_reconcile_exit0(tmp_path):
    """skeleton → project --reconcile out/m2/shortdrama_ep01 全链 returncode 0
    （2026-10-09 实测：内容类 0 处 / 元数据类 30 处）。"""
    pkg = tmp_path / "shortdrama_skeleton.yaml"
    make_skeleton("shortdrama_ep01", pkg)
    r = project_and_reconcile(pkg, "shortdrama_ep01", tmp_path)
    assert r.returncode == 0, f"短剧线往返应 exit 0，实得 {r.returncode}:\n{r.stdout}{r.stderr}"
    assert "内容类差异 0 处" in r.stdout, r.stdout
    # 投影产物落在 tmp（仓内零写入）
    assert (tmp_path / "shortdrama_ep01_proj" / "cp6.json").is_file()
    assert (tmp_path / "shortdrama_ep01_proj" / "project_report.json").is_file()


# ---------------------------------------------------------------- 4. 诚实口径不回退
def test_projector_comicanime_reconcile_honest_exit1(tmp_path):
    """comicanime --reconcile 必须 exit 1（参照链 cp6 负索引补帧缺陷已登记不修，
    evidence/vdl2-known-defects.md 缺陷一；投影侧 hamilton_frames 是正确实现，
    两侧逐位相等不可能达成——有人放宽对账让本测试变绿即为本测试失败）。"""
    pkg = tmp_path / "comicanime_skeleton.yaml"
    make_skeleton("comicanime_ep01", pkg)
    r = project_and_reconcile(pkg, "comicanime_ep01", tmp_path)
    assert r.returncode == 1, f"comicanime 对账必须诚实 exit 1，实得 {r.returncode}:\n{r.stdout}"
    # 总账与分布（终态口径 2026-10-09 18:5x 主控实跑写死：内容类 15 / 元数据类 30，
    # 分布仅 cp6——cp2/cp3/cp5 的差异已被登记位回读消除，剩余即登记缺陷一的 4 帧错位投影）
    assert ("RESULT 内容类差异 15 处 / 元数据类差异 30 处（分布 CP: cp6）"
            in r.stdout), r.stdout
    # cp6 内容类明细=登记缺陷的 4 帧错位投影（15 处；2026-10-09 终态工具实跑逐位一致）
    cp6_sec = r.stdout.split("== cp6 ", 1)[1]
    assert "-- cp6 结论: 内容类 15 处 / 元数据类 6 处" in cp6_sec
    assert ("[内容类] payload.shots[3].duration_frames" in cp6_sec
            and "proj: 101" in cp6_sec and "ref : 100" in cp6_sec), "登记签名 shots[3] 101↔100 缺失"
    assert ("[内容类] payload.shots[4].duration_frames" in cp6_sec
            and "proj: 58" in cp6_sec and "ref : 59" in cp6_sec), "登记签名 shots[4] 58↔59 缺失"
    assert sorted(content_paths(cp6_sec)) == sorted([
        "fingerprint",
        "payload.shots[3].duration_frames", "payload.shots[4].duration_frames",
        "payload.shots[5].duration_frames", "payload.shots[6].duration_frames",
        "payload.shots[4].start_frame", "payload.shots[6].start_frame",
        "payload.subtitle_segments[3].end_s", "payload.subtitle_segments[4].start_s",
        "payload.subtitle_segments[5].end_s", "payload.subtitle_segments[6].start_s",
        "payload.rhythm_segments[3].duration_s", "payload.rhythm_segments[4].duration_s",
        "payload.rhythm_segments[5].duration_s", "payload.rhythm_segments[6].duration_s",
    ]), "cp6 内容类差异面漂移（应=登记缺陷的同一 4 帧错位的 15 处投影）"
    # 判定行：诚实口径话术在位（放宽对账会连带消失）
    assert "判定：存在内容类差异 → 语义等价不成立（诚实口径，不放宽）" in r.stdout


# ---------------------------------------------------------------- 5. 登记位护栏
def test_registry_value_with_semicolon_rejected():
    """登记值含 ASCII ';' 破坏 'skeleton: k=v; k=v' 记法 → 结构性拒收（REG.semicolon，
    vdl2_skeleton.py _reg 的既定行为，不静默截断）。"""
    with pytest.raises(ValueError, match="REG.semicolon"):
        vdl2_skeleton._reg("cp2_visual_description", "画面里有;分号")
    # 拒收沿 project_shot 传播（build_skeleton 据此归 REG.semicolon 结构性错误）
    with pytest.raises(ValueError, match="REG.semicolon"):
        vdl2_skeleton.project_shot(
            {"shot_id": "s", "refs": []}, set(), set(), {}, {}, "x", "9:16", {},
            cp2_vis="含;分号的画面描述", cp5_seq=None)
    # 对照：无分号值正常放行（结构值 compact JSON 承载）
    assert vdl2_skeleton._reg("k", [1, 2.5]) == "k=[1,2.5]"


# ---------------------------------------------------------------- 6. marketing 线往返
def test_projector_marketing_roundtrip_exit0_after_registry_fix(tmp_path):
    """marketing 往返 exit 0（终态口径 2026-10-09 18:5x 主控实跑写死）。
    沿革：17:08 中间态本线 exit 1（内容类 8 处：cp2 cast_refs 投影保真差异及连带
    fingerprint/upstream_refs，根因=骨架器/投影器无 cast_refs 独立承载位）；18:56
    两工具新增 cp2_cast_refs/cp2_props_refs 登记位回读后该类差异全消，对账转
    exit 0 / 内容类 0 处 / 元数据类 30 处。若未来该线回退 exit 1，应查是登记位回读
    被破坏还是参照侧出新缺陷——前者是回归，后者补登记，均不放宽断言。"""
    pkg = tmp_path / "marketing_skeleton.yaml"
    make_skeleton("marketing_ep01", pkg)
    r = project_and_reconcile(pkg, "marketing_ep01", tmp_path)
    assert r.returncode == 0, f"marketing 对账应 exit 0（登记位回读修复后），实得 {r.returncode}:\n{r.stdout}"
    assert "RESULT 内容类差异 0 处 / 元数据类差异 30 处" in r.stdout, r.stdout
    assert "判定：仅元数据类差异（或无差异）" in r.stdout
    # 登记结论仍成立：marketing 参照 builder 无负索引缺陷 → cp6 payload 指纹逐位一致
    assert "[指纹] 投影=972211e4b2f6a32b… 参照=972211e4b2f6a32b… 一致" in r.stdout, \
        "cp6 payload 指纹应逐位一致（marketing 参照 builder 用正确 key，登记口径）"
    # 五件投影工件 payload 层与参照链位级相等（主控 18:2x 独立复核同结论）
    for cp in ("cp1", "cp2", "cp3", "cp5", "cp6"):
        assert f"-- {cp} 结论: 内容类 0 处" in r.stdout, f"{cp} 应内容类 0 处:\n{r.stdout}"
