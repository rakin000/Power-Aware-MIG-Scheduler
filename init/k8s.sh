#!/bin/bash
# Single-node Kubernetes (minikube with its NVIDIA device plugin addon) on a Lambda instance, shared
# by all three exp-*.py scripts. Run ./init/setup.sh first.
# Time-slicing (exp-timeslices.py, exp-perf-timeslice-k8s.py) needs MIG disabled (./init/mig.sh disable);
# the MIG sweep (exp-mig-k8s.py) needs it enabled and partitioned (./init/mig.sh enable, then create).
# GPU metrics on :9400 come from the standalone dcgm-exporter container started by setup.sh.
#
# No NVIDIA GPU Operator: on minikube its container toolkit switches the node's docker to a CDI
# runtime that can't resolve individual GPU/MIG devices, and its controller deletes minikube's
# device plugin daemonset (same name). minikube's addon + init/minikube-gpu.sh covers what's needed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v minikube >/dev/null; then
    curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube_latest_amd64.deb
    sudo dpkg -i minikube_latest_amd64.deb
fi

minikube delete || true
minikube start --driver docker --container-runtime docker --gpus all
minikube kubectl -- get po -A

# Images must live in minikube's docker daemon (pods use imagePullPolicy: Never)
eval "$(minikube docker-env)"
"$HERE/build-images.sh"

# Device plugin in MIG "mixed" mode + node-level MIG fixes (re-run after every `minikube start`)
"$HERE/minikube-gpu.sh"
echo "Ready. For MIG experiments: ./init/mig.sh enable (once), then ./init/mig.sh create"
