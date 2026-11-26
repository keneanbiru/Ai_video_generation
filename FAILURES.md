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

---
## v2 (upgrading to the recommended providers)

### F09: Gemini TTS changed API, and the free tier allows 10 requests a day
* **Symptom 1:** v1's Gemini provider used the old `generateContent` request shape and the model id `gemini-2.5-flash-preview-tts`. The current docs (checked 26 Nov 2026) use the **Interactions API** (`POST /v1beta/interactions`, style as a `speech_metadata` annotation, base64 WAV in `steps[].content[].data`) and the id `gemini-3.8-flash-tts`. The v1 path was never executed (no key), so it would have failed on first use. Rewritten and verified with a live call (HTTP 200, 4.4 s).
* **Symptom 2:** during E15 the API returned `429 … limit: 3 requests per minute on Free Tier`, then `limit: 10 requests per day`. My `@retry` waited 5/10/20 s, too short for the per-minute limit and pointless for the daily one: four wasted retries.
* **Fix:** (1) parse the server's "Please retry in 58s / 23h4m31s". Wait exactly that long for per-minute limits; for a daily limit raise `ProviderUnavailable` immediately, with no retries. (2) **Batch narration (E16):** one request per film instead of one per line. (3) Documented that `gemini-3.8-flash-lite-tts` has a separate quota as a same-provider backup.

### F10: Gemini text model overloaded; quota invisible until you hit it
* **Symptom:** `gemini-3.8-flash` (text) answered **503 "currently experiencing high demand"** twice in a row, at 2.4 s and 11.1 s. `gemini-3.5-flash-lite` answered the same structured-JSON request in 1.5 s.
* **Fix:** the script stage uses a text-model chain (`gemini-3.8-flash` → `gemini-3.5-flash-lite`). 429/5xx retry with backoff, then the next model.
* **Quota visibility:** there is no API to read the remaining free-tier quota, and the docs' rate-limit page lists no free-tier numbers. I spent the whole day's Flash-TTS quota (10/day, resets **11:00 EAT**, i.e. after the 23:59 deadline) on experiment E15 before seeing the limit. **Fix:** `pipeline/quota.py` keeps a ledger from `runs.jsonl` per model per Pacific-time quota day. `tts_gemini` and the script stage call `guard()` before every request; **experiments are refused** while a model is at or below a reserve kept for the film (`GEMINI_TTS_RESERVE`, default 8), and production stops hard only at limits the API itself stated. One unlogged probe call is recorded in `outputs/quota_adjust.json` so the ledger matches reality.
* **Consequence for the film:** today's narration must use `gemini-3.8-flash-lite-tts` (separate quota, Amharic supported). With one-request batch narration (E16) that is ~8 full takes.
* **Update (dashboard check, 12:10 EAT):** the AI Studio dashboard confirmed the daily limits: Flash TTS 10, Flash-Lite TTS 10, Flash text 20, Flash-Lite text 500. It also showed how requests are counted: our ledger matched it exactly once **503 errors were counted and 429 rejections were not**. `pipeline/quota.py` now uses these confirmed limits and that counting rule.

### F11: Cloudflare FLUX: the seed is rejected, and the reference field is undocumented
* **Symptom 1:** FLUX.1 schnell answered **400 `Additional or unevaluated properties '/seed' … not allowed`**. The docs page's own curl example sends `seed`, but the model's input schema (fetched from `/ai/models/schema`) allows only `prompt` and `steps`.
* **Fix:** the request no longer sends `seed`. Consequence: hosted keyframes are not reproducible from the storyboard; the cached PNG + sidecar is the record (E17).
* **Symptom 2:** FLUX.2 klein-4b takes an untyped multipart body. Its docs, schema, changelog and blog list no field names. Two guessed reference fields gave no effect measurable above klein's own run-to-run noise.
* **Decision:** timeboxed after two attempts (~95 neurons). The reference path is **not used and not claimed**; identity comes from explicit character text. `KLEIN_FIELDS` is an env override, so the correct names can be dropped in later without code changes.

### F12: ACE-Step 1.5 will not install on Kaggle's Python
* **Symptom:** first Kaggle run failed in 13 s: `ERROR: Package 'ace-step' requires a different Python: 3.13.16 not in '<3.13,>=3.11'`. Kaggle's image had moved to Python 3.13; the GPU probe a few minutes earlier had shown torch 2.11 on that image.
* **Fix:** follow the repo's own install path. The job pip-installs `uv`, runs `uv sync` in the cloned repo (it builds `.venv` with the pinned Python and CUDA torch), then re-executes itself inside that venv (`--inner`). I also switched the language model from 0.6B to **1.7B**: 0.6B is not in the main checkpoint download, and 1.7B is the docs' recommendation for 12–16 GB GPUs. Checkpoints are fetched explicitly with `snapshot_download`.
* **Observed in passing:** this job ran **while the Wan job was running**, so the free tier allows two GPU sessions at once and the runner can overlap music and video.

