"""Stage 3: one moving shot per storyboard shot, in both aspect ratios.

Providers (storyboard.providers.shots):
  wan22:kaggle  imports a Wan 2.2 TI2V-5B clip rendered by kaggle/wan22_i2v.py into
                outputs/clips_wan/<id>.mp4. The import is accepted only if the clip's sidecar
                says it was made from the current keyframe hash and motion prompt, so a
                changed keyframe can never be paired with a stale clip.
  kenburns      slow zoom/pan over the keyframe with FFmpeg (deterministic, no model call).

Both ratios are cropped from the same centred square keyframe, so the subject stays in the
vertical safe area.
"""
from __future__ import annotations

import json
from pathlib import Path

from .common import (
    OUT, ProviderUnavailable, cache_hit, cache_key, cache_write, ffmpeg, file_hash, log, log_call, run_chain, stage_paths,
)

RATIOS = {"16x9": (1280, 720), "9x16": (720, 1280)}
FPS = 24


def _crop_for(ratio: str) -> str:
    w, h = RATIOS[ratio]
    if w >= h:  # landscape window from a square: full width, centred band
        return f"crop=iw:iw*{h}/{w}:0:(ih-oh)/2"
    return f"crop=ih*{w}/{h}:ih:(iw-ow)/2:0"


def kenburns(name: str, shot: dict, keyframe: Path, dur: float, ratio: str, out: Path) -> dict:
    w, h = RATIOS[ratio]
    kb = shot["kenburns"]
    n = max(2, int(round(dur * FPS)))
    zf, zt = kb["zoom_from"], kb["zoom_to"]
    z = f"({zf}+({zt}-{zf})*on/{n - 1})"
    p = f"(on/{n - 1}-0.5)"
    x = {"left": f"(iw-iw/zoom)*(0.5-0.9*{p})", "right": f"(iw-iw/zoom)*(0.5+0.9*{p})"}.get(kb["pan"], "(iw-iw/zoom)/2")
    y = {"up": f"(ih-ih/zoom)*(0.5-0.9*{p})", "down": f"(ih-ih/zoom)*(0.5+0.9*{p})"}.get(kb["pan"], "(ih-ih/zoom)/2")
    # Upscale 3x before zoompan: zoompan rounds the window to whole pixels, which jitters at low res.
    vf = (f"{_crop_for(ratio)},scale={w * 3}:{h * 3}:flags=lanczos,"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={w}x{h}:fps={FPS},"
          f"noise=alls=5:allf=t,format=yuv420p")
    ffmpeg("-loop", "1", "-i", str(keyframe), "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(out))
    return {"provider": "kenburns", "frames": n, **kb}


def wan_import(name: str, shot: dict, keyframe: Path, dur: float, ratio: str, out: Path) -> dict:
    src = OUT / "clips_wan" / f"{shot['id']}.mp4"
    meta_p = OUT / "clips_wan" / f"{shot['id']}.json"
    if not src.exists() or not meta_p.exists():
        raise ProviderUnavailable(f"no Wan clip for {shot['id']} (render on Kaggle with kaggle/wan22_i2v.py)")
    meta = json.loads(meta_p.read_text())
    if meta.get("keyframe_sha16") != file_hash(keyframe) or meta.get("motion_prompt") != shot["motion_prompt"]:
        raise ProviderUnavailable(f"Wan clip for {shot['id']} is stale (keyframe or motion prompt changed)")
    w, h = RATIOS[ratio]
    # Trim the weak first/last 0.25 s, then hold the last frame if the shot is longer than the clip.
    vf = (f"trim=start=0.25,setpts=PTS-STARTPTS,"
          f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f},fps={FPS},format=yuv420p")
    ffmpeg("-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out))
    if ratio == "16x9":  # log the Kaggle GPU call once per clip, not once per aspect ratio
        log_call(stage="shots", item=shot["id"], provider="wan22:kaggle", model=meta.get("model"),
                 params=meta.get("params", {}), seed=meta.get("seed"), latency_s=meta.get("latency_s"),
                 device=meta.get("device"), compute_s=meta.get("latency_s"), imported=True,
                 output=str(src.relative_to(OUT.parent)))
    return {"provider": "wan22:kaggle", "source": src.name}


IMPLS = {"wan22": wan_import, "kenburns": kenburns}


def shots(sb: dict, keyframes: dict[str, Path], timeline: dict, force: bool = False) -> dict[str, dict[str, Path]]:
    durs = {t["id"]: t["duration"] for t in timeline["shots"]}
    res: dict[str, dict[str, Path]] = {r: {} for r in RATIOS}
    for ratio in RATIOS:
        d = stage_paths(f"shots/{ratio}")
        for shot in sb["shots"]:
            sid = shot["id"]
            path = d / f"{sid}.mp4"
            kf = keyframes[sid]
            wan = OUT / "clips_wan" / f"{sid}.mp4"
            ck = cache_key(stage="shot", kf=file_hash(kf), kb=shot["kenburns"], motion=shot["motion_prompt"],
                           dur=durs[sid], ratio=ratio, chain=sb["providers"]["shots"],
                           wan=file_hash(wan) if wan.exists() else None, v=2)
            res[ratio][sid] = path
            if not force and cache_hit(path, ck):
                continue
            prov, meta = run_chain("shots", sb["providers"]["shots"], IMPLS, shot, kf, durs[sid], ratio, path)
            cache_write(path, ck, **meta)
            log(f"  shots/{ratio}/{sid}: rendered with {prov} ({durs[sid]:.2f}s)")
    return res
