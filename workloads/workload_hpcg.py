from .workload_agent import WorkloadAgent

class WorkloadHpcg(WorkloadAgent):

    def __init__(self):
        super().__init__(name='hpcg')

    def pod_spec(self, label: str = 'default', result_directory: str = ''):
        return {
            'image': 'hpcg',
            'command': ['python3', 'hpcg.py', 'results/hpcg.csv', label, './hpcg.sh', '--dat', 'custom-hpcg.dat'],
            'volumes': [
                {'name': 'hpcg-results', 'mount_path': '/workspace/results', 'host_path': result_directory},
            ],
        }
