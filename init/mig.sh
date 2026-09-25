#!/bin/bash
# Enable/disable MIG on every GPU of a Lambda A100/H100 instance.
# Usage: ./init/mig.sh enable|disable|status
#
# Toggling MIG needs the GPUs idle. In a VM the GPU reset can be refused by the
# hypervisor; if MIG stays "pending", reboot the instance (the pending mode is applied
# at boot and persists), then run this script again with `status`, then setup.sh's
# dcgm-exporter step again (or `docker start`-equivalent, see bottom).
set -uo pipefail

action="${1:-status}"
DCGM_EXPORTER_IMAGE="${DCGM_EXPORTER_IMAGE:-nvcr.io/nvidia/k8s/dcgm-exporter:4.1.1-4.0.3-ubuntu22.04}"

status() { nvidia-smi --query-gpu=index,name,mig.mode.current,mig.mode.pending --format=csv; }

case "$action" in
status) status; exit 0 ;;
enable) mode=1 ;;
disable) mode=0 ;;
*) echo "usage: $0 enable|disable|status"; exit 1 ;;
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
