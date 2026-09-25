from .workload_agent import WorkloadAgent

class WorkloadBlender(WorkloadAgent):

    def __init__(self):
        super().__init__(name='blender')

    def pod_spec(self, label: str = 'default', result_directory: str = ''):
        return {
            'image': 'blender',
            'command': ['python3', 'blender.py', 'results/blender.csv', label,
                        './benchmark-launcher-cli', '--blender-version=4.3.0',
                        '--device-type=CUDA', '--verbosity=0', 'benchmark', 'monster', '--json'],
            'volumes': [
                {'name': 'blender-results', 'mount_path': '/app/results', 'host_path': result_directory},
            ],
        }
