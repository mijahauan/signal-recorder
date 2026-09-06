# T3 Self-Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The metrology finds the second boundary in the received WWV/WWVH tick train itself, holds that origin on the GPSDO-locked RTP counter, corroborates or corrects it every minute, and publishes it — so T3 stands without radiod's non-atomic pair or any higher tier.

**Architecture:** A new pure module `core/registration_acquirer.py` folds the band-limited envelope at one second, fits the peak set to the engine's expected station delays by a common shift, and produces a `Registration` held in the RTP frame (`rtp_ref`, `utc_ref`). A new `core/registration_store.py` writes one JSON per channel under `/run/hf-timestd/registration/` and fuses siblings inverse-variance (metrology runs one process per channel, so the per-radiod fusion crosses processes through the file system). `metrology_service.py` applies the fused registration to `BufferTiming` before `process_minute`, feeds the minute's ensembles back, and re-acquires on a counter-epoch change. `tick_edge_detector.py` labels acquired-plane ensembles `anchor_source="acquired"` and admits them to timing once the registration σ is under 2 ms. The Offset Judge gains an `HfAcquiredBench` that reads the fused registration and compares it with the raw radiod pair, host-clock free.

**Tech Stack:** Python ≥3.10, numpy, scipy.signal (`butter`, `sosfiltfilt`, `hilbert`), dataclasses, json, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-t3-self-registration-design.md` (54730fc). The spec binds; this plan argues from it.

## Global Constraints

- **No station runs anything from this plan until Task 12.** All tests run on the devbox (`/home/mjh/hamsci/repos/hf-timestd`, venv `.venv`). The replay fixture lives at `/home/mjh/hamsci/fixtures/nd-20260906/1788729000.{bin.zst,json}` (ND SHARED_10000, 2026-09-06 21:20–21:30Z, 102 MB, outside the repo). Replay tests `pytest.skip` when the fixture is absent.
- **Timing-authority invariant** (`CLAUDE.md`): no new `time.time()`, `datetime.now()`, or `chronyc tracking` in the timing path. The acquirer takes UTC only from `BufferTiming` and the signal. `time.time()` may stamp provenance JSON (`written_at`) only.
- **Sign convention (pinned):** `correction_s = expected_delay_s − fold_position_s`, wrapped into `(−0.5, 0.5]`; `sample0_utc_acquired = sample0_utc_label + correction_s`. Test: label `T + w` (label late by `w`) ⇒ tick appears at `d + w` in the label frame ⇒ correction `−w` ⇒ acquired plane `T`.
- **Constants (verbatim from the spec):** `ACQ_MIN_FOLD_SNR_DB = 10.0`; fold lengths 60, 120, 180 s; tone bands 900–1100 Hz (WWV, BPM) and 1100–1300 Hz (WWVH); outlier rejection at 3 ms from the median in per-radiod fusion; correct (re-acquire) when the residual exceeds 3 σ for 2 consecutive minutes on ≥ 2 channels; `timing_admissible` accepts `anchor_source="acquired"` when the registration σ < 2.0 ms; origin σ floored at 1.0 ms.
- **Skip seconds:** the fold excludes label seconds-in-minute `{59, 0, 1, 28, 29, 30}` (the spec's 0/29/59 widened by ±1 s because the label can be up to ~0.7 s wrong before acquisition).
- **BufferTiming is a frozen dataclass**; use `dataclasses.replace`. New fields default so every existing constructor call still works: `origin_source: str = "label"`, `origin_sigma_ms: float = float("inf")`, `counter_epoch_id: str = "unregistered"`.
- **One class per file, filename matches class**; type hints; `UPPER_SNAKE_CASE` constants; black/flake8 clean.
- Tests live under `tests/unit/`; run with `.venv/bin/pytest <path> --override-ini addopts=-ra -v` (the project's addopts already carry `-q`; the override restores the summary line).
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH
  ```
- Develop on `main` (repo convention); no feature branch. Do not push; the controller pushes.

---

## File map

| File | Role |
|---|---|
| `src/hf_timestd/core/registration_acquirer.py` (new) | `FoldPeak`, `Hypothesis`, `Registration`, `fold_tick_train`, `find_fold_peaks`, `fit_template`, `locate_minute_marker`, `RegistrationAcquirer` (state machine: BOOTSTRAP → ACQUIRED, corroborate/correct) |
| `src/hf_timestd/core/registration_store.py` (new) | `RegistrationStore`: per-channel JSON write, sibling read, `fuse_registrations`, summary `registration.json` |
| `src/hf_timestd/core/counter_epoch_tracker.py` (new) | `CounterEpochTracker`: mirrors `binary_archive_writer._note_counter_epoch` for the live ring path |
| `src/hf_timestd/core/buffer_timing.py` (mod) | three new defaulted fields |
| `src/hf_timestd/core/tick_edge_detector.py` (mod) | `anchor_source="acquired"`, `anchor_sigma_ms` on `EdgeEnsembleResult`, `timing_admissible` rule |
| `src/hf_timestd/core/metrology_service.py` (mod) | wire acquirer + store + tracker into the minute loop |
| `src/hf_timestd/core/offset_judge.py` (mod) | `HfAcquiredBench` |
| `src/hf_timestd/core/core_recorder_v2.py` (mod) | wire the bench |
| `src/hf_timestd/core/authority_manager.py` (mod) | `registration` block in authority.json |
| `tests/unit/test_registration_acquirer_fold.py`, `test_registration_acquirer_fit.py`, `test_registration_acquirer_marker.py`, `test_registration_acquirer_state.py`, `test_registration_store.py`, `test_counter_epoch_tracker.py`, `test_tick_edge_acquired_anchor.py`, `test_metrology_service_registration.py`, `test_offset_judge_hf_acquired.py`, `test_replay_nd_acquisition.py` | tests |
| `docs/METROLOGY.md` (mod) | §4.5 paragraph on self-registration |

Shared synthetic-signal helper: `tests/unit/synth_ticks.py` (Task 1) — every later test imports from it. Keep it a plain module (no `conftest` magic) so tests can be read alone.

---

### Task 1: Synthetic tick-train helper and BufferTiming fields

**Files:**
- Create: `tests/unit/synth_ticks.py`
- Modify: `src/hf_timestd/core/buffer_timing.py:95-140` (dataclass fields)
- Test: `tests/unit/test_buffer_timing_origin_fields.py`

**Interfaces:**
- Produces: `synth_ticks.make_tick_audio(n_seconds: int, sample_rate: int, true_sample0_utc: float, stations: dict[str, float], snr_db: float, seed: int = 7, marker: bool = True) -> np.ndarray` — real float64 "audio" (the envelope the engine hands the detector), with a 5 ms tick per second for each station at `utc_sec + delay_s` (tick tone 1000 Hz for WWV/BPM, 1200 Hz for WWVH; skipping seconds 29 and 59; an 800 ms marker at second 0 when `marker=True`), plus white noise scaled so that the per-tick amplitude-to-noise-σ ratio is `snr_db` (`20·log10`).
- Produces: `synth_ticks.label_timing(true_sample0_utc: float, walk_s: float, sample_rate: int) -> BufferTiming` with `source="rtp_gps"`.
- Produces: `BufferTiming.origin_source: str = "label"`, `BufferTiming.origin_sigma_ms: float = inf`, `BufferTiming.counter_epoch_id: str = "unregistered"`.

- [ ] **Step 1: Write the failing test for the new fields**

```python
# tests/unit/test_buffer_timing_origin_fields.py
import dataclasses
import math

from hf_timestd.core.buffer_timing import BufferTiming


def _bt(**kw):
    base = dict(sample0_utc=1_800_000_000.0, sample_rate=24000, source="rtp_gps",
                n_snapshots_used=1, jitter_ms=0.0)
    base.update(kw)
    return BufferTiming(**base)


def test_defaults_keep_existing_constructors_working():
    bt = _bt()
    assert bt.origin_source == "label"
    assert math.isinf(bt.origin_sigma_ms)
    assert bt.counter_epoch_id == "unregistered"


def test_replace_sets_acquired_origin():
    bt = dataclasses.replace(_bt(), sample0_utc=1_800_000_000.25,
                             origin_source="acquired", origin_sigma_ms=0.8,
                             counter_epoch_id="ep-1")
    assert bt.origin_source == "acquired"
    assert bt.origin_sigma_ms == 0.8
    assert bt.sample_to_utc(24000) == 1_800_000_001.25
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_buffer_timing_origin_fields.py --override-ini addopts=-ra -v`
Expected: FAIL with `AttributeError: 'BufferTiming' object has no attribute 'origin_source'` (or `TypeError: unexpected keyword argument`).

- [ ] **Step 3: Add the fields**

In `src/hf_timestd/core/buffer_timing.py`, after the last existing field of the `BufferTiming` dataclass (`offset_sigma_ns: float = 0.0`), add:

```python
    # ── Origin provenance (T3 self-registration, spec 2026-09-06) ──
    # Where sample0_utc's ORIGIN came from.  'label' = radiod's
    # (GPS_TIME, RTP_TIMESNAP) pair as adopted by the ring anchor;
    # 'acquired' = the received tick train placed the second boundary
    # (core/registration_acquirer.py).  The RATE is always the GPSDO's.
    origin_source: str = "label"
    # 1-sigma of the origin in ms.  inf for a label plane: radiod's pair
    # is not atomic and its skew was measured at 232 ms (ND) / 701 ms
    # (B4) on 2026-09-06, so the label carries no honest sigma.
    origin_sigma_ms: float = float("inf")
    # Counter epoch the origin belongs to (see CounterEpochTracker).  The
    # acquired origin is constant in RTP within one epoch and must be
    # discarded when the epoch changes.
    counter_epoch_id: str = "unregistered"
```

- [ ] **Step 4: Run the test and the existing buffer_timing tests**

Run: `.venv/bin/pytest tests/unit/test_buffer_timing_origin_fields.py tests/unit -k buffer_timing --override-ini addopts=-ra -v`
Expected: PASS.

- [ ] **Step 5: Write the synthetic helper**

```python
# tests/unit/synth_ticks.py
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


def make_tick_audio(n_seconds: int, sample_rate: int, true_sample0_utc: float,
                    stations: dict, snr_db: float, seed: int = 7,
                    marker: bool = True) -> np.ndarray:
    """``stations`` maps station name -> propagation delay in seconds."""
    rng = np.random.default_rng(seed)
    n = int(n_seconds * sample_rate)
    noise_std = 10.0 ** (-snr_db / 20.0)        # tick amplitude is 1.0
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


def label_timing(true_sample0_utc: float, walk_s: float,
                 sample_rate: int) -> BufferTiming:
    """The label plane: sample0_utc off truth by walk_s (positive = label late)."""
    return BufferTiming(sample0_utc=true_sample0_utc + walk_s,
                        sample_rate=sample_rate, source="rtp_gps",
                        n_snapshots_used=1, jitter_ms=0.0)
```

- [ ] **Step 6: Smoke-test the helper**

Append to `tests/unit/test_buffer_timing_origin_fields.py`:

```python
import numpy as np
from tests.unit.synth_ticks import make_tick_audio, label_timing


def test_synth_helper_places_a_tick_where_truth_says():
    sr = 24000
    t0 = 1_800_000_000.0 - 1.0
    audio = make_tick_audio(3, sr, t0, {"WWV": 0.010}, snr_db=40.0, marker=False)
    # second 1_800_000_000 is second 0 of a minute -> no tick (marker=False);
    # second 1_800_000_001 tick starts 2.010 s into the buffer.
    i0 = int(round(2.010 * sr))
    assert np.abs(audio[i0:i0 + 120]).max() > 0.5
    assert np.abs(audio[i0 - 600:i0 - 120]).max() < 0.2
    assert label_timing(t0, 0.3, sr).sample0_utc == t0 + 0.3
```

If `from tests.unit.synth_ticks import ...` fails to import, add an empty `tests/unit/__init__.py` and `tests/__init__.py` only if they do not exist; otherwise use `from synth_ticks import ...` with `tests/unit` on `sys.path` via the existing `conftest.py` pattern — check `ls tests/unit/__init__.py tests/__init__.py` first and match what is there.

Run: `.venv/bin/pytest tests/unit/test_buffer_timing_origin_fields.py --override-ini addopts=-ra -v`
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hf_timestd/core/buffer_timing.py tests/unit/synth_ticks.py tests/unit/test_buffer_timing_origin_fields.py
git commit -m "feat(timing): BufferTiming carries origin provenance; synthetic tick-train helper

Spec: docs/superpowers/specs/2026-09-06-t3-self-registration-design.md §3.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 2: Fold the tick train at one second and find peaks

**Files:**
- Create: `src/hf_timestd/core/registration_acquirer.py` (first part: constants, `FoldPeak`, `fold_tick_train`, `find_fold_peaks`)
- Test: `tests/unit/test_registration_acquirer_fold.py`

