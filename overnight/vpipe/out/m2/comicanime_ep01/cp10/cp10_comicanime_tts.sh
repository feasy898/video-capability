#!/bin/bash
# cp10_comicanime_tts.sh — CP10 漫剧线 9 句 TTS（StepFun stepaudio-2.5-tts，并行+失败重试）。
# 红线：真实调用 ≤12 次（9 首跑 + ≤3 重试）；key 由 api_keys.env 服务端注入零回显零落盘；
# 输出只落 /data/night/cp10-comicanime/；失败逐句如实记 launch.log 不冒充。
set -u
RUN=/data/night/cp10-comicanime
REPO=/data/night/g01-rerun/video-capability/overnight/vpipe
LOG=$RUN/launch.log
mkdir -p "$RUN"
: > "$LOG"

set -a
. /data/night/g01-rerun/video-capability/overnight/secrets/api_keys.env
set +a

run_one() {
  local sid="$1" text="$2"
  python3 "$REPO/src/tts.py" \
    --text "$text" \
    --out "$RUN/tts_${sid}.wav" \
    --voice-id cixingnansheng \
    --model stepaudio-2.5-tts \
    --response-format wav \
    --timeout 120 >> "$RUN/tts_${sid}.log" 2>&1
  echo "$sid rc=$?" >> "$LOG"
}

run_one seg_01 '雨夜，沈记面馆的灯还亮着。推门进来的人，十年没回来过了。' &
run_one seg_02 '老板，一碗头汤面。汤宽，面硬，葱花最后放。' &
run_one seg_03 '头汤只卖一碗。这规矩，十年前就断了。' &
run_one seg_04 '沈聿下面收汤，动作和十年前教他的一分不差。' &
run_one seg_05 '锅还是那口锅，可惜姓了沈。' &
run_one seg_06 '这手法……你到底跟谁学的？' &
run_one seg_07 '跟一个老师傅。他说，味道在，人就还在。' &
run_one seg_08 '师弟？！那道门是爹锁的，不关我的事！' &
run_one seg_09 '面凉了，雨声里谁都没先动筷。' &
wait

# ---- 失败重试（≤3 次，总量红线 12）----
RETRIED=0
for sid in seg_01 seg_02 seg_03 seg_04 seg_05 seg_06 seg_07 seg_08 seg_09; do
  if ! grep -q "^${sid} rc=0$" "$LOG"; then
    if [ "$RETRIED" -ge 3 ]; then echo "retry-budget-exhausted (>$((9+RETRIED)) calls)" >> "$LOG"; break; fi
    RETRIED=$((RETRIED+1))
    case "$sid" in
      seg_01) T='雨夜，沈记面馆的灯还亮着。推门进来的人，十年没回来过了。';;
      seg_02) T='老板，一碗头汤面。汤宽，面硬，葱花最后放。';;
      seg_03) T='头汤只卖一碗。这规矩，十年前就断了。';;
      seg_04) T='沈聿下面收汤，动作和十年前教他的一分不差。';;
      seg_05) T='锅还是那口锅，可惜姓了沈。';;
      seg_06) T='这手法……你到底跟谁学的？';;
      seg_07) T='跟一个老师傅。他说，味道在，人就还在。';;
      seg_08) T='师弟？！那道门是爹锁的，不关我的事！';;
      seg_09) T='面凉了，雨声里谁都没先动筷。';;
    esac
    mv "$RUN/tts_${sid}.log" "$RUN/tts_${sid}.try1.log" 2>/dev/null || true
    run_one "$sid" "$T"
    echo "retry $sid rc-recorded" >> "$LOG"
  fi
done

echo "TTS_ALL_DONE total_calls=$((9+RETRIED))" >> "$LOG"
cat "$LOG"
