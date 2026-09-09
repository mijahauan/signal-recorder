"""Which second of the minute a block starts on.

The correlation lag is ambiguous modulo ONE SECOND, because the tick train
repeats every second: measured on 2026-09-08, the peak slipped whole seconds
between minutes on two of four fixtures. Rate survives that (a slope needs
only consistency), but no ABSOLUTE claim does.

What breaks the tie is the structure a second does not have. Second 0 carries
an 800 ms marker -- 160 times a tick's duration -- and seconds 29 and 59 carry
no tick at all. Binned into one number per second, a minute therefore has a
signature, and the ambiguity becomes a choice among 60 cyclic shifts rather
than a continuum.
"""

import numpy as np
import pytest

from hf_timestd.replica.second_of_minute import (
    MIN_MARGIN,
    SECONDS,
    accumulate_energy,
    per_second_energy,
    resolve_from_energy,
    resolve_if_admissible,
    resolve_second_of_minute,
)
from hf_timestd.replica.template import minute_template

FS = 2000


def test_the_energy_vector_carries_one_number_per_second():
    e = per_second_energy(minute_template(FS), FS)
    assert len(e) == SECONDS == 60


def test_the_marker_second_dominates_the_energy_vector():
    e = per_second_energy(minute_template(FS), FS)
    assert int(np.argmax(e)) == 0
    ticks = np.concatenate([e[1:29], e[30:59]])
    assert e[0] > 100 * float(ticks.max())


def test_the_silent_seconds_read_as_silent():
    e = per_second_energy(minute_template(FS), FS)
    assert e[29] == 0.0
    assert e[59] == 0.0


def test_a_block_starting_on_the_minute_resolves_to_zero():
    r = resolve_second_of_minute(minute_template(FS), FS)
    assert r.resolved
    assert r.offset == 0


@pytest.mark.parametrize("shift", [1, 17, 29, 30, 45, 59])
def test_a_rolled_minute_reports_how_far_it_rolled(shift):
    """``offset`` names the second of the minute this block BEGINS on."""
    rolled = np.roll(minute_template(FS), shift * FS)
    r = resolve_second_of_minute(rolled, FS)
    assert r.resolved
    assert r.offset == (SECONDS - shift) % SECONDS


def test_noise_resolves_nothing():
    rng = np.random.default_rng(19)
    r = resolve_second_of_minute(rng.normal(1.0, 0.2, SECONDS * FS), FS)
    assert not r.resolved
    assert r.margin < MIN_MARGIN


def test_a_tick_train_WITHOUT_the_marker_resolves_nothing():
    """The whole point, stated as its own row.

    Strip second 0's marker and the two gaps are all that remain to
    distinguish 60 shifts. This is the case the fold method faced, and it must
    REFUSE rather than guess -- a wrong second is a whole second of error, not
    a noisy one.
    """
    t = minute_template(FS)
    flat = t.copy()
    flat[0:FS] = 0.0
    for second in (29, 59):
        a = second * FS
        b = a + 10
        flat[a:b] = 1.0
    r = resolve_second_of_minute(flat, FS)
    assert not r.resolved


def test_a_noisy_but_real_minute_still_resolves():
    rng = np.random.default_rng(23)
    t = minute_template(FS)
    r = resolve_second_of_minute(t + rng.normal(0.0, 0.05, len(t)), FS)
    assert r.resolved
    assert r.offset == 0


def test_the_margin_ranks_a_clean_minute_above_a_noisy_one():
    rng = np.random.default_rng(29)
    t = minute_template(FS)
    clean = resolve_second_of_minute(t, FS).margin
    noisy = resolve_second_of_minute(
        t + rng.normal(0.0, 1.0, len(t)), FS
    ).margin
    assert clean > noisy


def test_it_survives_noise_as_large_as_the_signal():
    """Measured margin 0.95 at sigma 1.0 -- the marker is 800 ms of energy."""
    rng = np.random.default_rng(31)
    t = minute_template(FS)
    r = resolve_second_of_minute(t + rng.normal(0.0, 1.0, len(t)), FS)
    assert r.resolved
    assert r.offset == 0


