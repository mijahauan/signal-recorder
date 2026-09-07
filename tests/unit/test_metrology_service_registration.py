"""apply_registration turns a skewed label plane into the acquired plane
and hands the engine a BufferTiming with origin_source='acquired'."""

import dataclasses
import json
import logging
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

    sample_rate = SR

    def prepare_audio(self, iq):
        return np.asarray(iq, dtype=np.float64)

    def expected_delays_s(self, system_time, utc_minute):
        return {"WWV": 0.0125}


def _service(tmp_path):
    svc = MetrologyService.__new__(MetrologyService)  # bypass the heavy __init__
    svc.channel_name = "SHARED_10000"
    svc.sample_rate = SR
    svc.engine = _Engine()
    svc.acquirer = RegistrationAcquirer("SHARED_10000", SR)
    svc.reg_store = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    svc.epoch_tracker = CounterEpochTracker()
    return svc


def _meta(k):
    return {
        "gps_time_ns": 1_000_000_000_000 + k * 60_000_000_000,
        "rtp_timesnap": 1_000_000 + k * 60 * SR,
        "sample_rate": SR,
    }


def test_first_minute_bootstraps_then_acquires(tmp_path):
    """task-11b: an own acquisition with no ACQUIRED siblings is a
    CANDIDATE until the tick detector verifies it -- the plane is still
    applied to BufferTiming (origin_source="acquired") in the meantime,
    but the published state is CANDIDATE, not ACQUIRED."""
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    label = label_timing(T0, 0.250, SR)  # radiod pair 250 ms late
    bt = svc.apply_registration(
        label, audio, start_rtp=1_000_000, minute_utc=MIN, metadata=_meta(0)
    )
    assert bt.origin_source == "acquired"
    assert bt.sample0_utc == pytest.approx(T0, abs=0.002)
    assert bt.origin_sigma_ms >= 1.0 and bt.counter_epoch_id.startswith("ep-")
    s = svc.reg_store.read_summary()
    assert s["state"] == "CANDIDATE" and s["raw_pair_residual_ms"] == pytest.approx(
        -250.0, abs=2.0
    )
    assert svc.acquirer.registration.verified is False


def test_verified_plane_publishes_acquired_next_minute(tmp_path):
    """task-11b: feed_back_ensembles with a tick-like ensemble for the
    acquired-plane's own station verifies it; the NEXT apply_registration
    then publishes ACQUIRED instead of CANDIDATE."""
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    label = label_timing(T0, 0.250, SR)
    svc.apply_registration(
        label, audio, start_rtp=1_000_000, minute_utc=MIN, metadata=_meta(0)
    )
    assert svc.reg_store.read_summary()["state"] == "CANDIDATE"
    r = SimpleNamespace(
        station="WWV",
        ensemble_timing_error_ms=0.3,
        sigma_single_ms=0.4,
        anchor_source="acquired",
    )
    svc.feed_back_ensembles([r])
    assert svc.acquirer.registration.verified is True
    bt2 = svc.apply_registration(
        label_timing(T0 + 60, 0.250, SR),
        audio,
        start_rtp=1_000_000 + 60 * SR,
        minute_utc=MIN + 60,
        metadata=_meta(1),
    )
    assert bt2.origin_source == "acquired"
    s = svc.reg_store.read_summary()
    assert s["state"] == "ACQUIRED"


def test_unverifiable_plane_publishes_bootstrap_next_minute(tmp_path):
    """task-11b: a junk (non-tick-like) ensemble fails verification and
    resets the acquirer -- the next minute publishes BOOTSTRAP."""
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    label = label_timing(T0, 0.250, SR)
    svc.apply_registration(
        label, audio, start_rtp=1_000_000, minute_utc=MIN, metadata=_meta(0)
    )
    r = SimpleNamespace(
        station="WWV",
        ensemble_timing_error_ms=2.0,
        sigma_single_ms=14.6,  # far past TIMING_SIGMA_MAX_MS -- not tick-like
        anchor_source="acquired",
    )
    svc.feed_back_ensembles([r])
    assert svc.acquirer.state == RegistrationAcquirer.STATE_BOOTSTRAP
    rng = np.random.default_rng(4)
    noise = 0.1 * rng.standard_normal(62 * SR)
    bt2 = svc.apply_registration(
        label_timing(T0 + 60, 0.250, SR),
        noise,
        start_rtp=1_000_000 + 60 * SR,
        minute_utc=MIN + 60,
        metadata=_meta(1),
    )
    assert bt2.origin_source == "label"
    assert svc.reg_store.read_summary()["state"] == "BOOTSTRAP"


