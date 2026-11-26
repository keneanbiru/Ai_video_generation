"""One command for the whole film:  python -m pipeline.run   (or: make film)

Stage order:
  1 validate   storyboard.json against schema/ + semantic checks
  2 narration  one WAV per shot (sets the timing of everything else)
  3 timeline   shot lengths cut to the voice -> outputs/timeline.json
  4 radio      radio cut (narration + temp music on black)        [--radio-only stops here]
  5 keyframes  reference sheet first, then one keyframe per shot
  6 shots      moving shots per aspect ratio (Wan import, else Ken Burns)
  7 music      score candidates + chosen bed shaped by the cue list
  8 assemble   duck, loudnorm, subtitles, end card, 16:9 + 9:16 exports

Every stage is cached by a hash of its inputs, so editing one shot regenerates only that
shot's model call(s); the FFmpeg stages downstream re-render what depends on it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .common import OUT, RUN_ID, RUNS, StoryboardError, load_storyboard, log


def _calls_this_run() -> list[dict]:
    if not RUNS.exists():
        return []
    rows = [json.loads(l) for l in RUNS.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r.get("run_id") == RUN_ID]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radio-only", action="store_true", help="stop after the radio cut")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--force", nargs="*", default=[], help="stages to regenerate ignoring cache")
    a = ap.parse_args(argv)

    t0 = time.time()
    log(f"=== run {RUN_ID} ===")
    try:
        sb = load_storyboard()
    except StoryboardError as e:
        log(str(e))
        return 2
    log(f"[1/8] storyboard valid: {len(sb['shots'])} shots, language={sb['film']['language']}")
    if a.validate_only:
        return 0

    from . import assemble, keyframes, music, narration, shots, timeline

    log("[2/8] narration")
    narr = narration.narration(sb, force="narration" in a.force)
    log("[3/8] timeline")
    tl = timeline.build(sb, narr)
    log(f"  total {tl['total_s']:.2f}s (target {sb['film']['target_duration_s']}s)")
    if not 60 <= tl["total_s"] <= 90:
        log(f"  WARNING: film length {tl['total_s']:.1f}s is outside 60-90s")
    log("[4/8] radio cut")
    assemble.radio_cut(sb, tl, narr)
    if a.radio_only:
        return _summary(t0)
    log("[5/8] keyframes (reference sheet first)")
    kfs = keyframes.keyframes(sb, force="keyframes" in a.force)
    log("[6/8] shots")
    clips = shots.shots(sb, kfs, tl, force="shots" in a.force)
    log("[7/8] music")
    bed = music.bed(sb, tl, force="music" in a.force)
    log("[8/8] assemble")
    assemble.final(sb, tl, narr, clips, bed)
    return _summary(t0)


def _summary(t0: float) -> int:
    calls = _calls_this_run()
    by = {}
    for c in calls:
        k = f"{c['stage']}/{c['item']}"
        by[k] = c["status"]
    log(f"=== done in {time.time() - t0:.1f}s; model calls this run: {len(calls)} "
        f"{json.dumps(by, ensure_ascii=False) if by else '(everything came from cache)'} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
