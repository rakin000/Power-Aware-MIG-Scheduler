#!/bin/bash
# Single-node Kubernetes (minikube + NVIDIA GPU operator) on a Lambda instance, shared by all
# three exp-*.py scripts. Run ./init/setup.sh first.
# Time-slicing (exp-timeslices.py, exp-perf-timeslice-k8s.py) needs MIG disabled (./init/mig.sh disable);
# the MIG sweep (exp-mig-k8s.py) needs it enabled and partitioned (./init/mig.sh enable, then create) —
# the MIG_STRATEGY=mixed set below is what lets the device plugin expose per-profile
# nvidia.com/mig-* resources once it is.
# GPU metrics on :9400 come from the standalone dcgm-exporter container started by setup.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v minikube >/dev/null; then
    curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube_latest_amd64.deb
    sudo dpkg -i minikube_latest_amd64.deb
fi
if ! command -v helm >/dev/null; then
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

minikube delete || true
minikube start --driver docker --container-runtime docker --gpus all
minikube kubectl -- get po -A

helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
# driver.enabled=false: the driver is already installed on the Lambda host
helm install gpuo nvidia/gpu-operator --namespace kube-system \
    --set driver.enabled=false --set mig.strategy=mixed --set devicePlugin.enabled=true \
    --set operator.defaultRuntime=docker --set gfd.version=v0.8.1

# Images must live in minikube's docker daemon (pods use imagePullPolicy: Never)
eval "$(minikube docker-env)"
"$HERE/build-images.sh"

# GPUs are advertised by minikube's nvidia-device-plugin addon (enabled by --gpus all), whose
# default MIG strategy (none) hides MIG instances; mixed exposes one resource per profile
# (nvidia.com/mig-1g.5gb, ...) and still plain nvidia.com/gpu when MIG is off. Persists across
# minikube stop/start.
minikube kubectl -- -n kube-system set env daemonset/nvidia-device-plugin-daemonset MIG_STRATEGY=mixed
echo "Ready. For MIG experiments: ./init/mig.sh enable (once), then ./init/mig.sh create"
