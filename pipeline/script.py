"""Stage 0: script. Gemini drafts the storyboard from a story, and translates subtitles.

    python -m pipeline.script draft  --story story/story.md   -> storyboard.draft.json (validated)
    python -m pipeline.script subtitles                        -> storyboard.draft.json with missing subtitle_en filled
    python -m pipeline.script accept                           -> copies the draft over storyboard.json (after you read it)

The model never writes storyboard.json directly: a human reads the draft, edits it, and accepts it,
so `git diff storyboard.json` stays a record of human decisions. Every call goes to runs.jsonl.

Privacy: the Gemini free tier may use prompts to improve Google's products (verified on the
pricing page, 26 Nov 2026). Keep private family details out of story.md, or use a paid key.

Text model chain: gemini-3.8-flash -> gemini-3.5-flash-lite (Flash returned 503 "high demand"
during testing; see FAILURES F10).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from .common import (
    ROOT, SCHEMA, STORYBOARD, ProviderUnavailable, StoryboardError, cache_key, load_storyboard, log, log_call,
    retry,
)

DRAFT = ROOT / "storyboard.draft.json"
TEXT_MODELS = [m for m in os.environ.get("GEMINI_TEXT_MODELS", "gemini-3.8-flash,gemini-3.5-flash-lite").split(",") if m]
CACHE = ROOT / "outputs" / "script" / "translations.json"


def gemini_json(prompt: str, item: str, stage: str = "script") -> tuple[dict, str]:
    """Call the text chain until one model returns valid JSON. Returns (data, model)."""
    from .common import require_online

    require_online("gemini-text")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ProviderUnavailable("GEMINI_API_KEY not set")
    import requests

    last = None
    from .quota import guard

    for model in TEXT_MODELS:
        try:
            guard(model, "film")
        except ProviderUnavailable as e:
            log(f"  [script] {e}")
            continue
        @retry(times=3, base_delay=6, retry_on=(RuntimeError, requests.RequestException))
        def call():
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7}},
                              timeout=180)
            if r.status_code in (429, 500, 502, 503, 504):
                # every attempt is a request the dashboard counts (503s count, 429s do not): log each one
                log_call(stage=stage, item=f"{item}:attempt", provider="gemini-text", model=model, device="hosted",
                         status="error", error=f"{r.status_code} {r.text[:120]}")
                raise RuntimeError(f"{r.status_code} {r.text[:160]}")
            if r.status_code >= 400:
                raise ProviderUnavailable(f"{model}: {r.status_code} {r.text[:200]}")
            return r.json()

        t0 = time.time()
        try:
            d = call()
            text = d["candidates"][0]["content"]["parts"][-1]["text"]
            data = json.loads(text)
        except Exception as e:  # this model failed after retries: try the next one
            log_call(stage=stage, item=item, provider="gemini-text", model=model, latency_s=round(time.time() - t0, 2),
                     device="hosted", status="error", error=repr(e)[:300])
            log(f"  [script] {model} failed: {e!r}"[:200])
            last = e
            continue
        u = d.get("usageMetadata", {})
        log_call(stage=stage, item=item, provider="gemini-text", model=d.get("modelVersion", model),
                 latency_s=round(time.time() - t0, 2), device="hosted", cost_usd=0.0,
                 tokens_in=u.get("promptTokenCount"), tokens_out=u.get("candidatesTokenCount"))
        return data, model
    raise RuntimeError(f"every Gemini text model failed: {last!r}")


DRAFT_RULES = """You are a story editor and storyboard artist for a 60-90 second narrated short film.
Turn the STORY below into a storyboard JSON object that validates against the JSON SCHEMA below.
Rules:
- 8-12 shots. Narration in the film language ({language_name}, ISO 639-3 "{language}"), written for the ear:
  short sentences, concrete images. Budget about {wps} words per second of narration
  (measured for this language and voice), so the narration fits the target duration.
- Every shot has a one-sentence "reason" (why the film needs it), a varied shot_size, a still-image prompt
  of at most 45 words that describes subject, place and light (no text, signs or letters in the image),
  and a motion_prompt that names ONLY motion and camera (the image already holds the subject).
- Characters: at most 3. Describe each in one fixed sentence of at most 18 words; in shot prompts refer
  to a character only as {{name}}. Set real_person to false unless the story says it is a real,
  identifiable person; if true, add consent_ref "consent-<name>".
