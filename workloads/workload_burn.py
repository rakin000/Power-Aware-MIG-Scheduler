from .workload_agent import WorkloadAgent

class WorkloadBurn(WorkloadAgent):

    def __init__(self):
        super().__init__(name='gpu_burn')

    def pod_spec(self, delay: int = 300, mem_use: str = '10%'):
        return {
            'image': 'gpu_burn',
            'command': ['./gpu_burn', '-m', mem_use, str(delay)],
        }
