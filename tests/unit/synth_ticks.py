"""Synthetic WWV/WWVH/BPM tick trains for the self-registration tests.

The engine hands the detector a real-valued envelope with the DC removed
(metrology_engine: ``audio_signal = envelope - mean``).  We synthesise
that quantity directly: tone bursts (1000 Hz for WWV/BPM, 1200 Hz for
WWVH) of 5 ms at each UTC second, skipping seconds 29 and 59, with an
800 ms marker at second 0, each onset at ``utc_sec + delay_s`` in TRUTH.
"""

from __future__ import annotations

import numpy as np

from hf_timestd.core.buffer_timing import BufferTiming

TICK_HZ = {"WWV": 1000.0, "BPM": 1000.0, "WWVH": 1200.0}
TICK_S = 0.005
MARKER_S = 0.800


def make_tick_audio(
    n_seconds: int,
    sample_rate: int,
    true_sample0_utc: float,
    stations: dict,
    snr_db: float,
    seed: int = 7,
    marker: bool = True,
) -> np.ndarray:
    """``stations`` maps station name -> propagation delay in seconds."""
    rng = np.random.default_rng(seed)
    n = int(n_seconds * sample_rate)
    noise_std = 10.0 ** (-snr_db / 20.0)  # tick amplitude is 1.0
    audio = noise_std * rng.standard_normal(n)
    t = np.arange(n) / sample_rate
    first_sec = int(np.floor(true_sample0_utc))
    last_sec = int(np.ceil(true_sample0_utc + n_seconds)) + 1
    for station, delay_s in stations.items():
        f = TICK_HZ[station]
        for utc_sec in range(first_sec, last_sec):
            sim = utc_sec % 60
            if sim in (29, 59):
                continue
            if sim == 0 and not marker:
                continue
            dur = MARKER_S if sim == 0 else TICK_S
            onset = (utc_sec + delay_s) - true_sample0_utc
            i0 = int(round(onset * sample_rate))
            i1 = i0 + int(dur * sample_rate)
            if i0 >= 0 and i1 <= n:
                audio[i0:i1] += np.cos(2 * np.pi * f * t[i0:i1])
    return audio


def label_timing(
    true_sample0_utc: float, walk_s: float, sample_rate: int
) -> BufferTiming:
    """The label plane: sample0_utc off truth by walk_s (positive = label late)."""
    return BufferTiming(
        sample0_utc=true_sample0_utc + walk_s,
        sample_rate=sample_rate,
        source="rtp_gps",
        n_snapshots_used=1,
        jitter_ms=0.0,
    )
