FROM nvidia/cuda:12.2.2-devel-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive
# Set the working directory
WORKDIR /app

# Copy the current folder into the container
COPY . /app

# Install dependencies (adjust as needed)
RUN apt-get update && apt-get install -y xorg python3 \
    wget curl unzip \
    && rm -rf /var/lib/apt/lists/*

# Download necessary benchmark assets
RUN ./benchmark-launcher-cli blender download 4.3.0 && \
    ./benchmark-launcher-cli scenes --blender-version=4.3.0 download monster

RUN mkdir -p results

# Set the default command when running the container
CMD ["python3", "blender.py", "results/blender.csv", "mylabel", "./benchmark-launcher-cli", "--blender-version=4.3.0", "--device-type=CUDA", "--verbosity=0", "benchmark", "monster", "--json"]
