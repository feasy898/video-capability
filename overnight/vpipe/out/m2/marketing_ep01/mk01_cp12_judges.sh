#!/bin/bash
# mk01_cp12_judges.sh — 营销线 EP01 CP12 三判官（GPU 机执行）。
# 红线：只卡 0、起跑前复测 ≤1024MiB（漫剧线可能在跑，等位不抢）、不 kill 任何进程；
#       J1 key 由 ZHIPU_API_KEY 服务端 env 注入零回显零落盘。
set -u
RUN=/data/night/mk01-cp12
LOG=$RUN/watch.log
JS=/data/night/cp12-run2/judges_src          # 与本仓 judges_src md5 一致（2026-10-09 核）
echo "[watch] start $(date +%F %T)" >> "$LOG"

# ---------- J1 glm8（API，无 GPU） ----------
export BIGMODEL_API_KEY="$(grep '^ZHIPU_API_KEY=' /data/night/g01-rerun/video-capability/overnight/secrets/api_keys.env | head -1 | cut -d= -f2-)"
if [ -z "$BIGMODEL_API_KEY" ]; then echo "[watch] ABORT J1 no key" >> "$LOG"; exit 3; fi
python3 "$JS/glm8_batch.py" \
  --frames-root "$RUN/frames" \
  --manifest "$RUN/manifest.json" \
  --out-dir "$RUN/out/judges/glm8" \
  --raw-dir "$RUN/out/judges/glm8/raw" \
  --meta "$RUN/out/judges/glm8/run_metadata.json" \
  --workers 2 > "$RUN/logs_j1.txt" 2>&1
rc1=$?
echo "[watch] J1 exit=$rc1 $(date +%F %T)" >> "$LOG"

# ---------- GPU0 复测（≤1024MiB 才起跑） ----------
used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0)
echo "[watch] preflight J3 gpu0_used=${used}MiB (require <=1024)" >> "$LOG"
if [ "$used" -gt 1024 ]; then echo "[watch] ABORT J3 preflight fail" >> "$LOG"; echo "$rc1 ABORT ABORT" > "$RUN/EXIT_CODES"; exit 4; fi
CUDA_VISIBLE_DEVICES=0 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  /data/night/venv-judge/bin/python "$JS/omnijev_batch.py" \
  --clips-dir "$RUN/clips" --out-dir "$RUN/out/judges/omnijev" --raw-dir "$RUN/out/judges/omnijev/raw" \
  --src-dir /data/night/src/OmniJev-main --ckpt /data/night/models/OmniJev-4B-v1.1 --base /data/night/models/Qwen3.5-4B \
  --meta "$RUN/out/judges/omnijev/run_metadata.json" > "$RUN/logs_j3.txt" 2>&1
rc3=$?
echo "[watch] J3 exit=$rc3 $(date +%F %T)" >> "$LOG"

used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0)
echo "[watch] preflight J5 gpu0_used=${used}MiB (require <=1024)" >> "$LOG"
if [ "$used" -gt 1024 ]; then echo "[watch] ABORT J5 preflight fail (J3 rc=$rc3)" >> "$LOG"; echo "$rc1 $rc3 ABORT" > "$RUN/EXIT_CODES"; exit 5; fi
CUDA_VISIBLE_DEVICES=0 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  /data/night/venv-vc3/bin/python "$JS/videochat3_batch.py" \
  --clips-dir "$RUN/clips" --out-dir "$RUN/out/judges/videochat3" --raw-dir "$RUN/out/judges/videochat3/raw" \
  --frames-dir "$RUN/vc3_frames" --model /data/night/models/VideoChat3-4B \
  --fps 0.25 --max-pixels 133072 \
  --meta "$RUN/out/judges/videochat3/run_metadata.json" > "$RUN/logs_j5.txt" 2>&1
rc5=$?
echo "[watch] J5 exit=$rc5 $(date +%F %T)" >> "$LOG"
echo "$rc1 $rc3 $rc5" > "$RUN/EXIT_CODES"
echo "[watch] all done $(date +%F %T)" >> "$LOG"
