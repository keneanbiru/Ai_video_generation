"""ACE-Step score candidates on a Kaggle/Colab GPU, one WAV per seed in storyboard.music.candidates.

STATUS: NOT executed (no GPU here; see FAILURES.md F06/F07). The call below follows the
ACE-Step v1 Python API (`ACEStepPipeline`). ACE-Step 1.5 may have renamed the entry point;
check https://github.com/ACE-Step/ACE-Step-1.5 and adjust `render()` only. The output
contract the local music stage expects is fixed:
    outputs/music_acestep/seed<N>.wav  +  seed<N>.json {"caption", "model", "params", "latency_s", "device"}
The local stage rejects a track whose recorded caption differs from storyboard.music.caption.

Kaggle:
    !git clone https://github.com/ACE-Step/ACE-Step-1.5 && pip install -q -e ACE-Step-1.5
    !python kaggle/acestep_score.py --repo /kaggle/working/heritage-short
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def render(caption: str, seconds: float, seed: int, out: Path) -> dict:
    from acestep.pipeline_ace_step import ACEStepPipeline  # adjust for 1.5 if needed

    pipe = render.__dict__.setdefault("pipe", ACEStepPipeline(dtype="float16"))
    params = {"audio_duration": seconds, "infer_step": 27, "guidance_scale": 15, "lyrics": "[instrumental]"}
    pipe(prompt=caption, manual_seeds=[seed], save_path=str(out), **params)
    return params


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    import torch

    repo = Path(a.repo)
    m = json.loads((repo / "storyboard.json").read_text())["music"]
    d = repo / "outputs" / "music_acestep"
    d.mkdir(parents=True, exist_ok=True)
    for seed in m["candidates"]:
        t0 = time.time()
        params = render(m["caption"], m["segment_s"], seed, d / f"seed{seed}.wav")
        (d / f"seed{seed}.json").write_text(json.dumps({
            "caption": m["caption"], "model": "ACE-Step-1.5", "params": params,
            "latency_s": round(time.time() - t0, 1), "device": torch.cuda.get_device_name(0)}, indent=1))
        print(f"seed {seed}: {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
