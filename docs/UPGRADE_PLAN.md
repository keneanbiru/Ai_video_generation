# v2 upgrade: audit against the brief, verified provider facts, plan

Written 26 Nov 2026 ~11:40 EAT. v1 (`~/heritage-short`) is frozen as the fallback. Its clean-clone rebuild was verified (30 calls, 37 min, byte-identical outputs).

## 1. Provider facts, verified today from official docs
| Need (brief) | Verified current option | Free? | Key facts | v1 code status |
|---|---|---|---|---|
| Script / storyboard / translation | `gemini-3.8-flash` (text), `gemini-3.5-flash-lite` for bulk | yes | free tier content **is used to improve Google products** → keep private family details out | **missing**: no script stage |
| Narration | `gemini-3.8-flash-tts` (also `gemini-3.8-flash-lite-tts`) | yes | **Amharic listed**, 130+ langs, 30 voices; new **Interactions API** `POST /v1beta/interactions`, style via `speech_metadata` annotation; returns WAV 24 kHz mono 16-bit (base64 in `steps[].content[].data`) | outdated: uses old `generateContent` shape + old model id, never run |
| Keyframes | `@cf/black-forest-labs/flux-1-schnell` (JSON: prompt, steps≤8, seed) · `@cf/black-forest-labs/flux-2-klein-4b` (**multipart**, image generation + **reference editing**) · klein-9b (multi-reference, but ~7 images/day) | yes, 10,000 neurons/day | ≈ 230 schnell or ≈ 380 klein-4b images/day at 512 px (my arithmetic from the neuron table) | schnell path written, never run; **klein not implemented**; no reference conditioning on hosted path |
| Moving shots | Wan 2.2 TI2V-5B, diffusers `Wan-AI/Wan2.2-TI2V-5B-Diffusers` | Kaggle ~30 GPU-h/week | needs **diffusers from git main**; docs use **bf16** (T4 lacks fast bf16 → test fp16 / P100 / Colab); "5 s 720p in under 9 min" on a consumer GPU; ≥24 GB with offload flags for native script | script written, never run; pipeline class unverified; **manual** upload/download |
| Music | ACE-Step 1.5 (`generate_music(dit_handler, llm_handler, GenerationParams, GenerationConfig)`) | open (MIT, outputs commercial OK) | Python 3.11–3.12, `uv sync`, ~10 GB checkpoints, DiT-only mode ≥4 GB VRAM, 12–16 GB = "tier 5", batch seeds supported | script uses the **v1 API** (wrong) |
| Assembly | FFmpeg | — | — | done, verified |
| Showcase | HF static page / Gradio Space | free | — | missing |

## 2. Gaps against the brief and the grading criteria
| # | Gap | Criterion hit | Priority |
|---|---|---|---|
| G1 | No recommended hosted model was actually executed (Gemini TTS, FLUX, Wan, ACE-Step) | SE 20, Measurement 5, film quality 50 | **P0–P2** |
| G2 | No `script` stage (brief: "pipeline/ one script per stage: script, keyframes, …"); storyboard drafting and subtitle translation were done by hand | SE, Design | P1 |
| G3 | GPU stages are manual (upload notebook, download files) | SE (one command), user asked for minimal manual steps | **P1**: Kaggle API push → poll → pull |
| G4 | Character consistency limited (E07 trade-off) | Film "consistent characters" | P1: FLUX.2 klein reference editing |
| G5 | Only music has provider-aware caching (F07 fix); keyframes/narration don't record a provider upgrade | SE caching | P2 (generalise, keyframes stay opt-in) |
| G6 | Real motion: all shots are Ken Burns | Film 50, walkthrough | P1 |
| G7 | Both user tests not yet run | Design 10, Report 10 | human, per story |
| G8 | Frontier/open benchmark: only a keyless endpoint compared | Measurement, Ceiling | P2: SD-Turbo vs FLUX, MMS vs Gemini TTS (blind test with ≥5 people = ceiling) |
| G9 | Showcase page | Ceiling | P3 |
| G10 | Docs/report describe v1; must be updated without erasing v1 evidence | Docs, all | continuous |

## 3. Plan (each step ends in a testable checkpoint; no new story until step 6)
1. **Gemini** (needs: your AI Studio API key) → rewrite Gemini TTS provider to the Interactions API; smoke test Amharic on the *existing development lines*; A/B vs MMS (latency, duration, native-speaker check by you). Add `pipeline/script.py`: Gemini turns a story text into a schema-valid storyboard draft + English subtitles (validated, never auto-accepted).
2. **Cloudflare** (needs: account id + API token with Workers AI permission) → FLUX.1 schnell + FLUX.2 klein-4b providers; probe klein's multipart fields; smoke on 2–3 existing dev prompts; compare with SD-Turbo; reference-conditioned keyframes via klein.
3. **Kaggle** (needs: phone-verified account + `kaggle.json` API token) → `pipeline/remote.py`: push a GPU kernel with the keyframes + storyboard, poll, pull clips/tracks with sidecars, merge timing into `runs.jsonl`. Smoke: Wan 2.2 on 2 existing keyframes at 480p; measure GPU minutes. Colab notebook as manual backup.
4. **ACE-Step 1.5** in the same Kaggle runner; 3 candidates on the dev caption; compare vs MusicGen.
5. Re-verify: caching, selective regeneration, retries, provider switching, clean-clone run; docs updated.
6. **Stop → ask for your story.** Then: audience/intent → storyboard → narration + radio cut → **stop for user test 1** → pictures/motion/music → near-final → **stop for user test 2** → finalize.

Time budget (deadline 23:59 EAT today): steps 1–5 by ~16:30; story work from ~16:30. If Wan on T4 is too slow for all shots, Wan goes on the 4–6 shots where motion matters, and Ken Burns stays on the rest (documented as a measured decision).
