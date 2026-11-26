# Interview prep: read this twice before the AI interview

**Be honest about how it was built.** A coding agent (Claude Code) wrote most of the code and ran the experiments overnight under your instructions. The brief explicitly expects "a coding agent writing most of the code under your direction". Say so plainly. What the interviewer checks is whether *you* understand the choices. Everything below is in the repo; reread `EXPERIMENTS.md` and `FAILURES.md` yourself.

## Why is the pipeline shaped like this?
* **One contract (`storyboard.json`)**, validated by JSON Schema + semantic checks before every run. Stages only read it. So `git diff storyboard.json` is the history of every creative decision.
* **Narration first** → the timeline is computed from voice durations (shot = max(min_duration, delay + voice + 0.9 s)). Picture is cut to the voice, as in professional editing.
* **Caching by content hash** with a sidecar `.cache.json` per output. Downstream keys include the *file hash* of upstream outputs, so invalidation is transitive and exact. Changing one narration line = 1 TTS call.
* **Provider chains** per stage (hosted → local → fallback). `ProviderUnavailable` (no key) falls through without retrying; real errors retry with exponential backoff, then fall through. Narration never mixes providers mid-film, because the voice would change.
* **Kaggle import contract with a stale guard:** GPU clips come back with a JSON sidecar recording the keyframe hash and motion prompt; a mismatch → Ken Burns fallback.

## Experiments to be able to walk through (pick E04 or E09 if asked for one)
* **E04:** MMS-Amharic vocabulary is 29 Latin symbols with no punctuation; `tok("qase, baqase.")` == `tok("qase baqase")`. Fix: split at `። ፣ ፦ ፤`, synthesise chunks, insert 0.25–0.55 s silences.
* **E09:** the first ducking test changed attack *and* release, giving "faster = shallower", which was nonsense. One variable at a time: attack 80 ms alone → 8.8 dB duck; release 800 ms alone → 4.8 dB. They cancelled. Chose attack 80 / release 1500.
* **E02:** Amharic narration ran at 1.2–1.5 words/s, not the 2–2.5 of the brief's English rule. Rate 0.85 → 96 s film (too long). Kept natural rate 1.0 and trimmed s01/s02 → 85 s.
* **E07/E08b, the metric misled me twice:** colour similarity rewarded copying the reference; speech-band energy picked a score with a steady 3–4 kHz tone. Both were caught by looking (grid, spectrogram).
* **F08:** CLIP's 77-token limit silently cut the style block off 6 of 12 prompts; now enforced before generation.
* **E13:** uroman maps Tigrinya `ዓ` and `ኣ` both to `aa`, so the pharyngeal contrast is lost before the model sees it. A front-end failure.

## Failures to be able to describe
* No GPU (F01) → CPU models + Kaggle scripts + Ken Burns fallback.
* 200 KB/s internet (F03) → fp16 weights, resumable downloader, priority order, procedural score so the film never blocks on a 2.4 GB download.
* The "free FLUX" endpoint served `sana` per EXIF and stamped a watermark (F05) → not used. Log the model the provider *says* it used.

## What your audience said (YOU must fill this in after the user tests)
* Test 1 (radio cut): ______ → changed ______ in storyboard.json (commit ______)
* Test 2 (near-final): ______ → changed ______

## Numbers to remember
Film 85.4 s · 12 shots · Amharic · −14.1 LUFS / −1.3 dBTP · ~1.4 words/s · MusicGen score seed 42 (E08b) · duck ~9 dB · keyframes 512 px, ~34 s each on CPU · full cold build 25 min, one-shot change ~3.5 min with 1 model call · 25 CPU-min total ≈ 3 T4-min ≈ $0.02 list price · $0 spent.
