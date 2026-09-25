import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import time, sys

# model_name = "meta-llama/llama-3.2-1b"
# model_name = "meta-llama/llama-3.2-3b"
# model_name = "meta-llama/Llama-3.1-8B-Instruct"

def run(output_file, label, model_name):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    print("Loading model...")
    model = AutoModelForCausalLM.from_pretrained(model_name).to(device)

    prompt = "What is the capital of France?"
    inputs = tokenizer(prompt, return_tensors="pt")
    # Move input tensors to GPU
    inputs = {key: value.to(device) for key, value in inputs.items()}

    launch = time.time()
    while True:

        start_ns = time.time_ns()
        with torch.no_grad():
            output = model.generate(**inputs, max_length=100, pad_token_id=tokenizer.eos_token_id)
        end_ns = time.time_ns()
        response_time_ms = round((end_ns - start_ns) / 1_000_000,1)
        print(f"Inference Time: {response_time_ms} ms")

        #print(tokenizer.decode(output[0], skip_special_tokens=True))

        timestamp = int(time.time() - launch)
        print(timestamp, round(response_time_ms,1), 'ms')
        with open(output_file, 'a') as f:
            f.write(f"{timestamp},{label},"f"{round(response_time_ms,1)}\n")

if __name__ == "__main__":

    if len(sys.argv) < 3:
        print("Usage: python3 llama.py <output_file> <label> <model_name>")
        sys.exit(1)

    output_file  = sys.argv[1]
    label        = sys.argv[2]
    model_name   = sys.argv[3]

    try:
        run(output_file, label, model_name)
    except KeyboardInterrupt:
        pass
