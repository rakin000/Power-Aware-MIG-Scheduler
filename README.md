# Power-Aware MIG Scheduler

Tools to run GPU-sharing experiments — NVIDIA MIG partitioning and time-slicing — on a
single-node Kubernetes cluster (minikube + NVIDIA GPU Operator) on a Lambda.ai A100/H100
instance, and to collect per-condition power/performance metrics (DCGM, IPMI, CPU) while
doing it.

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
├── k8s/                         # Cluster orchestration: KubectlWrapper, KubernetesScheduler, PodJob
├── workloads/                   # What to run in each Pod: WorkloadAgent and its subclasses
├── monitoring/                  # What to measure while it runs: DCGM/IPMI/SMI/CPU monitors
├── init/                        # Provisioning scripts for a Lambda.ai instance + benchmark Dockerfiles
├── data/                        # Monitor CSV output (empty in a fresh checkout)
└── bench-res/                   # Benchmark result CSV output (empty in a fresh checkout)
```

Each `exp-*.py` script composes the three packages: it uses `k8s.KubectlWrapper` to configure
the cluster (MIG mode / time-slicing oversubscription policy) for one experiment condition,
starts a `monitoring.MonitorWrapper` to record metrics in the background, then uses
`k8s.KubernetesScheduler` to launch a batch of `workloads.WorkloadAgent` Pods for that
condition and block until they finish, before moving to the next condition. See each
package's docstrings (`k8s/scheduler.py`, `workloads/workload_agent.py`) for the object model.

## 2. Setting up a Lambda.ai instance

Provision an A100/H100 instance on [lambda.ai](https://lambda.ai), then from this repo:

```bash
git clone <this repo> && cd Power-Aware-MIG-Scheduler
./init/setup.sh      # docker + nvidia-container-toolkit + dcgm-exporter + benchmark images
./init/k8s.sh         # single-node minikube + NVIDIA GPU Operator + device plugin in MIG "mixed" mode
```

`init/setup.sh` and `init/k8s.sh` are safe to re-run. If `setup.sh` adds you to the `docker`
group, log out and back in before continuing.

GPU metrics are scraped from the standalone `dcgm-exporter` container that `setup.sh` starts on
`:9400` (check with `curl -s localhost:9400/metrics | head`). IPMI (`ipmitool`) is intentionally
**not** installed: cloud VMs have no BMC, and `monitoring.IPMIMonitor` detects this and reports
no IPMI metrics instead of failing the run.

## 3. Running an experiment

All commands run from the repo root. Each experiment prints the condition it is on and blocks
until the whole sweep is done; `Ctrl-C` stops it cleanly and keeps the CSV written so far.

### 3.1 MIG partitioning (`exp-mig-k8s.py`)

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

This partitions every GPU, then restarts minikube so its container and device plugin see the new
instances, and prints the node's allocatable resources. Check that they include
`nvidia.com/mig-*` entries, e.g.:

```
"nvidia.com/mig-1g.5gb":"2","nvidia.com/mig-2g.10gb":"1","nvidia.com/mig-3g.20gb":"1"
```

You can check again at any time with
`minikube kubectl -- get node minikube -o jsonpath='{.status.allocatable}'`.

**3. Run the sweep:**

```bash
python3 exp-mig-k8s.py
```

It captures 5 min of idle, then for each MIG profile the node advertises runs 1..N concurrent
`gpu_burn` pods on that profile (N = number of instances of that profile), 5 min per step. With
the default layout that's `idle`, `1g.5gb|1`, `1g.5gb|2`, `2g.10gb|1`, `3g.20gb|1`, about 25 min
in total. Metrics go to `data/measures-mig-k8s.csv`, with the current step in the `context`
label. Don't run `./init/mig.sh create`/`destroy` while it runs: both restart minikube.

### 3.2 Time-slicing (`exp-timeslices.py`, `exp-perf-timeslice-k8s.py`)

> **Not yet verified on this setup.** `KubectlWrapper.set_kube_replicas_policy()` applies the
> oversubscription policy through the GPU Operator's `ClusterPolicy` in the `gpu-operator`
> namespace, but on minikube the GPUs are advertised by minikube's own device-plugin addon (see
> `init/k8s.sh`), so the policy may have no effect.

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

### 3.3 Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No MIG resources advertised by the cluster` | `./init/mig.sh status` → instances listed? If not, `./init/mig.sh create`. If they are, re-run `./init/mig.sh create` to restart minikube and the device plugin. |
| Pods stuck `Pending` | Requested resource not advertised: check the node's allocatable resources (see 3.1). |
| `minikube status` shows `Stopped` after a reboot | `minikube start` |
| DCGM columns missing from the CSV | `docker ps` should list `dcgm-exporter`; otherwise re-run the exporter step of `init/setup.sh`. |
