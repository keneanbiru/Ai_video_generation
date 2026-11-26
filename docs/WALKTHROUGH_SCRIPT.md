# Walkthrough video (≤ 5 min): script and exact commands

Record the screen (GNOME: Ctrl+Alt+Shift+R, or OBS). Speak in your own words; the bullets are prompts.

## 0:00–0:30 · The film
Play the first ~20 s of `outputs/cuts/final_9x16.mp4` (through the dissolve into the folktale).
"This is *ሁሉም ለበጎ ነው*, my mother's folktale, made from one JSON file by a pipeline of free models."

## 0:30–1:40 · Architecture
* Open `storyboard.json`: `film`, `voice`, `characters` (skin tone stated), `providers` (hosted first, local fallback), one shot (`reason`, `image_prompt`, `motion_prompt`, `narration`, `subtitle_en`, `focus`, `wan_qc`).
* `make validate` (schema + semantic checks).
* `ARCHITECTURE.md` diagram: script → narration → timeline → radio cut → keyframes → shots → music → assemble. "Picture is cut to the voice; every output is cached by a hash of its inputs."

## 1:40–2:40 · One hard decision (pick one)
* **Narration quota (E16/E22/F15):** 10 TTS requests a day. One request for the whole film, then an offline alignment rescued the take when the automatic split failed. Show `align_cuts` in `pipeline/narration.py` and `python -m pipeline.quota`.
* **Wan QC (E27):** 5 clips, 3 passed; show the `wan_qc` verdicts in the storyboard.

## 2:40–4:30 · Live: change one shot, only that shot regenerates
```bash
cd ~/heritage-short-v2
export PATH=$PWD/.venv/bin:$PATH
python -m pipeline.quota                 # show Cloudflare has neurons left (needs ~58)
make film                                # warm cache: ends with "model calls this run: 0"
```
Edit `storyboard.json`, shot **s07**, `image_prompt`: change "a shaft of evening light" to "a shaft of cold moonlight". Save.
```bash
make film 2>&1 | grep -E "generating|model calls"
tail -n 1 runs.jsonl | python -m json.tool  # the single new call: stage keyframes, item s07, model flux-1-schnell, latency, neurons
```
Expected: `keyframes/s07: generating`, every other stage cached, `model calls this run: 1 {"keyframes/s07": "ok"}`. FFmpeg then re-renders s07's two clips and re-assembles (≈ 6 min; you may pause the recording). Open `outputs/keyframes/s07.png`.
**Do not change a narration line on camera before 11:00 EAT on 27 Nov:** today's Gemini TTS quota is used up (the pipeline would refuse). If you want to show narration regeneration later, change one line and run `make radio` (1 request).
To restore afterwards: undo the edit and run `make film` again (≈ 1 new image call; FLUX has no seed, so it will be a new image unless you restore the cached file: keep a copy of `outputs/keyframes/s07.png` and its `.cache.json` before the demo).

## 4:30–5:00 · What I learned
e.g. "The audience caught what no metric did: two shots of the mother were two different women, and the king wasn't riding his horse."
