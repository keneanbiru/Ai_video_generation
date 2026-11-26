# EXPERIMENTS.md: hypothesis → change → result

Every number here comes from `outputs/experiments/<name>/results.json`, produced by `python -m tools.experiments.run <eNN>`. Every model call the experiments made is in `runs.jsonl` with `stage: "experiment"`. One variable changes at a time, with a fixed seed, unless stated otherwise.

**Limitation that applies to every audio decision below:** the agent that ran these cannot listen. Audio choices were made on measurements (duration, loudness, spectra, silence detection), and each says what a human listener still needs to confirm in user test 2.

---

### E01: Can MMS-TTS read Amharic script directly?
* **Hypothesis:** `facebook/mms-tts-amh` takes Ge'ez script as input.
* **Change:** compared the tokenizer's coverage of the raw narration with the same text romanised by `uroman`.
* **Result:** the model's vocabulary is **29 symbols: lowercase Latin letters, apostrophe, space, `_` and `<unk>`**. Raw Amharic: only **14–22 %** of characters are in vocabulary (only the spaces). After uroman: **91–98 %**. The remainder is punctuation (`, . : ?`), which is **not in the vocabulary at all**. `tokenizer.is_uroman == True`.
* **Decision:** always romanise (`narration.mms_prepare`). This led straight to E04.
* **Note for the native-speaker check:** uroman writes the sixth-order vowel as `e` everywhere (`ልጅነቴ` → `balejenatee`, `ቡናው` → `bunaawe`). The model was trained on the same romanisation, so this is expected, but it is the first place to listen for over-pronounced vowels.

### E02: Speaking rate vs. film length
* **Hypothesis:** at the default rate the 12 lines fit 60–90 s. The brief's rule of thumb is 2–2.5 words/s.
* **Change:** `speaking_rate` ∈ {0.85, 1.0, 1.1, 1.2}, same seed, full chunked narration path.

| rate | speech (s) | words/s | estimated film (s) | TTS CPU time (s) |
|---|---|---|---|---|
| 0.85 | 70.98 | 1.21 | **96.0** ✗ | 19.8 |
| 1.0 | 62.97 | 1.37 | 88.9 | 14.9 |
| 1.1 | 59.24 | 1.45 | 86.1 | 13.8 |
| 1.2 | 57.21 | 1.50 | 85.4 | 13.3 |

* **Result:** my first choice (0.85, "slow and warm") produced a **96 s** film, over the limit. Amharic runs at **1.2–1.5 words/s**, about half the English rule of thumb. Amharic words carry several morphemes each (`ያዘጋጃሉ` = "she prepares", `የሚጀምረው` = "that which begins"), so word budgets from English guides overshoot. Also, speeding up gives diminishing returns (0.85→1.0 saves 8 s, 1.1→1.2 saves 2 s), because the explicit pauses from E04 are fixed.
* **Decision:** keep the natural rate **1.0** and cut words instead of rushing the voice. s01 and s02 were trimmed (commit "Narration: chunked…"; `git log -p storyboard.json`). Result: **85.4 s**.

### E03: Is the TTS deterministic?
* **Hypothesis:** VITS has a stochastic duration predictor, so output depends on the seed. With `torch.manual_seed` fixed, it should be reproducible.
* **Change:** s06 rendered with seeds 7, 7, 8, 9, 10.
* **Result:** same seed → **byte-identical** WAV (sha256 equal). Different seeds → durations spread by **0.51 s** on one 6.5 s line.
* **Decision:** the seed is part of the narration cache key, and it is fixed (`MMS_SEED=7`) so a regenerated line cannot drift in timing and shift the whole edit.

