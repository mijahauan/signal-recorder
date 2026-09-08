"""The spec section 8 acceptance table, executed against the saved corpora.

Each row tests rate, self-consistency or refusal behaviour. None tests
absolute UTC, because the corpus carries an unknown constant offset by
construction: propagation delay plus the station's identity.

No test here exercises a step, on purpose. Every row carries ``tier="T3"``
throughout, because a corpus drawn from one band of one channel IS one
witness by construction -- one antenna, one measurement chain, nothing this
tool could split into a second independent tier without fabricating one.
``Admitter._concordant`` needs a quorum of at least two DISTINCT tiers
before a step may ripen and move the plane, and rightly so: a lone witness
moving the plane however confident is exactly the failure this library
exists to prevent (spec section 4). So a single-tier corpus can never
license a step here, and that is the real constraint working as intended,
not a gap this suite works around by staying quiet about it.

On trusting the corpus itself: the generator's whole-second unwrap
(scripts/build_estimator_corpus.py) clamps every adjacent step under half
a second BY CONSTRUCTION, so a script that only checks "does no step
exceed half a second" cannot fail -- it confirms the unwrap RAN, not that
it CHOSE RIGHT. That check is not repeated here for that reason: a check
that cannot fail does not belong in the record looking like assurance.
The real evidence the unwrap chose the right cycle is downstream, in this
file's own assertions -- ``nd-20260906-resampled-60ppm`` recovers -60.13
ppm from a fixture resampled by a KNOWN, exact -60 ppm, and all four rows'
self-consistency residuals land in the sub-millisecond range. A wrong
cycle choice would show up as exactly the kind of gross rate or residual
error those assertions exist to catch, not as a silent pass.
"""

import json
import pathlib

import pytest

from hf_timestd.estimator.estimator import StationTimingEstimator
from hf_timestd.estimator.observations import PhaseObservation

CORPUS = pathlib.Path(__file__).parent.parent / "data" / "estimator"
MS = 1_000_000.0
F_NOM = 24000

# fixture stem, channel, band, the ruler measured from the signal on
# 2026-09-08, tolerance
ROWS = [
    ("nd-20260906", "SHARED_10000", "1000", -0.03, 0.2),
    ("nd-20260906-bad", "SHARED_10000", "1200", -0.12, 0.2),
    ("b4-20260906-day", "SHARED_10000", "1000", +0.16, 0.2),
    ("nd-20260906-resampled-60ppm", "SHARED_10000", "1000", -60.0, 1.0),
]


def load(stem: str, channel: str, band: str) -> list[PhaseObservation]:
    """Rows for one fixture, channel and band, selected on their own fields.

    Never select on the filename: a prefix glob for ``nd-20260906`` also
    catches ``nd-20260906-bad`` and the resampled corpus. And never select
    on ``band`` alone: the same subcarrier tone is tagged identically
    across RF channels whose propagation paths -- and delays -- differ.
    """
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
    if len(rows) < 8:
        pytest.skip(f"{stem}/{channel}/{band}: {len(rows)} rows, too few")
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


@pytest.mark.parametrize("stem,channel,band,expected_ppm,tolerance", ROWS)
def test_the_estimator_recovers_each_corpus_ruler(
    stem,
    channel,
    band,
    expected_ppm,
    tolerance,
):
    _, sol = drive(load(stem, channel, band))
    assert sol.rate_ppm == pytest.approx(expected_ppm, abs=tolerance)


