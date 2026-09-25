from .monitor_agent import MonitorAgent
from .monitor_wrapper import MonitorWrapper
from .ipmi_monitor import IPMIMonitor
from .smi_monitor import SMIMonitor
from .const_monitor import ConstMonitor
from .dcgm_monitor import DCGMMonitor
from .cpu_monitoring import CPUMonitor

if __name__ == "__main__":

    mon_labels = ConstMonitor({'context':'test'})
    mon_ipmi = IPMIMonitor(sudo_command='sudo')
    mon_ipmi.discover()
    mon_smi  = SMIMonitor(sudo_command='sudo')
    mon_dcgm = DCGMMonitor(url='http://localhost:9400/metrics')

    monitors = [mon_ipmi,mon_smi,mon_dcgm,mon_labels]

    wrapper = MonitorWrapper(monitors=monitors)
    try:
        wrapper.start_monitoring()
    except KeyboardInterrupt:
        wrapper.stop_monitoring()
        print("Program interrupted")