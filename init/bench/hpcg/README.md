docker build . -t hpcg
mkdir -p results/hpcg
docker run -it --rm --runtime=nvidia --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 -v results/hpcg:/workspace/results hpcg