def test_candidate_file_written_by_channel_a_is_not_adopted_by_channel_b(tmp_path):
    """task-11b: RegistrationStore.read_siblings already skips any file
    whose state isn't ACQUIRED -- confirm a CANDIDATE file (channel A's own
    unverified plane) is not picked up as a sibling by channel B."""
    svc_a = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    svc_a.apply_registration(
        label_timing(T0, 0.250, SR), audio, 1_000_000, MIN, _meta(0)
    )
    assert svc_a.reg_store.read_summary()["state"] == "CANDIDATE"
    channel_file = tmp_path / "reg" / "SHARED_10000.json"
    assert json.loads(channel_file.read_text())["state"] == "CANDIDATE"

    svc_b = _service(tmp_path)
    svc_b.channel_name = "WWV_20000"
    svc_b.acquirer = RegistrationAcquirer("WWV_20000", SR)
    sibs = svc_b.reg_store.read_siblings(exclude_channel="WWV_20000")
    assert sibs == []


def test_bootstrap_leaves_the_label_plane_marked(tmp_path):
    svc = _service(tmp_path)
    rng = np.random.default_rng(3)
    noise = 0.1 * rng.standard_normal(62 * SR)
    bt = svc.apply_registration(
        label_timing(T0, 0.1, SR), noise, 1_000_000, MIN, _meta(0)
    )
    assert bt.origin_source == "label" and bt.sample0_utc == T0 + 0.1
    assert svc.reg_store.read_summary()["state"] == "BOOTSTRAP"


def test_sibling_registration_is_adopted(tmp_path):
    svc = _service(tmp_path)
    from hf_timestd.core.registration_acquirer import Registration

    sib = Registration(
        counter_epoch_id=svc.epoch_tracker.observe(**_meta(0)),
        rtp_ref=1_000_000,
        utc_ref=T0,
        sample_rate=SR,
        sigma_ms=0.9,
        channel="WWV_20000",
    )
    svc.reg_store.write_channel(sib, "ACQUIRED", {})
    rng = np.random.default_rng(3)
    noise = 0.1 * rng.standard_normal(62 * SR)  # this channel hears nothing
    bt = svc.apply_registration(
        label_timing(T0, 0.3, SR), noise, 1_000_000, MIN, _meta(0)
    )
    assert bt.origin_source == "acquired" and bt.sample0_utc == pytest.approx(
        T0, abs=1e-6
    )


def test_shared_channel_ambiguity_resolved_by_same_site_sibling(tmp_path):
    svc = _service(tmp_path)

    class _Eng(_Engine):
        def expected_delays_s(self, system_time, utc_minute):
            return {"WWV": 0.0125, "BPM": 0.0465}  # shared 1000 Hz band, 34 ms apart

    svc.engine = _Eng()
    from hf_timestd.core.registration_acquirer import Registration

    epoch = svc.epoch_tracker.observe(**_meta(0))
    sib = Registration(
        epoch,
        rtp_ref=1_000_000,
        utc_ref=T0 + 0.0005,
        sample_rate=SR,
        sigma_ms=0.9,
        channel="WWV_20000",
        stations=("WWV",),
    )
    svc.reg_store.write_channel(sib, "ACQUIRED", {})
    audio = make_tick_audio(
        62, SR, T0, {"WWV": 0.0125}, snr_db=20.0
    )  # only WWV audible
    bt = svc.apply_registration(
        label_timing(T0, 0.1, SR), audio, 1_000_000, MIN, _meta(0)
    )
    assert bt.origin_source == "acquired" and bt.sample0_utc == pytest.approx(
        T0, abs=0.002
    )
    assert svc.acquirer.registration.stations == (
        "WWV",
    )  # resolved, not merely adopted
    assert "SHARED_10000" in svc.reg_store.read_summary()["contributing"]


