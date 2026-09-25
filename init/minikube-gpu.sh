#!/bin/bash
# Makes minikube's GPU support work with MIG. Idempotent; re-run after every `minikube start`
# (k8s.sh and `mig.sh create` call it), since the procfs mount below does not survive a restart.
#
# Why each step is needed (minikube --driver docker --gpus all, A100 with MIG enabled):
#  1. The minikube node container sees a restricted /proc/driver/nvidia without
#     capabilities/mig/{config,monitor}, so even root NVML queries on a MIG GPU fail with
#     "Insufficient Permissions". A fresh procfs has the full tree: bind it over the restricted one.
#  2. The NVIDIA runtime's default "auto" mode generates CDI specs per container, which needs MIG
#     attributes the runtime can't read; "legacy" mode injects MIG devices via
#     NVIDIA_VISIBLE_DEVICES=MIG-<uuid> (what the device plugin sets) and works.
#  3. minikube's nvidia-device-plugin addon: MIG_STRATEGY=mixed advertises one resource per MIG
#     profile (nvidia.com/mig-1g.5gb, ...); it must run privileged with
#     NVIDIA_MIG_MONITOR_DEVICES=all to be allowed to enumerate MIG devices.
set -euo pipefail

K="minikube kubectl --"

minikube ssh -- 'sudo mkdir -p /run/hostproc
mountpoint -q /run/hostproc || sudo mount -t proc proc /run/hostproc
[ -e /proc/driver/nvidia/capabilities/mig/monitor ] || sudo mount --bind /run/hostproc/driver/nvidia /proc/driver/nvidia
sudo sed -i "s/^mode = \"auto\"/mode = \"legacy\"/" /etc/nvidia-container-runtime/config.toml'

$K -n kube-system patch ds nvidia-device-plugin-daemonset --type=json \
    -p '[{"op":"replace","path":"/spec/template/spec/containers/0/securityContext","value":{"privileged":true}}]'
$K -n kube-system set env ds/nvidia-device-plugin-daemonset MIG_STRATEGY=mixed NVIDIA_MIG_MONITOR_DEVICES=all
# Restart the plugin even if the spec didn't change, so it re-enumerates (e.g. new MIG instances)
$K -n kube-system rollout restart ds nvidia-device-plugin-daemonset
$K -n kube-system rollout status ds nvidia-device-plugin-daemonset --timeout=180s

echo "Waiting for GPU resources on the node..."
for _ in $(seq 30); do
    $K get node minikube -o jsonpath='{.status.allocatable}' | grep -qE '"nvidia.com/(gpu|mig-[^"]+)":"[1-9]' && break
    sleep 3
done
$K get node minikube -o jsonpath='{.status.allocatable}'; echo
