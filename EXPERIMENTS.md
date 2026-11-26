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
