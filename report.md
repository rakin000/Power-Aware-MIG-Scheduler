# `exp-power-model-k8s.py`: power-aware MIG scheduling with the GPU Power Model

## Summary

`exp-power-model-k8s.py` connects this repository's monitoring to the GPU Power Model
(`../GPU_Power_Model`) inside a real Kubernetes cluster (single-node minikube, A100-SXM4-40GB
with MIG enabled). It:

1. runs MIG workloads,
2. monitors them,
3. turns the monitored values into the model's input and gets an overload decision from a real
   kube-scheduler that consults the model,
4. reports every scheduling condition the scheduler raises, and what it would do about it.

It is observational for now: rejected pods are deleted rather than deferred or moved.

## Background: what the GPU Power Model decides

The GPU Power Model predicts whether **co-locating two MIG workloads on one GPU** will cause
*power pressure and a performance regression*. The prediction uses only each workload's
**solo-run profile**, a summary of how it behaves alone on the GPU:

| Field | Meaning |
| --- | --- |
| `mig_compute_slices`, `mig_memory_gb` | MIG geometry, e.g. `3g.20gb` → 3 slices, 20 GB |
| `idle_power_w` | GPU power with nothing running |
| `power_mean_w`, `power_p95_w` | Mean and 95th-percentile board power during the run |
| `power_cv` | Power coefficient of variation (std / mean) |
| `duty_above_90pct` | Fraction of samples at ≥ 90% of the power limit |
| `clock_p10_mhz`, `clock_cv` | 10th-percentile SM clock and its variation |
| `temperature_max_c` | Maximum GPU temperature |

It also uses per-node GPU facts: GPU name, power limit, total memory and maximum SM clock.

The model ships as an HTTP **kube-scheduler extender** (`scripts/run_scheduler_extender.py`).
For each candidate node, the extender combines the pending pod's profile with the profile of
the workload already on that GPU and computes a risk:

- **Filter:** removes the node if the risk meets the threshold (0.5).
- **Prioritize:** scores nodes by lower risk.

It **fails closed** outside its training domain: missing metadata, or more than one workload
already resident, rejects the node.

The extender reads everything from annotations but doesn't maintain them. The experiment
provides that side.

## Components

| Component | Role |
| --- | --- |
| `init/power-scheduler.sh` | Builds the extender image from `../GPU_Power_Model/deploy/scheduler/` into minikube and deploys it with the model repo's `extender.yaml`. Also starts a second kube-scheduler, `power-aware-scheduler`, configured to call the extender on every Filter/Prioritize. Only pods with `schedulerName: power-aware-scheduler` use it; the default scheduler is untouched. |
| `monitoring/` (`MonitorWrapper`, `ConstMonitor`, `DCGMMonitor`, `CPUMonitor`) | Samples GPU power, SM clock and temperature from dcgm-exporter every second into a CSV. Each sample carries a `context` label naming the current phase. |
| `monitoring/solo_profile.py` | Rebuilds the model's solo profile from the CSV, with the same definitions as the model's training extraction (details below). |
| `k8s/power_scheduler.py` (`PowerAwareScheduler`) | The inventory side: publishes node GPU metadata, rebuilds the node's list of resident workload profiles from the pods actually bound to it, submits pods to `power-aware-scheduler` with their profile attached, and waits for the scheduler's decision. |
| `k8s/scheduler.py` (`KubernetesScheduler`, `PodJob`) | Launches pods and waits for them. Used for the solo runs, which go through the default scheduler. |

## What the script does, step by step

### 0. Preconditions

The script checks that `power-aware-scheduler` is running and that the node advertises MIG
resources (`nvidia.com/mig-*`); otherwise it exits with a hint. It then:

- reads the GPU's static facts with `nvidia-smi` (name, power limit, memory, maximum SM clock)
  and publishes them as node annotations;
- loads the model's own policy code from `../GPU_Power_Model`. This is only used to print the
  risk behind each decision; the decision itself always comes from the scheduler.

The candidate workloads are one `gpu_burn` per MIG profile, largest first, each using 90% of its
instance's memory. With the default layout that's `3g.20gb`, `2g.10gb`, `1g.5gb`.

### 1. Idle capture (60 s)

Monitoring starts at a 1 s interval, with context `idle`. Idle power is the median GPU power
over this window; it becomes `idle_power_w` in every profile.

### 2. Solo profiling (60 s per workload)