- style.style_block: at most 20 words describing qualities (medium, palette, light), never an artist's name.
- music: an instrumental caption (style, mood, instruments, texture; no tempo or key in the caption),
  3 candidate seeds, chosen = the first, and 3-5 cues that refer to shot ids.
- subtitle_en: natural English, faithful to the narration, at most 80 characters.
- Keep providers exactly as given. Keep version 1.
Return ONLY the JSON object.

FILM SETTINGS: {settings}
PROVIDERS (copy exactly): {providers}
JSON SCHEMA: {schema}
STORY:
{story}
"""


def draft(story_path: Path, language: str, language_name: str, target: float, wps: float) -> Path:
    story = story_path.read_text(encoding="utf-8")
    schema = SCHEMA.read_text(encoding="utf-8")
    current = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    settings = {"language": language, "language_name": language_name, "target_duration_s": target}
    prompt = DRAFT_RULES.format(language=language, language_name=language_name, wps=wps, settings=json.dumps(settings),
                                providers=json.dumps(current["providers"]), schema=schema, story=story)
    data, model = gemini_json(prompt, "draft")
    for attempt in range(3):
        DRAFT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            load_storyboard(DRAFT)
            log(f"  [script] draft valid ({model}, attempt {attempt + 1}): {len(data['shots'])} shots -> {DRAFT.name}")
            return DRAFT
        except StoryboardError as e:
            if attempt == 2:
                raise
            log(f"  [script] draft invalid, asking for a repair:\n{e}")
            data, model = gemini_json(
                "Fix this storyboard JSON so it validates. Change only what the errors require.\n"
                f"ERRORS:\n{e}\nJSON SCHEMA:\n{schema}\nJSON:\n{json.dumps(data, ensure_ascii=False)}\n"
                "Return ONLY the corrected JSON object.", f"draft-repair-{attempt + 1}")
    return DRAFT


def subtitles(src: Path) -> Path:
    """Fill empty subtitle_en from narration (cached per line, so unchanged lines cost nothing)."""
    sb = json.loads(src.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [s for s in sb["shots"] if s["narration"].strip() and not s.get("subtitle_en", "").strip()]
    missing = [s for s in todo if cache_key(t=s["narration"], l=sb["film"]["language"]) not in cache]
    if missing:
        req = {s["id"]: s["narration"] for s in missing}
        data, _ = gemini_json(
            f"Translate each {sb['film']['language_name']} narration line into natural English film subtitles "
            "(faithful, at most 80 characters each). Keep names. Return a JSON object mapping each id to its "
            f"subtitle.\n{json.dumps(req, ensure_ascii=False)}", "subtitles")
        for s in missing:
            cache[cache_key(t=s["narration"], l=sb["film"]["language"])] = data[s["id"]]
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in todo:
        s["subtitle_en"] = cache[cache_key(t=s["narration"], l=sb["film"]["language"])]
    DRAFT.write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  [script] subtitles: {len(todo)} filled ({len(missing)} new translations) -> {DRAFT.name}")
    return DRAFT


def accept() -> None:
    load_storyboard(DRAFT)  # never accept an invalid draft
    backup = ROOT / "outputs" / "script" / f"storyboard.before-accept.{time.strftime('%Y%m%dT%H%M%S')}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(STORYBOARD, backup)
    shutil.copy(DRAFT, STORYBOARD)
    log(f"  [script] accepted draft -> storyboard.json (previous kept at {backup.relative_to(ROOT)})")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--story", type=Path, required=True)
    d.add_argument("--language", default="amh")
    d.add_argument("--language-name", default="Amharic")
    d.add_argument("--target", type=float, default=75)
    d.add_argument("--wps", type=float, default=1.35, help="measured words/s (E02, E15)")
    s = sub.add_parser("subtitles")
    s.add_argument("--src", type=Path, default=DRAFT if DRAFT.exists() else STORYBOARD)
    sub.add_parser("accept")
    a = ap.parse_args()
    if a.cmd == "draft":
        draft(a.story, a.language, a.language_name, a.target, a.wps)
    elif a.cmd == "subtitles":
        subtitles(a.src)
    else:
        accept()


if __name__ == "__main__":
    main()