**Interfaces:**
- Produces:
  ```python
  ACQ_MIN_FOLD_SNR_DB = 10.0
  FOLD_LENGTHS_S = (60, 120, 180)
  TONE_BANDS_HZ = {"1000": (900.0, 1100.0), "1200": (1100.0, 1300.0)}
  BAND_OF_STATION = {"WWV": "1000", "BPM": "1000", "WWVH": "1200"}
  FOLD_SKIP_SECONDS = frozenset({59, 0, 1, 28, 29, 30})

  @dataclass(frozen=True)
  class FoldPeak:
      band: str            # "1000" | "1200"
      position_s: float    # onset position within the label second, [0, 1)
      snr_db: float
      width_ms: float

  def fold_tick_train(audio: np.ndarray, sample_rate: int, sample0_utc_label: float,
                      band: str, n_seconds: int) -> tuple[np.ndarray, int]
      # returns (profile of length sample_rate, n_rows_folded)
  def find_fold_peaks(profile: np.ndarray, sample_rate: int, band: str,
                      min_snr_db: float = ACQ_MIN_FOLD_SNR_DB) -> list[FoldPeak]
  BAND_ARBITRATION_MS = 6.0
  def arbitrate_bands(peaks_by_band: dict[str, list[FoldPeak]],
                      agree_ms: float = BAND_ARBITRATION_MS) -> list[FoldPeak]
      # a 5 ms tick's ~200 Hz main lobe leaks into the neighbouring band; when two bands
      # show a peak at the same position (within agree_ms), keep only the stronger one
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_registration_acquirer_fold.py
import numpy as np
import pytest

from hf_timestd.core.registration_acquirer import (
    ACQ_MIN_FOLD_SNR_DB, FoldPeak, arbitrate_bands, find_fold_peaks, fold_tick_train,
)
from tests.unit.synth_ticks import make_tick_audio

SR = 24000
MIN = 1_800_000_000          # a minute boundary
T0 = MIN - 1.0               # truth: buffer starts 1 s before the minute


def _peaks(walk_s, snr_db, stations, n_seconds=60, band="1000"):
    audio = make_tick_audio(n_seconds + 2, SR, T0, stations, snr_db=snr_db)
    profile, n_rows = fold_tick_train(audio, SR, T0 + walk_s, band, n_seconds)
    assert len(profile) == SR
    assert n_rows >= n_seconds - 8          # skip set removes ≤ 6 of 60, edges ≤ 2
    return find_fold_peaks(profile, SR, band)


@pytest.mark.parametrize("snr_db", [30.0, 15.0, 5.0])
def test_wwv_tick_appears_at_delay_plus_walk(snr_db):
    peaks = _peaks(walk_s=0.250, snr_db=snr_db, stations={"WWV": 0.0125})
    assert peaks, "the fold must show the tick at 5 dB per tick (60 s fold gains ~17 dB)"
    best = max(peaks, key=lambda p: p.snr_db)
    assert best.band == "1000"
    assert abs(best.position_s - (0.0125 + 0.250)) < 0.002
    assert best.snr_db >= ACQ_MIN_FOLD_SNR_DB


def test_position_wraps_inside_the_second():
    peaks = _peaks(walk_s=-0.300, snr_db=20.0, stations={"WWV": 0.010})
    best = max(peaks, key=lambda p: p.snr_db)
    assert abs(best.position_s - ((0.010 - 0.300) % 1.0)) < 0.002


def test_wwvh_lands_in_the_1200_band_after_arbitration():
    # A 5 ms tick has a ~200 Hz sinc main lobe, so a 1200 Hz tick LEAKS into
    # the 900-1100 band; no filter separates them.  The tone identity comes
    # from comparing the two bands at the same fold position: the band that
    # matches the tone responds more strongly.
    audio = make_tick_audio(62, SR, T0, {"WWVH": 0.018}, snr_db=20.0)
    p1000, _ = fold_tick_train(audio, SR, T0, "1000", 60)
    p1200, _ = fold_tick_train(audio, SR, T0, "1200", 60)
    peaks = arbitrate_bands({"1000": find_fold_peaks(p1000, SR, "1000"),
                             "1200": find_fold_peaks(p1200, SR, "1200")})
    assert len(peaks) == 1 and peaks[0].band == "1200"
    assert abs(peaks[0].position_s - 0.018) < 0.002


def test_arbitration_keeps_distinct_positions_in_both_bands():
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.010, "WWVH": 0.028}, snr_db=20.0)
    p1000, _ = fold_tick_train(audio, SR, T0, "1000", 60)
    p1200, _ = fold_tick_train(audio, SR, T0, "1200", 60)
    peaks = arbitrate_bands({"1000": find_fold_peaks(p1000, SR, "1000"),
                             "1200": find_fold_peaks(p1200, SR, "1200")})
    by_band = {p.band: p.position_s for p in peaks}
    assert abs(by_band["1000"] - 0.010) < 0.002 and abs(by_band["1200"] - 0.028) < 0.002


def test_noise_alone_yields_no_peak():
    rng = np.random.default_rng(1)
    audio = 0.1 * rng.standard_normal(62 * SR)
    profile, _ = fold_tick_train(audio, SR, T0, "1000", 60)
    assert find_fold_peaks(profile, SR, "1000") == []


def test_two_stations_two_peaks():
    peaks = _peaks(walk_s=0.0, snr_db=20.0, stations={"WWV": 0.010, "BPM": 0.044})
    pos = sorted(p.position_s for p in peaks)
    assert len(pos) == 2
    assert abs(pos[0] - 0.010) < 0.002 and abs(pos[1] - 0.044) < 0.002
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_fold.py --override-ini addopts=-ra -v`
Expected: FAIL with `ModuleNotFoundError: hf_timestd.core.registration_acquirer`.

- [ ] **Step 3: Implement the fold and peak finder**

```python
# src/hf_timestd/core/registration_acquirer.py
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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import butter, sosfiltfilt

logger = logging.getLogger(__name__)

ACQ_MIN_FOLD_SNR_DB = 10.0
FOLD_LENGTHS_S = (60, 120, 180)
TONE_BANDS_HZ: Dict[str, Tuple[float, float]] = {
    "1000": (900.0, 1100.0),     # WWV and BPM ticks
    "1200": (1100.0, 1300.0),    # WWVH ticks
}
BAND_OF_STATION: Dict[str, str] = {"WWV": "1000", "BPM": "1000", "WWVH": "1200"}
# Label seconds-in-minute excluded from the fold: 0 (marker), 29/59 (no
# tick), each widened by ±1 s because the label may be ~0.7 s wrong.
FOLD_SKIP_SECONDS = frozenset({59, 0, 1, 28, 29, 30})
# Fold-peak geometry: a 5 ms tick through a 200 Hz band is a ~10 ms bump.
PEAK_MIN_SEPARATION_MS = 8.0
PEAK_MAX_WIDTH_MS = 25.0
ENVELOPE_LPF_HZ = 400.0
ORIGIN_SIGMA_FLOOR_MS = 1.0


@dataclass(frozen=True)
class FoldPeak:
    band: str
    position_s: float      # onset (half-rise) position within the label second
    snr_db: float
    width_ms: float


def _band_envelope(audio: np.ndarray, sample_rate: int, band: str) -> np.ndarray:
    lo, hi = TONE_BANDS_HZ[band]
    sos = butter(4, [lo, hi], btype="bandpass", fs=sample_rate, output="sos")
    x = sosfiltfilt(sos, np.asarray(audio, dtype=np.float64))
    env = np.abs(x)
    sos_lp = butter(2, ENVELOPE_LPF_HZ, btype="lowpass", fs=sample_rate, output="sos")
    return sosfiltfilt(sos_lp, env)


def fold_tick_train(audio: np.ndarray, sample_rate: int, sample0_utc_label: float,
                    band: str, n_seconds: int) -> Tuple[np.ndarray, int]:
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


def find_fold_peaks(profile: np.ndarray, sample_rate: int, band: str,
                    min_snr_db: float = ACQ_MIN_FOLD_SNR_DB) -> List[FoldPeak]:
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
    order = np.argsort(dev)[::-1]
    taken = np.zeros_like(dev, dtype=bool)
    peaks: List[FoldPeak] = []
    for idx in order:
        if dev[idx] < thr:
            break
        if taken[max(0, idx - sep):idx + sep + 1].any():
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
        width_ms = (steps + steps2) * 1000.0 / sample_rate
        if width_ms > PEAK_MAX_WIDTH_MS:
            continue                      # a plateau, not a tick
        taken[max(0, idx - max_w):idx + max_w + 1] = True
        peaks.append(FoldPeak(band=band, position_s=onset / sample_rate,
                              snr_db=float(20 * np.log10(dev[idx] / mad)),
                              width_ms=width_ms))
    peaks.sort(key=lambda p: -p.snr_db)
    return peaks


BAND_ARBITRATION_MS = 6.0


def arbitrate_bands(peaks_by_band: Dict[str, List[FoldPeak]],
                    agree_ms: float = BAND_ARBITRATION_MS) -> List[FoldPeak]:
    """Assign each fold position to ONE tone band.  A 5 ms tick has a sinc
    main lobe ~200 Hz wide, so a 1200 Hz tick leaks into 900-1100 Hz and a
    1000 Hz tick into 1100-1300 Hz; no filter separates them.  The band
    whose centre matches the tone responds more strongly, so when two
    bands carry a peak at the same position the weaker one is the leak."""
    allp = [p for ps in peaks_by_band.values() for p in ps]
    allp.sort(key=lambda p: -p.snr_db)
    kept: List[FoldPeak] = []
    for p in allp:
        clash = any(k.band != p.band
                    and abs(((p.position_s - k.position_s) + 0.5) % 1.0 - 0.5) * 1000.0 <= agree_ms
                    for k in kept)
        if not clash:
            kept.append(p)
    return kept
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_fold.py --override-ini addopts=-ra -v`
Expected: all PASS. Note on the synthetic SNR: `make_tick_audio` defines `snr_db` against the full 12 kHz noise band; the 200 Hz tone bandpass adds ≈ 17.8 dB, and the 54-row fold another ≈ 17 dB, so the "5 dB" case sits near 40 dB in the fold. If the 5 dB case fails, the culprit is the position tolerance, not the threshold: loosen only that case to `< 0.003`. If the noise-only test finds a peak, the `noise_extreme` term is wrong — print `mad`, `dev.max()/mad` and `n_eff` and fix the term; never lower `ACQ_MIN_FOLD_SNR_DB`.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/core/registration_acquirer.py tests/unit/test_registration_acquirer_fold.py
git commit -m "feat(timing): one-second fold of the tick train with robust peak finding

Spec §4.1-4.3.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 3: Template fit — peaks to station delays by a common shift

**Files:**
- Modify: `src/hf_timestd/core/registration_acquirer.py` (append `Hypothesis`, `wrap_half_second`, `fit_template`)
- Test: `tests/unit/test_registration_acquirer_fit.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Hypothesis:
      correction_s: float                 # add to the label plane
      sigma_ms: float
      assignments: tuple                  # ((station, band, position_s, snr_db), ...)
      support: int                        # number of peaks explaining it
      unambiguous: bool

  def wrap_half_second(x_s: float) -> float        # into (-0.5, 0.5]
  def fit_template(peaks: list[FoldPeak], expected_delays_s: dict[str, float],
                   agree_ms: float = 3.0) -> list[Hypothesis]
      # sorted best first; [] when no peak matches any eligible station
  ```
- Rule: a hypothesis is `unambiguous` when `support >= 2`, or when exactly one eligible station is compatible with the peak's band (single-station channel). Otherwise each compatible (peak, station) pairing is its own ambiguous hypothesis.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_registration_acquirer_fit.py
import pytest

from hf_timestd.core.registration_acquirer import (
    FoldPeak, fit_template, wrap_half_second,
)


def _pk(band, pos, snr=20.0):
    return FoldPeak(band=band, position_s=pos % 1.0, snr_db=snr, width_ms=10.0)


def test_wrap():
    assert wrap_half_second(0.7) == pytest.approx(-0.3)
    assert wrap_half_second(-0.6) == pytest.approx(0.4)
    assert wrap_half_second(0.5) == pytest.approx(0.5)


def test_single_station_channel_is_unambiguous():
    # WWV 20 MHz: only WWV is eligible; label late by 0.250 -> peak at d + 0.250
    hyps = fit_template([_pk("1000", 0.0125 + 0.250)], {"WWV": 0.0125})
    assert len(hyps) == 1
    h = hyps[0]
    assert h.unambiguous and h.support == 1
    assert h.correction_s == pytest.approx(-0.250, abs=1e-6)
    assert h.assignments[0][0] == "WWV"


def test_two_peaks_resolve_shared_channel():
    d = {"WWV": 0.010, "WWVH": 0.028, "BPM": 0.044}
    walk = -0.300                       # label EARLY: ticks appear at d + walk (wraps to 0.71x)
    peaks = [_pk("1000", 0.010 + walk), _pk("1200", 0.028 + walk, snr=14.0)]
    hyps = fit_template(peaks, d)
    assert hyps[0].unambiguous and hyps[0].support == 2
    assert hyps[0].correction_s == pytest.approx(0.300, abs=1e-6)
    stations = {a[0] for a in hyps[0].assignments}
    assert stations == {"WWV", "WWVH"}


def test_one_peak_on_shared_channel_carries_both_hypotheses():
    d = {"WWV": 0.010, "WWVH": 0.028}
    hyps = fit_template([_pk("1000", 0.010 + 0.1)], d)
    # band 1000 excludes WWVH; only WWV compatible -> unambiguous after all
    assert len(hyps) == 1 and hyps[0].unambiguous
    # band-ambiguous case: WWV and BPM share 1000 Hz
    d2 = {"WWV": 0.010, "BPM": 0.044}
    hyps2 = fit_template([_pk("1000", 0.010 + 0.1)], d2)
    assert len(hyps2) == 2 and not any(h.unambiguous for h in hyps2)
    corr = sorted(h.correction_s for h in hyps2)
    assert corr[0] == pytest.approx(-0.100, abs=1e-6)   # if it were WWV  (0.010 - 0.110)
    assert corr[1] == pytest.approx(-0.066, abs=1e-6)   # if it were BPM  (0.044 - 0.110)


def test_bpm_wwv_collision_resolved_by_34ms_separation():
    d = {"WWV": 0.010, "BPM": 0.044}
    peaks = [_pk("1000", 0.010 + 0.05), _pk("1000", 0.044 + 0.05, snr=12.0)]
    hyps = fit_template(peaks, d)
    assert hyps[0].unambiguous and hyps[0].support == 2
    assert hyps[0].correction_s == pytest.approx(-0.050, abs=1e-6)


def test_peak_in_wrong_band_matches_nothing():
    assert fit_template([_pk("1200", 0.1)], {"WWV": 0.010}) == []


def test_sigma_from_snr_and_floor():
    h = fit_template([_pk("1000", 0.2, snr=40.0)], {"WWV": 0.010})[0]
    assert h.sigma_ms >= 1.0
    h2 = fit_template([_pk("1000", 0.2, snr=10.0)], {"WWV": 0.010})[0]
    assert h2.sigma_ms > h.sigma_ms
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_fit.py --override-ini addopts=-ra -v`
Expected: FAIL with `ImportError: cannot import name 'fit_template'`.

- [ ] **Step 3: Implement**

Append to `registration_acquirer.py`:

```python
@dataclass(frozen=True)
class Hypothesis:
    correction_s: float
    sigma_ms: float
    assignments: tuple          # ((station, band, position_s, snr_db), ...)
    support: int
    unambiguous: bool


def wrap_half_second(x_s: float) -> float:
    """Wrap into (-0.5, 0.5]."""
    y = (x_s + 0.5) % 1.0 - 0.5
    return 0.5 if y == -0.5 else y


def _sigma_ms_from_snr(snr_db: float) -> float:
    # Tick rise through a 200 Hz band ~5 ms; timing sigma ≈ rise / (S/N).
    rise_ms = 5.0
    return max(ORIGIN_SIGMA_FLOOR_MS, rise_ms / (10 ** (snr_db / 20.0)) * 3.0)


