"""Stage 4: narration, one WAV per shot.

One provider is chosen for the whole film (first available in the chain) so the voice never
changes mid-film. Each line is cached by (text, provider, voice settings, seed), so editing
one narration line regenerates exactly one file.

Providers:
  gemini-tts      Gemini API TTS (needs GEMINI_API_KEY; model via GEMINI_TTS_MODEL)
  local:mms-tts   facebook/mms-tts-<lang> (VITS) on CPU; Amharic is romanised with uroman
"""
from __future__ import annotations

import argparse
import base64
import os
import time
import wave
from pathlib import Path

from .common import (
    ProviderUnavailable, require_online, cache_hit, cache_key, cache_write, device_name, duration_s, ffmpeg,
    load_storyboard, log, log_call, model_path, retry, stage_paths,
)
from . import prices

MMS_RATE = float(os.environ.get("MMS_SPEAKING_RATE", "1.0"))
MMS_NOISE = float(os.environ.get("MMS_NOISE_SCALE", "0.6"))
MMS_SEED = int(os.environ.get("MMS_SEED", "7"))
GEMINI_MODEL = "gemini-3.8-flash-tts"  # verified current id, 26 Nov 2026
GEMINI_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Sulafat")
GEMINI_STYLE = "calm, warm, unhurried storyteller"  # default; storyboard.voice.style overrides

_mms: dict = {}

# Silence inserted after each Ethiopic punctuation mark (seconds). See EXPERIMENTS.md E04.
PAUSES = {"።": 0.55, "?": 0.55, "፦": 0.35, "፣": 0.25, "፤": 0.3}


def split_for_pauses(text: str) -> list[tuple[str, float]]:
    """'a፣ b። c' -> [('a', .25), ('b', .55), ('c', 0)]. Quote marks are dropped."""
    import re

    out, buf = [], ""
    for ch in text.replace("«", "").replace("»", ""):
        if ch in PAUSES:
            if buf.strip():
                out.append((buf.strip(), PAUSES[ch]))
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append((buf.strip(), 0.0))
    return [(re.sub(r"\s+", " ", c), p) for c, p in out]


def _uromanize(text: str, lang: str) -> str:
    import uroman as ur

    if "u" not in _mms:
        _mms["u"] = ur.Uroman()
    return _mms["u"].romanize_string(text, lcode=lang)


def mms_prepare(text: str, lang: str) -> str:
    """What the MMS tokenizer actually sees. Ethiopic punctuation becomes pauses."""
    from transformers import AutoTokenizer

    tok = _mms.get(("tok", lang)) or AutoTokenizer.from_pretrained(model_path(f"facebook/mms-tts-{lang}"))
    _mms[("tok", lang)] = tok
    t = text
    for a, b in {"።": ".", "፣": ",", "፤": ",", "፦": ":", "«": "", "»": "", "?": "?"}.items():
        t = t.replace(a, b)
    if getattr(tok, "is_uroman", False):
        t = _uromanize(t, lang)
    return t.lower()


def tts_mms(text: str, lang: str, out: Path, item: str, ck: str) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoTokenizer, VitsModel

    model_id = f"facebook/mms-tts-{lang}"
    if ("m", lang) not in _mms:
        _mms[("m", lang)] = VitsModel.from_pretrained(model_path(model_id)).eval()
        _mms[("tok", lang)] = AutoTokenizer.from_pretrained(model_path(model_id))
    model, tok = _mms[("m", lang)], _mms[("tok", lang)]
    # E04: the MMS vocabulary has no punctuation, so "።" or "," is silently dropped and gives
    # no pause. Split at Ethiopic punctuation, synthesise each chunk, insert explicit silences.
    chunks = split_for_pauses(text)
    prepared = " | ".join(mms_prepare(c, lang) for c, _ in chunks)
    params = {"speaking_rate": MMS_RATE, "noise_scale": MMS_NOISE, "uroman": bool(getattr(tok, "is_uroman", False)),
              "input_chars": len(text), "prepared": prepared, "chunks": len(chunks), "pauses": PAUSES}
    t0 = time.time()
    try:
        model.speaking_rate = MMS_RATE
        model.noise_scale = MMS_NOISE
        torch.manual_seed(MMS_SEED)
        sr = model.config.sampling_rate
        parts = []
        for chunk, pause in chunks:
            inputs = tok(mms_prepare(chunk, lang), return_tensors="pt")
            with torch.no_grad():
                parts.append(model(**inputs).waveform[0].numpy())
            parts.append(np.zeros(int(pause * sr), dtype=np.float32))
        wav = np.concatenate(parts)
    except Exception as e:
        log_call(stage="narration", item=item, provider="local:mms-tts", model=model_id, params=params, seed=MMS_SEED,
                 latency_s=round(time.time() - t0, 2), device=device_name(), status="error", cache_key=ck, error=repr(e))
        raise
    raw = out.with_suffix(".raw.wav")
    sf.write(raw, wav.astype(np.float32), model.config.sampling_rate)
    _finish(raw, out)
    dt = time.time() - t0
    log_call(stage="narration", item=item, provider="local:mms-tts", model=model_id, params=params, seed=MMS_SEED,
             latency_s=round(dt, 2), device=device_name(), compute_s=round(dt, 2),
             list_price_usd=prices.gpu_equivalent_usd(dt), cache_key=ck, output=str(out.relative_to(out.parents[1])),
             audio_s=round(duration_s(out), 2))
    return params


