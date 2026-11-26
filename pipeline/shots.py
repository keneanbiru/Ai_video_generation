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


def _crop_for(ratio: str, focus: dict | None = None) -> str:
    """Crop the square keyframe to the ratio, centred on the shot's subject (storyboard focus),
    clamped to the image. Without focus it falls back to the centre (v1 behaviour)."""
    w, h = RATIOS[ratio]
    fx, fy = (focus or {}).get("x", 0.5), (focus or {}).get("y", 0.5)
    if w >= h:  # landscape window from a square: full width, band centred on the subject's height
        return f"crop=iw:iw*{h}/{w}:0:'max(0,min(ih-oh,{fy}*ih-oh/2))'"
    return f"crop=ih*{w}/{h}:ih:'max(0,min(iw-ow,{fx}*iw-ow/2))':0"


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
    vf = (f"{_crop_for(ratio, shot.get('focus'))},scale={w * 3}:{h * 3}:flags=lanczos,"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={w}x{h}:fps={FPS},"
          f"noise=alls=5:allf=t,format=yuv420p")
    ffmpeg("-loop", "1", "-i", str(keyframe), "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(out))
    return {"provider": "kenburns", "frames": n, **kb}


def wan_import(name: str, shot: dict, keyframe: Path, dur: float, ratio: str, out: Path) -> dict:
    if str(shot.get("wan_qc", "")).startswith("reject"):
        raise ProviderUnavailable(f"Wan clip for {shot['id']} rejected in QC ({shot['wan_qc']})")
    src = OUT / "clips_wan" / f"{shot['id']}.mp4"
    meta_p = OUT / "clips_wan" / f"{shot['id']}.json"
    if not src.exists() or not meta_p.exists():
        raise ProviderUnavailable(f"no Wan clip for {shot['id']} (render on Kaggle with kaggle/wan22_i2v.py)")
    meta = json.loads(meta_p.read_text())
    if meta.get("keyframe_sha16") != file_hash(keyframe) or meta.get("motion_prompt") != shot["motion_prompt"]:
        raise ProviderUnavailable(f"Wan clip for {shot['id']} is stale (keyframe or motion prompt changed)")
    w, h = RATIOS[ratio]
    from .common import duration_s

    clip = max(0.5, duration_s(src) - 0.5)  # usable length after trimming the weak first/last 0.25 s
    slow = min(1.5, max(1.0, dur / clip))  # stretch up to 1.5x before holding the last frame
    # square Wan clip -> cover the target ratio at 2x, hold the last frame for any remainder, and run a
    # slow continuous zoom over the WHOLE shot so the picture keeps moving after the AI motion ends (E23).
    n = max(2, int(round(dur * FPS)))
    kb = shot["kenburns"]
    z0, z1 = min(kb["zoom_from"], kb["zoom_to"]), max(kb["zoom_from"], kb["zoom_to"])
    z1 = max(z1, z0 + 0.06)  # always some drift, even if the storyboard asked for a static frame
    vf = (f"trim=start=0.25:end={0.25 + clip:.3f},setpts={slow:.3f}*(PTS-STARTPTS),fps={FPS},"
          f"{_crop_for(ratio, shot.get('focus'))},scale={2 * w}:{2 * h}:flags=lanczos,"
          f"tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f},"
          f"zoompan=z='{z0}+({z1}-{z0})*on/{n - 1}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s={w}x{h}:fps={FPS},"
          f"unsharp=5:5:0.7:5:5:0.0,"  # E27: 512 px clips upscaled ~2.5x measured 61-85 % of the stills' sharpness
          f"format=yuv420p")
    ffmpeg("-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out))
    if ratio == "16x9":  # log the Kaggle GPU call once per clip, not once per aspect ratio
        log_call(stage="shots", item=shot["id"], provider="wan22:kaggle", model=meta.get("model"),
                 params=meta.get("params", {}), seed=meta.get("seed"), latency_s=meta.get("latency_s"),
                 device=meta.get("device"), compute_s=meta.get("latency_s"), imported=True,
                 output=str(src.relative_to(OUT.parent)))
    return {"provider": "wan22:kaggle", "source": src.name, "slowdown": round(slow, 3)}


IMPLS = {"wan22": wan_import, "kenburns": kenburns}


def shots(sb: dict, keyframes: dict[str, Path], timeline: dict, force: bool = False) -> dict[str, dict[str, Path]]:
    durs = {t["id"]: t["duration"] for t in timeline["shots"]}
    # a shot that the NEXT shot dissolves out of is rendered longer by the dissolve, so the overlap
    # does not shorten the film or move any narration (assemble.join_with_transitions)
    for cur, nxt in zip(sb["shots"], sb["shots"][1:]):
        if nxt.get("transition_in") == "dissolve":
            durs[cur["id"]] = round(durs[cur["id"]] + nxt.get("transition_s", 1.0), 3)
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
                           wan=file_hash(wan) if wan.exists() else None, wan_qc=shot.get("wan_qc"), focus=shot.get("focus"), v=5)
            res[ratio][sid] = path
            if not force and cache_hit(path, ck):
                continue
            prov, meta = run_chain("shots", sb["providers"]["shots"], IMPLS, shot, kf, durs[sid], ratio, path)
            cache_write(path, ck, **meta)
            log(f"  shots/{ratio}/{sid}: rendered with {prov} ({durs[sid]:.2f}s)")
    return res
