#!/bin/bash
# Enable/disable MIG on every GPU of a Lambda A100/H100 instance, and create/destroy its MIG instances.
# Usage: ./init/mig.sh enable|disable|create [LAYOUT]|destroy|status
#
#   enable   turn MIG mode on (GPUs must be idle; may need a reboot, see below)
#   create   partition every GPU into MIG instances. LAYOUT is a comma-separated list of GPU
#            instance profile IDs or names (`nvidia-smi mig -lgip` lists them), default
#            9,14,19,19 = 3g + 2g + 1g + 1g (3g.20gb/2g.10gb/1g.5gb on an A100-40GB). Also
#            restarts minikube if it is running, so its container and device plugin see the new
#            instances. MIG instances do not survive a reboot: re-run this after every reboot.
#   destroy  delete every MIG instance
#   disable  destroy MIG instances, then turn MIG mode off (for the time-slicing experiments)
#   status   MIG mode and MIG devices per GPU
#
# Toggling MIG needs the GPUs idle. In a VM the GPU reset can be refused by the
# hypervisor; if MIG stays "pending", reboot the instance (the pending mode is applied
# at boot and persists), then run this script again with `status`, then setup.sh's
# dcgm-exporter step again (or `docker start`-equivalent, see bottom).
set -uo pipefail

action="${1:-status}"
DCGM_EXPORTER_IMAGE="${DCGM_EXPORTER_IMAGE:-nvcr.io/nvidia/k8s/dcgm-exporter:4.1.1-4.0.3-ubuntu22.04}"

status() { nvidia-smi --query-gpu=index,name,mig.mode.current,mig.mode.pending --format=csv; nvidia-smi -L; }

destroy_instances() {
    sudo nvidia-smi mig -dci >/dev/null 2>&1
    sudo nvidia-smi mig -dgi >/dev/null 2>&1
}

# minikube's container only gets the MIG device nodes that exist when it starts, and its device
# plugin only advertises nvidia.com/mig-* resources for them: restart both after (re)partitioning
restart_minikube() {
    minikube status >/dev/null 2>&1 || return 0
    minikube stop && minikube start
    minikube kubectl -- -n kube-system set env daemonset/nvidia-device-plugin-daemonset MIG_STRATEGY=mixed
    echo "Waiting for nvidia.com/mig-* resources on the node..."
    for _ in $(seq 60); do
        minikube kubectl -- get node minikube -o jsonpath='{.status.allocatable}' | grep -q 'nvidia.com/mig-' && break
        sleep 5
    done
    minikube kubectl -- get node minikube -o jsonpath='{.status.allocatable}'; echo
}

case "$action" in
status) status; exit 0 ;;
create)
    destroy_instances
    sudo nvidia-smi mig -cgi "${2:-9,14,19,19}" -C || exit 1
    status
    restart_minikube
    exit 0 ;;
destroy) destroy_instances; status; restart_minikube; exit 0 ;;
enable) mode=1 ;;
disable) mode=0; destroy_instances ;;
*) echo "usage: $0 enable|disable|create [LAYOUT]|destroy|status"; exit 1 ;;
esac

# Release everything holding the GPUs
docker rm -f dcgm-exporter >/dev/null 2>&1
sudo systemctl stop dcgm nvidia-dcgm nvidia-persistenced nvidia-fabricmanager 2>/dev/null

gpu_count=$(nvidia-smi --query-gpu=count --format=csv,noheader | head -n 1)
for i in $(seq 0 $((gpu_count-1))); do
    sudo nvidia-smi -i "$i" -mig "$mode"
    sudo nvidia-smi -i "$i" --gpu-reset || echo "GPU $i: reset refused, a reboot is needed to apply MIG mode"
done
sudo nvidia-smi -pm 1

status
if nvidia-smi --query-gpu=mig.mode.current,mig.mode.pending --format=csv,noheader | awk -F', ' '$1 != $2 {bad=1} END {exit !bad}'; then
    echo "MIG mode is still pending on some GPUs: run 'sudo reboot', then './init/mig.sh status'"
fi

# Bring the exporter back
docker run -d --gpus all --cap-add SYS_ADMIN --name dcgm-exporter --rm -p 9400:9400 "$DCGM_EXPORTER_IMAGE"