BATCH_MIN_LINES = int(os.environ.get("GEMINI_BATCH_MIN_LINES", "3"))
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


def _quota_wait(text: str) -> float | None:
    """Seconds the server asks us to wait ('Please retry in 58s' / '23h4m31s'); None if absent."""
    import re

    m = re.search(r"retry in ((?:\d+h)?(?:\d+m)?(?:[\d.]+s)?)", text)
    if not m or not m.group(1):
        return None
    t = 0.0
    for num, unit in re.findall(r"([\d.]+)([hms])", m.group(1)):
        t += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return t


def tts_gemini(text: str, lang: str, out: Path, item: str, ck: str, voice: dict | None = None) -> dict:
    """Gemini TTS through the Interactions API (verified 26 Nov 2026, FAILURES F09).
    Reads Ge'ez script directly: no romanisation, no chunking. Returns a 24 kHz mono WAV."""
    require_online("gemini-tts")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ProviderUnavailable("GEMINI_API_KEY not set")
    import requests

    voice = voice or {}
    # the storyboard wins over the environment: a creative choice must travel with the contract (F18)
    model = voice.get("gemini_model") or os.environ.get("GEMINI_TTS_MODEL") or GEMINI_MODEL
    name = voice.get("gemini_voice") or GEMINI_VOICE
    style = voice.get("style") or GEMINI_STYLE
    params = {"voice": name, "style": style}
    from .quota import guard

    guard(model, "experiment" if ck == "experiment" else "film")  # never burn the film's quota on tests
    body = {"model": model,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": text, "annotations": [
                {"type": "speech_metadata", "style": style}]}]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": name}]}}

    class Fatal(Exception):
        pass

    @retry(times=4, base_delay=5, retry_on=(requests.RequestException, RuntimeError))
    def call():
        r = requests.post(GEMINI_URL, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                          json=body, timeout=180)
        if r.status_code == 429:
            wait = _quota_wait(r.text)
            if wait is None or wait > 120:  # daily quota: retrying today is pointless (F09)
                raise ProviderUnavailable(f"{model} quota exhausted: {r.text[:160]}")
            log(f"  [gemini-tts] per-minute limit; waiting {wait:.0f}s as the server asks")
            time.sleep(wait + 1)
            raise RuntimeError("429 per-minute limit")
        if r.status_code >= 500:
            log_call(stage="narration", item=f"{item}:attempt", provider="gemini-tts", model=model, device="hosted",
                     status="error", error=f"{r.status_code} {r.text[:120]}")  # counts against the quota
            raise RuntimeError(f"{r.status_code} {r.text[:200]}")  # server: retry
        if r.status_code >= 400:
            raise Fatal(f"{r.status_code} {r.text[:300]}")  # bad request / auth: do not retry
        return r.json()

    t0 = time.time()
    try:
        data = call()
        audio = next(c for st in data.get("steps", []) for c in st.get("content", []) if c.get("type") == "audio")
        wav_bytes = base64.b64decode(audio["data"])
    except Exception as e:
        log_call(stage="narration", item=item, provider="gemini-tts", model=model, params=params,
                 latency_s=round(time.time() - t0, 2), device="hosted", status="error", cache_key=ck,
                 error=repr(e)[:500])
        raise
    raw = out.with_suffix(".raw.wav")
    raw.write_bytes(wav_bytes)  # complete RIFF/WAV, 24 kHz mono 16-bit
    _finish(raw, out)
    usage = data.get("usage", {})
    log_call(stage="narration", item=item, provider="gemini-tts", model=data.get("model", model), params=params,
             latency_s=round(time.time() - t0, 2), device="hosted", cost_usd=0.0, cache_key=ck,
             output=str(out.relative_to(out.parents[1])), audio_s=round(duration_s(out), 2),
             tokens_in=usage.get("total_input_tokens"), tokens_out=usage.get("total_output_tokens"),
             interaction_id=data.get("id"))
    return params