def fit_template(peaks: List[FoldPeak], expected_delays_s: Dict[str, float],
                 agree_ms: float = 3.0) -> List[Hypothesis]:
    """Fit the peak set to the station delay template by a common shift.

    Every (peak, station) pairing whose tone bands agree proposes a
    correction; pairings whose corrections agree within ``agree_ms`` form
    one hypothesis with support = number of peaks.  A hypothesis is
    unambiguous with support >= 2 or when the peak's band admits exactly
    one eligible station."""
    pairings = []
    for p in peaks:
        compatible = [s for s in expected_delays_s if BAND_OF_STATION.get(s) == p.band]
        for s in compatible:
            corr = wrap_half_second(expected_delays_s[s] - p.position_s)
            pairings.append((corr, s, p, len(compatible)))
    if not pairings:
        return []
    pairings.sort(key=lambda x: x[0])
    used = [False] * len(pairings)
    hyps: List[Hypothesis] = []
    for i, (corr_i, _, _, _) in enumerate(pairings):
        if used[i]:
            continue
        group = []
        seen_peaks = set()
        for j, (corr_j, s_j, p_j, n_comp) in enumerate(pairings):
            if used[j] or id(p_j) in seen_peaks:
                continue
            if abs(wrap_half_second(corr_j - corr_i)) * 1000.0 <= agree_ms:
                group.append(j)
                seen_peaks.add(id(p_j))
        for j in group:
            used[j] = True
        members = [pairings[j] for j in group]
        w = np.array([10 ** (m[2].snr_db / 10.0) for m in members])
        corr = float(np.sum(w * np.array([m[0] for m in members])) / np.sum(w))
        sig = float(min(_sigma_ms_from_snr(m[2].snr_db) for m in members)
                    / np.sqrt(len(members)))
        support = len(members)
        unamb = support >= 2 or (support == 1 and members[0][3] == 1)
        hyps.append(Hypothesis(
            correction_s=wrap_half_second(corr),
            sigma_ms=max(ORIGIN_SIGMA_FLOOR_MS, sig),
            assignments=tuple((m[1], m[2].band, m[2].position_s, m[2].snr_db)
                              for m in members),
            support=support, unambiguous=unamb))
    hyps.sort(key=lambda h: (-h.support, -sum(a[3] for a in h.assignments)))
    return hyps
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_fit.py tests/unit/test_registration_acquirer_fold.py --override-ini addopts=-ra -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/core/registration_acquirer.py tests/unit/test_registration_acquirer_fit.py
git commit -m "feat(timing): template fit of fold peaks to station delays by a common shift

Spec §4.4-4.5: two peaks disambiguate WWV/WWVH (18 ms) and WWV/BPM (34 ms);
a single peak on a shared channel carries every compatible hypothesis.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 4: Minute marker resolves the integer second

**Files:**
- Modify: `src/hf_timestd/core/registration_acquirer.py` (append `locate_minute_marker`, `integer_second_correction`)
- Test: `tests/unit/test_registration_acquirer_marker.py`

**Interfaces:**
- Produces:
  ```python
  MARKER_SEARCH_HALF_S = 1.5
  def locate_minute_marker(audio: np.ndarray, sample_rate: int, sample0_utc_label: float,
                           band: str, minute_utc: int) -> Optional[tuple[float, float]]
      # -> (marker_onset_s_in_label_frame_relative_to_minute_utc, snr_db) or None
  def integer_second_correction(marker_offset_s: float, expected_delay_s: float,
                                fractional_correction_s: float) -> int
  ```
- The fold gives the correction modulo one second. radiod's pair skew was measured up to 0.7 s, so the label can be a whole second off. The 800 ms marker at second 0, located within ±1.5 s of where the label puts it, names the integer.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_registration_acquirer_marker.py
import pytest

from hf_timestd.core.registration_acquirer import (
    integer_second_correction, locate_minute_marker,
)
from tests.unit.synth_ticks import make_tick_audio

SR = 24000
MIN = 1_800_000_000
T0 = MIN - 4.0        # 10 s buffer: the ±1.5 s marker search must fit for walks up to ±1.2 s


@pytest.mark.parametrize("walk_s", [0.0, 0.4, -0.7, 1.2])
def test_marker_found_where_truth_put_it(walk_s):
    audio = make_tick_audio(10, SR, T0, {"WWV": 0.012}, snr_db=15.0)
    res = locate_minute_marker(audio, SR, T0 + walk_s, "1000", MIN)
    assert res is not None
    offset_s, snr = res
    # in the label frame the marker onset sits at d + walk after the minute
    assert offset_s == pytest.approx(0.012 + walk_s, abs=0.005)
    assert snr > 6.0


def test_no_marker_returns_none():
    audio = make_tick_audio(10, SR, T0, {"WWV": 0.012}, snr_db=15.0, marker=False)
    assert locate_minute_marker(audio, SR, T0, "1000", MIN) is None


@pytest.mark.parametrize("walk_s,frac,expected", [
    (0.4, -0.4, 0),       # label 0.4 s late: total correction -0.4, fold says -0.4, no whole second
    (1.2, -0.2, -1),      # label 1.2 s late: total -1.2, fold wraps to -0.2, marker adds -1
    (-0.7, -0.3, 1),      # label 0.7 s early: total +0.7, fold wraps to -0.3, marker adds +1
])
def test_integer_second_from_marker(walk_s, frac, expected):
    # the fold only ever reports (-0.5, 0.5]; the marker supplies the rest
    # marker_offset = d + walk ; total correction = -walk ; integer = round(-walk - frac)
    d = 0.012
    assert integer_second_correction(d + walk_s, d, frac) == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_marker.py --override-ini addopts=-ra -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Append to `registration_acquirer.py`:

```python
MARKER_SEARCH_HALF_S = 1.5
MARKER_LEN_S = 0.800
MARKER_MIN_SNR_DB = 6.0


def locate_minute_marker(audio: np.ndarray, sample_rate: int, sample0_utc_label: float,
                         band: str, minute_utc: int) -> Optional[Tuple[float, float]]:
    """Find the 800 ms marker near where the label puts second 0 of
    ``minute_utc``.  Correlates a boxcar of MARKER_LEN_S with the band
    envelope over ±MARKER_SEARCH_HALF_S.  Returns (onset offset from the
    label's minute_utc in seconds, SNR dB) or None."""
    env = _band_envelope(audio, sample_rate, band)
    centre = int(round((minute_utc - sample0_utc_label) * sample_rate))
    half = int(MARKER_SEARCH_HALF_S * sample_rate)
    L = int(MARKER_LEN_S * sample_rate)
    a = centre - half
    b = centre + half + L
    if a < 0 or b > len(env):
        return None
    seg = env[a:b]
    csum = np.concatenate(([0.0], np.cumsum(seg)))
    score = (csum[L:] - csum[:-L]) / L          # mean over each 800 ms window
    k = int(np.argmax(score))
    baseline = np.median(score)
    mad = np.median(np.abs(score - baseline)) * 1.4826
    if mad <= 0:
        return None
    snr_db = float(20 * np.log10((score[k] - baseline) / mad))
    if snr_db < MARKER_MIN_SNR_DB:
        return None
    # refine to the half-rise onset of the envelope inside the window
    win = seg[k:k + L]
    thr = baseline + 0.5 * (np.max(win) - baseline)
    rise = int(np.argmax(win > thr))
    onset_sample = a + k + rise
    return (onset_sample / sample_rate) - (minute_utc - sample0_utc_label), snr_db


def integer_second_correction(marker_offset_s: float, expected_delay_s: float,
                              fractional_correction_s: float) -> int:
    """Whole seconds to add to the label plane on top of the fold's
    fractional correction.  The marker appears at ``expected_delay + walk``
    in the label frame, so the total correction is ``expected_delay −
    marker_offset``; the fold already supplied its fractional part."""
    total = expected_delay_s - marker_offset_s
    return int(round(total - fractional_correction_s))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_marker.py --override-ini addopts=-ra -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/core/registration_acquirer.py tests/unit/test_registration_acquirer_marker.py
git commit -m "feat(timing): minute marker names the integer second under the fold's fraction

Spec §10 (whole-second ambiguity row).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 5: RegistrationAcquirer state machine (acquire, hold, corroborate, correct)

**Files:**
- Modify: `src/hf_timestd/core/registration_acquirer.py` (append `Registration`, `RegistrationAcquirer`)
- Test: `tests/unit/test_registration_acquirer_state.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Registration:
      counter_epoch_id: str
      rtp_ref: int              # RTP counter value of a reference sample
      utc_ref: float            # acquired UTC of that sample
      sample_rate: int
      sigma_ms: float
      method: str = "fold+template"
      n_minutes: int = 0        # minutes corroborated since acquisition
      channel: str = ""
      hypotheses_open: int = 0
      def sample0_utc_for(self, start_rtp: int) -> float

  class RegistrationAcquirer:
      STATE_BOOTSTRAP = "BOOTSTRAP"; STATE_ACQUIRED = "ACQUIRED"
      CORRECT_K_SIGMA = 3.0; CORRECT_MINUTES = 2; FILTER_MEMORY_MINUTES = 30
      def __init__(self, channel: str, sample_rate: int): ...
      @property
      def state(self) -> str
      @property
      def registration(self) -> Optional[Registration]
      def offer_minute(self, audio: np.ndarray, label: BufferTiming, start_rtp: int,
                       minute_utc: int, expected_delays_s: dict[str, float],
                       counter_epoch_id: str) -> Optional[Registration]
          # BOOTSTRAP: accumulate up to 180 s and try to acquire; ACQUIRED: return held registration
      def corroborate(self, residuals_ms: dict[str, tuple[float, float]]) -> str
          # {station: (ensemble_timing_error_ms, sigma_single_ms)} for tick-like ensembles
          # against the ACQUIRED plane; returns "held" | "tightened" | "reacquire"
      def adopt(self, reg: Registration) -> None      # take a sibling's fused registration
      def reset(self, why: str) -> None
  ```
- The `audio` offered is the same `envelope − mean` the engine computes (`metrology_engine.py:1437`); the service computes it once (Task 8) and hands it to both.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_registration_acquirer_state.py
import numpy as np
import pytest

from hf_timestd.core.registration_acquirer import (
    Registration, RegistrationAcquirer,
)
from tests.unit.synth_ticks import make_tick_audio, label_timing

SR = 24000
MIN = 1_800_000_000
T0 = MIN - 1.0                     # buffer 0 starts 1 s before minute 0 (truth)
D = {"WWV": 0.0125}


def _minute(k, walk_s, snr_db=15.0, stations=D):
    """Minute k: 62 s buffer starting at T0 + 60k (truth)."""
    t0 = T0 + 60 * k
    audio = make_tick_audio(62, SR, t0, stations, snr_db=snr_db, seed=7 + k)
    label = label_timing(t0, walk_s, SR)
    start_rtp = 1_000_000 + k * 60 * SR
    return audio, label, start_rtp, MIN + 60 * k


def test_bootstrap_then_acquires_within_one_minute_at_good_snr():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    assert acq.state == acq.STATE_BOOTSTRAP
    audio, label, rtp, m = _minute(0, walk_s=0.250, snr_db=20.0)
    reg = acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert reg is not None and acq.state == acq.STATE_ACQUIRED
    assert reg.sample0_utc_for(rtp) == pytest.approx(T0, abs=0.002)
    assert reg.counter_epoch_id == "ep-1" and reg.sigma_ms >= 1.0


def test_weak_signal_extends_the_fold_to_three_minutes():
    # snr_db is against the full 12 kHz band; in the 200 Hz tone band a -25 dB
    # tick is ~ -7 dB per tick: 54 rows fold it to ~10 dB (under the ~13 dB
    # noise-extreme threshold), 174 rows to ~15.5 dB (over it).
    acq = RegistrationAcquirer("SHARED_10000", SR)
    outcomes = []
    for k in range(3):
        audio, label, rtp, m = _minute(k, walk_s=-0.300, snr_db=-25.0)
        outcomes.append(acq.offer_minute(audio, label, rtp, m, D, "ep-1"))
    assert outcomes[0] is None, "one minute must NOT suffice at this SNR (else the test is toothless)"
    assert outcomes[-1] is not None, "180 s fold must lift the tick over the threshold"
    assert outcomes[-1].sample0_utc_for(rtp) == pytest.approx(T0 + 120, abs=0.003)


def test_held_registration_ignores_a_new_label_plane():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.1, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    # next minute the ring anchor refreshes to a different pair (label jumps 0.4 s)
    audio, label, rtp, m = _minute(1, walk_s=0.5, snr_db=20.0)
    reg = acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert reg.sample0_utc_for(rtp) == pytest.approx(T0 + 60, abs=0.002)


def test_counter_epoch_change_resets_to_bootstrap():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.1, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    audio, label, rtp, m = _minute(1, walk_s=0.1, snr_db=20.0)
    reg = acq.offer_minute(audio, label, rtp, m, D, "ep-2")
    # a fresh acquisition from this one minute is allowed; the OLD one is gone
    assert acq.registration is None or acq.registration.counter_epoch_id == "ep-2"


def test_corroborate_tightens_and_flags_sustained_residual():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    s0 = acq.registration.sigma_ms
    assert acq.corroborate({"WWV": (0.4, 0.5)}) == "tightened"
    assert acq.registration.sigma_ms <= s0
    # a plane that moved 30 ms: two consecutive minutes on two stations -> reacquire
    assert acq.corroborate({"WWV": (30.0, 0.5), "WWVH": (30.5, 0.6)}) == "held"
    assert acq.corroborate({"WWV": (30.2, 0.5), "WWVH": (30.1, 0.6)}) == "reacquire"
    assert acq.state == acq.STATE_BOOTSTRAP


def test_adopt_sibling_registration():
    acq = RegistrationAcquirer("WWV_20000", SR)
    reg = Registration(counter_epoch_id="ep-1", rtp_ref=5_000, utc_ref=T0,
                       sample_rate=SR, sigma_ms=1.2, channel="SHARED_10000")
    acq.adopt(reg)
    assert acq.state == acq.STATE_ACQUIRED
    assert acq.registration.sample0_utc_for(5_000 + 60 * SR) == pytest.approx(T0 + 60)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_state.py --override-ini addopts=-ra -v`
Expected: FAIL with `ImportError: cannot import name 'Registration'`.

- [ ] **Step 3: Implement**

Append to `registration_acquirer.py`:

