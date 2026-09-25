#!/bin/bash
# One-time setup of a Lambda (lambda.ai) A100/H100 instance for the experiments.
# Lambda images ship the NVIDIA driver, Docker and nvidia-container-toolkit (Lambda Stack);
# each step below is a no-op if it is already in place.
#
# Usage (from the repo root):  ./init/setup.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DCGM_EXPORTER_IMAGE="${DCGM_EXPORTER_IMAGE:-nvcr.io/nvidia/k8s/dcgm-exporter:4.1.1-4.0.3-ubuntu22.04}"

nvidia-smi -L || { echo "No working NVIDIA driver, aborting"; exit 1; }

# Docker + NVIDIA runtime (workloads use `docker run --runtime=nvidia`)
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "Added $USER to the docker group: log out/in (or run 'newgrp docker') and re-run this script"
    exit 0
fi
if ! command -v nvidia-ctk >/dev/null; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
fi
if ! docker info 2>/dev/null | grep -q 'Runtimes:.*nvidia'; then
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
fi

# The DCGM exporter the monitors scrape on :9400 (needs SYS_ADMIN to see MIG devices).
# ipmitool is deliberately not installed: VMs have no BMC and the IPMI monitor skips itself.
# -c 1000: refresh metrics every 1 s (default 30 s), otherwise per-second monitoring reads the same
# stale value and power variability (the GPU Power Model's power_cv) comes out as 0.
docker rm -f dcgm-exporter >/dev/null 2>&1 || true
docker run -d --gpus all --cap-add SYS_ADMIN --name dcgm-exporter --rm -p 9400:9400 "$DCGM_EXPORTER_IMAGE" -c 1000

"$HERE/build-images.sh"

# Output directories expected by the experiment scripts (exp-*.py)
mkdir -p bench-res data

echo "Setup done. Next: ./init/k8s.sh                 (single-node Kubernetes cluster)"
echo "      then, optionally: ./init/mig.sh enable && ./init/mig.sh create   (MIG experiments; ./init/mig.sh disable for time-slicing)"
