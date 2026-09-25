from .workload_agent import WorkloadAgent

class WorkloadTrainingYolo(WorkloadAgent):

    def __init__(self):
        super().__init__(name='yolo')

    def pod_spec(self, label: str = 'default', model_name: str = 'yolov8n.pt',
                 result_directory: str = '', shm_size: str = '4Gi'):
        return {
            'image': 'yolo',
            'command': ['python3', 'yolo.py', 'results/yolo.csv', label, model_name],
            'volumes': [
                {'name': 'yolo-results', 'mount_path': '/app/results', 'host_path': result_directory},
                # docker's --shm-size=4g equivalent: a memory-backed emptyDir mounted on /dev/shm
                {'name': 'dshm', 'mount_path': '/dev/shm', 'medium': 'Memory', 'size_limit': shm_size},
            ],
        }