```python
@dataclass
class Registration:
    """The acquired origin, held in the RTP frame: utc(sample at rtp) =
    utc_ref + (rtp − rtp_ref) / sample_rate, valid within one counter epoch."""
    counter_epoch_id: str
    rtp_ref: int
    utc_ref: float
    sample_rate: int
    sigma_ms: float
    method: str = "fold+template"
    n_minutes: int = 0
    channel: str = ""
    hypotheses_open: int = 0

    def sample0_utc_for(self, start_rtp: int) -> float:
        return self.utc_ref + (int(start_rtp) - int(self.rtp_ref)) / float(self.sample_rate)


class RegistrationAcquirer:
    """Acquire from the signal, hold on the ruler, corroborate or correct
    every minute (spec §2 rules 1-3)."""

    STATE_BOOTSTRAP = "BOOTSTRAP"
    STATE_ACQUIRED = "ACQUIRED"
    CORRECT_K_SIGMA = 3.0
    CORRECT_MINUTES = 2
    CORRECT_MIN_CHANNELS = 2        # here: stations on this channel's ensembles
    FILTER_MEMORY_MINUTES = 30
    TIMING_SIGMA_MAX_MS = 6.0       # tick-like: TickEdgeDetector.LABEL_ANCHOR_MAX_SIGMA_MS

    def __init__(self, channel: str, sample_rate: int):
        self.channel = channel
        self.sample_rate = int(sample_rate)
        self._state = self.STATE_BOOTSTRAP
        self._reg: Optional[Registration] = None
        self._epoch: Optional[str] = None
        self._buf: List[Tuple[np.ndarray, float, int, int]] = []   # (audio, label_s0, start_rtp, minute)
        self._bad_minutes = 0
        self._open: List[Hypothesis] = []

    @property
    def state(self) -> str:
        return self._state

    @property
    def registration(self) -> Optional[Registration]:
        return self._reg

    def reset(self, why: str) -> None:
        logger.info(f"[{self.channel}] registration reset -> BOOTSTRAP ({why})")
        self._state = self.STATE_BOOTSTRAP
        self._reg = None
        self._buf.clear()
        self._bad_minutes = 0
        self._open.clear()

    def adopt(self, reg: Registration) -> None:
        self._reg = Registration(**{**reg.__dict__, "channel": reg.channel or self.channel})
        self._epoch = reg.counter_epoch_id
        self._state = self.STATE_ACQUIRED
        self._buf.clear()
        self._bad_minutes = 0

    # ── acquisition ────────────────────────────────────────────────
    def offer_minute(self, audio: np.ndarray, label, start_rtp: int, minute_utc: int,
                     expected_delays_s: Dict[str, float],
                     counter_epoch_id: str) -> Optional[Registration]:
        if self._epoch is not None and counter_epoch_id != self._epoch:
            self.reset(f"counter epoch {self._epoch} -> {counter_epoch_id}")
        self._epoch = counter_epoch_id
        if self._state == self.STATE_ACQUIRED and self._reg is not None:
            return self._reg
        self._buf.append((np.asarray(audio, dtype=np.float64), float(label.sample0_utc),
                          int(start_rtp), int(minute_utc)))
        self._buf = self._buf[-3:]
        return self._try_acquire(expected_delays_s)

    def _try_acquire(self, expected_delays_s: Dict[str, float]) -> Optional[Registration]:
        # Concatenate the buffered minutes in the frame of the OLDEST label;
        # each minute is re-labelled onto that frame through RTP, so a ring
        # anchor refresh between minutes cannot smear the fold.
        a0, s0, rtp0, _ = self._buf[0]
        pieces = []
        for audio, s_lbl, rtp, _ in self._buf:
            # gap/overlap between consecutive buffers, in samples, from RTP
            want = (rtp - rtp0)
            have = sum(len(p) for p in pieces)
            if want > have:
                pieces.append(np.zeros(want - have))
            elif want < have:
                audio = audio[have - want:]
            pieces.append(audio)
        audio_all = np.concatenate(pieces)
        n_sec = min(180, len(audio_all) // self.sample_rate)
        by_band: Dict[str, List[FoldPeak]] = {}
        for band in TONE_BANDS_HZ:
            # fold EVERY band, even one with no eligible station: the leak of a
            # 1200 Hz tick into 900-1100 Hz is only recognisable by comparison
            profile, rows = fold_tick_train(audio_all, self.sample_rate, s0, band, n_sec)
            if rows == 0:
                continue
            by_band[band] = find_fold_peaks(profile, self.sample_rate, band)
        best = [p for p in arbitrate_bands(by_band)
                if any(BAND_OF_STATION.get(s) == p.band for s in expected_delays_s)]
        hyps = fit_template(best, expected_delays_s)
        self._open = [h for h in hyps if not h.unambiguous]
        winners = [h for h in hyps if h.unambiguous]
        if not winners:
            logger.info(f"[{self.channel}] BOOTSTRAP: {n_sec} s folded, "
                        f"{len(best)} peaks, {len(self._open)} ambiguous hypotheses")
            return None
        h = winners[0]
        # integer second from the marker of the most recent minute, located in
        # the OLDEST label's frame (re-labelled through RTP) so that a ring
        # anchor refresh between minutes cannot shift the whole-second answer
        k_int = 0
        a_last, _s_last_unused, rtp_last, minute_last = self._buf[-1]
        s_last_in_frame0 = s0 + (rtp_last - rtp0) / self.sample_rate
        st0 = h.assignments[0][0]
        mk = locate_minute_marker(a_last, self.sample_rate, s_last_in_frame0,
                                  BAND_OF_STATION[st0], minute_last)
        if mk is not None:
            k_int = integer_second_correction(mk[0], expected_delays_s[st0], h.correction_s)
        corr = h.correction_s + k_int
        self._reg = Registration(counter_epoch_id=self._epoch or "unregistered",
                                 rtp_ref=rtp0, utc_ref=s0 + corr,
                                 sample_rate=self.sample_rate, sigma_ms=h.sigma_ms,
                                 channel=self.channel, hypotheses_open=len(self._open))
        self._state = self.STATE_ACQUIRED
        self._bad_minutes = 0
        logger.info(f"[{self.channel}] ACQUIRED: correction {corr*1000:+.1f} ms "
                    f"(int {k_int:+d} s), σ {h.sigma_ms:.2f} ms, support {h.support}, "
                    f"stations {[a[0] for a in h.assignments]}, fold {n_sec} s")
        return self._reg

    # ── corroboration ──────────────────────────────────────────────
    def corroborate(self, residuals_ms: Dict[str, Tuple[float, float]]) -> str:
        """``residuals_ms``: station -> (ensemble timing error vs the
        ACQUIRED plane, per-tick sigma).  Only tick-like ensembles
        (sigma ≤ TIMING_SIGMA_MAX_MS) count."""
        if self._reg is None:
            return "held"
        good = {s: r for s, r in residuals_ms.items() if r[1] <= self.TIMING_SIGMA_MAX_MS}
        if not good:
            return "held"
        thr = self.CORRECT_K_SIGMA * max(self._reg.sigma_ms, ORIGIN_SIGMA_FLOOR_MS)
        far = [s for s, (e, _) in good.items() if abs(e) > thr]
        if len(far) >= self.CORRECT_MIN_CHANNELS or (len(good) == 1 and far):
            self._bad_minutes += 1
            if self._bad_minutes >= self.CORRECT_MINUTES:
                self.reset(f"residual > {self.CORRECT_K_SIGMA}σ for "
                           f"{self.CORRECT_MINUTES} minutes on {far}")
                return "reacquire"
            return "held"
        self._bad_minutes = 0
        # slow filter: running weighted mean with long memory (the true origin
        # is constant on the GPSDO; this is a smoother, not a tracker)
        w_new = sum(1.0 / max(sig, 0.1) ** 2 for _, sig in good.values())
        e_new = sum(e / max(sig, 0.1) ** 2 for e, sig in good.values()) / w_new
        n = min(self._reg.n_minutes, self.FILTER_MEMORY_MINUTES)
        w_old = (n / max(self._reg.sigma_ms, ORIGIN_SIGMA_FLOOR_MS) ** 2) if n else 0.0
        shift_ms = (w_new * e_new) / (w_new + w_old)
        self._reg.utc_ref += shift_ms / 1000.0
        self._reg.n_minutes += 1
        new_sigma = 1.0 / np.sqrt(w_new + w_old) if (w_new + w_old) > 0 else self._reg.sigma_ms
        self._reg.sigma_ms = float(max(ORIGIN_SIGMA_FLOOR_MS * 0.1, min(self._reg.sigma_ms, new_sigma)))
        return "tightened"
```

