Llama models must be downloaded and mount to the container

docker build . -t llama
mkdir -p results/llama
docker run -it --rm --runtime=nvidia --gpus all -v ~/.cache/huggingface/:/root/.cache/huggingface/ -v results/llama:/app/results llama
