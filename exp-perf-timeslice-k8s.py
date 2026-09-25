from monitoring import *
from k8s import *
from workloads import *

import os, sys, time

DELAY=300

# This script evaluates GPU time-slicing performance in a Kubernetes environment by varying the number of pod replicas using the GPU.
# No MIG is used — performance impact is assessed as more GPU-sharing pods are scheduled.
# Benchmarks run in each pod, and metrics (DCGM, IPMI, CPU) are collected to analyze performance under contention.
#
# Orchestration is delegated to KubernetesScheduler (k8s/scheduler.py): for each condition it
# launches one Pod per replica (via the Workload* classes in workloads/), and blocks until they
# all finish (bounded by `timeout`) instead of guessing a fixed sleep duration.

BENCHES = {
    'blender': (WorkloadBlender, lambda label, result_directory, cache_directory: {
        'label': label, 'result_directory': result_directory}),
    'hpcg': (WorkloadHpcg, lambda label, result_directory, cache_directory: {
        'label': label, 'result_directory': result_directory}),
    'llama': (WorkloadInferenceLlama, lambda label, result_directory, cache_directory: {
        'label': label, 'model_name': 'meta-llama/Llama-3.1-8B-Instruct',
        'result_directory': result_directory, 'cache_directory': cache_directory}),
    'yolo': (WorkloadTrainingYolo, lambda label, result_directory, cache_directory: {
        'label': label, 'model_name': 'yolov8n.pt', 'result_directory': result_directory}),
}

#########################
# Setup Replicas policy #
#########################
def setup_namespace_and_launch(kubectl_wrapper, scheduler, monitors_wrapper, gpu_count):

    kubectl_wrapper.destroy_all_pods()

    # Overridable through env vars; must be absolute paths for k8s hostPath
    result_directory = os.path.abspath(os.environ.get('BENCH_RESULT_DIR', 'bench-res'))
    cache_directory  = os.path.expanduser(os.environ.get('HF_CACHE_DIR', '~/.cache/huggingface/'))
    os.makedirs(result_directory, exist_ok=True)
    os.makedirs(cache_directory, exist_ok=True)

    oversub = 8
    # I) Setup oversubscription policy
    if oversub > 1:
        kubectl_wrapper.set_kube_replicas_policy(oversub, config_name="oversub-all-" + str(oversub))
        kubectl_wrapper.patch_cluster_policy(config_name="oversub-all-" + str(oversub))
        while(True):
            current_value = kubectl_wrapper.get_current_oversub_policy()
            if current_value == oversub: break
            time.sleep(5) # Waiting for patch to be applied, can be long

    print("New GPU instance count:", kubectl_wrapper.get_gpu_instance_count())

    # Use different workloads
    for bench in BENCHES:

        # II) Iterate through different number of pods
        for instance_per_gpu in range(oversub+1):

            wanted_instance = instance_per_gpu * gpu_count

            # III) Update monitoring
            setting_name = bench + '|' + str(oversub) + '|' + str(instance_per_gpu)
            monitors_wrapper.update_monitoring({'context': setting_name}, monitor_index=0, reset_launch=True)
            print(setting_name)

            # IV) Launch, wait for completion, and tear down
            jobs = build_jobs_for_bench(bench, num_pods=wanted_instance, label=setting_name,
                                         result_directory=result_directory, cache_directory=cache_directory)
            scheduler.run(jobs, timeout=DELAY + 300) # benchmarks run longer than a fixed-duration burn

def build_jobs_for_bench(bench: str, num_pods: int, label: str, result_directory: str, cache_directory: str):
    if bench not in BENCHES:
        print('Unknow bench specified')
        sys.exit(-1)
    agent_cls, kwargs_fn = BENCHES[bench]
    agent = agent_cls()
    kwargs = kwargs_fn(label, result_directory, cache_directory)
    return [PodJob(name=f'{agent.name}-{i}', workload=agent, kwargs=kwargs) for i in range(num_pods)]

if __name__ == "__main__":

    print('Starting time-slice experiment')

    #########################
    # Cluster management    #
    #########################
    kubectl_wrapper = KubectlWrapper()
    scheduler = KubernetesScheduler(kubectl_wrapper)

    # Physical GPU count, read before any oversubscription policy is applied (the
    # allocatable count below would otherwise already be inflated by the replica factor)
    gpu_count = kubectl_wrapper.get_allocatable_gpu_resources().get('nvidia.com/gpu', 0)
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
    monitors_wrapper = MonitorWrapper(monitors=monitors, output_file='data/measures-perf-timeslices-k8s.csv')

    ##########################
    # Starting  measurements #
    ##########################

    try:
        monitors_wrapper.start_monitoring()

        print('Capturing idle')
        monitors_wrapper.update_monitoring({'context':'idle'}, monitor_index=0, reset_launch=False)
        time.sleep(DELAY)
        print('Idle capture ended')

        setup_namespace_and_launch(kubectl_wrapper, scheduler, monitors_wrapper, gpu_count)

    except KeyboardInterrupt:
        pass
    print('Exiting')
    monitors_wrapper.stop_monitoring()
