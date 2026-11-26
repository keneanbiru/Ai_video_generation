"""Kaggle GPU probe: what hardware/software do we actually get, and which Wan pipeline does I2V?"""
import json, subprocess, sys, time, inspect
t0 = time.time()
rep = {}
rep["nvidia_smi"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv"],
                                   capture_output=True, text=True).stdout
import torch
rep["torch"] = torch.__version__
rep["cuda"] = torch.version.cuda
rep["gpus"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
rep["capability"] = [torch.cuda.get_device_capability(i) for i in range(torch.cuda.device_count())]
rep["bf16_supported"] = torch.cuda.is_bf16_supported()
# bf16 vs fp16 matmul speed on GPU 0
def bench(dt):
    a = torch.randn(4096, 4096, device="cuda", dtype=dt); b = torch.randn(4096, 4096, device="cuda", dtype=dt)
    torch.cuda.synchronize(); t = time.time()
    for _ in range(20): a @ b
    torch.cuda.synchronize(); return round((time.time() - t) / 20 * 1000, 2)
rep["matmul_ms_4096"] = {"fp16": bench(torch.float16), "bf16": bench(torch.bfloat16), "fp32": bench(torch.float32)}
t = time.time()
p = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "git+https://github.com/huggingface/diffusers",
                    "ftfy", "imageio-ffmpeg"], capture_output=True, text=True)
rep["pip_diffusers_main_s"] = round(time.time() - t, 1)
rep["pip_tail"] = p.stderr[-500:]
import importlib, diffusers
importlib.reload(diffusers)
rep["diffusers"] = diffusers.__version__
from diffusers import WanPipeline
rep["WanPipeline_call_params"] = list(inspect.signature(WanPipeline.__call__).parameters)
try:
    from diffusers import WanImageToVideoPipeline
    rep["WanImageToVideoPipeline_call_params"] = list(inspect.signature(WanImageToVideoPipeline.__call__).parameters)
except Exception as e:
    rep["WanImageToVideoPipeline"] = repr(e)
import shutil
rep["disk_free_gb"] = round(shutil.disk_usage("/kaggle/working").free / 1e9, 1)
rep["ram_gb"] = round(__import__("os").sysconf("SC_PAGE_SIZE") * __import__("os").sysconf("SC_PHYS_PAGES") / 1e9, 1)
rep["python"] = sys.version
rep["elapsed_s"] = round(time.time() - t0, 1)
json.dump(rep, open("/kaggle/working/probe.json", "w"), indent=1)
print(json.dumps(rep, indent=1))