def _finish(raw: Path, out: Path) -> None:
    """48 kHz mono, trimmed silence at both ends, light high-pass; per-line loudness evened out."""
    ffmpeg("-i", str(raw), "-af",
           "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
           "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
           "highpass=f=70,loudnorm=I=-18:TP=-2:LRA=7", "-ar", "48000", "-ac", "1", str(out))
    raw.unlink(missing_ok=True)


IMPLS = {"gemini-tts": tts_gemini, "local:mms-tts": tts_mms}


BATCH_GAP_STYLE = ("Read each paragraph as a separate line of narration. "
                   "Leave a long, clear silence of about two seconds between paragraphs.")


def align_cuts(runs, chars, n_samples, sr, silent):
    """Choose len(chars)-1 silent runs as line boundaries so that each piece's length best matches
    its expected share (proportional to characters). Dynamic programming over candidate pauses,
    with a small bonus for longer pauses. E22: the model left 0.4-1.0 s between lines, the same as
    pauses inside lines, so "the N-1 longest pauses" failed while this alignment succeeded."""
    import math
    from functools import lru_cache

    import numpy as np

    voiced = np.where(~silent)[0]
    a0, a1 = int(voiced[0]), int(voiced[-1])
    cand = [r for r in runs if a0 < r[0] < a1]
    n = len(chars)
    exp = np.array(chars, float) / sum(chars) * ((a1 - a0) / sr)

    @lru_cache(None)
    def f(start, k, ci):
        if k == n - 1:
            return (math.log(max(1e-3, (a1 - start) / sr) / exp[k]) ** 2, ())
        best = (float("inf"), ())
        for j in range(ci, len(cand) - (n - 2 - k)):
            s0, e0 = cand[j]
            c = math.log(max(1e-3, (s0 - start) / sr) / exp[k]) ** 2 - 0.15 * min(1.0, (e0 - s0) / sr)
            sub = f(e0, k + 1, j + 1)
            if c + sub[0] < best[0]:
                best = (c + sub[0], (j,) + sub[1])
        return best

    _, idx = f(a0, 0, 0)
    return [cand[j] for j in idx]


