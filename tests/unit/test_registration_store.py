import json

import pytest

from hf_timestd.core.registration_acquirer import Registration
from hf_timestd.core.registration_store import (
    RegistrationStore,
    fuse_registrations,
    fuse_registrations_with_members,
)

SR = 24000


def _reg(ch, utc_ref, sigma, epoch="ep-1", rtp_ref=1000, epoch_offset_s=float("nan")):
    return Registration(
        counter_epoch_id=epoch,
        rtp_ref=rtp_ref,
        utc_ref=utc_ref,
        sample_rate=SR,
        sigma_ms=sigma,
        channel=ch,
        epoch_offset_s=epoch_offset_s,
    )


def test_fuse_inverse_variance_and_outlier():
    regs = [_reg("a", 100.000, 1.0), _reg("b", 100.0005, 0.5), _reg("c", 100.0100, 0.5)]
    f = fuse_registrations(regs, at_rtp=1000)
    # c is 10 ms off the median -> rejected; a,b weighted 1:4
    assert f.utc_ref == pytest.approx(100.0004, abs=2e-5)
    assert f.sigma_ms == pytest.approx(1 / (1 + 4) ** 0.5, abs=1e-3)
    assert f.rtp_ref == 1000 and f.channel == "fused"


def test_fuse_unions_stations_and_roundtrips_them(tmp_path):
    regs = [
        Registration("ep-1", 1000, 100.0, SR, 1.0, channel="a", stations=("WWV",)),
        Registration(
            "ep-1", 1000, 100.0, SR, 1.0, channel="b", stations=("WWVH", "WWV")
        ),
    ]
    assert fuse_registrations(regs, 1000).stations == ("WWV", "WWVH")
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_channel(regs[1], "ACQUIRED", {})
    assert st.read_siblings()[0].stations == ("WWVH", "WWV")


def test_fuse_rebases_to_common_rtp():
    regs = [_reg("a", 100.0, 1.0, rtp_ref=0), _reg("a2", 101.0, 1.0, rtp_ref=SR)]
    f = fuse_registrations(regs, at_rtp=2 * SR)
    assert f.utc_ref == pytest.approx(102.0)


def test_fuse_majority_epoch_wins_and_empty_is_none():
    regs = [
        _reg("a", 100.0, 1.0, "ep-2"),
        _reg("b", 100.0, 1.0, "ep-2"),
        _reg("c", 5.0, 1.0, "ep-1"),
    ]
    assert fuse_registrations(regs, 1000).counter_epoch_id == "ep-2"
    assert fuse_registrations([], 1000) is None


def test_store_roundtrip_and_staleness(tmp_path):
    clock = [1000.0]
    st = RegistrationStore(
        tmp_path / "reg",
        tmp_path / "registration.json",
        stale_s=300.0,
        time_fn=lambda: clock[0],
    )
    st.write_channel(
        _reg("SHARED_10000", 100.0, 1.0), "ACQUIRED", {"correction_ms": -250.0}
    )
    st.write_channel(_reg("WWV_20000", 100.001, 2.0), "ACQUIRED", {})
    sibs = st.read_siblings(exclude_channel="SHARED_10000")
    assert [r.channel for r in sibs] == ["WWV_20000"]
    clock[0] += 301
    assert st.read_siblings() == []
    data = json.loads((tmp_path / "reg" / "SHARED_10000.json").read_text())
    assert data["correction_ms"] == -250.0 and data["state"] == "ACQUIRED"