def test_feed_back_reacquires_on_sustained_residual(tmp_path):
    """task-11b: feed_back_ensembles routes an unverified plane's first
    good ensemble to verify() rather than corroborate(); this test is
    about corroborate's OWN sustained-residual/reacquire logic, so mark
    the plane verified directly rather than spending one of the two calls
    on verification."""
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    svc.apply_registration(label_timing(T0, 0.0, SR), audio, 1_000_000, MIN, _meta(0))
    svc.acquirer.registration.verified = True
    r = SimpleNamespace(
        station="WWV",
        ensemble_timing_error_ms=40.0,
        sigma_single_ms=0.5,
        anchor_source="acquired",
    )
    svc.feed_back_ensembles([r])
    svc.feed_back_ensembles([r])
    assert svc.acquirer.state == RegistrationAcquirer.STATE_BOOTSTRAP


# ── Fix round 1 (task-8-review.md / task-8-fix1-brief.md) ──────────────


def test_t6_authoritative_plane_is_not_replaced(tmp_path):
    """C3: T6 must win.  ``judge_tier == "T6"`` on the incoming plane (the
    sidecar/replay shape) means the ring anchor already carries T6's
    correction -- apply_registration must publish a WITNESS, not overwrite
    the origin."""
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    label = label_timing(T0, 0.010, SR)  # T6 says T0+10ms; the ticks agree closely
    label.judge_tier = "T6"
    bt = svc.apply_registration(label, audio, 1_000_000, MIN, _meta(0))
    assert bt.origin_source == "label"
    assert bt.sample0_utc == pytest.approx(
        T0 + 0.010, abs=1e-9
    )  # T6's plane, untouched
    s = svc.reg_store.read_summary()
    assert s["state"] == "WITNESS"
    # acquired ~T0, label T0+10ms -> residual (acquired - label) ~ -10 ms
    assert s["residual_vs_t6_ms"] == pytest.approx(-10.0, abs=2.0)


def test_t6_authoritative_via_authority_json_on_the_live_ring_path(tmp_path):
    """C3, second path: the live ring never populates ``judge_tier`` on
    BufferTiming (ring_buffer_reader's metadata carries no "timing" block --
    confirmed by reading resolve_buffer_timing and ring_buffer_reader.
    extract_interval), so on that path the tier must come from
    AuthorityManager's own /run/hf-timestd/authority.json."""
    svc = _service(tmp_path)
    auth_path = tmp_path / "authority.json"
    auth_path.write_text(json.dumps({"t_level_active": "T6"}))
    svc._AUTHORITY_JSON_PATH = auth_path
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    label = label_timing(T0, 0.010, SR)
    assert label.judge_tier is None  # the live-ring shape: never populated
    bt = svc.apply_registration(label, audio, 1_000_000, MIN, _meta(0))
    assert bt.origin_source == "label" and bt.sample0_utc == label.sample0_utc
    assert svc.reg_store.read_summary()["state"] == "WITNESS"


def test_missing_authority_json_is_not_authoritative(tmp_path):
    """Absent file -> not authoritative (no crash, normal acquisition)."""
    svc = _service(tmp_path)
    svc._AUTHORITY_JSON_PATH = tmp_path / "does_not_exist.json"
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    bt = svc.apply_registration(
        label_timing(T0, 0.1, SR), audio, 1_000_000, MIN, _meta(0)
    )
    assert bt.origin_source == "acquired"


