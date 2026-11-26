# ቀስ በቀስ: *Slowly, Slowly*. A heritage short made by a pipeline

A 60–90 second film in **Amharic** with English subtitles and an original score, about a grandmother's coffee ceremony and the proverb she repeated to an impatient child: *ቀስ በቀስ እንቁላል በእግሩ ይሄዳል*, "slowly, slowly, an egg will walk on its own legs."

The film is made by code. One file, **`storyboard.json`**, is the contract. Each stage reads it and writes to `outputs/`: narration → timeline → radio cut → reference sheet + keyframes → moving shots → score → assembly (ducking, loudness, subtitles, end card, 16:9 + 9:16).

```
make film
```

## Quick start (clean clone)

Requirements: Linux/macOS, Python 3.10–3.12, **FFmpeg ≥ 6 with libass** on `PATH`, about 6 GB disk. **No GPU and no API keys needed.**

```bash
git clone <this repo> && cd heritage-short
make setup                  # .venv + CPU PyTorch + requirements.txt
./tools/fetch_models.sh     # optional: resumable download of the open weights (~2.9 GB; else fetched on first use with ALLOW_HF_DOWNLOAD=1)
make film                   # validate → … → outputs/film_16x9.mp4 and outputs/film_9x16.mp4
```

Other targets:

| Command | What it does |
|---|---|
| `make validate` | schema + semantic checks on `storyboard.json` only |
| `make radio` | stops after the radio cut (`outputs/radio_cut/radio_cut.mp4`), the cheap prototype for user test 1 |
| `make smoke` | calls each provider once and logs its latency, to see what works on your machine |
| `make test` | contract, cache and subtitle tests (no models needed) |
| `make costs` | per-stage calls, latency, CPU/GPU minutes and list-price equivalent from `runs.jsonl` |
| `python -m pipeline.keyframes --only s06` | one stage, one shot |

### Optional hosted / GPU providers
Copy `.env.example` to `.env` and fill in what you have. Each stage tries its providers in the order listed in `storyboard.json → providers` and falls through to the next when a key is missing or a quota runs out:

| Stage | Chain (first available wins) |
|---|---|
| keyframes | Cloudflare Workers AI FLUX.1 schnell → **local SD-Turbo (CPU)** |
| narration | Gemini TTS → **local MMS-TTS Amharic (CPU)** |
| shots | Wan 2.2 TI2V-5B clips rendered on Kaggle (`kaggle/wan22_i2v.py`) → **Ken Burns (FFmpeg)** |
| music | ACE-Step 1.5 rendered on Kaggle (`kaggle/acestep_score.py`) → **local MusicGen-small (CPU)** → procedural score |

**Bold** = what produced the committed film. The hosted and Kaggle paths are implemented but **were not exercised**: the build machine had no keys, no GPU, and the Kaggle account needs its owner's phone verification. See FAILURES.md.

## The live "change one shot" demo (for the walkthrough)

```bash
make film                                   # warm cache: finishes with "model calls this run: 0"
# edit storyboard.json: change the narration of s05, or the image_prompt of s07
make film                                   # exactly one new model call
tail -n 1 runs.jsonl | python -m json.tool  # the single new call: stage, item, model, seed, latency
```
Changing a narration line re-runs one TTS call; changing an image prompt re-runs one keyframe call. Downstream FFmpeg renders that depend on it are redone automatically (no model calls). See ARCHITECTURE.md → Caching.

## What it costs
Actual spend **$0**. Everything ran on an 8-core laptop CPU. Measured latency per stage and list-price equivalents are in **COSTS.md** (generated from `runs.jsonl` by `make costs`).

## Repository map
| Path | |
|---|---|
| `storyboard.json` | the contract: film, style block, characters, providers, music cues, 12 shots (each with a reason), end card |
| `schema/storyboard.schema.json` | JSON Schema, validated before every run |
| `pipeline/` | one module per stage + `run.py` orchestrator (see ARCHITECTURE.md) |
| `kaggle/` | GPU-side scripts for Wan 2.2 and ACE-Step |
| `runs.jsonl` | one line per model call |
| `outputs/` | references, keyframes, narration, music candidates, timeline, QC, final films |
| `DESIGN.md` | audience, intent, shot reasons, user tests |
| `ARCHITECTURE.md` | stages, contracts, caching, failure handling |
| `EXPERIMENTS.md` | hypothesis → change → result |
| `FAILURES.md` | what broke and what fixed it |
| `COSTS.md` | measured latency, CPU/GPU minutes, list price |
| `ETHICS.md` | consent, licences, labelling |

## Credits and licences
Story and direction: Kenean Biru. Images: SD-Turbo (Stability AI Community License). Narration: Meta MMS-TTS (CC-BY-NC 4.0). Score: see ETHICS.md. Because of the CC-BY-NC weights, **the film is non-commercial**. This project uses the universal romanizer software 'uroman' written by Ulf Hermjakob, USC Information Sciences Institute (2015-2020).
