# OvisOCR2 deployment readiness

Date: 2026-08-23  
Model source: [ATH-MaaS/OvisOCR2 on ModelScope](https://modelscope.cn/models/ATH-MaaS/OvisOCR2)

## Decision

Use a fresh Python 3.12 environment with the model card's exact `vllm==0.22.1` and `Pillow`. Use the CUDA 12.9 PyTorch/vLLM backend. Do not upgrade the system CUDA toolkit to CUDA 13: the workstation already has CUDA 12.9, and the vLLM 0.22.1 installation documentation describes precompiled CUDA 12.9 binaries.

The installation is currently blocked by a host NVIDIA driver/library mismatch. The model must not be downloaded or configured until `nvidia-smi` succeeds.

## Required software

| Component | Required or selected version | Evidence and workstation state |
| --- | --- | --- |
| Operating system | Linux | vLLM 0.22.1 documents Linux support; this workstation is Ubuntu 22.04.5 LTS. |
| Python | 3.10–3.13 supported; select 3.12 | vLLM documents 3.10–3.13 and its package metadata requires `>=3.10,<3.15`. Python 3.12.13 is already available through `uv`. |
| vLLM | `0.22.1` exactly | Required by the OvisOCR2 model card. |
| Image input | `Pillow` | Required by the OvisOCR2 model card. |
| PyTorch stack | Let vLLM resolve `torch==2.11.0`, `torchvision==0.26.0`, and `torchaudio==2.11.0` | These are vLLM 0.22.1 package dependencies. Do not mix them with an existing PyTorch installation. |
| Transformers | `>=4.56.0`, excluding `5.0.*` through `5.4.*` and `5.5.0` | This is vLLM 0.22.1's dependency constraint; the model config identifies `Qwen3_5ForConditionalGeneration` and was created with a Transformers 4.57 development baseline. |
| CUDA | CUDA 12.9 runtime/backend | vLLM 0.22.1 documents CUDA 12.9 precompiled binaries. The workstation has CUDA SDK `12.9.20250426` and `nvcc` `12.9.41`. |
| NVIDIA driver | Linux driver >=550.54.14 for CUDA 12.9 compatibility; retain the 580 branch | NVIDIA's CUDA 12.9 release notes give the minimum. The workstation has 580.173.02 packages, but the running kernel module is stale at 580.159.03. |

The model config is natively supported by the vLLM 0.22.1 Qwen3.5 multimodal architecture. The RTX 4060 Ti is compute capability 8.9, above vLLM's published NVIDIA minimum of 7.5.

## Workstation audit

- GPU: NVIDIA GeForce RTX 4060 Ti at PCIe address `0000:73:00.0`.
- Driver packages: `580.173.02`; loaded kernel module: `580.159.03`.
- Host error: `nvidia-smi` reports `Failed to initialize NVML: Driver/library version mismatch`.
- CUDA executable: `/usr/local/cuda-12.9/bin/nvcc`.
- Global CUDA symlink: `/usr/local/cuda` currently resolves to `/usr/local/cuda-12.4`; use `/usr/local/cuda-12.9` explicitly for any source-build environment.
- Python: system Python 3.10.12; managed Python 3.12.13 is already installed.
- Capacity: 62 GiB RAM and 88 GiB free disk space. Swap is fully occupied, so avoid unrelated memory-heavy work during installation.

## Required repair gate

Root access is required for the host driver repair. Run this on the workstation, then return to the deployment session:

```bash
sudo apt-get update
sudo apt-get install --reinstall nvidia-driver-580 nvidia-utils-580 nvidia-dkms-580 linux-modules-nvidia-580-6.8.0-124-generic
sudo reboot
```

Ubuntu names the NVIDIA kernel-module package for a specific kernel; there is no generic package named `linux-modules-nvidia-580`.

After reboot, verify:

```bash
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,cuda_version,memory.total,memory.free --format=csv,noheader
```

If `nvidia-smi` still reports a mismatch, stop there; do not install vLLM or download OvisOCR2 until the package and loaded-module versions agree.

## Installation approach after the gate

Use a new environment and select the CUDA 12.9 backend rather than reusing one of the existing workspace environments:

```bash
uv venv --python 3.12 Ovis/.venv
VIRTUAL_ENV=Ovis/.venv uv pip install "vllm==0.22.1" pillow --torch-backend=cu129
```

The installed vLLM wheel requires its bundled CUDA 13 runtime directory at process startup. Use `Ovis/run_ocr.sh`, which adds that directory and the Torch library directory to `LD_LIBRARY_PATH` before launching `Ovis/run_ocr.py`.

The model card's runtime settings are `tensor_parallel_size=1`, `gpu_memory_utilization=0.8`, and `gdn_prefill_backend="triton"`. The first smoke test should query actual VRAM after the driver repair and use the model's documented image limits (`448*448` minimum pixels and `2880*2880` maximum pixels).

The downloaded ModelScope checkpoint is stored at `Ovis/model/OvisOCR2`. ModelScope published SHA-256 `9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009` for `model.safetensors`, and the local file matches it.

## Completed verification

- `nvidia-smi`: driver `580.178.04`, RTX 4060 Ti, 16,380 MiB VRAM.
- Runtime smoke test: `torch.cuda.is_available()` is `True`, CUDA capability is `(8, 9)`, and `vllm.LLM` imports with the bundled CUDA runtime path.
- Model smoke test: the local ModelScope checkpoint loaded with Qwen3.5, Triton GDN prefill, and FlashAttention; one page image produced Markdown output successfully.
- First startup on this workstation took about 206 seconds for compilation, profiling, and CUDA graph capture. The resulting vLLM compile cache is reused by subsequent runs.
- The first run emitted non-fatal Transformers deprecation/docstring warnings from the vLLM/Transformers integration.

Run OCR with:

```bash
Ovis/run_ocr.sh /path/to/page.png --output /path/to/page.md
```

## Sources

1. [OvisOCR2 ModelScope README](https://modelscope.cn/models/ATH-MaaS/OvisOCR2/resolve/master/README.md) — exact vLLM/Pillow install, runtime settings, prompt, and image limits.
2. [OvisOCR2 ModelScope config](https://modelscope.cn/models/ATH-MaaS/OvisOCR2/resolve/master/config.json) — Qwen3.5 architecture and Transformers baseline.
3. [vLLM 0.22.1 package metadata](https://pypi.org/pypi/vllm/0.22.1/json) — Python and dependency constraints.
4. [vLLM 0.22.1 CUDA installation source](https://raw.githubusercontent.com/vllm-project/vllm/v0.22.1/docs/getting_started/installation/gpu.cuda.inc.md) — compute capability minimum, CUDA 12.9 binaries, fresh-environment guidance, and PyTorch backend selection.
5. [vLLM 0.22.1 supported models](https://raw.githubusercontent.com/vllm-project/vllm/v0.22.1/docs/models/supported_models.md) — `Qwen3_5ForConditionalGeneration` multimodal support.
6. [NVIDIA CUDA GPU Compute Capability](https://developer.nvidia.com/cuda-gpus) — RTX 4060 Ti compute capability 8.9.
7. [NVIDIA CUDA 12.9 Release Notes](https://docs.nvidia.com/cuda/archive/12.9.0/cuda-toolkit-release-notes/index.html) — minimum Linux driver version.
