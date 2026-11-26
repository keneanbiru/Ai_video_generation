"""Stage 2: reference sheet, then one keyframe per shot.

Order matters: the character reference images are generated (and cached) first; any shot
that lists a character is conditioned on that character's golden reference (img2img) when
the provider supports it. Prompts always carry the unchanged style block.

Providers (storyboard.providers.keyframes, tried in order):
  cloudflare:<model>  Cloudflare Workers AI (needs CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN)
  local:sd-turbo      stabilityai/sd-turbo through diffusers, runs on CPU
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import time
from pathlib import Path

from PIL import Image

from .common import (
    ProviderUnavailable, cache_hit, cache_key, cache_write, device_name, expand_prompt,
    file_hash, load_storyboard, model_path, log, log_call, retry, run_chain, stage_paths,
)
from . import prices

SIZE = int(os.environ.get("KEYFRAME_SIZE", "640"))  # square; both aspect ratios are cropped from it
STEPS = int(os.environ.get("KEYFRAME_STEPS", "4"))
REF_STRENGTH = float(os.environ.get("KEYFRAME_REF_STRENGTH", "0.8"))

_pipes: dict = {}


def _sd_turbo(img2img: bool):
    key = "i2i" if img2img else "t2i"
    if key in _pipes:
        return _pipes[key]
    import torch
    from diffusers import AutoPipelineForImage2Image, AutoPipelineForText2Image

    torch.set_num_threads(os.cpu_count() or 4)
    if "t2i" not in _pipes:
        _pipes["t2i"] = AutoPipelineForText2Image.from_pretrained(model_path("stabilityai/sd-turbo"), variant="fp16",
                                                                   torch_dtype=torch.float32)
        _pipes["t2i"].set_progress_bar_config(disable=True)
    if img2img:
        _pipes["i2i"] = AutoPipelineForImage2Image.from_pipe(_pipes["t2i"])
        _pipes["i2i"].set_progress_bar_config(disable=True)
    return _pipes[key]


def gen_local(name: str, prompt: str, seed: int, ref: Path | None, item: str, out: Path, ck: str) -> dict:
    if model_path("stabilityai/sd-turbo") == "stabilityai/sd-turbo" and not os.environ.get("ALLOW_HF_DOWNLOAD"):
        raise ProviderUnavailable("sd-turbo weights not downloaded yet (tools/fetch_models.sh); "
                                  "set ALLOW_HF_DOWNLOAD=1 to let diffusers fetch 2.6 GB")
    import torch

    t0 = time.time()
    g = torch.Generator("cpu").manual_seed(seed)
    params = {"steps": STEPS, "size": SIZE, "guidance_scale": 0.0}
    try:
        if ref is not None:
            pipe = _sd_turbo(img2img=True)
            init = Image.open(ref).convert("RGB").resize((SIZE, SIZE))
            params.update({"mode": "img2img", "strength": REF_STRENGTH, "ref": ref.name})
            img = pipe(prompt=prompt, image=init, num_inference_steps=STEPS, strength=REF_STRENGTH,
                       guidance_scale=0.0, generator=g).images[0]
        else:
            pipe = _sd_turbo(img2img=False)
            params["mode"] = "txt2img"
            img = pipe(prompt=prompt, num_inference_steps=STEPS, guidance_scale=0.0,
                       width=SIZE, height=SIZE, generator=g).images[0]
    except Exception as e:
        log_call(stage="keyframes", item=item, provider=name, model="stabilityai/sd-turbo", params=params,
                 seed=seed, latency_s=round(time.time() - t0, 2), device=device_name(), status="error",
                 cache_key=ck, error=repr(e))
        raise
    img.save(out)
    dt = time.time() - t0
    log_call(stage="keyframes", item=item, provider=name, model="stabilityai/sd-turbo", params=params, seed=seed,
             latency_s=round(dt, 2), device=device_name(), compute_s=round(dt, 2),
             list_price_usd=prices.image_equivalent(), cache_key=ck, output=str(out.relative_to(out.parents[1])),
             prompt=prompt)
    return params


def gen_cloudflare(name: str, prompt: str, seed: int, ref: Path | None, item: str, out: Path, ck: str) -> dict:
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        raise ProviderUnavailable("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set")
    import requests

    model = name.split(":", 1)[1]
    params = {"steps": 4, "seed": seed, "note": "reference conditioning not used on this endpoint" if ref else ""}

    @retry(times=3, base_delay=4)
    def call():
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"prompt": prompt, "steps": 4, "seed": seed}, timeout=120)
        if r.status_code == 429:
            raise RuntimeError("429 rate limited / daily allowance used")
        r.raise_for_status()
        return r.json()

    t0 = time.time()
    try:
        data = call()
        b64 = data["result"]["image"]
    except Exception as e:
        log_call(stage="keyframes", item=item, provider="cloudflare", model=model, params=params, seed=seed,
                 latency_s=round(time.time() - t0, 2), status="error", cache_key=ck, error=repr(e))
        raise
    Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out)
    log_call(stage="keyframes", item=item, provider="cloudflare", model=model, params=params, seed=seed,
             latency_s=round(time.time() - t0, 2), device="hosted", cost_usd=0.0,
             list_price_usd=prices.image_equivalent("cloudflare"), cache_key=ck,
             output=str(out.relative_to(out.parents[1])), prompt=prompt)
    return params


IMPLS = {"local:sd-turbo": gen_local, "cloudflare": gen_cloudflare}


def references(sb: dict, force: bool = False) -> dict[str, Path]:
    """Character reference sheet: one golden image per character, generated before any shot."""
    d = stage_paths("references")
    out = {}
    for name, c in sb["characters"].items():
        prompt = f"{c['reference_prompt']}, {sb['style']['style_block']}"
        path = d / f"{name}.png"
        ck = cache_key(stage="reference", prompt=prompt, seed=c["reference_seed"], chain=sb["providers"]["keyframes"],
                       size=SIZE, steps=STEPS)
        if not force and cache_hit(path, ck):
            log(f"  references/{name}: cached")
        else:
            log(f"  references/{name}: generating")
            prov, params = run_chain("keyframes", sb["providers"]["keyframes"], IMPLS, prompt, c["reference_seed"],
                                     None, f"ref:{name}", path, ck)
            cache_write(path, ck, provider=prov, prompt=prompt, seed=c["reference_seed"], params=params)
        out[name] = path
    return out


def keyframes(sb: dict, only: set[str] | None = None, force: bool = False) -> dict[str, Path]:
    refs = references(sb)
    d = stage_paths("keyframes")
    out = {}
    for shot in sb["shots"]:
        sid = shot["id"]
        path = d / f"{sid}.png"
        out[sid] = path
        prompt = expand_prompt(sb, shot)
        ref = refs[shot["characters"][0]] if shot["characters"] else None
        ck = cache_key(stage="keyframe", prompt=prompt, seed=shot["seed"], chain=sb["providers"]["keyframes"],
                       size=SIZE, steps=STEPS, ref=file_hash(ref) if ref else None,
                       ref_strength=REF_STRENGTH if ref else None)
        if only and sid not in only and path.exists():
            continue
        if not force and cache_hit(path, ck):
            log(f"  keyframes/{sid}: cached")
            continue
        log(f"  keyframes/{sid}: generating ({'img2img on ' + ref.name if ref else 'txt2img'})")
        prov, params = run_chain("keyframes", sb["providers"]["keyframes"], IMPLS, prompt, shot["seed"], ref, sid,
                                 path, ck)
        cache_write(path, ck, provider=prov, prompt=prompt, seed=shot["seed"], params=params)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    keyframes(load_storyboard(), set(a.only) if a.only else None, a.force)


if __name__ == "__main__":
    main()
