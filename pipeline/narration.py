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
    ProviderUnavailable, cache_hit, cache_key, cache_write, device_name, duration_s, ffmpeg,
    load_storyboard, log, log_call, model_path, retry, stage_paths,
)
from . import prices

MMS_RATE = float(os.environ.get("MMS_SPEAKING_RATE", "1.0"))
MMS_NOISE = float(os.environ.get("MMS_NOISE_SCALE", "0.6"))
MMS_SEED = int(os.environ.get("MMS_SEED", "7"))
GEMINI_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Sulafat")
GEMINI_STYLE = "Read slowly and warmly, like an adult remembering their grandmother, in Amharic:"

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


def tts_gemini(text: str, lang: str, out: Path, item: str, ck: str) -> dict:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ProviderUnavailable("GEMINI_API_KEY not set")
    import requests

    params = {"voice": GEMINI_VOICE, "style": GEMINI_STYLE}

    @retry(times=4, base_delay=5)
    def call():
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": f"{GEMINI_STYLE} {text}"}]}],
                  "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                      "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_VOICE}}}}},
            timeout=120)
        if r.status_code == 429:
            raise RuntimeError("429 quota exhausted")
        r.raise_for_status()
        return r.json()

    t0 = time.time()
    try:
        data = call()
        pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    except Exception as e:
        log_call(stage="narration", item=item, provider="gemini-tts", model=GEMINI_MODEL, params=params,
                 latency_s=round(time.time() - t0, 2), status="error", cache_key=ck, error=repr(e))
        raise
    raw = out.with_suffix(".raw.wav")
    with wave.open(str(raw), "wb") as w:  # Gemini returns 24 kHz 16-bit mono PCM
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    _finish(raw, out)
    log_call(stage="narration", item=item, provider="gemini-tts", model=GEMINI_MODEL, params=params,
             latency_s=round(time.time() - t0, 2), device="hosted", cache_key=ck,
             output=str(out.relative_to(out.parents[1])), audio_s=round(duration_s(out), 2))
    return params


def _finish(raw: Path, out: Path) -> None:
    """48 kHz mono, trimmed silence at both ends, light high-pass; per-line loudness evened out."""
    ffmpeg("-i", str(raw), "-af",
           "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
           "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
           "highpass=f=70,loudnorm=I=-18:TP=-2:LRA=7", "-ar", "48000", "-ac", "1", str(out))
    raw.unlink(missing_ok=True)


IMPLS = {"gemini-tts": tts_gemini, "local:mms-tts": tts_mms}


def pick_provider(chain: list[str]) -> str:
    for name in chain:
        if name == "gemini-tts" and not os.environ.get("GEMINI_API_KEY"):
            log("  [narration] gemini-tts unavailable: GEMINI_API_KEY not set")
            continue
        if name in IMPLS:
            return name
    raise RuntimeError("no narration provider available")


def voice_settings(provider: str) -> dict:
    if provider == "local:mms-tts":
        return {"rate": MMS_RATE, "noise": MMS_NOISE, "seed": MMS_SEED, "pauses": PAUSES, "chunked": 1}
    return {"model": GEMINI_MODEL, "voice": GEMINI_VOICE, "style": GEMINI_STYLE}


def narration(sb: dict, only: set[str] | None = None, force: bool = False) -> dict[str, Path]:
    d = stage_paths("narration")
    lang = sb["film"]["language"]
    provider = pick_provider(sb["providers"]["narration"])
    out = {}
    for shot in sb["shots"]:
        sid, text = shot["id"], shot["narration"].strip()
        if not text:
            continue
        path = d / f"{sid}.wav"
        out[sid] = path
        ck = cache_key(stage="narration", text=text, lang=lang, provider=provider, voice=voice_settings(provider))
        if only and sid not in only and path.exists():
            continue
        if not force and cache_hit(path, ck):
            log(f"  narration/{sid}: cached")
            continue
        log(f"  narration/{sid}: generating with {provider}")
        # No per-line fallback on purpose: switching provider for one line would change the voice
        # mid-film. A hosted failure after retries stops the stage; rerun with the provider
        # removed from the chain to regenerate the whole narration with the next one.
        params = IMPLS[provider](text, lang, path, sid, ck)
        cache_write(path, ck, provider=provider, text=text, params=params)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    narration(load_storyboard(), set(a.only) if a.only else None, a.force)


if __name__ == "__main__":
    main()
