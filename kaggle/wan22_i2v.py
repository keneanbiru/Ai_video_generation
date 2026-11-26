"""Wan 2.2 TI2V-5B image-to-video on Kaggle (T4 x2). Launched by `python -m pipeline.remote wan`.

Inputs  (private dataset mounted under /kaggle/input/heritage-inputs/): storyboard.json, keyframes/<id>.png
Outputs (/kaggle/working/clips_wan/): <id>.mp4 + <id>.json {model, keyframe_sha16, motion_prompt, seed,
         params, latency_s, device, dtype}, written as soon as each clip finishes (sessions can time out).

Both GPUs are used: one worker process per GPU, alternate shots. Verified facts this relies on
(model card, 26 Nov 2026): diffusers from git main; VAE in fp32; 24 fps; documented dtype bf16.
A T4 has no fast bf16, so fp16 is tried first and a clip with NaN/black frames is redone in bf16.
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

ARGS_FROM_RUNNER = []  # filled in by pipeline/remote.py
WORK = "/kaggle/working"
MODEL = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"


def find_inputs():
    hits = glob.glob("/kaggle/input/**/storyboard.json", recursive=True)
    if not hits:
        raise SystemExit("storyboard.json not found under /kaggle/input")
    return os.path.dirname(hits[0])


def sha16(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def worker(gpu, shots, a):
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    import numpy as np
    import torch
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline
    from diffusers.utils import export_to_video
    from PIL import Image

    inp = find_inputs()
    sb = json.load(open(os.path.join(inp, "storyboard.json")))
    by_id = {s["id"]: s for s in sb["shots"]}
    out = os.path.join(WORK, "clips_wan")
    os.makedirs(out, exist_ok=True)
    w = h = a.size  # square: matches the square keyframes; 16:9 and 9:16 are both cropped locally (E17)
    pipes = {}

    def pipe_for(dtype):
        if dtype not in pipes:
            pipes.clear()
            torch.cuda.empty_cache()
            vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32)
            p = WanImageToVideoPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=dtype)
            if os.environ.get("WAN_OFFLOAD", a.offload) == "sequential":
                p.enable_sequential_cpu_offload()  # E21: model-level offload still OOMs on 15 GB; layer-by-layer fits, slowly
            else:
                p.enable_model_cpu_offload()  # 15 GB T4: keep only the active module on the GPU
            p.vae.enable_tiling()  # E20: untiled fp32 decode of all frames asked for 6.3 GiB at once -> OOM
            p.set_progress_bar_config(disable=True)
            pipes[dtype] = p
        return pipes[dtype]

    for sid in shots:
        s = by_id[sid]
        kf = os.path.join(inp, "keyframes", f"{sid}.png")
        img = Image.open(kf).convert("RGB")
        img = img.resize((w, h), Image.LANCZOS)
        for dtype in ([torch.float16, torch.bfloat16] if a.dtype == "auto" else [getattr(torch, a.dtype)]):
            t0 = time.time()
            g = torch.Generator("cpu").manual_seed(s["seed"])
            try:
                frames = pipe_for(dtype)(image=img, prompt=s["motion_prompt"], height=h, width=w,
                                         num_frames=a.frames, num_inference_steps=a.steps, guidance_scale=5.0,
                                         generator=g, output_type="np").frames[0]
            except torch.cuda.OutOfMemoryError as e:
                print(f"[gpu{gpu}] {sid} OOM in {dtype}: {e}", flush=True)
                torch.cuda.empty_cache()
                continue
            bad = (not np.isfinite(frames).all()) or float(np.mean(frames)) < 0.02
            dt = time.time() - t0
            print(f"[gpu{gpu}] {sid} {dtype} {dt:.0f}s mean={float(np.nanmean(frames)):.3f} bad={bad}", flush=True)
            if bad:
                continue
            path = os.path.join(out, f"{sid}.mp4")
            export_to_video(list(frames), path, fps=24)
            json.dump({"model": MODEL, "keyframe_sha16": sha16(kf), "motion_prompt": s["motion_prompt"],
                       "seed": s["seed"], "params": {"size": a.size, "frames": a.frames, "steps": a.steps, "cfg": 5.0},
                       "dtype": str(dtype), "latency_s": round(dt, 1),
                       "device": torch.cuda.get_device_name(0), "peak_vram_gb":
                       round(torch.cuda.max_memory_allocated() / 1e9, 2)}, open(path[:-4] + ".json", "w"), indent=1)
            break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--size", type=int, default=640, help="square side, multiple of 32 (640 draft, 960 final)")
    ap.add_argument("--frames", type=int, default=81, help="4k+1; 81 = 3.4 s, 121 = 5 s at 24 fps")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--dtype", default="auto", choices=["auto", "float16", "bfloat16"])
    ap.add_argument("--worker", type=int, default=-1)
    ap.add_argument("--offload", default="sequential", choices=["model", "sequential"])
    ap.add_argument("--workers", type=int, default=1,
                    help="processes (one per GPU). 2 was killed by host-RAM OOM: each loads 5B + text encoder for offload (E20)")
    ap.add_argument("--shots", nargs="*")
    a = ap.parse_args((sys.argv[1:] or ARGS_FROM_RUNNER))
    if a.worker >= 0:
        return worker(a.worker, a.shots, a)
    t0 = time.time()
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "git+https://github.com/huggingface/diffusers",
                    "ftfy", "imageio-ffmpeg"], check=True)
    print(f"deps installed in {time.time() - t0:.0f}s", flush=True)
    inp = find_inputs()
    sb = json.load(open(os.path.join(inp, "storyboard.json")))
    shots = a.only or [s["id"] for s in sb["shots"]]
    import torch
    n = max(1, min(a.workers, torch.cuda.device_count()))
    # pre-download weights once so the two workers don't race
    from huggingface_hub import snapshot_download
    t1 = time.time()
    snapshot_download(MODEL)
    print(f"weights downloaded in {time.time() - t1:.0f}s", flush=True)
    base = [a2 for a2 in (sys.argv[1:] or ARGS_FROM_RUNNER) if a2]
    procs = []
    for gpu in range(n):
        part = shots[gpu::n]
        if part:
            cmd = [sys.executable, __file__, *base, "--worker", str(gpu), "--shots", *part]
            procs.append(subprocess.Popen(cmd))
    codes = [p.wait() for p in procs]
    done = sorted(os.path.basename(p) for p in glob.glob(os.path.join(WORK, "clips_wan", "*.mp4")))
    json.dump({"requested": shots, "done": done, "worker_exit_codes": codes, "wall_s": round(time.time() - t0)},
              open(os.path.join(WORK, "wan_summary.json"), "w"), indent=1)
    print(json.dumps({"done": done, "wall_s": round(time.time() - t0)}), flush=True)


if __name__ == "__main__":
    main()
