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
./init/k8s.sh         # single-node minikube + NVIDIA GPU Operator (time-slicing experiments)
./init/mig.sh enable  # enable MIG mode on every GPU (MIG experiments; needs ./init/k8s.sh first)
```

`init/setup.sh` and `init/k8s.sh` are safe to re-run (each step is a no-op if already done).
`init/mig.sh status` shows current MIG mode per GPU; toggling mode can require a `sudo reboot`
if the hypervisor refuses a live GPU reset — see the script's comments.

IPMI (`ipmitool`) is intentionally **not** installed: cloud VMs have no BMC, and
`monitoring.IPMIMonitor` detects this and reports no IPMI metrics instead of failing the run.

## 3. Running an experiment

```bash
python3 exp-timeslices.py            # time-slicing, worst-case power (gpu_burn only)
python3 exp-perf-timeslice-k8s.py    # time-slicing, performance (Blender/HPCG/Llama/YOLO)
python3 exp-mig-k8s.py               # MIG partitioning, worst-case power (gpu_burn only)
```

Each writes its monitoring CSV to `data/` (e.g. `data/measures-timeslices.csv`) and, for the
benchmark script, per-run results under `bench-res/`. `BENCH_RESULT_DIR` and `HF_CACHE_DIR`
env vars override the default `bench-res/` and `~/.cache/huggingface/` paths.

A quick smoke test that only exercises the scheduler (4 short `gpu_burn` Pods, no monitoring):

```bash
python3 -m k8s
```
