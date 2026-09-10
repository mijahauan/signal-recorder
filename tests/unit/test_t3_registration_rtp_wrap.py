"""The T3 registration plane must survive a 32-bit RTP counter wrap.

ND's counter crossed 2**32 at ~11:00:56Z on 2026-09-09.  At 24 kHz that
recurs every 2**32/24000 = 178,956.97 s (49.7 h), on every station.  Across
that crossing four channel files published ``correction_ms`` of about
-178,956,540 ms -- one full counter period -- while reporting
``state: ACQUIRED`` and ``verified: true``.

``Registration.sample0_utc_for`` mapped the counter with a raw subtraction.
T6 has carried ``test_t6_rtp_wrap_continuity.py`` for this since well before
T3 self-registration shipped; this is the same law for the T3 plane.
"""

from hf_timestd.core.registration_acquirer import Registration

TWO32 = 1 << 32
SR = 24000
WRAP_PERIOD_S = TWO32 / SR  # 178,956.97 s


def _reg(rtp_ref: int, utc_ref: float) -> Registration:
    return Registration(
        counter_epoch_id="ep-1472933713",
        rtp_ref=rtp_ref,
        utc_ref=utc_ref,
        sample_rate=SR,
        sigma_ms=1.0,
        channel="SHARED_2500",
    )


def test_maps_across_a_counter_wrap_by_elapsed_samples_not_raw_difference():
    """ND's geometry at 11:00:44Z: rtp_ref 286,219 samples short of the wrap.

    A start_rtp 720,000 samples past the wrap sits 1,006,219 samples later,
    41.926 s.  The raw subtraction returned utc_ref - 178,915 s instead.
    """
    utc_ref = 1788944444.0
    reg = _reg(rtp_ref=TWO32 - 286_219, utc_ref=utc_ref)

    got = reg.sample0_utc_for(720_000)

    assert got == utc_ref + (286_219 + 720_000) / SR


def test_a_wrap_never_reports_a_time_a_whole_counter_period_away():
    """The signature of the ND defect, stated as the property it violated."""
    utc_ref = 1788944444.0
    reg = _reg(rtp_ref=TWO32 - 1, utc_ref=utc_ref)

    err = reg.sample0_utc_for(0) - utc_ref

    assert abs(err) < 1.0, f"mapped {err:+.3f} s away; a wrap is {WRAP_PERIOD_S:.1f} s"


def test_a_counter_that_has_not_wrapped_maps_exactly_as_before():
    """The fix must not move the ordinary case by so much as a sample."""
    utc_ref = 1788911999.9910216
    reg = _reg(rtp_ref=324_115_758, utc_ref=utc_ref)

    assert reg.sample0_utc_for(324_115_758 + 1_440_000) == utc_ref + 60.0
    assert reg.sample0_utc_for(324_115_758) == utc_ref


def test_a_start_rtp_before_the_reference_still_maps_backwards():
    """Fusion asks for at_rtp on either side of a member's rtp_ref."""
    utc_ref = 1788911999.9910216
    reg = _reg(rtp_ref=324_115_758, utc_ref=utc_ref)

    assert reg.sample0_utc_for(324_115_758 - 24_000) == utc_ref - 1.0
