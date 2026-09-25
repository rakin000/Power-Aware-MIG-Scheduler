import subprocess
import json
import re

class KubectlWrapper(object):
    """Low-level cluster operations: oversubscription policy, GPU/MIG resource
    discovery, and generic Pod apply/delete/status. It knows nothing about specific
    workloads/images — that's workloads/workload_*.py — nor how to batch and wait on
    a set of pods for one experiment condition — that's k8s/scheduler.py.
    """

    def __init__(self, prefix_command: list = ['minikube', 'kubectl', '--']):
        self.prefix_command = prefix_command

    def set_kube_replicas_policy(self, replicas: int, namespace: str = 'gpu-operator', config_name: str = 'oversub-all'):
        config_yaml = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {config_name}
data:
  any: |-
    version: v1
    flags:
      migStrategy: none
    sharing:
      timeSlicing:
        resources:
        - name: nvidia.com/gpu
          replicas: {replicas}
"""
        process = subprocess.run(
            self.prefix_command + ['apply', '-n', namespace, '-f', '-'],
            input=config_yaml,
            text=True,
            capture_output=True
        )

        if process.returncode == 0:
            print('ConfigMap updated successfully.')
        else:
            print('Error updating ConfigMap:', process.stderr)

    def patch_cluster_policy(self, namespace: str = 'gpu-operator', policy_name: str = 'cluster-policy', config_name: str = 'oversub-all-2', default_value: str = 'any'):
        patch_data = f'{{"spec": {{"devicePlugin": {{"config": {{"name": "{config_name}", "default": "{default_value}"}}}}}}}}'
        process = subprocess.run(
            self.prefix_command + ['patch', f'clusterpolicies.nvidia.com/{policy_name}', '-n', namespace, '--type', 'merge', '-p', patch_data],
            text=True,
            capture_output=True
        )

        if process.returncode == 0:
            print('Cluster policy patched successfully.')
        else:
            print('Error patching cluster policy:', process.stderr)

    def get_current_oversub_policy(self):
        process = subprocess.run(
            self.prefix_command + ['describe', 'nodes'],
            text=True,
            capture_output=True
        )
        if process.returncode != 0:
            print('Error retrieving node description:', process.stderr)
            return None

        match = re.search(r'nvidia.com/gpu\.replicas=(\d+)', process.stdout)
        if match:
            return int(match.group(1))

        print('No replicas information found.')
        return None

    def get_gpu_instance_count(self):
        process = subprocess.run(
            self.prefix_command + ['describe', 'nodes'],
            text=True,
            capture_output=True
        )
        if process.returncode != 0:
            print('Error retrieving node description:', process.stderr)
            return None

        match = re.search(r'nvidia.com/gpu:\s+(\d+)', process.stdout)
        if match:
            return int(match.group(1))

        print('No GPU instance information found.')
        return None

    def get_allocatable_gpu_resources(self, node: str = None) -> dict:
        """Returns {resource_name: allocatable_count} for every nvidia.com/gpu* resource
        advertised by `node` (or summed across all nodes if `node` is None) — e.g.
        {'nvidia.com/gpu': 4} on a whole-GPU/time-sliced node, or
        {'nvidia.com/mig-1g.10gb': 28, 'nvidia.com/mig-3g.40gb': 4} on a MIG-partitioned one.
        """
        cmd = ['get', 'node', node, '-o', 'json'] if node is not None else ['get', 'nodes', '-o', 'json']
        process = subprocess.run(self.prefix_command + cmd, text=True, capture_output=True)
        if process.returncode != 0:
            print('Error retrieving node resources:', process.stderr)
            return {}
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError:
            return {}
        items = payload['items'] if 'items' in payload else [payload]  # `get node <name>` returns a bare Node, not a List
        resources = {}
        for item in items:
            for name, value in item.get('status', {}).get('allocatable', {}).items():
                if not name.startswith('nvidia.com/'): continue
                resources[name] = resources.get(name, 0) + int(value)
        return resources

    def get_mig_resources(self, node: str = None) -> dict:
        """Subset of get_allocatable_gpu_resources() restricted to MIG profile resources
        (nvidia.com/mig-<profile>, e.g. 'nvidia.com/mig-1g.10gb'), as exposed by the GPU
        Operator's device plugin once the node's MIG mode is enabled and its strategy is
        'mixed' (see init/mig.sh and init/k8s.sh).
        """
        return {name: count for name, count in self.get_allocatable_gpu_resources(node).items()
                if name.startswith('nvidia.com/mig-')}

    def apply_manifest(self, manifest_yaml: str, namespace: str = 'default') -> bool:
        """Apply one or more (`---`-separated) resource manifests."""
        process = subprocess.run(
            self.prefix_command + ['apply', '-n', namespace, '-f', '-'],
            input=manifest_yaml,
            text=True,
            capture_output=True
        )
        if process.returncode != 0:
            print('Error applying manifest:', process.stderr)
        return process.returncode == 0

    def get_pod_phases(self, pod_names: list, namespace: str = 'default') -> dict:
        """Returns {pod_name: phase}, e.g. Pending/Running/Succeeded/Failed.
        A pod missing from the API response (not yet scheduled, or already
        garbage-collected) is reported as None.
        """
        if not pod_names: return {}
        process = subprocess.run(
            self.prefix_command + ['get', 'pods'] + pod_names + ['-n', namespace, '-o', 'json'],
            text=True,
            capture_output=True
        )
        phases = {name: None for name in pod_names}
        if process.returncode != 0:
            # kubectl still prints the pods it did find on stdout even if some are missing
            print('Warning while fetching pod status:', process.stderr.strip())
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError:
            return phases
        items = payload['items'] if 'items' in payload else [payload]  # single `get <name>` returns a bare Pod, not a List
        for item in items:
            name = item.get('metadata', {}).get('name')
            phase = item.get('status', {}).get('phase')
            if name: phases[name] = phase
        return phases

    def get_object(self, kind: str, name: str, namespace: str = 'default') -> dict:
        """Full API object (e.g. kind 'pod' or 'node') as a dict, or None if it can't be read."""
        process = subprocess.run(
            self.prefix_command + ['get', kind, name, '-n', namespace, '-o', 'json'],
            text=True,
            capture_output=True
        )
        if process.returncode != 0: return None
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError:
            return None

    def list_pods(self, namespace: str = 'default') -> list:
        """All Pod objects in `namespace`."""
        process = subprocess.run(
            self.prefix_command + ['get', 'pods', '-n', namespace, '-o', 'json'],
            text=True,
            capture_output=True
        )
        if process.returncode != 0:
            print('Error listing pods:', process.stderr)
            return []
        try:
            return json.loads(process.stdout).get('items', [])
        except json.JSONDecodeError:
            return []

    def annotate_node(self, node: str, annotations: dict) -> bool:
        """Sets (overwrites) string annotations on `node`."""
        process = subprocess.run(
            self.prefix_command + ['annotate', 'node', node, '--overwrite']
            + [f'{key}={value}' for key, value in annotations.items()],
            text=True,
            capture_output=True
        )
        if process.returncode != 0:
            print('Error annotating node:', process.stderr)
        return process.returncode == 0

    def get_pod_logs(self, pod_name: str, namespace: str = 'default') -> str:
        process = subprocess.run(
            self.prefix_command + ['logs', pod_name, '-n', namespace],
            text=True,
            capture_output=True
        )
        return process.stdout if process.returncode == 0 else process.stderr

    def delete_pods(self, pod_names: list, namespace: str = 'default'):
        if not pod_names: return
        process = subprocess.run(
            self.prefix_command + ['delete', 'pod'] + pod_names + ['-n', namespace, '--ignore-not-found'],
            text=True,
            capture_output=True
        )
        if process.returncode != 0:
            print('Error deleting pods:', process.stderr)

    def destroy_all_pods(self, namespace: str = 'default'):
        process = subprocess.run(
            self.prefix_command + ['delete', 'pods', '--all', '-n', namespace],
            text=True,
            capture_output=True
        )

        if process.returncode == 0:
            print('All pods deleted successfully.')
        else:
            print('Error deleting pods:', process.stderr)