Each workload runs **alone** on its MIG instance through the default scheduler, with context
`solo|<pod name>`. Afterwards its samples are read back from the CSV and summarized:

- **Active samples only:** samples with power ≥ idle + max(10 W, 2% of the power limit). If
  fewer than 8 qualify, all samples of the run are used. This drops pod start-up and tear-down.
- **CV:** population standard deviation divided by the mean.
- **Quantiles:** linear interpolation.

These are the definitions in `GPU_Power_Model/src/mig_power/extraction.py`, so the live
profiles match what the model was trained on.

### 3. Power-aware scheduling (co-location)

The workloads are submitted again, one after another. Each now runs for 180 s so that they
overlap. For each workload:

1. **Reconcile residents:** the node's `resident-profiles` annotation is rebuilt from the pods
   bound to the node that haven't finished. The extender decides from this annotation, so it
   must be current before every submission.
2. **Predict (for the printout):** the model's policy is evaluated locally on the same pod and
   node objects the scheduler will see.
3. **Submit:** the pod is created with `schedulerName: power-aware-scheduler` and its solo
   profile in the `gpu-power.myscheduler.com/solo-profile` annotation.
4. **Await decision:** the pod is polled until it is bound to a node or its `PodScheduled`
   condition turns `False`. The extender's per-node reasons appear in that condition's message.
5. **If bound:** wait until the pod is Running, so it really is resident for the next submission.
   **If rejected:** print the condition and the intended action, then delete the pod.

The monitoring context is `corun|<residents>+<pending>`, so the co-run power is recorded next to
each decision.

### 4. Report

Each decision is printed as `[scheduler]` lines, and every rejection gets a `[decision]` line:

| Scheduling condition | Printed action (not taken yet) |
| --- | --- |
| Risk ≥ threshold (`meets threshold`) | **POWER OVERLOAD predicted**: would defer the pod until a resident finishes, or place it on another GPU |
| Model contract error (e.g. 2+ residents, missing metadata) | **OUTSIDE MODEL DOMAIN** (fail-closed): would need a model for this co-location, or defer |
| `Insufficient nvidia.com/mig-…` | **NO FREE MIG INSTANCE**: would wait for one |
| No decision within 60 s | **NO DECISION**: check the scheduler and extender pods |

Finally, the script waits for the admitted co-located pods to finish, deletes them and resets
the resident annotation.

## Example run

These results come from a shortened validation run: 15 s idle, 25 s solo runs, 60 s co-runs.
Default MIG layout, A100-SXM4-40GB (power limit 400 W).

**Idle power:** 45.7 W.

**Solo profiles:**

| Workload | Power mean (W) | Power p95 (W) | Power CV | Clock p10 (MHz) | Max temp (°C) |
| --- | --- | --- | --- | --- | --- |
| `gpu-burn-3g-20gb` | 168.3 | 177.5 | 0.158 | 1410 | 48 |
| `gpu-burn-2g-10gb` | 140.4 | 144.3 | 0.109 | 1410 | 46 |
| `gpu-burn-1g-5gb` | 109.1 | 111.4 | 0.083 | 1410 | 41 |

**Scheduling decisions:**

```
Submitting gpu-burn-3g-20gb to power-aware-scheduler, resident on the GPU: none
  [scheduler] gpu-burn-3g-20gb: bound to minikube (model: first GPU workload on node)
Submitting gpu-burn-2g-10gb to power-aware-scheduler, resident on the GPU: ['gpu-burn-3g-20gb']
  [scheduler] gpu-burn-2g-10gb: bound to minikube (model: predicted harmful-pair risk 0.083333 is below threshold 0.500000)
Submitting gpu-burn-1g-5gb to power-aware-scheduler, resident on the GPU: ['gpu-burn-2g-10gb', 'gpu-burn-3g-20gb']
  [scheduler] gpu-burn-1g-5gb: PodScheduled=False reason=Unschedulable (model: power-model contract error: model supports one resident plus one pending workload; found 2 residents)
              0/1 nodes are available: 1 power-model contract error: model supports one resident plus one pending workload; found 2 residents. ...
  [decision]  OUTSIDE MODEL DOMAIN (fail-closed) -> would need a model for this co-location, or defer
```

What this shows:

1. **Empty GPU:** the first workload is admitted without a prediction.
2. **Pair:** the second is evaluated against the first; the predicted risk of 0.083 is below
   the 0.5 threshold, so it's admitted.