Note `TIMING_SIGMA_MAX_MS = 6.0` duplicates `TickEdgeDetector.LABEL_ANCHOR_MAX_SIGMA_MS`; import it instead: `from .tick_edge_detector import TickEdgeDetector` at module top and set `TIMING_SIGMA_MAX_MS = TickEdgeDetector.LABEL_ANCHOR_MAX_SIGMA_MS`. If that import is circular at runtime (Task 7 adds an import the other way), keep the literal and add a test asserting equality in Task 7.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/unit/test_registration_acquirer_state.py --override-ini addopts=-ra -v`
Expected: PASS. The 4 dB three-minute case is the sensitive one: 180 rows fold gain is `10·log10(174) ≈ 22 dB` over a 4 dB tick → ≈ 26 dB against the ≈ 12 dB noise-extreme threshold. If it fails, print `rows` and `peaks` from `_try_acquire` (temporary) and check the RTP-based concatenation (`want`/`have`) — an off-by-one-buffer there smears the fold.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/core/registration_acquirer.py tests/unit/test_registration_acquirer_state.py
git commit -m "feat(timing): RegistrationAcquirer — acquire from the fold, hold in RTP, corroborate or correct

Spec §2 rules 1-3, §4.5-4.6 (per-channel), §5.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 6: RegistrationStore — per-channel files, sibling fusion, summary

**Files:**
- Create: `src/hf_timestd/core/registration_store.py`
- Test: `tests/unit/test_registration_store.py`

**Interfaces:**
- Consumes: `Registration` (Task 5).
- Produces:
  ```python
  DEFAULT_DIR = Path("/run/hf-timestd/registration")
  DEFAULT_SUMMARY = Path("/run/hf-timestd/registration.json")
  FUSE_OUTLIER_MS = 3.0
  def fuse_registrations(regs: list[Registration], at_rtp: int) -> Optional[Registration]
      # inverse-variance mean of utc at at_rtp after rejecting > FUSE_OUTLIER_MS from the median;
      # None if regs empty or epochs disagree with the majority epoch
  class RegistrationStore:
      def __init__(self, directory: Path = DEFAULT_DIR, summary_path: Path = DEFAULT_SUMMARY,
                   stale_s: float = 300.0, time_fn=time.time)
      def write_channel(self, reg: Registration, state: str, extra: dict) -> None
      def read_siblings(self, exclude_channel: str = "") -> list[Registration]
      def write_summary(self, fused: Optional[Registration], contributing: list[str],
                        state: str, extra: dict) -> None
      def read_summary(self) -> Optional[dict]
  ```
- File format (`<dir>/<channel>.json`): `{"channel","state","counter_epoch_id","rtp_ref","utc_ref","sample_rate","sigma_ms","method","n_minutes","hypotheses_open","written_at", ...extra}`. Atomic write via temp-in-dir + `os.replace` (copy the pattern from `fusion_status_writer.py:123-140`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_registration_store.py
import json

import pytest

from hf_timestd.core.registration_acquirer import Registration
from hf_timestd.core.registration_store import RegistrationStore, fuse_registrations

SR = 24000


def _reg(ch, utc_ref, sigma, epoch="ep-1", rtp_ref=1000):
    return Registration(counter_epoch_id=epoch, rtp_ref=rtp_ref, utc_ref=utc_ref,
                        sample_rate=SR, sigma_ms=sigma, channel=ch)


def test_fuse_inverse_variance_and_outlier():
    regs = [_reg("a", 100.000, 1.0), _reg("b", 100.0005, 0.5), _reg("c", 100.0100, 0.5)]
    f = fuse_registrations(regs, at_rtp=1000)
    # c is 10 ms off the median -> rejected; a,b weighted 1:4
    assert f.utc_ref == pytest.approx(100.0004, abs=2e-5)
    assert f.sigma_ms == pytest.approx(1 / (1 + 4) ** 0.5, abs=1e-3)
    assert f.rtp_ref == 1000 and f.channel == "fused"


def test_fuse_rebases_to_common_rtp():
    regs = [_reg("a", 100.0, 1.0, rtp_ref=0), _reg("a2", 101.0, 1.0, rtp_ref=SR)]
    f = fuse_registrations(regs, at_rtp=2 * SR)
    assert f.utc_ref == pytest.approx(102.0)


def test_fuse_majority_epoch_wins_and_empty_is_none():
    regs = [_reg("a", 100.0, 1.0, "ep-2"), _reg("b", 100.0, 1.0, "ep-2"), _reg("c", 5.0, 1.0, "ep-1")]
    assert fuse_registrations(regs, 1000).counter_epoch_id == "ep-2"
    assert fuse_registrations([], 1000) is None


def test_store_roundtrip_and_staleness(tmp_path):
    clock = [1000.0]
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json",
                           stale_s=300.0, time_fn=lambda: clock[0])
    st.write_channel(_reg("SHARED_10000", 100.0, 1.0), "ACQUIRED", {"correction_ms": -250.0})
    st.write_channel(_reg("WWV_20000", 100.001, 2.0), "ACQUIRED", {})
    sibs = st.read_siblings(exclude_channel="SHARED_10000")
    assert [r.channel for r in sibs] == ["WWV_20000"]
    clock[0] += 301
    assert st.read_siblings() == []
    data = json.loads((tmp_path / "reg" / "SHARED_10000.json").read_text())
    assert data["correction_ms"] == -250.0 and data["state"] == "ACQUIRED"


def test_summary(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_summary(_reg("fused", 100.0, 0.7), ["SHARED_10000", "WWV_20000"], "ACQUIRED",
                     {"raw_pair_residual_ms": 16.7})
    s = st.read_summary()
    assert s["state"] == "ACQUIRED" and s["contributing"] == ["SHARED_10000", "WWV_20000"]
    assert s["raw_pair_residual_ms"] == 16.7 and s["sigma_ms"] == 0.7


def test_bootstrap_summary_has_no_plane(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_summary(None, [], "BOOTSTRAP", {})
    s = st.read_summary()
    assert s["state"] == "BOOTSTRAP" and s["utc_ref"] is None


def test_bootstrap_channel_file_has_null_sigma_and_is_not_a_sibling(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_channel(_reg("WWV_25000", 0.0, float("inf")), "BOOTSTRAP", {})
    text = (tmp_path / "reg" / "WWV_25000.json").read_text()
    assert "Infinity" not in text and json.loads(text)["sigma_ms"] is None
    assert st.read_siblings() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_registration_store.py --override-ini addopts=-ra -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/hf_timestd/core/registration_store.py
"""RegistrationStore — the acquired registration crosses processes.

Metrology runs one process per channel (timestd-metrology@<channel>).
Every channel on one radiod shares one ADC and one RTP counter, so they
share one origin (spec §4.6).  Each process writes its own estimate to
<dir>/<channel>.json and reads its siblings; ``fuse_registrations``
gives every reader the same answer.  The last writer also refreshes the
station summary /run/hf-timestd/registration.json (spec §7), which the
Offset Judge's HfAcquiredBench and the provenance sidecar read.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from .registration_acquirer import ORIGIN_SIGMA_FLOOR_MS, Registration

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("/run/hf-timestd/registration")
DEFAULT_SUMMARY = Path("/run/hf-timestd/registration.json")
FUSE_OUTLIER_MS = 3.0


def fuse_registrations(regs: List[Registration], at_rtp: int) -> Optional[Registration]:
    if not regs:
        return None
    epochs: Dict[str, int] = {}
    for r in regs:
        epochs[r.counter_epoch_id] = epochs.get(r.counter_epoch_id, 0) + 1
    epoch = max(epochs, key=epochs.get)
    same = [r for r in regs if r.counter_epoch_id == epoch]
    utc = np.array([r.sample0_utc_for(at_rtp) for r in same])
    med = np.median(utc)
    keep = [(r, u) for r, u in zip(same, utc) if abs(u - med) * 1000.0 <= FUSE_OUTLIER_MS]
    if not keep:
        return None
    w = np.array([1.0 / max(r.sigma_ms, ORIGIN_SIGMA_FLOOR_MS * 0.1) ** 2 for r, _ in keep])
    u = np.array([u for _, u in keep])
    fused_utc = float(np.sum(w * u) / np.sum(w))
    return Registration(counter_epoch_id=epoch, rtp_ref=int(at_rtp), utc_ref=fused_utc,
                        sample_rate=keep[0][0].sample_rate,
                        sigma_ms=float(1.0 / np.sqrt(np.sum(w))),
                        n_minutes=max(r.n_minutes for r, _ in keep), channel="fused",
                        hypotheses_open=sum(r.hypotheses_open for r, _ in keep))


class RegistrationStore:
    def __init__(self, directory: Path = DEFAULT_DIR, summary_path: Path = DEFAULT_SUMMARY,
                 stale_s: float = 300.0, time_fn: Callable[[], float] = time.time):
        self.directory = Path(directory)
        self.summary_path = Path(summary_path)
        self.stale_s = float(stale_s)
        self._time = time_fn

    # ── writing ────────────────────────────────────────────────────
    def _atomic_write(self, path: Path, payload: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=str(path.parent),
                                             prefix=f".{path.name}.", suffix=".tmp",
                                             delete=False, encoding="utf-8") as tmp:
                json.dump(payload, tmp, separators=(",", ":"))
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name
            os.replace(tmp_path, path)
        except OSError as e:
            logger.warning(f"registration write failed for {path}: {e}")

    @staticmethod
    def _payload(reg: Optional[Registration]) -> dict:
        if reg is None:
            return {"counter_epoch_id": None, "rtp_ref": None, "utc_ref": None,
                    "sample_rate": None, "sigma_ms": None, "method": None,
                    "n_minutes": 0, "hypotheses_open": 0}
        # strict JSON: a BOOTSTRAP channel file carries sigma inf -> null
        sigma = float(reg.sigma_ms) if math.isfinite(reg.sigma_ms) else None
        return {"counter_epoch_id": reg.counter_epoch_id, "rtp_ref": int(reg.rtp_ref),
                "utc_ref": float(reg.utc_ref), "sample_rate": int(reg.sample_rate),
                "sigma_ms": sigma, "method": reg.method,
                "n_minutes": int(reg.n_minutes), "hypotheses_open": int(reg.hypotheses_open)}

    def write_channel(self, reg: Registration, state: str, extra: dict) -> None:
        payload = {"channel": reg.channel, "state": state, "written_at": self._time(),
                   **self._payload(reg), **extra}
        self._atomic_write(self.directory / f"{reg.channel}.json", payload)

    def write_summary(self, fused: Optional[Registration], contributing: List[str],
                      state: str, extra: dict) -> None:
        payload = {"state": state, "contributing": list(contributing),
                   "written_at": self._time(), **self._payload(fused), **extra}
        self._atomic_write(self.summary_path, payload)

    # ── reading ────────────────────────────────────────────────────
    def read_siblings(self, exclude_channel: str = "") -> List[Registration]:
        out: List[Registration] = []
        if not self.directory.is_dir():
            return out
        now = self._time()
        for p in sorted(self.directory.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if d.get("channel") == exclude_channel or d.get("utc_ref") is None:
                continue
            if d.get("sigma_ms") is None:
                continue
            if now - float(d.get("written_at", 0)) > self.stale_s:
                continue
            if d.get("state") != "ACQUIRED":
                continue
            out.append(Registration(counter_epoch_id=str(d["counter_epoch_id"]),
                                    rtp_ref=int(d["rtp_ref"]), utc_ref=float(d["utc_ref"]),
                                    sample_rate=int(d["sample_rate"]), sigma_ms=float(d["sigma_ms"]),
                                    method=str(d.get("method") or "fold+template"),
                                    n_minutes=int(d.get("n_minutes", 0)),
                                    channel=str(d["channel"]),
                                    hypotheses_open=int(d.get("hypotheses_open", 0))))
        return out

    def read_summary(self) -> Optional[dict]:
        try:
            return json.loads(self.summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/unit/test_registration_store.py --override-ini addopts=-ra -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/core/registration_store.py tests/unit/test_registration_store.py
git commit -m "feat(timing): RegistrationStore — per-channel registration files, sibling fusion, summary

Spec §4.6 (per-radiod fusion across the per-channel processes) and §7.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 7: CounterEpochTracker and detector changes (`acquired` anchor source)

**Files:**
- Create: `src/hf_timestd/core/counter_epoch_tracker.py`
- Modify: `src/hf_timestd/core/tick_edge_detector.py:183-212` (`EdgeEnsembleResult`), `:598-615` (`timing_admissible`), `:627` (`anchor_source` in `_search_pass`), `:915` (result construction)
- Test: `tests/unit/test_counter_epoch_tracker.py`, `tests/unit/test_tick_edge_acquired_anchor.py`

**Interfaces:**
- Produces:
  ```python
  COUNTER_EPOCH_STEP_S = 0.5     # same value as binary_archive_writer.COUNTER_EPOCH_STEP_S
  class CounterEpochTracker:
      def __init__(self): ...
      def observe(self, gps_time_ns: int, rtp_timesnap: int, sample_rate: int) -> str
          # returns the current epoch id "ep-<gps_time_ns of first pair>" ; opens a new one when
          # |gps − predicted_from_prev| > COUNTER_EPOCH_STEP_S
      @property
      def epoch_id(self) -> str        # "unregistered" before the first observe
  ```
- Produces on `EdgeEnsembleResult`: `anchor_sigma_ms: float = float("inf")`; `anchor_source` may be `"acquired"`.
- `timing_admissible`: `"minute_marker"` → True (unchanged); `"acquired"` → True iff `result.anchor_sigma_ms < ACQUIRED_ANCHOR_MAX_SIGMA_MS = 2.0` and `result.sigma_single_ms <= LABEL_ANCHOR_MAX_SIGMA_MS` (junk on a good plane is still junk); `"host_label"` unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_counter_epoch_tracker.py
from hf_timestd.core.counter_epoch_tracker import COUNTER_EPOCH_STEP_S, CounterEpochTracker
from hf_timestd.core import binary_archive_writer


def test_step_constant_matches_the_recorder():
    assert COUNTER_EPOCH_STEP_S == binary_archive_writer.COUNTER_EPOCH_STEP_S


def test_same_mapping_keeps_the_epoch():
    t = CounterEpochTracker()
    assert t.epoch_id == "unregistered"
    e1 = t.observe(1_000_000_000_000, 0, 24000)
    # 10 s later in RTP, GPS advanced 10 s + 40 ms skew: same epoch
    e2 = t.observe(1_000_000_000_000 + 10_040_000_000, 240_000, 24000)
    assert e1 == e2 == t.epoch_id


def test_pair_off_by_more_than_step_opens_a_new_epoch():
    t = CounterEpochTracker()
    e1 = t.observe(1_000_000_000_000, 0, 24000)
    e2 = t.observe(1_000_000_000_000 + 10_000_000_000 + 700_000_000, 240_000, 24000)
    assert e2 != e1
```

```python
# tests/unit/test_tick_edge_acquired_anchor.py
import dataclasses

import pytest

from hf_timestd.core.tick_edge_detector import EdgeEnsembleResult, TickEdgeDetector
from tests.unit.synth_ticks import make_tick_audio, label_timing

SR = 24000
MIN = 1_800_000_000
T0 = MIN - 1.0


def _res(anchor_source, anchor_sigma_ms, sigma_single_ms=0.5):
    return EdgeEnsembleResult(station="WWV", frequency_hz=1e7, minute_number=MIN,
                              ensemble_timing_error_ms=0.0, ensemble_uncertainty_ms=0.1,
                              ensemble_n_edges=50, n_attempted=57, n_detected=50, n_clean=50,
                              mean_edge_snr_db=30.0, confidence=0.9,
                              anchor_source=anchor_source, sigma_single_ms=sigma_single_ms,
                              anchor_sigma_ms=anchor_sigma_ms)


def test_acquired_admitted_when_registration_is_tight():
    ok, why = TickEdgeDetector.timing_admissible(_res("acquired", 0.8))
    assert ok and "acquired" in why


def test_acquired_refused_when_registration_is_loose_or_ensemble_is_junk():
    assert not TickEdgeDetector.timing_admissible(_res("acquired", 2.5))[0]
    assert not TickEdgeDetector.timing_admissible(_res("acquired", 0.8, sigma_single_ms=15.0))[0]


def test_marker_and_label_rules_unchanged():
    assert TickEdgeDetector.timing_admissible(_res("minute_marker", float("inf")))[0]
    assert TickEdgeDetector.timing_admissible(_res("host_label", float("inf"), 3.0))[0]
    assert not TickEdgeDetector.timing_admissible(_res("host_label", float("inf"), 9.0))[0]


def test_detector_labels_an_acquired_plane():
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0045}, snr_db=25.0)
    bt = dataclasses.replace(label_timing(T0, 0.0, SR), origin_source="acquired",
                             origin_sigma_ms=0.9)
    det = TickEdgeDetector(sample_rate=SR)
    res = det.detect_edges(audio_signal=audio, station="WWV", minute_number=MIN,
                           buffer_timing=bt, expected_delay_sec=0.0045,
                           is_dedicated_channel=True, iq_samples=None)
    assert res is not None
    assert res.anchor_source == "acquired" and res.anchor_sigma_ms == 0.9
    assert abs(res.ensemble_timing_error_ms) < 1.0
```

Check `detect_edges`' exact parameter names at `tick_edge_detector.py:522-535` before writing the last test and match them.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_counter_epoch_tracker.py tests/unit/test_tick_edge_acquired_anchor.py --override-ini addopts=-ra -v`
Expected: FAIL (`ModuleNotFoundError`, then `TypeError: unexpected keyword 'anchor_sigma_ms'`).

- [ ] **Step 3: Implement the tracker**

```python
# src/hf_timestd/core/counter_epoch_tracker.py
"""CounterEpochTracker — the live-ring twin of the recorder's
``binary_archive_writer._note_counter_epoch``.

radiod's (GPS_TIME, RTP_TIMESNAP) pair is re-adopted at every radiod or
recorder restart.  Within one counter space a new pair predicts the old
one to within the pair's skew (< 0.5 s); a jump past COUNTER_EPOCH_STEP_S
means the RTP counter space itself changed, and every registration held
in the old RTP frame is void (spec §5, "step on counter-epoch change").
"""
from __future__ import annotations

from typing import Optional, Tuple

COUNTER_EPOCH_STEP_S = 0.5


class CounterEpochTracker:
    def __init__(self) -> None:
        self._id: Optional[str] = None
        self._pair: Optional[Tuple[int, int, int]] = None

    @property
    def epoch_id(self) -> str:
        return self._id or "unregistered"

    def observe(self, gps_time_ns: int, rtp_timesnap: int, sample_rate: int) -> str:
        gps, snap, sr = int(gps_time_ns), int(rtp_timesnap), int(sample_rate)
        if self._pair is not None:
            pg, ps, psr = self._pair
            predicted_ns = pg + ((snap - ps) & 0xFFFFFFFF if snap < ps else snap - ps) * 1e9 / psr
            if abs(gps - predicted_ns) <= COUNTER_EPOCH_STEP_S * 1e9:
                self._pair = (gps, snap, sr)
                return self.epoch_id
        self._pair = (gps, snap, sr)
        self._id = f"ep-{gps}"
        return self._id
```

Read `binary_archive_writer.py:385-400` first; if its prediction handles RTP wrap differently, copy its arithmetic exactly so the two trackers agree.

- [ ] **Step 4: Modify the detector**

In `tick_edge_detector.py`:

1. In `EdgeEnsembleResult` after `sigma_single_ms: float = 0.0` add:
   ```python
       # 1-sigma of the anchor plane itself (ms).  inf for a host label;
       # the registration sigma for anchor_source='acquired'.
       anchor_sigma_ms: float = float("inf")
   ```
2. Add a class constant beside `LABEL_ANCHOR_MAX_SIGMA_MS`:
   ```python
       ACQUIRED_ANCHOR_MAX_SIGMA_MS = 2.0   # spec §5: acquired plane admits timing under 2 ms
   ```
3. In `_search_pass` replace the line `anchor_source = 'minute_marker' if anchor_onset is not None else 'host_label'` with:
   ```python
           if anchor_onset is not None:
               anchor_source = 'minute_marker'
           elif getattr(buffer_timing, 'origin_source', 'label') == 'acquired':
               anchor_source = 'acquired'
           else:
               anchor_source = 'host_label'
           anchor_sigma_ms = float(getattr(buffer_timing, 'origin_sigma_ms', float('inf')))
   ```
   and pass `anchor_sigma_ms=anchor_sigma_ms` into every `EdgeEnsembleResult(...)` constructed in that method (there are two: the `sigma_single_ms=999.0` fallback near line 861 and the main one near line 915).
