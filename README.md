# ሁሉም ለበጎ ነው: *Everything Is for the Good*. A heritage short made by a pipeline

An 87-second film in **Amharic** with English subtitles, based on the director's memory of failing an exam and the folktale the director's mother told: a king's fall, a servant thrown into a pit, and why *ሁሉም ለበጎ ነው*, everything is for the good.

The film is made by code. One file, **`storyboard.json`**, is the contract; each stage reads it and writes to `outputs/`. The stages are script (Gemini) → narration (Gemini TTS) → radio cut → reference sheet + keyframes (Cloudflare FLUX) → moving shots (Wan 2.2 on Kaggle, Ken Burns fallback) → score (ACE-Step 1.5 on Kaggle) → assembly (ducking, loudness, subtitles, dissolves, AI end card, 16:9 + 9:16).

```
make film
```

**Deliverables:** `outputs/cuts/final_9x16.mp4` and `outputs/cuts/final_16x9.mp4` (not committed: about 55 MB each; upload them for assignment 2). Report: `docs/REPORT.docx`. The development prototype (*ቀስ በቀስ*, local CPU models) and all its evidence are kept in `outputs/prototype_v1/`, `storyboards/` and the E01–E14 / F01–F08 entries.

## Who did what
* **Kenean Biru (director):** the story (a personal memory and the folktale the director's mother told), the audience and emotional intent, approval of the treatment and every narration line (and the revised Amharic wording), the choice of narrator and the student's appearance, both audience tests and the decisions taken from them (keep the reflective pace; fix the mother's consistency and the king's staging), account setup and credentials, and final review of the film.
* **Claude Code (coding agent, under the director's direction):** wrote the pipeline code, ran the experiments and logged them (EXPERIMENTS.md, FAILURES.md), drafted the storyboard and first Amharic narration (the Gemini text API was overloaded, F14), and assembled the film. As the brief expects, the agent wrote most of the code; the creative and audience decisions are the director's.

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

## v2: the recommended providers (Gemini, Cloudflare FLUX, Kaggle Wan 2.2 / ACE-Step)

v2 keeps every v1 stage and fallback and puts the brief's recommended models first in each chain. Setup:

| Provider | What you need | Where it goes |
|---|---|---|
| Gemini API (script, translation, narration) | key from https://aistudio.google.com/apikey | `GEMINI_API_KEY` in `.env` |
| Cloudflare Workers AI (FLUX keyframes) | account id + API token (Workers AI template) | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` in `.env` |
| Kaggle (Wan 2.2, ACE-Step on T4 ×2) | phone-verified account + API token | `~/.kaggle/access_token` (never in the repo) |

```bash
python -m pipeline.quota                                  # what each free tier has left today (no API calls)
python -m pipeline.script draft --story story/story.md    # Gemini -> storyboard.draft.json (validated)
python -m pipeline.script accept                          # after you have read and edited the draft
make radio                                                # narration (ONE Gemini TTS request) + radio cut
python -m pipeline.remote wan                             # Wan 2.2 clips for shots with "animate": true (private Kaggle job)
python -m pipeline.remote acestep                         # ACE-Step score candidates (private Kaggle job)
make film                                                 # assemble both aspect ratios
HERITAGE_OFFLINE=1 make film                              # no hosted calls at all: fallbacks + cache only
```

Free-tier limits the code enforces (confirmed 26 Nov 2026): Gemini Flash TTS 10/day, Flash-Lite TTS 10/day, Flash 20/day, Flash-Lite 500/day (reset 11:00 EAT); Cloudflare 10,000 neurons/day (reset 03:00 EAT); Kaggle ~30 GPU-h/week. Experiments are refused when they would cut into the film's reserve.

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
Story and direction: Kenean Biru. Submitted film: narration Gemini 3.8 Flash-Lite TTS; images FLUX.1 schnell (Cloudflare Workers AI); moving shots Wan 2.2 TI2V-5B; score ACE-Step 1.5; see ETHICS.md. The prototype used SD-Turbo, MMS-TTS and MusicGen (CC-BY-NC). This project uses the universal romanizer software 'uroman' written by Ulf Hermjakob, USC Information Sciences Institute (2015-2020).
