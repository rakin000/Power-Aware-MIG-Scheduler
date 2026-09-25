Retrieve the dataset and the model before building

Generate a link at with YOLOv8 https://universe.roboflow.com/roboflow-58fyf/rock-paper-scissors-sxsw
curl -L "<dataset_url>" > roboflow.zip; unzip roboflow.zip; rm roboflow.zip /workspace/data/rock-paper-scissors

docker build . -t yolo
mkdir -p results/llama
docker run -it --rm --runtime=nvidia --shm-size=4g --gpus all -v results/yolo:/app/results yolo

The increase of shared memory is important