def test_adopted_plane_does_not_re_enter_fusion(tmp_path):
    """C1: adopt() must stamp this channel's own name and method="adopted",
    and an adopted plane must never contribute back into its own fusion
    (mathematically: fusing an echo of a sibling alongside that same
    sibling understates sigma) nor appear as "fused" in contributing.
    Four-minute probe from the review: one sibling sigma 0.9ms, this
    channel hears nothing every minute -> summary sigma must stay 0.9ms."""
    svc = _service(tmp_path)
    from hf_timestd.core.registration_acquirer import Registration

    sib = Registration(
        counter_epoch_id=svc.epoch_tracker.observe(**_meta(0)),
        rtp_ref=1_000_000,
        utc_ref=T0,
        sample_rate=SR,
        sigma_ms=0.9,
        channel="WWV_20000",
    )
    svc.reg_store.write_channel(sib, "ACQUIRED", {})
    rng = np.random.default_rng(3)
    for k in range(4):
        noise = 0.1 * rng.standard_normal(62 * SR)  # this channel hears nothing, ever
        svc.apply_registration(
            label_timing(T0, 0.3, SR),
            noise,
            1_000_000 + k * 60 * SR,
            MIN + k * 60,
            _meta(k),
        )
    assert svc.acquirer.registration.channel == "SHARED_10000"
    assert svc.acquirer.registration.method == "adopted"
    s = svc.reg_store.read_summary()
    assert s["sigma_ms"] == pytest.approx(0.9, abs=1e-6)
    assert "fused" not in s["contributing"]


def test_apply_registration_failure_keeps_the_label_plane(tmp_path, monkeypatch):
    """I1: a raising acquirer must not wedge the minute -- apply_registration
    logs and returns the ORIGINAL (label) plane unchanged."""
    svc = _service(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc.acquirer, "offer_minute", _boom)
    label = label_timing(T0, 0.1, SR)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    bt = svc.apply_registration(label, audio, 1_000_000, MIN, _meta(0))
    assert bt is label
    assert bt.origin_source == "label" and bt.sample0_utc == T0 + 0.1


def test_sibling_conflict_reverts_to_label_and_flags_conflict(tmp_path):
    """I2: this channel's own ACQUIRED plane disagreeing with its sibling
    (nothing within FUSE_OUTLIER_MS of the combined median) must publish
    ONE state ("CONFLICT", not channel=ACQUIRED/summary=BOOTSTRAP) and
    revert to the label plane, with a warning naming the disagreement.

    fuse_registrations' median can only return an empty "keep" set for an
    EVEN total (an odd count always keeps at least the middle value, which
    sits at distance 0 from itself) -- so the minimal, reliable
    reproduction is exactly two planes (this channel's own + one sibling),
    not the review's "two siblings" text verbatim."""
    svc = _service(tmp_path)
    from hf_timestd.core.registration_acquirer import Registration

    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    svc.apply_registration(label_timing(T0, 0.0, SR), audio, 1_000_000, MIN, _meta(0))
    assert svc.acquirer.state == RegistrationAcquirer.STATE_ACQUIRED
    own_epoch = svc.acquirer.registration.counter_epoch_id
    sib = Registration(
        own_epoch,
        rtp_ref=1_000_000,
        utc_ref=T0 + 0.020,
        sample_rate=SR,
        sigma_ms=0.9,
        channel="WWV_20000",
    )
    svc.reg_store.write_channel(sib, "ACQUIRED", {})
    audio1 = make_tick_audio(62, SR, T0 + 60, {"WWV": 0.0125}, snr_db=20.0, seed=8)
    bt = svc.apply_registration(
        label_timing(T0 + 60, 0.0, SR),
        audio1,
        1_000_000 + 60 * SR,
        MIN + 60,
        _meta(1),
    )
    assert bt.origin_source == "label"
    s = svc.reg_store.read_summary()
    assert s["state"] == "CONFLICT"
    assert "SHARED_10000" in s["contributing"] and "WWV_20000" in s["contributing"]


