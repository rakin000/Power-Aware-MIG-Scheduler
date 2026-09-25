class WorkloadAgent:
    """Describes one benchmark/stress test as a Pod container. Subclasses turn their
    arguments into a plain dict; k8s/scheduler.py's KubernetesScheduler turns that dict
    into a Pod manifest, applies it, and waits on it. This class knows nothing about
    GPU/MIG resource requests — that's k8s.PodJob's job, set per launch, not per workload.
    """

    def __init__(self, name: str):
        self.name = name

    def pod_spec(self, **args) -> dict:
        """Describe the container to run.

        Returns a dict with:
            image (str):            image name/tag, expected to already be loaded in the
                                     cluster's docker daemon (imagePullPolicy: Never, as
                                     images are built locally, not pushed to a registry).
            command (list[str]):    container entrypoint override.
            volumes (list[dict]):   optional hostPath/emptyDir mounts, each
                                     {'name', 'mount_path', 'host_path'} or
                                     {'name', 'mount_path', 'medium': 'Memory', 'size_limit'}.
        """
        raise NotImplementedError("This method should be implemented in subclasses.")
