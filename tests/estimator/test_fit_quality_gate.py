"""The fit-quality gates, measured against AC0G-ND's and AC0G-B4's own signal.

A devbox shadow run on 2026-09-08 drove all sixteen committed corpus series
through the estimator. Five behaved. Nine published a rate wrong by one to
three orders of magnitude, because the gate chain bounded no rate's absolute
magnitude: ``rate_disagreement`` tests only the SPREAD BETWEEN rate sources,
and a single tier supplying no rate observation leaves that spread unmeasured.

These rows come from that run. They are the real recordings, not synthetic
witnesses, and they carry the two failure mechanisms the shadow run separated:
an exactly-determined fit (few accepted witnesses, no residue to contradict
the answer) and visible scatter with redundancy (enough witnesses to fit, and
they plainly disagree).
"""

import collections
import json
import pathlib

import pytest

from hf_timestd.estimator.estimator import StationTimingEstimator
from hf_timestd.estimator.observations import PhaseObservation
from hf_timestd.estimator.solution import VERDICT_PUBLISH, VERDICT_WITHHOLD

CORPUS = pathlib.Path(__file__).parent.parent / "data" / "estimator"
F_NOM = 24000

# Series the shadow run found TRUSTWORTHY: every witness accepted, scatter
# from 0.15 to 0.70 ms, and a rate the acceptance table already grades.
GOOD = [
    ("nd-20260906", "SHARED_10000", "1000"),
    ("nd-20260906-bad", "SHARED_10000", "1200"),
    ("b4-20260906-day", "SHARED_10000", "1000"),
    # A ruler resampled by an exact -60 ppm. A naive absolute-rate bound
    # would refuse this correct answer; the fit-quality gates must not.
    ("nd-20260906-resampled-60ppm", "SHARED_10000", "1000"),
]

# Series the shadow run found GARBAGE, with the rate each one published and
# the mechanism that produced it.
GARBAGE = [
    ("nd-20260906", "WWV_20000", "1200", -46.8, "thin_fit"),
    ("nd-20260906", "SHARED_10000", "1200", -3.2, "fit_scatter"),
    ("nd-20260906-bad", "SHARED_10000", "1000", +8.5, "fit_scatter"),
    ("b4-20260906-day", "SHARED_10000", "1200", -7.5, "fit_scatter"),
    # Seven accepted of fifteen, so the update count speaks first and
    # rightly: this fit is thin as well as scattered.
    ("b4-20260907", "SHARED_10000", "1200", +10.8, "thin_fit"),
    (
        "nd-20260906-resampled-60ppm",
        "SHARED_10000",
        "1200",
        -63.6,
        "fit_scatter",
    ),
]


def load(stem: str, channel: str, band: str) -> list[PhaseObservation]:
    """Rows for one fixture, channel and band, selected on their own fields."""
    paths = sorted(CORPUS.glob("*.jsonl"))
    if not paths:
        pytest.skip("no corpus; run scripts/build_estimator_corpus.py")
    rows = []
    for path in paths:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if (
                row.get("fixture") == stem
                and row.get("channel") == channel
                and row.get("band") == band
            ):
                rows.append(row)
    if not rows:
        pytest.skip(f"{stem}/{channel}/{band}: absent from the corpus")
    rows.sort(key=lambda r: r["rtp"])
    return [
        PhaseObservation(
            tier=r["tier"],
            rtp=r["rtp"],
            utc_ns=r["utc_ns"],
            sigma_ns=r["sigma_ns"],
            plane=r["plane"],
            source=r["source"],
        )
        for r in rows
    ]


def drive(observations):
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for obs in observations:
        est.observe(obs)
        est.advance(obs.rtp)
    return est.solve(observations[-1].rtp)


@pytest.mark.parametrize("stem,channel,band", GOOD)
def test_a_trustworthy_series_still_publishes(stem, channel, band):
    sol = drive(load(stem, channel, band))
    assert sol.verdict == VERDICT_PUBLISH, f"refused {sol.refusal}"
    assert sol.refusal is None


@pytest.mark.parametrize("stem,channel,band,was_ppm,expected", GARBAGE)
def test_a_series_that_published_a_garbage_rate_now_withholds(
    stem, channel, band, was_ppm, expected
):
    sol = drive(load(stem, channel, band))
    assert sol.verdict == VERDICT_WITHHOLD, (
        f"{stem}/{channel}/{band} published {sol.rate_ppm:+.2f} ppm; the"
        f" shadow run measured {was_ppm:+.1f} ppm here"
    )
    assert sol.refusal == expected


def test_no_committed_series_publishes_a_rate_beyond_a_governed_ruler():
    """The whole point, stated once over every series in the corpus.

    A governed ruler cannot run parts per million fast. The one legitimate
    exception carries it in its name -- the fixture resampled by an exact
    -60 ppm -- so it is named here rather than silently tolerated.
    """
    by = collections.defaultdict(list)
    for path in sorted(CORPUS.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            by[(row["fixture"], row["channel"], row["band"])].append(row)
    if not by:
        pytest.skip("no corpus; run scripts/build_estimator_corpus.py")
    published = []
    for key in sorted(by):
        stem, channel, band = key
        sol = drive(load(stem, channel, band))
        if sol.verdict != VERDICT_PUBLISH:
            continue
        if abs(sol.rate_ppm) > 1.0 and "resampled" not in stem:
            published.append(f"{'/'.join(key)} at {sol.rate_ppm:+.2f} ppm")
    assert not published, "published beyond a governed ruler: " + "; ".join(
        published
    )
