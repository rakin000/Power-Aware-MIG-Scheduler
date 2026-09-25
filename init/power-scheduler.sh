#!/bin/bash
# Deploys the power-aware scheduler into minikube:
#  1. the GPU Power Model's scheduler extender (HTTP Filter/Prioritize service + its model), built
#     and deployed from the GPU_Power_Model repository's deploy/scheduler/ files, and
#  2. a secondary kube-scheduler named "power-aware-scheduler" that calls it (power-scheduler/scheduler.yaml).
# Idempotent. Run after ./init/k8s.sh; used by exp-power-model-k8s.py.
# Usage: ./init/power-scheduler.sh      (GPU_POWER_MODEL_DIR defaults to ../GPU_Power_Model)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPU_POWER_MODEL_DIR="${GPU_POWER_MODEL_DIR:-$HERE/../../GPU_Power_Model}"
GPU_POWER_MODEL_DIR="$(cd "$GPU_POWER_MODEL_DIR" && pwd)"
K="minikube kubectl --"

# Extender image in minikube's docker daemon (the Deployment uses image mig-power-extender:prototype)
eval "$(minikube docker-env)"
docker build -f "$GPU_POWER_MODEL_DIR/deploy/scheduler/Dockerfile" -t mig-power-extender:prototype "$GPU_POWER_MODEL_DIR"
eval "$(minikube docker-env --unset)"

# Namespace, model ConfigMap, Deployment and Service, as shipped by the model repository.
# A single replica: this is a one-node cluster.
$K apply -f "$GPU_POWER_MODEL_DIR/deploy/scheduler/extender.yaml"
$K -n mig-power-system scale deployment mig-power-extender --replicas=1
$K -n mig-power-system rollout restart deployment mig-power-extender  # pick up a rebuilt image
$K -n mig-power-system rollout status deployment mig-power-extender --timeout=180s

# Secondary kube-scheduler, same version as the cluster's control plane
version="$($K version -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])')"
sed "s#KUBE_SCHEDULER_IMAGE#registry.k8s.io/kube-scheduler:$version#" "$HERE/power-scheduler/scheduler.yaml" | $K apply -f -
$K -n kube-system rollout restart deployment power-aware-scheduler  # pick up config changes
$K -n kube-system rollout status deployment power-aware-scheduler --timeout=180s

echo "Ready: pods with 'schedulerName: power-aware-scheduler' are placed through the GPU Power Model."