def test_adopted_plane_with_expired_donor_returns_to_bootstrap(tmp_path, caplog):
    """New Important (re-review, fix round 2): CONFLICT requires siblings
    to disagree WITH.  The C1 fix (excluding an adopted `own` from
    fusion_inputs) meant that once the donor's file goes stale (or
    disappears), fusion_inputs is empty, fuse_registrations([]) is None,
    and the old code read that as "channels disagree" -- publishing
    CONFLICT and the label plane every minute forever, with a WARNING
    naming nothing (empty parentheses), because ACQUIRED short-circuits
    offer_minute and a label-plane ensemble never reaches corroborate.
    An orphaned adopted plane must instead reset to BOOTSTRAP so the
    channel tries its own signal (or re-adopts a fresh sibling) next
    minute."""
    svc = _service(tmp_path)
    clock = [1_000_000.0]
    svc.reg_store = RegistrationStore(
        tmp_path / "reg", tmp_path / "registration.json", time_fn=lambda: clock[0]
    )
    from hf_timestd.core.registration_acquirer import Registration

    # minute 1: this channel hears nothing and adopts a sibling's plane.
    sib = Registration(
        counter_epoch_id=svc.epoch_tracker.observe(**_meta(0)),
        rtp_ref=1_000_000,
        utc_ref=T0,
        sample_rate=SR,
        sigma_ms=0.9,
        channel="WWV_20000",
    )
    svc.reg_store.write_channel(sib, "ACQUIRED", {})
    rng = np.random.default_rng(3)
    noise1 = 0.1 * rng.standard_normal(62 * SR)
    bt1 = svc.apply_registration(
        label_timing(T0, 0.3, SR), noise1, 1_000_000, MIN, _meta(0)
    )
    assert bt1.origin_source == "acquired"
    assert svc.acquirer.registration.channel == "SHARED_10000"
    assert svc.acquirer.registration.method == "adopted"

    # advance the clock past the sibling file's staleness window (300 s).
    clock[0] += 301.0

    # minute 2: the donor's file is now stale -> read_siblings drops it ->
    # fusion_inputs is empty -> ORPHAN, not CONFLICT.
    noise2 = 0.1 * rng.standard_normal(62 * SR)
    with caplog.at_level("WARNING", logger="hf_timestd.core.metrology_service"):
        bt2 = svc.apply_registration(
            label_timing(T0 + 60, 0.3, SR),
            noise2,
            1_000_000 + 60 * SR,
            MIN + 60,
            _meta(1),
        )
    assert bt2.origin_source == "label"
    s = svc.reg_store.read_summary()
    assert s["state"] == "BOOTSTRAP"
    assert svc.acquirer.state == RegistrationAcquirer.STATE_BOOTSTRAP
    # no "sibling registrations disagree ... ()" warning naming nothing
    assert not any("own plane ()" in r.getMessage() for r in caplog.records)
    assert not any(
        r.levelno >= logging.WARNING and "CONFLICT" in r.getMessage()
        for r in caplog.records
    )

    # minute 3: audible ticks -> re-acquires from this channel's OWN signal.
    audio3 = make_tick_audio(62, SR, T0 + 120, {"WWV": 0.0125}, snr_db=20.0, seed=9)
    bt3 = svc.apply_registration(
        label_timing(T0 + 120, 0.0, SR),
        audio3,
        1_000_000 + 120 * SR,
        MIN + 120,
        _meta(2),
    )
    assert bt3.origin_source == "acquired"
    assert svc.acquirer.state == RegistrationAcquirer.STATE_ACQUIRED
    assert svc.acquirer.registration.method != "adopted"


def test_host_label_ensemble_does_not_reach_corroborate(tmp_path, monkeypatch):
    """I3: the anchor_source filter -- a host_label ensemble must never
    reach RegistrationAcquirer.corroborate."""
    svc = _service(tmp_path)
    seen = []
    monkeypatch.setattr(
        svc.acquirer, "corroborate", lambda res: seen.append(res) or "held"
    )
    r = SimpleNamespace(
        station="WWV",
        ensemble_timing_error_ms=40.0,
        sigma_single_ms=0.5,
        anchor_source="host_label",
    )
    svc.feed_back_ensembles([r])
    assert seen == []


