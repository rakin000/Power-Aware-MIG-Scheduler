# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Power-Aware MIG Scheduler: a Kubernetes-based framework for running GPU-sharing experiments
(NVIDIA MIG partitioning, GPU time-slicing) on a Lambda.ai A100/H100 instance, and collecting
per-condition power/performance metrics (DCGM, IPMI, CPU) while doing it. It targets a
**single-node** cluster: one Lambda VM running minikube + the NVIDIA GPU Operator. It has no
figure-generation or paper-artifact code — it only drives the cluster and writes raw CSVs.

Everything here is pure-stdlib Python (`subprocess`, `threading`, `json`, ...); there is no
`requirements.txt` and nothing to `pip install` to run it. What it does need at runtime:
`kubectl`/`minikube` on PATH, a `dcgm-exporter` reachable at `http://localhost:9400/metrics`,
and (for MIG experiments) MIG mode enabled on the node's GPUs.

## Commands

There is no build step, linter, or test suite. Provisioning (from a fresh Lambda instance):
```bash
./init/setup.sh       # docker + nvidia-container-toolkit + dcgm-exporter + benchmark images
./init/k8s.sh          # single-node minikube + NVIDIA GPU Operator
./init/mig.sh enable   # enable MIG mode on every GPU (only needed for exp-mig-k8s.py; may need a reboot)
./init/mig.sh create   # create MIG instances + restart minikube (again after every reboot)
```
GPUs are advertised to pods by minikube's `nvidia-device-plugin` addon (not the GPU Operator's
device plugin); `k8s.sh`/`mig.sh create` set its `MIG_STRATEGY=mixed` so MIG instances show up
as `nvidia.com/mig-<profile>` resources. minikube must be restarted after (re)partitioning, since
its container only sees the MIG device nodes that existed when it started.

Running an experiment (each is standalone, invoked directly with `python3` from the repo root):
```bash
python3 exp-timeslices.py            # time-slicing, worst-case power (gpu_burn)
python3 exp-perf-timeslice-k8s.py    # time-slicing, performance (Blender/HPCG/Llama/YOLO)
python3 exp-mig-k8s.py               # MIG partitioning, worst-case power (gpu_burn)
```
Each does `from monitoring import *`, `from k8s import *`, `from workloads import *` as local
package imports (so must be run from the repo root), and expects `data/` and `bench-res/` output
directories to already exist there (they're checked into the repo as empty placeholders).

A scheduler-only smoke test with no monitoring: `python3 -m k8s` (from the repo root).

## Architecture

Three small plugin-style packages, each with a base `*Agent`/`*Wrapper` interface implemented
by concrete classes, imported via each package's `__init__.py`:

- **`monitoring/`** — `MonitorAgent` subclasses (`DCGMMonitor`, `SMIMonitor` for `nvidia-smi`,
  `IPMIMonitor`, `CPUMonitor`, `ConstMonitor` for injecting constant experiment-condition
  labels) each implement `discover()`/`query_metrics()`/`get_label()`/`update()`.
  `MonitorWrapper` runs all configured monitors on a background thread at a fixed interval,
  appending long-format rows (`timestamp,domain,metric,measure`) to a single output CSV.
  `update_monitoring(...)` lets the main experiment thread inject a new label (e.g. current
  condition under test) into `ConstMonitor` mid-run, optionally resetting the elapsed-time
  clock (`reset_launch`). `IPMIMonitor` degrades to reporting nothing (rather than aborting)
  when there's no BMC to query, which is the normal case on a cloud VM.
- **`k8s/`** — cluster orchestration: `KubectlWrapper` wraps `kubectl` for time-slicing
  oversubscription policy, GPU/MIG resource discovery (`get_allocatable_gpu_resources()`,
  `get_mig_resources()`), and generic Pod apply/status/delete/logs. `KubernetesScheduler`
  batches `PodJob`s (name + a `WorkloadAgent` + its kwargs + which GPU resource to request,
  e.g. `nvidia.com/gpu` or a MIG profile like `nvidia.com/mig-1g.10gb`) into one manifest,
  applies it, polls until every pod reaches a terminal phase (or a timeout elapses), then
  tears down — see `k8s/scheduler.py`'s docstring.
- **`workloads/`** — `WorkloadAgent` subclasses (`WorkloadBurn` = gpu-burn stress test,
  `WorkloadBlender`, `WorkloadHpcg`, `WorkloadInferenceLlama`, `WorkloadTrainingYolo`), each
  implementing `pod_spec(**args) -> dict` (image/command/volumes) that `KubernetesScheduler`
  turns into a Pod manifest. A workload knows nothing about GPU/MIG resource requests — that's
  set per-launch on the `PodJob`, not baked into the workload.

Each top-level `exp-*.py` script composes these three packages: it uses `KubectlWrapper` to set
up the cluster for one experiment condition (oversubscription policy, or nothing extra for MIG
since profiles are already exposed by the device plugin once `mig.sh create` has run), starts a
`MonitorWrapper`, sweeps a grid of conditions (updating monitor labels between them), and for
each condition builds a batch of `PodJob`s and hands them to `KubernetesScheduler.run()`, which
blocks until they finish before the script moves to the next condition.

`init/` holds shell scripts (`setup.sh`, `k8s.sh`, `build-images.sh`, `mig.sh`) and Dockerfiles
for provisioning a Lambda.ai host and its benchmark images (`init/bench/<name>/`) — not Python,
not imported by the experiment scripts, just setup tooling referenced from the root `README.md`.

### Data flow

`exp-*.py` → `KubectlWrapper`/`KubernetesScheduler` drive the cluster → raw monitoring CSV in
`data/` (e.g. `data/measures-timeslices.csv`) and per-run benchmark results in `bench-res/`.
Both are empty placeholders (`.gitkeep`) in a fresh checkout; nothing in this repo consumes
those CSVs further (no plotting/analysis code is kept here).
