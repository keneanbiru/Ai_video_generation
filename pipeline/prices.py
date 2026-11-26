"""List-price equivalents used for COSTS.md and runs.jsonl.

Everything actually ran at $0. These numbers answer "what would this have cost on a paid,
hosted equivalent?" Every rate is an explicit assumption kept in one place with its source,
so it can be corrected without touching stage code. See COSTS.md for how they were chosen.
"""
from __future__ import annotations

RATES = {
    # Hosted GPU rental, used to price local CPU work as "the GPU minutes it would need".
    "t4_gpu_hour_usd": 0.35,          # assumption: typical on-demand T4 rate on major clouds
    "cpu_to_t4_speedup": 8.0,         # assumption: SD-Turbo/VITS/MusicGen-small run ~8x faster on a T4 than on this 8-core laptop CPU
    # Per-item hosted list prices for the providers named in the brief (free tier at the time of writing).
    "cloudflare_flux_schnell_per_image_usd": 0.00053,   # assumption: ~4 steps at 512-640px on Workers AI neuron pricing
    "gemini_tts_per_1k_chars_usd": 0.0,                 # free tier; paid rate not used
    "wan22_5b_t4_minutes_per_5s_clip": 12.0,            # assumption from the brief: "several minutes on a 4090, longer on a T4"
}


def gpu_equivalent_usd(cpu_seconds: float) -> float:
    gpu_h = cpu_seconds / RATES["cpu_to_t4_speedup"] / 3600.0
    return round(gpu_h * RATES["t4_gpu_hour_usd"], 6)


def image_equivalent(provider: str = "local") -> float:
    return RATES["cloudflare_flux_schnell_per_image_usd"]


def wan_clip_equivalent_usd() -> float:
    return round(RATES["wan22_5b_t4_minutes_per_5s_clip"] / 60.0 * RATES["t4_gpu_hour_usd"], 4)
