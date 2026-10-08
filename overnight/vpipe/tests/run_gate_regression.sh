#!/bin/bash
# 全量门禁回归：五校验器 × 示例 × pass/fail 夹具
cd /home/pan-ding/workspace/视频能力
V="overnight/vpipe/src/gate"; E="overnight/vpipe/contracts/v2/examples"; F="overnight/vpipe/tests/fixtures/checkpoints"
pass=0; fail=0
chk() { # $1=描述 $2=预期exit $3=实际exit（必须先存 ec=$? 再调用，防 $(basename) 覆盖 $?）
  if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "  MISMATCH: $1 预期exit=$2 实际=$3"; fi
}
# 示例（cp3 需 script）
python3 $V/validate_cp2.py $E/cp2.json >/dev/null 2>&1; chk "cp2 示例" 0 $?
python3 $V/validate_cp3.py $E/cp3.json --script $E/cp2.json >/dev/null 2>&1; chk "cp3 示例+script" 0 $?
python3 $V/validate_cp5.py $E/cp5.json >/dev/null 2>&1; chk "cp5 示例" 0 $?
python3 $V/validate_cp6.py $E/cp6.json >/dev/null 2>&1; chk "cp6 示例" 0 $?
# cp2 夹具
for f in $F/cp2/pass/*.json; do python3 $V/validate_cp2.py "$f" >/dev/null 2>&1; ec=$?; chk "cp2 pass $(basename $f)" 0 $ec; done
for f in $F/cp2/fail/*.json; do python3 $V/validate_cp2.py "$f" >/dev/null 2>&1; ec=$?; chk "cp2 fail $(basename $f)" 1 $ec; done
# cp3 夹具（fail 组配同名 cp2 script）
for f in $F/cp3/pass/cp3_*.json; do b=$(basename $f .json); s="$F/cp3/pass/${b/cp3_/cp2_}.json"; python3 $V/validate_cp3.py "$f" --script "$s" >/dev/null 2>&1; ec=$?; chk "cp3 pass $b" 0 $ec; done
for f in $F/cp3/fail/cp3_*.json; do b=$(basename $f .json); [ "$b" = "cp3_fail_refs_without_script" ] && continue; s="$F/cp3/fail/${b/cp3_/cp2_}.json"; python3 $V/validate_cp3.py "$f" --script "$s" >/dev/null 2>&1; ec=$?; chk "cp3 fail $b" 1 $ec; done
# 特殊夹具：cp3_fail_refs_without_script 的配对 script 是 cp2_pass.json（非同名前缀）
python3 overnight/vpipe/src/gate/validate_cp3.py $F/cp3/fail/cp3_fail_refs_without_script.json --script $F/cp3/pass/cp2_pass.json >/dev/null 2>&1; ec=$?; chk "cp3 fail refs_without_script+cp2_pass(转pass)" 0 $ec
# cp3 fail-closed 专项：无 script 必拒
for f in $F/cp3/fail/cp3_fail_refs_without_script.json $E/cp3.json; do python3 $V/validate_cp3.py "$f" >/dev/null 2>&1; ec=$?; chk "cp3 无script拒 $(basename $f)" 1 $ec; done
# cp5 夹具
for f in $F/cp5/pass/*.json; do python3 $V/validate_cp5.py "$f" >/dev/null 2>&1; ec=$?; chk "cp5 pass $(basename $f)" 0 $ec; done
for f in $F/cp5/fail/*.json; do python3 $V/validate_cp5.py "$f" >/dev/null 2>&1; ec=$?; chk "cp5 fail $(basename $f)" 1 $ec; done
# cp6 夹具
for f in $F/cp6/pass/*.json; do python3 $V/validate_cp6.py "$f" >/dev/null 2>&1; ec=$?; chk "cp6 pass $(basename $f)" 0 $ec; done
for f in $F/cp6/fail/*.json; do python3 $V/validate_cp6.py "$f" >/dev/null 2>&1; ec=$?; chk "cp6 fail $(basename $f)" 1 $ec; done
# cp11 夹具（--probe 实测道：时长/黑场/切点三道均在实测道裁决——黑场超差/时长超差
# 两件 fail 夹具声明道自认 pass，无 probe 判不了。--probe 省略路径时按各工件
# payload.master_asset.path 解析。mp4 不入 git，缺 mp4 先 cd $F/cp11 && python3 make_fixture.py）
if [ -f "$F/cp11/master_9s.mp4" ]; then
  for f in $F/cp11/pass/*.json; do python3 $V/validate_cp11.py "$f" --probe >/dev/null 2>&1; ec=$?; chk "cp11 pass probe $(basename $f)" 0 $ec; done
  for f in $F/cp11/fail/*.json; do python3 $V/validate_cp11.py "$f" --probe >/dev/null 2>&1; ec=$?; chk "cp11 fail probe $(basename $f)" 1 $ec; done
else
  echo "  SKIP cp11（mp4 未生成：cd $F/cp11 && python3 make_fixture.py）"
fi
# cp12 示例 + 夹具（composite 成片门；注：fail 组 cp12_fail_d_group_auto_veto 同时被 schema
# d_group.warn_only const:true 结构层拦截（双层覆盖，FIXTURES-LAYERING.md 第 2 类），规则门同判）
python3 $V/validate_cp12.py $E/cp12.json >/dev/null 2>&1; chk "cp12 示例" 0 $?
for f in $F/cp12/pass/*.json; do python3 $V/validate_cp12.py "$f" >/dev/null 2>&1; ec=$?; chk "cp12 pass $(basename $f)" 0 $ec; done
for f in $F/cp12/fail/*.json; do python3 $V/validate_cp12.py "$f" >/dev/null 2>&1; ec=$?; chk "cp12 fail $(basename $f)" 1 $ec; done
echo "=============================="
echo "回归结果: 判对 $pass / 错判 $fail"
