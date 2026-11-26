"""Fallback score composed in code (no model, no download): `local:procedural` provider.

Not AI. A small, seeded algorithmic composer, used when no music model is available, so the
pipeline always finishes. Timbres: a plucked lyre (Karplus-Strong string synthesis, a stand-in
for the krar), a breathy flute pad (a stand-in for the washint), a low drone. Pitches come from
the tizita major pentatonic (1 2 3 5 6), common in Ethiopian song. Each seed gives a different
melody, so candidates can be auditioned like model outputs.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

SR = 48000
TIZITA = [0, 2, 4, 7, 9]  # semitones of the tizita major pentatonic


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def pluck(freq: float, dur: float, rng: np.random.Generator, bright: float = 0.6) -> np.ndarray:
    n = int(dur * SR)
    p = max(2, int(SR / freq))
    burst = np.zeros(n)
    burst[:p] = rng.uniform(-1, 1, p) * np.hanning(p)
    burst[:p] = lfilter([bright, 1 - bright], [1], burst[:p])  # soften the attack
    d = 0.996
    a = np.zeros(p + 2)
    a[0], a[p], a[p + 1] = 1.0, -d / 2, -d / 2
    y = lfilter([1.0], a, burst)
    return y * np.exp(-np.linspace(0, dur, n) * 1.2)


def flute(freq: float, dur: float, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    vib = 1 + 0.004 * np.sin(2 * np.pi * 4.8 * t)
    ph = 2 * np.pi * freq * np.cumsum(vib) / SR
    tone = np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.05 * np.sin(3 * ph)
    breath = lfilter([1], [1, -0.97], rng.normal(0, 0.02, t.size)) * 0.25
    env = np.minimum(1, t / 0.6) * np.minimum(1, (dur - t) / 0.9).clip(0)
    return (tone + breath) * env * 0.22


def compose(seconds: float, seed: int, bpm: float = 63, root_midi: int = 57) -> np.ndarray:
    """Stereo float32 array. root 57 = A3."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    L, R = np.zeros(n + SR * 4), np.zeros(n + SR * 4)
    beat = 60 / bpm
    # drone: root + fifth, slowly breathing
    t = np.arange(L.size) / SR
    drone = (np.sin(2 * np.pi * _hz(root_midi - 12) * t) + 0.5 * np.sin(2 * np.pi * _hz(root_midi - 5) * t))
    drone *= 0.05 * (0.75 + 0.25 * np.sin(2 * np.pi * t / 11))
    L += drone; R += drone
    # lyre: a sparse arpeggio over a 4-bar progression on scale degrees
    prog = rng.permutation([0, 3, 4, 1])
    pos = 0.0
    while pos < seconds:
        bar = int(pos / (beat * 4)) % 4
        base = TIZITA[prog[bar]]
        for k in range(4):
            if rng.random() < 0.72:  # leave gaps: sparse under the voice
                deg = TIZITA[(TIZITA.index(base) + rng.choice([0, 1, 2, 4])) % 5]
                octv = 12 * rng.choice([0, 0, 1])
                note = pluck(_hz(root_midi + deg + octv), beat * 3, rng, bright=rng.uniform(0.45, 0.7))
                i = int((pos + k * beat + rng.normal(0, 0.012)) * SR)
                if 0 <= i < n:
                    pan = rng.uniform(0.3, 0.7)
                    L[i:i + note.size] += note[: L.size - i] * 0.35 * (1 - pan)
                    R[i:i + note.size] += note[: R.size - i] * 0.35 * pan
        pos += beat * 4
    # flute: one long phrase every 8 bars, a motif that returns
    motif = [TIZITA[i] for i in rng.choice(5, 4)]
    for start in np.arange(beat * 8, seconds - beat * 6, beat * 16):
        for j, deg in enumerate(motif):
            tone = flute(_hz(root_midi + 12 + deg), beat * 2.2, rng)
            i = int((start + j * beat * 2) * SR)
            L[i:i + tone.size] += tone[: L.size - i] * 0.9
            R[i:i + tone.size] += tone[: R.size - i]
    st = np.stack([L[:n], R[:n]], axis=1)
    # a touch of room: two short feedback-free echoes
    for dly, g in ((0.031, 0.25), (0.067, 0.15)):
        k = int(dly * SR)
        st[k:] += st[:-k][:, ::-1] * g
    st /= np.abs(st).max() + 1e-9
    return (st * 0.8).astype(np.float32)
