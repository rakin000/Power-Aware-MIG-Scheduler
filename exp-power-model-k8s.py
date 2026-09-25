from monitoring import *
from k8s import *
from workloads import *

import json, os, subprocess, sys, time

IDLE_DELAY = 60      # s of idle capture (the model's idle_power_w)
SOLO_DELAY = 60      # s per solo profiling run
CORUN_DELAY = 180    # s each co-located workload runs, long enough to overlap the next submissions
MONITOR_DELAY = 1    # s between monitoring samples
OUTPUT_FILE = 'data/measures-power-model.csv'
GPU_POWER_MODEL_DIR = os.environ.get('GPU_POWER_MODEL_DIR', os.path.join('..', 'GPU_Power_Model'))

# This script closes the loop between this repo's monitoring and the GPU Power Model
# (../GPU_Power_Model), on MIG instances of the minikube node:
#   1. run    : each workload alone on its MIG instance (default scheduler),
#   2. monitor: DCGM power/clock/temperature via MonitorWrapper -> OUTPUT_FILE, labeled by context,
#   3. profile: turn each solo run's monitored samples into the model's solo-profile summary
#               (monitoring/solo_profile.py),
#   4. decide : submit the workloads one after another to the `power-aware-scheduler`
#               kube-scheduler (init/power-scheduler.sh), whose extender predicts from the pending
#               pod's profile and the profiles already resident on the GPU whether co-location
#               overloads it, and filters the node out if so,
#   5. report : print every scheduling condition the scheduler raises, and what we would do about
#               it. Nothing is acted on yet (rejected pods are deleted, not requeued elsewhere).
# Needs MIG instances (./init/mig.sh create) and the power-aware scheduler (./init/power-scheduler.sh).

def gpu_info() -> dict:
    """Static GPU facts of GPU 0 (single-node, single-GPU cluster)."""
    output = subprocess.check_output(['nvidia-smi', '-i', '0', '--query-gpu=name,power.limit,memory.total,clocks.max.sm',
                                      '--format=csv,noheader,nounits'], text=True)
    name, power_limit, memory_total, clock_max = [field.strip() for field in output.splitlines()[0].split(',')]
    return {'gpu_name': name, 'power_limit_w': float(power_limit), 'memory_total_mb': float(memory_total),
            'sm_clock_max_mhz': float(clock_max)}

def load_power_model():
    """The GPU Power Model's own policy code, to print the risk behind each decision. The decision
    itself is always the scheduler's; this only explains it. None if the repository isn't found.
    """
    sys.path.insert(0, os.path.join(GPU_POWER_MODEL_DIR, 'src'))
    try:
        from mig_power.scheduler import SchedulerPolicy, TreeRiskModel
        model = TreeRiskModel.from_path(os.path.join(GPU_POWER_MODEL_DIR, 'deploy', 'scheduler', 'model.json'))
        return SchedulerPolicy(model)
    except Exception as exc:
        print('GPU Power Model not importable from', GPU_POWER_MODEL_DIR, f'({exc}): risk values will not be printed')
        return None

def job_for(workload, kwargs: dict, mig_resource: str) -> PodJob:
    profile = mig_resource.removeprefix('nvidia.com/mig-')
    return PodJob(name=f'{workload.name}-{profile}', workload=workload, kwargs=kwargs, gpu_resource=mig_resource)

#########################
# 1-3. Solo profiling   #
#########################
def profile_workloads(candidates: list, monitors_wrapper, info: dict, idle_w: float) -> dict:
    """Runs every (workload, kwargs, MIG resource) alone and returns {pod name: solo profile}."""
    batch = KubernetesScheduler(KubectlWrapper())
    profiles = {}
    for workload, kwargs, mig_resource in candidates:
        job = job_for(workload, dict(kwargs, delay=SOLO_DELAY), mig_resource)
        context = 'solo|' + job.name
        monitors_wrapper.update_monitoring({'context': context}, monitor_index=0, reset_launch=True)
        print(f'Profiling {job.name} alone on {mig_resource} for {SOLO_DELAY}s')
        phases = batch.run([job], timeout=SOLO_DELAY + 120)
        monitors_wrapper.update_monitoring({'context': 'between'}, monitor_index=0, reset_launch=True)
        if phases.get(job.name) != 'Succeeded':
            print(f'  skipped: solo run ended {phases.get(job.name)!r}')
            continue
        time.sleep(2 * MONITOR_DELAY)  # let the last ticks of the run reach the CSV
        samples = read_context_samples(OUTPUT_FILE, context)
        profiles[job.name] = summarize_solo_profile(samples, job.name, info['gpu_name'], mig_resource,
                                                    idle_w, info['power_limit_w'])
        print('  solo profile:', json.dumps(profiles[job.name]))
    return profiles

