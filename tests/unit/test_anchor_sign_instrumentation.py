"""The sign contradiction gets watched, not acted on (task 17c).

AC0G-ND, 2026-09-07.  The anchor-direct FUSE feed engaged at 20:41Z and
21:21Z and both times reported the host clock SLOW -- +23..28 ms, then
+60.5 ms -- while four NTP witnesses put the host FAST by +13 and
+30 ms.  chrony followed FUSE and slewed the host the wrong way.  Which
of the two is right is still unknown, and it cannot be settled from the
station's own frame while the closure has every surface on one plane.

So fusion states the three numbers side by side, once a minute, at INFO,
whether or not the closure is on:

    anchor-direct WOULD feed: reference−system = ±NN.N ms;
    NTP consensus (chronyc sources, pool median) = ±NN.N ms;
    ring plane vs registration = ±NN.N ms

All three are in the SAME sense -- reference minus system, positive
meaning the host clock reads early -- so the contradiction is the
difference between the first two, and the third says how far the ring
plane sits from the registration (their difference, never their sum).
"""

import math

import pytest

from hf_timestd.core.chrony_stats import (
    parse_csv_sources,
    pool_median_offset_ms,
)
from hf_timestd.core.multi_broadcast_fusion import anchor_sign_line

# `chronyc -c sources` on a station with four pool servers, one FUSE
# refclock and one unreachable server.  Fields: mode, state, name,
# stratum, poll, reach, lastRx, adjusted offset, measured offset, margin.
CSV = "\n".join(
    [
        "^,*,162.159.200.1,3,6,377,49,0.013100,0.013050,0.000516",
        "^,+,17.253.20.253,2,6,377,51,0.030200,0.030150,0.000701",
        "^,+,44.190.6.254,2,6,377,12,0.012400,0.012380,0.000480",
        "^,-,72.30.35.88,2,6,377,33,0.029900,0.029880,0.000900",
        "#,*,FUSE,0,4,377,3,-0.150000,-0.150000,0.001000",
        "^,?,10.0.0.9,0,6,0,-,0.000000,0.000000,0.000000",
    ]
)


def test_the_refclocks_are_not_witnesses():
    """FUSE is the thing under test, not a witness of it.

    Mode ``#`` is a local reference clock.  Leaving it in would let the
    registration vote in its own consensus check -- the exact
    circularity the whole line exists to break.
    """
    rows = parse_csv_sources(CSV)
    assert [r.address for r in rows] == [
        "162.159.200.1",
        "17.253.20.253",
        "44.190.6.254",
        "72.30.35.88",
    ]


def test_an_unreachable_server_does_not_vote():
    """``reach`` 0 means nothing has been heard; its 0.0 offset is not a
    measurement and would drag the median toward zero."""
    assert "10.0.0.9" not in [r.address for r in parse_csv_sources(CSV)]


def test_the_pool_median_is_the_median_of_the_witnesses():
    # 13.1, 30.2, 12.4, 29.9 -> median of the two middles: 21.5
    assert pool_median_offset_ms(CSV) == pytest.approx(21.5)


def test_no_witnesses_is_none_not_zero():
    assert pool_median_offset_ms("") is None
    assert pool_median_offset_ms("#,*,FUSE,0,4,377,3,-0.15,-0.15,0.001") is None


def test_a_malformed_row_is_skipped_not_fatal():
    csv = "\n".join(
        [
            "garbage",
            "^,*,1.2.3.4,3,6,377,49,not-a-number,0.0,0.0",
            "^,*,5.6.7.8,3,6,377,49,0.020000,0.020000,0.0005",
        ]
    )
    assert pool_median_offset_ms(csv) == pytest.approx(20.0)


# ── the line itself ──────────────────────────────────────────────────


def test_the_line_states_all_three_numbers():
    """The ND geometry: the anchor says the host is slow, the pool says
    it is fast, and the ring plane sits between them."""
    line = anchor_sign_line(
        anchor_offset_ms=-25.5, pool_median_ms=21.5, d_clock_fused_ms=-0.4
    )
    assert "anchor-direct WOULD feed" in line
    assert "reference−system = -25.5 ms" in line
    assert "NTP consensus (chronyc sources, pool median) = +21.5 ms" in line
    # ring plane vs registration = d_clock − anchor = -0.4 − (-25.5)
    assert "ring plane vs registration = +25.1 ms" in line


def test_an_unavailable_term_reads_as_such_rather_than_as_zero():
    line = anchor_sign_line(
        anchor_offset_ms=+60.5, pool_median_ms=None, d_clock_fused_ms=None
    )
    assert "reference−system = +60.5 ms" in line
    assert "pool median) = n/a" in line
    assert "ring plane vs registration = n/a" in line


def test_a_nan_pool_median_reads_as_unavailable():
    line = anchor_sign_line(
        anchor_offset_ms=1.0, pool_median_ms=math.nan, d_clock_fused_ms=math.nan
    )
    assert "pool median) = n/a" in line
    assert "ring plane vs registration = n/a" in line


def test_the_line_is_written_once_a_minute():
    from hf_timestd.core.multi_broadcast_fusion import (
        ANCHOR_SIGN_LOG_INTERVAL_S,
    )

    assert ANCHOR_SIGN_LOG_INTERVAL_S == 60.0


def test_the_witness_block_reaches_the_line_with_the_closure_off(tmp_path):
    """End to end: judge (closure off) → witness block → the line.

    This is the path a station that never opted in actually runs, and it
    is the one that has to work — the whole purpose of 17c is evidence
    from a station nothing is steering.
    """
    from hf_timestd.core.offset_judge import (
        BenchReading,
        LABEL_PLANE_ANCHOR_KEY,
        LABEL_PLANE_WITNESS_KEY,
        OffsetJudge,
        label_plane_chrony_sample,
    )
    from hf_timestd.core.buffer_timing import unix_ns_to_gps_time_ns

    wall, mono = 1_800_000_000.0, 1000.0
    judge = OffsetJudge(
        config={"enabled": True},
        benches=[
            type(
                "B",
                (),
                {
                    "poll": lambda _s: BenchReading(
                        # the ND geometry: the anchor calls the host slow
                        utc=wall - 0.0255,
                        mono=mono,
                        sigma_ns=1e6,
                        tier="T3",
                        detail={"bench": "hf_acquired", "authoritative": True},
                        plane="label",
                    )
                },
            )()
        ],
        publish_path=tmp_path / "offset_judge.json",
        time_fn=lambda: wall,
        mono_fn=lambda: mono,
    )
    judge.register_radiod_pair(
        ("h", 1), unix_ns_to_gps_time_ns(int(wall * 1e9)), 0, 24000
    )
    judge.tick()
    path = tmp_path / "offset_judge.json"
    # Nothing on the key chrony reads...
    assert (
        label_plane_chrony_sample(
            path, key=LABEL_PLANE_ANCHOR_KEY, mono_fn=lambda: mono
        )
        is None
    )
    # ...and the statement intact on the one it does not.
    sample = label_plane_chrony_sample(
        path,
        key=LABEL_PLANE_WITNESS_KEY,
        time_fn=lambda: wall,
        mono_fn=lambda: mono,
    )
    assert sample is not None
    line = anchor_sign_line(sample.offset_s * 1e3, 21.5, -0.4)
    assert "reference−system = -25.5 ms" in line
    assert "NTP consensus (chronyc sources, pool median) = +21.5 ms" in line
