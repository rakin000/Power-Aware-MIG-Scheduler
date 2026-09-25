FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir torch transformers

RUN mkdir -p results

CMD ["python3", "llama.py", "results/llama.csv", "mylabel", "meta-llama/llama-3.2-1b"]
