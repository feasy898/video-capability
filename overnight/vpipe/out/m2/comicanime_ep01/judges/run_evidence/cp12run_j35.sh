#!/bin/bash
# cp12_comicanime_j35.sh — J3 omnijev → J5 videochat3（漫剧线 CP12）。
# 红线：只卡0、起跑前复测 <=1024MiB 才发车（等位不抢卡，忙则 60s 后重测）、
# 不 kill 任何进程、不 pip、不下载。外部瞬态任务（如营销线判官）占用时纯等待。
set -u
RUN=/data/night/cp12-comicanime
LOG=$RUN/watch_j35.log
echo "[watch] start $(date +%F %T)" >> "$LOG"

wait_card0() {
  while true; do
    used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0)
    echo "[watch] preflight gpu0_used=${used}MiB (require <=1024) $(date +%F %T)" >> "$LOG"
    if [ "$used" -le 1024 ]; then return 0; fi
    sleep 60
  done
}

wait_card0 || exit 3
cd "$RUN"
CUDA_VISIBLE_DEVICES=0 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  /data/night/venv-judge/bin/python judges_src/omnijev_batch.py \
  --clips-dir "$RUN/clips" --out-dir "$RUN/out/judges/omnijev" --raw-dir "$RUN/out/judges/omnijev/raw" \
  --src-dir /data/night/src/OmniJev-main --ckpt /data/night/models/OmniJev-4B-v1.1 --base /data/night/models/Qwen3.5-4B \
  --meta "$RUN/out/judges/omnijev/run_metadata.json" > "$RUN/logs_j3.txt" 2>&1
rc3=$?
echo "[watch] J3 exit=$rc3 $(date +%F %T)" >> "$LOG"

wait_card0 || { echo "$rc3 ABORT" > "$RUN/J35_EXIT_CODES"; exit 4; }
CUDA_VISIBLE_DEVICES=0 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  /data/night/venv-vc3/bin/python judges_src/videochat3_batch.py \
  --clips-dir "$RUN/clips" --out-dir "$RUN/out/judges/videochat3" --raw-dir "$RUN/out/judges/videochat3/raw" \
  --frames-dir "$RUN/vc3_frames" --model /data/night/models/VideoChat3-4B \
  --fps 0.25 --max-pixels 133072 \
  --meta "$RUN/out/judges/videochat3/run_metadata.json" > "$RUN/logs_j5.txt" 2>&1
rc5=$?
echo "[watch] J5 exit=$rc5 $(date +%F %T)" >> "$LOG"
echo "$rc3 $rc5" > "$RUN/J35_EXIT_CODES"
echo "[watch] all done $(date +%F %T)" >> "$LOG"
