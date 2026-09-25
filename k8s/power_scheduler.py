"""Power-aware placement through the GPU Power Model's kube-scheduler extender.

init/power-scheduler.sh deploys a secondary kube-scheduler, `power-aware-scheduler`, whose
Filter/Prioritize phases call the GPU Power Model's HTTP extender (../GPU_Power_Model,
deploy/scheduler + src/mig_power/scheduler.py). The extender predicts, from two workloads'
solo-run profiles, whether co-locating them on one GPU causes power pressure *and* slowdown,
and filters out nodes where the predicted risk meets its threshold.

The extender itself reads everything from annotations, and deliberately doesn't maintain them:
- on the pending Pod: its solo-run profile (built by monitoring/solo_profile.py);
- on each Node: static GPU metadata, and the profiles of the GPU workloads already resident.
PowerAwareScheduler is that missing inventory side for this single-node cluster: it publishes
the node annotations, reconciles the resident list from bound pods before every submission, and
reports what the scheduler decided for each pod (bound, or its PodScheduled=False condition).
"""
import json, time
from .scheduler import KubernetesScheduler, PodJob

POWER_SCHEDULER_NAME = 'power-aware-scheduler'

ANNOTATION_PREFIX = 'gpu-power.myscheduler.com/'
POD_PROFILE_ANNOTATION = ANNOTATION_PREFIX + 'solo-profile'
NODE_RESIDENT_PROFILES_ANNOTATION = ANNOTATION_PREFIX + 'resident-profiles'
NODE_GPU_NAME_ANNOTATION = ANNOTATION_PREFIX + 'gpu-name'
NODE_POWER_LIMIT_ANNOTATION = ANNOTATION_PREFIX + 'power-limit-w'
NODE_MEMORY_TOTAL_ANNOTATION = ANNOTATION_PREFIX + 'gpu-memory-total-mb'
NODE_CLOCK_MAX_ANNOTATION = ANNOTATION_PREFIX + 'sm-clock-max-mhz'

RESIDENT_PHASES = {'Pending', 'Running'}  # bound (spec.nodeName set) and not finished

class PowerAwareScheduler(object):

    def __init__(self, kubectl_wrapper, node: str, namespace: str = 'default', poll_interval: float = 1):
        self.kubectl = kubectl_wrapper
        self.node = node
        self.namespace = namespace
        self.poll_interval = poll_interval
        self.batch = KubernetesScheduler(kubectl_wrapper, namespace=namespace)

    def is_deployed(self) -> bool:
        deployment = self.kubectl.get_object('deployment', POWER_SCHEDULER_NAME, namespace='kube-system')
        return bool(deployment and deployment.get('status', {}).get('readyReplicas'))

    def publish_gpu_metadata(self, gpu_name: str, power_limit_w: float, memory_total_mb: float, sm_clock_max_mhz: float):
        """Static per-node GPU facts the model normalizes by (power cap, memory, max SM clock)."""
        self.kubectl.annotate_node(self.node, {
            NODE_GPU_NAME_ANNOTATION: gpu_name,
            NODE_POWER_LIMIT_ANNOTATION: power_limit_w,
            NODE_MEMORY_TOTAL_ANNOTATION: memory_total_mb,
            NODE_CLOCK_MAX_ANNOTATION: sm_clock_max_mhz,
        })

    def resident_pods(self) -> list:
        """Pods bound to this node, not finished, and carrying a solo profile."""
        return [pod for pod in self.kubectl.list_pods(self.namespace)
                if pod.get('spec', {}).get('nodeName') == self.node
                and pod.get('status', {}).get('phase') in RESIDENT_PHASES
                and POD_PROFILE_ANNOTATION in pod.get('metadata', {}).get('annotations', {})]

    def reconcile_residents(self) -> list:
        """Rewrites the node's resident-profiles annotation from the pods actually bound to it
        and returns the resident profiles. Must run before each submission: the extender decides
        from this annotation, not from the pods.
        """
        profiles = [json.loads(pod['metadata']['annotations'][POD_PROFILE_ANNOTATION]) for pod in self.resident_pods()]
        self.kubectl.annotate_node(self.node, {NODE_RESIDENT_PROFILES_ANNOTATION: json.dumps(profiles, sort_keys=True)})
        return profiles

    def submit(self, job: PodJob, solo_profile: dict) -> str:
        """Launches `job` through the power-aware scheduler with its solo profile attached."""
        job.scheduler_name = POWER_SCHEDULER_NAME
        job.annotations[POD_PROFILE_ANNOTATION] = json.dumps(solo_profile, sort_keys=True)
        return self.batch.launch([job])[0]

    def await_decision(self, pod_name: str, timeout: float = 60) -> dict:
        """Polls until the scheduler has decided on `pod_name`: bound to a node, or marked
        unschedulable (PodScheduled=False, reason/message from the scheduler — including the
        extender's per-node reasons). Returns {'scheduled', 'node', 'reason', 'message'}; on
        timeout 'scheduled' is None.
        """
        start = time.time()
        while time.time() - start < timeout:
            pod = self.kubectl.get_object('pod', pod_name, namespace=self.namespace) or {}
            node = pod.get('spec', {}).get('nodeName')
            for condition in pod.get('status', {}).get('conditions', []):
                if condition.get('type') != 'PodScheduled': continue
                if condition.get('status') == 'True' or node:
                    return {'scheduled': True, 'node': node, 'reason': 'Scheduled', 'message': ''}
                if condition.get('status') == 'False':
                    return {'scheduled': False, 'node': None, 'reason': condition.get('reason', ''),
                            'message': condition.get('message', '')}
            time.sleep(self.poll_interval)
        return {'scheduled': None, 'node': None, 'reason': 'Timeout', 'message': f'no scheduling decision after {timeout}s'}

    def await_running(self, pod_name: str, timeout: float = 120) -> str:
        """Waits for a bound pod to start (so it really is resident); returns its last phase."""
        start = time.time()
        phase = None
        while time.time() - start < timeout:
            phase = self.kubectl.get_pod_phases([pod_name], namespace=self.namespace).get(pod_name)
            if phase in ('Running', 'Succeeded', 'Failed'): break
            time.sleep(self.poll_interval)
        return phase
