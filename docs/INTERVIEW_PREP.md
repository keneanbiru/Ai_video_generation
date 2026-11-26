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

---
## Submitted film: ሁሉም ለበጎ ነው (know these cold)
* **Pipeline:** storyboard.json → narration (Gemini 3.8 Flash-Lite TTS, voice Sulafat, ONE request for all 11 lines) → radio cut → FLUX.1 schnell keyframes (Cloudflare) → Wan 2.2 on Kaggle T4 (s01, s08) + Ken Burns → ACE-Step 1.5 score (seed 23 of 3) → FFmpeg assembly, 87.2 s, both ratios, −14.1 LUFS.
* **Hardest problem:** TTS quota 10/day. The batch split failed (gaps between lines no longer than pauses inside them) and the fallback spent the quota (F15). Rescued offline by DP alignment, verified 7/7 by rhythm correlation (E22).
* **Audience test 1:** positive; one "slightly slow". Kept: the voice is not slowed (2.06 words/s), the holds are deliberate.
* **Audience test 2:** mother looked different in s02/s03 → s03 reuses s02's image (push-in); king not riding in s04 → re-staged. Plus focus-point framing (the 16:9 crop had cut the mother's head at the eyes) (E28).
* **Wan:** 2 OOM failures → sequential offload fits in 2.25 GB; ~7–9 GPU-min per 2 s clip; 5 generated, 3 passed QC (ambient motion passes, physical actions hallucinate) (E27).
* **Practice that helped:** several candidates + evidence (score E26, Wan QC E27). **Practice that didn't work as stated:** the reference sheet couldn't condition FLUX (no seed or reference, F11); consistency came from explicit character text + reusing images.
* **Your personal input still needed:** mother's consent (ETHICS.md), testers' exact words (DESIGN.md §2–3), GitHub URL in the report.