def test_the_best_score_alone_would_NOT_have_caught_noise():
    """Why ``score`` is reported and ``margin`` decides.

    Pure noise scores about 0.42 for its best shift, which any threshold set
    to admit a real minute would wave through. Its MARGIN is 0.13.
    """
    rng = np.random.default_rng(19)
    r = resolve_second_of_minute(rng.normal(1.0, 0.2, SECONDS * FS), FS)
    assert r.score > 0.2, "the trap this test documents has moved"
    assert not r.resolved


# ---- accumulating minutes, and the trap that comes with it ---------------


def rolled_minutes(shift, count, sigma, seed):
    """``count`` minutes of the same rolled template, each freshly noisy."""
    rng = np.random.default_rng(seed)
    base = np.roll(minute_template(FS), shift * FS)
    return [base + rng.normal(0.0, sigma, len(base)) for _ in range(count)]


def test_accumulating_minutes_resolves_what_one_minute_cannot():
    """Every minute shares the same offset, so the marker builds up.

    Measured on real signal: ND's 12:00Z WWVH channel goes from a margin of
    0.060 on one minute -- a refusal -- to 1.003 over ten, and B4's 18:00Z
    channel from 0.042 to 1.003. Both land on the right second, and neither
    could be resolved from one minute at all.
    """
    # Measured: at sigma 8 one minute reaches 0.229 and refuses, while ten
    # accumulate to 0.757. Below sigma 5 one minute already resolves.
    minutes = rolled_minutes(shift=0, count=10, sigma=8.0, seed=41)
    alone = resolve_second_of_minute(minutes[0], FS)
    together = resolve_from_energy(
        accumulate_energy(per_second_energy(m, FS) for m in minutes), FS
    )
    assert not alone.resolved, "pick a noise level one minute cannot carry"
    assert together.resolved
    assert together.offset == 0
    assert together.margin > 3.0 * alone.margin


def test_accumulation_normalises_each_minute_before_summing():
    """One very loud minute must not outvote nine quiet ones.

    A minute arriving 1000x louder would otherwise decide the answer alone,
    which is how a single fade or a burst of interference would capture the
    result.
    """
    good = rolled_minutes(shift=12, count=9, sigma=0.2, seed=43)
    liar = np.roll(minute_template(FS), 30 * FS) * 1000.0
    acc = accumulate_energy(
        [per_second_energy(m, FS) for m in good]
        + [per_second_energy(liar, FS)]
    )
    r = resolve_from_energy(acc, FS)
    assert r.resolved
    assert r.offset == (SECONDS - 12) % SECONDS, "the loud liar captured it"


def test_white_noise_does_NOT_accumulate_into_confidence():
    """Which is why the real trap needed real signal to find.

    ⚠ On ND's WWV_20000 -- a channel with a correlation score of 5.2 and no
    usable structure -- ten accumulated minutes reach a margin of 0.494
    against a threshold of 0.5, naming the WRONG second: within one per cent
    of a confident wrong answer. WHITE noise does not do that. It lands at
    0.02 to 0.06 however many minutes are summed, as this row shows.

    The difference: a dead HF channel is not white. It carries AGC action,
    interference and other broadcasts, and that structure correlates with
    itself across minutes where noise does not.

    So the danger is real and it CANNOT be reproduced synthetically. That is
    the argument for ``resolve_if_admissible`` rather than a stricter
    threshold: no margin chosen against white noise would have caught it.
    """
    rng = np.random.default_rng(47)
    noise = [rng.normal(1.0, 0.2, SECONDS * FS) for _ in range(40)]
    acc = accumulate_energy(per_second_energy(m, FS) for m in noise)
    assert not resolve_from_energy(acc, FS).resolved


def test_the_composition_refuses_a_channel_that_failed_the_structure_gate():
    rng = np.random.default_rng(47)
    noise = [rng.normal(1.0, 0.2, SECONDS * FS) for _ in range(40)]
    acc = accumulate_energy(per_second_energy(m, FS) for m in noise)
    guarded = resolve_if_admissible(acc, FS, cc_snr=5.2)
    assert guarded is None


def test_the_composition_passes_a_channel_that_earned_it():
    minutes = rolled_minutes(shift=7, count=10, sigma=0.5, seed=53)
    acc = accumulate_energy(per_second_energy(m, FS) for m in minutes)
    r = resolve_if_admissible(acc, FS, cc_snr=63.5)
    assert r is not None
    assert r.resolved
    assert r.offset == (SECONDS - 7) % SECONDS
