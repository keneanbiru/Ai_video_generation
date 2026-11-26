"""The edit decision list, computed (never hand-written) from the storyboard and narration.

Picture is cut to the voice: a shot lasts max(min_duration_s, delay + narration + tail).
"""
from __future__ import annotations

import json
from pathlib import Path

from .common import OUT, duration_s

TAIL_S = 0.9  # breath after each line before the cut


def build(sb: dict, narr: dict[str, Path]) -> dict:
    t = 0.0
    shots = []
    tail = sb["film"].get("line_tail_s", TAIL_S)
    for s in sb["shots"]:
        delay = s.get("narration_delay_s", 0.4)
        nd = duration_s(narr[s["id"]]) if s["id"] in narr else 0.0
        d = max(s["min_duration_s"], delay + nd + tail) if nd else s["min_duration_s"]
        d = round(d * 24) / 24  # whole frames at 24 fps
        shots.append({"id": s["id"], "start": round(t, 3), "duration": round(d, 3),
                      "narration_start": round(t + delay, 3) if nd else None,
                      "narration_s": round(nd, 3), "subtitle_en": s["subtitle_en"]})
        t += d
    end = sb["end_card"]["duration_s"]
    tl = {"shots": shots, "end_card": {"start": round(t, 3), "duration": end}, "total_s": round(t + end, 3),
          "fps": 24}
    OUT.mkdir(exist_ok=True)
    (OUT / "timeline.json").write_text(json.dumps(tl, indent=1, ensure_ascii=False))
    return tl
