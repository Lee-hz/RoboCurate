#!/usr/bin/env bash
set -euo pipefail
CPU_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CPU_VLM_ROOT="$CPU_PROJECT_ROOT/workspace/local-vlm"
CPU_VLM_BIN="$CPU_VLM_ROOT/llama-b11429/llama-b11429/llama-server"
CPU_VLM_MODEL="$CPU_VLM_ROOT/models/Qwen3-VL-2B-Instruct/Qwen3VL-2B-Instruct-Q4_K_M.gguf"
CPU_VLM_VISION="$CPU_VLM_ROOT/models/Qwen3-VL-2B-Instruct/mmproj-Qwen3VL-2B-Instruct-F16.gguf"
if [[ ! -x "$CPU_VLM_BIN" || ! -f "$CPU_VLM_MODEL" || ! -f "$CPU_VLM_VISION" ]]; then
  printf '%s\n' '请先运行 python3 scripts/setup_local_vlm_cpu.py 完成模型下载与校验。' >&2
  exit 1
fi
printf '%s\n' "$$" > "$CPU_VLM_ROOT/cpu-server.pid"
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
exec nice -n 10 "$CPU_VLM_BIN" \
  --model "$CPU_VLM_MODEL" --mmproj "$CPU_VLM_VISION" \
  --n-gpu-layers 0 --no-mmproj-offload --threads 4 --threads-batch 4 \
  --ctx-size 4096 --parallel 1 --batch-size 256 --ubatch-size 128 \
  --image-max-tokens 256 --reasoning-budget 0 --perf \
  --alias Qwen3-VL-2B-Instruct-Q4_K_M --host 127.0.0.1 --port 8423 \
  --offline --no-webui "$@"
