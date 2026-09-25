import shutil, os, time, sys
os.environ['YOLO_VERBOSE'] = 'False'
import ultralytics
from ultralytics import YOLO

def run(output_file, label, model_name):

    model = YOLO(model_name)

    launch = time.time()
    while True:

        start_ns = time.time_ns()
        model.train(data='data.yaml', device=0, save=False, epochs=1)
        end_ns = time.time_ns()
        response_time_ms = round((end_ns - start_ns) / 1_000_000,1)
        print(f"Training Time: {response_time_ms} ms")

        timestamp = int(time.time() - launch)
        print(timestamp, round(response_time_ms,1), 'ms')
        with open(output_file, 'a') as f:
            f.write(f"{timestamp},{label},"f"{round(response_time_ms,1)}\n")

if __name__ == "__main__":

    if len(sys.argv) < 3:
        print("Usage: python3 yolo.py <output_file> <label> <model_name>")
        sys.exit(1)

    output_file  = sys.argv[1]
    label        = sys.argv[2]
    model_name   = sys.argv[3] # yolov8n.pt

    try:
        run(output_file, label, model_name)
    except KeyboardInterrupt:
        pass
