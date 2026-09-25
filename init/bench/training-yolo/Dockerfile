FROM python:3.10

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir ultralytics

RUN apt-get update && apt-get install -y --no-install-recommends mesa-utils

RUN mkdir -p results

# Command to run the script (replace 'script.py' with your actual script)
CMD ["python", "yolo.py", "results/yolo.csv", "mylabel", "yolov8n.pt"]
