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
import json
import base64
import io
import os
import time
from pathlib import Path

from PIL import Image

from .common import (
    ProviderUnavailable, require_online, cache_hit, cache_key, cache_write, device_name, expand_prompt,
    file_hash, load_storyboard, model_path, log, log_call, retry, run_chain, stage_paths,
)
from . import prices

SIZE = int(os.environ.get("KEYFRAME_SIZE", "512"))  # square; both aspect ratios are cropped from it
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


def gen_local(name: str, prompt: str, seed: int, ref: Path | None, item: str, out: Path, ck: str,
              strength: float | None = None) -> dict:
    strength = strength or REF_STRENGTH
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
            params.update({"mode": "img2img", "strength": strength, "ref": ref.name})
            img = pipe(prompt=prompt, image=init, num_inference_steps=STEPS, strength=strength,
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


FLUX_SIZE = int(os.environ.get("FLUX_SIZE", "1024"))  # FLUX's native resolution; cost is per 512px tile
FLUX_STEPS = int(os.environ.get("FLUX_STEPS", "4"))
# FLUX.2 klein multipart field names are not documented on the model page (checked 26 Nov 2026);
# confirmed by a probe call and overridable here (FAILURES F11).
KLEIN_FIELDS = json.loads(os.environ.get("KLEIN_FIELDS", '{"prompt": "prompt", "width": "width", "height": "height", '
                                         '"steps": "steps", "seed": "seed", "image": "input_image_0"}'))


def _cf_post(model: str, purpose: str, neurons: float, **kw):
    require_online("cloudflare")
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        raise ProviderUnavailable("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set")
    import requests

    from .quota import cf_guard

    cf_guard(model, neurons, purpose)

    @retry(times=3, base_delay=5, retry_on=(RuntimeError, requests.RequestException))
    def call():
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}",
                          headers={"Authorization": f"Bearer {token}"}, timeout=180, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            raise RuntimeError(f"{r.status_code} {r.text[:200]}")
        if r.status_code >= 400:
            raise ProviderUnavailable(f"{model}: {r.status_code} {r.text[:300]}")
        ctype = r.headers.get("content-type", "")
        if ctype.startswith("image/"):
            return r.content
        d = r.json()
        res = d.get("result", d)
        return base64.b64decode(res["image"])

    return call()


def gen_cloudflare(name: str, prompt: str, seed: int, ref: Path | None, item: str, out: Path, ck: str,
                   strength: float | None = None) -> dict:
    """cloudflare:@cf/black-forest-labs/flux-1-schnell (JSON) or ...flux-2-klein-4b (multipart, reference)."""
    from .quota import cf_cost

    model = name.split(":", 1)[1]
    purpose = "experiment" if ck == "experiment" else "film"
    klein = "flux-2-klein" in model
    t0 = time.time()
    if klein:
        ref_tiles = 4 if ref else 0  # a 1024px reference = 4 input tiles
        neurons = cf_cost(model, FLUX_SIZE, FLUX_SIZE, FLUX_STEPS, ref_tiles)
        f = KLEIN_FIELDS
        data = {f["prompt"]: prompt, f["width"]: str(FLUX_SIZE), f["height"]: str(FLUX_SIZE),
                f["seed"]: str(seed), f["steps"]: str(FLUX_STEPS)}
        files = {k: (None, v) for k, v in data.items()}
        if ref:
            buf = io.BytesIO()
            Image.open(ref).convert("RGB").resize((FLUX_SIZE, FLUX_SIZE)).save(buf, "PNG")
            files[f["image"]] = ("reference.png", buf.getvalue(), "image/png")
        params = {"size": FLUX_SIZE, "steps": FLUX_STEPS, "reference": ref.name if ref else None, "neurons": neurons}
        kw = {"files": files}
    else:
        neurons = cf_cost(model, 1024, 1024, FLUX_STEPS)  # schnell has no size parameter; output is 1024
        params = {"steps": FLUX_STEPS, "neurons": neurons,
                  "note": "schnell takes no reference image; identity comes from the character text" if ref else ""}
        kw = {"json": {"prompt": prompt, "steps": FLUX_STEPS}}  # schnell rejects "seed" (400, E17): not reproducible
    try:
        img_bytes = _cf_post(model, purpose, neurons, **kw)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        log_call(stage="keyframes", item=item, provider="cloudflare", model=model, params=params, seed=seed,
                 latency_s=round(time.time() - t0, 2), device="hosted", status="error", cache_key=ck,
                 error=repr(e)[:400])
        raise
    native = img.size
    side = min(img.size)  # centre-square (both aspect ratios are cropped from a square)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2, (img.width + side) // 2, (img.height + side) // 2))
    img.save(out)
    log_call(stage="keyframes", item=item, provider="cloudflare", model=model, params={**params, "native": native},
             seed=seed, latency_s=round(time.time() - t0, 2), device="hosted", cost_usd=0.0, neurons=neurons,
             list_price_usd=round(neurons / 1000 * 0.011, 5), cache_key=ck,
             output=str(out.relative_to(out.parents[1])), prompt=prompt)
    return params