def gemini_batch(lines: list[tuple[str, str]], d: Path, voice: dict | None, cks: dict[str, str]) -> dict[str, dict]:
    """One Gemini TTS request for several lines (the free tier allows ~10 requests/day, a film has
    8-12 lines). Split the returned audio at the N-1 longest silences and validate each piece's
    length against its text. Raises ValueError if the split is not trustworthy (caller falls back)."""
    import numpy as np
    import soundfile as sf

    v = dict(voice or {})
    v["style"] = f"{v.get('style') or GEMINI_STYLE}. {BATCH_GAP_STYLE}"
    take = d / "_batch_take.wav"
    joined = "\n\n".join(t for _, t in lines)
    params = tts_gemini(joined, "", take, "batch:" + ",".join(i for i, _ in lines), "batch", v)
    x, sr = sf.read(take)
    win = int(0.02 * sr)
    rms = np.sqrt(np.convolve(x ** 2, np.ones(win) / win, mode="same"))
    silent = rms < max(1e-4, 0.03 * np.percentile(rms, 95))
    # silent runs (start, end) longer than 0.35 s
    runs, start = [], None
    for i, sil in enumerate(silent):
        if sil and start is None:
            start = i
        elif not sil and start is not None:
            if (i - start) / sr > 0.35:
                runs.append((start, i))
            start = None
    n = len(lines)
    if len(runs) < n - 1:
        raise ValueError(f"batch split: found {len(runs)} gaps for {n} lines")
    cuts = align_cuts(runs, [len(t) for _, t in lines], len(x), sr, silent)
    bounds = [0] + [(a + b) // 2 for a, b in cuts] + [len(x)]
    # voiced length = from the end of the previous gap to the start of the next one (not the midpoints,
    # which add half a gap to each side and inflate short lines)
    v_start = [0] + [b for _, b in cuts]
    v_end = [a for a, _ in cuts] + [len(x)]
    durs = np.array([(v_end[i] - v_start[i]) / sr for i in range(n)])
    chars = np.array([len(t) for _, t in lines], float)
    ratio = (durs / durs.sum()) / (chars / chars.sum())
    if ratio.min() < 0.35 or ratio.max() > 2.8:
        raise ValueError(f"batch split: implausible segment lengths (ratio {ratio.round(2).tolist()})")
    out = {}
    for i, (sid, text) in enumerate(lines):
        raw = d / f"{sid}.raw.wav"
        sf.write(raw, x[bounds[i]:bounds[i + 1]], sr)
        path = d / f"{sid}.wav"
        _finish(raw, path)
        cache_write(path, cks[sid], provider="gemini-tts", text=text, params={**params, "batch": True,
                    "batch_index": i, "batch_size": n, "split_ratio": round(float(ratio[i]), 2)})
        out[sid] = {"ratio": round(float(ratio[i]), 2), "dur": round(float(durs[i]), 2)}
    log(f"  [gemini-tts] 1 request -> {n} lines; length/text ratios {ratio.round(2).tolist()}")
    return out


def pick_provider(chain: list[str]) -> str:
    for name in chain:
        if name == "gemini-tts" and (not os.environ.get("GEMINI_API_KEY") or os.environ.get("HERITAGE_OFFLINE") == "1"):
            log("  [narration] gemini-tts unavailable: " + ("HERITAGE_OFFLINE=1" if os.environ.get("HERITAGE_OFFLINE") == "1" else "GEMINI_API_KEY not set"))
            continue
        if name in IMPLS:
            return name
    raise RuntimeError("no narration provider available")


def voice_settings(provider: str, voice: dict | None = None) -> dict:
    if provider == "local:mms-tts":
        return {"rate": MMS_RATE, "noise": MMS_NOISE, "seed": MMS_SEED, "pauses": PAUSES, "chunked": 1}
    v = voice or {}
    return {"model": v.get("gemini_model") or os.environ.get("GEMINI_TTS_MODEL") or GEMINI_MODEL,
            "voice": v.get("gemini_voice") or GEMINI_VOICE, "style": v.get("style") or GEMINI_STYLE}


def narration(sb: dict, only: set[str] | None = None, force: bool = False) -> dict[str, Path]:
    d = stage_paths("narration")
    lang = sb["film"]["language"]
    provider = pick_provider(sb["providers"]["narration"])
    out, todo, cks = {}, [], {}
    for shot in sb["shots"]:
        sid, text = shot["id"], shot["narration"].strip()
        if not text:
            continue
        path = d / f"{sid}.wav"
        out[sid] = path
        ck = cache_key(stage="narration", text=text, lang=lang, provider=provider, voice=voice_settings(provider, sb.get("voice")))
        cks[sid] = ck
        if only and sid not in only and path.exists():
            continue
        if not force and cache_hit(path, ck):
            log(f"  narration/{sid}: cached")
            continue
        # F16: never overwrite a line made by a BETTER provider just because it is unavailable right now
        # (offline, out of quota). Keep the cached hosted take for the same text.
        chain = sb["providers"]["narration"]
        better = chain[:chain.index(provider)] if provider in chain else []
        kept = False
        for bp in better:
            bk = cache_key(stage="narration", text=text, lang=lang, provider=bp, voice=voice_settings(bp, sb.get("voice")))
            if not force and cache_hit(path, bk):
                log(f"  narration/{sid}: keeping cached {bp} take ({provider} would be a downgrade)")
                cks[sid] = bk
                kept = True
                break
        if kept:
            continue
        todo.append((sid, text))
    if provider == "gemini-tts" and len(todo) >= BATCH_MIN_LINES:
        log(f"  narration: {len(todo)} lines in ONE Gemini request (free tier is ~10 requests/day)")
        try:
            gemini_batch(todo, d, sb.get("voice"), cks)
            todo = []
        except ValueError as e:
            from .quota import remaining

            model = (sb.get("voice") or {}).get("gemini_model") or os.environ.get("GEMINI_TTS_MODEL") or GEMINI_MODEL
            if remaining(model) < len(todo):  # F15: never let a fallback spend the quota it cannot finish with
                raise RuntimeError(f"batch split failed ({e}) and only ~{remaining(model)} {model} requests remain "
                                   f"for {len(todo)} lines; the take is kept at {d / '_batch_take.wav'} for an offline split")
            log(f"  [gemini-tts] {e}; falling back to one request per line")
    for sid, text in todo:
        log(f"  narration/{sid}: generating with {provider}")
        # No per-line fallback on purpose: switching provider for one line would change the voice
        # mid-film. A hosted failure after retries stops the stage; rerun with the provider
        # removed from the chain to regenerate the whole narration with the next one.
        if provider == "gemini-tts":
            params = tts_gemini(text, lang, d / f"{sid}.wav", sid, cks[sid], sb.get("voice"))
        else:
            params = IMPLS[provider](text, lang, d / f"{sid}.wav", sid, cks[sid])
        cache_write(d / f"{sid}.wav", cks[sid], provider=provider, text=text, params=params)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    narration(load_storyboard(), set(a.only) if a.only else None, a.force)


if __name__ == "__main__":
    main()
