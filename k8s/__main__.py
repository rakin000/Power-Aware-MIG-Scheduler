"""Smoke test: launches 4 short gpu_burn Pods and waits for them to finish.
Run as `python3 -m k8s` from the repo root once init/k8s.sh has set up the cluster.
"""
from .kubectl import KubectlWrapper
from .scheduler import KubernetesScheduler, PodJob
from workloads import WorkloadBurn

if __name__ == '__main__':
    kubectl_wrapper = KubectlWrapper()
    scheduler = KubernetesScheduler(kubectl_wrapper)
    burn = WorkloadBurn()
    jobs = [PodJob(name=f'gpu_burn-{i}', workload=burn, kwargs={'delay': 60}) for i in range(4)]
    print(scheduler.run(jobs, timeout=120))
