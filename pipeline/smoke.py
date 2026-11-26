"""Phase-1 smoke test: call each provider once, log latency to runs.jsonl, report what works here.

    python -m pipeline.smoke
"""
from __future__ import annotations

import json
import os
import time

from .common import OUT, ProviderUnavailable, cache_key, ffmpeg_bin, log, log_call, run, stage_paths


def main() -> int:
    d = stage_paths("smoke")
    results = {}

    def attempt(name, fn):
        t0 = time.time()
        try:
            fn()
            results[name] = f"ok ({time.time() - t0:.1f}s)"
        except ProviderUnavailable as e:
            results[name] = f"unavailable: {e}"
            log_call(stage="smoke", item=name, provider=name, status="unavailable", error=str(e),
                     latency_s=round(time.time() - t0, 2))
        except Exception as e:
            results[name] = f"FAILED: {e!r}"[:300]
            log_call(stage="smoke", item=name, provider=name, status="error", error=repr(e)[:500],
                     latency_s=round(time.time() - t0, 2))

    attempt("ffmpeg", lambda: run([ffmpeg_bin(), "-version"]))

    from . import keyframes, music, narration

    attempt("gemini-tts", lambda: narration.tts_gemini("ሰላም።", "amh", d / "gemini.wav", "smoke", "smoke"))
    attempt("local:mms-tts", lambda: narration.tts_mms("ሰላም። እንዴት ናችሁ?", "amh", d / "mms.wav", "smoke", "smoke"))
    attempt("cloudflare", lambda: keyframes.gen_cloudflare("cloudflare:@cf/black-forest-labs/flux-1-schnell",
                                                            "a clay coffee pot, gouache", 1, None, "smoke",
                                                            d / "cf.png", "smoke"))
    attempt("local:sd-turbo", lambda: keyframes.gen_local("local:sd-turbo", "a clay coffee pot, gouache", 1, None,
                                                          "smoke", d / "sd.png", "smoke"))
    attempt("local:musicgen-small", lambda: music.gen_musicgen("local:musicgen-small", "soft calm flute", 1, 3.0,
                                                               d / "mg.wav", "smoke"))
    attempt("kaggle-gpu (wan22/acestep)", lambda: (_ for _ in ()).throw(ProviderUnavailable(
        "runs only inside a Kaggle notebook; see kaggle/README.md")))
    (OUT / "smoke.json").write_text(json.dumps(results, indent=1))
    for k, v in results.items():
        log(f"  {k:28s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
