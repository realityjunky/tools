#!/usr/bin/env bash
set -euo pipefail

project_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="${project_path}/.venv/lib/python3.12/site-packages/nvidia/cu13/lib:${project_path}/.venv/lib/python3.12/site-packages/torch/lib:${LD_LIBRARY_PATH:-}"
exec "${project_path}/.venv/bin/python" "${project_path}/process_pdf.py" "$@"