### F13: Wan 2.2 on two T4s: GPU OOM plus host-RAM kill (details in EXPERIMENTS E20)
* GPU OOM came from the untiled fp32 VAE decode (6.31 GiB request); the host-RAM kill (exit −9) came from running two model copies for two GPUs. Fixed: VAE tiling, one worker process. The local poller also lost DNS for `api.kaggle.com` during this job. The poll loop tolerated it (status calls do not raise), but the logged wall time (4,548 s) includes the outage; the Kaggle-side time was 756 s.

### F14: The Gemini text API was overloaded when the film's storyboard was due
* **Symptom (14:23–14:25 EAT):** `pipeline.script draft` failed twice: `gemini-3.8-flash` and `gemini-3.5-flash-lite` both answered **503 "experiencing high demand"** on every retry, 16 requests in all. The same Flash-Lite model had answered a small JSON request in 1.5 s two hours earlier. The draft prompt is large (story + full JSON schema), which may matter.
* **A second bug found:** the quota ledger logged one line per model per stage call, not one per HTTP attempt. Since the dashboard counts 503s, retries were undercounted. **Fixed:** every 5xx attempt is now logged (`item: "<stage>:attempt"`), and the 4 missed attempts of the first failed draft were back-filled and marked as such.
* **Decision:** stop spending quota on retries (Flash text left: 11/20). The agent (Claude Code) drafted the storyboard directly, as the brief allows ("have your agent draft storyboard.json"), with the provenance recorded in DESIGN.md. Gemini Flash-Lite is kept for a cheap independent back-translation check of the Amharic narration once the service recovers.

### F15: A fallback spent the narration quota it could not finish with
* **What happened (14:39 EAT):** the batch split of the film's narration failed its plausibility check, and the code fell back to one request per line, with **7 requests left for 11 lines**. It voiced s01–s08 and then hit the daily limit: Flash-Lite TTS 10/10, with no TTS left before the deadline (Flash TTS was already exhausted, F09).
* **Root causes:** (1) the splitter assumed the model would honour "two seconds between paragraphs"; it left 0.4–1.0 s. (2) The fallback did not ask whether it could finish before starting to spend.
* **Recovery:** the batch take contained all 11 lines. It was split offline by length alignment and verified against the per-line takes (EXPERIMENTS E22): **no line is missing and no quota was needed.**
* **Fixes in code:** `align_cuts` (length-aligned DP) replaces "longest pauses". The per-line fallback now refuses to start unless the remaining quota covers every line, and otherwise keeps the take for an offline split. Regression test added. Also, while archiving prototype assets I moved `outputs/clips_wan/` during a running Wan job, which made that job's final copy fail. The clip was recovered from the downloaded results, and lesson noted: don't move directories a background job writes to.

### F16: An offline test overwrote the film's Gemini narration with the fallback voice
* **What happened (15:13 EAT):** to test transitions without spending quota, I ran the stages with `HERITAGE_OFFLINE=1`. Narration then picked MMS (first *available* provider), found no MMS cache for the new lines, and regenerated all 11, **overwriting the Gemini lines** in place (11 real MMS calls, logged).
* **Recovery:** the Gemini batch take and the alignment plan were untouched, and the split is deterministic. The 11 lines were rebuilt exactly (56.69 s vs 56.7 s before). No quota was needed.
* **Fix:** on a cache miss, the narration stage now first looks for a cached take of the **same text from a better provider earlier in the chain** and keeps it ("would be a downgrade"). Regression test added; verified on the real files (11/11 kept offline).

### F17: Kaggle cancelled two parallel Wan kernels
* **What happened:** `pipeline.remote wan --jobs 2` pushed two kernels while the ACE-Step kernel was still queued. Both Wan kernels went to `CANCEL_ACKNOWLEDGED` after 38 s with no log. Two concurrent sessions had worked earlier (E19/E20); three did not.
* **Decision:** one Wan kernel at a time next to ACE-Step, shots ordered by narrative importance (s04, s08, s10, s01, s05) so a partial run still delivers the most valuable clips. The runner already logs delivered vs requested clips (`wan:clips`).

### F18: A clean clone did not reproduce the film: the voice model lived in `.env`
* **Found by the final audit:** a fresh clone, run offline, regenerated all 11 narration lines with the MMS fallback and produced a 98.7 s film instead of 87.2 s. The narration WAVs were committed, but their cache key includes the TTS model name, which came from `GEMINI_TTS_MODEL` in the git-ignored `.env`. Without it the key used the default model name, missed, and the fallback ran.
* **Fix:** the model is now part of the contract (`storyboard.voice.gemini_model`), and the storyboard takes precedence over the environment. Verified with no `.env`: 11/11 narration cache hits. Two related completeness fixes from the same audit: the three ACE-Step candidates are now committed (they were git-ignored, so a clone would have composed a different score), and three early manual probe calls missing from `runs.jsonl` (the Kaggle GPU probe, the first Gemini TTS probe, the v1 keyless image probe) were back-filled and marked `"backfilled": true`.
* **Lesson:** "it runs from a clean clone" has to be tested from a clean clone. Every creative choice must live in the storyboard, not in local configuration.