def test_counter_epoch_change_on_the_live_ring_reacquires(tmp_path):
    """I3: a pair jump > COUNTER_EPOCH_STEP_S mid-stream resets the acquirer
    to BOOTSTRAP and, at good SNR, lets it re-acquire within the same
    minute -- exercised through the service's own apply_registration, not
    just the acquirer directly."""
    svc = _service(tmp_path)
    audio0 = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    bt0 = svc.apply_registration(
        label_timing(T0, 0.0, SR), audio0, 1_000_000, MIN, _meta(0)
    )
    assert bt0.origin_source == "acquired"
    epoch0 = svc.acquirer.registration.counter_epoch_id
    meta1 = dict(_meta(1))
    meta1["gps_time_ns"] = meta1["gps_time_ns"] + int(
        0.7e9
    )  # pair jumps 0.7s -> new epoch
    audio1 = make_tick_audio(62, SR, T0 + 60, {"WWV": 0.0125}, snr_db=20.0, seed=8)
    bt1 = svc.apply_registration(
        label_timing(T0 + 60, 0.0, SR),
        audio1,
        1_000_000 + 60 * SR,
        MIN + 60,
        meta1,
    )
    assert svc.acquirer.registration is not None
    epoch1 = svc.acquirer.registration.counter_epoch_id
    assert epoch1 != epoch0
    assert bt1.origin_source == "acquired"  # re-acquired within the same minute


def test_no_timing_buffer_returns_unchanged_with_no_store_write(
    tmp_path, monkeypatch, caplog
):
    """I3: the no_timing guard -- returned unchanged, no store write, and
    the acquirer never even offered the minute.

    Given teeth (fix round 2): a 10-sample buffer let the *previous*
    version of this test pass for the wrong reason -- with the guard
    deleted, the unsafe path raised ValueError out of sosfiltfilt on the
    too-short buffer, and I1's blanket except caught it and returned the
    same object, so the assertions held even with no guard at all.  A
    full 62 s clean 20 dB audio buffer means nothing raises on its own;
    offer_minute is monkeypatched to explode if the guard is ever
    removed; and asserting no ERROR was logged rules out "the guard is
    gone but I1's except silently saved us" as an explanation for a pass.
    """
    svc = _service(tmp_path)

    def _must_not_be_offered(*a, **k):
        raise AssertionError("must not be offered")

    monkeypatch.setattr(svc.acquirer, "offer_minute", _must_not_be_offered)
    bt_in = BufferTiming(
        sample0_utc=0.0,
        sample_rate=SR,
        source="no_timing",
        n_snapshots_used=0,
        jitter_ms=float("inf"),
    )
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    with caplog.at_level("ERROR", logger="hf_timestd.core.metrology_service"):
        bt_out = svc.apply_registration(bt_in, audio, 1_000_000, MIN, _meta(0))
    assert bt_out is bt_in
    assert svc.reg_store.read_summary() is None
    assert not (tmp_path / "reg").exists()
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_resolve_before_adopt_precedence(tmp_path, monkeypatch):
    """I3: resolve-before-adopt precedence -- monkeypatch adopt to raise;
    the ambiguity-resolution test must still pass because adopt is never
    reached when resolve_ambiguity already named the station."""
    svc = _service(tmp_path)

    class _Eng(_Engine):
        def expected_delays_s(self, system_time, utc_minute):
            return {"WWV": 0.0125, "BPM": 0.0465}

    svc.engine = _Eng()
    from hf_timestd.core.registration_acquirer import Registration

    epoch = svc.epoch_tracker.observe(**_meta(0))
    sib = Registration(
        epoch,
        rtp_ref=1_000_000,
        utc_ref=T0 + 0.0005,
        sample_rate=SR,
        sigma_ms=0.9,
        channel="WWV_20000",
        stations=("WWV",),
    )
    svc.reg_store.write_channel(sib, "ACQUIRED", {})

    def _boom(reg):
        raise AssertionError(
            "adopt must not run when resolve_ambiguity already acquired"
        )

    monkeypatch.setattr(svc.acquirer, "adopt", _boom)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    bt = svc.apply_registration(
        label_timing(T0, 0.1, SR), audio, 1_000_000, MIN, _meta(0)
    )
    assert bt.origin_source == "acquired" and bt.sample0_utc == pytest.approx(
        T0, abs=0.002
    )
