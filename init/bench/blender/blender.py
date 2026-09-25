import subprocess, time, json, sys

def launch_process(command_args):

    process = subprocess.Popen(command_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    output = '\n'.join(stdout.splitlines())

    try:
        data = json.loads(output)

        device_name = data[0]['device_info']['compute_devices'][0]['name']
        stats = data[0]['stats']

        return device_name, stats
    
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"Error processing the JSON output: {e}")
        return None, None

def run(output_file, label, command_args):
    launch = time.time()
    while True:
        device_name, stats = launch_process(command_args)
        if not isinstance(stats, dict):
            continue
        timestamp = int(time.time() - launch)
        print(timestamp, round(stats['samples_per_minute'],1), 'samples/m')
        with open(output_file, 'a') as f:
            f.write(f"{timestamp},{label},{device_name},"
                f"{round(stats['device_peak_memory'], 1)},"
                f"{round(stats['number_of_samples'], 1)},"
                f"{round(stats['time_for_samples'], 1)},"
                f"{round(stats['samples_per_minute'], 1)}\n")

# python3 blender.py output mylabel ./benchmark-launcher-cli --blender-version=4.3.0 --device-type=CUDA --verbosity=0 benchmark monster --json
if __name__ == "__main__":

    if len(sys.argv) < 3:
        print("Usage: python3 blender.py <output_file> <label> <command> [params...]")
        sys.exit(1)

    output_file  = sys.argv[1]
    label        = sys.argv[2]
    command_args = sys.argv[3:]

    if "--json" not in command_args:
        print('--json must be passed')
        sys.exit(1)
    if "--verbosity=0" not in command_args:
        print('--verbosity=0 must be passed')
        sys.exit(1)
    if "benchmark" not in command_args:
        print('benchmark must be passed')
        sys.exit(1)

    try:
        run(output_file, label, command_args)
    except KeyboardInterrupt:
        pass
