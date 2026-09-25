import subprocess, time, re, sys

def launch_process(command_args):

    process = subprocess.Popen(command_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()

    pattern = r"^(GB/s|GFLOP/s) Summary::(.+?)=([\d\.]+)$"
    stats = {}
    try:
        for line in stdout.splitlines():
            line = line.strip()
            if not line: continue
            match = re.match(pattern, line)
            if match:
                unit = match.group(1)
                metric = match.group(2).strip()
                value = float(match.group(3))
                # Combine unit and metric to form a key, e.g., "GB/s Raw Read B/W"
                key = f"{unit} {metric}".replace(' ','_')
                stats[key] = value
        return stats
    except (IndexError, KeyError) as e:
        print(f"Error processing the output: {e}")
        return None

def run(output_file, label, command_args):
    launch = time.time()
    while True:
        stats = launch_process(command_args)
        if not isinstance(stats, dict):
            continue
        timestamp = int(time.time() - launch)
        if 'GFLOP/s_Total_with_convergence_and_optimization_phase_overhead' in stats:
            print(timestamp, stats['GFLOP/s_Total_with_convergence_and_optimization_phase_overhead'], 'GFLOP/s')
        else: print('Something is wrong')
        with open(output_file, 'a') as f:
            for metric, value in stats.items():
                f.write(f"{timestamp},{label},{metric},{value}\n")

# python3 hpcg.py output mylabel ./hpcg.sh --dat custom-hpcg.dat
if __name__ == "__main__":

    if len(sys.argv) < 3:
        print("Usage: python3 hpcg.py <output_file> <label> <command> [params...]")
        sys.exit(1)

    output_file  = sys.argv[1]
    label        = sys.argv[2]
    command_args = sys.argv[3:]

    try:
        run(output_file, label, command_args)
    except KeyboardInterrupt:
        pass