3. **Third workload:** rejected by the extender inside the real scheduler, because the model
   only covers pairs. The rejection surfaces as a standard `PodScheduled=False` condition.

## Outputs

- **Console:** idle power, each solo profile (JSON), and the scheduling decisions above.
- **`data/measures-power-model.csv`:** long-format monitoring samples
  (`timestamp,domain,metric,measure`) with `context` labels `idle`, `solo|…`, `between` and
  `corun|…`.


## Demo 

```bash
# Start minikube with MIG enabled and partitioned, and the power-aware scheduler deployed.
ubuntu@193-122-152-43:~/Power-Aware-MIG-Scheduler$ ./init/power-scheduler.sh 
[+] Building 0.2s (10/10) FINISHED                                                                                              docker:default
 => [internal] load build definition from Dockerfile                                                                                      0.0s
 => => transferring dockerfile: 406B                                                                                                      0.0s
 => [internal] load metadata for docker.io/library/python:3.12-slim                                                                       0.1s
 => [internal] load .dockerignore                                                                                                         0.0s
 => => transferring context: 2B                                                                                                           0.0s
 => [1/5] FROM docker.io/library/python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9                 0.0s
 => [internal] load build context                                                                                                         0.0s
 => => transferring context: 1.16kB                                                                                                       0.0s
 => CACHED [2/5] WORKDIR /app                                                                                                             0.0s
 => CACHED [3/5] COPY src /app/src                                                                                                        0.0s
 => CACHED [4/5] COPY scripts/run_scheduler_extender.py /app/scripts/run_scheduler_extender.py                                            0.0s
 => CACHED [5/5] COPY deploy/scheduler/model.json /models/model.json                                                                      0.0s
 => exporting to image                                                                                                                    0.0s
 => => exporting layers                                                                                                                   0.0s
 => => writing image sha256:aacd607fcef1573d618502f51c2fd1f4e61709374249e6bb4479f30805cd71f1                                              0.0s
 => => naming to docker.io/library/mig-power-extender:prototype                                                                           0.0s
namespace/mig-power-system unchanged
configmap/mig-power-model unchanged
deployment.apps/mig-power-extender configured
service/mig-power-extender unchanged
deployment.apps/mig-power-extender scaled
deployment.apps/mig-power-extender restarted
Waiting for deployment "mig-power-extender" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "mig-power-extender" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "mig-power-extender" rollout to finish: 1 old replicas are pending termination...
deployment "mig-power-extender" successfully rolled out
serviceaccount/power-aware-scheduler unchanged
clusterrolebinding.rbac.authorization.k8s.io/power-aware-scheduler-as-kube-scheduler unchanged
clusterrolebinding.rbac.authorization.k8s.io/power-aware-scheduler-as-volume-scheduler unchanged
rolebinding.rbac.authorization.k8s.io/power-aware-scheduler-extension-apiserver-authentication-reader unchanged
configmap/power-aware-scheduler-config unchanged
deployment.apps/power-aware-scheduler unchanged
deployment.apps/power-aware-scheduler restarted
Waiting for deployment "power-aware-scheduler" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "power-aware-scheduler" rollout to finish: 1 old replicas are pending termination...
deployment "power-aware-scheduler" successfully rolled out
Ready: pods with 'schedulerName: power-aware-scheduler' are placed through the GPU Power Model.
ubuntu@193-122-152-43:~/Power-Aware-MIG-Scheduler$ python3 exp-power-model-k8s.py 
Starting GPU Power Model scheduling experiment
MIG profiles found: {'nvidia.com/mig-1g.5gb': 2, 'nvidia.com/mig-2g.10gb': 1, 'nvidia.com/mig-3g.20gb': 1}
All pods deleted successfully.
Capturing idle for 60s
Idle power: 45.9 W
Profiling gpu-burn-3g-20gb alone on nvidia.com/mig-3g.20gb for 60s
  solo profile: {"id": "gpu-burn-3g-20gb", "gpu_name": "NVIDIA A100-SXM4-40GB", "mig_compute_slices": 3, "mig_memory_gb": 20, "idle_power_w": 45.878, "power_mean_w": 172.601, "power_p95_w": 178.915, "power_cv": 0.114017, "duty_above_90pct": 0.0, "clock_p10_mhz": 1410.0, "clock_cv": 0.005807, "temperature_max_c": 49.0, "active_samples": 83}
Profiling gpu-burn-2g-10gb alone on nvidia.com/mig-2g.10gb for 60s
  solo profile: {"id": "gpu-burn-2g-10gb", "gpu_name": "NVIDIA A100-SXM4-40GB", "mig_compute_slices": 2, "mig_memory_gb": 10, "idle_power_w": 45.878, "power_mean_w": 142.495, "power_p95_w": 145.033, "power_cv": 0.080549, "duty_above_90pct": 0.0, "clock_p10_mhz": 1410.0, "clock_cv": 0.061129, "temperature_max_c": 47.0, "active_samples": 82}
Profiling gpu-burn-1g-5gb alone on nvidia.com/mig-1g.5gb for 60s
  solo profile: {"id": "gpu-burn-1g-5gb", "gpu_name": "NVIDIA A100-SXM4-40GB", "mig_compute_slices": 1, "mig_memory_gb": 5, "idle_power_w": 45.878, "power_mean_w": 110.494, "power_p95_w": 111.884, "power_cv": 0.058259, "duty_above_90pct": 0.0, "clock_p10_mhz": 1410.0, "clock_cv": 0.0, "temperature_max_c": 42.0, "active_samples": 77}
Submitting gpu-burn-3g-20gb to power-aware-scheduler, resident on the GPU: none
  [scheduler] gpu-burn-3g-20gb: bound to minikube (model: first GPU workload on node)
Submitting gpu-burn-2g-10gb to power-aware-scheduler, resident on the GPU: ['gpu-burn-3g-20gb']
  [scheduler] gpu-burn-2g-10gb: bound to minikube (model: predicted harmful-pair risk 0.083333 is below threshold 0.500000)
Submitting gpu-burn-1g-5gb to power-aware-scheduler, resident on the GPU: ['gpu-burn-2g-10gb', 'gpu-burn-3g-20gb']
  [scheduler] gpu-burn-1g-5gb: PodScheduled=False reason=Unschedulable (model: power-model contract error: model supports one resident plus one pending workload; found 2 residents)
              0/1 nodes are available: 1 power-model contract error: model supports one resident plus one pending workload; found 2 residents. preemption: 0/1 nodes are available: 1 No preemption victims found for incoming pod.
  [decision]  OUTSIDE MODEL DOMAIN (fail-closed) -> would need a model for this co-location, or defer
Waiting for the co-located workloads to finish: ['gpu-burn-3g-20gb', 'gpu-burn-2g-10gb']
Exiting
ubuntu@193-122-152-43:~/Power-Aware-MIG-Scheduler$ 
```

