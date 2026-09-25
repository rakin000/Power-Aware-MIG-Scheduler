from .monitor_agent import MonitorAgent
import subprocess as sp
import re

class IPMIMonitor(MonitorAgent):

    def __init__(self, sudo_command):
        self.sudo_command = sudo_command
        self.sensors_dict = None
        self.available = False # False on hosts without a BMC (e.g. cloud VMs): the monitor then reports nothing

    def discover(self):
        cmd = self.sudo_command + " ipmitool sdr type temperature"
        result = sp.run(cmd, shell=True, capture_output=True, text=True)

        # No BMC / ipmitool: keep running without IPMI data instead of aborting the experiment
        if result.returncode != 0:
            print("IPMI unavailable, continuing without IPMI metrics:", result.stderr.strip())
            self.sensors_dict = {}
            self.available = False
            return

        # Extract label and address using regex
        output = result.stdout.strip().splitlines()
        sensors_dict = {}
        gpu_found = 0
        for line in output:
            if 'Disabled' in line: continue
            match = re.match(r'(\S.+?)\s+\| ([0-9A-Fa-f]+h)', line)
            if match:
                label, address = match.groups()
                label = label.strip()

                # Check label consistency and unicity
                domain = 'global'
                if 'GPU' in label:
                    domain = 'GPU-X'

                uniqueness_count = 0
                while label in sensors_dict.keys():
                    uniqueness_count+=1
                    if '(' in label and ')' in label:
                        label = re.sub('(.*?)', '', label)
                    label+='(' + str(uniqueness_count) +  ')'

                sensors_dict[address.strip()] = (domain.strip(), label.strip())

        self.sensors_dict = sensors_dict
        self.available = True

    def update(self, args):
        pass

    def query_metrics(self):
        if not self.available:
            return {}
        cmd = self.sudo_command  + " ipmitool sdr type temperature"
        result = sp.run(cmd, shell=True, capture_output=True, text=True)

        # Check for errors
        if result.returncode != 0:
            print("Command failed:", result.stderr)
            exit(1)

        ipmi_measures = {}
        for line in result.stdout.strip().splitlines():
            if 'Disabled' in line: continue
            match = re.match(r"(.+?)\s+\|\s+([0-9A-Fa-f]{2}h)\s+\|\s+\w+\s+\|\s+[\d.]+\s+\|\s+(.+)", line)
            if match:
                label = match.group(1).strip()
                address = match.group(2).strip()
                value = match.group(3).strip().split(' ')[0]

                if address not in self.sensors_dict:
                    continue
                
                (domain, label) = self.sensors_dict[address]
                if domain not in ipmi_measures:
                    ipmi_measures[domain] = {}
                ipmi_measures[domain][label] = value

        return ipmi_measures

    def get_label(self):
        return "IPMI"
