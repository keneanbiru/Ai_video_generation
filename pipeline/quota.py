"""Local quota ledger for free-tier APIs (no API calls: counts our own runs.jsonl).

Google publishes no free-tier numbers in the docs and no endpoint reports remaining quota, so we
count requests ourselves per model per quota day (Gemini resets at midnight US Pacific) against
the limits the API itself stated in its 429 messages. Experiments are refused when a model would
drop below a reserve kept for the film (FAILURES F09).

    python -m pipeline.quota            # table of today's usage
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .common import OUT, RUNS

# Requests per day, confirmed on the AI Studio rate-limit dashboard (26 Nov 2026).
DAILY_LIMITS = {"gemini-3.8-flash-tts": 10, "gemini-3.8-flash-lite-tts": 10, "gemini-3.8-flash": 20,
                "gemini-3.5-flash-lite": 500}
# How the dashboard counts (checked against our log): 503 errors COUNT, 429 rejections do NOT.
ASSUMED_LIMIT = 10  # for unobserved models: assume the same as the observed TTS limit
ADJUST = OUT / "quota_adjust.json"  # calls made outside the logger, e.g. {"2026-11-26": {"gemini-3.8-flash-tts": 1}}


def quota_day(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def used_today(model: str) -> int:
    day = quota_day()
    n = 0
    if RUNS.exists():
        for line in RUNS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("model") != model or r.get("status") == "unavailable":
                continue
            if r.get("status") == "error" and "429" in str(r.get("error") or ""):
                continue  # rejected by the rate limiter: not counted against the quota
            ts = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%S%z")
            if quota_day(ts) == day:
                n += 1
    if ADJUST.exists():
        n += json.loads(ADJUST.read_text()).get(day, {}).get(model, 0)
    return n


def remaining(model: str) -> int:
    limit = DAILY_LIMITS.get(model) or ASSUMED_LIMIT
    return max(0, limit - used_today(model))


def guard(model: str, purpose: str) -> None:
    """Raise before spending a request an experiment cannot afford. Production calls are only warned."""
    from .common import ProviderUnavailable, log

    left = remaining(model)
    reserve = int(os.environ.get("GEMINI_TTS_RESERVE", "8"))  # today: keep all Lite TTS for the film
    if purpose == "experiment" and left <= reserve:
        raise ProviderUnavailable(f"{model}: ~{left} requests left today, reserve {reserve} kept for the film; "
                                  "experiment refused (set GEMINI_TTS_RESERVE to override)")
    if left <= 0 and DAILY_LIMITS.get(model):  # hard stop only on a limit the API actually stated
        raise ProviderUnavailable(f"{model}: daily quota used up by our own count ({used_today(model)} calls today)")
    if left <= 2:
        log(f"  [quota] {model}: only ~{left} requests left today")


def main() -> None:
    day = quota_day()
    reset = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=ZoneInfo("America/Los_Angeles")) + timedelta(days=1)
    print(f"quota day {day} (US Pacific); resets {reset.astimezone(ZoneInfo('Africa/Addis_Ababa')):%Y-%m-%d %H:%M} EAT")
    for m, lim in DAILY_LIMITS.items():
        print(f"  {m:28s} used {used_today(m):3d}  limit {lim if lim else f'~{ASSUMED_LIMIT} (assumed)'}  "
              f"left ~{remaining(m)}")
    print(f"cloudflare neurons (UTC day): used {cf_used_today():.0f} / {CF_DAILY_NEURONS}; "
          f"schnell 512px 4 steps = {cf_cost('@cf/black-forest-labs/flux-1-schnell', 512, 512, 4)} n, "
          f"klein-4b 512px = {cf_cost('@cf/black-forest-labs/flux-2-klein-4b', 512, 512, 0)} n "
          f"(+{cf_cost('@cf/black-forest-labs/flux-2-klein-4b', 0, 0, 0, 1):.2f} per 512px reference tile)")



# ---------------------------------------------------------------- Cloudflare Workers AI neurons
# Free allocation 10,000 neurons/day, resets 00:00 UTC (pricing page, 18 Nov 2026 revision).
CF_DAILY_NEURONS = 10_000
CF_NEURONS = {  # per image, from the published per-tile / per-step rates
    "@cf/black-forest-labs/flux-1-schnell": lambda tiles, steps, inputs=0: 4.80 * tiles + 9.60 * steps,
    "@cf/black-forest-labs/flux-2-klein-4b": lambda tiles, steps, inputs=0: 26.05 * tiles + 5.37 * inputs,
}


def cf_cost(model: str, width: int, height: int, steps: int, input_tiles: int = 0) -> float:
    import math

    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    f = CF_NEURONS.get(model)
    return round(f(tiles, steps, input_tiles), 2) if f else 0.0


def cf_used_today() -> float:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used = 0.0
    if RUNS.exists():
        for line in RUNS.read_text(encoding="utf-8").splitlines():
            if '"cloudflare"' not in line:
                continue
            r = json.loads(line)
            ts = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
            if ts.strftime("%Y-%m-%d") == day and r.get("status") == "ok":
                used += float(r.get("neurons") or 0)
    return used


def cf_guard(model: str, neurons: float, purpose: str) -> None:
    from .common import ProviderUnavailable

    left = CF_DAILY_NEURONS - cf_used_today()
    reserve = float(os.environ.get("CF_NEURON_RESERVE", "3000"))  # kept for the film's keyframes
    if purpose == "experiment" and left - neurons < reserve:
        raise ProviderUnavailable(f"cloudflare: {left:.0f} neurons left today; experiment would cut into the "
                                  f"{reserve:.0f} reserved for the film")
    if left - neurons < 0:
        raise ProviderUnavailable(f"cloudflare: free daily neurons used up ({left:.0f} left, need {neurons})")


if __name__ == "__main__":
    main()
