from .workload_agent import WorkloadAgent

class WorkloadInferenceLlama(WorkloadAgent):

    def __init__(self):
        super().__init__(name='llama')

    def pod_spec(self, label: str = 'default', model_name: str = 'meta-llama/llama-3.2-1b',
                 result_directory: str = '', cache_directory: str = ''):
        return {
            'image': 'llama',
            'command': ['python3', 'llama.py', 'results/llama.csv', label, model_name],
            'volumes': [
                {'name': 'huggingface-cache', 'mount_path': '/root/.cache/huggingface/', 'host_path': cache_directory},
                {'name': 'llama-results', 'mount_path': '/app/results', 'host_path': result_directory},
            ],
        }
