# FAILURES.md: what broke, what was tried, what fixed it

Entries are in the order they happened. Times are EAT on 26 Nov 2026 (the build night).

### F01: No GPU on the build machine
* **Symptom:** `nvidia-smi: command not found`. The machine is an 8-core laptop CPU with 14 GB RAM, about 7 GB of it already in use.
* **Impact:** Wan 2.2 (video), ACE-Step (music) and FLUX at full size cannot run locally.
* **Tried:** the brief's answer is Kaggle T4s, but a Kaggle account needs its owner's **phone verification**, and the agent building this overnight could not do that for the owner.
* **Resolution:** every stage got a **CPU-runnable provider** (SD-Turbo for keyframes, MMS-TTS for narration, MusicGen-small or a procedural score for music, Ken Burns for motion). The **GPU work is packaged** as `kaggle/wan22_i2v.py` and `kaggle/acestep_score.py`, which write files plus a JSON sidecar that the local stages import (with a stale-input guard). Once the owner runs the notebook, `make film` picks the clips up with no code change.

### F02: No ffmpeg, no git, no pip, and no sudo
* **Symptom:** `ffmpeg`, `git`, `pip3` not found. System Python is 3.14, too new for CPU PyTorch wheels. `sudo: interactive authentication is required`.
* **Tried:** `micromamba create … python=3.11 ffmpeg git make pip` in user space. The conda-forge `ffmpeg` package pulled in more than 1 GB of optional dependencies (OpenVINO plugins, etc.) and after ~10 minutes had downloaded 637 MB with no end in sight on this link (F03).
* **Resolution:** stopped it. Created the env **without** ffmpeg (Python 3.11, git, make, pip: done in under a minute), and used the **static FFmpeg 7.0.2 build** (40 MB) instead, after checking it has `subtitles` (libass), `sidechaincompress`, `loudnorm`, `zoompan` and `xfade`. It lacks `drawtext`, so the end card is drawn with Pillow instead.
* **Lesson:** check what a package drags in before downloading it on a slow link.

### F03: The internet connection is ~200 KB/s
* **Symptom:** measured with `/proc/net/dev` over 30 s: **205 KB/s total**, shared between pip and the model download. PyTorch CPU alone is 210 MB. The planned weights (SD-Turbo full precision 5.2 GB, MusicGen-small 2.4 GB, MMS 145 MB) would take **7+ hours**.
* **Tried / resolved:**
  1. **fp16 variants**: SD-Turbo's fp16 UNet + text encoder + VAE = 2.58 GB instead of 5.2 GB. Loaded with `variant="fp16"` and upcast to fp32 on CPU.
  2. A **resumable downloader** (`tools/fetch_models.sh`, `curl -C - --retry 20`) that mirrors only the needed files and marks each repo `.complete`. `common.model_path()` prefers the local mirror.
  3. **Priority order**: narration model first (it gates the radio cut), then images, then music.
  4. Providers **refuse to trigger a surprise multi-GB download** mid-run (`ProviderUnavailable` unless `ALLOW_HF_DOWNLOAD=1`), so the chain falls through to a fallback instead of hanging for hours.
  5. A **procedural score** fallback (`pipeline/procedural_score.py`, numpy only, zero download), so the film can finish even if MusicGen never arrives.

### F04: No API keys for Gemini or Cloudflare
* **Symptom:** no `GEMINI_API_KEY`, `CLOUDFLARE_*` in the environment. Creating accounts needs the owner.
* **Resolution:** the provider chain logs `unavailable: GEMINI_API_KEY not set` and falls through to local models. `make smoke` records this in `runs.jsonl` and `outputs/smoke.json`. The hosted code paths are written against the documented REST APIs but are **unverified** until a key is added.

### F05: A "free FLUX" endpoint silently served a different model and stamped a watermark
* **Context:** to work around F03 for images I tried a keyless hosted endpoint (`image.pollinations.ai`, `model=flux`, `nologo=true`). One 640×640 image: 43 KB, 6.9 s.
* **Symptom:** the JPEG's EXIF says **`manufacturer=sana`**, so it was not FLUX. It also carries a visible **"pollinations.ai" watermark** despite `nologo=true`. The image ignored "clay" and "gouache" in the prompt (a shiny metal kettle, photographic).
* **Decision:** not used for the film. Cropping a watermark out would contradict the brief's labelling guidance ("leave watermarks intact"), and a provider that substitutes models silently breaks reproducibility (same request, unknown model). Kept only as a hosted-vs-local data point (EXPERIMENTS.md).
* **Lesson:** log the model the provider *says it used*, not the one you asked for. Check output metadata.

### F06: The brief's tool names had moved on
* The brief names Gemini 3.8 Flash TTS, FLUX.2 klein and ACE-Step 1.5. With no keys and no GPU none of these could be called, so their current model ids and entry points could not be verified. Mitigations: the Gemini TTS model id is an env var (`GEMINI_TTS_MODEL`); `kaggle/acestep_score.py` isolates the model call in one `render()` function and documents the output contract the local stage checks, so an API rename touches one function.

### F07: The download stalled for two hours, then the cache refused to use the better model
* **Symptom 1 (07:36–09:51):** the SD-Turbo UNet download crawled from 675 to 803 MB in over two hours (measured 5 KB/s). `curl` was still alive, so `--retry` never fired: a connection that is slow but not dead never triggers a retry.
* **Fix 1:** killed and restarted the downloader (`curl -C -` resumes from the byte offset). The new connection ran at **8.9 MB/s**; the remaining 1.1 GB took about two minutes, and MusicGen (2.4 GB) arrived right after. Next time: `curl --speed-limit 20000 --speed-time 60` so a stalled transfer aborts itself and the retry loop reconnects. (A side mistake: my first `pkill -f` pattern also matched the shell running it and killed it, exit 144.)
* **Symptom 2:** with MusicGen finally on disk, the music stage would still have served the **procedural fallback** candidates from cache. Their key (caption, seed, length, chain) does not change when a better provider becomes available.
* **Fix 2:** the music cache key now includes `best_available(chain, seed)`, the first provider that can actually run right now. A fallback output is automatically regenerated once a better provider shows up, and only then. Keyframes deliberately do **not** do this: an approved image should not change just because an API key was added.

### F08: CLIP silently truncated the style block
* **Symptom:** while the first full keyframe pass ran, the log said `The following part of your input was truncated because CLIP can only handle sequences up to 77 tokens: [', golden morning light, earthy ochre, terracotta and deep green palette…']`. SD-Turbo's text encoder reads at most 77 tokens. The style block is appended **at the end** of every prompt, so the longer prompts lost exactly the words that keep the film's look consistent.
* **Measured:** style block alone = 38 tokens. 6 of 12 shot prompts were over the limit (s02 = 103, s09 = 100, s10 = 92, s06 = 91, s05 = 86), plus Emama's reference prompt (80). Consistency was being broken silently for half the film.
* **Fix:** compressed the style block to 20 tokens and the character descriptions to 12–18 tokens (same meaning, fewer words: commit "F08"). Added `keyframes.check_prompt_lengths()`, which runs before any generation and fails the stage with the offending shot ids, plus a test. Every prompt now fits.
* **Lesson:** a warning buried in library output can be the most important line of a run. The style-block practice from the brief is only as good as the token budget it lives in.
