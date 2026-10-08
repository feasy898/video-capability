#!/bin/bash
# mk01_cp10_tts.sh — 营销线 EP01 CP10 配音合成（StepFun stepaudio-2.5-tts，GPU 机执行）。
# 红线：key 经 --env-file 内存态读取零回显零落盘；TTS ≤8 次（本批 6 句 + 最多 1 轮失败重试）
# 并行化应对 ~122s/句延迟（短剧线 CP10 实测 122.7s/次）。
set -u
RUN=/data/night/mk01-cp10
REPO=/data/night/g01-rerun/video-capability
KEYS=$REPO/overnight/secrets/api_keys.env
cd "$RUN"
export PYTHONIOENCODING=utf-8

declare -A TEXT
TEXT[seg_01]="卧室睡不好？试试这瓶雪松香薰，无火无烟，开着就能睡。"
TEXT[seg_02]="植物精油，尾调雪松，越闻越安神。"
TEXT[seg_03]="一瓶扩香约六十天，睡前拨拨藤条，香感就回来。"
TEXT[seg_04]="床头摆一瓶，像把雪松林搬进卧室。"
TEXT[seg_05]="玻璃瓶身配木底座，摆哪都好看。"
TEXT[seg_06]="想要的点置顶链接，今晚下单。"

run_one() {
  local sid=$1
  python3 "$REPO/overnight/vpipe/src/tts.py" \
    --text "${TEXT[$sid]}" \
    --out "$RUN/tts_${sid}.wav" \
    --voice-id cixingnansheng \
    --env-file "$KEYS" \
    --timeout 300 > "$RUN/tts_${sid}.log" 2>&1
  echo "$sid rc=$?"
}

echo "[launch] start $(date +%F %T)" >> "$RUN/launch.log"
for sid in seg_01 seg_02 seg_03 seg_04 seg_05 seg_06; do
  run_one "$sid" &
done
wait

# 失败重试（≤1 轮/句；重试调用计入 TTS 红线 ≤8：6+2=8 封顶）
for sid in seg_01 seg_02 seg_03 seg_04 seg_05 seg_06; do
  if ! grep -q "status.: .ok" "$RUN/tts_${sid}.meta.json" 2>/dev/null; then
    echo "[retry] $sid" >> "$RUN/launch.log"
    cp "$RUN/tts_${sid}.log" "$RUN/tts_${sid}.retry0.log" 2>/dev/null
    run_one "$sid" >> "$RUN/launch.log"
  fi
done

echo "[launch] done $(date +%F %T)" >> "$RUN/launch.log"
for sid in seg_01 seg_02 seg_03 seg_04 seg_05 seg_06; do
  st=$(python3 -c "import json;print(json.load(open('$RUN/tts_${sid}.meta.json')).get('status'))" 2>/dev/null || echo missing)
  echo "$sid status=$st" >> "$RUN/launch.log"
done
