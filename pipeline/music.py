"""Stage 5: score candidates, then the chosen bed fitted to the film length.

Every seed in storyboard.music.candidates becomes one candidate (the composer's sketchbook).
The chosen seed is then looped with crossfades to the film length and shaped by the cue list
(start / dip / swell / out), which is the spotting session written as data.

Providers:
  acestep:kaggle        imports ACE-Step 1.5 tracks rendered by kaggle/acestep_score.py into
                        outputs/music_acestep/seed<N>.wav (no GPU here, so this cannot run locally)
  local:musicgen-small  facebook/musicgen-small through transformers, on CPU
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .common import (
    OUT, ProviderUnavailable, cache_hit, cache_key, cache_write, device_name, duration_s, ffmpeg,
    load_storyboard, log, log_call, model_path, run_chain, stage_paths,
)
from . import prices

_mg: dict = {}


def gen_musicgen(name: str, caption: str, seed: int, seconds: float, out: Path, ck: str) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    mid = "facebook/musicgen-small"
    if "m" not in _mg:
        _mg["p"] = AutoProcessor.from_pretrained(model_path(mid))
        _mg["m"] = MusicgenForConditionalGeneration.from_pretrained(model_path(mid)).eval()
    proc, model = _mg["p"], _mg["m"]
    tokens = int(seconds * model.config.audio_encoder.frame_rate)
    params = {"max_new_tokens": tokens, "guidance_scale": 3.0, "do_sample": True, "seconds": seconds}
    t0 = time.time()
    try:
        torch.manual_seed(seed)
        inputs = proc(text=[caption], padding=True, return_tensors="pt")
        with torch.no_grad():
            audio = model.generate(**inputs, do_sample=True, guidance_scale=3.0, max_new_tokens=tokens)
    except Exception as e:
        log_call(stage="music", item=f"seed{seed}", provider=name, model=mid, params=params, seed=seed,
                 latency_s=round(time.time() - t0, 2), device=device_name(), status="error", cache_key=ck, error=repr(e))
        raise
    sr = model.config.audio_encoder.sampling_rate
    raw = out.with_suffix(".raw.wav")
    sf.write(raw, audio[0, 0].numpy().astype(np.float32), sr)
    ffmpeg("-i", str(raw), "-af", "loudnorm=I=-20:TP=-3:LRA=11", "-ar", "48000", "-ac", "2", str(out))
    raw.unlink(missing_ok=True)
    dt = time.time() - t0
    log_call(stage="music", item=f"seed{seed}", provider=name, model=mid, params=params, seed=seed,
             latency_s=round(dt, 2), device=device_name(), compute_s=round(dt, 2),
             list_price_usd=prices.gpu_equivalent_usd(dt), cache_key=ck, output=str(out.relative_to(OUT.parent)),
             caption=caption, audio_s=round(duration_s(out), 2))
    return params


def gen_acestep_import(name: str, caption: str, seed: int, seconds: float, out: Path, ck: str) -> dict:
    src = OUT / "music_acestep" / f"seed{seed}.wav"
    meta = OUT / "music_acestep" / f"seed{seed}.json"
    if not src.exists():
        raise ProviderUnavailable(f"{src.relative_to(OUT.parent)} not found (render it with kaggle/acestep_score.py)")
    m = json.loads(meta.read_text()) if meta.exists() else {}
    if m.get("caption") != caption:
        raise ProviderUnavailable("imported ACE-Step track was rendered from a different caption")
    ffmpeg("-i", str(src), "-af", "loudnorm=I=-20:TP=-3:LRA=11", "-ar", "48000", "-ac", "2", str(out))
    # The GPU call itself was logged on Kaggle; merge its runs line here so runs.jsonl stays complete.
    log_call(stage="music", item=f"seed{seed}", provider="acestep:kaggle", model=m.get("model", "ACE-Step-1.5"),
             params=m.get("params", {}), seed=seed, latency_s=m.get("latency_s"), device=m.get("device", "kaggle"),
             compute_s=m.get("latency_s"), cache_key=ck, output=str(out.relative_to(OUT.parent)), imported=True)
    return {"imported": True, **m.get("params", {})}


def gen_procedural(name: str, caption: str, seed: int, seconds: float, out: Path, ck: str) -> dict:
    """Algorithmic fallback (not a model). Logged like a call so its latency is measured too."""
    import soundfile as sf

    from .procedural_score import SR, compose

    t0 = time.time()
    raw = out.with_suffix(".raw.wav")
    sf.write(raw, compose(seconds, seed), SR)
    ffmpeg("-i", str(raw), "-af", "loudnorm=I=-20:TP=-3:LRA=11", "-ar", "48000", "-ac", "2", str(out))
    raw.unlink(missing_ok=True)
    dt = time.time() - t0
    params = {"seconds": seconds, "bpm": 63, "scale": "tizita major pentatonic", "note": "algorithmic, not AI"}
    log_call(stage="music", item=f"seed{seed}", provider=name, model="procedural_score.py", params=params, seed=seed,
             latency_s=round(dt, 2), device=device_name(), compute_s=round(dt, 2), list_price_usd=0.0,
             cache_key=ck, output=str(out.relative_to(OUT.parent)), audio_s=round(duration_s(out), 2))
    return params


def gen_musicgen_checked(name: str, caption: str, seed: int, seconds: float, out: Path, ck: str) -> dict:
    from .common import model_path

    if model_path("facebook/musicgen-small") == "facebook/musicgen-small" and not os.environ.get("ALLOW_HF_DOWNLOAD"):
        raise ProviderUnavailable("musicgen-small weights not downloaded yet (tools/fetch_models.sh); "
                                  "set ALLOW_HF_DOWNLOAD=1 to let transformers fetch 2.4 GB")
    return gen_musicgen(name, caption, seed, seconds, out, ck)


IMPLS = {"acestep": gen_acestep_import, "local:musicgen-small": gen_musicgen_checked,
         "local:procedural": gen_procedural}


def best_available(chain: list[str], seed: int) -> str:
    """First provider in the chain that can run right now. Part of the cache key, so an output made
    by a fallback is regenerated automatically once a better provider becomes available (FAILURES F07)."""
    from .common import model_path

    for name in chain:
        if name.startswith("acestep") and (OUT / "music_acestep" / f"seed{seed}.wav").exists():
            return name
        if name == "local:musicgen-small" and (model_path("facebook/musicgen-small") != "facebook/musicgen-small"
                                               or os.environ.get("ALLOW_HF_DOWNLOAD")):
            return name
        if name == "local:procedural":
            return name
    return "none"


def candidates(sb: dict, force: bool = False) -> dict[int, Path]:
    m = sb["music"]
    d = stage_paths("music")
    out = {}
    for seed in m["candidates"]:
        path = d / f"candidate_seed{seed}.wav"
        from .procedural_score import VERSION as proc_version

        ck = cache_key(stage="music", caption=m["caption"], seed=seed, seconds=m["segment_s"],
                       chain=sb["providers"]["music"], best=best_available(sb["providers"]["music"], seed),
                       procedural_version=proc_version)
        out[seed] = path
        if not force and cache_hit(path, ck):
            log(f"  music/seed{seed}: cached")
            continue
        log(f"  music/seed{seed}: generating {m['segment_s']}s")
        prov, params = run_chain("music", sb["providers"]["music"], IMPLS, m["caption"], seed, m["segment_s"], path, ck)
        cache_write(path, ck, provider=prov, caption=m["caption"], seed=seed, params=params)
    return out


def cue_envelope(sb: dict, timeline: dict, total: float) -> str:
    """Turn the cue list into an ffmpeg volume expression (piecewise, smoothed by 1.5 s ramps)."""
    starts = {t["id"]: t["start"] for t in timeline["shots"]}
    level = {"start": 0.0, "dip": -4.0, "swell": 2.5, "out": 0.0}
    points = []  # (time, dB)
    for cue in sb["music"]["cues"]:
        points.append((starts[cue["at_shot"]], level[cue["action"]]))
    points.sort()
    ramp = 1.5

    def seg(i: int) -> str:
        """Gain in dB for t >= points[i].time: ramp from the previous level, hold, then the next segment."""
        t, db = points[i]
        prev = points[i - 1][1] if i else 0.0
        ramp_expr = f"({prev})+(({db})-({prev}))*(t-{t:.2f})/{ramp}"
        rest = seg(i + 1) if i + 1 < len(points) else f"{db}"
        if i + 1 < len(points):
            rest = f"if(lt(t,{points[i + 1][0]:.2f}),{db},{rest})"
        return f"if(lt(t,{t + ramp:.2f}),{ramp_expr},{rest})"

    expr = f"if(lt(t,{points[0][0]:.2f}),0,{seg(0)})" if points else "0"
    return f"pow(10,({expr})/20)"


def bed(sb: dict, timeline: dict, force: bool = False) -> Path:
    """Loop the chosen candidate with crossfades to film length, apply cues and fades."""
    cands = candidates(sb)
    src = cands[sb["music"]["chosen"]]
    total = timeline["total_s"]
    path = stage_paths("music") / "bed.wav"
    from .common import file_hash

    ck = cache_key(stage="bed", src=file_hash(src), total=round(total, 2), cues=sb["music"]["cues"],
                   starts=[(t["id"], t["start"]) for t in timeline["shots"]])
    if not force and cache_hit(path, ck):
        log("  music/bed: cached")
        return path
    seg = duration_s(src)
    xf = 3.0
    n = 1
    while n * seg - (n - 1) * xf < total + 1:
        n += 1
    inputs, chain, last = [], [], "[0:a]"
    for i in range(n):
        inputs += ["-i", str(src)]
    for i in range(1, n):
        lab = f"[x{i}]"
        chain.append(f"{last}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri{lab}")
        last = lab
    env = cue_envelope(sb, timeline, total)
    fade_out_at = max(0.0, total - 4.0)
    chain.append(f"{last}atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume='{env}':eval=frame,"
                 f"afade=t=in:d=2.5,afade=t=out:st={fade_out_at:.3f}:d=4[out]")
    ffmpeg(*inputs, "-filter_complex", ";".join(chain), "-map", "[out]", "-ar", "48000", "-ac", "2", str(path))
    cache_write(path, ck, source=src.name, loops=n)
    log(f"  music/bed: built from seed {sb['music']['chosen']} ({n} loops, {total:.1f}s)")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    candidates(load_storyboard(), a.force)


if __name__ == "__main__":
    main()
