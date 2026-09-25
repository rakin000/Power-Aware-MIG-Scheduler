#!/bin/bash
# Single-node Kubernetes (minikube + NVIDIA GPU operator) on a Lambda instance, shared by all
# three exp-*.py scripts. Run ./init/setup.sh first.
# Time-slicing (exp-timeslices.py, exp-perf-timeslice-k8s.py) needs MIG disabled (./init/mig.sh disable);
# the MIG sweep (exp-mig-k8s.py) needs it enabled (./init/mig.sh enable) — the mig.strategy=mixed set
# below is what lets the device plugin expose per-profile nvidia.com/mig-* resources once it is.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# minikube owns the GPUs' metrics endpoint from here on: the operator's dcgm-exporter
# replaces the standalone container on :9400
docker rm -f dcgm-exporter >/dev/null 2>&1 || true

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

echo "Waiting for the operator's dcgm-exporter pod..."
until minikube kubectl -- get pods -n gpu-operator -l app=nvidia-dcgm-exporter -o name 2>/dev/null | grep -q pod; do sleep 10; done
POD_NAME=$(minikube kubectl -- get pods -n gpu-operator -l app=nvidia-dcgm-exporter -o jsonpath='{.items[0].metadata.name}')
minikube kubectl -- -n gpu-operator wait --for=condition=Ready pod/"$POD_NAME" --timeout=600s
nohup minikube kubectl -- -n gpu-operator port-forward pod/"$POD_NAME" 9400:9400 > /dev/null 2>&1 &
echo "Ready: DCGM metrics forwarded on :9400."
