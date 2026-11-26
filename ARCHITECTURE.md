# ARCHITECTURE.md

## One contract, eight stages

```
                         storyboard.json  ──validate──▶ schema/storyboard.schema.json
                               │                         + semantic checks (common.py)
         ┌─────────────────────┼───────────────────────────────────────────────┐
         ▼                     ▼                     ▼                         ▼
  [2] narration          [5] keyframes          [7] music                (read by all)
  one WAV per shot       refs first, then       N candidates (seeds),
  outputs/narration/     one PNG per shot       chosen seed → bed.wav
         │               outputs/references/    shaped by cue list
         ▼               outputs/keyframes/     outputs/music/
  [3] timeline                 │                     │
  shot length = max(min,       ▼                     │
  delay+voice+tail)       [6] shots                  │
  outputs/timeline.json   Wan import | Ken Burns     │
         │                per ratio: shots/16x9,     │
         ▼                shots/9x16                 │
  [4] radio cut                │                     │
  voice + temp drone           └──────────┬──────────┘
  on black (user test 1)                  ▼
                                   [8] assemble
                         duck (sidechaincompress) → 2-pass loudnorm −14 LUFS/−1 dBTP
                         → subtitles (safe area) → end card → film_16x9.mp4, film_9x16.mp4
                         → outputs/qc.json (measured duration + loudness of each export)
```

`make film` runs `python -m pipeline.run`, which calls the stages in this order. Each stage is also runnable alone (`python -m pipeline.keyframes --only s06`).

### Why this order (narration before pictures)
Professionals cut picture to the voice. The narration WAV durations decide every shot's length (`timeline.py`), so narration and the radio cut come first and are cheap. Keyframes, the expensive step on a GPU, come after the story and timing have been tested. Music is generated against the final timeline so cues land on shot boundaries.

## Contracts

| Stage | Reads from storyboard | Reads from upstream | Writes |
|---|---|---|---|
| validate | everything | `schema/`, `ETHICS.md` (consent refs) | nothing (fails fast with a list of errors) |
| narration | `film.language`, `shots[].narration`, `providers.narration` | — | `outputs/narration/sXX.wav` (48 kHz mono, trimmed, −18 LUFS per line) |
| timeline | `shots[].min_duration_s`, `narration_delay_s`, `end_card` | narration WAV durations | `outputs/timeline.json` |
| radio cut | `music.duck` | timeline, narration | `outputs/radio_cut/radio_cut.mp4` |
| keyframes | `characters`, `style`, `shots[].image_prompt/seed/characters`, `providers.keyframes` | reference images | `outputs/references/<char>.png`, `outputs/keyframes/sXX.png` |
| shots | `shots[].kenburns/motion_prompt`, `providers.shots` | keyframes, timeline, optional `outputs/clips_wan/` | `outputs/shots/<ratio>/sXX.mp4` |
| music | `music.caption/candidates/chosen/segment_s/cues`, `providers.music` | timeline | `outputs/music/candidate_seedN.wav`, `bed.wav` |
| assemble | `music.duck`, `end_card` | all of the above | `outputs/film_16x9.mp4`, `outputs/film_9x16.mp4`, `outputs/final/subtitles_en.srt`, `outputs/qc.json` |

Rules:
* **Stages never write to `storyboard.json`.** It is edited by a human (or the agent under review) only, so `git diff storyboard.json` is the complete history of creative decisions.
* **Prompts, seeds and providers live in the storyboard, not in code.** Tuning knobs that are not creative decisions (image size, steps, TTS rate) are env vars with defaults (`.env.example`) and are part of each cache key, so changing one invalidates exactly the outputs it affects.
* **Style block and character text are injected by code** (`common.expand_prompt`): a shot prompt says `{emama}` and gets the same character description every time. Drift from re-describing a character differently is impossible by construction. Enforced by a test.

## Caching: regenerate only what changed

Every artifact has a stable path and a sidecar `<file>.cache.json` holding `key = sha256(inputs)[:16]`:

