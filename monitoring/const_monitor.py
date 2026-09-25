from .monitor_agent import MonitorAgent

class ConstMonitor(MonitorAgent):

    def __init__(self, labels : dict, gpu_count : int = 0, include_gpu_x : bool = False):
        domains = ['global']
        for i in range(gpu_count): domains.append('GPU' + str(i))
        if include_gpu_x: domains.append('GPU-X')
        # Apply extra labels to all domains
        self.values = {domain:labels for domain in domains}

    def discover(self):
        pass

    def query_metrics(self):
        return self.values

    def get_label(self):
        return "CONST"

    def update(self, labels : dict):
        domains = self.values.keys() 
        for domain in domains: self.values[domain] = labels