@pytest.mark.parametrize(
    "stem,channel,band",
    [(r[0], r[1], r[2]) for r in ROWS],
)
def test_the_accepted_witnesses_stay_self_consistent(stem, channel, band):
    observations = load(stem, channel, band)
    _, sol = drive(observations)
    residuals = [obs.utc_ns - sol.utc_ns_at(obs.rtp) for obs in observations]
    centred = [r - sorted(residuals)[len(residuals) // 2] for r in residuals]
    worst = max(abs(r) for r in centred)
    label = f"{stem}/{channel}/{band}"
    assert worst < 2 * MS, f"{label} worst residual {worst / MS:.2f} ms"


def _drive_counting(observations, config=None):
    """Like ``drive``, but also returns each observation's verdict.

    A lattice test needs to know not just where the plane ends up but
    what happened to every witness along the way -- a regression that
    narrowed the acceptance gate until nothing was ever accepted would
    leave the plane exactly where it started too, and ``drive`` alone
    cannot tell that apart from a plane that correctly refused a step.
    """
    est = StationTimingEstimator(
        f_nom=F_NOM,
        ruler_provenance="assumed",
        config=config,
    )
    verdicts = []
    for obs in observations:
        verdicts.append(est.observe(obs))
        est.advance(obs.rtp)
    return est, est.solve(observations[-1].rtp), verdicts


# Tolerances for assertion 3 below (subject vs. CONTROL, not vs. a settled
# half-corpus). The reviewer measured an ABSORBED lattice step moving the
# rate by 47.97 to 126.02 ppm and the projected plane by the injected
# offset itself (18.7 to 50 ms) -- both of those are the signal a
# regression that stopped refusing steps would produce. Against that, the
# CORPUS'S OWN natural convergence movement between a half-length fit and
# the full corpus is under 2 ppm in rate and under 1 ms in plane (measured
# 0.24-1.89 ppm, 0.11-0.84 ms across these four rows) -- so a bar of a few
# ppm and a few milliseconds sits well clear of both, catching an absorbed
# step by a wide margin while never flagging the corpus's own convergence.
_LATTICE_RATE_TOL_PPM = 5.0
_LATTICE_PLANE_TOL_NS = 5.0 * MS


@pytest.mark.parametrize("lattice_ms", [18.7, 34.0, 50.0])
@pytest.mark.parametrize(
    "stem,channel,band",
    [(r[0], r[1], r[2]) for r in ROWS],
)
def test_a_lattice_step_on_one_tier_never_moves_a_corpus_plane(
    stem,
    channel,
    band,
    lattice_ms,
):
    """A lone tier's fifty-millisecond-scale step must be refused outright.

    Comparing a post-injection estimate against a SETTLED HALF-CORPUS (the
    prior version of this test) cannot tell "the step was refused" apart
    from "the estimator stopped learning from everything": both leave the
    plane sitting at the half-corpus's own estimate, and a regression that
    narrowed the acceptance gate until every witness was rejected would
    pass either way. So this drives two independent estimators over the
    same rows -- a CONTROL fed the corpus unmodified, and a SUBJECT fed
    the same rows with the second half's utc_ns offset by ``lattice_ms``
    -- and checks three things that together cannot be satisfied by
    either failure mode alone: the control must actually be admitting
    witnesses (catching a reject-everything regression), the subject must
    actually be refusing the injected ones (catching an absorb-everything
    regression), and only once both hold does comparing the subject's
    rate and projected plane against the CONTROL (not a half-settled
    fit) isolate the injection's effect from the corpus's own ordinary
    convergence.
    """
    # ``control_sol`` and ``subject_sol`` below are NOT this fixture's
    # ruler estimate and must never be read as one. ``control_sol`` is
    # the full-corpus fit here for comparison only, unrelated to a
    # settled state; ``subject_sol`` is deliberately a HALF-CONVERGED
    # state once the injected witnesses are (correctly) all rejected,
    # and both can sit far from the expected_ppm this fixture's row in
    # ROWS asserts (measured up to 1.89 ppm off across these four rows,
    # against a 0.2 ppm acceptance tolerance elsewhere in this file). The
    # only thing asserted about them here is that they agree with EACH
    # OTHER, not that either matches the ruler.
    observations = load(stem, channel, band)
    half = len(observations) // 2

    _, control_sol, control_verdicts = _drive_counting(observations)
    accepted = sum(1 for v in control_verdicts if v.accepted)
    assert accepted >= 0.75 * len(
        observations
    ), f"control accepted only {accepted}/{len(observations)} witnesses"

    subject_observations = [
        (
            obs
            if i < half
            else PhaseObservation(
                tier=obs.tier,
                rtp=obs.rtp,
                utc_ns=obs.utc_ns + round(lattice_ms * MS),
                sigma_ns=obs.sigma_ns,
                plane=obs.plane,
                source=obs.source,
            )
        )
        for i, obs in enumerate(observations)
    ]
    _, subject_sol, subject_verdicts = _drive_counting(subject_observations)
    injected_verdicts = subject_verdicts[half:]
    rejected = sum(1 for v in injected_verdicts if not v.accepted)
    n_inj = len(injected_verdicts)
    msg = f"only {rejected}/{n_inj} injected witnesses rejected"
    assert rejected >= len(injected_verdicts) - 1, msg

    rate_diff = abs(subject_sol.rate_ppm - control_sol.rate_ppm)
    assert rate_diff < _LATTICE_RATE_TOL_PPM, (
        f"subject rate {subject_sol.rate_ppm:.4f} vs control"
        f" {control_sol.rate_ppm:.4f} ppm"
    )
    check_rtp = observations[-1].rtp
    plane_diff = abs(
        control_sol.utc_ns_at(check_rtp) - subject_sol.utc_ns_at(check_rtp)
    )
    assert (
        plane_diff < _LATTICE_PLANE_TOL_NS
    ), f"subject plane vs control plane differ by {plane_diff / MS:.3f} ms"


def test_the_band_disagreement_in_the_bad_nd_fixture_raises_no_rate_alarm():
    """Spec section 8: the bands disagree about identity, not rate.

    ``assert sol.refusal != "rate_disagreement"`` cannot fail on this
    corpus: that refusal is reachable only from a RateObservation's
    spread (``_rate_spread_ppm``, estimator.py), and this corpus -- every
    row of it -- emits phase observations exclusively. No rate alarm can
    fire here by construction, and that absence is the substance, not a
    caveat: an identity disagreement between two bands must surface as
    DISSENT between individual witnesses, never as a rate fault the
    estimator never actually observed. So assert the dissent directly --
    merging the two disagreeing bands must reject a substantial fraction
    of the combined witnesses (measured: 18 of 60, settling at +1.4515
    ppm) -- and keep the rate-refusal assertion beside it as the
    documented absence it is.
    """
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    merged = sorted(
        load("nd-20260906-bad", "SHARED_10000", "1200")
        + load("nd-20260906-bad", "SHARED_10000", "1000"),
        key=lambda o: o.rtp,
    )
    rejected = 0
    for obs in merged:
        verdict = est.observe(obs)
        if not verdict.accepted:
            rejected += 1
        est.advance(obs.rtp)
    sol = est.solve(merged[-1].rtp)
    assert (
        rejected >= len(merged) // 4
    ), f"only {rejected}/{len(merged)} merged witnesses rejected"
    assert sol.refusal != "rate_disagreement"
