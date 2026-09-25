from .workload_agent import WorkloadAgent
from .workload_burn import WorkloadBurn
from .workload_blender import WorkloadBlender
from .workload_hpcg import WorkloadHpcg
from .workload_inference_llama import WorkloadInferenceLlama
from .workload_training_yolo import WorkloadTrainingYolo

__all__ = [
    "WorkloadAgent", "WorkloadBurn", "WorkloadBlender", "WorkloadHpcg",
    "WorkloadInferenceLlama", "WorkloadTrainingYolo",
]
