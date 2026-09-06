"""RegistrationAcquirer — the received ticks place the second boundary.

Spec: docs/superpowers/specs/2026-09-06-t3-self-registration-design.md.

The registration ``utc(sample) = sample0_utc + sample/sample_rate`` has a
rate (the GPSDO's, needs no help) and an origin (a measurement).  Before
this module the origin came from radiod's non-atomic (GPS_TIME,
RTP_TIMESNAP) pair, and the ±20 ms tick search around it could not
re-find the second when the pair landed off (232 ms on ND, 701 ms on
B4, 2026-09-06).  Here the tick train itself places the second: fold the
band-limited envelope at one second, find the peaks, fit them to the
expected station delays by a common shift, hold the result in the RTP
frame, and corroborate or correct it every minute.

Sign convention (pinned in the plan's Global Constraints):
    correction_s = expected_delay_s - fold_position_s, wrapped to (-0.5, 0.5]
    sample0_utc_acquired = sample0_utc_label + correction_s
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
from scipy.signal import butter, sosfiltfilt

logger = logging.getLogger(__name__)

ACQ_MIN_FOLD_SNR_DB = 10.0
FOLD_LENGTHS_S = (60, 120, 180)
TONE_BANDS_HZ: Dict[str, Tuple[float, float]] = {
    "1000": (900.0, 1100.0),  # WWV and BPM ticks
    "1200": (1100.0, 1300.0),  # WWVH ticks
}
BAND_OF_STATION: Dict[str, str] = {"WWV": "1000", "BPM": "1000", "WWVH": "1200"}
# Label seconds-in-minute excluded from the fold: 0 (marker), 29/59 (no
# tick), each widened by ±1 s because the label may be ~0.7 s wrong.
FOLD_SKIP_SECONDS = frozenset({59, 0, 1, 28, 29, 30})
# Fold-peak geometry: a 5 ms tick through a 200 Hz band is a ~10 ms bump.
# PEAK_MIN_SEPARATION_MS is a GUARD BAND, added on each side of a peak's own
# measured half-max width when marking samples taken -- it is not itself the
# two-peak resolving floor.  Two ticks resolve once separated by roughly
# (the weaker tick's half-max width + 2 * PEAK_MIN_SEPARATION_MS), which is
# usually well under PEAK_MAX_WIDTH_MS but scales with the actual bump, not
# with a fixed 25 ms exclusion regardless of width.
PEAK_MIN_SEPARATION_MS = 8.0
PEAK_MAX_WIDTH_MS = 25.0
ENVELOPE_LPF_HZ = 400.0
ORIGIN_SIGMA_FLOOR_MS = 1.0


@dataclass(frozen=True)
class FoldPeak:
    band: str
    position_s: float  # onset (half-rise) position within the label second
    snr_db: float
    width_ms: float


def _band_envelope(audio: np.ndarray, sample_rate: int, band: str) -> np.ndarray:
    lo, hi = TONE_BANDS_HZ[band]
    sos = butter(4, [lo, hi], btype="bandpass", fs=sample_rate, output="sos")
    x = sosfiltfilt(sos, np.asarray(audio, dtype=np.float64))
    env = np.abs(x)
    sos_lp = butter(2, ENVELOPE_LPF_HZ, btype="lowpass", fs=sample_rate, output="sos")
    return sosfiltfilt(sos_lp, env)


def fold_tick_train(
    audio: np.ndarray,
    sample_rate: int,
    sample0_utc_label: float,
    band: str,
    n_seconds: int,
) -> Tuple[np.ndarray, int]:
    """Average ``n_seconds`` label-seconds of the band envelope into one
    second.  Rows whose label second-in-minute is in FOLD_SKIP_SECONDS
    are left out.  Returns (profile[sample_rate], rows_used)."""
    env = _band_envelope(audio, sample_rate, band)
    first_sec = int(np.ceil(sample0_utc_label))
    i0 = int(round((first_sec - sample0_utc_label) * sample_rate))
    rows = []
    for k in range(n_seconds):
        utc_sec = first_sec + k
        if utc_sec % 60 in FOLD_SKIP_SECONDS:
            continue
        a = i0 + k * sample_rate
        b = a + sample_rate
        if b > len(env):
            break
        rows.append(env[a:b])
    if not rows:
        return np.zeros(sample_rate), 0
    return np.mean(np.stack(rows), axis=0), len(rows)


def find_fold_peaks(
    profile: np.ndarray,
    sample_rate: int,
    band: str,
    min_snr_db: float = ACQ_MIN_FOLD_SNR_DB,
) -> List[FoldPeak]:
    """Peaks above ``min_snr_db`` over a robust baseline.  SNR is
    20·log10(peak_above_baseline / MAD·1.4826).  Position is the half-rise
    sample on the leading edge, which sits on the tick onset; the apex
    would sit ~5 ms late."""
    if profile.size == 0 or not np.any(profile):
        return []
    baseline = np.median(profile)
    dev = profile - baseline
    mad = np.median(np.abs(dev)) * 1.4826
    if mad <= 0:
        return []
    # ACQ_MIN_FOLD_SNR_DB is a FLOOR.  The profile has ~len/30 independent
    # bins after the 400 Hz envelope LPF (24000 -> ~800), and pure noise
    # reaches sqrt(2 ln n_eff) ≈ 3.7σ somewhere among them; one extra σ of
    # margin puts the effective threshold near 13 dB, so noise alone never
    # names a tick.  A real tick folds far above this (a 5 dB tick gains
    # ~17 dB over 54 rows).
    n_eff = max(16.0, len(dev) * 2.0 * ENVELOPE_LPF_HZ / sample_rate)
    noise_extreme = np.sqrt(2.0 * np.log(n_eff)) + 1.0
    thr = mad * max(10 ** (min_snr_db / 20.0), noise_extreme)
    sep = int(PEAK_MIN_SEPARATION_MS * sample_rate / 1000)
    max_w = int(PEAK_MAX_WIDTH_MS * sample_rate / 1000)
    n = len(dev)
    order = np.argsort(dev)[::-1]
    taken = np.zeros_like(dev, dtype=bool)
    peaks: List[FoldPeak] = []
    for idx in order:
        if dev[idx] < thr:
            break
        # exclusion zone wraps circularly: position_s is defined mod 1 s,
        # so a peak near sample 0 and one near sample n-1 can be neighbors.
        if taken[(np.arange(idx - sep, idx + sep + 1)) % n].any():
            continue
        half = dev[idx] / 2.0
        # walk back to the half-rise point (circular within the second)
        j = idx
        steps = 0
        while dev[j % len(dev)] > half and steps < max_w:
            j -= 1
            steps += 1
        onset = (j + 1) % len(dev)
        # width at half max
        k = idx
        steps2 = 0
        while dev[k % len(dev)] > half and steps2 < max_w:
            k += 1
            steps2 += 1
        width_samples = steps + steps2
        width_ms = width_samples * 1000.0 / sample_rate
        if width_ms > PEAK_MAX_WIDTH_MS:
            continue  # a plateau, not a tick
        # Taken zone is the MEASURED bump plus PEAK_MIN_SEPARATION_MS of
        # guard on each side (circular within the second, as the
        # acceptance check above already is) -- not a fixed ±max_w, which
        # would force unrelated ticks apart by ~sep+max_w instead of the
        # intended ~width+2*sep.
        taken[(np.arange(onset - sep, onset + width_samples + sep + 1)) % n] = True
        peaks.append(
            FoldPeak(
                band=band,
                position_s=onset / sample_rate,
                snr_db=float(20 * np.log10(dev[idx] / mad)),
                width_ms=width_ms,
            )
        )
    peaks.sort(key=lambda p: -p.snr_db)
    return peaks


BAND_ARBITRATION_MS = 6.0


def arbitrate_bands(
    peaks_by_band: Dict[str, List[FoldPeak]], agree_ms: float = BAND_ARBITRATION_MS
) -> List[FoldPeak]:
    """Assign each fold position to ONE tone band.  A 5 ms tick has a sinc
    main lobe ~200 Hz wide, so a 1200 Hz tick leaks into 900-1100 Hz and a
    1000 Hz tick into 1100-1300 Hz; no filter separates them.  The band
    whose centre matches the tone responds more strongly, so when two
    bands carry a peak at the same position the weaker one is the leak.
    agree_ms=6.0: a measured WWVH leak's onset sat ~2.75 ms from its true
    1200-band peak (a real, same-tick artifact); distinct stations in
    different bands are >=18 ms apart in the tests here, so 6 ms merges
    the former without any real risk of merging the latter."""
    allp = [p for ps in peaks_by_band.values() for p in ps]
    allp.sort(key=lambda p: -p.snr_db)
    kept: List[FoldPeak] = []
    for p in allp:
        clash = any(
            k.band != p.band
            and abs(((p.position_s - k.position_s) + 0.5) % 1.0 - 0.5) * 1000.0
            <= agree_ms
            for k in kept
        )
        if not clash:
            kept.append(p)
    return kept