| Artifact | Key inputs |
|---|---|
| reference image | reference prompt + style block, seed, provider chain, size, steps |
| keyframe | expanded prompt, seed, provider chain, size, steps, **hash of the reference image file**, ref strength |
| narration line | text, language, provider, voice settings |
| music candidate | caption, seed, length, provider chain |
| shot clip | **hash of keyframe file**, Ken Burns params, motion prompt, duration, ratio, Wan clip hash |
| music bed | hash of chosen candidate, total length, cues, shot start times |

Because downstream keys include **file hashes** of upstream outputs (not just their prompts), the cache is correct transitively: change a character description → its reference changes → every keyframe with that character changes → those shots re-render, and nothing else. Change one narration line → one TTS call. The timeline shifts, so the FFmpeg-only stages re-render the shots whose duration changed plus the mix. Zero extra model calls. The run ends with a summary line listing exactly which model calls happened, and `runs.jsonl` has one line per call, so the walkthrough's "only that shot regenerated" is visible in the logs.

`make clean-cache` drops only FFmpeg renders. `make clean-all` drops model outputs too.

## Failure handling

* **Provider chains.** Each stage has an ordered list in `storyboard.providers`, e.g. keyframes `["cloudflare:@cf/black-forest-labs/flux-1-schnell", "local:sd-turbo"]`. `common.run_chain` tries each in turn.
  * `ProviderUnavailable` (no API key, no Kaggle output, a stale Wan clip) is **not retried**. It is logged and falls through immediately.
  * Any other error (HTTP 5xx, 429 quota, timeout) is retried by `@retry` with exponential backoff (3–4 attempts), logged to `runs.jsonl` with `status: "error"`, then falls through to the next provider.
* **Narration is deliberately not mixed across providers.** The first available provider is chosen for the whole film, so a quota failure on line 7 cannot give line 7 a different voice. The stage stops instead, and the fix is one line in the chain.
* **Stale-import guard.** GPU work done on Kaggle (Wan 2.2 clips, ACE-Step tracks) comes back as files plus a JSON sidecar recording the keyframe hash / caption it was made from. The local stage accepts an import only if those still match the storyboard. Otherwise it falls back to Ken Burns or MusicGen and says why. The GPU latency in the sidecar is merged into `runs.jsonl`, so remote calls are logged too.
* **Validation before anything runs.** JSON Schema (types, ranges, 8–12 shots, 60–90 s target) plus semantic checks: unique ids, known characters, `{char}` placeholders declared, subtitle for every narration line, chosen music seed among candidates, **consent record present in ETHICS.md for any `real_person: true`**.
* **Prompt budget guard.** SD-Turbo reads at most 77 CLIP tokens, and anything longer is silently truncated (it was cutting off the style block, F08). `keyframes.check_prompt_lengths` fails the stage before any generation if a prompt is over budget.
* **Fallback upgrade.** The music cache key includes the best provider available *now*, so a fallback output (procedural score) is regenerated automatically once a better provider (MusicGen) becomes available, and only then (F07).
* **Length guard.** If the timeline falls outside 60–90 s, the run warns before rendering, and `outputs/qc.json` records the measured length and loudness of each export.
* **Fallback is a film.** With no keys and no GPU (the conditions this was built under) every stage still completes with local providers and Ken Burns motion.

## Secrets
Keys are read from environment / `.env` (git-ignored; template in `.env.example`). No key is ever written to logs: `runs.jsonl` records provider and model names only.

## Logging
* `runs.jsonl`: one JSON line per model call: `ts, run_id, stage, item, provider, model, params, seed, latency_s, device, compute_s, cost_usd, list_price_usd, status, cache_key, output, error` (+ prompt/caption, audio_s).
* `outputs/pipeline.log`: human-readable stage log incl. cache hits.
* `make costs` aggregates `runs.jsonl` into the table in COSTS.md.