4. In `timing_admissible`, before the `host_label` branch:
   ```python
           if result.anchor_source == 'acquired':
               if result.anchor_sigma_ms >= cls.ACQUIRED_ANCHOR_MAX_SIGMA_MS:
                   return False, (f"acquired anchor σ {result.anchor_sigma_ms:.2f} ms ≥ "
                                  f"{cls.ACQUIRED_ANCHOR_MAX_SIGMA_MS} ms — registration not yet tight")
               if result.sigma_single_ms > cls.LABEL_ANCHOR_MAX_SIGMA_MS:
                   return False, (f"acquired anchor but per-tick σ {result.sigma_single_ms:.1f} ms "
                                  f"is window scatter, not ticks")
               return True, (f"acquired anchor σ {result.anchor_sigma_ms:.2f} ms, "
                             f"per-tick σ {result.sigma_single_ms:.1f} ms")
   ```
5. In `detect_edges` (line ~582), the rule that falls back from a marker anchor to the label when the anchored pass is junk stays as is.

- [ ] **Step 5: Run the new tests and the whole detector suite**

Run: `.venv/bin/pytest tests/unit/test_counter_epoch_tracker.py tests/unit/test_tick_edge_acquired_anchor.py tests/unit/test_tick_edge_anchor.py tests/unit/test_tick_edge_detector_doppler.py --override-ini addopts=-ra -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hf_timestd/core/counter_epoch_tracker.py src/hf_timestd/core/tick_edge_detector.py tests/unit/test_counter_epoch_tracker.py tests/unit/test_tick_edge_acquired_anchor.py
git commit -m "feat(timing): 'acquired' anchor source admits timing under 2 ms; live counter-epoch tracker

Spec §5 (anchor_source 'acquired', timing_admissible rule) and §3.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 8: Wire the acquirer into the metrology minute loop

**Files:**
- Modify: `src/hf_timestd/core/metrology_service.py:143-200` (`__init__`), `:588-600` (after `resolve_buffer_timing`), `:637-700` (`_process_minute_data`)
- Modify: `src/hf_timestd/core/metrology_engine.py:1436-1440` (expose the envelope + expected delays; see Step 3)
- Test: `tests/unit/test_metrology_service_registration.py`

**Interfaces:**
- Consumes: `RegistrationAcquirer`, `Registration` (Task 5); `RegistrationStore`, `fuse_registrations` (Task 6); `CounterEpochTracker` (Task 7); `BufferTiming` fields (Task 1).
- Produces on `MetrologyService`: `self.acquirer`, `self.reg_store`, `self.epoch_tracker`; new method `apply_registration(self, buffer_timing, iq_samples, start_rtp, minute_utc, metadata) -> BufferTiming`; new method `feed_back_ensembles(self, results) -> None`.
- Produces on `MetrologyEngine`: `prepare_audio(self, iq_samples) -> np.ndarray` (the `envelope − mean` at line 1437, factored out) and `expected_delays_s(self, system_time: float, minute_utc: int) -> dict[str, float]` (the geometric prediction filtered by `eligible_candidates`, in seconds; `minute_utc` is the minute boundary in Unix seconds). `process_minute` must call the same two helpers so the acquirer and the detector see identical inputs.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_metrology_service_registration.py
"""apply_registration turns a skewed label plane into the acquired plane
and hands the engine a BufferTiming with origin_source='acquired'."""
import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest

from hf_timestd.core.buffer_timing import BufferTiming
from hf_timestd.core.counter_epoch_tracker import CounterEpochTracker
from hf_timestd.core.metrology_service import MetrologyService
from hf_timestd.core.registration_acquirer import RegistrationAcquirer
from hf_timestd.core.registration_store import RegistrationStore
from tests.unit.synth_ticks import make_tick_audio, label_timing

SR = 24000
MIN = 1_800_000_000
T0 = MIN - 1.0


class _Engine:
    """Stand-in exposing the two helpers the service relies on."""
    def prepare_audio(self, iq):
        return np.asarray(iq, dtype=np.float64)

    def expected_delays_s(self, system_time, utc_minute):
        return {"WWV": 0.0125}


def _service(tmp_path):
    svc = MetrologyService.__new__(MetrologyService)      # bypass the heavy __init__
    svc.channel_name = "SHARED_10000"
    svc.sample_rate = SR
    svc.engine = _Engine()
    svc.acquirer = RegistrationAcquirer("SHARED_10000", SR)
    svc.reg_store = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    svc.epoch_tracker = CounterEpochTracker()
    svc._last_registration_meta = {}
    return svc


def _meta(k):
    return {"gps_time_ns": 1_000_000_000_000 + k * 60_000_000_000,
            "rtp_timesnap": 1_000_000 + k * 60 * SR, "sample_rate": SR}


def test_first_minute_bootstraps_then_acquires(tmp_path):
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    label = label_timing(T0, 0.250, SR)                  # radiod pair 250 ms late
    bt = svc.apply_registration(label, audio, start_rtp=1_000_000, minute_utc=MIN, metadata=_meta(0))
    assert bt.origin_source == "acquired"
    assert bt.sample0_utc == pytest.approx(T0, abs=0.002)
    assert bt.origin_sigma_ms >= 1.0 and bt.counter_epoch_id.startswith("ep-")
    s = svc.reg_store.read_summary()
    assert s["state"] == "ACQUIRED" and s["raw_pair_residual_ms"] == pytest.approx(-250.0, abs=2.0)


def test_bootstrap_leaves_the_label_plane_marked(tmp_path):
    svc = _service(tmp_path)
    rng = np.random.default_rng(3)
    noise = 0.1 * rng.standard_normal(62 * SR)
    bt = svc.apply_registration(label_timing(T0, 0.1, SR), noise, 1_000_000, MIN, _meta(0))
    assert bt.origin_source == "label" and bt.sample0_utc == T0 + 0.1
    assert svc.reg_store.read_summary()["state"] == "BOOTSTRAP"


def test_sibling_registration_is_adopted(tmp_path):
    svc = _service(tmp_path)
    from hf_timestd.core.registration_acquirer import Registration
    sib = Registration(counter_epoch_id=svc.epoch_tracker.observe(**_meta(0)), rtp_ref=1_000_000,
                       utc_ref=T0, sample_rate=SR, sigma_ms=0.9, channel="WWV_20000")
    svc.reg_store.write_channel(sib, "ACQUIRED", {})
    rng = np.random.default_rng(3)
    noise = 0.1 * rng.standard_normal(62 * SR)          # this channel hears nothing
    bt = svc.apply_registration(label_timing(T0, 0.3, SR), noise, 1_000_000, MIN, _meta(0))
    assert bt.origin_source == "acquired" and bt.sample0_utc == pytest.approx(T0, abs=1e-6)


def test_feed_back_reacquires_on_sustained_residual(tmp_path):
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    svc.apply_registration(label_timing(T0, 0.0, SR), audio, 1_000_000, MIN, _meta(0))
    r = SimpleNamespace(station="WWV", ensemble_timing_error_ms=40.0, sigma_single_ms=0.5,
                        anchor_source="acquired")
    svc.feed_back_ensembles([r])
    svc.feed_back_ensembles([r])
    assert svc.acquirer.state == RegistrationAcquirer.STATE_BOOTSTRAP
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_metrology_service_registration.py --override-ini addopts=-ra -v`
Expected: FAIL with `AttributeError: 'MetrologyService' object has no attribute 'apply_registration'`.

- [ ] **Step 3: Factor the engine helpers**

In `metrology_engine.py`, add two methods to `MetrologyEngine` and call them from `process_minute` in place of the inline code at lines 1436-1452 and 2395-2410:

```python
    def prepare_audio(self, iq_samples: np.ndarray) -> np.ndarray:
        """The real envelope with DC removed — the detector's and the
        acquirer's common input (one measurand, one ruler)."""
        envelope = np.abs(iq_samples)
        return envelope - np.mean(envelope)

    def expected_delays_s(self, system_time: float, minute_utc: int) -> Dict[str, float]:
        """Geometric expected delays (seconds) for the stations that can be
        on the air at this minute on this frequency — the same set and the
        same numbers the tick search uses.  ``minute_utc`` is the minute
        boundary in Unix seconds; ``eligible_candidates`` wants minute-of-
        hour and hour-of-day, derived here."""
        delays_ms: Dict[str, float] = {}
        for station in _live_station_names():
            expected_delay_ms, _dist_km, _unc = self._predict_geometric_delay(station, system_time)
            if expected_delay_ms > 0:
                delays_ms[station] = expected_delay_ms
        utc_hour = (int(minute_utc) // 3600) % 24
        bpm_hours = getattr(getattr(self, "bpm_discriminator", None), "active_hours", None)
        try:
            from hf_timestd.core.wwv_constants import STATION_CATALOG as _CAT
            st_freqs = {n: list(_CAT.get(n).frequencies_mhz) for n in _live_station_names()
                        if _CAT.get(n) is not None}
        except Exception:  # noqa: BLE001
            st_freqs = None
        eligible = eligible_candidates(delays_ms, utc_minute=(int(minute_utc) // 60) % 60,
                                       utc_hour=utc_hour, bpm_active_hours=bpm_hours,
                                       frequency_mhz=self.frequency_mhz,
                                       station_frequencies=st_freqs)
        return {s: d / 1000.0 for s, d in eligible.items()}
```

Read `process_minute` around lines 1430-1460 and 2380-2415 to see how `utc_minute`/`utc_hour` are derived there and match them exactly (the existing code computes them from `system_time`; keep one derivation). Replace the inline envelope computation with `audio_signal = self.prepare_audio(iq_samples)`. Leave `expected_uncertainty_by_station` where it is — the helper does not carry it. Run the engine's existing tests (`.venv/bin/pytest tests/unit -k "engine or metrology" --override-ini addopts=-ra -q`) — they must stay green before continuing.

- [ ] **Step 4: Implement the service wiring**

In `metrology_service.py`:

1. Imports at top:
   ```python
   import dataclasses
   from .counter_epoch_tracker import CounterEpochTracker
   from .registration_acquirer import RegistrationAcquirer, Registration
   from .registration_store import RegistrationStore, fuse_registrations
   ```
2. In `__init__` after `self.engine` is built (find `self.engine = MetrologyEngine(` and add after that block):
   ```python
           # T3 self-registration (spec 2026-09-06): the ticks place the second.
           self.acquirer = RegistrationAcquirer(self.channel_name, self.sample_rate)
           self.reg_store = RegistrationStore()
           self.epoch_tracker = CounterEpochTracker()
           self._last_registration_meta: Dict[str, Any] = {}
   ```
   Confirm `self.sample_rate` exists in `__init__`; if the attribute has another name (grep `sample_rate` in the file), use that.
3. Add the two methods to the class:
   ```python
       def apply_registration(self, buffer_timing, iq_samples: np.ndarray, start_rtp: int,
                              minute_utc: int, metadata: Dict[str, Any]):
           """Replace the label ORIGIN with the acquired one (rate untouched).
           Returns the BufferTiming to hand the engine."""
           if buffer_timing is None or buffer_timing.source == 'no_timing':
               return buffer_timing
           epoch = self.epoch_tracker.observe(metadata.get("gps_time_ns", 0),
                                              metadata.get("rtp_timesnap", 0),
                                              metadata.get("sample_rate", self.sample_rate))
           audio = self.engine.prepare_audio(iq_samples)
           delays = self.engine.expected_delays_s(buffer_timing.sample0_utc, int(minute_utc))
           own = self.acquirer.offer_minute(audio, buffer_timing, int(start_rtp), int(minute_utc),
                                            delays, epoch)
           sibs = self.reg_store.read_siblings(exclude_channel=self.channel_name)
           fused = fuse_registrations(([own] if own else []) + sibs, at_rtp=int(start_rtp))
           if own is None and fused is not None:
               self.acquirer.adopt(fused)          # a sibling already placed the second
           label_s0 = float(buffer_timing.sample0_utc)
           if fused is None:
               self._publish_registration(None, [], label_s0, None, epoch)
               return dataclasses.replace(buffer_timing, origin_source="label",
                                          counter_epoch_id=epoch)
           s0 = fused.sample0_utc_for(int(start_rtp))
           residual_ms = (s0 - label_s0) * 1000.0
           self._publish_registration(fused, [r.channel for r in sibs] + ([self.channel_name] if own else []),
                                      label_s0, residual_ms, epoch)
           return dataclasses.replace(buffer_timing, sample0_utc=s0, origin_source="acquired",
                                      origin_sigma_ms=fused.sigma_ms, counter_epoch_id=epoch)

       def _publish_registration(self, fused, contributing, label_s0, residual_ms, epoch):
           own = self.acquirer.registration
           state = self.acquirer.state
           if own is not None:
               self.reg_store.write_channel(own, state, {
                   "label_sample0_utc": label_s0,
                   "correction_ms": None if residual_ms is None else round(residual_ms, 3)})
           else:
               self.reg_store.write_channel(
                   Registration(counter_epoch_id=epoch, rtp_ref=0, utc_ref=0.0,
                                sample_rate=self.sample_rate, sigma_ms=float("inf"),
                                channel=self.channel_name), state, {"label_sample0_utc": label_s0})
           self.reg_store.write_summary(fused, sorted(set(contributing)),
                                        "ACQUIRED" if fused is not None else "BOOTSTRAP",
                                        {"raw_pair_residual_ms": None if residual_ms is None else round(residual_ms, 3),
                                         "counter_epoch_id": epoch,
                                         "minutes_since_acquisition": 0 if fused is None else fused.n_minutes})

       def feed_back_ensembles(self, results) -> None:
           """Hand this minute's acquired-plane ensembles to the acquirer
           (spec §5 corroborate / correct)."""
           res = {}
           for r in results or []:
               if getattr(r, "anchor_source", None) != "acquired":
                   continue
               res[str(r.station)] = (float(r.ensemble_timing_error_ms), float(r.sigma_single_ms))
           if res:
               outcome = self.acquirer.corroborate(res)
               if outcome == "reacquire":
                   logger.warning(f"[{self.channel_name}] registration residual sustained; re-acquiring")
   ```
   `write_channel` for the BOOTSTRAP case writes `utc_ref=0.0` and `sigma_ms=inf` (serialised as `null`); `read_siblings` skips non-ACQUIRED files and null sigmas, so it is inert for fusion and visible for provenance.