### E04: Does Ethiopic punctuation create pauses?
* **Hypothesis:** mapping `።`→`.` and `፣`→`,` gives the model pause cues.
* **Change:** same lines with punctuation mapped vs. stripped. Then checked token ids directly.
* **Result:** `tok("qase, baqase.")` and `tok("qase baqase")` give **identical input ids**. Punctuation is silently dropped (consistent with E01's vocabulary). Measured pause patterns differed only by sampling noise (s08: 3 pauses / 1.38 s mapped vs 5 / 1.69 s stripped, in the "wrong" direction).
* **Change 2:** split each line at Ethiopic punctuation, synthesise the chunks separately, and insert explicit silence: `።`/`?` 0.55 s, `፦` 0.35 s, `፤` 0.30 s, `፣` 0.25 s (`narration.split_for_pauses`).
* **Decision:** adopted. The proverb now has a real beat: "…ይመልሳሉ፦ [0.35 s] ቀስ በቀስ፣ [0.25 s] እንቁላል በእግሩ ይሄዳል።" *Listener check needed: do the pauses sound natural or chopped?*

### E08: Choosing the score candidate (procedural fallback; the choice was superseded by E08b)
* **Hypothesis:** the least busy candidate sits best under narration: fewest onsets, least energy in the speech band (300–3400 Hz).
* **Change:** three seeds (7, 21, 42) of the same composer, measured after a first balancing fix (see note).

| seed | onsets/min | speech-band energy share | spectral centroid (Hz) | loudness range (dB) |
|---|---|---|---|---|
| 7 | 78.5 | 0.583 | 794 | 9.0 |
| **21** | 64.6 | **0.566** | **623** | 10.4 |
| 42 | **62.3** | 0.622 | 696 | 11.9 |

* **Result / decision:** **seed 21**. It has the least energy competing with the voice and the darkest timbre, with onsets close to the sparsest (42), whose higher speech-band share and wider loudness swings would fight the narrator. *Listener check: low volume, under the voice, on a phone.*
* **Note:** the first render (v1) had the flute phrase ~4× louder than the lyre (visible in a waveform plot), so peak normalisation left the lyre nearly silent. Rebalanced (lyre ×2.6, flute ×0.33) and bumped `procedural_score.VERSION` so the cache invalidated. **Without that version bump the "fix" would have silently reused the old audio**, a caching bug caught by looking at the output.
* **Provider note:** these are the procedural fallback, because MusicGen's 2.4 GB weights could not download in time (FAILURES.md F03). The same measurement code applies unchanged to MusicGen/ACE-Step candidates.

### E09: Ducking depth (sidechaincompress)
* **Hypothesis:** the brief's starting point (threshold 0.02, ratio 6, attack 300 ms, release 1500 ms) ducks the music clearly under the voice.
* **Measure:** music level (dB RMS) inside narration intervals vs. in the gaps, from `timeline.json`.

| setting | music during speech | music in gaps | duck depth |
|---|---|---|---|
| no ducking (bed −10 dB) | −34.6 | −35.2 | −0.6 |
| brief default (a300/r1500) | −44.0 | −36.8 | **7.2 dB** |
| attack 80 + release 800 (two changes) | −41.7 | −35.9 | 5.8 dB |
| **attack 80 only** | −46.0 | −37.2 | **8.8 dB** |
| release 800 only | −40.5 | −35.7 | 4.8 dB |
| hard (thr 0.01, ratio 12, a80) | −51.0 | −38.4 | 12.5 dB |

* **Result:** my first comparison changed attack and release together, and it suggested "faster = shallower", which made no sense. Re-running **one variable at a time** showed the truth: a faster attack alone **deepens** the duck (8.8 dB), because it catches word onsets. The shorter release alone **shallows** it (4.8 dB), because the music recovers inside the 0.25–0.55 s pauses between phrases. The two effects had cancelled out. "Hard" ducks most but also pulls the gaps down 3 dB (audible pumping).
* **Decision:** `attack_ms: 80`, `release_ms: 1500` in the storyboard. *Listener check: any audible "pumping" at phrase starts?*

### E10: Loudness normalisation, one pass vs two
* **Hypothesis:** two-pass `loudnorm` (measure, then apply with `linear=true`) lands on target more accurately than one pass.
* **Change:** the same mix pushed 6 dB quieter (−20.0 LUFS in), normalised both ways.
* **Result:** one-pass → **−13.8 LUFS**, −1.0 dBTP, LRA 6.5. Two-pass → **−14.0 LUFS**, −1.0 dBTP, LRA 6.8 (input LRA 6.8 preserved).
* **Decision:** two-pass in `assemble.mix`. It is exact, and linear mode keeps the dynamics instead of compressing them (LRA 6.5 vs 6.8). The difference is small but free.

### E13 (ceiling): Does the same pipeline work for Tigrinya and Afaan Oromo?
* **Hypothesis:** MMS-TTS has models for Tigrinya (`tir`) and Afaan Oromo (`orm`). Swapping `film.language` should be all it takes.
* **Change:** three narration lines (s01, s06 the proverb, s12) translated by the agent into Tigrinya and Afaan Oromo. **The translations are not native-checked; that check is part of the open result.** Rendered with each language's MMS model, seed 7. Measured tokenizer coverage, speech rate, and how uroman romanises letters that only Tigrinya uses.

| lang | script → model input | chars dropped | words/s (s01 / s06 / s12) |
|---|---|---|---|
| amh | Ge'ez → uroman | none | 1.82 / 1.43 / 1.51 |
| tir | Ge'ez → uroman | none | 1.97 / 1.77 / 1.71 |
| orm | Latin (Qubee), **no uroman** (`is_uroman=False`) | none | 2.12 / 1.82 / 1.84 |

* **Results:**
  1. **uroman has no language-specific rules for these codes.** `romanize_string("ቐ ቑ ኸ ዀ ዓ ኣ ቍ ቋ", lcode=…)` gives exactly the same string for `amh`, `tir` and no code: `qha qhu kxa kxwa aa aa qwe qwaa`.
  2. **The Tigrinya pharyngeal is lost.** `ዓ` (ʿayn, a pharyngeal consonant Tigrinya keeps distinct) and `ኣ` (glottal a) both become `aa`. So `ዓባየይ` (my grandmother) reaches the model as `aabaayaye`, the same as if it began with `ኣ`. The model cannot pronounce a contrast its input does not contain. This is a **front-end failure, not a model failure**, and no amount of prompt or voice tuning fixes it.
  3. Tigrinya-specific letters that *are* kept distinct: `ቐ`→`qh`, `ኸ`→`kx`, `ቍ`→`qwe`. Those contrasts survive.
  4. Afaan Oromo needs no romanisation. The vocabulary keeps `'` (hudhaa, the glottal stop) and the Qubee digraphs are plain Latin letters, so the model sees the text as written. It also spoke fastest (≈1.8–2.1 words/s, closer to the English rule of thumb, because Qubee words map to sounds almost one-to-one).
* **What this means for the film:** a Tigrinya version is one storyboard field (`"language": "tir"`) plus translated lines, but **expect `ዓ`/`ሐ`-heavy words to sound wrong**. The audio is in `outputs/experiments/e13_languages/*.wav` for a native speaker to judge. The fix to try next is a custom pre-romanisation that maps `ዓ`-series letters to a distinct symbol, if the model's training data used one (unknown; needs the MMS training romaniser).

### E05: Keyframe size and steps (SD-Turbo on CPU)
* **Hypothesis:** a larger render (640–768 px) gives more detail for the Ken Burns zoom. 4 steps beats 1.
* **Change:** shot s04 (the roast), seed 104, at 512/640/768 px and 1/4 steps.

| size, steps | CPU latency (s) | what it looks like |
|---|---|---|
| 512, 1 | 19.8 | coherent, softer |
| **512, 4** | **29.4** | **one pan, painterly texture, a hand entering frame** |
| 640, 1 | 26.4 | composition starts to repeat |
| 640, 4 | 42.6 | two overlapping pans |
| 768, 4 | 66.6 | three or more pans tiled across the frame |

* **Result:** bigger is **worse**, not better. SD-Turbo was distilled at 512 px. Above that it fills the extra canvas by **repeating the subject** (the classic "duplication" failure of diffusion models off their training resolution), and it costs 1.4–2.3× more CPU time.
* **Decision:** `KEYFRAME_SIZE=512`, 4 steps. Detail for 720p output comes from Lanczos upscaling inside the Ken Burns stage, which suits a painted look. I had defaulted to 640 in the code before testing; the measurement reversed that choice.

### E07: Keeping Emama the same person (reference conditioning)
* **Hypothesis:** img2img from the golden reference (`outputs/references/emama.png`) keeps her identity across s02, s06 and s09. Higher similarity to the reference = better.
* **Change:** for each shot: txt2img (style block + identical character text only), or img2img on the reference at strength 0.6 / 0.8 / 0.9, same seed. Metric: HSV colour-histogram intersection with the reference. Then I looked at the 3×3 grid.

| shot | txt2img | img2img 0.6 | img2img 0.8 | img2img 0.9 |
|---|---|---|---|---|
| s02 (medium, working) | 0.47 | 0.75 | 0.67 | 0.67 |
| s06 (close-up, the proverb) | 0.64 | **0.75** | 0.58 | 0.58 |
| s09 (wide, neighbours) | 0.41 | 0.68 | 0.47 | 0.47 |

* **Result 1, the metric lied.** img2img 0.6 scored highest everywhere because it **copied the reference portrait**: s02 ("spreading grass") and s09 ("wide room of neighbours") both came out as the same head-and-shoulders portrait. The colour metric rewarded the exact failure I needed to avoid. Prompt adherence is invisible to it.
* **Result 2, a hidden step quantisation.** 0.8 and 0.9 are **pixel-identical**: with 4 steps diffusers runs `int(4 × strength)` = 3 denoising steps for both. With 4-step distilled models only strengths 0.5 / 0.75 / 1.0 actually differ.
* **Result 3, a trade-off by shot size.** txt2img follows the composition (s02 shows her working, s09 shows the room) but her face changes. img2img keeps the face but pulls every shot toward a portrait.
* **Decision:** a per-shot `ref_strength` field in the contract. **s06** (the close-up where her face carries the film) uses the reference at 0.8. **s02, s09** (her face is small, composition matters) use txt2img with the identical character text. The child and adult (seen from behind / in silhouette) use txt2img. *User test 2 asks whether she reads as one person.*
* **Next step:** a LoRA trained on 10–20 curated reference images would decouple identity from composition. That needs a GPU (see report → what I would build next).

### E08b: Re-choosing the score once MusicGen arrived (supersedes E08's choice)
* **Hypothesis:** the E08 rule (pick the lowest speech-band energy share) still picks the best candidate for MusicGen output.
* **Change:** same caption, same seeds (7, 21, 42), now rendered by MusicGen-small. Same metrics, then spectrograms (0–12 kHz) of all three.

| seed | onsets/min | flatness | centroid (Hz) | speech-band share | loudness range (dB) |
|---|---|---|---|---|---|
| 7 | 81.0 | 0.076 | 1726 | 0.786 | **44.5** |
| 21 | 120.3 | 0.034 | **2660** | **0.180** | 14.3 |
| **42** | 118.0 | **0.018** | 764 | 0.701 | 22.0 |

* **Result:** the rule would have picked **seed 21**, and the spectrogram shows why that is wrong: a **sustained tone around 3–4 kHz** plus a broadband noise floor. 3–4 kHz is where consonants carry intelligibility, so a steady tone there masks the narrator all film long. "Speech-band share" scored it well only because most of its energy sits *above* 3.4 kHz. Seed 7 has dark gaps where the music drops out mid-track (the 44.5 dB loudness range). **Seed 42** is the most tonal (lowest flatness), with clear note events below 1.5 kHz and a clean 2–4 kHz band. Ducking handles low-mid overlap well; it does not fix a constant tone in the consonant band.
* **Decision:** `music.chosen = 42` with this reason in the storyboard. The metric design is fixed in hindsight: intelligibility is about **2–4 kHz specifically**, not 300–3400 Hz overall. *Listener check in user test 2.*
* **Meta-lesson (twice now, see E07):** an automatic score picked the failure case. Every automatic choice in this project is now confirmed by looking at the output.

### E10b: True peak after AAC encoding
* **Observation:** the mixed WAV measured −1.0 dBTP, but the encoded MP4 measured **−0.8 dBTP**, over the −1 dBTP ceiling. AAC's lossy encoding adds inter-sample overshoot.
* **Change:** loudnorm true-peak target −1.0 → **−1.5** in `assemble.py` (integrated target unchanged).
* **Result:** both exports now measure **−14.1 LUFS, −1.3 dBTP** (`outputs/qc.json`). The QC step that measures the *final file*, not the intermediate WAV, is what caught this.

### E11: Hosted (keyless) vs local images, same prompts and seeds
* **Change:** s04, s06, s08 at 640 px through `image.pollinations.ai` (`model=flux`) and through local SD-Turbo.

| shot | hosted latency | hosted model reported (EXIF) | local SD-Turbo latency |
|---|---|---|---|
| s04 | 7.3 s | `sana` | 81.8 s |
| s06 | 6.2 s | `sana` | 66.0 s |
| s08 | **503 error** | — | 75.4 s |

* **Result:** hosted is about **10× faster**, but (1) it reported `sana`, not the FLUX requested; (2) it failed 1 of 3 calls; (3) it carries a watermark; (4) for s06 it ignored the character text ("an old Ethiopian grandmother with a kind wrinkled face…") and drew a **younger, lighter-skinned woman**, and it ignored the gouache style block. Local SD-Turbo kept the character. (Local latencies here are at 640 px and with CPU contention; production is 512 px, ~34 s.)
* **Decision:** local for the film. Speed does not help if the identity of the main character and the reproducibility of the run are lost.

### E12: Ken Burns jitter, with and without a 3× pre-upscale
* **Hypothesis:** FFmpeg's `zoompan` rounds the crop window to whole pixels, which makes slow zooms on a small image jitter. Upscaling first reduces it.
* **Change:** s06, 96 frames, zoom 1.0→1.18, rendered from the 512 px keyframe with no upscale vs 3× Lanczos upscale before `zoompan`. Measured the mean absolute difference between consecutive frames (centre crop), and its coefficient of variation (CV; a smooth zoom has evenly sized steps).
* **Result:** no upscale: mean diff 2.63, **CV 0.271**. 3× upscale: mean diff 1.13, **CV 0.136**. Steps are half as uneven, and the extra render cost is 0.3 s per shot.
* **Decision:** keep the 3× upscale in `shots.kenburns`.

### E14: Fixing the final shot (s12) within three attempts
* **Problem:** the closing image ("a single small white cup of coffee steaming on a windowsill…") came out as a **tall wooden cylinder** (seed 112). Attempt 2 (a reworded prompt, same seed) gave the same cylinder.
* **Change (attempt 3):** a concrete close-up prompt ("close-up of a tiny white porcelain coffee cup without a handle, full of black coffee with steam…"), 4 seeds explored (`outputs/experiments/e14_s12_seeds/`).
* **Result:** all 4 seeds gave a recognisable cup. Seed 312 had steam, the sill, city rooftops and hills beyond, which matches the intent. But **"without a handle" produced a handle in 4 of 4 seeds**. SD-Turbo runs at guidance 0, so it ignores negative prompts, and a negated word in the positive prompt still pulls the concept in.
* **Decision:** s12 = seed 312. Regenerating through the pipeline reproduced the explored image **byte-for-byte** (`cmp` identical), which confirms the seed + prompt + settings in the storyboard fully determine the keyframe. The brief's "three attempts per shot, then fall back" rule held: attempt 3 worked.

---
## v2 experiments (recommended providers)

### E15: Gemini 3.8 Flash TTS vs MMS-TTS on the development lines
* **Hypothesis:** Gemini TTS (the brief's recommended narrator) handles Amharic in Ge'ez script directly, including the punctuation pauses that MMS needed a workaround for (E04).
* **Change:** the 12 v1 narration lines (development material only, not the new film), Gemini `gemini-3.8-flash-tts`, voice Sulafat, style "calm, warm, unhurried; an adult remembering their grandmother", sent as plain Ge'ez text (no romanisation, no chunking). Compared with the MMS lines already in v1.

| | Gemini 3.8 Flash TTS | MMS-TTS amh (with E04 chunking) |
|---|---|---|
| input | Ge'ez script as written | uroman romanisation + split at punctuation |
| silences ≥ 0.15 s, across 30 punctuation marks | **30** | 29 (only because of the E04 workaround) |
| speech, 12 lines | 61.3 s | 57.6 s |
| words / s | 1.34 | 1.42 |
| latency / line | median 6.2 s (4.5–21.3 s; the high values are rate-limit waits) | ~1.1 s on CPU |
| determinism | not established (the repeat call hit the daily quota) | byte-identical with a fixed seed (E03) |

* **Result:** Gemini pauses at Ethiopic punctuation **natively**, one pause per mark. Pacing is almost the same as MMS. Pronunciation and naturalness cannot be judged by the agent: **blind A/B pairs** are in `outputs/experiments/e15_gemini_vs_mms/blind_ab/` (5 lines, X/Y order randomised, key in a separate file) for a native listener.
* **Quota found:** `gemini-3.8-flash-tts` free tier = **3 requests/minute and 10 requests/day** (from the 429 message; the docs' rate-limit page has no free-tier numbers). 13 calls succeeded before the daily block. `gemini-3.8-flash-lite-tts` has a **separate** quota and also speaks Amharic (one test call, 7.3 s).

### E16: One Gemini request per film (batch narration)
* **Hypothesis:** with 10 requests/day and 8–12 lines per film, per-line TTS makes retakes impossible. One request containing all lines, split at the longest silences, gives the same per-line audio.
* **Change:** s01–s05 in one request (`gemini-3.8-flash-lite-tts`), style plus "leave about two seconds of silence between paragraphs". Split at the 4 longest silent runs (> 0.35 s). Validate each piece: (its share of audio) / (its share of characters) must lie in 0.35–2.8, otherwise fall back to per-line calls.
* **Result:** one 23.8 s take split into 5 pieces with ratios **1.00, 1.14, 1.07, 1.03, 0.84**. Piece lengths match the same lines made by separate calls in E15 (s01 5.26 vs 5.29 s, s02 4.18 vs 3.95, s03 4.52 vs 4.27, s04 4.97 vs 4.59, s05 4.89 vs 5.72).
* **Decision:** `narration` uses one batch request whenever ≥ 3 lines need (re)generating, and per-line requests for 1–2 changed lines. That keeps selective regeneration at one request per changed line. A whole film is 1 request, so the free tier allows ~10 full takes a day.

### E17: Cloudflare FLUX.1 schnell and FLUX.2 klein-4b vs local SD-Turbo (keyframes)
* **Setup:** authentication verified (`/user/tokens/verify`: active). The model search API lists `flux-1-schnell`, `flux-2-klein-4b`, `flux-2-klein-9b` and `flux-2-dev` on this account. Development prompts only (v1 s02/s06, v1 reference image). Neuron cost from the published rates, logged per call. **Spent: 9 calls, 314 neurons of 10,000** (ledger: `python -m pipeline.quota`).
* **Measured:**

| model | size | latency (s) | neurons | seed | notes |
|---|---|---|---|---|---|
| FLUX.1 schnell | 1024 | 3.98, 3.95 | 57.6 | **rejected**: 400 "Additional … properties '/seed' … not allowed" | runs differ (mean pixel diff 86.6/255) |
| FLUX.2 klein-4b | 512 | 11.8, 8.9, 12.5, 27.3 (text-only) | 26.05 | accepted, but **not deterministic** (same call twice: pixel diff 44.6) | `width`/`height` honoured |
| FLUX.2 klein-4b + reference | 512 | 5.9, 9.8 | 47.53 | — | **no measurable effect** (see below) |
| SD-Turbo (local CPU, v1) | 512 | ~34 | 0 | deterministic, byte-identical | — |

* **Results:**
  1. **Quality and prompt adherence: FLUX is clearly better** than SD-Turbo on the same prompts. Stool, jebena, grass spread on the floor and window light all appear as described. Schnell at 1024 px is ~8× faster than SD-Turbo at 512 px on this CPU.
  2. **Reproducibility is lost.** Schnell rejects `seed` (the docs' curl example sends one); klein accepts it but repeated calls still differ. Hosted keyframes can be *reproduced* only from the cache. That is why the stored PNG and its sidecar, not the seed, are the source of truth for a FLUX keyframe.
  3. **Reference conditioning could not be verified.** The klein page and its schema list only an untyped `multipart` body. A research pass over the docs, changelog and blog found no field names. Two guesses (`input_image_0`, `input_image`) produced outputs whose difference from no-reference (39.7) was **smaller than klein's own run-to-run noise (44.6)**. Timeboxed: not used for the film, not claimed as working.
  4. **Representation:** both FLUX models drew the grandmother with **noticeably lighter skin** than the reference. Cause: F08's prompt compression had dropped "dark brown skin" from her description. SD-Turbo still drew dark skin from "Ethiopian"; FLUX did not. Restoring the words helped only partly. **Rule for the new storyboard: state skin tone and other identity traits explicitly in every character description**, and check every keyframe by eye (as in E11).
* **Decision:** keyframe chain = **`cloudflare:flux-1-schnell` (1024 px, ~58 neurons) → `local:sd-turbo`**. Schnell over klein: faster, follows the prompt as well, and klein's only extra (references) is unverified. A full film (3 references + 12 shots + ~12 retakes) ≈ 27 × 58 ≈ **1,560 neurons**, well inside the free 10,000 left today.

### E18: What a free Kaggle GPU session really is (probe job)
* **Purpose:** before spending GPU hours on Wan, measure the hardware, the software, and the precision question the model card left open (Wan's examples use bf16; the T4 has no bf16 tensor cores).
* **Method:** private script kernel `heritage-gpu-probe`, `--accelerator NvidiaTeslaT4`: `nvidia-smi`, torch/CUDA versions, 20× 4096² matmul per dtype, `pip install git+…/diffusers`, introspection of the Wan pipelines. Output: `outputs/remote/results/probe/probe.json`.
* **Measured:** **2× Tesla T4, 15,360 MiB each**, compute capability 7.5, driver 580, torch 2.11.0+cu130. **Queue wait 23 min** (submitted 11:59, running ~12:22 EAT). diffusers main (0.44.0.dev0) installs in 19 s. `WanImageToVideoPipeline.__call__` takes `image, prompt, …, guidance_scale_2`.

| dtype | 4096² matmul (ms) |
|---|---|
| **fp16** | **14.5** |
| fp32 | 31.6 |
| bf16 | 53.4 (reported "supported" but emulated) |

* **Decision:** Wan runs in **fp16** on T4. bf16 would be ~3.7× slower than fp16 (slower even than fp32). Because fp16 can overflow where bf16 would not, the job checks every clip for NaN/black frames and redoes a bad shot in bf16. Both GPUs are used (one worker per GPU). Queue time is now logged per job (`stage: remote`, `queue_s`): on the free tier it is a real share of the wall-clock budget.

### E19: ACE-Step 1.5 on a Kaggle T4 vs MusicGen-small on the laptop CPU
* **Setup:** same caption and seeds as v1 (7, 21, 42), 26 s instrumental, `acestep-v15-turbo` DiT + `acestep-5Hz-lm-1.7B` planner, PyTorch backend, one T4. Launched by `python -m pipeline.remote acestep` (private kernel; second attempt, after F12).
* **Measured (from the job's own `time_costs`):**

| | ACE-Step 1.5 (T4) | MusicGen-small (CPU, v1) |
|---|---|---|
| time per 26 s candidate | **27.1–31.5 s** | 183–243 s |
| of which LM planner ("thinking") | **25.6 s (88 %)** | — |
| of which DiT diffusion + VAE decode | 3.5 s | — |
| one-off setup per job | `uv sync` 112 s + checkpoints 53 s + model load 120 s | — |
| whole job incl. queue (55 s) | 390 s for 3 candidates | ~12 min for 3 |
| licence of outputs | **MIT, commercial use allowed** | CC-BY-NC weights (film non-commercial) |

* **Spectral comparison (E08 metrics):** ACE-Step seed 7 had the lowest speech-band share of any candidate in this project (0.43) at a tonal, low-centred spectrum (flatness 0.019, centroid 897 Hz). No candidate showed a sustained tone in the 2–4 kHz consonant band (MusicGen seed 21's problem in E08b).
* **Found by looking at the spectrograms:** every ACE-Step track ends with **1.6–2.3 s of silence**. Looping it for the bed would make the score drop out every ~24 s. **Fix:** the import trims trailing silence before normalising (24.4 / 24.2 / 23.7 s left).
* **Decision:** ACE-Step is the film's music provider (first in the chain; MusicGen and the procedural score remain as fallbacks). The 88 % planner share suggests a next experiment: `thinking=False` (DiT-only) could cut a candidate to ~4 s, at an unknown cost in musical structure.

### E20: Wan 2.2 TI2V-5B on Kaggle T4s, first attempt: out of memory twice
* **Config:** 2 shots (v1 s04, s08), 640×640, 81 frames, 30 steps, `WanImageToVideoPipeline` fp16, `enable_model_cpu_offload()`, **two worker processes** (one per T4).
* **Measured:** dependencies 26 s, weights download 154 s. GPU 1: **CUDA OOM in fp16** (14.54 GiB in use) **and in bf16** ("tried to allocate 6.31 GiB": the fp32 VAE decoding all frames at once). GPU 0 worker: **killed by the OS (exit −9)**: two processes each holding the 5B transformer + UMT5 text encoder in host RAM for offloading exceeded the machine's RAM. Kaggle job 756 s, **0 clips**.
* **Fixes for attempt 2:** one worker process; `vae.enable_tiling()`; smaller first proof (512×512, 49 frames, 20 steps, 1 shot). Result: see E21.
* **Lesson:** "fits on a 24 GB GPU with offload" in the model card does not transfer to 15 GB T4s by turning on offload alone. The decode step, not the transformer, was the peak.

### E21: Wan 2.2 TI2V-5B, attempt 2: still out of GPU memory at the smallest test size
* **Config:** 1 shot (v1 s04), **512×512, 49 frames, 20 steps**, one worker, `enable_model_cpu_offload()` + `vae.enable_tiling()`, fp16 then bf16.
* **Measured:** queue **1,108 s** (18.5 min), deps 25 s, weights 155 s. fp16: **OOM with 14.38 GiB allocated by PyTorch** (asked for 108 MiB more). bf16: OOM asking for 1,014 MiB with 13.60 GiB allocated. Job 547 s, **0 clips**.
* **Interpretation:** the peak is no longer the VAE decode (tiling was on). With model-level offload, the module resident during denoising, the 5B transformer at 16-bit (≈10 GB of weights) plus its activations, does not leave room on a 15 GB T4. The model card's "24 GB with offload" figure is the honest floor for this offload mode.
* **Decision (timeboxed per the brief's advice):** the film uses **Ken Burns** (verified, E12) unless a final background attempt with `enable_sequential_cpu_offload()` (layer-by-layer, minimal VRAM, much slower) produces a usable clip in time. Total Wan cost so far: 2 jobs, ~22 GPU-min, ~41 min including queues, 0 clips.

### E21b: Wan 2.2 TI2V-5B, attempt 3: the first real clip, via sequential offload
* **Config:** v1 s04 keyframe, 512×512, 49 frames (2.0 s at 24 fps), 20 steps, fp16, `enable_sequential_cpu_offload()` (layer by layer), one worker.
* **Measured:** queue 1,116 s, weights 155 s, **generation 524 s** for 2 s of video, **peak VRAM 2.25 GB** (vs > 14.4 GB OOM with model-level offload), no NaN/black frames (mean 0.43).
* **Quality (frames 0/16/32/48 inspected):** first ~1 s clean, with gentle motion. From ~frame 30 a **blue, hand-like smear morphs into the frame**, a hallucination the prompt ("smoke curls upward, beans shift slightly") did not ask for, on a 512 px SD-Turbo keyframe.
* **Decision for the film:** Wan *is* usable on free T4s, but at ~8.7 GPU-min per 2-second clip, and every clip needs a frame-level QC before use. Plan: only the 5 shots marked `animate` (s01, s04, s05, s08, s10); FLUX keyframes; motion prompts limited to one gentle movement; two parallel Kaggle jobs (separate VMs, to avoid the host-RAM kill of E20); keep the clean part of each clip; any clip that morphs falls back to Ken Burns.
* **Wan totals so far:** 3 jobs, ~31 GPU-min, ~1 h 50 min wall clock including 41 min of queueing, **1 clip**.

### E22: Recovering the narration from one take when the automatic split failed
* **What happened:** the film's 11 lines went to Gemini Flash-Lite TTS in **one** request (E16 design). The take came back fine (65.1 s), but the model left only 0.4–1.0 s between lines (asked for ~2 s), the same as pauses *inside* lines. "Cut at the N−1 longest pauses" produced implausible pieces (length/text ratios 0.14–2.8), and the fallback then spent the rest of the day's quota on per-line calls (FAILURES F15).
* **Offline recovery (no API calls):** dynamic-programming alignment that picks 10 of the take's 29 pauses so each piece's length best fits its expected share (from 7 per-line takes, scaled to the batch pace, plus character counts for the rest), with a small bonus for longer pauses. Every chosen cut sits on a 0.65–1.05 s pause; batch/per-line length ratio is steady (0.72–1.0).
* **Independent verification:** the energy envelope (syllable rhythm) of each recovered piece correlated best with its **own** per-line recording **in 7 of 7 lines** (mean 0.31 vs 0.06 with other lines).
* **Decision:** the film uses the single continuous take for all 11 lines (one consistent performance); the 7 per-line takes are kept in `outputs/narration/per_line_takes/`. The alignment is now the production splitter (`narration.align_cuts`), covered by a regression test that reproduces this exact failure.
* **Measured narration:** 56.7 s of speech for 117 Amharic words (**2.06 words/s** in the single take, faster than per-line delivery at ~1.5 w/s). Film length with the director's full wording: **79.7 s**, so no compression was needed. Holds were lengthened on the transition and emotional beats → **87.2 s** radio cut.

### E23: Hiding the end of a short Wan clip inside a long shot
* **Problem:** a Wan clip gives ~2 s of usable motion (E21b), but shots last 5–10 s. Slowing the clip by up to 1.5× and then holding the last frame left ~3.5 s of frozen picture in a 6 s shot.
* **Change:** the import now scales the clip to 2× the output size, holds the last frame, and runs one slow `zoompan` across the **whole** shot (the shot's own Ken Burns zoom range, at least +6 %), so the camera keeps moving after the AI motion ends.
* **Measured** (v1 s04 clip, 6 s, 9:16): mean frame-to-frame change 12.6 during the AI-motion part, 3.0 during the held part, **0 frozen frames**; 2.3 s to render per ratio. Both 16:9 and 9:16 rendered to exactly 6.00 s.
* **Also changed for the film run:** `pipeline.remote wan` now defaults to 512 px / 49 frames / 25 steps / sequential offload, and splits shots over **2 parallel Kaggle kernels** (separate machines). It logs the real outcome (`wan:clips`, clips delivered vs requested), because a kernel that "completes" is not a delivered clip. The three earlier Wan jobs were back-filled as 0/2, 0/1 and 1/1.

---
## Film production (ሁሉም ለበጎ ነው)

### E24: Keyframes for the film: FLUX.1 schnell, reviewed by eye, retaken selectively
* **Run:** 4 character references + 12 keyframes, `flux-1-schnell` 1024 px, ~3 s each (log: 15:10:51–15:11:35). Then two rounds of selective retakes: 4 images, then 2. Every round regenerated **only** the shots whose prompt or seed changed; the rest came from cache. Cloudflare usage for the whole film: **1,582 of 10,000** neurons, including the 314 spent on E17 earlier the same UTC day.
* **Review checklist per image:** identity (skin tone, hair, clothing), cultural accuracy, emotion vs. the shot's `reason`, letterbox, hands.

| shot | problem found | change | result |
|---|---|---|---|
| ref:king | FLUX added black letterbox bars ("cinematic film still") | kept: the reference is used only for QC and the SD-Turbo fallback | noted |
| s02 | the "jebena" was a **metal moka pot** | describe it: round black clay pot, long narrow neck, straw stopper, small white cups | ✅ correct jebena |
| s03 | mother looked **alarmed**, wrong for the bridge into memory | "soft nostalgic half-smile, eyes looking gently away as if remembering" | ✅ |
| s09 | eyes read slightly comic → then a **large crown** (identity break) | reroll, then "thin simple gold circlet (no large crown)" | ✅ consistent circlet |
| s10 | the king and servant **merged into one figure** at the pit | redesigned as a close-up of **two hands clasping over the pit** | first try: **light-skinned hands** → stated "dark brown-skinned Ethiopian hands" → ✅ |

* **Findings:** (1) Representation drift appears whenever a body part is named without its skin tone, the same lesson as E17, now three times. Every prompt that shows people now states skin tone. (2) Two-person physical interaction is the weakest case for a 4-step model; a symbolic close-up is both more reliable and more cinematic. (3) Consistency held through explicit, fixed character text alone: the king keeps beard, cape and circlet across s05/s08/s09/s11, and the servant keeps shaved head and gabi across s06/s07/s11, with no reference conditioning (which is unverified for klein, F11).

### E25: A dissolve from the mother's face into the folktale
* **Goal (director's brief):** a cinematic, emotional transition between the personal memory and the folktale.
* **Change:** per-shot `transition_in: dissolve` + `transition_s` in the contract. The outgoing clip is rendered longer by the dissolve, and the two overlap by exactly that much (`xfade`), so **total length and narration sync are unchanged**. Set: s03 (0.8 s, into the mother's remembering face), **s04 (1.5 s, mother's face → the king's horse on the highland road)**, s12 (1.5 s, back to the present).
* **Failures on the way:** `xfade` rejected mixed timebases, then a variable frame rate after `concat`, then `settb` placed after `fps` (it resets the rate). Fix: normalise every input (`settb=AVTB,setpts,fps=24,format`) and re-apply `settb,fps` after every join.
* **Measured:** both ratios join to **87.208 s = timeline 87.208 s** exactly. The mid-dissolve frame at 20.9 s (9:16) shows the mother's eyes over the horse on the road, which is the intended image.

### E26: Three full-length ACE-Step scores, judged against the story's emotional arc
* **Run:** 3 seeds (11, 23, 47), one **88 s** instrumental track each (one evolving piece instead of a looped 26 s clip). Caption: Ethiopian-inspired, krar/masinko/washint/kebero, minor tizita mode, "begins sparse and sad, builds slow suspense with low drums, then resolves into a warm hopeful theme". Kaggle: queue 485 s, `uv sync` 122 s, checkpoints 38 s, model load 110 s, **69.8–71.3 s per candidate**, job 1,023 s.
* **Method:** each track was measured over the film's actual story phases (from `timeline.json`): RMS level, spectral centroid (brightness), and low-end (< 150 Hz, drums/drone) share. Then I looked at the spectrograms.

| phase (film time) | seed 11 | **seed 23** | seed 47 |
|---|---|---|---|
| sadness (0–17 s) | −23.8 dB, 1,892 Hz | **−23.3 dB, 1,024 Hz** | −23.0 dB, 989 Hz |
| transition | −19.9, 1,882 | −22.8, 1,653 | −25.1, 1,170 |
| tension (fall → capture) | −19.1, 2,427, low 0.65 | **−22.2, 1,067, low 0.40** | −21.1, 1,327 |
| surprise | −19.2, 2,805 | **−19.6 (peak), 1,726** | −26.2, 1,287 |
| realisation + comfort | −19.8, 2,721, low 0.76 | **−23.5, 1,877** | −26.1, 1,347 |

* **Result:** seed 11 never comes down (loud, bright, bass-heavy to the end: no comfort). Seed 47 resolves dark and quiet (no hope). **Seed 23 matches the arc:** dark and quiet for the sadness, drums entering for the tension, its loudest moment exactly at the surprise, then quieter *and brighter* for the comfort ending. Its spectrogram shows a distinct calm final section. Chosen.
* **Fit problem found:** after trimming ACE-Step's trailing silence (E19) the tracks are 80–84 s, but the film is 87.2 s. The bed logic would have **looped** the track, restarting the sad intro under the hopeful ending. **Fix:** a candidate ≥ 85 % of the film length is tempo-stretched to fit (`atempo`, pitch preserved; seed 23: ×0.94) instead of looped.
* **Licence:** ACE-Step outputs may be used commercially (MIT). With Gemini narration and FLUX images, no component of the film's media is non-commercial any more (v1 used CC-BY-NC MMS and MusicGen).

### E27: Wan 2.2 for the film: 5 clips generated, 3 passed QC
* **Run:** one private Kaggle kernel (after F17), 512×512, 49 frames, 25 steps, fp16, sequential offload. Queue 426 s, weights 155 s, then per clip **574 / 436 / 433 / 433 / 433 s** (s01, s04, s05, s08, s10); job 2,551 s on the GPU, 2,999 s wall. All five passed the automatic NaN/black check.
* **Human QC (6 frames per clip, 0–48):**

| shot | verdict | evidence |
|---|---|---|
| s01 student at the door | **pass** | subtle head and light movement; identity stable |
| s04 road into the tale | **pass** | horse and servant walk toward camera, dust; stable |
| s05 king's fall | **reject** | a glowing flame-like object materialises in the foreground from ~frame 20 |
| s08 torches | **pass** | flames flicker, hooded figures and king stable (best clip) |
| s10 hands over the pit | **reject** | sparkle noise from ~frame 20, full colour melt by frame 48 |

* **Pattern:** the passes are scenes where the motion is *ambient* (light, dust, flames, a small head movement). Both rejects asked for a *physical event* (dust settling around a fallen man; one hand pulling another). The same pattern appeared in E21b (a hand-like smear). For a 5B model at 512 px, "one gentle ambient movement" is the reliable prompt class.
* **Mechanism:** verdicts live in the storyboard (`shots[].wan_qc: "pass: …" | "reject: …"`). A rejected clip is never imported, even though it exists and matches its keyframe; the shot falls back to Ken Burns with the reason in the log.
* **Sharpness cost (Laplacian variance of the same frame vs the Ken Burns cut, 9:16):** s01 0.85, s04 0.66, s08 0.61. The clips are 512 px upscaled 2.5×. A light unsharp mask raised this by only 1–2 points (0.86 / 0.67 / 0.63): the loss is resolution, not edge contrast. **Trade-off for the director:** real motion (living torches, walking figures) vs ~35 % less fine detail on those three shots.
* **Cost:** 3 usable seconds-of-motion clips for ~45 GPU-min in this run; total Wan effort across the project: 4 jobs, ~76 GPU-min, 4 of 8 clips generated were usable (1 in the test, 3 in the film).

### E28: Corrections from audience test 2, and per-shot framing for each aspect ratio
* **Feedback (2 of 3 viewers, director agreed):** (1) the mother looked like two different people in s02 and s03; (2) in s04 the king was not riding the horse.
* **Fix 1, consistency by construction:** s03 is no longer generated. `keyframe_from: "s02"` copies s02's image (no model call), and s03's Ken Burns pushes in from 1.3× to 1.6× onto her face (`focus` x 0.60, y 0.22). Same woman by definition, and a continuous move from the living room into her eyes before the dissolve to the road.
* **Fix 2, staging:** s04 regenerated once with explicit staging ("sits mounted in the saddle on the back of a white horse, riding forward, while {servant} walks on foot beside the horse"). **First attempt correct.** The old Wan clip was made from the previous keyframe, so it is marked `wan_qc: reject` (stale; no time for a new Wan run) and s04 uses Ken Burns.
* **Fix 3, framing:** every shot now has a `focus` point in the square keyframe. The 16:9 crop is centred on its y, the 9:16 crop on its x, clamped to the image (`shots._crop_for`); the same crop is applied to Wan clips. Before, a generic centre crop was used. Measured problems it fixed (frames in `outputs/review/`):
  * 16:9 s02: the band covered 22–78 % of the height, but the mother's face is at ~20 %, so **her head was cut off at the eyes**. After: whole face with headroom.
  * 16:9 s12: the student's forehead was cut. After: full face.
  * 9:16 s08: the king stands at x ≈ 0.17. A centred vertical band (22–78 %) would cut him out, and `focus.x = 0.25` keeps him in frame (the Wan clip had re-framed him already).
* **Cost of the corrections:** 1 FLUX image (~58 neurons), 0 narration or music calls. Full rebuild 353 s; total length unchanged at **87.208 s** in both ratios; −14.1 LUFS / −1.1 dBTP.
* **Before/after evidence:** `outputs/review/compare_9x16.png` (s02, s03, s04, s08 before | after) and `outputs/review/compare_16x9.png` (s02, s12), plus the individual frames and the original keyframes in `outputs/review/before/`.