## Files
```
pipeline/common.py     contract loading + validation, caching, retries, provider chains, ffmpeg helpers, logging
pipeline/narration.py  Gemini TTS | MMS-TTS (uroman romanisation for Ge'ez script)
pipeline/timeline.py   cut-to-voice edit list
pipeline/keyframes.py  reference sheet, keyframes; Cloudflare FLUX | SD-Turbo (txt2img / img2img on reference)
pipeline/shots.py      Wan 2.2 import | Ken Burns, per aspect ratio
pipeline/music.py      ACE-Step import | MusicGen; looping + cue envelope
pipeline/assemble.py   radio cut, ducking, loudnorm, subtitles, end card, exports, QC
pipeline/run.py        orchestrator (`make film`)
pipeline/smoke.py      phase-1 provider smoke test
pipeline/costs.py      runs.jsonl → COSTS.md table
pipeline/prices.py     every list-price assumption in one place
kaggle/*.py            GPU-side scripts for Wan 2.2 and ACE-Step (write the import contract)
tools/fetch_models.sh  resumable weight downloader (slow link)
tools/experiments/     scripts behind EXPERIMENTS.md
tests/                 contract, cache and subtitle tests (no models needed)
```

---
## v2 additions (recommended providers)

```
story/story.md ──[0] script (Gemini text: 3.8 Flash → 3.5 Flash-Lite)──▶ storyboard.draft.json
                     validated against the schema; errors sent back for ≤2 repair rounds
                     human reads/edits → `python -m pipeline.script accept` → storyboard.json
storyboard.json ──[2] narration: Gemini TTS, ONE request per film (batch split, E16) │ fallback MMS
                ──[5] keyframes: Cloudflare FLUX.2 klein-4b (reference image) / FLUX.1 schnell │ SD-Turbo
                ──[6] shots:  `python -m pipeline.remote wan` → private Kaggle kernel (T4 ×2) → clips_wan/
                ──[7] music:  `python -m pipeline.remote acestep` → private Kaggle kernel → music_acestep/
```

### Remote GPU runner (`pipeline/remote.py`)
Kaggle work is one local command. No notebook clicking, no manual downloads:
1. **Diff:** only shots whose clip is missing or stale (keyframe hash, motion prompt or size changed) are sent. With nothing changed, no GPU job is submitted at all.
2. **Package:** the storyboard + needed keyframes go into a **private** Kaggle dataset (`kaggle datasets create/version`).
3. **Run:** a **private** kernel is pushed with `--accelerator NvidiaTeslaT4` and a timeout. The job script installs its own dependencies, uses **both T4s** (one worker per GPU, alternate shots), and saves each clip with its JSON sidecar as soon as it finishes.
4. **Poll and pull:** status is polled every 30 s, outputs are downloaded, and the clips are copied to `outputs/clips_wan/`. Queue time and wall time go into `runs.jsonl` (stage `remote`). Per-clip GPU latency, dtype and peak VRAM go in via the shots stage's import.
5. **Fallback:** if the job fails or times out, the shots stage still finishes with Ken Burns, and the error and log tail are recorded.

### Quotas as a first-class constraint (`pipeline/quota.py`)
Free tiers are the binding constraint, so they are enforced in code before every hosted call:
* **Gemini:** a ledger per model per **US-Pacific quota day** (resets 11:00 EAT), with limits confirmed on the AI Studio dashboard (Flash TTS 10, Flash-Lite TTS 10, Flash 20, Flash-Lite 500/day). It counts the way the dashboard does (503 counts, 429 does not). **Experiments are refused** below a reserve kept for the film.
* **Cloudflare:** a neuron ledger per UTC day (10,000 free), with per-image cost computed from the published tile/step rates. Experiments are refused below `CF_NEURON_RESERVE`.
* `python -m pipeline.quota` prints both.

### Provider choice is data, not code
Everything that differs between films lives in `storyboard.json`: providers, voice/style (`voice`), per-shot `animate` (Wan or Ken Burns) and `ref_strength`, music caption/seeds/cues. A new film needs a new storyboard, not a code change.
