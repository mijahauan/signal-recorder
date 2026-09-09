"""Which second of the minute a block begins on.

A correlation lag is ambiguous modulo ONE SECOND: the tick train repeats every
second, so 60 shifts fit a minute equally well. Rate survives that, needing
only consistency between minutes, but no absolute claim does -- and a wrong
choice costs a WHOLE SECOND, not a noisy fraction.

What breaks the tie is the structure a second does not have. Second 0 carries
an 800 ms marker, 160 times a tick's duration, and seconds 29 and 59 carry no
tick at all. Reduced to one number per second, a minute has a signature, and
the ambiguity becomes a choice among 60 cyclic shifts.

⚠ This module reports a MARGIN and refuses below it, because the failure it
exists to prevent is a confident wrong answer. A channel whose marker did not
survive the path resolves nothing here, and that is the correct outcome: the
2026-09-08 shadow run watched the fold method guess instead, and publish
-46.8 ppm off a series whose cycle choice had coin-flipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .correlate import MIN_CC_SNR
from .template import SECONDS_PER_MINUTE, minute_template

SECONDS = SECONDS_PER_MINUTE
# How far the best shift beats the runner-up, as a DIFFERENCE of cosines
# rather than a ratio. A ratio is useless here: the signature is dominated by
# one very loud second, so the runner-up usually scores at or below zero and
# every ratio saturates. Measured across the cases that matter -- a real
# minute lands at 0.95 to 1.02 even under noise as large as the signal, while
# a tick train with no marker lands at 0.0000 and pure noise at 0.1284. So
# 0.5 sits sevenfold above the worst failure and half the worst success.
MIN_MARGIN = 0.5


@dataclass(frozen=True)
class SecondOfMinute:
    """The second this block begins on, and how clearly it won.

    ``score`` reports how much the winning shift resembles a minute at all,
    and it is REPORTED rather than gated on purpose: pure noise scores a
    respectable 0.42 by itself, so a threshold there would pass what it means
    to catch. Only ``margin`` decides.
    """

    offset: int
    score: float
    margin: float

    @property
    def resolved(self) -> bool:
        return self.margin >= MIN_MARGIN


def per_second_energy(
    envelope: np.ndarray, sample_rate: int, lag_s: float = 0.0
) -> np.ndarray:
    """Total envelope energy in each of the minute's sixty seconds.

    ``lag_s`` shifts the second boundaries by a known sub-second offset. It
    barely matters here and is offered for completeness: the marker runs
    800 ms, so binning it a few milliseconds early or late moves almost none
    of its energy across a boundary. The tick that DOES straddle a boundary
    contributes 5 ms against the marker's 800.
    """
    fs = int(sample_rate)
    x = np.asarray(envelope, dtype=np.float64)
    n = SECONDS * fs
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    else:
        x = x[:n]
    shift = int(round(float(lag_s) * fs))
    if shift:
        x = np.roll(x, -shift)
    # Energy above a ROBUST floor. The floor has to be the median, not the
    # minimum: one negative excursion sets a minimum, and subtracting it
    # lifts the whole minute onto a pedestal that squaring then flattens --
    # which let a single noiseless-but-wrong minute outvote nine noisy right
    # ones in testing. Ticks and the marker together occupy under 2 % of a
    # minute, so the median IS the noise floor.
    #
    # Energy rather than amplitude, because the marker's advantage over a
    # tick is duration, and squaring keeps a long loud second from being
    # averaged into its neighbours.
    x = np.maximum(x - float(np.median(x)), 0.0)
    return (x * x).reshape(SECONDS, fs).sum(axis=1)


def _signature(sample_rate: int) -> np.ndarray:
    """The energy vector a minute starting on second 0 produces."""
    return per_second_energy(minute_template(sample_rate), sample_rate)


def accumulate_energy(vectors: Iterable[np.ndarray]) -> np.ndarray:
    """Sum per-minute energy vectors, each NORMALISED to unit total first.

    Every minute shares the same second-of-minute offset, so the marker
    accumulates while noise does not: measured on real signal, ND's 12:00 Z
    channel went from a margin of 0.060 on one minute to 1.003 over ten, and
    B4's 18:00 Z channel from 0.042 to 1.003. Both land on the right second,
    and neither could be resolved from a single minute at all.

    The normalisation is not cosmetic. Without it one very loud minute -- a
    fade recovering, a burst of interference -- outvotes every quiet one and
    decides the answer alone.
    """
    total = np.zeros(SECONDS, dtype=np.float64)
    for vector in vectors:
        v = np.asarray(vector, dtype=np.float64)
        if v.shape != (SECONDS,):
            raise ValueError(
                f"energy vector has shape {v.shape}, want ({SECONDS},)"
            )
        scale = float(v.sum())
        if scale > 0.0:
            total += v / scale
    return total


def resolve_from_energy(
    energy: np.ndarray, sample_rate: int
) -> SecondOfMinute:
    """Choose among 60 cyclic shifts of an ALREADY BINNED energy vector."""
    measured = np.asarray(energy, dtype=np.float64)
    expected = _signature(sample_rate)
    # Correlate the two as SHAPES. Removing each mean stops a channel's own
    # gain from deciding anything, and normalising by the norms makes the
    # score a cosine, so the margin compares like with like.
    a = measured - measured.mean()
    b = expected - expected.mean()
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return SecondOfMinute(offset=0, score=0.0, margin=0.0)
    scores = np.array(
        [float(np.dot(np.roll(a, -k), b)) / (na * nb) for k in range(SECONDS)]
    )
    order = np.argsort(scores)[::-1]
    best, runner = int(order[0]), int(order[1])
    top, second = float(scores[best]), float(scores[runner])
    # ``best`` names how far the CONTENT sits from a minute's start, so the
    # second this block BEGINS on is its complement: content displaced by k
    # means index 0 holds the minute's second 60 - k.
    offset = (SECONDS - best) % SECONDS
    return SecondOfMinute(offset=offset, score=top, margin=top - second)


def resolve_second_of_minute(
    envelope: np.ndarray, sample_rate: int, lag_s: float = 0.0
) -> SecondOfMinute:
    """One minute of envelope, binned and resolved in one step."""
    return resolve_from_energy(
        per_second_energy(envelope, sample_rate, lag_s), sample_rate
    )


def resolve_if_admissible(
    energy: np.ndarray, sample_rate: int, cc_snr: float
) -> SecondOfMinute | None:
    """Resolve only on a channel whose structure gate already passed.

    ⛔ The composition matters more than either half. Accumulation raises
    confidence whether or not there is anything to be confident about:
    measured on ND's WWV_20000, a channel with a correlation score of 5.2 and
    no usable structure at all, one minute refuses at a margin of 0.072 while
    ten accumulate to 0.494 against a threshold of 0.5 -- within one per cent
    of passing, and naming the WRONG second. A hair's breadth is not a margin
    of safety. The two gates answer different questions and both must be
    asked: ``cc_snr`` says whether this channel carries a minute at all, and
    ``margin`` says which one.

    Returns ``None`` when the channel never earned the question.
    """
    if not float(cc_snr) >= MIN_CC_SNR:
        return None
    return resolve_from_energy(energy, sample_rate)
