# Walkthrough video script (≤ 5 min)

Record your screen (e.g. OBS, or `Ctrl+Alt+Shift+R` on GNOME for the built-in recorder) with a terminal and an editor. Talk in your own words; the bullets are prompts, not a script to read.

## 0:00–0:30 · The film in one breath
* Play the first 10 s of `outputs/film_9x16.mp4`.
* "This is *ቀስ በቀስ*, 85 seconds in Amharic about a grandmother's coffee ceremony and the proverb she repeated to me as a child. Nobody edited it by hand. A pipeline made it from one JSON file."

## 0:30–1:45 · Architecture
* Open `storyboard.json`. Scroll: `film` (audience, intent), `style.style_block`, `characters`, `providers`, `music.cues`, then one shot with `reason`, `image_prompt`, `seed`, `narration`, `subtitle_en`.
* "This file is the contract. Every stage reads it and none of them writes to it." Show `schema/storyboard.schema.json` briefly, then run `make validate`.
* Show the diagram at the top of `ARCHITECTURE.md`: narration → timeline → radio cut → keyframes → shots → music → assemble.
* "Narration runs first because picture is cut to the voice: each shot lasts as long as its line plus a breath."

## 1:45–2:45 · One hard decision (pick ONE)
* **Option A: Amharic pauses (E04).** "The TTS vocabulary has no punctuation at all, so `።` produced no pause. I proved it by tokenising with and without punctuation: identical ids. The fix splits lines at Ethiopic punctuation and inserts silences." Show `split_for_pauses` in `pipeline/narration.py`.
* **Option B: no GPU, 200 KB/s internet (F01/F03).** Provider chains with fallbacks: show `providers` in the storyboard and `run_chain` in `common.py`. The Kaggle scripts and the stale-clip guard.
* **Option C: ducking (E09).** "My first test changed two settings at once and gave a nonsense result; one variable at a time showed attack and release pulling in opposite directions."

## 2:45–4:30 · Live: change one shot, only that shot regenerates
```bash
make film                                  # warm cache → "model calls this run: 0"
```
Edit `storyboard.json`, shot **s07**, `image_prompt`, e.g. add "…, a small bowl of popcorn beside it" (popcorn is traditionally served with buna). Save.
```bash
make film
```
* Point at the log: `keyframes/s07: generating`, every other keyframe `cached`, and the summary line `model calls this run: 1 {"keyframes/s07": "ok"}`.
* `tail -n 1 runs.jsonl | python -m json.tool`: stage, item s07, model sd-turbo, seed 107, latency.
* Open `outputs/keyframes/s07.png` to show the new image. (You can pause the recording while it runs. On this laptop one keyframe takes about 10–20 s on CPU and the full re-assembly about 1–2 min.)
* Alternative: change the narration of s05 → `narration/s05: generating`, one TTS call.

## 4:30–5:00 · What I learned
* One sentence, e.g. "Measure before you trust: the TTS dropped punctuation, the free image endpoint swapped models silently, and my first ducking test lied to me because I changed two things at once."
