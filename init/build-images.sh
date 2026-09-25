#!/bin/bash
# Builds the gpu_burn + benchmark images in the docker daemon currently selected
# (host daemon by default; minikube's daemon after `eval $(minikube docker-env)`).
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/bench" && pwd)"
GPU_BURN_DIR="${GPU_BURN_DIR:-$HOME/gpu-burn}"
CUDA_VERSION="${CUDA_VERSION:-12.4.1}" # >= 11.8 is required for H100 (sm_90)

if [ ! -d "$GPU_BURN_DIR" ]; then
    git clone https://github.com/wilicc/gpu-burn "$GPU_BURN_DIR"
fi

docker build "$GPU_BURN_DIR" -t gpu_burn \
    --build-arg CUDA_VERSION="$CUDA_VERSION" --build-arg IMAGE_DISTRO=ubuntu22.04 &
(cd "$BENCH_DIR/blender"            && docker build . -t blender) &
(cd "$BENCH_DIR/hpcg"               && docker build . -t hpcg) &
(cd "$BENCH_DIR/inference-llama"    && docker build . -t llama) &
(cd "$BENCH_DIR/training-yolo"      && docker build . -t yolo) &

fail=0
for job in $(jobs -p); do wait "$job" || fail=1; done
exit $fail
