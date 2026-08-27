#!/usr/bin/env bash
set -euo pipefail

project_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
model_path="${OVIS_MODEL_PATH:-${project_path}/model/OvisOCR2}"
server_host="${OVIS_VLLM_HOST:-0.0.0.0}"
server_port="${OVIS_VLLM_PORT:-8001}"
api_key="${OVIS_VLLM_API_KEY:?Set OVIS_VLLM_API_KEY before starting the local OvisOCR2 server}"

export LD_LIBRARY_PATH="${project_path}/.venv/lib/python3.12/site-packages/nvidia/cu13/lib:${project_path}/.venv/lib/python3.12/site-packages/torch/lib:${LD_LIBRARY_PATH:-}"
exec "${project_path}/.venv/bin/vllm" serve "$model_path" \
  --host "$server_host" \
  --port "$server_port" \
  --api-key "$api_key" \
  --served-model-name ovisocr2 \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.8 \
  --gdn-prefill-backend triton
