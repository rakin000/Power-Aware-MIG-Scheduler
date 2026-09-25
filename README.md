# Power-Aware MIG Scheduler

Tools to run GPU-sharing experiments — NVIDIA MIG partitioning and time-slicing — on a
single-node Kubernetes cluster (minikube) on a Lambda.ai A100/H100 instance, to collect
per-condition power/performance metrics (DCGM, IPMI, CPU) while doing it, and to place MIG
workloads through the [GPU Power Model](../GPU_Power_Model)'s power-overload predictor running
as a kube-scheduler extender.

There is no figure-generation or data-analysis code here: this repo drives the cluster and
writes raw long-format CSVs (`timestamp,domain,metric,measure`) to `data/` and per-benchmark
result CSVs to `bench-res/`. Everything runs on Python's standard library — no `pip install`
needed for the code in this repo.

## 1. Project structure

```
.
├── exp-timeslices.py            # Worst-case power vs. time-slicing oversubscription (gpu_burn)
├── exp-perf-timeslice-k8s.py    # Performance vs. time-slicing oversubscription (real benchmarks)
├── exp-mig-k8s.py               # Worst-case power vs. MIG profile + instance count (gpu_burn)
├── exp-power-model-k8s.py       # Run + monitor MIG workloads, schedule them through the GPU Power Model
├── k8s/                         # Cluster orchestration: KubectlWrapper, KubernetesScheduler, PodJob,
│                                #   PowerAwareScheduler (GPU Power Model inventory/submission)
├── workloads/                   # What to run in each Pod: WorkloadAgent and its subclasses
├── monitoring/                  # What to measure while it runs: DCGM/IPMI/SMI/CPU monitors,
│                                #   solo_profile.py (monitored samples -> GPU Power Model profile)
├── init/                        # Provisioning scripts for a Lambda.ai instance + benchmark Dockerfiles
├── data/                        # Monitor CSV output (empty in a fresh checkout)
└── bench-res/                   # Benchmark result CSV output (empty in a fresh checkout)
```

Each `exp-*.py` script composes the three packages: it uses `k8s.KubectlWrapper` to configure
the cluster (MIG mode / time-slicing oversubscription policy) for one experiment condition,
starts a `monitoring.MonitorWrapper` to record metrics in the background, then uses
`k8s.KubernetesScheduler` to launch a batch of `workloads.WorkloadAgent` Pods for that
condition and block until they finish, before moving to the next condition. See each
package's docstrings (`k8s/scheduler.py`, `k8s/power_scheduler.py`, `workloads/workload_agent.py`)
for the object model.

## 2. Setting up a Lambda.ai instance

