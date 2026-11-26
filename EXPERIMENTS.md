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

### E08: Choosing the score candidate
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
