import re, time
from dataclasses import dataclass, field

DEFAULT_GPU_RESOURCE = 'nvidia.com/gpu'

@dataclass
class PodJob:
    """One Pod to launch: `workload.pod_spec(**kwargs)` supplies the image/command/volumes,
    `gpu_resource`/`gpu_count` say what to request in `resources.limits` — a whole GPU
    (the default) for time-slicing, or a MIG profile such as 'nvidia.com/mig-1g.10gb' for
    MIG experiments (see KubectlWrapper.get_mig_resources() to discover what a node offers).
    `name` is normalized to a valid Pod/container name (RFC 1123 label), e.g. 'gpu_burn-0' ->
    'gpu-burn-0', since workload names like 'gpu_burn' contain characters Kubernetes rejects.
    """
    name: str
    workload: object              # a WorkloadAgent (workloads/workload_agent.py)
    kwargs: dict = field(default_factory=dict)
    gpu_resource: str = DEFAULT_GPU_RESOURCE
    gpu_count: int = 1

    def __post_init__(self):
        self.name = re.sub(r'[^a-z0-9-]+', '-', self.name.lower()).strip('-')[:63]

class KubernetesScheduler(object):
    """Drives a batch of PodJobs for one experiment condition: build manifests, apply,
    poll until every pod reaches a terminal phase (or a timeout elapses), then tear down.
    Reused across every exp-*.py script the way MonitorWrapper is reused across all of them.
    """

    TERMINAL_PHASES = {'Succeeded', 'Failed'}

    def __init__(self, kubectl_wrapper, namespace: str = 'default', poll_interval: int = 5):
        self.kubectl = kubectl_wrapper
        self.namespace = namespace
        self.poll_interval = poll_interval

    def run(self, jobs: list[PodJob], timeout: int = None) -> dict:
        """Returns {pod_name: final phase}. Any pod that didn't end Succeeded has its logs
        printed before cleanup, so a bad run is visible without keeping the pod around.
        """
        pod_names = self.launch(jobs)
        try:
            phases = self.wait(pod_names, timeout=timeout)
            for name, phase in phases.items():
                if phase != 'Succeeded':
                    print(f'Pod {name} ended in phase {phase!r}, logs:')
                    print(self.kubectl.get_pod_logs(name, namespace=self.namespace))
            return phases
        finally:
            self.kubectl.delete_pods(pod_names, namespace=self.namespace)

    def launch(self, jobs: list[PodJob]) -> list[str]:
        """Applies one Pod per job and returns the list of pod names, in order."""
        if not jobs: return []
        pod_names = [job.name for job in jobs]
        self.kubectl.delete_pods(pod_names, namespace=self.namespace)  # clear stale same-named pods first
        manifest = '\n'.join(self._pod_manifest(job) for job in jobs)
        if not self.kubectl.apply_manifest(manifest, namespace=self.namespace):
            raise RuntimeError('Failed to launch pods: ' + ', '.join(pod_names))
        return pod_names

    def wait(self, pod_names: list[str], timeout: int = None) -> dict:
        """Polls until every pod in `pod_names` is Succeeded/Failed, or `timeout` (seconds,
        None = wait forever) elapses. Returns the last observed {pod_name: phase}.
        """
        start = time.time()
        while True:
            phases = self.kubectl.get_pod_phases(pod_names, namespace=self.namespace)
            if all(phase in self.TERMINAL_PHASES for phase in phases.values()):
                return phases
            if timeout is not None and (time.time() - start) > timeout:
                pending = [name for name, phase in phases.items() if phase not in self.TERMINAL_PHASES]
                print('Timeout waiting for pods, still not finished:', pending)
                return phases
            time.sleep(self.poll_interval)

    def _pod_manifest(self, job: PodJob) -> str:
        spec = job.workload.pod_spec(**job.kwargs)
        volumes = spec.get('volumes', [])

        volume_mounts_block = ''
        if volumes:
            volume_mounts_block = '    volumeMounts:\n' + ''.join(
                f"    - name: {v['name']}\n      mountPath: {v['mount_path']}\n" for v in volumes
            )
        volumes_block = ''
        if volumes:
            volumes_block = '  volumes:\n' + ''.join(self._volume_yaml(v) for v in volumes)

        return f"""---
apiVersion: v1
kind: Pod
metadata:
  name: {job.name}
spec:
  restartPolicy: Never
  containers:
  - name: {job.name}
    image: {spec['image']}
    imagePullPolicy: Never
    command: {spec['command']}
{volume_mounts_block}    resources:
      limits:
        {job.gpu_resource}: {job.gpu_count}
{volumes_block}"""

    @staticmethod
    def _volume_yaml(v: dict) -> str:
        if v.get('medium') == 'Memory':
            return (f"  - name: {v['name']}\n"
                    f"    emptyDir:\n"
                    f"      medium: Memory\n"
                    f"      sizeLimit: {v.get('size_limit', '1Gi')}\n")
        return (f"  - name: {v['name']}\n"
                f"    hostPath:\n"
                f"      path: {v['host_path']}\n"
                f"      type: Directory\n")