def test_summary(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_summary(
        _reg("fused", 100.0, 0.7),
        ["SHARED_10000", "WWV_20000"],
        "ACQUIRED",
        {"raw_pair_residual_ms": 16.7},
    )
    s = st.read_summary()
    assert s["state"] == "ACQUIRED" and s["contributing"] == [
        "SHARED_10000",
        "WWV_20000",
    ]
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


def test_candidate_state_file_is_not_a_sibling(tmp_path):
    """task-11b: RegistrationStore.read_siblings already filters on
    ``state == "ACQUIRED"`` -- confirm a channel file written with the new
    CANDIDATE state (an own plane not yet verified by the tick detector)
    is not picked up as a sibling."""
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_channel(_reg("WWV_25000", 100.0, 3.116), "CANDIDATE", {})
    text = (tmp_path / "reg" / "WWV_25000.json").read_text()
    assert json.loads(text)["state"] == "CANDIDATE"
    assert st.read_siblings() == []


def test_adopted_registration_is_not_a_sibling(tmp_path):
    """C1: a channel that merely ADOPTED a sibling's (or fusion's) plane
    must never re-enter another channel's fusion as if it were independent
    evidence -- otherwise the same measurement gets inverse-variance
    combined with itself and sigma is understated by sqrt(n_adopters+1)."""
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    reg = Registration(
        "ep-1", 1000, 100.0, SR, 0.9, method="adopted", channel="SHARED_10000"
    )
    st.write_channel(reg, "ACQUIRED", {})
    assert st.read_siblings() == []
    assert st.read_siblings(exclude_channel="WWV_20000") == []


def test_read_siblings_skips_a_schema_incomplete_file(tmp_path):
    clock = [5000.0]
    st = RegistrationStore(
        tmp_path / "reg",
        tmp_path / "registration.json",
        time_fn=lambda: clock[0],
    )
    # Write a valid ACQUIRED file for channel "a"
    st.write_channel(_reg("a", 100.0, 1.0), "ACQUIRED", {})
    # Write an incomplete JSON file for channel "b" (missing rtp_ref)
    # Use written_at=5000.0 (same as current clock) so it's not stale
    (tmp_path / "reg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reg" / "b.json").write_text(
        json.dumps(
            {
                "channel": "b",
                "state": "ACQUIRED",
                "utc_ref": 1.0,
                "sigma_ms": 1.0,
                "written_at": 5000.0,
            }
        )
    )
    # read_siblings must return exactly the "a" registration
    # (b is skipped by the KeyError guard since it's missing rtp_ref)
    sibs = st.read_siblings()
    assert len(sibs) == 1
    assert sibs[0].channel == "a"


def test_write_failure_is_counted(tmp_path):
    # Create a file at the directory path so mkdir cannot create it
    bad_dir = tmp_path / "bad_file.txt"
    bad_dir.write_text("not a directory")
    st = RegistrationStore(bad_dir / "reg", tmp_path / "registration.json")
    st.write_channel(_reg("test", 100.0, 1.0), "ACQUIRED", {})
    assert st.write_failures == 1


# ── C1: cluster by IMPLIED OFFSET, not by epoch id string ─────────────


def test_fuse_clusters_by_offset_across_differently_named_epochs():
    """C1 (final review): metrology runs one process per channel, each with
    its own CounterEpochTracker sampling the ring anchor at its own phase,
    so two channels in ONE physical counter epoch carry two different
    ``counter_epoch_id`` strings.  The old majority-epoch filter saw every
    count tied at 1, ``max`` returned the first key in insertion order, and
    every other channel was discarded -- inverse-variance combination across
    channels (spec §4.6) silently degraded to "pick one channel".  Cluster by
    the implied offset instead: two 1.0 ms planes must fuse to 0.707 ms."""
    off = 1_000_000_000.0
    regs = [
        _reg("a", 100.0, 1.0, epoch="ep-A", epoch_offset_s=off),
        _reg("b", 100.0, 1.0, epoch="ep-B", epoch_offset_s=off + 0.0019),
    ]
    f = fuse_registrations(regs, at_rtp=1000)
    assert f.sigma_ms == pytest.approx(1.0 / 2**0.5, abs=1e-6)
    assert f.utc_ref == pytest.approx(100.0)


def test_fuse_rejects_a_channel_from_a_different_counter_space():
    """The other half of C1: an offset a full counter epoch away (hours) is
    a different RTP counter space and must NOT be fused in, however its id
    string happens to be spelled."""
    off = 1_000_000_000.0
    regs = [
        _reg("a", 100.0, 1.0, epoch="ep-A", epoch_offset_s=off),
        _reg("b", 100.0, 1.0, epoch="ep-A", epoch_offset_s=off + 0.0019),
        _reg("c", 100.0, 0.2, epoch="ep-A", epoch_offset_s=off + 69732.0),
    ]
    fused, kept = fuse_registrations_with_members(regs, at_rtp=1000)
    assert [r for r in kept] == ["a", "b"]
    assert fused.sigma_ms == pytest.approx(1.0 / 2**0.5, abs=1e-6)


def test_fuse_offset_tie_goes_to_the_cluster_with_the_smallest_sigma():
    """Two clusters of equal size: prefer the one holding the tightest
    plane rather than whichever landed first in insertion order (the
    defect the string-id ``max`` had)."""
    off = 1_000_000_000.0
    regs = [
        _reg("a", 100.0, 1.0, epoch_offset_s=off),
        _reg("b", 200.0, 0.25, epoch_offset_s=off + 4000.0),
    ]
    fused, kept = fuse_registrations_with_members(regs, at_rtp=1000)
    assert kept == ["b"] and fused.utc_ref == pytest.approx(200.0)


def test_fuse_falls_back_to_the_id_string_when_offsets_are_unknown():
    """A registration written before ``epoch_offset_s`` existed (or by a
    tracker that never saw a valid pair) carries NaN.  Then the only thing
    left to group by is the id string, which is the pre-C1 behaviour."""
    regs = [
        _reg("a", 100.0, 1.0, "ep-2"),
        _reg("b", 100.0, 1.0, "ep-2"),
        _reg("c", 5.0, 1.0, "ep-1"),
    ]
    fused, kept = fuse_registrations_with_members(regs, at_rtp=1000)
    assert fused.counter_epoch_id == "ep-2" and kept == ["a", "b"]


def test_fuse_members_are_what_fusion_actually_kept():
    """C1's third consequence: the summary's ``contributing`` claimed N
    contributors for a one-channel answer.  ``fuse_registrations_with_members``
    returns the channels the outlier test kept, so the caller can publish
    the truth."""
    off = 1_000_000_000.0
    regs = [
        _reg("a", 100.000, 1.0, epoch_offset_s=off),
        _reg("b", 100.0005, 0.5, epoch_offset_s=off),
        _reg("c", 100.0100, 0.5, epoch_offset_s=off),
    ]
    fused, kept = fuse_registrations_with_members(regs, at_rtp=1000)
    assert kept == ["a", "b"]  # c is 10 ms off the median
    assert fused.epoch_offset_s == pytest.approx(off)


def test_store_round_trips_the_epoch_offset(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_channel(
        _reg("WWV_20000", 100.0, 1.0, epoch_offset_s=1_234.5), "ACQUIRED", {}
    )
    data = json.loads((tmp_path / "reg" / "WWV_20000.json").read_text())
    assert data["epoch_offset_s"] == pytest.approx(1_234.5)
    assert st.read_siblings()[0].epoch_offset_s == pytest.approx(1_234.5)


def test_store_writes_null_for_an_unknown_epoch_offset(tmp_path):
    """strict JSON: NaN is not a JSON number.  It must round-trip as null
    -> NaN, and a null must not make the file unreadable as a sibling."""
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_channel(_reg("WWV_20000", 100.0, 1.0), "ACQUIRED", {})
    text = (tmp_path / "reg" / "WWV_20000.json").read_text()
    assert "NaN" not in text and json.loads(text)["epoch_offset_s"] is None
    import math

    assert math.isnan(st.read_siblings()[0].epoch_offset_s)


# ── Task 16b: the fused plane's corroboration is its WEAKEST member's ──


def test_fused_n_minutes_is_the_minimum_over_the_kept_members():
    """A fused plane inherits the weakest provenance among the members it
    kept -- ``verified`` already works that way (task-14c), and
    ``n_minutes`` must too.  Taking the MAXIMUM let one channel's long
    history vouch for a sibling that had corroborated nothing, which is
    exactly what the ADOPT_MIN_CORROBORATED_MINUTES gate exists to
    refuse."""
    off = 1_000_000_000.0
    regs = [
        Registration(
            counter_epoch_id="ep-1",
            rtp_ref=1000,
            utc_ref=100.0,
            sample_rate=SR,
            sigma_ms=1.0,
            n_minutes=17,
            channel="a",
            verified=True,
            epoch_offset_s=off,
        ),
        Registration(
            counter_epoch_id="ep-1",
            rtp_ref=1000,
            utc_ref=100.0005,
            sample_rate=SR,
            sigma_ms=1.0,
            n_minutes=0,
            channel="b",
            verified=True,
            epoch_offset_s=off,
        ),
    ]
    fused, kept = fuse_registrations_with_members(regs, at_rtp=1000)
    assert kept == ["a", "b"]
    assert fused.n_minutes == 0
    # and an outlier that fusion DROPS cannot hold the number down
    regs.append(
        Registration(
            counter_epoch_id="ep-1",
            rtp_ref=1000,
            utc_ref=100.010,  # 10 ms off the median
            sample_rate=SR,
            sigma_ms=1.0,
            n_minutes=0,
            channel="c",
            verified=True,
            epoch_offset_s=off,
        )
    )
    regs[1] = Registration(**{**regs[1].__dict__, "n_minutes": 5})
    fused2, kept2 = fuse_registrations_with_members(regs, at_rtp=1000)
    assert kept2 == ["a", "b"] and fused2.n_minutes == 5