Provision an A100/H100 instance on [lambda.ai](https://lambda.ai), then from this repo:

```bash
git clone <this repo> && cd Power-Aware-MIG-Scheduler
./init/setup.sh      # docker + nvidia-container-toolkit + dcgm-exporter + benchmark images
./init/k8s.sh         # single-node minikube + its NVIDIA device plugin (MIG "mixed" mode)
```

`init/setup.sh` and `init/k8s.sh` are safe to re-run. If `setup.sh` adds you to the `docker`
group, log out and back in before continuing.

GPUs are advertised to pods by minikube's own `nvidia-device-plugin` addon. The NVIDIA GPU
Operator is **not** used: on minikube its container toolkit breaks per-device GPU injection and it
deletes the addon's device plugin. `init/minikube-gpu.sh` (run by `k8s.sh` and `mig.sh create`)
applies the node-level fixes MIG needs; see its header. **Re-run it after every `minikube start`.**

GPU metrics are scraped from the standalone `dcgm-exporter` container that `setup.sh` starts on
`:9400` with a 1 s refresh (check with `curl -s localhost:9400/metrics | head`). IPMI (`ipmitool`)
is intentionally **not** installed: cloud VMs have no BMC, and `monitoring.IPMIMonitor` detects
this and reports no IPMI metrics instead of failing the run.

## 3. Running an experiment

All commands run from the repo root. Each experiment prints the condition it is on and blocks
until the whole sweep is done; `Ctrl-C` stops it cleanly and keeps the CSV written so far.

### 3.1 MIG setup (for `exp-mig-k8s.py` and `exp-power-model-k8s.py`)

**1. Enable MIG mode** (once per instance):

```bash
./init/mig.sh enable
./init/mig.sh status     # mig.mode.current must read "Enabled"
```

On a Lambda VM the GPU reset is usually refused, leaving MIG `Pending`: run `sudo reboot`,
then after the reboot `minikube start` and `./init/mig.sh status`. MIG mode then stays on
across reboots.

**2. Create MIG instances** (after every reboot, since MIG instances don't survive one):

```bash
./init/mig.sh create                 # default layout 9,14,19,19 = 3g.20gb + 2g.10gb + 2x 1g.5gb on A100-40GB
./init/mig.sh create 19,19,19,19,19,19,19   # or any layout: profile IDs/names from `nvidia-smi mig -lgip`
```

This partitions every GPU, then restarts minikube and re-applies `init/minikube-gpu.sh` so the
node and its device plugin see the new instances, and prints the node's allocatable resources.
Check that they include `nvidia.com/mig-*` entries, e.g.:

```
"nvidia.com/mig-1g.5gb":"2","nvidia.com/mig-2g.10gb":"1","nvidia.com/mig-3g.20gb":"1"
```

You can check again at any time with
`minikube kubectl -- get node minikube -o jsonpath='{.status.allocatable}'`.

### 3.2 MIG power sweep (`exp-mig-k8s.py`)

```bash
python3 exp-mig-k8s.py
```

It captures 5 min of idle, then for each MIG profile the node advertises runs 1..N concurrent
`gpu_burn` pods on that profile (N = number of instances of that profile), 5 min per step. With
the default layout that's `idle`, `1g.5gb|1`, `1g.5gb|2`, `2g.10gb|1`, `3g.20gb|1`, about 25 min
in total. Metrics go to `data/measures-mig-k8s.csv`, with the current step in the `context`
label. Don't run `./init/mig.sh create`/`destroy` while it runs: both restart minikube.

### 3.3 Power-aware scheduling with the GPU Power Model (`exp-power-model-k8s.py`)

Needs the MIG setup (3.1) and the [GPU Power Model](../GPU_Power_Model) repository checked out
next to this one (or `GPU_POWER_MODEL_DIR=/path/to/it`). Deploy the scheduler once:

```bash
./init/power-scheduler.sh
```

This builds the model repository's scheduler extender (`deploy/scheduler/Dockerfile`, i.e.
`scripts/run_scheduler_extender.py` + `model.json`) into minikube, deploys it with the model's
`deploy/scheduler/extender.yaml`, and starts a second kube-scheduler named
`power-aware-scheduler` (`init/power-scheduler/scheduler.yaml`) that calls it on every
Filter/Prioritize. Only pods with `schedulerName: power-aware-scheduler` go through it.

Then:

```bash
python3 exp-power-model-k8s.py
```

1. **Run + monitor**: captures idle, then runs one `gpu_burn` alone on each MIG profile
   (largest first), sampling DCGM power/SM clock/temperature every second into
   `data/measures-power-model.csv`.
2. **Profile**: turns each solo run's monitored samples into the model's solo profile (power
   mean/p95/CV, duty above 90% of the cap, clock p10/CV, max temperature, idle power, MIG
   geometry; `monitoring/solo_profile.py`, same definitions as the model's training data).
3. **Schedule**: submits the workloads again one after another to `power-aware-scheduler`, each
   carrying its profile. Before each submission the node's resident-workload annotation is
   rebuilt from the pods actually running, so the extender predicts the risk of the pending pod
   next to what is already on the GPU and filters the node out if the risk meets its threshold.
4. **Report**: prints what the scheduler decided and, for every scheduling condition, what we
   would do. Nothing is acted on yet: rejected pods are deleted.

Example output (default MIG layout, ~8 min):

```
Submitting gpu-burn-3g-20gb to power-aware-scheduler, resident on the GPU: none
  [scheduler] gpu-burn-3g-20gb: bound to minikube (model: first GPU workload on node)
Submitting gpu-burn-2g-10gb to power-aware-scheduler, resident on the GPU: ['gpu-burn-3g-20gb']
  [scheduler] gpu-burn-2g-10gb: bound to minikube (model: predicted harmful-pair risk 0.083333 is below threshold 0.500000)
Submitting gpu-burn-1g-5gb to power-aware-scheduler, resident on the GPU: ['gpu-burn-2g-10gb', 'gpu-burn-3g-20gb']
  [scheduler] gpu-burn-1g-5gb: PodScheduled=False reason=Unschedulable (model: power-model contract error: ...found 2 residents)
  [decision]  OUTSIDE MODEL DOMAIN (fail-closed) -> would need a model for this co-location, or defer
```

The conditions reported are `POWER OVERLOAD predicted` (risk ≥ threshold), `OUTSIDE MODEL
DOMAIN` (the model only covers one resident + one pending workload, and fails closed on
anything else), and `NO FREE MIG INSTANCE`. The model is a research prototype trained on 20
pairs (see the GPU Power Model's `deploy/scheduler/README.md`); treat its decisions accordingly.

### 3.4 Time-slicing (`exp-timeslices.py`, `exp-perf-timeslice-k8s.py`)

> **Not working on this setup yet.** `KubectlWrapper.set_kube_replicas_policy()` applies the
> oversubscription policy through the GPU Operator's `ClusterPolicy`, and the GPU Operator is no
> longer installed (section 2). Time-slicing would have to be configured on minikube's device
> plugin instead.

These need whole GPUs, so turn MIG off first (may also need a `sudo reboot`, as above):

```bash
./init/mig.sh disable
python3 exp-timeslices.py            # worst-case power (gpu_burn only) -> data/measures-timeslices.csv
python3 exp-perf-timeslice-k8s.py    # performance (Blender/HPCG/Llama/YOLO) -> data/ + bench-res/
```

`BENCH_RESULT_DIR` and `HF_CACHE_DIR` env vars override the default `bench-res/` and
`~/.cache/huggingface/` paths.

A quick smoke test that only exercises the scheduler (4 short `gpu_burn` Pods on whole GPUs, no
monitoring, so MIG must be off):

```bash
python3 -m k8s
```

### 3.5 Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No MIG resources advertised by the cluster` | `./init/mig.sh status` → instances listed? If not, `./init/mig.sh create`. If they are, `./init/minikube-gpu.sh`. |
| MIG resources listed with count `0`, device plugin pod in `CrashLoopBackOff` | minikube was restarted: `./init/minikube-gpu.sh` |
| Pods stuck `Pending` | Requested resource not advertised: check the node's allocatable resources (see 3.1). |
| `minikube status` shows `Stopped` after a reboot | `minikube start`, then `./init/mig.sh create` |
| `power-aware-scheduler is not running` | `./init/power-scheduler.sh` |
| Every profile has `power_cv` 0 | dcgm-exporter is refreshing every 30 s: restart it with `-c 1000` (re-run the exporter step of `init/setup.sh`). |
| DCGM columns missing from the CSV | `docker ps` should list `dcgm-exporter`; otherwise re-run the exporter step of `init/setup.sh`. |