## Requirements

- MIG enabled and partitioned: `./init/mig.sh enable`, then `./init/mig.sh create`.
- `init/minikube-gpu.sh` applied since the last `minikube start` (`mig.sh create` does it).
- The power-aware scheduler deployed: `./init/power-scheduler.sh`.
- dcgm-exporter on `:9400` with a 1 s refresh (`-c 1000`, as started by `init/setup.sh`).
- `../GPU_Power_Model` checked out, or `GPU_POWER_MODEL_DIR` set.

## Limitations and caveats

- **Nothing is acted on.** Conditions are only printed, and rejected pods are deleted. Deferring,
  requeueing or migrating pods is the next step.
- **Model scope.** The extender's model is a research prototype: a depth-1 tree trained on 20
  pairs, 3 of them harmful, all harmful cases on A100-80GB. Its only split is on mean solo power
  CV (≤ 0.0356 → risk 0.5, otherwise 0.083). Its own documentation recommends shadow-mode
  evaluation before enforcing decisions. This A100-40GB is not in its training data.
- **Sensitivity to monitoring.** Because power CV decides the outcome, sampling quality matters.
  With dcgm-exporter's default 30 s refresh, every sample in a run was identical, CV came out as
  0, and every pair was rejected as overload. The 1 s refresh fixes this.
- **The active-sample filter keeps ramp-up samples**, as the training definition does, which
  raises power CV for short runs. The shortened validation run above is more affected than the
  default 60 s runs.
- **Single node, single GPU.** "Place it on another GPU" can't happen here; with more nodes, the
  extender's Prioritize scores would rank them.
- **Only `gpu_burn` workloads.** They are near-constant power loads. Other workloads from
  `workloads/` (Blender, HPCG, Llama, YOLO) can be added to the candidate list for more varied
  profiles.
- **Inventory is reconciled by the experiment script**, synchronously before each submission,
  not by a controller. That's sufficient for sequential submissions, not for concurrent ones.
