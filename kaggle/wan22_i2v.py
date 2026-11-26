"""Wan 2.2 TI2V-5B image-to-video for every keyframe. Run INSIDE a Kaggle notebook (GPU T4 x2).

STATUS: written against the diffusers Wan 2.2 integration but NOT executed by this pipeline's
author's machine (no GPU, and Kaggle needs the owner's phone-verified account). See FAILURES.md F06.

Kaggle steps
  1. New notebook -> Settings -> Accelerator: GPU T4 x2, Internet: on.
  2. Add this repo as a dataset (or `git clone` it), then in a cell:
        !pip install -q "diffusers>=0.35" transformers accelerate ftfy imageio imageio-ffmpeg
        !python kaggle/wan22_i2v.py --repo /kaggle/working/heritage-short --res 480
  3. Download outputs/clips_wan/ (the .mp4 + .json pairs) back into your local repo.
  4. Locally `make film`: the shots stage imports each clip ONLY if its .json records the
     sha256 of the current keyframe and the current motion prompt; otherwise it falls back to
     Ken Burns. The GPU latency of every clip is merged into runs.jsonl from the .json files.

Draft at 480p first (much faster on T4); re-run chosen shots with --res 704 --only s06 s09.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def sha16(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--res", type=int, default=480, choices=[480, 704])
    ap.add_argument("--frames", type=int, default=121, help="121 frames = ~5 s at 24 fps")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()

    import torch
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline
    from diffusers.utils import export_to_video
    from PIL import Image

    repo = Path(a.repo)
    sb = json.loads((repo / "storyboard.json").read_text())
    out_dir = repo / "outputs" / "clips_wan"
    out_dir.mkdir(parents=True, exist_ok=True)

    model_id = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
    dtype = torch.float16  # T4 has no fast bf16
    vae = AutoencoderKLWan.from_pretrained(model_id, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanImageToVideoPipeline.from_pretrained(model_id, vae=vae, torch_dtype=dtype)
    pipe.enable_model_cpu_offload()  # fits the 16 GB T4
    w, h = (832, 480) if a.res == 480 else (1280, 704)

    for shot in sb["shots"]:
        sid = shot["id"]
        if a.only and sid not in a.only:
            continue
        kf = repo / "outputs" / "keyframes" / f"{sid}.png"
        # Square keyframe -> centre crop to 16:9; the local stage crops 9:16 from this clip.
        img = Image.open(kf).convert("RGB")
        s = img.width
        img = img.crop((0, (s - s * h // w) // 2, s, (s + s * h // w) // 2)).resize((w, h))
        t0 = time.time()
        g = torch.Generator("cpu").manual_seed(shot["seed"])
        frames = pipe(image=img, prompt=shot["motion_prompt"], height=h, width=w, num_frames=a.frames,
                      num_inference_steps=a.steps, guidance_scale=5.0, generator=g).frames[0]
        export_to_video(frames, str(out_dir / f"{sid}.mp4"), fps=24)
        dt = time.time() - t0
        (out_dir / f"{sid}.json").write_text(json.dumps({
            "model": model_id, "keyframe_sha16": sha16(kf), "motion_prompt": shot["motion_prompt"],
            "seed": shot["seed"], "params": {"res": a.res, "frames": a.frames, "steps": a.steps, "cfg": 5.0},
            "latency_s": round(dt, 1), "device": torch.cuda.get_device_name(0),
        }, indent=1))
        print(f"{sid}: {dt:.0f}s", flush=True)  # save as we go: Kaggle sessions time out


if __name__ == "__main__":
    main()
