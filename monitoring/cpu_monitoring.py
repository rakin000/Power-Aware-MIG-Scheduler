from .monitor_agent import MonitorAgent

class CPUMonitor(MonitorAgent):

    SYSFS_STAT    = '/proc/stat'
    SYSFS_STATS_KEYS  = {'cpuid':0, 'user':1, 'nice':2 , 'system':3, 'idle':4, 'iowait':5, 'irq':6, 'softirq':7, 'steal':8, 'guest':9, 'guest_nice':10}
    SYSFS_STATS_IDLE  = ['idle', 'iowait']
    SYSFS_STATS_NTID  = ['user', 'nice', 'system', 'irq', 'softirq', 'steal']

    def __init__(self, gpu_count : int = 0, include_gpu_x : bool = False):
        self.domains = ['global']
        for i in range(gpu_count): self.domains.append('GPU' + str(i))
        if include_gpu_x: self.domains.append('GPU-X')
        self.cputime_hist = {}

    def discover(self):
        pass

    def update(self, args):
        pass

    class CpuTime(object):
        def has_time(self):
            return hasattr(self, 'idle') and hasattr(self, 'not_idle')

        def set_time(self, idle : int, not_idle : int):
            setattr(self, 'idle', idle)
            setattr(self, 'not_idle', not_idle)

        def get_time(self):
            return getattr(self, 'idle'), getattr(self, 'not_idle')

        def clear_time(self):
            if hasattr(self, 'idle'): delattr(self, 'idle')
            if hasattr(self, 'not_idle'): delattr(self, 'not_idle')

    def query_metrics(self):
        with open(CPUMonitor.SYSFS_STAT, 'r') as f:
            split = f.readlines()[0].split(' ')
            split.remove('')
        if 'global' not in self.cputime_hist: self.cputime_hist['global'] = CPUMonitor.CpuTime()
        cpu_usage = self.__get_usage_of_line(split=split, hist_object=self.cputime_hist['global'])
        
        if cpu_usage is None:
            return {} 

        return {domain:{'cpu%': cpu_usage} for domain in self.domains}

    def get_label(self):
        return "CPU"
    
    def __get_usage_of_line(self, split : list, hist_object : object, update_history : bool = True):
        idle          = sum([ int(split[CPUMonitor.SYSFS_STATS_KEYS[idle_key]])     for idle_key     in CPUMonitor.SYSFS_STATS_IDLE])
        not_idle      = sum([ int(split[CPUMonitor.SYSFS_STATS_KEYS[not_idle_key]]) for not_idle_key in CPUMonitor.SYSFS_STATS_NTID])

        # Compute delta
        cpu_usage  = None
        if hist_object.has_time():
            prev_idle, prev_not_idle = hist_object.get_time()
            delta_idle     = idle - prev_idle
            delta_total    = (idle + not_idle) - (prev_idle + prev_not_idle)
            if delta_total>0: # Manage overflow
                cpu_usage = ((delta_total-delta_idle)/delta_total)*100
        
        if update_history: hist_object.set_time(idle=idle, not_idle=not_idle)
        return cpu_usage