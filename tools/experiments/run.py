"""Experiments behind EXPERIMENTS.md. Each writes outputs/experiments/<name>/results.json.

    python -m tools.experiments.run <name> [<name> ...]      (from the repo root)

Model calls made here are logged to runs.jsonl with stage="experiment" (excluded from COSTS
production totals but kept as evidence).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline import common  # noqa: E402
from pipeline.common import OUT, duration_s, ffmpeg, ffmpeg_bin, log_call, loudness, load_storyboard  # noqa: E402

EXP = OUT / "experiments"


def save(name: str, data: dict) -> None:
    d = EXP / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(json.dumps(data, indent=1, ensure_ascii=False)[:4000])


def _silences(wav: Path, thresh="-35dB", d=0.12) -> list[float]:
    p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(wav), "-af", f"silencedetect=n={thresh}:d={d}",
                        "-f", "null", "-"], capture_output=True, text=True)
    return [float(x) for x in re.findall(r"silence_duration: ([0-9.]+)", p.stderr)]


# ---------------------------------------------------------------- E01 romanisation coverage
def e01_uroman():
    from transformers import AutoTokenizer

    from pipeline.narration import mms_prepare

    sb = load_storyboard()
    tok = AutoTokenizer.from_pretrained(common.model_path("facebook/mms-tts-amh"))
    vocab = set(tok.get_vocab())
    rows = []
    for s in sb["shots"]:
        raw = s["narration"].lower()
        prep = mms_prepare(s["narration"], "amh")
        oov_raw = sorted({c for c in raw if c not in vocab and not c.isspace()})
        oov_prep = sorted({c for c in prep if c not in vocab and not c.isspace()})
        rows.append({"id": s["id"], "raw_chars": len(raw),
                     "raw_in_vocab_pct": round(100 * sum(c in vocab for c in raw) / len(raw), 1),
                     "prepared_in_vocab_pct": round(100 * sum(c in vocab for c in prep) / max(1, len(prep)), 1),
                     "oov_prepared": oov_prep, "prepared": prep, "oov_raw_sample": oov_raw[:8]})
    save("e01_uroman", {"is_uroman": bool(getattr(tok, "is_uroman", False)), "vocab_size": len(vocab),
                        "vocab": "".join(sorted(vocab)), "rows": rows})


# ---------------------------------------------------------------- E02/E03/E04 TTS knobs
def _tts(text: str, out: Path, rate: float, noise: float, seed: int, lang="amh", prepare=True) -> float:
    import soundfile as sf
    import torch
    from transformers import AutoTokenizer, VitsModel

    from pipeline.narration import _mms, mms_prepare

    mid = f"facebook/mms-tts-{lang}"
    if ("m", lang) not in _mms:
        _mms[("m", lang)] = VitsModel.from_pretrained(common.model_path(mid)).eval()
        _mms[("tok", lang)] = AutoTokenizer.from_pretrained(common.model_path(mid))
    model, tok = _mms[("m", lang)], _mms[("tok", lang)]
    t = mms_prepare(text, lang) if prepare else text.lower()
    model.speaking_rate, model.noise_scale = rate, noise
    torch.manual_seed(seed)
    t0 = time.time()
    with torch.no_grad():
        w = model(**tok(t, return_tensors="pt")).waveform[0].numpy()
    dt = time.time() - t0
    sf.write(out, w, model.config.sampling_rate)
    log_call(stage="experiment", item=out.stem, provider="local:mms-tts", model=mid,
             params={"rate": rate, "noise": noise, "prepare": prepare}, seed=seed, latency_s=round(dt, 2),
             device=common.device_name(), compute_s=round(dt, 2), output=str(out.relative_to(ROOT)))
    return dt


def e02_rate():
    """Speaking-rate sweep through the real narration path (chunked, with pauses)."""
    from pipeline import narration

    sb = load_storyboard()
    d = EXP / "e02_rate"
    d.mkdir(parents=True, exist_ok=True)
    words = sum(len(s["narration"].split()) for s in sb["shots"])
    res = {"words": words, "rates": {}}
    for rate in (0.85, 1.0, 1.1, 1.2):
        narration.MMS_RATE = rate
        tot, lat = 0.0, 0.0
        film = sb["end_card"]["duration_s"]
        for s in sb["shots"]:
            p = d / f"{s['id']}_r{rate}.wav"
            t0 = time.time()
            narration.tts_mms(s["narration"], "amh", p, f"e02:{s['id']}:r{rate}", "experiment")
            lat += time.time() - t0
            v = duration_s(p)
            tot += v
            film += max(s["min_duration_s"], s.get("narration_delay_s", 0.4) + v + 0.9)
        res["rates"][str(rate)] = {"speech_s": round(tot, 2), "words_per_s": round(words / tot, 2),
                                   "film_s_estimate": round(film, 1), "tts_latency_s": round(lat, 2)}
    save("e02_rate", res)


def e03_determinism():
    sb = load_storyboard()
    d = EXP / "e03_det"
    d.mkdir(parents=True, exist_ok=True)
    text = sb["shots"][5]["narration"]
    import hashlib

    out = {}
    for tag, seed in (("a", 7), ("b", 7), ("c", 8), ("d", 9), ("e", 10)):
        p = d / f"{tag}_seed{seed}.wav"
        _tts(text, p, 0.85, 0.6, seed)
        out[tag] = {"seed": seed, "sha": hashlib.sha256(p.read_bytes()).hexdigest()[:12], "dur": round(duration_s(p), 3)}
    durs = [v["dur"] for v in out.values()]
    save("e03_determinism", {"runs": out, "same_seed_identical": out["a"]["sha"] == out["b"]["sha"],
                             "duration_spread_s": round(max(durs) - min(durs), 3)})


def e04_punct():
    sb = load_storyboard()
    d = EXP / "e04_punct"
    d.mkdir(parents=True, exist_ok=True)
    res = {}
    for sid in ("s05", "s08", "s09"):
        s = next(x for x in sb["shots"] if x["id"] == sid)
        mapped = d / f"{sid}_mapped.wav"
        _tts(s["narration"], mapped, 0.85, 0.6, 7, prepare=True)
        # control: romanise but DROP Ethiopic punctuation instead of mapping it to , . :
        import uroman as ur

        stripped_txt = re.sub(r"[።፣፤፦«»]", " ", s["narration"])
        stripped = d / f"{sid}_stripped.wav"
        _tts(ur.Uroman().romanize_string(stripped_txt, lcode="amh"), stripped, 0.85, 0.6, 7, prepare=False)
        res[sid] = {"mapped": {"dur": round(duration_s(mapped), 2), "pauses": _silences(mapped)},
                    "stripped": {"dur": round(duration_s(stripped), 2), "pauses": _silences(stripped)},
                    "ethiopic_punct_count": len(re.findall(r"[።፣፤፦]", s["narration"]))}
    save("e04_punct", res)


# ---------------------------------------------------------------- E05/E06 image size & steps
def e05_size_steps():
    import torch

    from pipeline import keyframes as kf

    sb = load_storyboard()
    shot = next(s for s in sb["shots"] if s["id"] == "s04")
    prompt = common.expand_prompt(sb, shot)
    d = EXP / "e05_size_steps"
    d.mkdir(parents=True, exist_ok=True)
    pipe = kf._sd_turbo(img2img=False)
    res = {}
    for size, steps in ((512, 1), (512, 4), (640, 1), (640, 4), (768, 4)):
        g = torch.Generator("cpu").manual_seed(shot["seed"])
        t0 = time.time()
        img = pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=0.0, width=size, height=size,
                   generator=g).images[0]
        dt = time.time() - t0
        p = d / f"s04_{size}_{steps}step.png"
        img.save(p)
        log_call(stage="experiment", item=p.stem, provider="local:sd-turbo", model="stabilityai/sd-turbo",
                 params={"size": size, "steps": steps}, seed=shot["seed"], latency_s=round(dt, 2),
                 device=common.device_name(), compute_s=round(dt, 2), output=str(p.relative_to(ROOT)))
        res[f"{size}px_{steps}step"] = {"latency_s": round(dt, 2)}
    save("e05_size_steps", res)


# ---------------------------------------------------------------- E07 character consistency
def _hist_sim(a: Path, b: Path) -> float:
    from PIL import Image

    def h(p):
        im = Image.open(p).convert("HSV").resize((128, 128))
        arr = np.asarray(im)
        hist, _ = np.histogramdd(arr.reshape(-1, 3), bins=(12, 4, 4), range=((0, 256),) * 3)
        hist = hist.ravel() / hist.sum()
        return hist

    ha, hb = h(a), h(b)
    return float(np.minimum(ha, hb).sum())  # histogram intersection, 1.0 = identical colour distribution


def e07_consistency():
    import torch
    from PIL import Image

    from pipeline import keyframes as kf

    sb = load_storyboard()
    refs = kf.references(sb)
    ref = refs["emama"]
    d = EXP / "e07_consistency"
    d.mkdir(parents=True, exist_ok=True)
    res = {}
    for sid in ("s02", "s06", "s09"):
        shot = next(s for s in sb["shots"] if s["id"] == sid)
        prompt = common.expand_prompt(sb, shot)
        for mode, strength in (("txt2img", None), ("img2img", 0.6), ("img2img", 0.8), ("img2img", 0.9)):
            g = torch.Generator("cpu").manual_seed(shot["seed"])
            t0 = time.time()
            if mode == "txt2img":
                img = kf._sd_turbo(False)(prompt=prompt, num_inference_steps=4, guidance_scale=0.0, width=640,
                                         height=640, generator=g).images[0]
            else:
                init = Image.open(ref).convert("RGB").resize((640, 640))
                img = kf._sd_turbo(True)(prompt=prompt, image=init, num_inference_steps=4, strength=strength,
                                        guidance_scale=0.0, generator=g).images[0]
            dt = time.time() - t0
            tag = f"{sid}_{mode}{'' if strength is None else strength}"
            p = d / f"{tag}.png"
            img.save(p)
            log_call(stage="experiment", item=tag, provider="local:sd-turbo", model="stabilityai/sd-turbo",
                     params={"mode": mode, "strength": strength}, seed=shot["seed"], latency_s=round(dt, 2),
                     device=common.device_name(), compute_s=round(dt, 2), output=str(p.relative_to(ROOT)))
            res[tag] = {"latency_s": round(dt, 2), "colour_similarity_to_ref": round(_hist_sim(p, ref), 3)}
    save("e07_consistency", res)


# ---------------------------------------------------------------- E08 music candidates
def _music_metrics(wav: Path) -> dict:
    import soundfile as sf
    from scipy.signal import stft

    x, sr = sf.read(wav)
    x = x.mean(axis=1) if x.ndim > 1 else x
    f, t, Z = stft(x, sr, nperseg=2048)
    mag = np.abs(Z) + 1e-10
    flat = np.exp(np.mean(np.log(mag), axis=0)) / np.mean(mag, axis=0)
    flux = np.sqrt((np.diff(mag, axis=1).clip(0) ** 2).sum(axis=0))
    onsets = int((flux > flux.mean() + 2 * flux.std()).sum())
    centroid = (f[:, None] * mag).sum(0) / mag.sum(0)
    # energy in the speech band 300-3400 Hz competes with the narrator
    band = (f >= 300) & (f <= 3400)
    speech_share = float((mag[band] ** 2).sum() / (mag ** 2).sum())
    rms = np.sqrt(np.convolve(x ** 2, np.ones(sr // 2) / (sr // 2), mode="valid"))
    return {"onsets_per_min": round(onsets / (len(x) / sr) * 60, 1),
            "spectral_flatness": round(float(np.median(flat)), 4),
            "centroid_hz": round(float(np.median(centroid)), 0),
            "speech_band_energy_share": round(speech_share, 3),
            "loudness_range_db": round(float(20 * np.log10(np.percentile(rms, 95) / (np.percentile(rms, 10) + 1e-9))), 1)}


def e08_music():
    from pipeline import music

    sb = load_storyboard()
    c = music.candidates(sb)
    res = {}
    for seed, p in c.items():
        meta = common.cache_meta(p)
        res[f"seed{seed}"] = {"provider": meta.get("provider"), **_music_metrics(p)}
    save("e08_music", res)


# ---------------------------------------------------------------- E09 ducking depth
def e09_duck():
    """How many dB does the music drop while the narrator speaks, for several duck settings?"""
    import soundfile as sf

    sb = load_storyboard()
    tl = json.loads((OUT / "timeline.json").read_text())
    nar = OUT / "final" / "narration.wav"
    nar = nar if nar.exists() else OUT / "radio_cut" / "narration.wav"
    bed = OUT / "music" / "bed.wav"
    d = EXP / "e09_duck"
    d.mkdir(parents=True, exist_ok=True)
    speech = [(t["narration_start"], t["narration_start"] + t["narration_s"]) for t in tl["shots"]
              if t["narration_start"] is not None]
    settings = {
        "none_bed-10": None,
        "brief_default": {"threshold": 0.02, "ratio": 6, "attack_ms": 300, "release_ms": 1500, "bed_gain_db": -10},
        "faster_attack": {"threshold": 0.02, "ratio": 6, "attack_ms": 80, "release_ms": 800, "bed_gain_db": -10},
        "attack80_only": {"threshold": 0.02, "ratio": 6, "attack_ms": 80, "release_ms": 1500, "bed_gain_db": -10},
        "release800_only": {"threshold": 0.02, "ratio": 6, "attack_ms": 300, "release_ms": 800, "bed_gain_db": -10},
        "hard": {"threshold": 0.01, "ratio": 12, "attack_ms": 80, "release_ms": 1500, "bed_gain_db": -10},
    }
    res = {}
    for name, s in settings.items():
        out = d / f"{name}.wav"
        if s is None:
            ffmpeg("-i", str(bed), "-af", "volume=-10dB", str(out))
        else:
            ffmpeg("-i", str(bed), "-i", str(nar), "-filter_complex",
                   f"[0:a]volume={s['bed_gain_db']}dB[m];[1:a]aformat=channel_layouts=stereo[v];"
                   f"[m][v]sidechaincompress=threshold={s['threshold']}:ratio={s['ratio']}:attack={s['attack_ms']}:"
                   f"release={s['release_ms']}:makeup=1[o]", "-map", "[o]", str(out))
        x, sr = sf.read(out)
        x = x.mean(axis=1)
        mask = np.zeros(len(x), bool)
        for a, b in speech:
            mask[int(a * sr): int(b * sr)] = True

        def db(v):
            return 10 * np.log10(np.mean(v ** 2) + 1e-12)

        res[name] = {"music_db_during_speech": round(db(x[mask]), 2), "music_db_in_gaps": round(db(x[~mask]), 2),
                     "duck_depth_db": round(db(x[~mask]) - db(x[mask]), 2)}
    save("e09_duck", res)


# ---------------------------------------------------------------- E10 loudnorm one vs two pass
def e10_loudnorm():
    pre = EXP / "e10_loudnorm"
    pre.mkdir(parents=True, exist_ok=True)
    src = OUT / "final" / "mix.wav"
    src = src if src.exists() else OUT / "radio_cut" / "mix.wav"
    one = pre / "one_pass.wav"
    ffmpeg("-i", str(src), "-af", "volume=-6dB,loudnorm=I=-14:TP=-1:LRA=11", "-ar", "48000", str(one))
    quiet = pre / "quiet_input.wav"
    ffmpeg("-i", str(src), "-af", "volume=-6dB", str(quiet))
    from pipeline.assemble import mix  # two-pass path, via the real function on a fresh pre-mix

    two = pre / "two_pass.wav"
    p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(quiet), "-af",
                        "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    m = json.loads(p[p.rfind("{"): p.rfind("}") + 1])
    ffmpeg("-i", str(quiet), "-af", f"loudnorm=I=-14:TP=-1:LRA=11:measured_I={m['input_i']}:"
           f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
           f"offset={m['target_offset']}:linear=true", "-ar", "48000", str(two))
    save("e10_loudnorm", {"input": loudness(quiet), "one_pass": loudness(one), "two_pass": loudness(two),
                          "target": {"integrated_lufs": -14, "true_peak_dbtp": -1}})


# ---------------------------------------------------------------- E12 Ken Burns jitter
def e12_kenburns():
    """Frame-to-frame motion smoothness of zoompan with and without the 3x pre-upscale."""
    from PIL import Image

    kfp = OUT / "keyframes" / "s06.png"
    d = EXP / "e12_kenburns"
    d.mkdir(parents=True, exist_ok=True)
    res = {}
    for up in (1, 3):
        out = d / f"up{up}.mp4"
        n = 96
        vf = (f"crop=iw:iw*720/1280:0:(ih-oh)/2,scale={1280 * up}:{720 * up}:flags=lanczos,"
              f"zoompan=z='1+0.18*on/{n - 1}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={n}:s=1280x720:fps=24")
        t0 = time.time()
        ffmpeg("-loop", "1", "-i", str(kfp), "-vf", vf, "-frames:v", str(n), "-c:v", "libx264", "-crf", "16", str(out))
        dt = time.time() - t0
        # measure: per-frame centre-crop shift via phase correlation of consecutive frames
        frames_dir = d / f"f{up}"
        frames_dir.mkdir(exist_ok=True)
        ffmpeg("-i", str(out), "-vf", "crop=320:180,format=gray", str(frames_dir / "%03d.png"))
        fr = [np.asarray(Image.open(p), dtype=float) for p in sorted(frames_dir.glob("*.png"))]
        diffs = [float(np.abs(fr[i + 1] - fr[i]).mean()) for i in range(len(fr) - 1)]
        for p in frames_dir.glob("*.png"):
            p.unlink()
        frames_dir.rmdir()
        res[f"upscale_{up}x"] = {"render_s": round(dt, 2), "mean_frame_diff": round(float(np.mean(diffs)), 3),
                                 "frame_diff_cv": round(float(np.std(diffs) / (np.mean(diffs) + 1e-9)), 3)}
    save("e12_kenburns", res)


EXPERIMENTS = {k.split("_", 1)[0]: v for k, v in globals().items() if re.match(r"e\d\d_", k) and callable(v)}

if __name__ == "__main__":
    for name in sys.argv[1:]:
        EXPERIMENTS[name]()