IMPLS = {"local:sd-turbo": gen_local, "cloudflare": gen_cloudflare}


CLIP_MAX_TOKENS = 77  # SD-Turbo's text encoder silently truncates anything longer (FAILURES F08)


def check_prompt_lengths(sb: dict) -> None:
    """Fail before generating if any prompt would be truncated: the style block sits at the end,
    so truncation would silently drop exactly the part that keeps the look consistent."""
    from transformers import CLIPTokenizer

    from .common import StoryboardError

    tok = CLIPTokenizer.from_pretrained(model_path("stabilityai/sd-turbo"), subfolder="tokenizer")
    prompts = {f"ref:{n}": f"{c['reference_prompt']}, {sb['style']['style_block']}" for n, c in sb["characters"].items()}
    prompts.update({s["id"]: expand_prompt(sb, s) for s in sb["shots"]})
    over = {k: len(tok(p).input_ids) for k, p in prompts.items() if len(tok(p).input_ids) > CLIP_MAX_TOKENS}
    if over:
        raise StoryboardError("prompts longer than 77 CLIP tokens (would be truncated): "
                              + ", ".join(f"{k}={v}" for k, v in over.items()))


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
    chain = sb["providers"]["keyframes"]
    if chain and chain[0].startswith("local:sd-turbo"):
        check_prompt_lengths(sb)  # primary provider truncates at 77 tokens: fail early (F08)
    elif any(p.startswith("local:sd-turbo") for p in chain):
        try:  # FLUX reads up to 512 tokens; only the fallback would truncate, so warn instead of failing
            check_prompt_lengths(sb)
        except Exception as e:
            log(f"  [keyframes] warning for the SD-Turbo fallback only: {e}")
    refs = references(sb)
    d = stage_paths("keyframes")
    out = {}
    import shutil

    for shot in sb["shots"]:
        sid = shot["id"]
        path = d / f"{sid}.png"
        out[sid] = path
        if shot.get("keyframe_from"):
            continue  # filled after the source shot exists
        prompt = expand_prompt(sb, shot)
        strength = shot.get("ref_strength", REF_STRENGTH)
        ref = refs[shot["characters"][0]] if shot["characters"] and strength is not None else None
        ck = cache_key(stage="keyframe", prompt=prompt, seed=shot["seed"], chain=sb["providers"]["keyframes"],
                       size=SIZE, steps=STEPS, ref=file_hash(ref) if ref else None,
                       ref_strength=strength if ref else None)
        if only and sid not in only and path.exists():
            continue
        if not force and cache_hit(path, ck):
            log(f"  keyframes/{sid}: cached")
            continue
        log(f"  keyframes/{sid}: generating" + (f" (reference {ref.name}: used by SD-Turbo img2img only; FLUX ignores it)" if ref else ""))
        prov, params = run_chain("keyframes", sb["providers"]["keyframes"], IMPLS, prompt, shot["seed"], ref, sid,
                                 path, ck, strength if ref else None)
        cache_write(path, ck, provider=prov, prompt=prompt, seed=shot["seed"], params=params)
    for shot in sb["shots"]:  # reuse: same picture, same person by construction (test 2 feedback)
        if shot.get("keyframe_from"):
            src = out[shot["keyframe_from"]]
            dst = out[shot["id"]]
            ck = cache_key(stage="keyframe_from", src=file_hash(src))
            if force or not cache_hit(dst, ck):
                shutil.copy(src, dst)
                cache_write(dst, ck, provider="reuse", source=shot["keyframe_from"])
                log(f"  keyframes/{shot['id']}: reused from {shot['keyframe_from']} (no model call)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    keyframes(load_storyboard(), set(a.only) if a.only else None, a.force)


if __name__ == "__main__":
    main()
