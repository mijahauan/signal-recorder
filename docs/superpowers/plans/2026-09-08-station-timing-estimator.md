# Station Timing Estimator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a library that tracks one station's sample-counter-to-UTC map as two states, phase and rate, admitting every timing tier as a witness with its own sigma, with no consumers and no station integration.

**Architecture:** A two-state Kalman filter on the RTP sample counter. Phase in nanoseconds against an integer reference plane that rebases each cycle; rate in nanoseconds per second. Process noise reads off a measured Allan deviation, with a documented stand-in floor. A robust admission layer rejects a lone outlier, licenses a phase step only on a concordant quorum after a dwell, and never lets a step become a rate. Six ordered refusals decide whether a solution may be published.

**Tech Stack:** Python 3.10+, numpy, `hamsci_dsp.stability` for Allan deviation, pytest, black, flake8, mypy.

**Spec:** `docs/superpowers/specs/2026-09-08-station-timing-estimator-design.md`

## Global Constraints

- Python `>=3.10`. Type hints throughout. `black` formatting, `flake8` clean, `mypy` clean.
- The package `hf_timestd.estimator` imports **nothing** from `hf_timestd.core`, `hf_timestd.models`, `hf_timestd.interfaces`, `hf_timestd.io` or `hf_timestd.replay`. Only stdlib, numpy, and `hamsci_dsp.stability`. Task 1 installs the test that enforces this.
- No `time.time()`, `time.monotonic()`, `datetime.now()` or `chronyc` anywhere in the package. Every clock reaches the estimator as a sample index inside an observation. The repository's timing-authority invariant in `CLAUDE.md` requires this.
- One convention for elapsed time: sample count divided by the **measured** rate, `f_meas = f_nom * (1 + y)`. Exactly one line in the package divides by the nominal rate, the line that forms `f_meas`. Task 1 installs the test that enforces this.
- Sign convention, copied verbatim from the spec: `y = (f_true - f_nom) / f_nom`, positive when the converter samples fast. The state's rate relates to it by `rate_ns_per_s = -y * 1e9`. One part per million equals 1000 nanoseconds per second.
- Test invocation: this repo sets `addopts = "-ra -q"`, so use `--override-ini=addopts=` when you need the full summary line. Run tests from the repo root with `.venv/bin/python -m pytest`.
- Commits: small and frequent, on `main`, no feature branch. Every commit message ends with these two lines:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014fxKGYhGpcPpYFsPbDj4KH
```

- Numeric constants that mirror values in `hf_timestd.core` get redefined locally with a comment naming their origin, because the package may not import core. Task 3 installs a drift guard that compares them.

---

## File Structure

| file | responsibility |
|---|---|
| `src/hf_timestd/estimator/__init__.py` | public surface; re-exports the estimator, observations, solution |
| `src/hf_timestd/estimator/observations.py` | `PhaseObservation`, `RateObservation`, plane validation |
| `src/hf_timestd/estimator/clock_state.py` | two-state predict, scalar update, exact rebase, projection |
| `src/hf_timestd/estimator/process_noise.py` | Allan deviation to `q1`/`q2`, stand-in floors |
| `src/hf_timestd/estimator/admission.py` | innovation test, per-tier counts, quorum and dwell |
| `src/hf_timestd/estimator/gates.py` | the six ordered refusals |
| `src/hf_timestd/estimator/solution.py` | `TimingSolution`, frozen, with `utc_ns_at` |
| `src/hf_timestd/estimator/estimator.py` | `StationTimingEstimator`: observe, advance, solve |
| `tests/estimator/test_boundaries.py` | import boundary and nominal-rate guards |
| `tests/estimator/test_observations.py` | construction and validation |
| `tests/estimator/test_clock_state.py` | filter mathematics, signs, rebase exactness |
| `tests/estimator/test_process_noise.py` | coefficient recovery, floors, core drift guard |
| `tests/estimator/test_admission.py` | outlier rejection, quorum, dwell |
| `tests/estimator/test_gates.py` | each refusal, and their order |
| `tests/estimator/test_estimator.py` | end-to-end on synthetic witnesses |
| `tests/estimator/test_acceptance_corpus.py` | the spec §8 acceptance table |
| `scripts/build_estimator_corpus.py` | one-time corpus generator, no production role |
| `tests/data/estimator/*.jsonl` | committed witness traces |

---

## Task 1: Package skeleton and the two guard tests

**Files:**
- Create: `src/hf_timestd/estimator/__init__.py`
- Create: `tests/estimator/__init__.py`
- Create: `tests/estimator/test_boundaries.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the package `hf_timestd.estimator`, importable and empty. Both guard tests, which every later task must keep green.

- [ ] **Step 1: Write the failing tests**

Create `tests/estimator/test_boundaries.py`:

```python
"""Guards on the estimator package's boundaries.

The package is a library. It may not reach into the timing core, and it may
not divide by the nominal sample rate anywhere except the one line that
forms the measured rate. Both rules come from the design spec, sections 1
and 7, and both erode one convenience at a time without a test.
"""
import pathlib
import re

import hf_timestd.estimator

PKG_DIR = pathlib.Path(hf_timestd.estimator.__file__).parent

FORBIDDEN_MODULES = (
    "hf_timestd.core",
    "hf_timestd.models",
    "hf_timestd.interfaces",
    "hf_timestd.io",
    "hf_timestd.replay",
)

FORBIDDEN_CLOCKS = (
    "time.time(",
    "time.monotonic(",
    "datetime.now(",
    "utcnow(",
    "chronyc",
)


def _sources():
    return sorted(PKG_DIR.glob("*.py"))


def test_package_has_sources():
    assert _sources(), f"no python sources under {PKG_DIR}"


def test_no_imports_from_the_timing_core():
    offenders = []
    for path in _sources():
        text = path.read_text()
        for module in FORBIDDEN_MODULES:
            if module in text:
                offenders.append(f"{path.name} references {module}")
    assert offenders == [], "\n".join(offenders)


def test_no_host_clock_anywhere_in_the_package():
    offenders = []
    for path in _sources():
        text = path.read_text()
        for token in FORBIDDEN_CLOCKS:
            if token in text:
                offenders.append(f"{path.name} uses {token}")
    assert offenders == [], "\n".join(offenders)


def test_only_one_line_divides_by_the_nominal_rate():
    """Exactly one line may divide by f_nom: the line forming f_meas.

    It carries the marker comment ``# THE ONE NOMINAL DIVISION`` so the test
    can tell the sanctioned line from a new one.
    """
    pattern = re.compile(r"/\s*(self\.)?f_nom\b|/\s*float\(\s*(self\.)?f_nom\s*\)")
    offenders = []
    sanctioned = 0
    for path in _sources():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if not pattern.search(line):
                continue
            if "THE ONE NOMINAL DIVISION" in line:
                sanctioned += 1
                continue
            offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
    assert sanctioned <= 1, f"{sanctioned} lines claim to be the one nominal division"
```

Create `src/hf_timestd/estimator/__init__.py`:

```python
"""One estimator on the ruler: phase, rate, and every tier as a witness.

A library. Nothing here reads a host clock, and nothing here imports the
timing core. See docs/superpowers/specs/2026-09-08-station-timing-estimator-design.md
"""

__all__: list[str] = []
```

Create an empty `tests/estimator/__init__.py`.

- [ ] **Step 2: Run the tests to verify they pass on an empty package**

Run: `.venv/bin/python -m pytest tests/estimator/test_boundaries.py -v`
Expected: 4 passed. The guards are vacuously true now, which is the point. They fail the moment a later task breaches a boundary.

- [ ] **Step 3: Commit**

```bash
git add src/hf_timestd/estimator/__init__.py tests/estimator/
git commit -m "feat(estimator): package skeleton, with the boundary and nominal-rate guards"
```

---

## Task 2: The two observation types

**Files:**
- Create: `src/hf_timestd/estimator/observations.py`
- Create: `tests/estimator/test_observations.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PhaseObservation(tier: str, rtp: int, utc_ns: int, sigma_ns: float, plane: str, source: str)` with property `is_label_plane -> bool`.
  - `RateObservation(tier: str, ppm: float, sigma_ppm: float, span_s: float, n: int, plane: str, source: str)` with properties `ns_per_s -> float` and `sigma_ns_per_s -> float` and `is_label_plane -> bool`.
  - `PLANE_LABEL = "label"`, `PLANE_HOST = "host"`, `NS_PER_S_PER_PPM = 1000.0`.

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_observations.py`:

```python
import pytest

from hf_timestd.estimator.observations import (
    NS_PER_S_PER_PPM,
    PLANE_HOST,
    PLANE_LABEL,
    PhaseObservation,
    RateObservation,
)


def test_a_phase_observation_names_a_sample_and_its_utc():
    obs = PhaseObservation(
        tier="T3", rtp=1_000_000, utc_ns=1_788_729_000_000_000_000,
        sigma_ns=1.0e6, plane=PLANE_LABEL, source="registration",
    )
    assert obs.rtp == 1_000_000
    assert obs.is_label_plane is True


def test_a_host_plane_observation_says_so():
    obs = PhaseObservation(
        tier="T2", rtp=5, utc_ns=7, sigma_ns=25.0e6,
        plane=PLANE_HOST, source="ntp-pool",
    )
    assert obs.is_label_plane is False


def test_a_rate_observation_converts_ppm_to_nanoseconds_per_second():
    """A converter running FAST gives positive ppm and a NEGATIVE state rate.

    Spec section 1: rate_ns_per_s = -y * 1e9, and 1 ppm = 1000 ns/s.
    """
    obs = RateObservation(
        tier="T6", ppm=+2.0, sigma_ppm=0.5, span_s=900.0, n=900,
        plane=PLANE_LABEL, source="t6-residual",
    )
    assert obs.ns_per_s == pytest.approx(-2000.0)
    assert obs.sigma_ns_per_s == pytest.approx(500.0)
    assert NS_PER_S_PER_PPM == 1000.0


def test_a_slow_converter_gives_a_positive_state_rate():
    obs = RateObservation(
        tier="T6", ppm=-60.0, sigma_ppm=1.0, span_s=600.0, n=30,
        plane=PLANE_LABEL, source="fold-drift",
    )
    assert obs.ns_per_s == pytest.approx(+60_000.0)


@pytest.mark.parametrize("plane", ["", "Label", "host ", "anchor"])
def test_an_unknown_plane_is_refused(plane):
    with pytest.raises(ValueError, match="plane"):
        PhaseObservation(tier="T3", rtp=1, utc_ns=2, sigma_ns=1.0,
                         plane=plane, source="x")


@pytest.mark.parametrize("sigma", [0.0, -1.0, float("nan"), float("inf")])
def test_a_useless_sigma_is_refused(sigma):
    with pytest.raises(ValueError, match="sigma"):
        PhaseObservation(tier="T3", rtp=1, utc_ns=2, sigma_ns=sigma,
                         plane=PLANE_LABEL, source="x")


def test_observations_are_frozen():
    obs = PhaseObservation(tier="T3", rtp=1, utc_ns=2, sigma_ns=1.0,
                           plane=PLANE_LABEL, source="x")
    with pytest.raises(Exception):
        obs.rtp = 9  # type: ignore[misc]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/estimator/test_observations.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hf_timestd.estimator.observations'`

- [ ] **Step 3: Write the implementation**

Create `src/hf_timestd/estimator/observations.py`:

```python
"""What a witness may say to the estimator.

Two statements, and no others. A phase observation names a sample and gives
its UTC. A rate observation gives parts per million. Each declares the plane
it was measured on, because a host-plane observation may reach the refusal
gates and must never reach the filter (spec section 3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

PLANE_LABEL = "label"
PLANE_HOST = "host"
_PLANES = (PLANE_LABEL, PLANE_HOST)

# 1 ppm of frequency error walks the phase correction by 1000 ns every second.
# Mirrors PPM_PER_NS_PER_S = 1.0/1000.0 in core/offset_judge.py, redefined here
# because this package may not import the core (spec section 7).
NS_PER_S_PER_PPM = 1000.0


def _check_plane(plane: str) -> None:
    if plane not in _PLANES:
        raise ValueError(f"plane {plane!r} names neither {_PLANES}")


def _check_sigma(sigma: float, what: str) -> None:
    if not math.isfinite(sigma) or sigma <= 0.0:
        raise ValueError(f"{what} sigma {sigma!r} carries no information")


@dataclass(frozen=True)
class PhaseObservation:
    """The sample at ``rtp`` carried UTC ``utc_ns``, to within ``sigma_ns``."""

    tier: str
    rtp: int
    utc_ns: int
    sigma_ns: float
    plane: str
    source: str

    def __post_init__(self) -> None:
        _check_plane(self.plane)
        _check_sigma(self.sigma_ns, "phase")

    @property
    def is_label_plane(self) -> bool:
        return self.plane == PLANE_LABEL


@dataclass(frozen=True)
class RateObservation:
    """The ruler runs ``ppm`` parts per million fast, to within ``sigma_ppm``."""

    tier: str
    ppm: float
    sigma_ppm: float
    span_s: float
    n: int
    plane: str
    source: str

    def __post_init__(self) -> None:
        _check_plane(self.plane)
        _check_sigma(self.sigma_ppm, "rate")

    @property
    def ns_per_s(self) -> float:
        """The state's rate. A fast converter needs a shrinking correction."""
        return -self.ppm * NS_PER_S_PER_PPM

    @property
    def sigma_ns_per_s(self) -> float:
        return self.sigma_ppm * NS_PER_S_PER_PPM

    @property
    def is_label_plane(self) -> bool:
        return self.plane == PLANE_LABEL
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/estimator/ -v`
Expected: all pass, including the four boundary guards.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/estimator/observations.py tests/estimator/test_observations.py
git commit -m "feat(estimator): a witness says one of two things, and names its plane"
```

---

## Task 3: Process noise from the Allan deviation

**Files:**
- Create: `src/hf_timestd/estimator/process_noise.py`
- Create: `tests/estimator/test_process_noise.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `RulerNoise(q1: float, q2: float, source: str)` where `q1` has units ns²/s, `q2` has units ns²/s³, and `source` is `"measured"` or `"standin"`.
  - `RulerNoise.q_matrix(tau_s: float) -> np.ndarray`, the 2x2 process covariance over `tau_s`. Task 4 calls it.
  - `standin_sigma_ppm(provenance: str) -> float`
  - `noise_from_standin(sigma_ppm: float, horizon_s: float = 3600.0) -> RulerNoise`
  - `noise_from_adev(taus, adev, floor: RulerNoise) -> RulerNoise`
  - `SIGMA_PPM_DISCIPLINED_STANDIN = 0.01`, `SIGMA_PPM_UNDISCIPLINED_STANDIN = 2.0`

**Background the implementer needs.** The two-state clock model takes process noise as

    Q(tau) = [[q1*tau + q2*tau**3/3, q2*tau**2/2],
              [q2*tau**2/2,          q2*tau]]

`q1` carries white frequency noise, whose Allan variance falls as `q1/tau`. `q2` carries
random-walk frequency noise, whose Allan variance rises as `q2*tau/3`. Fitting `q1` at the
shortest available tau and `q2` at the longest errs toward a wider, more agile filter in both
cases, never a narrower one, which is the safe direction. The floor exists so a filter can widen
its memory but never narrow it below what the hardware supports.

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_process_noise.py`:

```python
import numpy as np
import pytest

from hf_timestd.estimator.process_noise import (
    SIGMA_PPM_DISCIPLINED_STANDIN,
    SIGMA_PPM_UNDISCIPLINED_STANDIN,
    RulerNoise,
    noise_from_adev,
    noise_from_standin,
    standin_sigma_ppm,
)

NO_FLOOR = RulerNoise(q1=0.0, q2=0.0, source="standin")


def test_white_frequency_noise_recovers_its_own_coefficient():
    """sigma_y(tau) = A / sqrt(tau) implies q1 = A**2 * 1e18."""
    amplitude = 3.0e-9
    taus = np.array([1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
    adev = amplitude / np.sqrt(taus)
    noise = noise_from_adev(taus, adev, floor=NO_FLOOR)
    assert noise.q1 == pytest.approx(amplitude**2 * 1e18, rel=0.01)
    assert noise.source == "measured"


def test_random_walk_frequency_noise_recovers_its_own_coefficient():
    """sigma_y(tau) = B * sqrt(tau) implies q2 = 3 * B**2 * 1e18."""
    amplitude = 2.0e-11
    taus = np.array([10.0, 100.0, 1000.0])
    adev = amplitude * np.sqrt(taus)
    noise = noise_from_adev(taus, adev, floor=NO_FLOOR)
    assert noise.q2 == pytest.approx(3.0 * amplitude**2 * 1e18, rel=0.01)


def test_the_floor_is_never_undercut():
    taus = np.array([1.0, 2.0, 4.0])
    adev = np.array([1e-15, 1e-15, 1e-15])
    floor = RulerNoise(q1=500.0, q2=7.0, source="standin")
    noise = noise_from_adev(taus, adev, floor=floor)
    assert noise.q1 >= floor.q1
    assert noise.q2 >= floor.q2


def test_too_few_points_falls_back_to_the_floor_and_says_so():
    taus = np.array([1.0])
    adev = np.array([1e-12])
    floor = RulerNoise(q1=500.0, q2=7.0, source="standin")
    noise = noise_from_adev(taus, adev, floor=floor)
    assert noise == floor
    assert noise.source == "standin"


def test_a_standin_forgets_back_to_its_sigma_over_the_horizon():
    """With no rate witness for the horizon, rate variance regrows to the stand-in."""
    horizon = 3600.0
    noise = noise_from_standin(SIGMA_PPM_UNDISCIPLINED_STANDIN, horizon_s=horizon)
    sigma_ns_per_s = SIGMA_PPM_UNDISCIPLINED_STANDIN * 1000.0
    assert noise.q2 * horizon == pytest.approx(sigma_ns_per_s**2, rel=1e-9)
    assert noise.q1 == 0.0
    assert noise.source == "standin"


@pytest.mark.parametrize(
    "provenance,expected",
    [
        ("observed", SIGMA_PPM_DISCIPLINED_STANDIN),
        ("attested", SIGMA_PPM_DISCIPLINED_STANDIN),
        ("assumed", SIGMA_PPM_UNDISCIPLINED_STANDIN),
        ("", SIGMA_PPM_UNDISCIPLINED_STANDIN),
        ("nonsense", SIGMA_PPM_UNDISCIPLINED_STANDIN),
    ],
)
def test_an_unstated_ruler_counts_as_undisciplined(provenance, expected):
    """Measurement model section 2: never silently assume discipline."""
    assert standin_sigma_ppm(provenance) == expected


def test_the_standin_numbers_have_not_drifted_from_the_core():
    """This package may not import the core, so a test compares the copies."""
    from hf_timestd.core.t6_holdover import (
        UNMEASURED_RATE_SIGMA_PPM,
        UNMEASURED_RATE_SIGMA_PPM_A0,
    )

    assert SIGMA_PPM_DISCIPLINED_STANDIN == UNMEASURED_RATE_SIGMA_PPM
    assert SIGMA_PPM_UNDISCIPLINED_STANDIN == UNMEASURED_RATE_SIGMA_PPM_A0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/estimator/test_process_noise.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hf_timestd.estimator.process_noise'`

- [ ] **Step 3: Write the implementation**

Create `src/hf_timestd/estimator/process_noise.py`:

```python
"""Process noise, read off the ruler's own Allan deviation.

A governed ruler measures a small deviation, so the filter grows a long
memory and a witness barely nudges the rate. A free-running one measures a
large deviation, so the memory shortens to minutes and the same witnesses
track a rate that actually moves. One mechanism, two regimes, no branch
(spec section 6).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

# Copied from core/t6_holdover.py, which this package may not import.
# A synthesised GPSDO holding an RX888 measures 0.0004 ppm; the stand-in
# below sits 25x above that, and a free-running TCXO runs 0.5 to 2 ppm.
SIGMA_PPM_DISCIPLINED_STANDIN = 0.01
SIGMA_PPM_UNDISCIPLINED_STANDIN = 2.0

_DISCIPLINED_PROVENANCE = ("observed", "attested")
_NS_PER_S_PER_PPM = 1000.0
_MIN_ADEV_POINTS = 2
_DIMENSIONLESS_TO_NS = 1e18  # (ns/s)^2 per (s/s)^2


@dataclass(frozen=True)
class RulerNoise:
    """``q1`` in ns^2/s, ``q2`` in ns^2/s^3, and where they came from."""

    q1: float
    q2: float
    source: str

    def q_matrix(self, tau_s: float) -> np.ndarray:
        """The standard two-state process covariance over ``tau_s``."""
        tau = float(tau_s)
        return np.array(
            [
                [self.q1 * tau + self.q2 * tau**3 / 3.0, self.q2 * tau**2 / 2.0],
                [self.q2 * tau**2 / 2.0, self.q2 * tau],
            ],
            dtype=float,
        )


def standin_sigma_ppm(provenance: str) -> float:
    """An unstated or assumed ruler counts as undisciplined, never otherwise."""
    if provenance in _DISCIPLINED_PROVENANCE:
        return SIGMA_PPM_DISCIPLINED_STANDIN
    return SIGMA_PPM_UNDISCIPLINED_STANDIN


def noise_from_standin(sigma_ppm: float, horizon_s: float = 3600.0) -> RulerNoise:
    """Floor the noise so rate uncertainty regrows to the stand-in over the horizon.

    ``q1`` stays zero deliberately. Phase white-frequency noise on any ruler
    we own sits below every witness sigma we have, and the innovation gate and
    the staleness refusal handle over-confidence in phase.
    """
    sigma_ns_per_s = float(sigma_ppm) * _NS_PER_S_PER_PPM
    return RulerNoise(q1=0.0, q2=sigma_ns_per_s**2 / float(horizon_s), source="standin")


def noise_from_adev(
    taus: Sequence[float], adev: Sequence[float], floor: RulerNoise
) -> RulerNoise:
    """Fit ``q1`` at the shortest tau and ``q2`` at the longest, then floor both.

    Both fits err toward a wider, more agile filter when the noise type does
    not match the region, which keeps the error on the safe side.
    """
    tau_arr = np.asarray(taus, dtype=float)
    adev_arr = np.asarray(adev, dtype=float)
    good = np.isfinite(tau_arr) & np.isfinite(adev_arr) & (tau_arr > 0) & (adev_arr > 0)
    if int(good.sum()) < _MIN_ADEV_POINTS:
        return floor

    tau_arr, adev_arr = tau_arr[good], adev_arr[good]
    order = np.argsort(tau_arr)
    tau_arr, adev_arr = tau_arr[order], adev_arr[order]

    tau_short, adev_short = float(tau_arr[0]), float(adev_arr[0])
    tau_long, adev_long = float(tau_arr[-1]), float(adev_arr[-1])

    q1 = adev_short**2 * tau_short * _DIMENSIONLESS_TO_NS
    q2 = 3.0 * adev_long**2 / tau_long * _DIMENSIONLESS_TO_NS
    if not (math.isfinite(q1) and math.isfinite(q2)):
        return floor
    return RulerNoise(q1=max(q1, floor.q1), q2=max(q2, floor.q2), source="measured")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/estimator/ -v`
Expected: all pass. The boundary guard still passes because the drift-guard import of the core lives in the **test**, not in the package.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/estimator/process_noise.py tests/estimator/test_process_noise.py
git commit -m "feat(estimator): process noise off the measured Allan deviation, floored honestly"
```

---

## Task 4: The clock state, its filter mathematics, and the exact rebase

**Files:**
- Create: `src/hf_timestd/estimator/clock_state.py`
- Create: `tests/estimator/test_clock_state.py`

**Interfaces:**
- Consumes: `RulerNoise` from Task 3.
- Produces `ClockState` with:
  - constructor `ClockState(f_nom: int, rtp_ref: int, utc_ref_ns: int, phase_ns: float = 0.0, rate_ns_per_s: float = 0.0, p: np.ndarray | None = None)`
  - `f_meas -> float`, `rate_ppm -> float`, `sigma_phase_ns -> float`, `sigma_rate_ppm -> float`
  - `elapsed_s(rtp_from: int, rtp_to: int) -> float`
  - `predict(tau_s: float, noise: RulerNoise) -> None`
  - `update(z: float, index: int, r: float) -> float` returning the innovation
  - `innovation(z: float, index: int, r: float) -> tuple[float, float]` returning `(nu, s)` without mutating
  - `utc_ns_at(rtp: int) -> int`
  - `rebase(rtp_now: int) -> None`
  - `reseed_phase(utc_ns: int, rtp: int, sigma_ns: float) -> None`
  - `PHASE, RATE = 0, 1`
  - module-level `signed_rtp_delta(rtp_from: int, rtp_to: int) -> int`, the signed distance across a 32-bit counter wrap. Task 7 consumes it.

**Background the implementer needs.** The RTP counter is 32 bits and wraps, so every difference
of sample indices takes a signed 32-bit wrap, exactly as `core/native_anchor.py` does it:
`delta = ((b - a + 2**31) % 2**32) - 2**31`. Do not import that module; write the three lines.

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_clock_state.py`:

```python
import numpy as np
import pytest

from hf_timestd.estimator.clock_state import PHASE, RATE, ClockState
from hf_timestd.estimator.process_noise import RulerNoise

F_NOM = 24000
QUIET = RulerNoise(q1=0.0, q2=0.0, source="standin")


def fresh(**kw) -> ClockState:
    args = dict(f_nom=F_NOM, rtp_ref=1_000_000, utc_ref_ns=1_788_729_000_000_000_000)
    args.update(kw)
    return ClockState(**args)


def test_a_fresh_state_projects_its_own_reference_exactly():
    st = fresh()
    assert st.utc_ns_at(1_000_000) == 1_788_729_000_000_000_000


def test_one_second_of_samples_advances_utc_by_one_second():
    st = fresh()
    assert st.utc_ns_at(1_000_000 + F_NOM) - st.utc_ns_at(1_000_000) == 1_000_000_000


def test_a_fast_converter_makes_a_second_of_samples_arrive_early():
    """+10 ppm means the ADC samples fast, so 24000 samples take LESS than 1 s."""
    st = fresh(rate_ns_per_s=-10.0 * 1000.0)  # -y*1e9 with y = +10 ppm
    assert st.rate_ppm == pytest.approx(+10.0)
    span = st.utc_ns_at(1_000_000 + F_NOM) - st.utc_ns_at(1_000_000)
    assert span == pytest.approx(1_000_000_000 * (1 - 10e-6), rel=1e-9)


def test_the_counter_wrap_is_signed():
    st = fresh(rtp_ref=2**32 - 100)
    ahead = st.utc_ns_at(50)  # 150 samples past the reference, across the wrap
    assert ahead - st.utc_ns_at(2**32 - 100) == pytest.approx(
        150 * 1e9 / F_NOM, abs=2
    )


def test_predict_walks_phase_by_the_rate():
    st = fresh(rate_ns_per_s=-1000.0)
    st.predict(10.0, QUIET)
    assert st.phase_ns == pytest.approx(-10_000.0)


def test_predict_grows_the_covariance_and_couples_phase_to_rate():
    st = fresh(p=np.diag([100.0, 4.0]))
    st.predict(3.0, QUIET)
    # F P F' with F = [[1, tau], [0, 1]]
    assert st.p[PHASE, PHASE] == pytest.approx(100.0 + 9.0 * 4.0)
    assert st.p[PHASE, RATE] == pytest.approx(3.0 * 4.0)
    assert st.p[RATE, RATE] == pytest.approx(4.0)


def test_process_noise_widens_a_quiet_state():
    st = fresh(p=np.zeros((2, 2)))
    st.predict(10.0, RulerNoise(q1=0.0, q2=2.0, source="standin"))
    assert st.p[RATE, RATE] == pytest.approx(20.0)
    assert st.p[PHASE, PHASE] == pytest.approx(2.0 * 1000.0 / 3.0)


def test_a_perfect_phase_observation_pulls_phase_to_it():
    st = fresh(p=np.diag([1.0e6, 1.0]))
    nu = st.update(z=500.0, index=PHASE, r=1.0e-6)
    assert nu == pytest.approx(500.0)
    assert st.phase_ns == pytest.approx(500.0, rel=1e-3)
    assert st.p[PHASE, PHASE] < 1.0


def test_a_rate_observation_moves_rate_and_leaves_phase_near_where_it_was():
    st = fresh(p=np.diag([1.0, 1.0e6]))
    st.update(z=-60_000.0, index=RATE, r=1.0)
    assert st.rate_ppm == pytest.approx(+60.0, rel=1e-3)
    assert abs(st.phase_ns) < 1.0


def test_the_covariance_stays_symmetric_and_positive_through_many_updates():
    rng = np.random.default_rng(7)
    st = fresh(p=np.diag([1.0e8, 1.0e4]))
    for _ in range(500):
        st.predict(1.0, RulerNoise(q1=1.0, q2=1e-3, source="standin"))
        st.update(z=float(rng.normal(0.0, 1000.0)), index=PHASE, r=1.0e6)
    assert st.p[PHASE, RATE] == pytest.approx(st.p[RATE, PHASE])
    assert np.all(np.linalg.eigvals(st.p) > 0)


def test_innovation_does_not_mutate_the_state():
    st = fresh(p=np.diag([100.0, 1.0]))
    before = (st.phase_ns, st.rate_ns_per_s, st.p.copy())
    nu, s = st.innovation(z=1234.0, index=PHASE, r=25.0)
    assert nu == pytest.approx(1234.0)
    assert s == pytest.approx(125.0)
    assert (st.phase_ns, st.rate_ns_per_s) == before[:2]
    assert np.allclose(st.p, before[2])


def test_a_hundred_thousand_rebases_lose_no_nanoseconds():
    """The reference plane must survive rebasing exactly (spec section 2)."""
    st = fresh(rate_ns_per_s=-1234.5)
    control = fresh(rate_ns_per_s=-1234.5)

    rtp = 1_000_000
    step = 24_007  # deliberately not a whole second of samples
    for _ in range(100_000):
        rtp += step
        st.rebase(rtp)

    # One nanosecond, not zero: the control's single projection is a float at
    # ~1e14 ns, where float64 resolves near 0.015 ns, so it need not round
    # identically to a sum of integers. A biased half-nanosecond error per
    # rebase would reach 50 microseconds here, so 1 ns still proves no
    # accumulation (controller ruling R4, 2026-09-08).
    assert abs(st.utc_ns_at(rtp) - control.utc_ns_at(rtp)) <= 1


def test_a_rebase_changes_no_belief():
    st = fresh(p=np.array([[100.0, 5.0], [5.0, 2.0]]))
    before = st.p.copy()
    st.rebase(1_000_000 + 5 * F_NOM)
    assert np.allclose(st.p, before)


def test_reseeding_phase_leaves_rate_and_its_variance_alone():
    """Spec section 4: a step never becomes a rate."""
    st = fresh(rate_ns_per_s=-750.0, p=np.array([[10.0, 3.0], [3.0, 9.0]]))
    st.reseed_phase(utc_ns=st.utc_ns_at(1_000_000) + 50_000_000, rtp=1_000_000,
                    sigma_ns=2.0e6)
    assert st.rate_ns_per_s == pytest.approx(-750.0)
    assert st.p[RATE, RATE] == pytest.approx(9.0)
    assert st.p[PHASE, RATE] == 0.0
    assert st.p[PHASE, PHASE] == pytest.approx((2.0e6) ** 2)
    assert st.phase_ns == pytest.approx(50_000_000.0, abs=1.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/estimator/test_clock_state.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hf_timestd.estimator.clock_state'`

- [ ] **Step 3: Write the implementation**

Create `src/hf_timestd/estimator/clock_state.py`:

```python
"""Two numbers, a reference plane, and the arithmetic that keeps them exact.

Phase in nanoseconds against an integer plane, and its rate of change in
nanoseconds per second. Elapsed time always means sample count over the
MEASURED rate. The host clock appears nowhere (spec sections 1 and 2).
"""
from __future__ import annotations

import math

import numpy as np

from .process_noise import RulerNoise

PHASE = 0
RATE = 1

_NS_PER_S = 1_000_000_000
_NS_PER_S_PER_PPM = 1000.0
_WRAP = 2**32
_HALF_WRAP = 2**31


def signed_rtp_delta(rtp_from: int, rtp_to: int) -> int:
    """The shortest signed distance across a 32-bit counter wrap."""
    return ((int(rtp_to) - int(rtp_from) + _HALF_WRAP) % _WRAP) - _HALF_WRAP


class ClockState:
    """The station's clock: a plane, a residual, a rate, and a covariance."""

    def __init__(
        self,
        f_nom: int,
        rtp_ref: int,
        utc_ref_ns: int,
        phase_ns: float = 0.0,
        rate_ns_per_s: float = 0.0,
        p: np.ndarray | None = None,
    ) -> None:
        if int(f_nom) <= 0:
            raise ValueError(f"nominal rate {f_nom!r} makes no ruler")
        self.f_nom = int(f_nom)
        self.rtp_ref = int(rtp_ref)
        self.utc_ref_ns = int(utc_ref_ns)
        self.x = np.array([float(phase_ns), float(rate_ns_per_s)], dtype=float)
        self.p = np.eye(2) if p is None else np.array(p, dtype=float)

    # ---- readings -------------------------------------------------------

    @property
    def phase_ns(self) -> float:
        return float(self.x[PHASE])

    @property
    def rate_ns_per_s(self) -> float:
        return float(self.x[RATE])

    @property
    def rate_ppm(self) -> float:
        """Positive when the converter samples fast (spec section 1)."""
        return -self.rate_ns_per_s / _NS_PER_S_PER_PPM

    @property
    def f_meas(self) -> float:
        """The measured sample rate. The one place the nominal rate divides."""
        y = -self.rate_ns_per_s / _NS_PER_S
        return self.f_nom * (1.0 + y)

    @property
    def sigma_phase_ns(self) -> float:
        return math.sqrt(max(float(self.p[PHASE, PHASE]), 0.0))

    @property
    def sigma_rate_ppm(self) -> float:
        return math.sqrt(max(float(self.p[RATE, RATE]), 0.0)) / _NS_PER_S_PER_PPM

    def elapsed_s(self, rtp_from: int, rtp_to: int) -> float:
        """Seconds between two samples, by the measured rate."""
        return signed_rtp_delta(rtp_from, rtp_to) / self.f_meas

    # ---- projection -----------------------------------------------------

    def _projection_ns(self, rtp: int) -> float:
        return _NS_PER_S * signed_rtp_delta(self.rtp_ref, rtp) / self.f_meas

    def utc_ns_at(self, rtp: int) -> int:
        """UTC of the sample at ``rtp``, through the current plane and rate."""
        return self.utc_ref_ns + round(self.phase_ns) + round(self._projection_ns(rtp))

    # ---- the filter -----------------------------------------------------

    def predict(self, tau_s: float, noise: RulerNoise) -> None:
        tau = float(tau_s)
        f = np.array([[1.0, tau], [0.0, 1.0]], dtype=float)
        self.x = f @ self.x
        self.p = f @ self.p @ f.T + noise.q_matrix(tau)
        self._symmetrise()

    def innovation(self, z: float, index: int, r: float) -> tuple[float, float]:
        """``(nu, s)`` for a scalar observation, without touching the state."""
        nu = float(z) - float(self.x[index])
        s = float(self.p[index, index]) + float(r)
        return nu, s

    def update(self, z: float, index: int, r: float) -> float:
        nu, s = self.innovation(z, index, r)
        if s <= 0.0:
            raise ValueError(f"innovation variance {s!r} is not positive")
        k = self.p[:, index] / s
        self.x = self.x + k * nu
        self.p = self.p - np.outer(k, self.p[index, :])
        self._symmetrise()
        return nu

    def _symmetrise(self) -> None:
        self.p = 0.5 * (self.p + self.p.T)

    # ---- plane maintenance ---------------------------------------------

    def rebase(self, rtp_now: int) -> None:
        """Move the plane to ``rtp_now``, keeping the fractional nanosecond."""
        total = self.phase_ns + self._projection_ns(rtp_now)
        whole = math.floor(total)
        self.utc_ref_ns += int(whole)
        self.x[PHASE] = total - whole
        self.rtp_ref = int(rtp_now)

    def reseed_phase(self, utc_ns: int, rtp: int, sigma_ns: float) -> None:
        """Place phase from an observation, and leave the rate exactly alone.

        A wrong lock arrives as a step. Absorbing a step into rate fabricates
        a frequency error and projects it forward forever, so the rate state
        and its variance survive a reseed untouched (spec section 4).
        """
        self.rebase(rtp)
        self.x[PHASE] = float(int(utc_ns) - self.utc_ref_ns)
        self.p[PHASE, PHASE] = float(sigma_ns) ** 2
        self.p[PHASE, RATE] = 0.0
        self.p[RATE, PHASE] = 0.0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/estimator/test_clock_state.py -v`
Expected: all pass.

- [ ] **Step 5: Check the nominal-rate guard still holds**

Run: `.venv/bin/python -m pytest tests/estimator/test_boundaries.py -v`
Expected: pass. If `test_only_one_line_divides_by_the_nominal_rate` fails, the `f_meas` line needs the marker comment appended:

```python
        return self.f_nom * (1.0 + y)  # THE ONE NOMINAL DIVISION
```

Note that `f_meas` multiplies rather than divides, so the guard may report zero sanctioned lines, which passes. Add the marker only if the guard objects.

- [ ] **Step 6: Commit**

```bash
git add src/hf_timestd/estimator/clock_state.py tests/estimator/test_clock_state.py
git commit -m "feat(estimator): the two-state clock, with an exact rebase and a reseed that spares the rate"
```

---

## Task 5: Admission — the outlier, the quorum, and the dwell

**Files:**
- Create: `src/hf_timestd/estimator/admission.py`
- Create: `tests/estimator/test_admission.py`

**Interfaces:**
- Consumes: `PhaseObservation` (Task 2).
- Produces:
  - `AdmissionPolicy(k_accept: float = 3.0, quorum: int = 2, concord_k: float = 3.0, dwell_s: float = 120.0, freshness_s: float = 180.0)`
  - `Verdict(accepted: bool, reason: str, innovation_ns: float, s_ns2: float)` with reasons `"accepted"`, `"host_plane"`, `"outlier"`
  - `StepProposal(implied_error_ns: float, spread_ns: float, tiers: tuple[str, ...])`
  - `Admitter(policy)` with `judge(nu, s, obs, now_s) -> Verdict`, `counts() -> dict[str, dict[str, int]]`, `step(now_s) -> StepProposal | None`, `clear_step()`
  - `Admitter.last_residual_ns: dict[str, float]`

**Background the implementer needs.** The dwell clock runs on the estimator's own ruler time, in
seconds of elapsed sample count. There is no host clock to ask. The caller passes `now_s`.

Concordance copies the test in `core/witness_dissent.py`, which this package may not import:
the spread across dissenting witnesses must stay within `concord_k * (2 * max_sigma)`, floored at
1 ns. Witnesses that disagree with each other are simply all noisy and prove nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_admission.py`:

```python
import pytest

from hf_timestd.estimator.admission import AdmissionPolicy, Admitter
from hf_timestd.estimator.observations import PLANE_HOST, PLANE_LABEL, PhaseObservation

MS = 1_000_000.0


def obs(tier: str, plane: str = PLANE_LABEL, sigma_ns: float = 1.0 * MS):
    return PhaseObservation(tier=tier, rtp=1, utc_ns=2, sigma_ns=sigma_ns,
                            plane=plane, source="test")


def test_an_observation_inside_three_sigmas_is_accepted():
    a = Admitter(AdmissionPolicy())
    v = a.judge(nu=2.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    assert v.accepted is True
    assert v.reason == "accepted"


def test_an_observation_beyond_three_sigmas_is_rejected():
    a = Admitter(AdmissionPolicy())
    v = a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    assert v.accepted is False
    assert v.reason == "outlier"


def test_a_host_plane_observation_never_reaches_the_filter():
    a = Admitter(AdmissionPolicy())
    v = a.judge(nu=0.0, s=1.0, obs=obs("T2", plane=PLANE_HOST, sigma_ns=25 * MS),
                now_s=0.0)
    assert v.accepted is False
    assert v.reason == "host_plane"


def test_counts_are_kept_per_tier():
    a = Admitter(AdmissionPolicy())
    a.judge(nu=0.0, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=1.0)
    a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T6"), now_s=1.0)
    counts = a.counts()
    assert counts["T3"] == {"accepted": 1, "rejected": 1}
    assert counts["T6"] == {"accepted": 0, "rejected": 1}


def test_one_tier_alone_never_proposes_a_step_however_often_it_repeats():
    """Spec section 4: a single tier may never move the plane."""
    a = Admitter(AdmissionPolicy())
    for i in range(1000):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=float(i))
        assert a.step(now_s=float(i)) is None


def test_a_concordant_quorum_proposes_a_step_only_after_the_dwell():
    a = Admitter(AdmissionPolicy(dwell_s=120.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    assert a.step(now_s=0.0) is None
    assert a.step(now_s=119.0) is None
    proposal = a.step(now_s=121.0)
    assert proposal is not None
    assert proposal.implied_error_ns == pytest.approx(50.0 * MS)
    assert set(proposal.tiers) == {"T3", "T5"}


def test_tiers_disagreeing_with_each_other_prove_nothing():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    a.judge(nu=500.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T5"), now_s=0.0)
    assert a.step(now_s=10.0) is None


def test_opposite_directions_prove_nothing():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    a.judge(nu=+50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    a.judge(nu=-50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T5"), now_s=0.0)
    assert a.step(now_s=10.0) is None


def test_a_dissolved_quorum_expires_and_moves_nothing():
    a = Admitter(AdmissionPolicy(dwell_s=120.0, freshness_s=60.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    # One tier comes good again while the other's dissent goes stale.
    a.judge(nu=0.0, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=30.0)
    assert a.step(now_s=200.0) is None


def test_an_accepted_observation_clears_that_tier_from_the_candidate():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    a.judge(nu=0.0, s=(1.0 * MS) ** 2, obs=obs("T5"), now_s=1.0)
    assert a.step(now_s=10.0) is None


def test_clear_step_forgets_the_candidate():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    assert a.step(now_s=10.0) is not None
    a.clear_step()
    assert a.step(now_s=10.0) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/estimator/test_admission.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hf_timestd.estimator.admission'`

- [ ] **Step 3: Write the implementation**

Create `src/hf_timestd/estimator/admission.py`:

```python
"""Who gets to move the plane, and who only gets counted.

A lone witness never moves it, however confident. A quorum that agrees with
itself may, and only after a dwell. And a step, once accepted, changes phase
and never rate (spec section 4).
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .observations import PhaseObservation


@dataclass(frozen=True)
class AdmissionPolicy:
    k_accept: float = 3.0
    quorum: int = 2
    concord_k: float = 3.0
    dwell_s: float = 120.0
    freshness_s: float = 180.0


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str
    innovation_ns: float
    s_ns2: float


@dataclass(frozen=True)
class StepProposal:
    implied_error_ns: float
    spread_ns: float
    tiers: tuple[str, ...]


@dataclass
class _Dissent:
    residual_ns: float
    sigma_ns: float
    at_s: float


@dataclass
class Admitter:
    policy: AdmissionPolicy
    last_residual_ns: dict[str, float] = field(default_factory=dict)
    _counts: dict[str, dict[str, int]] = field(default_factory=dict)
    _dissent: dict[str, _Dissent] = field(default_factory=dict)
    _candidate_since: float | None = None

    def judge(
        self, nu: float, s: float, obs: PhaseObservation, now_s: float
    ) -> Verdict:
        tally = self._counts.setdefault(obs.tier, {"accepted": 0, "rejected": 0})

        if not obs.is_label_plane:
            return Verdict(False, "host_plane", float(nu), float(s))

        self.last_residual_ns[obs.tier] = float(nu)
        if s <= 0.0 or not math.isfinite(s):
            tally["rejected"] += 1
            return Verdict(False, "outlier", float(nu), float(s))

        if abs(nu) <= self.policy.k_accept * math.sqrt(s):
            tally["accepted"] += 1
            self._dissent.pop(obs.tier, None)
            self._reconsider_candidate(now_s)
            return Verdict(True, "accepted", float(nu), float(s))

        tally["rejected"] += 1
        self._dissent[obs.tier] = _Dissent(float(nu), float(obs.sigma_ns), float(now_s))
        self._reconsider_candidate(now_s)
        return Verdict(False, "outlier", float(nu), float(s))

    def counts(self) -> dict[str, dict[str, int]]:
        return {tier: dict(v) for tier, v in self._counts.items()}

    def step(self, now_s: float) -> StepProposal | None:
        """A concordant quorum that has dwelled long enough, or nothing."""
        agreed = self._concordant(now_s)
        if agreed is None:
            return None
        if self._candidate_since is None:
            return None
        if (float(now_s) - self._candidate_since) < self.policy.dwell_s:
            return None
        return agreed

    def clear_step(self) -> None:
        self._dissent.clear()
        self._candidate_since = None

    # ---- internals ------------------------------------------------------

    def _fresh(self, now_s: float) -> dict[str, _Dissent]:
        cutoff = float(now_s) - self.policy.freshness_s
        return {t: d for t, d in self._dissent.items() if d.at_s >= cutoff}

    def _concordant(self, now_s: float) -> StepProposal | None:
        fresh = self._fresh(now_s)
        if len(fresh) < self.policy.quorum:
            return None

        residuals = [d.residual_ns for d in fresh.values()]
        if not (all(r > 0 for r in residuals) or all(r < 0 for r in residuals)):
            return None

        spread = max(residuals) - min(residuals)
        combined = max(d.sigma_ns for d in fresh.values()) * 2.0
        if spread > self.policy.concord_k * max(combined, 1.0):
            return None

        return StepProposal(
            implied_error_ns=float(statistics.median(residuals)),
            spread_ns=float(spread),
            tiers=tuple(sorted(fresh)),
        )

    def _reconsider_candidate(self, now_s: float) -> None:
        if self._concordant(now_s) is None:
            self._candidate_since = None
        elif self._candidate_since is None:
            self._candidate_since = float(now_s)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/estimator/test_admission.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/estimator/admission.py tests/estimator/test_admission.py
git commit -m "feat(estimator): one tier never moves the plane, a concordant quorum may after a dwell"
```

---

## Task 6: The six refusals

**Files:**
- Create: `src/hf_timestd/estimator/gates.py`
- Create: `tests/estimator/test_gates.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `GateConfig(max_phase_age_s: float = 300.0, publish_sigma_max_ns: float = 5.0e6, coarse_k: float = 3.0, rate_alarm_ppm: float = 1.0)`
  - `GateInputs(has_phase: bool, phase_age_s: float, step_pending: bool, sigma_phase_ns: float, coarse_delta_ns: float | None, coarse_sigma_ns: float | None, rate_spread_ppm: float | None)`
  - `refusal(inputs: GateInputs, config: GateConfig) -> str | None`
  - `REFUSAL_ORDER: tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_gates.py`:

```python
import pytest

from hf_timestd.estimator.gates import (
    REFUSAL_ORDER,
    GateConfig,
    GateInputs,
    refusal,
)

MS = 1_000_000.0
CFG = GateConfig()


def clean(**kw) -> GateInputs:
    args = dict(
        has_phase=True,
        phase_age_s=10.0,
        step_pending=False,
        sigma_phase_ns=1.0 * MS,
        coarse_delta_ns=None,
        coarse_sigma_ns=None,
        rate_spread_ppm=None,
    )
    args.update(kw)
    return GateInputs(**args)


def test_a_clean_state_publishes():
    assert refusal(clean(), CFG) is None


def test_no_phase_witness():
    assert refusal(clean(has_phase=False), CFG) == "no_phase_witness"


def test_stale_phase():
    assert refusal(clean(phase_age_s=301.0), CFG) == "stale_phase"


def test_step_pending():
    assert refusal(clean(step_pending=True), CFG) == "step_pending"


def test_variance():
    assert refusal(clean(sigma_phase_ns=5.1 * MS), CFG) == "variance"


def test_coarse_disagreement_beyond_three_combined_sigmas():
    inputs = clean(coarse_delta_ns=100.0 * MS, coarse_sigma_ns=25.0 * MS)
    assert refusal(inputs, CFG) == "coarse_disagreement"


def test_coarse_agreement_inside_the_budget_publishes():
    inputs = clean(coarse_delta_ns=30.0 * MS, coarse_sigma_ns=25.0 * MS)
    assert refusal(inputs, CFG) is None


def test_rate_disagreement_beyond_one_ppm():
    assert refusal(clean(rate_spread_ppm=1.5), CFG) == "rate_disagreement"


def test_rate_agreement_inside_one_ppm_publishes():
    assert refusal(clean(rate_spread_ppm=0.4), CFG) is None


def test_an_unstated_ruler_does_not_refuse():
    """Measurement model section 2: it widens sigma, it does not withhold."""
    assert refusal(clean(), GateConfig()) is None


def test_the_order_is_fixed_and_the_earliest_reason_wins():
    both = clean(has_phase=False, phase_age_s=9e9, step_pending=True,
                 sigma_phase_ns=9e9, coarse_delta_ns=9e9,
                 coarse_sigma_ns=1.0, rate_spread_ppm=9e9)
    assert refusal(both, CFG) == REFUSAL_ORDER[0]


def test_step_pending_outranks_variance():
    inputs = clean(step_pending=True, sigma_phase_ns=9e9)
    assert refusal(inputs, CFG) == "step_pending"
    assert REFUSAL_ORDER.index("step_pending") < REFUSAL_ORDER.index("variance")


def test_every_named_refusal_can_actually_fire():
    fired = set()
    for inputs in (
        clean(has_phase=False),
        clean(phase_age_s=1e9),
        clean(step_pending=True),
        clean(sigma_phase_ns=1e9),
        clean(coarse_delta_ns=1e9, coarse_sigma_ns=1.0),
        clean(rate_spread_ppm=1e9),
    ):
        reason = refusal(inputs, CFG)
        assert reason is not None
        fired.add(reason)
    assert fired == set(REFUSAL_ORDER)


@pytest.mark.parametrize("delta,sigma", [(None, 25.0 * MS), (100.0 * MS, None)])
def test_a_half_reported_coarse_witness_does_not_refuse(delta, sigma):
    assert refusal(clean(coarse_delta_ns=delta, coarse_sigma_ns=sigma), CFG) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/estimator/test_gates.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hf_timestd.estimator.gates'`

- [ ] **Step 3: Write the implementation**

Create `src/hf_timestd/estimator/gates.py`:

```python
"""Six refusals, resolved in order, first match winning.

The estimator publishes a solution every cycle and that solution carries a
verdict. It never withholds silently and never corrects anything: the caller
alarms and withdraws (spec section 5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

REFUSAL_ORDER = (
    "no_phase_witness",
    "stale_phase",
    "step_pending",
    "variance",
    "coarse_disagreement",
    "rate_disagreement",
)


@dataclass(frozen=True)
class GateConfig:
    max_phase_age_s: float = 300.0
    publish_sigma_max_ns: float = 5.0e6
    coarse_k: float = 3.0
    # Matches rate_alarm_ppm in core/offset_judge.py, so one station does not
    # carry two opinions about what a rate disagreement means.
    rate_alarm_ppm: float = 1.0


@dataclass(frozen=True)
class GateInputs:
    has_phase: bool
    phase_age_s: float
    step_pending: bool
    sigma_phase_ns: float
    coarse_delta_ns: float | None
    coarse_sigma_ns: float | None
    rate_spread_ppm: float | None


def refusal(inputs: GateInputs, config: GateConfig) -> str | None:
    """The first reason this solution may not be published, or None."""
    if not inputs.has_phase:
        return "no_phase_witness"

    if inputs.phase_age_s > config.max_phase_age_s:
        return "stale_phase"

    if inputs.step_pending:
        return "step_pending"

    if inputs.sigma_phase_ns > config.publish_sigma_max_ns:
        return "variance"

    delta, sigma = inputs.coarse_delta_ns, inputs.coarse_sigma_ns
    if delta is not None and sigma is not None:
        combined = math.hypot(float(sigma), float(inputs.sigma_phase_ns))
        if abs(float(delta)) > config.coarse_k * combined:
            return "coarse_disagreement"

    spread = inputs.rate_spread_ppm
    if spread is not None and abs(float(spread)) > config.rate_alarm_ppm:
        return "rate_disagreement"

    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/estimator/test_gates.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/estimator/gates.py tests/estimator/test_gates.py
git commit -m "feat(estimator): six refusals in order, and the two that withdraw outright"
```

---

## Task 7: The published solution

**Files:**
- Create: `src/hf_timestd/estimator/solution.py`
- Modify: `src/hf_timestd/estimator/__init__.py`
- Create: `tests/estimator/test_solution.py`

**Interfaces:**
- Consumes: `signed_rtp_delta` from Task 4.
- Produces `TimingSolution`, frozen, with fields `rtp_ref, utc_ref_ns, phase_ns, sigma_phase_ns, rate_ppm, sigma_rate_ppm, rate_samples_per_utc_sec, covariance, verdict, refusal, witnesses, a_level, ruler_provenance, q_source, span_s, n_updates, generation` and method `utc_ns_at(rtp) -> int`; plus `VERDICT_PUBLISH = "publish"`, `VERDICT_WITHHOLD = "withhold"`.

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_solution.py`:

```python
import pytest

from hf_timestd.estimator.solution import (
    VERDICT_PUBLISH,
    VERDICT_WITHHOLD,
    TimingSolution,
)

F_NOM = 24000


def make(**kw) -> TimingSolution:
    args = dict(
        rtp_ref=1_000_000,
        utc_ref_ns=1_788_729_000_000_000_000,
        phase_ns=0.25,
        sigma_phase_ns=1.0e6,
        rate_ppm=+0.03,
        sigma_rate_ppm=0.05,
        rate_samples_per_utc_sec=F_NOM * (1 + 0.03e-6),
        covariance=(1.0e12, 0.0, 2.5e-3),
        verdict=VERDICT_PUBLISH,
        refusal=None,
        witnesses={"T3": {"accepted": 12, "rejected": 0}},
        a_level="A1",
        ruler_provenance="observed",
        q_source="measured",
        span_s=600.0,
        n_updates=12,
        generation=1,
    )
    args.update(kw)
    return TimingSolution(**args)


def test_a_solution_projects_through_its_own_measured_rate():
    sol = make(rate_ppm=+60.0, rate_samples_per_utc_sec=F_NOM * (1 + 60e-6))
    span = sol.utc_ns_at(1_000_000 + F_NOM) - sol.utc_ns_at(1_000_000)
    assert span == pytest.approx(1_000_000_000 * (1 - 60e-6), rel=1e-9)


def test_the_reference_sample_reads_back_the_plane():
    sol = make(phase_ns=0.0)
    assert sol.utc_ns_at(1_000_000) == 1_788_729_000_000_000_000


def test_a_withheld_solution_still_carries_its_numbers_and_its_reason():
    sol = make(verdict=VERDICT_WITHHOLD, refusal="rate_disagreement")
    assert sol.refusal == "rate_disagreement"
    assert sol.rate_ppm == pytest.approx(+0.03)
    assert sol.utc_ns_at(1_000_000 + F_NOM) > sol.utc_ref_ns


def test_a_solution_is_frozen():
    sol = make()
    with pytest.raises(Exception):
        sol.rate_ppm = 9.0  # type: ignore[misc]


def test_a_publishing_solution_carries_no_refusal():
    with pytest.raises(ValueError, match="refusal"):
        make(verdict=VERDICT_PUBLISH, refusal="variance")


def test_a_withholding_solution_must_name_a_reason():
    with pytest.raises(ValueError, match="refusal"):
        make(verdict=VERDICT_WITHHOLD, refusal=None)


def test_the_public_surface_exports_the_solution():
    import hf_timestd.estimator as pkg

    assert "TimingSolution" in pkg.__all__
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/estimator/test_solution.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hf_timestd.estimator.solution'`

- [ ] **Step 3: Write the implementation**

Create `src/hf_timestd/estimator/solution.py`:

```python
"""What the estimator publishes, and the provenance it publishes with it.

Frozen, self-describing, and honest about its own refusal. A withheld
solution still carries every number it has, because a consumer that can see
why an answer was withheld can act; one handed silence cannot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .clock_state import signed_rtp_delta

VERDICT_PUBLISH = "publish"
VERDICT_WITHHOLD = "withhold"

_NS_PER_S = 1_000_000_000


@dataclass(frozen=True)
class TimingSolution:
    rtp_ref: int
    utc_ref_ns: int
    phase_ns: float
    sigma_phase_ns: float
    rate_ppm: float
    sigma_rate_ppm: float
    rate_samples_per_utc_sec: float
    covariance: tuple[float, float, float]
    verdict: str
    refusal: str | None
    witnesses: Mapping[str, Mapping[str, int]]
    a_level: str
    ruler_provenance: str
    q_source: str
    span_s: float
    n_updates: int
    generation: int

    def __post_init__(self) -> None:
        if self.verdict == VERDICT_PUBLISH and self.refusal is not None:
            raise ValueError(f"a publishing solution carries a refusal: {self.refusal}")
        if self.verdict == VERDICT_WITHHOLD and self.refusal is None:
            raise ValueError("a withholding solution names no refusal")
        if self.verdict not in (VERDICT_PUBLISH, VERDICT_WITHHOLD):
            raise ValueError(f"verdict {self.verdict!r} names neither outcome")

    def utc_ns_at(self, rtp: int) -> int:
        """UTC of the sample at ``rtp``, through this plane and measured rate."""
        delta = signed_rtp_delta(self.rtp_ref, rtp)
        projection = _NS_PER_S * delta / self.rate_samples_per_utc_sec
        return self.utc_ref_ns + round(self.phase_ns) + round(projection)
```

Replace `src/hf_timestd/estimator/__init__.py` with:

```python
"""One estimator on the ruler: phase, rate, and every tier as a witness.

A library. Nothing here reads a host clock, and nothing here imports the
timing core. See docs/superpowers/specs/2026-09-08-station-timing-estimator-design.md
"""
from .observations import (
    PLANE_HOST,
    PLANE_LABEL,
    PhaseObservation,
    RateObservation,
)
from .solution import VERDICT_PUBLISH, VERDICT_WITHHOLD, TimingSolution

__all__ = [
    "PLANE_HOST",
    "PLANE_LABEL",
    "PhaseObservation",
    "RateObservation",
    "TimingSolution",
    "VERDICT_PUBLISH",
    "VERDICT_WITHHOLD",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/estimator/ -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/hf_timestd/estimator/solution.py src/hf_timestd/estimator/__init__.py tests/estimator/test_solution.py
git commit -m "feat(estimator): the published solution carries its rate, its refusal and its provenance"
```

---

## Task 8: The estimator itself

**Files:**
- Create: `src/hf_timestd/estimator/estimator.py`
- Modify: `src/hf_timestd/estimator/__init__.py`
- Create: `tests/estimator/test_estimator.py`

**Interfaces:**
- Consumes: everything from Tasks 2 through 7.
- Produces:
  - `EstimatorConfig(gates: GateConfig, admission: AdmissionPolicy, adev_refit_every: int = 60, adev_min_points: int = 20, standin_horizon_s: float = 3600.0, a1_max_ppm: float = 0.05)`
  - `StationTimingEstimator(f_nom: int, ruler_provenance: str = "assumed", config: EstimatorConfig | None = None)` with:
    - `observe(obs: PhaseObservation | RateObservation) -> Verdict`
    - `advance(rtp: int) -> None`
    - `solve(rtp: int) -> TimingSolution`
    - `note_counter_epoch_change(why: str) -> None`
    - `generation -> int`

**Behaviour the implementer must get right.**

1. **Seeding.** The first accepted label-plane phase observation sets the plane exactly:
   `rtp_ref = obs.rtp`, `utc_ref_ns = obs.utc_ns`, `phase_ns = 0`, `P[0,0] = sigma_ns**2`,
   `P[1,1] = (standin_sigma_ppm * 1000)**2`, `P[0,1] = P[1,0] = 0`, rate `0`. Before that seed
   there is no state, so `observe` on a rate observation records it and returns a verdict with
   reason `"no_plane"`, and `solve` refuses with `no_phase_witness`.
2. **Ruler time.** The estimator keeps `_ruler_s`, the cumulative elapsed time since the seed,
   advanced by `ClockState.elapsed_s` on every `advance` and on every observation whose `rtp`
   moves forward. Every dwell, age and span uses `_ruler_s`. No host clock.
3. **Host-plane observations** feed the coarse gate: store `coarse_delta_ns = obs.utc_ns -
   utc_ns_at(obs.rtp)` and `coarse_sigma_ns = obs.sigma_ns`, keeping only the newest.
4. **Rate spread.** Keep the newest rate observation per source. `rate_spread_ppm` is the widest
   pairwise difference among label-plane sources, or `None` with fewer than two.
5. **Step handling in `solve`.** Ask `Admitter.step(_ruler_s)`. A proposal means reseed phase to
   `utc_ns_at(rtp) + implied_error_ns` with `sigma_ns = max(spread, smallest witness sigma)`,
   then `clear_step()`, then publish. Until the dwell elapses, refuse with `step_pending`.
6. **Allan deviation.** Append `(ruler_s, accepted phase innovation in seconds)` to a residual
   series. Every `adev_refit_every` accepted phase observations, if the series holds at least
   `adev_min_points`, call `hamsci_dsp.stability.compute_phase_adev(phase, tau0)` with `tau0`
   the median spacing, then `noise_from_adev`. Floor with `noise_from_standin`.
7. **A-level.** `"A1"` when `abs(rate_ppm) <= a1_max_ppm` and `sigma_rate_ppm <= a1_max_ppm`,
   else `"A0"`. Diagnosis only. Nothing branches on it.

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_estimator.py`:

```python
"""End-to-end behaviour on synthetic witnesses.

The synthetic station has a ruler running a chosen number of parts per
million and a witness that reports the true UTC of a named sample with a
chosen sigma. Everything the estimator learns, it learns from those reports.
"""
import numpy as np
import pytest

from hf_timestd.estimator.estimator import StationTimingEstimator
from hf_timestd.estimator.observations import (
    PLANE_HOST,
    PLANE_LABEL,
    PhaseObservation,
    RateObservation,
)
from hf_timestd.estimator.solution import VERDICT_PUBLISH, VERDICT_WITHHOLD

F_NOM = 24000
MS = 1_000_000.0
T0_NS = 1_788_729_000_000_000_000


class Station:
    """A ruler running ``ppm`` fast, and truthful witnesses on it."""

    def __init__(self, ppm: float, rtp0: int = 1_000_000):
        self.ppm = float(ppm)
        self.rtp0 = int(rtp0)

    def true_utc_ns(self, rtp: int) -> int:
        f_true = F_NOM * (1.0 + self.ppm * 1e-6)
        return T0_NS + round(1e9 * (rtp - self.rtp0) / f_true)

    def phase(self, rtp: int, tier: str = "T3", sigma_ns: float = 1.0 * MS,
              error_ns: float = 0.0, rng=None) -> PhaseObservation:
        noise = 0.0 if rng is None else float(rng.normal(0.0, sigma_ns))
        return PhaseObservation(
            tier=tier, rtp=int(rtp),
            utc_ns=self.true_utc_ns(rtp) + round(error_ns + noise),
            sigma_ns=sigma_ns, plane=PLANE_LABEL, source="synthetic",
        )


def minute_marks(n_minutes: int, rtp0: int = 1_000_000):
    return [rtp0 + m * 60 * F_NOM for m in range(n_minutes)]


def test_a_fresh_estimator_refuses_for_want_of_a_witness():
    est = StationTimingEstimator(f_nom=F_NOM)
    sol = est.solve(1_000_000)
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "no_phase_witness"


def test_the_first_witness_seeds_the_plane_exactly():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    obs = st.phase(st.rtp0)
    est.observe(obs)
    sol = est.solve(st.rtp0)
    assert sol.utc_ns_at(st.rtp0) == obs.utc_ns


def test_it_recovers_a_sixty_ppm_ruler_from_ten_minutes_of_witnesses():
    """The headline capability: rate from phase drift alone."""
    st = Station(ppm=-60.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp, sigma_ns=1.0 * MS))
        est.advance(rtp)
    sol = est.solve(minute_marks(11)[-1])
    assert sol.rate_ppm == pytest.approx(-60.0, abs=1.0)


def test_it_recovers_a_governed_ruler_as_near_zero():
    st = Station(ppm=+0.03)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    rng = np.random.default_rng(3)
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp, sigma_ns=0.15 * MS, rng=rng))
        est.advance(rtp)
    sol = est.solve(minute_marks(11)[-1])
    assert abs(sol.rate_ppm) < 0.5


def test_the_published_rate_and_the_projection_agree():
    st = Station(ppm=-60.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    sol = est.solve(minute_marks(11)[-1])
    implied = (sol.rate_samples_per_utc_sec / F_NOM - 1.0) * 1e6
    assert implied == pytest.approx(sol.rate_ppm, rel=1e-6)


def test_a_lone_tier_repeating_a_fifty_millisecond_error_moves_nothing():
    """The regression test for 2026-09-07 (spec section 4)."""
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp, tier="T3", sigma_ns=1.0 * MS))
        est.advance(rtp)
    before = est.solve(minute_marks(6)[-1])

    liar = minute_marks(30)[6:]
    for rtp in liar:
        est.observe(st.phase(rtp, tier="T3", sigma_ns=1.0 * MS, error_ns=50.0 * MS))
        est.advance(rtp)
    after = est.solve(liar[-1])

    assert abs(after.rate_ppm - before.rate_ppm) < 0.1
    assert after.witnesses["T3"]["rejected"] >= 20


@pytest.mark.parametrize("lattice_ms", [18.7, 34.0, 50.0])
def test_no_lattice_confusion_from_one_tier_moves_the_plane(lattice_ms):
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp, tier="T3"))
        est.advance(rtp)
    settled = est.solve(minute_marks(6)[-1])

    for rtp in minute_marks(20)[6:]:
        est.observe(st.phase(rtp, tier="T3", error_ns=lattice_ms * MS))
        est.advance(rtp)
    after = est.solve(minute_marks(20)[-1])

    assert abs(after.utc_ns_at(st.rtp0) - settled.utc_ns_at(st.rtp0)) < 5 * MS


def test_a_concordant_quorum_moves_the_plane_and_spares_the_rate():
    st = Station(ppm=-20.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(8):
        est.observe(st.phase(rtp, tier="T3"))
        est.advance(rtp)
    settled = est.solve(minute_marks(8)[-1])

    # Two tiers now agree that the plane sits 40 ms out, for five minutes.
    for rtp in minute_marks(14)[8:]:
        for tier in ("T3", "T5"):
            est.observe(st.phase(rtp, tier=tier, error_ns=40.0 * MS))
        est.advance(rtp)
    after = est.solve(minute_marks(14)[-1])

    assert after.verdict == VERDICT_PUBLISH
    assert abs(after.rate_ppm - settled.rate_ppm) < 0.1


def test_a_host_plane_witness_never_enters_the_state():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    before = est.solve(minute_marks(6)[-1])

    verdict = est.observe(PhaseObservation(
        tier="T2", rtp=minute_marks(6)[-1],
        utc_ns=st.true_utc_ns(minute_marks(6)[-1]) + round(20.0 * MS),
        sigma_ns=25.0 * MS, plane=PLANE_HOST, source="ntp-pool",
    ))
    after = est.solve(minute_marks(6)[-1])

    assert verdict.accepted is False
    assert verdict.reason == "host_plane"
    assert after.phase_ns == pytest.approx(before.phase_ns, abs=1.0)


def test_a_wildly_disagreeing_coarse_witness_withdraws_the_solution():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    rtp = minute_marks(6)[-1]
    est.observe(PhaseObservation(
        tier="T2", rtp=rtp,
        utc_ns=st.true_utc_ns(rtp) + round(400.0 * MS),
        sigma_ns=25.0 * MS, plane=PLANE_HOST, source="ntp-pool",
    ))
    sol = est.solve(rtp)
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "coarse_disagreement"


def test_two_rate_witnesses_that_disagree_withdraw_the_solution():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    for ppm, source in ((+0.0, "t6-residual"), (+5.0, "fold-drift")):
        est.observe(RateObservation(
            tier="T6", ppm=ppm, sigma_ppm=0.1, span_s=900.0, n=900,
            plane=PLANE_LABEL, source=source,
        ))
    sol = est.solve(minute_marks(6)[-1])
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "rate_disagreement"


def test_a_stale_witness_withdraws_the_solution():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(3):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    far = minute_marks(3)[-1] + 400 * F_NOM  # more than 300 s of samples later
    est.advance(far)
    sol = est.solve(far)
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "stale_phase"


def test_a_counter_epoch_change_drops_phase_and_keeps_rate():
    st = Station(ppm=-30.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    before = est.solve(minute_marks(11)[-1])

    est.note_counter_epoch_change("recorder announced a new counter space")
    assert est.generation == before.generation + 1
    assert est.solve(minute_marks(11)[-1]).refusal == "no_phase_witness"

    st2 = Station(ppm=-30.0, rtp0=5_000_000)
    est.observe(st2.phase(st2.rtp0))
    after = est.solve(st2.rtp0)
    assert after.rate_ppm == pytest.approx(before.rate_ppm, abs=0.5)


def test_the_a_level_describes_the_ruler_and_nothing_branches_on_it():
    st = Station(ppm=-60.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    assert est.solve(minute_marks(11)[-1]).a_level == "A0"

    governed = Station(ppm=0.0)
    est2 = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    for rtp in minute_marks(31):
        est2.observe(governed.phase(rtp, sigma_ns=0.1 * MS))
        est2.advance(rtp)
    assert est2.solve(minute_marks(31)[-1]).a_level == "A1"


def test_the_process_noise_source_turns_measured_once_the_span_allows():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    rng = np.random.default_rng(11)
    early = est.solve(st.rtp0)
    assert early.q_source == "standin"
    for rtp in minute_marks(90):
        est.observe(st.phase(rtp, sigma_ns=0.5 * MS, rng=rng))
        est.advance(rtp)
    assert est.solve(minute_marks(90)[-1]).q_source == "measured"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/estimator/test_estimator.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hf_timestd.estimator.estimator'`

- [ ] **Step 3: Write the implementation**

Create `src/hf_timestd/estimator/estimator.py`. Follow the seven numbered behaviours above. The
shape:

```python
"""One estimator per station, on the ruler.

Three verbs. ``observe`` takes a witness statement, ``advance`` predicts to a
sample index, ``solve`` returns a solution and rebases. No thread owns this
object; the caller holds whatever lock it already holds.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import numpy as np
from hamsci_dsp.stability import compute_phase_adev

from .admission import AdmissionPolicy, Admitter, Verdict
from .clock_state import PHASE, RATE, ClockState
from .gates import GateConfig, GateInputs, refusal
from .observations import PhaseObservation, RateObservation
from .process_noise import (
    RulerNoise,
    noise_from_adev,
    noise_from_standin,
    standin_sigma_ppm,
)
from .solution import VERDICT_PUBLISH, VERDICT_WITHHOLD, TimingSolution

_NS_PER_S_PER_PPM = 1000.0


@dataclass(frozen=True)
class EstimatorConfig:
    gates: GateConfig = field(default_factory=GateConfig)
    admission: AdmissionPolicy = field(default_factory=AdmissionPolicy)
    adev_refit_every: int = 60
    adev_min_points: int = 20
    standin_horizon_s: float = 3600.0
    a1_max_ppm: float = 0.05


class StationTimingEstimator:
    def __init__(
        self,
        f_nom: int,
        ruler_provenance: str = "assumed",
        config: EstimatorConfig | None = None,
    ) -> None:
        self.f_nom = int(f_nom)
        self.ruler_provenance = str(ruler_provenance)
        self.config = config or EstimatorConfig()
        self._admitter = Admitter(self.config.admission)
        self._standin = noise_from_standin(
            standin_sigma_ppm(self.ruler_provenance),
            horizon_s=self.config.standin_horizon_s,
        )
        self._noise = self._standin
        self._state: ClockState | None = None
        self._generation = 0
        self._ruler_s = 0.0
        self._last_rtp: int | None = None
        self._last_phase_at_s: float | None = None
        self._n_updates = 0
        self._seed_s = 0.0
        self._residuals: list[tuple[float, float]] = []
        self._since_refit = 0
        self._coarse: tuple[float, float] | None = None
        self._rates: dict[str, float] = {}

    @property
    def generation(self) -> int:
        return self._generation

    # ---- the three verbs ------------------------------------------------

    def observe(self, obs) -> Verdict: ...
    def advance(self, rtp: int) -> None: ...
    def solve(self, rtp: int) -> TimingSolution: ...
    def note_counter_epoch_change(self, why: str) -> None: ...
```

Fill each verb per the behaviour list. Points that the tests pin down and that are easy to get
wrong:

- `advance(rtp)` computes `tau = state.elapsed_s(self._last_rtp, rtp)`, refuses a negative tau by
  returning without change, then calls `state.predict(tau, self._noise)`, adds tau to
  `_ruler_s`, and sets `_last_rtp = rtp`.
- `observe` on a `PhaseObservation` first advances to `obs.rtp` when the state exists, then
  computes `z = obs.utc_ns - state.utc_ns_at(obs.rtp) + state.phase_ns`, because the filter's
  phase state lives against the plane and the observation speaks in absolute UTC.
- On acceptance, call `state.update(z, PHASE, obs.sigma_ns**2)`, record
  `_last_phase_at_s = _ruler_s`, increment `_n_updates`, append the innovation in seconds to
  `_residuals`, and consider a refit.
- `observe` on a `RateObservation` records `self._rates[obs.source] = obs.ppm` for the spread
  gate, and when label-plane and the state exists, calls
  `state.update(obs.ns_per_s, RATE, obs.sigma_ns_per_s**2)`.
- `note_counter_epoch_change` keeps `state.x[RATE]` and `state.p[RATE, RATE]`, drops everything
  else by setting `_state = None` and stashing the surviving rate so the next seed restores it,
  and increments `_generation`.
- `solve(rtp)` advances to `rtp`, handles a step proposal, rebases, builds `GateInputs`, calls
  `refusal`, and returns the frozen solution with `witnesses=self._admitter.counts()`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/estimator/test_estimator.py -v`
Expected: all pass. Where a tolerance genuinely cannot be met, do not widen it silently. Report
the number you got, and treat a disagreement with the spec as a finding.

- [ ] **Step 5: Export the estimator**

Add to `src/hf_timestd/estimator/__init__.py`:

```python
from .estimator import EstimatorConfig, StationTimingEstimator
```

and extend `__all__` with `"EstimatorConfig"` and `"StationTimingEstimator"`.

- [ ] **Step 6: Run the whole suite and the boundary guards**

Run: `.venv/bin/python -m pytest tests/estimator/ -v`
Expected: all pass, including the four guards. The `hamsci_dsp` import is allowed; a
`hf_timestd.core` import is not.

- [ ] **Step 7: Commit**

```bash
git add src/hf_timestd/estimator/estimator.py src/hf_timestd/estimator/__init__.py tests/estimator/test_estimator.py
git commit -m "feat(estimator): one estimator per station, three verbs, and the rate it learns from drift"
```

---

## Task 9: The corpus generator

**Files:**
- Create: `scripts/build_estimator_corpus.py`
- Create: `tests/data/estimator/*.jsonl` (generated, then committed)

**Interfaces:**
- Consumes: nothing from the estimator package. This script may import `hf_timestd.core`, because
  it holds no production role and does not ship inside the package.
- Produces: one JSON-lines file per fixture channel, each line
  `{"tier": "T3", "rtp": <int>, "utc_ns": <int>, "sigma_ns": <float>, "plane": "label",
  "source": "fold-peak", "band": "1000", "fixture": "nd-20260906"}`.
  The `fixture` field carries the fixture name plus any resampling suffix, and Task 10 selects on
  it rather than on the filename. Filename prefixes cross-match: a glob for `nd-20260906` also
  catches `nd-20260906-bad` and `nd-20260906-resampled-60ppm` (controller ruling R2, 2026-09-08).

**What the generator measures, and what it cannot.** It folds the tick envelope in short blocks
and takes the peak position. That gives phase against the ruler up to one unknown constant, the
propagation delay plus the station's identity offset. The constant cancels in a slope, so the
corpus measures rate honestly and measures absolute phase not at all. Every acceptance row in
Task 10 respects that limit.

**Method, verified on 2026-09-08.** Twenty-second blocks on the ND and B4 fixtures gave
+0.03 ppm, +0.12 ppm and -0.16 ppm with fit residuals of 0.05 to 0.15 ms, so the approach works
and its slope uncertainty sits near 0.15 ppm at these spans.

- [ ] **Step 1: Write the generator**

Create `scripts/build_estimator_corpus.py`:

```python
#!/usr/bin/env python3
"""Build witness traces for the estimator's acceptance tests. One-time tool.

Reads a fixture's compressed IQ and sidecar, folds the tick envelope in short
blocks, and writes one phase observation per block per band. The absolute UTC
carries an unknown constant (propagation plus station identity), so the traces
support rate and behaviour tests and never an absolute accuracy claim.

Usage:
    python scripts/build_estimator_corpus.py FIXTURE_DIR OUT_DIR [--resample-ppm N]
"""
from __future__ import annotations

import argparse
import json
import pathlib

import numpy as np
import zstandard

from hf_timestd.core.registration_acquirer import band_envelopes, fold_envelope

BLOCK_S = 20
MIN_SNR = 1.5
SIGMA_NS = 1_000_000.0  # 1 ms, the acquirer's own origin sigma floor


def read_iq(path: pathlib.Path) -> np.ndarray:
    with open(path, "rb") as fh:
        raw = zstandard.ZstdDecompressor().stream_reader(fh).read()
    return np.frombuffer(raw, dtype=np.complex64)


def resample_ppm(iq: np.ndarray, ppm: float) -> np.ndarray:
    """Stretch the signal as a ruler error of ``ppm`` would, by interpolation.

    A converter running ``ppm`` fast produces this many more samples per real
    second, so the same real signal lands on a longer index axis.
    """
    n_out = int(round(len(iq) * (1.0 + ppm * 1e-6)))
    src = np.arange(len(iq), dtype=np.float64)
    dst = np.linspace(0.0, len(iq) - 1.0, n_out)
    return (np.interp(dst, src, iq.real) + 1j * np.interp(dst, src, iq.imag)).astype(
        np.complex64
    )


def trace(iq: np.ndarray, meta: dict, fixture: str, block_s: int = BLOCK_S):
    fs = int(meta["sample_rate"])
    label0 = float(meta["start_system_time"])
    rtp0 = int(meta["start_rtp_timestamp"])
    out = []
    for b in range(len(iq) // (block_s * fs)):
        seg = np.abs(iq[b * block_s * fs : (b + 1) * block_s * fs]).astype(np.float64)
        seg -= seg.mean()
        for band, env in band_envelopes(seg, fs).items():
            profile, rows = fold_envelope(env, fs, label0 + b * block_s, block_s)
            if rows == 0:
                continue
            peak = int(np.argmax(profile))
            snr = float(profile[peak] / (np.median(profile) + 1e-12))
            if snr < MIN_SNR:
                continue
            mid_rtp = rtp0 + (b * block_s + block_s // 2) * fs
            second = int(np.floor(label0 + b * block_s + block_s // 2))
            out.append(
                {
                    "tier": "T3",
                    "rtp": int(mid_rtp),
                    "utc_ns": int(second * 1_000_000_000 + peak * 1_000_000_000 // fs),
                    "sigma_ns": SIGMA_NS,
                    "plane": "label",
                    "source": "fold-peak",
                    "band": band,
                    "snr": snr,
                    "fixture": fixture,
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture_dir", type=pathlib.Path)
    ap.add_argument("out_dir", type=pathlib.Path)
    ap.add_argument("--resample-ppm", type=float, default=None)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for sidecar in sorted(args.fixture_dir.glob("*.json")):
        binary = sidecar.with_suffix(".bin.zst")
        if not binary.exists():
            continue
        meta = json.loads(sidecar.read_text())
        iq = read_iq(binary)
        suffix = ""
        if args.resample_ppm is not None:
            iq = resample_ppm(iq, args.resample_ppm)
            suffix = f"-resampled{args.resample_ppm:+g}ppm"
        fixture = f"{args.fixture_dir.name}{suffix}"
        rows = trace(iq, meta, fixture)
        name = f"{fixture}-{meta['channel_name']}.jsonl"
        (args.out_dir / name).write_text(
            "".join(json.dumps(r) + "\n" for r in rows)
        )
        print(f"{name}: {len(rows)} observations")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the four real corpora**

```bash
for d in nd-20260906 nd-20260906-bad b4-20260906-day b4-20260907; do
  .venv/bin/python scripts/build_estimator_corpus.py \
    /home/mjh/hamsci/fixtures/$d tests/data/estimator
done
```

Expected: one file per fixture channel, each with tens of observations. `b4-20260907` may produce
few or none on the 20 MHz channel, which is a known dead receive chain and not a bug in this
tool.

- [ ] **Step 3: Generate the known-truth resampled corpus**

```bash
.venv/bin/python scripts/build_estimator_corpus.py \
  /home/mjh/hamsci/fixtures/nd-20260906 tests/data/estimator --resample-ppm -60
```

- [ ] **Step 4: Check the corpora are small enough to commit**

Run: `du -sh tests/data/estimator && wc -l tests/data/estimator/*.jsonl`
Expected: kilobytes, not megabytes. If any file exceeds about 200 kB, raise `BLOCK_S` and
regenerate rather than committing bulk.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_estimator_corpus.py tests/data/estimator
git commit -m "test(estimator): witness traces from the saved fixtures, and a known-truth resampling"
```

---

## Task 10: The acceptance table

**Files:**
- Create: `tests/estimator/test_acceptance_corpus.py`

**Interfaces:**
- Consumes: `StationTimingEstimator` (Task 8) and the corpora (Task 9).
- Produces: the spec §8 acceptance table, executable.

- [ ] **Step 1: Write the failing test**

Create `tests/estimator/test_acceptance_corpus.py`:

```python
"""The spec section 8 acceptance table, executed against the saved corpora.

Each row tests rate, self-consistency or refusal behaviour. None tests
absolute UTC, because the corpus carries an unknown constant offset by
construction: propagation delay plus the station's identity.
"""
import json
import pathlib

import pytest

from hf_timestd.estimator.estimator import StationTimingEstimator
from hf_timestd.estimator.observations import PhaseObservation

CORPUS = pathlib.Path(__file__).parent.parent / "data" / "estimator"
MS = 1_000_000.0
F_NOM = 24000

# fixture stem, band, the ruler measured from the signal on 2026-09-08, tolerance
ROWS = [
    ("nd-20260906", "1000", +0.03, 0.2),
    ("nd-20260906-bad", "1200", +0.12, 0.2),
    ("b4-20260906-day", "1000", -0.16, 0.2),
    ("nd-20260906-resampled-60ppm", "1000", -60.0, 1.0),
]


def load(stem: str, band: str) -> list[PhaseObservation]:
    """Rows for one fixture and one band, selected on the row's own fields.

    Never select on the filename: a prefix glob for ``nd-20260906`` also
    catches ``nd-20260906-bad`` and the resampled corpus.
    """
    paths = sorted(CORPUS.glob("*.jsonl"))
    if not paths:
        pytest.skip("no corpus; run scripts/build_estimator_corpus.py")
    rows = []
    for path in paths:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("fixture") == stem and row.get("band") == band:
                rows.append(row)
    if len(rows) < 8:
        pytest.skip(f"corpus {stem} band {band} holds {len(rows)} rows, too few")
    rows.sort(key=lambda r: r["rtp"])
    return [
        PhaseObservation(
            tier=r["tier"], rtp=r["rtp"], utc_ns=r["utc_ns"],
            sigma_ns=r["sigma_ns"], plane=r["plane"], source=r["source"],
        )
        for r in rows
    ]


def drive(observations):
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for obs in observations:
        est.observe(obs)
        est.advance(obs.rtp)
    return est, est.solve(observations[-1].rtp)


@pytest.mark.parametrize("stem,band,expected_ppm,tolerance", ROWS)
def test_the_estimator_recovers_each_corpus_ruler(stem, band, expected_ppm, tolerance):
    _, sol = drive(load(stem, band))
    assert sol.rate_ppm == pytest.approx(expected_ppm, abs=tolerance)


@pytest.mark.parametrize("stem,band", [(r[0], r[1]) for r in ROWS])
def test_the_accepted_witnesses_stay_self_consistent(stem, band):
    observations = load(stem, band)
    _, sol = drive(observations)
    residuals = [
        obs.utc_ns - sol.utc_ns_at(obs.rtp) for obs in observations
    ]
    centred = [r - sorted(residuals)[len(residuals) // 2] for r in residuals]
    worst = max(abs(r) for r in centred)
    assert worst < 2 * MS, f"{stem}/{band} worst residual {worst / MS:.2f} ms"


@pytest.mark.parametrize("lattice_ms", [18.7, 34.0, 50.0])
@pytest.mark.parametrize("stem,band", [(r[0], r[1]) for r in ROWS])
def test_a_lattice_step_on_one_tier_never_moves_a_corpus_plane(stem, band, lattice_ms):
    observations = load(stem, band)
    half = len(observations) // 2
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for obs in observations[:half]:
        est.observe(obs)
        est.advance(obs.rtp)
    settled = est.solve(observations[half - 1].rtp)

    for obs in observations[half:]:
        est.observe(PhaseObservation(
            tier=obs.tier, rtp=obs.rtp,
            utc_ns=obs.utc_ns + round(lattice_ms * MS),
            sigma_ns=obs.sigma_ns, plane=obs.plane, source=obs.source,
        ))
        est.advance(obs.rtp)
    after = est.solve(observations[-1].rtp)

    assert abs(after.rate_ppm - settled.rate_ppm) < 0.5


def test_the_band_disagreement_in_the_bad_nd_fixture_raises_no_rate_alarm():
    """Spec section 8: the two bands disagree about identity, not about rate."""
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    merged = sorted(
        load("nd-20260906-bad", "1200") + load("nd-20260906-bad", "1000"),
        key=lambda o: o.rtp,
    )
    for obs in merged:
        est.observe(obs)
        est.advance(obs.rtp)
    sol = est.solve(merged[-1].rtp)
    assert sol.refusal != "rate_disagreement"
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/python -m pytest tests/estimator/test_acceptance_corpus.py -v`
Expected: all pass, or a clear failure naming the number that came out. A row that fails is a
finding about the estimator or about the corpus. Report it; do not widen a tolerance to make it
pass.

- [ ] **Step 3: Run the whole repository suite for regressions**

Run: `.venv/bin/python -m pytest tests/ --override-ini=addopts= -q 2>&1 | tail -20`
Expected: the estimator tests pass and the pre-existing baseline holds. `test_restart_stability`
is known flaky and predates this work.

- [ ] **Step 4: Run the formatters and the type checker**

```bash
.venv/bin/black src/hf_timestd/estimator tests/estimator scripts/build_estimator_corpus.py
.venv/bin/flake8 src/hf_timestd/estimator tests/estimator
.venv/bin/mypy src/hf_timestd/estimator
```

Expected: clean. Commit any formatting the tools apply.

- [ ] **Step 5: Update the code graph**

Run: `graphify update /home/mjh/hamsci/repos`
Never `graphify update .` from `/home/mjh/hamsci`, which re-roots the graph.

- [ ] **Step 6: Commit**

```bash
git add tests/estimator/test_acceptance_corpus.py
git commit -m "test(estimator): the acceptance table, executable against the saved corpora"
```

---

## Task 11: The library's own documentation

**Files:**
- Create: `docs/design/STATION-TIMING-ESTIMATOR.md`
- Modify: `docs/INDEX.md`

**Interfaces:**
- Consumes: the finished library.
- Produces: the reference a future reader needs before wiring a consumer.

- [ ] **Step 1: Write the document**

Cover, in this order, and in prose rather than bullet taxonomy:

1. The two states, their units, and the sign convention, copied verbatim from the spec so the
   two documents cannot drift.
2. The one convention for elapsed time, and the guard test that keeps it.
3. What a witness must supply, and why a host-plane witness reaches the gates and not the state.
4. The six refusals, in order, with what a caller should do about each. Name explicitly that the
   library never actuates and never alarms: the caller does both.
5. The step rule, with the 2026-09-07 lattice as the worked example.
6. What the measured rate means for a consumer, and the fact that no consumer reads it yet.
7. A short section headed by what this does NOT provide: absolute accuracy bounded by
   propagation, station identity, and any station integration.

- [ ] **Step 2: Add it to the index**

Add one line under the Metrology and Timing group in `docs/INDEX.md`, naming the spec as its
companion.

- [ ] **Step 3: Commit**

```bash
git add docs/design/STATION-TIMING-ESTIMATOR.md docs/INDEX.md
git commit -m "docs(timing): the station timing estimator, and what it does not provide"
```

---

## Task 12: Hand back a written finding, not a claim of success

**Files:**
- Create: `ops/reviews/2026-09-08-station-timing-estimator/findings.md` (in the `hamsci-ops` repo)

**Interfaces:**
- Consumes: everything.
- Produces: the record the next session reads.

- [ ] **Step 1: Record the numbers the run actually produced**

For each acceptance row, write the measured rate, its sigma, and the worst residual. Do not
round toward the expectation. Where a row failed, say so plainly and name the number.

- [ ] **Step 2: Record what remains open**

At least: the unexplained 2026-09-07 rate figures, the unproven measured-Allan path for want of
span, the propagation-bounded absolute accuracy, and the replica correlator as the named
successor.

- [ ] **Step 3: Commit in the ops repo**

```bash
cd /home/mjh/hamsci/ops
git add reviews/2026-09-08-station-timing-estimator/
git commit -m "review(timing): station timing estimator, measured results and what stays open"
```

---

## Self-Review

**Spec coverage.**

| spec section | task |
|---|---|
| §1 measurand, two states, one convention, published projection | 4, plus the guard in 1 |
| §2 reference plane, rebase, counter epoch change | 4, 8 |
| §3 witnesses, measurement models, host-plane rule, tier does not weigh | 2, 5, 8 |
| §4 innovation test, lone tier, concordant quorum, dwell, step never becomes rate | 5, 4 (`reseed_phase`), 8 |
| §5 the six refusals, in order | 6, 8 |
| §6 Allan deviation to q1 and q2, stand-in bootstrap, A-level as diagnosis | 3, 8 |
| §7 package layout, one object, published solution, one ruler one instance | 1, 7, 8, 11 |
| §8 property tests, replay corpus, acceptance table | every task's tests, 9, 10 |
| §9 out of scope | enforced by the guards in 1; documented in 11 |
| §10 risks | documented in 11, reported in 12 |

**Placeholder scan.** Task 8 step 3 gives a class skeleton with `...` bodies plus seven numbered
behaviours and six named pitfalls, rather than the full method bodies. That stays deliberate: the
tests in step 1 pin every behaviour, and the surrounding units are complete. Every other code
step carries runnable code.

**Type consistency.** `RulerNoise.q_matrix` is defined in Task 3 and consumed by
`ClockState.predict` in Task 4. `Verdict` is defined in Task 5 and returned by
`StationTimingEstimator.observe` in Task 8. `signed_rtp_delta` is defined in Task 4 and consumed
by `TimingSolution.utc_ns_at` in Task 7. `PHASE` and `RATE` are defined in Task 4 and used in
Tasks 4 and 8. `GateInputs` and `GateConfig` are defined in Task 6 and constructed in Task 8.
`standin_sigma_ppm`, `noise_from_standin` and `noise_from_adev` are defined in Task 3 and called
in Task 8. Names agree across all tasks.
