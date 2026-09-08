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

# fixture stem, band, the ruler measured from the signal on 2026-09-08,
# tolerance
ROWS = [
    ("nd-20260906", "1000", -0.03, 0.2),
    ("nd-20260906-bad", "1200", -0.12, 0.2),
    ("b4-20260906-day", "1000", +0.16, 0.2),
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
        pytest.skip(
            f"corpus {stem} band {band} holds {len(rows)} rows, too few",
        )
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
    return est, est.solve(observations[-1].rtp)


@pytest.mark.parametrize("stem,band,expected_ppm,tolerance", ROWS)
def test_the_estimator_recovers_each_corpus_ruler(
    stem,
    band,
    expected_ppm,
    tolerance,
):
    _, sol = drive(load(stem, band))
    assert sol.rate_ppm == pytest.approx(expected_ppm, abs=tolerance)


@pytest.mark.parametrize("stem,band", [(r[0], r[1]) for r in ROWS])
def test_the_accepted_witnesses_stay_self_consistent(stem, band):
    observations = load(stem, band)
    _, sol = drive(observations)
    residuals = [obs.utc_ns - sol.utc_ns_at(obs.rtp) for obs in observations]
    centred = [r - sorted(residuals)[len(residuals) // 2] for r in residuals]
    worst = max(abs(r) for r in centred)
    assert worst < 2 * MS, f"{stem}/{band} worst residual {worst / MS:.2f} ms"


@pytest.mark.parametrize("lattice_ms", [18.7, 34.0, 50.0])
@pytest.mark.parametrize("stem,band", [(r[0], r[1]) for r in ROWS])
def test_a_lattice_step_on_one_tier_never_moves_a_corpus_plane(
    stem,
    band,
    lattice_ms,
):
    observations = load(stem, band)
    half = len(observations) // 2
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for obs in observations[:half]:
        est.observe(obs)
        est.advance(obs.rtp)
    settled = est.solve(observations[half - 1].rtp)

    for obs in observations[half:]:
        est.observe(
            PhaseObservation(
                tier=obs.tier,
                rtp=obs.rtp,
                utc_ns=obs.utc_ns + round(lattice_ms * MS),
                sigma_ns=obs.sigma_ns,
                plane=obs.plane,
                source=obs.source,
            )
        )
        est.advance(obs.rtp)
    after = est.solve(observations[-1].rtp)

    assert abs(after.rate_ppm - settled.rate_ppm) < 0.5


def test_the_band_disagreement_in_the_bad_nd_fixture_raises_no_rate_alarm():
    """Spec section 8: the bands disagree about identity, not rate."""
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
