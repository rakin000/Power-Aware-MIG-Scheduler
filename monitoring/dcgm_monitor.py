from .monitor_agent import MonitorAgent
import subprocess as sp
import re

class DCGMMonitor(MonitorAgent):

    def __init__(self, url):
        self.url = url

    def discover(self):
        pass

    def update(self, args):
        pass

    def query_metrics(self):
        try:
            # Run the curl command and capture the output
            cmd = "curl -s " + self.url
            result = sp.run(cmd, shell=True, text=True, capture_output=True, check=True)
            output = result.stdout

            dcgm_measures = {}
            for line in output.splitlines():
                # Skip comments and empty lines
                if line.startswith('#') or not line.strip():
                    continue

                # Match metric name, labels, and value
                match = re.match(r'^([\w:]+)(\{.*\})?\s+([\d.]+)', line)
                if match:
                    metric_name = match.group(1)
                    labels = match.group(2)  # e.g., {gpu="0"}
                    value = match.group(3)

                    # Parse labels if present
                    label_dict = {}
                    if labels: # Remove the surrounding braces and split into key-value pairs
                        label_pairs = labels.strip('{}').split(',')
                        for pair in label_pairs:
                            splitted_val = pair.split('=')
                            if len(splitted_val) == 2:
                                key, val = splitted_val
                                label_dict[key.strip()] = val.strip('"')
                            else: pass # Probably an error message, print('DCGM monitoring: Something weird with line', line)

                    if label_dict:
                        domain = 'GPU' + str(label_dict["gpu"])
                        if domain not in dcgm_measures:
                            dcgm_measures[domain] = {}
                        try:
                            dcgm_measures[domain][metric_name] = float(value)
                        except ValueError:
                            dcgm_measures[domain][metric_name] = value  # Keep as string if not a float

            return dcgm_measures
        except sp.CalledProcessError as e:
            print(f"DCGM parsing failed with error: {e.stderr}")
            return {}

    def get_label(self):
        return "DCGM"