4. In the minute loop, after `buffer_timing = resolve_buffer_timing(...)` and the `no_timing` skip (lines ~588-600), before `_process_minute_data`:
   ```python
                   buffer_timing = self.apply_registration(
                       buffer_timing, samples, metadata.get("start_rtp_timestamp", 0),
                       next_minute, metadata)
   ```
5. In `_process_minute_data`, right after `results = self.engine.process_minute(...)`:
   ```python
               edge_results = getattr(self.engine, "last_edge_results", None)
               if edge_results:
                   self.feed_back_ensembles(edge_results)
   ```
   and in `metrology_engine.process_minute`, where `edge_result` objects are produced (near lines 1674 and 1783), collect them into `self.last_edge_results: List[EdgeEnsembleResult]` (reset to `[]` at the top of `process_minute`). Grep `edge_result = self.edge_detector.detect_edges(` to find each production site.

- [ ] **Step 5: Run the new test and the metrology suites**

Run: `.venv/bin/pytest tests/unit/test_metrology_service_registration.py tests/unit -k "metrology or engine or service" --override-ini addopts=-ra -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hf_timestd/core/metrology_service.py src/hf_timestd/core/metrology_engine.py src/hf_timestd/core/registration_store.py tests/unit/test_metrology_service_registration.py tests/unit/test_registration_store.py
git commit -m "feat(timing): metrology applies the acquired registration before the tick search

The acquirer sees the same envelope and the same eligible station delays the
detector uses; the fused registration replaces the label origin; each minute's
acquired-plane ensembles corroborate or correct it.  Spec §3, §5, §7.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 9: HfAcquiredBench in the Offset Judge

**Files:**
- Modify: `src/hf_timestd/core/offset_judge.py` (append `HfAcquiredBench` after `LbeT5Bench`)
- Modify: `src/hf_timestd/core/core_recorder_v2.py:703-712` (wire the bench)
- Test: `tests/unit/test_offset_judge_hf_acquired.py`

**Interfaces:**
- Consumes: `RegistrationStore.read_summary()` (Task 6) — a dict with `state`, `rtp_ref`, `utc_ref`, `sample_rate`, `sigma_ms`, `counter_epoch_id`, `written_at`.
- Produces:
  ```python
  class HfAcquiredBench:
      TIER = "T3"           # the acquired plane IS the HF answer; judged on its measured sigma
      FRESHNESS_S = 180.0
      def __init__(self, provider: Callable[[], Optional[Tuple[int, float]]],
                   store: Optional[RegistrationStore] = None,
                   mono_fn=time.monotonic, time_fn=time.time)
          # provider -> (arrival_rtp, arrival_mono) of the most recent arrived sample, or None
      def poll(self) -> Optional[BenchReading]
  ```
- `BenchReading(utc=utc_ref + (arrival_rtp − rtp_ref)/sr, mono=arrival_mono, sigma_ns=sigma_ms·1e6, tier="T3", detail={"bench": "hf_acquired", "counter_epoch_id", "raw_pair_residual_ms", "registration_age_s"})`. Read `BenchReading`'s exact field list at `offset_judge.py:306-330` and fill every required field.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_offset_judge_hf_acquired.py
from hf_timestd.core.offset_judge import HfAcquiredBench
from hf_timestd.core.registration_acquirer import Registration
from hf_timestd.core.registration_store import RegistrationStore

SR = 24000


def _store(tmp_path, clock):
    return RegistrationStore(tmp_path / "reg", tmp_path / "registration.json", time_fn=lambda: clock[0])


def test_bench_projects_the_registration_to_the_arrival(tmp_path):
    clock = [5000.0]
    st = _store(tmp_path, clock)
    st.write_summary(Registration("ep-1", rtp_ref=1000, utc_ref=100.0, sample_rate=SR, sigma_ms=0.8,
                                  channel="fused"), ["SHARED_10000"], "ACQUIRED",
                     {"raw_pair_residual_ms": 16.7})
    bench = HfAcquiredBench(provider=lambda: (1000 + 10 * SR, 42.0), store=st,
                            mono_fn=lambda: 42.5, time_fn=lambda: clock[0])
    r = bench.poll()
    assert r is not None
    assert r.utc == 110.0 and r.mono == 42.0
    assert r.sigma_ns == 0.8e6 and r.tier == "T3"
    assert r.detail["bench"] == "hf_acquired" and r.detail["raw_pair_residual_ms"] == 16.7


def test_bench_silent_in_bootstrap_or_when_stale(tmp_path):
    clock = [5000.0]
    st = _store(tmp_path, clock)
    st.write_summary(None, [], "BOOTSTRAP", {})
    bench = HfAcquiredBench(provider=lambda: (1, 1.0), store=st, mono_fn=lambda: 1.0,
                            time_fn=lambda: clock[0])
    assert bench.poll() is None
    st.write_summary(Registration("ep-1", 1000, 100.0, SR, 0.8, channel="fused"), ["x"], "ACQUIRED", {})
    clock[0] += 200.0
    assert bench.poll() is None
    assert HfAcquiredBench(provider=lambda: None, store=st).poll() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_offset_judge_hf_acquired.py --override-ini addopts=-ra -v`
Expected: FAIL with `ImportError: cannot import name 'HfAcquiredBench'`.

- [ ] **Step 3: Implement**

Append to `offset_judge.py` after `LbeT5Bench`:

```python
class HfAcquiredBench:
    """T3 bench: the tick-acquired registration (spec 2026-09-06 §6).

    The ONE bench that never touches the host clock: it projects the
    acquired origin (utc_ref at rtp_ref, held on the GPSDO-locked RTP
    counter) to the most recently arrived sample and hands that off to
    the monotonic clock at the arrival instant, exactly as
    NativeAnchorBench does for T6.  Its residual against the raw radiod
    pair (carried in ``detail``) names pair skew directly.
    """

    TIER = "T3"
    FRESHNESS_S = 180.0
    ARRIVAL_MAX_AGE_S = 5.0

    def __init__(self, provider: Callable[[], Optional[Tuple[int, float]]],
                 store=None, mono_fn: Callable[[], float] = time.monotonic,
                 time_fn: Callable[[], float] = time.time):
        from .registration_store import RegistrationStore
        self._provider = provider
        self._store = store if store is not None else RegistrationStore()
        self._mono = mono_fn
        self._time = time_fn

    def poll(self) -> Optional[BenchReading]:
        try:
            state = self._provider()
        except Exception:  # noqa: BLE001 — provider trouble ≠ judge trouble
            return None
        if state is None:
            return None
        arrival_rtp, arrival_mono = state
        age = self._mono() - float(arrival_mono)
        if age < 0 or age > self.ARRIVAL_MAX_AGE_S:
            return None
        s = self._store.read_summary()
        if not s or s.get("state") != "ACQUIRED" or s.get("utc_ref") is None:
            return None
        reg_age = self._time() - float(s.get("written_at", 0))
        if reg_age > self.FRESHNESS_S:
            return None
        sr = float(s["sample_rate"])
        utc = float(s["utc_ref"]) + ((int(arrival_rtp) - int(s["rtp_ref"])) & 0xFFFFFFFF
                                     if int(arrival_rtp) < int(s["rtp_ref"])
                                     else int(arrival_rtp) - int(s["rtp_ref"])) / sr
        return BenchReading(
            utc=utc, mono=float(arrival_mono), sigma_ns=float(s["sigma_ms"]) * 1e6,
            tier=self.TIER,
            detail={"bench": "hf_acquired", "counter_epoch_id": s.get("counter_epoch_id"),
                    "raw_pair_residual_ms": s.get("raw_pair_residual_ms"),
                    "registration_age_s": round(reg_age, 1)},
        )
```

Open `BenchReading` (`offset_judge.py:306-330`) and add any further required positional fields with the values the other benches use. If `BenchReading` has a `name`/`source` field, set it to `"hf_acquired"`.

Wire it in `core_recorder_v2.py` inside the existing `if self._offset_judge is not None:` block (line ~703), after the T5 bench:

```python
                from .offset_judge import HfAcquiredBench
                self._offset_judge.add_bench(
                    HfAcquiredBench(provider=self._hf_acquired_bench_state))
```

and add the provider method beside `_t6_bench_state`:

```python
    def _hf_acquired_bench_state(self):
        """HfAcquiredBench provider: (arrival_rtp, arrival_mono) of the most
        recently arrived sample, from the same pairing product the T6
        bench uses (the acquired registration lives in RTP; only the
        arrival point grounds it in 'now')."""
        pairing = getattr(self, '_t5_pairing', None)
        if pairing is None:
            return None
        arrival = pairing.latest_arrival
        if arrival is None:
            return None
        return (arrival[0], arrival[1])
```

Check `_t5_pairing` is created on stations without an LB-142x (ND has none): grep `_t5_pairing =` in `core_recorder_v2.py`. If it exists only with the T5 probe, use the recorder's own latest RTP arrival instead — grep `latest_arrival\|last_rtp\|_last_arrival` for the attribute the stream path maintains and return `(rtp, mono)` from it. Record which one you used in the report.

- [ ] **Step 4: Run the tests and the judge suite**