#########################
# 4-5. Scheduling       #
#########################
def describe_decision(pod_name: str, decision: dict, risk_text: str):
    """Prints the scheduling condition and the action we would take (none is taken yet)."""
    if decision['scheduled']:
        print(f'  [scheduler] {pod_name}: bound to {decision["node"]}{risk_text}')
        return
    message = decision['message']
    print(f'  [scheduler] {pod_name}: PodScheduled=False reason={decision["reason"]}{risk_text}')
    print(f'              {message}')
    if 'meets threshold' in message:
        action = 'POWER OVERLOAD predicted -> would defer the pod until a resident finishes, or place it on another GPU'
    elif 'power-model contract' in message:
        action = 'OUTSIDE MODEL DOMAIN (fail-closed) -> would need a model for this co-location, or defer'
    elif 'Insufficient' in message:
        action = 'NO FREE MIG INSTANCE of this profile -> would wait for one'
    elif decision['scheduled'] is None:
        action = 'NO DECISION -> check the power-aware-scheduler and extender pods'
    else:
        action = 'UNSCHEDULABLE for another reason -> see message'
    print(f'  [decision]  {action}')

def schedule_workloads(candidates: list, profiles: dict, power_scheduler, monitors_wrapper, policy):
    submitted = []
    for workload, kwargs, mig_resource in candidates:
        job = job_for(workload, dict(kwargs, delay=CORUN_DELAY), mig_resource)
        if job.name not in profiles: continue

        residents = power_scheduler.reconcile_residents()
        context = 'corun|' + '+'.join([p['id'] for p in residents] + [job.name])
        monitors_wrapper.update_monitoring({'context': context}, monitor_index=0, reset_launch=True)
        print(f'Submitting {job.name} to {POWER_SCHEDULER_NAME}, resident on the GPU: {[p["id"] for p in residents] or "none"}')

        # What the model will say, computed by the model's own code on the same pod/node objects
        risk_text = ''
        if policy is not None:
            pod = {'metadata': {'annotations': {'gpu-power.myscheduler.com/solo-profile': json.dumps(profiles[job.name])}},
                   'spec': {'containers': [{'resources': {'limits': {mig_resource: 1}}}]}}
            node = power_scheduler.kubectl.get_object('node', power_scheduler.node) or {}
            predicted = policy.evaluate(pod, node)
            risk_text = f' (model: {predicted.reason})'

        pod_name = power_scheduler.submit(job, profiles[job.name])
        submitted.append(pod_name)
        decision = power_scheduler.await_decision(pod_name)
        describe_decision(pod_name, decision, risk_text)
        if decision['scheduled']:
            power_scheduler.await_running(pod_name)  # only then is it really resident
        else:
            power_scheduler.kubectl.delete_pods([pod_name])  # no action on conditions yet
            submitted.remove(pod_name)

    if submitted:
        print(f'Waiting for the co-located workloads to finish: {submitted}')
        power_scheduler.batch.wait(submitted, timeout=CORUN_DELAY + 120)
        power_scheduler.kubectl.delete_pods(submitted)
    power_scheduler.reconcile_residents()

if __name__ == "__main__":

    print('Starting GPU Power Model scheduling experiment')

    kubectl_wrapper = KubectlWrapper()
    power_scheduler = PowerAwareScheduler(kubectl_wrapper, node='minikube')
    if not power_scheduler.is_deployed():
        print(f'{POWER_SCHEDULER_NAME} is not running: ./init/power-scheduler.sh')
        sys.exit(-1)
    mig_profiles = kubectl_wrapper.get_mig_resources()
    if not mig_profiles:
        print('No MIG resources advertised by the cluster (MIG mode enabled and instances created? see init/mig.sh)')
        sys.exit(-1)
    print('MIG profiles found:', mig_profiles)

    info = gpu_info()
    power_scheduler.publish_gpu_metadata(info['gpu_name'], info['power_limit_w'], info['memory_total_mb'], info['sm_clock_max_mhz'])
    policy = load_power_model()

    # One gpu_burn per MIG profile, largest first. mem_use: see exp-mig-k8s.py
    burn = WorkloadBurn()
    candidates = [(burn, {'mem_use': '90%'}, profile) for profile in sorted(mig_profiles, key=lambda p: -mig_geometry(p)[0])]

    mon_labels = ConstMonitor({'context': 'init'}, gpu_count=1, include_gpu_x=True)
    mon_cpu = CPUMonitor(gpu_count=1, include_gpu_x=True)
    mon_dcgm = DCGMMonitor(url='http://localhost:9400/metrics')
    os.makedirs('data', exist_ok=True)
    monitors_wrapper = MonitorWrapper(monitors=[mon_labels, mon_cpu, mon_dcgm], output_file=OUTPUT_FILE, delay=MONITOR_DELAY)

    try:
        monitors_wrapper.start_monitoring()
        kubectl_wrapper.destroy_all_pods()
        power_scheduler.reconcile_residents()

        print(f'Capturing idle for {IDLE_DELAY}s')
        monitors_wrapper.update_monitoring({'context': 'idle'}, monitor_index=0, reset_launch=True)
        time.sleep(IDLE_DELAY)
        idle_w = idle_power(OUTPUT_FILE)
        print(f'Idle power: {idle_w:.1f} W')

        profiles = profile_workloads(candidates, monitors_wrapper, info, idle_w)
        schedule_workloads(candidates, profiles, power_scheduler, monitors_wrapper, policy)

    except KeyboardInterrupt:
        pass
    print('Exiting')
    monitors_wrapper.stop_monitoring()
