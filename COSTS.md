# COSTS.md: measured latency, compute and list-price equivalent

**Actual spend: $0.00.** Everything ran locally on the build laptop: an 8-core x86 CPU, 14 GB RAM, **no GPU**, Linux. No hosted API was paid or used for the film.

## Per-model-call measurements (from `runs.jsonl`, via `make costs`)
Production calls only: experiment and smoke-test calls are excluded (they are in `runs.jsonl` with `stage: "experiment"` / `"smoke"`, 46 + 7 lines).

| stage | provider | model | calls | ok | errors | mean latency (s) | max (s) | CPU min | T4-min equiv. | list-price equiv. (USD) |
|---|---|---|---|---|---|---|---|---|---|---|
| narration | local:mms-tts | facebook/mms-tts-amh | 24 | 24 | 0 | 1.10 | 1.65 | 0.44 | 0.06 | 0.0003 |
| keyframes | local:sd-turbo | stabilityai/sd-turbo | 22 | 22 | 0 | 34.0 | 44.9 | 12.47 | 1.56 | 0.0117 |
| music | local:musicgen-small | facebook/musicgen-small | 4 | 4 | 0 | 183.2 | 242.9 | 12.21 | 1.53 | 0.0089 |
| music | local:procedural | procedural_score.py (not AI) | 6 | 6 | 0 | 1.15 | 1.18 | 0.12 | 0.01 | 0 |
| **total** | | | **56** | **56** | 0 | | | **25.2** | **3.2** | **$0.021** |

* narration: 24 = 12 lines × 2 passes (rate 0.85, then 1.0 after E02).
* keyframes: 22 = 3 references + 12 shots, + 4 shots from a run stopped when the prompts were found to be truncated (F08), + 3 regenerations of s12.
* music: MusicGen 4 = 3 score candidates of 26 s + 1 three-second smoke-test call. **MusicGen runs at ≈ 0.14× real time on this CPU** (243 s for 26 s of audio).

## Wall-clock per stage, the full film from a cold cache
From `outputs/pipeline.log`, run `20261126T100620`. Narration was already cached; its own cold timing is from run `20261126T055125`.

| stage | wall time | model calls | notes |
|---|---|---|---|
| validate | < 1 s | 0 | schema + semantic checks + CLIP token budget |
| narration | 25 s | 12 | MMS-TTS, ~1.1 s per line |
| timeline + radio cut | 14 s | 0 | FFmpeg |
| references + keyframes | 8 min 31 s | 15 | SD-Turbo 512 px, 4 steps, ~34 s/image |
| shots (Ken Burns, 2 ratios) | 2 min 28 s | 0 | 24 FFmpeg renders |
| music | 11 min 47 s | 3 | MusicGen-small, 26 s candidates |
| assemble (2 exports) | 2 min 15 s | 0 | ducking, two-pass loudnorm, subtitles, end card, H.264 |
| **total** | **25 min 13 s** | **30** | |
| **incremental: one keyframe prompt changed** | **3 min 30 s – 3 min 53 s** | **1** | runs `…103229`, `…103936`; mostly FFmpeg re-assembly |

## List-price equivalent: how it is computed
All rates live in `pipeline/prices.py` so they can be corrected in one place. **They are assumptions, not quotes. None were verified against a live pricing page during the build (no billing account).**
* Local CPU work is priced as the GPU time it would need on a rented NVIDIA T4: `cpu_seconds / 8` (assumed T4 speed-up over this CPU for these small models) × **$0.35 per T4-hour** (assumed typical on-demand rate). 25.2 CPU-min → 3.2 T4-min → **≈ $0.02**.
* Keyframes are also priced per image at an assumed **$0.00053/image** for FLUX.1 schnell on Cloudflare Workers AI, which would be inside the free daily allowance.
* Not run, estimated for the GPU path: Wan 2.2 TI2V-5B, assumed ~12 T4-min per 5 s clip (the brief: "several minutes on a 4090, longer on a T4") → 12 clips ≈ 2.4 T4-hours ≈ **$0.84**, or ~8 % of Kaggle's ~30 free weekly GPU hours.

## Free tiers: what was actually found (26 Nov 2026)
| service | status here |
|---|---|
| Gemini API (TTS) | not tested: no key on the build machine (F04) |
| Cloudflare Workers AI | not tested: no account (F04) |
| Kaggle GPU | not tested: needs the owner's phone verification (F01) |
| Hugging Face weight downloads | free, no login needed for SD-Turbo, MMS, MusicGen. **The real constraint was bandwidth**: 200 KB/s, and a two-hour stall (F03, F07) |
| keyless hosted image endpoint (pollinations) | free, **6–7 s/image** vs 34 s local, but silently served `sana` instead of FLUX, watermarked, and returned **503 on 1 of 3 calls** (E11) |

## Frontier comparison
No frontier model (Omni Flash, Nano Banana, Lyria) was available. The only hosted comparison is E11 (keyless endpoint vs local SD-Turbo): hosted was **~10× faster** but ignored the character description and style, and could not be reproduced (unknown model, no seed guarantee).

## Download cost (the hidden one)
| weights | size | time on this link |
|---|---|---|
| PyTorch CPU wheel | 210 MB | ~60 min (shared link) |
| MMS-TTS amh / tir / orm | 145 MB each | ~10–25 min each |
| SD-Turbo fp16 (UNet + text encoder + VAE) | 2.58 GB | ~4 h (stalled), then ~3 min after a reconnect |
| MusicGen-small | 2.36 GB | ~5 min after the reconnect |
On a slow link, **model size, not compute, was the binding constraint**. That is why fp16 variants were chosen and a procedural score fallback exists.
