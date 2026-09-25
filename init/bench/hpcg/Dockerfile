FROM nvcr.io/nvidia/hpc-benchmarks:25.02

RUN apt-get update && apt-get install -y python3

# Set the working directory
WORKDIR /workspace

# Copy the needed files
COPY custom-hpcg.dat /workspace/custom-hpcg.dat
COPY hpcg.py /workspace/hpcg.py

RUN mkdir -p results

# Set the default command to run when the container starts
CMD ["python3", "hpcg.py", "results/hpcg.csv", "mylabel", "./hpcg.sh", "--dat", "custom-hpcg.dat"]
