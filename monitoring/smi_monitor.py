from .monitor_agent import MonitorAgent
import subprocess as sp
import re

class SMIMonitor(MonitorAgent):

    SMI_QUERY = ['index','utilization.gpu','temperature.gpu','pstate','clocks.current.graphics','clocks.current.sm','clocks.current.memory','clocks.current.video','utilization.memory','memory.used','memory.free','memory.total','power.draw','power.max_limit','fan.speed']
    SMI_QUERY_FLAT  = ','.join(SMI_QUERY)

    def __init__(self, sudo_command):
        self.sudo_command = sudo_command

    def discover(self):
        pass

    def update(self, args):
        pass

    def query_metrics(self):
        command = "nvidia-smi --query-gpu=" + SMIMonitor.SMI_QUERY_FLAT + " --format=csv"
        smi_data = self.__generic_smi(command)
        header = smi_data[0]
        data   = smi_data[1:]
        smi_measures = {}
        for data_single_gc in data:
            gpu_index, gpu_data = self.__convert_gc_to_dict(header, data_single_gc)
            smi_measures[gpu_index] = gpu_data
        return smi_measures

    def get_label(self):
        return "SMI"

    def __generic_smi(self, command : str):
        try:
            csv_like_data = sp.check_output(command.split(),stderr=sp.STDOUT).decode('ascii').split('\n')
            smi_data = [cg_data.split(',') for cg_data in csv_like_data[:-1]] # end with ''
        except sp.CalledProcessError as e:
            raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))
        return smi_data

    def __convert_gc_to_dict(self, header : list, data_single_gc : list):
        gpu_index = None
        gpu_data = {}
        for position, query in enumerate(SMIMonitor.SMI_QUERY):
            if 'N/A' in data_single_gc[position]:
                value = 'NA'
            elif '[' in header[position]: # if a unit is written, like [MiB], we have to strip it from value
                value = float(re.sub(r"[^\d\.]", "", data_single_gc[position]))
            else:
                value = data_single_gc[position].strip()
            if query == 'index':
                gpu_index = 'GPU' + str(value)
                continue
            gpu_data[query] = value
        return gpu_index, gpu_data