Run: `.venv/bin/pytest tests/unit/test_offset_judge_hf_acquired.py tests/unit -k "offset_judge or judge" --override-ini addopts=-ra -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/core/offset_judge.py src/hf_timestd/core/core_recorder_v2.py tests/unit/test_offset_judge_hf_acquired.py
git commit -m "feat(judge): hf_acquired bench — the tick-acquired plane, host-clock free

Spec §6.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 10: Provenance in authority.json and the docs paragraph

**Files:**
- Modify: `src/hf_timestd/core/authority_manager.py` (the state builder that writes `/run/hf-timestd/authority.json`)
- Modify: `docs/METROLOGY.md` §4.5
- Test: `tests/unit/test_authority_registration_block.py`

**Interfaces:**
- Consumes: `RegistrationStore.read_summary()`.
- Produces: `authority.json["registration"] = {"source": "hf_acquired" | "label", "state", "sigma_ms", "counter_epoch_id", "raw_pair_residual_ms", "contributing"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_authority_registration_block.py
from hf_timestd.core.authority_manager import registration_block
from hf_timestd.core.registration_acquirer import Registration
from hf_timestd.core.registration_store import RegistrationStore


def test_block_from_acquired_summary(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_summary(Registration("ep-1", 1000, 100.0, 24000, 0.7, channel="fused"),
                     ["SHARED_10000", "WWV_20000"], "ACQUIRED", {"raw_pair_residual_ms": 16.7})
    b = registration_block(st)
    assert b == {"source": "hf_acquired", "state": "ACQUIRED", "sigma_ms": 0.7,
                 "counter_epoch_id": "ep-1", "raw_pair_residual_ms": 16.7,
                 "contributing": ["SHARED_10000", "WWV_20000"]}


def test_block_without_summary_is_label(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    assert registration_block(st) == {"source": "label", "state": "UNKNOWN", "sigma_ms": None,
                                      "counter_epoch_id": None, "raw_pair_residual_ms": None,
                                      "contributing": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_authority_registration_block.py --override-ini addopts=-ra -v`
Expected: FAIL with `ImportError: cannot import name 'registration_block'`.

- [ ] **Step 3: Implement**

In `authority_manager.py` add a module-level function and call it where the authority payload dict is assembled (grep `"tier"` or `payload = {` in the file; add `"registration": registration_block()` to that dict):

```python
def registration_block(store=None) -> dict:
    """The origin's provenance for authority.json (spec §7)."""
    from .registration_store import RegistrationStore
    s = (store or RegistrationStore()).read_summary()
    if not s:
        return {"source": "label", "state": "UNKNOWN", "sigma_ms": None,
                "counter_epoch_id": None, "raw_pair_residual_ms": None, "contributing": []}
    acquired = s.get("state") == "ACQUIRED" and s.get("utc_ref") is not None
    return {"source": "hf_acquired" if acquired else "label",
            "state": s.get("state", "UNKNOWN"),
            "sigma_ms": s.get("sigma_ms"),
            "counter_epoch_id": s.get("counter_epoch_id"),
            "raw_pair_residual_ms": s.get("raw_pair_residual_ms"),
            "contributing": list(s.get("contributing", []))}
```

Also add the same block to `timing_chain.json` if a writer for it exists in `src/hf_timestd/core/` (grep `timing_chain.json`); if the writer lives in another repo or module you cannot find in 5 minutes, record that in the report and leave it.

Docs: in `docs/METROLOGY.md` §4.5 (the T3 paragraph), add under its own sub-heading "Self-registration (2026-09-06)":

> T3 places the second boundary from the received tick train itself. The metrology folds the band-limited envelope at one second over 60 to 180 s, fits the peaks to the expected station delays by a common shift, and holds the result in the RTP frame, where the GPSDO keeps it constant within a counter epoch. Each minute's ensembles corroborate or correct it; a counter-epoch change discards it. radiod's `(GPS_TIME, RTP_TIMESNAP)` pair now bounds only the whole second. Until acquisition the station reports `BOOTSTRAP` and promotes no timing. `/run/hf-timestd/registration.json` carries the acquired origin, its σ, the contributing channels and the raw-pair residual; the Offset Judge's `hf_acquired` bench reads it. Design: `docs/superpowers/specs/2026-09-06-t3-self-registration-design.md`.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/unit/test_authority_registration_block.py tests/unit -k authority --override-ini addopts=-ra -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/core/authority_manager.py docs/METROLOGY.md tests/unit/test_authority_registration_block.py
git commit -m "feat(provenance): authority.json carries the registration's source; METROLOGY §4.5 paragraph

Spec §7.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 11: Replay acceptance on ND's chunk (devbox only)

**Files:**
- Create: `tests/unit/test_replay_nd_acquisition.py`
- Create: `scripts/replay-registration.py` (operator tool: run the acquirer over a chunk + sidecar with a label shift; prints the table)

**Interfaces:**
- Consumes: everything above. Fixture: `/home/mjh/hamsci/fixtures/nd-20260906/1788729000.bin.zst` + `.json` (complex64 little-endian IQ at 24 kHz, 600 s, zstd; sidecar keys `gps_time_ns`, `rtp_timesnap`, `start_rtp_timestamp`, `sample_rate`, `minute_boundary`, `frequency_hz`, `station` (receiver dict with lat/lon)).
- Acceptance (spec §8): with the sidecar label shifted by −300, −100, +50, +250 ms, acquisition recovers the shift within ±2 ms inside 180 s, and the fine search on the acquired plane reports σ₁ under 1 ms.

- [ ] **Step 1: Write the replay test**

```python
# tests/unit/test_replay_nd_acquisition.py
"""Spec §8 replay acceptance on ND's own SHARED_10000 chunk (2026-09-06
21:20-21:30Z).  Runs ONLY on the devbox: the fixture lives outside the
repo and the test skips when it is absent.  Never run this on a station."""
import json
import os
from pathlib import Path

import numpy as np
import pytest

FIX = Path(os.environ.get("HF_TIMESTD_ND_FIXTURE", "/home/mjh/hamsci/fixtures/nd-20260906"))
CHUNK = FIX / "1788729000.bin.zst"
SIDECAR = FIX / "1788729000.json"

pytestmark = pytest.mark.skipif(not CHUNK.exists(), reason="ND fixture not present")


@pytest.fixture(scope="module")
def chunk():
    import zstandard
    raw = zstandard.ZstdDecompressor().decompress(CHUNK.read_bytes(), max_output_size=1 << 31)
    iq = np.frombuffer(raw, dtype="<c8")
    meta = json.loads(SIDECAR.read_text())
    return iq, meta


def _engine(meta):
    from hf_timestd.core.metrology_engine import MetrologyEngine
    st = meta["station"]
    return MetrologyEngine(frequency_hz=float(meta["frequency_hz"]),
                           receiver_lat=float(st["lat"]), receiver_lon=float(st["lon"]),
                           sample_rate=int(meta["sample_rate"]))


@pytest.mark.parametrize("shift_ms", [-300.0, -100.0, 50.0, 250.0])
def test_acquisition_recovers_a_shifted_label(chunk, shift_ms):
    import dataclasses
    from hf_timestd.core.buffer_timing import resolve_buffer_timing
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer
    from hf_timestd.core.tick_edge_detector import TickEdgeDetector

    iq, meta = chunk
    sr = int(meta["sample_rate"])
    eng = _engine(meta)
    acq = RegistrationAcquirer("SHARED_10000", sr)
    bt_true = resolve_buffer_timing(meta, sample_rate=sr)
    got = None
    for k in range(3):                              # up to 180 s of bootstrap
        a = k * 60 * sr
        seg = iq[a:a + 62 * sr]
        minute_utc = int(meta["minute_boundary"]) + 60 * k
        label = dataclasses.replace(bt_true, sample0_utc=bt_true.sample0_utc + a / sr + shift_ms / 1000.0)
        audio = eng.prepare_audio(seg)
        delays = eng.expected_delays_s(label.sample0_utc, minute_utc)
        got = acq.offer_minute(audio, label, int(meta["start_rtp_timestamp"]) + a, minute_utc, delays, "ep-nd")
        if got is not None:
            break
    assert got is not None, "no acquisition within 180 s"
    recovered_ms = (got.sample0_utc_for(int(meta["start_rtp_timestamp"]) + a) - (bt_true.sample0_utc + a / sr)) * 1000.0
    assert abs(recovered_ms) <= 2.0, f"acquired plane off truth by {recovered_ms:+.2f} ms"
    # fine search on the acquired plane: sigma_1 under 1 ms
    bt_acq = dataclasses.replace(bt_true, sample0_utc=got.sample0_utc_for(int(meta["start_rtp_timestamp"]) + a),
                                 origin_source="acquired", origin_sigma_ms=got.sigma_ms)
    det = TickEdgeDetector(sample_rate=sr)
    res = det.detect_edges(audio_signal=audio, station="WWV", minute_number=minute_utc,
                           buffer_timing=bt_acq, expected_delay_sec=delays["WWV"],
                           is_dedicated_channel=False, iq_samples=None)
    assert res is not None and res.anchor_source == "acquired"
    assert res.sigma_single_ms < 1.0 and res.n_detected >= 40
```

Match `MetrologyEngine.__init__`'s real parameter names (grep `def __init__` in `metrology_engine.py`; on 2026-09-06 the replay proof built it from the station config — if the constructor needs a config object, build it the way `replay/window_source.py` or `metrology_service.py` does and keep the helper `_engine` local to the test). The truth here is the sidecar plane, which the 2026-09-06 replay proof showed correct to +8.8 ms of WWV timing error; so "within ±2 ms of truth" means within ±2 ms of `bt_true` **after** the fine search's own residual — if the acquired plane lands consistently ~9 ms from `bt_true` but `res.ensemble_timing_error_ms` is then near 0, the acquired plane is *more* right than the sidecar and the assertion should compare `recovered_ms + res.ensemble_timing_error_ms` to the WWV timing error the proof measured (+8.8 ms). Decide from the numbers, record the ruling in the report.

- [ ] **Step 2: Run it**

Run: `.venv/bin/pytest tests/unit/test_replay_nd_acquisition.py --override-ini addopts=-ra -v -s`
Expected: 4 PASS on the devbox (≈ 30–60 s each; the fold is one bandpass and one reshape per band). If `zstandard` is missing from the venv, `.venv/bin/pip install zstandard` and add it to `[project.optional-dependencies] dev` in `pyproject.toml`.

- [ ] **Step 3: Write the operator replay script**

```python
#!/usr/bin/env python3
# scripts/replay-registration.py
"""Replay a raw chunk through the RegistrationAcquirer with a label shift.

    scripts/replay-registration.py CHUNK.bin.zst SIDECAR.json [--shift-ms X ...]

DEVBOX ONLY.  This is the sweep that loaded two station recorders to their
watchdog on 2026-09-06; scp the chunk here and run it here.
"""
import argparse
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import zstandard

from hf_timestd.core.buffer_timing import resolve_buffer_timing
from hf_timestd.core.metrology_engine import MetrologyEngine
from hf_timestd.core.registration_acquirer import RegistrationAcquirer
from hf_timestd.core.tick_edge_detector import TickEdgeDetector


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chunk", type=Path)
    ap.add_argument("sidecar", type=Path)
    ap.add_argument("--shift-ms", type=float, nargs="*", default=[0.0])
    ap.add_argument("--channel", default="SHARED_10000")
    args = ap.parse_args()
    meta = json.loads(args.sidecar.read_text())
    sr = int(meta["sample_rate"])
    iq = np.frombuffer(zstandard.ZstdDecompressor().decompress(
        args.chunk.read_bytes(), max_output_size=1 << 31), dtype="<c8")
    st = meta["station"]
    eng = MetrologyEngine(frequency_hz=float(meta["frequency_hz"]), receiver_lat=float(st["lat"]),
                          receiver_lon=float(st["lon"]), sample_rate=sr)
    bt_true = resolve_buffer_timing(meta, sample_rate=sr)
    det = TickEdgeDetector(sample_rate=sr)
    print(f"{'shift_ms':>9} {'minutes':>7} {'recovered_ms':>13} {'sigma_ms':>9} {'fine_sigma1':>11} {'fine_err_ms':>11}")
    for shift in args.shift_ms:
        acq = RegistrationAcquirer(args.channel, sr)
        got, k = None, -1
        for k in range(min(3, len(iq) // (60 * sr) - 1)):
            a = k * 60 * sr
            seg = iq[a:a + 62 * sr]
            minute_utc = int(meta["minute_boundary"]) + 60 * k
            label = dataclasses.replace(bt_true, sample0_utc=bt_true.sample0_utc + a / sr + shift / 1000.0)
            audio = eng.prepare_audio(seg)
            delays = eng.expected_delays_s(label.sample0_utc, minute_utc)
            got = acq.offer_minute(audio, label, int(meta["start_rtp_timestamp"]) + a, minute_utc, delays, "ep-replay")
            if got is not None:
                break
        if got is None:
            print(f"{shift:>9.1f} {k + 1:>7} {'BOOTSTRAP':>13}")
            continue
        s0 = got.sample0_utc_for(int(meta["start_rtp_timestamp"]) + a)
        rec = (s0 - (bt_true.sample0_utc + a / sr)) * 1000.0
        bt_acq = dataclasses.replace(bt_true, sample0_utc=s0, origin_source="acquired", origin_sigma_ms=got.sigma_ms)
        res = det.detect_edges(audio_signal=audio, station="WWV", minute_number=minute_utc, buffer_timing=bt_acq,
                               expected_delay_sec=delays.get("WWV", 0.0), is_dedicated_channel=False, iq_samples=None)
        fs = f"{res.sigma_single_ms:11.2f} {res.ensemble_timing_error_ms:11.2f}" if res else f"{'none':>11} {'':>11}"
        print(f"{shift:>9.1f} {k + 1:>7} {rec:>13.2f} {got.sigma_ms:>9.2f} {fs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`chmod +x scripts/replay-registration.py`. Run it once on the fixture with `--shift-ms -300 -100 0 50 250` and paste the table into the task report.

- [ ] **Step 4: Run the whole unit suite**

Run: `.venv/bin/pytest tests/unit --override-ini addopts=-ra -q -x`
Expected: green (the pre-existing baseline is green per memory `reference_hf_timestd_suite_green`).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_replay_nd_acquisition.py scripts/replay-registration.py pyproject.toml
git commit -m "test(timing): replay acceptance on ND's SHARED_10000 chunk with shifted labels; devbox replay tool

Spec §8.  Fixture lives outside the repo; the test skips when absent.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH"
```

---

### Task 12: Deploy staging and live acceptance (controller + Michael, not a subagent)

**Files:**
- Create: `~/hf-deploy-20260907-t3-registration.sh` (outside the repo; Michael runs it on ND via `!`)
- No repo files change in this task beyond a `git tag`.

**Steps (controller):**

- [ ] **Step 1: Bus announcement.** Write `/srv/hamsci/claude-bus/$(date -u +%Y%m%dT%H%M%SZ)-mjh.md` announcing: hf-timestd T3 self-registration ready; deploy to ND first (T6-less; the station that lost T3), B4 after 24 h; what changes (metrology processes gain `/run/hf-timestd/registration/*.json` + `registration.json`; core recorder gains the `hf_acquired` judge bench; no chrony, IRQ, affinity or timer changes); rollback = `git checkout <previous tag>` + restart `timestd-metrology.target` and `timestd-core-recorder`. `chown mjh:hamsci; chmod 660`.

- [ ] **Step 2: Stage the deploy script** with the pattern from `~/hf-deploy-20260906-station-web.sh` (git fetch + ff to the tag as the hf-timestd checkout owner; `systemctl restart timestd-metrology.target`; then `timestd-core-recorder` **only after** confirming with Michael on the bus that no A/B window is open — a recorder restart is a pair lottery on today's code and the first minute on the new code). Do not run it. Tell Michael the path and the exact `!` line.

- [ ] **Step 3: Live acceptance on ND (spec §8)**, read-only commands only, each single-shot:
  ```
  journalctl -u 'timestd-metrology@*' --since -10min | grep -E 'ACQUIRED|BOOTSTRAP|registration'
  cat /run/hf-timestd/registration.json | python3 -m json.tool
  sqlite3 /var/lib/timestd/phase2/timestd.db "SELECT MAX(timestamp_utc) FROM l2_timing_measurements"
  chronyc sources; chronyc sourcestats
  ```
  Pass: within three minutes of the metrology restart every audible channel logs `ACQUIRED`, `registration.json` shows `state: ACQUIRED` with `raw_pair_residual_ms` populated, L2 timing rows advance, fusion reaches T3, FUSE returns to selectable. Then wait for the next natural recorder restart and confirm re-acquisition without a second restart.

- [ ] **Step 4: B4 non-regression** after 24 h: T6 stays authoritative; the `hf_acquired` bench residual against T6 (Offset Judge log) stays under 2 ms.

- [ ] **Step 5: Tag and record.** `git tag -a v7.1.0 -m "T3 self-registration"`; push tag and main; memory update (`project_t3_self_registration.md`), bus close-out message.

---

## Self-review

**Spec coverage:** §1 defect → Tasks 2-5 replace the mechanism; §2 rule 1 (acquire) Tasks 2-5, rule 2 (hold in RTP) Task 5 `Registration.sample0_utc_for` + Task 7 tracker, rule 3 (corroborate/correct) Task 5 `corroborate` + Task 8 `feed_back_ensembles`; §3 file list: `registration_acquirer.py` T2-5, `metrology_service.py` T8, `tick_edge_detector.py` T7, `buffer_timing.py` T1, `offset_judge.py` T9, `registration.json` T6+T8 (the per-channel directory is an addition the spec's one-process-per-channel reality forces; noted in the store's docstring); §4 steps 1-6 → T2 (1-3), T3 (4-5), T4 (integer second), T5+T6 (6); BOOTSTRAP state T5, T8 summary; §5 corroborate/correct T5, ambiguity carry T3/T5 (`hypotheses_open`; resolution by fine search happens through `corroborate` — a wrong hypothesis yields junk and never tightens, and the sibling fusion supplies the right one; the marker-tone tie-break is the band choice in `_try_acquire`), counter-epoch step T7+T5+T8, `anchor_source='acquired'` + `timing_admissible` T7; §6 bench T9, T6 override untouched (the engine's anchor inversion still replaces the plane when authoritative — confirm in Task 8 review that `apply_registration` runs *before* the engine, so T6's inversion inside the engine still wins); §7 provenance T6/T8/T10; §8 unit tests T2-T9, replay T11, live T12; §9 out of scope untouched; §10 risks: multipath (peak width test T2), weak nights (180 s extension + BOOTSTRAP T5), BPM collision T3, whole-second T4, drifting filter (3σ×2 rule T5).

**Gaps found and fixed inline:** the spec's "second radiod-channel gets it free" needed the cross-process store (T6) since metrology is one process per channel; `timing_admissible` also had to keep refusing junk on a good plane (T7). Spec §8 "B4's chunk, where the answer is known from T6" is not in T11: no B4 fixture is on the devbox yet; T12 Step 4 covers B4 live instead, and a B4 chunk can be added to the fixture dir later by the same `scp` route.

**Type consistency:** `Registration(counter_epoch_id, rtp_ref, utc_ref, sample_rate, sigma_ms, method, n_minutes, channel, hypotheses_open)` used identically in T5, T6, T8, T9, T10 tests (positional order in T9/T10 tests matches the dataclass order). `offer_minute(audio, label, start_rtp, minute_utc, expected_delays_s, counter_epoch_id)` identical in T5, T8, T11. `fuse_registrations(regs, at_rtp)` T6/T8. `RegistrationStore(directory, summary_path, stale_s, time_fn)` T6/T8/T9/T10. `EdgeEnsembleResult.anchor_sigma_ms` T7/T8/T11. `engine.prepare_audio` / `engine.expected_delays_s(system_time, utc_minute)` T8/T11.
