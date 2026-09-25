import threading, time
from os import listdir
from os.path import isfile, join, exists

class MonitorWrapper:

    def __init__(self, monitors : list, output_file : str = 'measures.csv', delay : int = 5):
        self.monitors = monitors
        self.output_file = output_file
        self.delay = delay
        self.thread = None
        self.thread_lock  = None
        self.thread_stop  = None
        self.thread_reset = None

    def start_monitoring(self):

        with open(self.output_file, 'w') as f:
            f.write('timestamp,domain,metric,measure\n')

        def monitor_loop(monitors : list, output_file : str, delay : int, thread_lock, thread_reset, thread_stop):
            launch_at = time.time_ns()
            while True:
                if thread_reset.is_set():
                    launch_at = time.time_ns()
                    thread_reset.clear()

                time_begin = time.time_ns()
                time_since_launch=int((time.time_ns()-launch_at)/(10**9))
                all_measures = {}
                with thread_lock:
                    for monitor in monitors: all_measures[monitor.get_label()] = monitor.query_metrics()

                for label, measures in all_measures.items():
                    with open(self.output_file, 'a') as f:
                        for domain, values in measures.items():
                            for metric, value in values.items():
                                f.write(f"{time_since_launch},{domain},{label}_{metric},{value}\n")

                time_to_sleep = (delay*10**9) - (time.time_ns() - time_begin)
                if thread_stop.is_set(): break
                if time_to_sleep>0: time.sleep(time_to_sleep/10**9)
                else: print('Warning: overlap iteration', -(time_to_sleep/10**9), 's')

        self.thread_lock  = threading.Lock()
        self.thread_reset = threading.Event()
        self.thread_stop  = threading.Event()
        self.thread = threading.Thread(target=monitor_loop, args=(self.monitors, self.output_file, self.delay, self.thread_lock, self.thread_reset, self.thread_stop))
        self.thread.start()

    def update_monitoring(self, args, monitor_index : int, reset_launch : bool = False):
        if self.thread is None:
            self.monitors[monitor_index].update(args)
            return
        with self.thread_lock:
            self.monitors[monitor_index].update(args)
            if reset_launch: self.thread_reset.set()

    def stop_monitoring(self):
        self.thread_stop.set()
        self.thread.join()