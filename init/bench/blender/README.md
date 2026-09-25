Install benchmark-launcher-cli in this folder before building

docker build . -t blender
mkdir -p results/blender
docker run --rm --runtime=nvidia --gpus all -v results/blender:/app/results blender