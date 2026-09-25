"""Solo-run profiles for the GPU Power Model, computed from a MonitorWrapper CSV.

The GPU Power Model (../GPU_Power_Model, scheduler extender) predicts whether co-locating two
MIG workloads overloads the GPU from each workload's *solo-run summary*: power mean/p95/CV,
duty above 90% of the power limit, SM clock p10/CV, max temperature, plus idle power and MIG
geometry. This module rebuilds that summary from the samples our monitors already record, with
the same definitions the model's training data used (GPU_Power_Model
src/mig_power/extraction.py: summarize_experiment()):

- samples are restricted to "active" ones, power >= idle + max(10 W, 2% of the power limit),
  falling back to all samples of the run if fewer than 8 are active;
- CV is the population standard deviation over the mean; quantiles interpolate linearly.
"""
import csv, math, re, statistics

POWER_METRIC = 'DCGM_DCGM_FI_DEV_POWER_USAGE'
CLOCK_METRIC = 'DCGM_DCGM_FI_DEV_SM_CLOCK'
TEMPERATURE_METRIC = 'DCGM_DCGM_FI_DEV_GPU_TEMP'
CONTEXT_METRIC = 'CONST_context'

ACTIVE_INCREMENT_MIN_W = 10.0
ACTIVE_INCREMENT_FRACTION = 0.02
MINIMUM_ACTIVE_SAMPLES = 8

def read_context_samples(csv_path: str, context: str, domain: str = 'GPU0') -> dict:
    """Returns {metric: [values]} for `domain` over every sampling tick labeled `context`
    (the 'context' label injected with MonitorWrapper.update_monitoring into a ConstMonitor).
    """
    samples, current = {}, None
    with open(csv_path, newline='') as f:
        for row in csv.DictReader(f):
            if row['metric'] == CONTEXT_METRIC:
                current = row['measure']  # ConstMonitor rows come first in each tick
                continue
            if current != context or row['domain'] != domain: continue
            try:
                samples.setdefault(row['metric'], []).append(float(row['measure']))
            except ValueError:
                pass
    return samples

def _quantile(values: list, q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

def _cv(values: list) -> float:
    mean = statistics.fmean(values)
    return statistics.pstdev(values) / abs(mean) if mean else 0.0

def idle_power(csv_path: str, context: str = 'idle', domain: str = 'GPU0') -> float:
    """Median GPU power over the `context` ticks (an idle capture)."""
    power = read_context_samples(csv_path, context, domain).get(POWER_METRIC, [])
    if not power:
        raise ValueError(f'no {POWER_METRIC} samples labeled {context!r} in {csv_path}')
    return statistics.median(power)

def mig_geometry(mig_resource: str) -> tuple:
    """(compute slices, memory GB) of a MIG profile, e.g. 'nvidia.com/mig-3g.20gb' -> (3, 20)."""
    match = re.search(r'(\d+)g\.(\d+)gb', mig_resource)
    if not match:
        raise ValueError(f'not a MIG profile resource: {mig_resource!r}')
    return int(match.group(1)), int(match.group(2))

def summarize_solo_profile(samples: dict, profile_id: str, gpu_name: str, mig_resource: str,
                           idle_power_w: float, power_limit_w: float) -> dict:
    """Solo-profile JSON object in the GPU Power Model's `gpu-power.myscheduler.com/solo-profile`
    annotation schema, from read_context_samples() output for one solo run.
    """
    power = samples.get(POWER_METRIC, [])
    clocks = samples.get(CLOCK_METRIC, [])
    temperatures = samples.get(TEMPERATURE_METRIC, [])
    if not power:
        raise ValueError(f'no power samples for {profile_id}')

    # Same activity filter as the training data: drop pod start-up/tear-down ticks
    threshold = idle_power_w + max(ACTIVE_INCREMENT_MIN_W, ACTIVE_INCREMENT_FRACTION * power_limit_w)
    active = [i for i, value in enumerate(power) if value >= threshold]
    if len(active) < MINIMUM_ACTIVE_SAMPLES:
        active = list(range(len(power)))
    power = [power[i] for i in active]
    clocks = [clocks[i] for i in active if i < len(clocks)]
    temperatures = [temperatures[i] for i in active if i < len(temperatures)]

    slices, memory_gb = mig_geometry(mig_resource)
    return {
        'id': profile_id,
        'gpu_name': gpu_name,
        'mig_compute_slices': slices,
        'mig_memory_gb': memory_gb,
        'idle_power_w': round(idle_power_w, 3),
        'power_mean_w': round(statistics.fmean(power), 3),
        'power_p95_w': round(_quantile(power, 0.95), 3),
        'power_cv': round(_cv(power), 6),
        'duty_above_90pct': round(sum(value >= 0.90 * power_limit_w for value in power) / len(power), 6),
        'clock_p10_mhz': round(_quantile(clocks, 0.10), 3) if clocks else float('nan'),
        'clock_cv': round(_cv(clocks), 6) if clocks else float('nan'),
        'temperature_max_c': max(temperatures) if temperatures else float('nan'),
        'active_samples': len(power),
    }
