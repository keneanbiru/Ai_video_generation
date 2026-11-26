"""ACE-Step 1.5 score candidates on Kaggle (T4). Launched by `python -m pipeline.remote acestep`.

Input : storyboard.json (private dataset) -> music.caption, music.candidates (seeds), music.segment_s
Output: /kaggle/working/music_acestep/seed<N>.wav + seed<N>.json {caption, model, params, latency_s, device}

API verified from docs/en/INFERENCE.md (26 Nov 2026): AceStepHandler.initialize_service,
LLMHandler.initialize, GenerationParams(caption, lyrics, instrumental, duration, seed...),
GenerationConfig(batch_size, seeds, use_random_seed, audio_format), generate_music(...).
Python 3.11-3.12 required; checkpoints ~10 GB from HF ACE-Step/Ace-Step1.5.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ARGS_FROM_RUNNER = []
WORK = "/kaggle/working"
REPO = "/kaggle/temp/ACE-Step-1.5"


def bootstrap():
    """Kaggle's image is Python 3.13; ACE-Step 1.5 requires >=3.11,<3.13 (FAILURES F12).
    Use the repo's documented path: `uv sync` builds .venv with the pinned Python and CUDA torch,
    then this script re-runs itself inside it with --inner."""
    t0 = time.time()
    os.makedirs("/kaggle/temp", exist_ok=True)
    if not os.path.exists(REPO):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/ACE-Step/ACE-Step-1.5.git", REPO], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
    env = dict(os.environ, UV_LINK_MODE="copy")
    subprocess.run([sys.executable, "-m", "uv", "sync"], cwd=REPO, check=True, env=env)
    print(f"uv sync done in {time.time() - t0:.0f}s", flush=True)
    r = subprocess.run([os.path.join(REPO, ".venv", "bin", "python"), os.path.abspath(__file__), "--inner"],
                       cwd=REPO, env=env)
    print(f"total {time.time() - t0:.0f}s, inner exit {r.returncode}", flush=True)
    sys.exit(r.returncode)


def main():
    if "--inner" not in sys.argv:
        return bootstrap()
    t0 = time.time()
    sb = json.load(open(glob.glob("/kaggle/input/**/storyboard.json", recursive=True)[0]))
    m = sb["music"]
    sys.path.insert(0, REPO)
    import torch
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    t1 = time.time()
    from huggingface_hub import snapshot_download

    ckpt = os.path.join(REPO, "checkpoints")
    snapshot_download("ACE-Step/Ace-Step1.5", local_dir=ckpt)  # ~10 GB: vae, text encoder, turbo DiT, LM 1.7B
    print(f"checkpoints ready in {time.time() - t1:.0f}s", flush=True)
    dit = AceStepHandler()
    dit.initialize_service(project_root=REPO, config_path="acestep-v15-turbo", device="cuda")
    llm = LLMHandler()
    llm.initialize(checkpoint_dir=ckpt, lm_model_path="acestep-5Hz-lm-1.7B",  # in the main download; docs' pick for 12-16 GB
                   backend="pt", device="cuda")
    print(f"models ready in {time.time() - t1:.0f}s", flush=True)
    out = os.path.join(WORK, "music_acestep")
    os.makedirs(out, exist_ok=True)
    for seed in m["candidates"]:  # one at a time so each seed's latency is measured separately
        t2 = time.time()
        params = GenerationParams(caption=m["caption"], lyrics="[Instrumental]", instrumental=True,
                                  duration=float(m["segment_s"]), seed=seed, shift=3.0)
        cfg = GenerationConfig(batch_size=1, seeds=[seed], use_random_seed=False, audio_format="wav")
        res = generate_music(dit, llm, params, cfg, save_dir=os.path.join(WORK, "tmp"))
        dt = time.time() - t2
        if not res.success:
            print(f"seed {seed} failed: {res.error}", flush=True)
            continue
        shutil.copy(res.audios[0]["path"], os.path.join(out, f"seed{seed}.wav"))
        json.dump({"caption": m["caption"], "model": "ACE-Step-1.5 acestep-v15-turbo + lm-1.7B",
                   "params": {"duration": m["segment_s"], "instrumental": True, "shift": 3.0, "seed": seed},
                   "latency_s": round(dt, 1), "device": torch.cuda.get_device_name(0),
                   "time_costs": res.extra_outputs.get("time_costs") if hasattr(res, "extra_outputs") else None},
                  open(os.path.join(out, f"seed{seed}.json"), "w"), indent=1, default=str)
        print(f"seed {seed}: {dt:.1f}s", flush=True)
    print(f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
