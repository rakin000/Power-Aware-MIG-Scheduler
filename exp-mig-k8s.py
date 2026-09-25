from monitoring import *
from k8s import *
from workloads import *

import os, subprocess, sys, time

DELAY=300

# This script evaluates worst-case power consumption under NVIDIA MIG partitioning: for every MIG
# profile the cluster currently exposes (e.g. nvidia.com/mig-1g.10gb, nvidia.com/mig-3g.40gb — see
# init/mig.sh to enable MIG mode and init/k8s.sh for the GPU Operator's `mig.strategy=mixed`), it
# sweeps the number of concurrent gpu_burn instances requesting that profile, from 1 up to however
# many the cluster can schedule at once. Metrics (especially power via DCGM and IPMI) are collected
# to assess peak per-partition-size consumption under contention.
#
# Orchestration is delegated to KubernetesScheduler (k8s/scheduler.py). Unlike exp-timeslices.py,
# each PodJob here sets gpu_resource to a MIG profile name instead of the default 'nvidia.com/gpu',
# so pods land on MIG instances of that specific size rather than whole (or time-sliced) GPUs.

#########################
# Sweep MIG profiles    #
#########################
def sweep_mig_profiles(kubectl_wrapper, scheduler, monitors_wrapper):

    kubectl_wrapper.destroy_all_pods()
    burn = WorkloadBurn()

    mig_profiles = kubectl_wrapper.get_mig_resources()
    if not mig_profiles:
        print('No MIG resources advertised by the cluster (MIG mode enabled and instances created? see init/mig.sh)')
        sys.exit(-1)
    print('MIG profiles found:', mig_profiles)

    for profile, capacity in sorted(mig_profiles.items()):
        for replicas in range(1, capacity + 1):

            # I) Update monitoring
            setting_name = profile.removeprefix('nvidia.com/mig-') + '|' + str(replicas)
            monitors_wrapper.update_monitoring({'context': setting_name}, monitor_index=0, reset_launch=True)
            print(setting_name)

            # II) Launch `replicas` burn pods each requesting one instance of this MIG profile,
            #     wait for completion, and tear down
            # mem_use: the workload's 10% default suits time-slicing (pods share one GPU's memory) but
            # is below gpu_burn's ~768 MB minimum on small MIG instances (1g.5gb -> ~475 MB) and aborts
            jobs = [PodJob(name=f'{burn.name}-{i}', workload=burn, kwargs={'delay': DELAY, 'mem_use': '90%'},
                            gpu_resource=profile, gpu_count=1) for i in range(replicas)]
            scheduler.run(jobs, timeout=DELAY + 120)

def local_gpu_count() -> int:
    """Physical GPU count on this node, for labeling monitor domains (GPU0..GPUn) — MIG profile
    resources don't map 1:1 to physical GPUs, so this still needs a direct nvidia-smi query.
    """
    try:
        output = subprocess.check_output(['nvidia-smi', '--query-gpu=count', '--format=csv,noheader'], text=True)
        return int(output.splitlines()[0])
    except Exception:
        return 0

if __name__ == "__main__":

    print('Starting MIG experiment')

    #########################
    # Cluster management    #
    #########################
    kubectl_wrapper = KubectlWrapper()
    scheduler = KubernetesScheduler(kubectl_wrapper)

    gpu_count = local_gpu_count()
    if gpu_count <= 0:
        print('Not enough GPU to continue')
        sys.exit(-1)

    ##########################
    # Monitoring management  #
    ##########################
    mon_labels = ConstMonitor({'context':'init'}, gpu_count=gpu_count, include_gpu_x=True)
    mon_cpu = CPUMonitor(gpu_count=gpu_count, include_gpu_x=True)
    mon_ipmi = IPMIMonitor(sudo_command='sudo')
    mon_ipmi.discover()
    mon_smi  = SMIMonitor(sudo_command='sudo')
    mon_dcgm = DCGMMonitor(url='http://localhost:9400/metrics')

    monitors = [mon_labels, mon_cpu, mon_ipmi, mon_smi, mon_dcgm] # index matters for update
    os.makedirs('data', exist_ok=True)
    monitors_wrapper = MonitorWrapper(monitors=monitors, output_file='data/measures-mig-k8s.csv')

    ##########################
    # Starting  measurements #
    ##########################

    try:
        monitors_wrapper.start_monitoring()

        print('Capturing idle')
        monitors_wrapper.update_monitoring({'context':'idle'}, monitor_index=0, reset_launch=False)
        time.sleep(DELAY)
        print('Idle capture ended')

        sweep_mig_profiles(kubectl_wrapper, scheduler, monitors_wrapper)

    except KeyboardInterrupt:
        pass
    print('Exiting')
    monitors_wrapper.stop_monitoring()
