"""apply_registration turns a skewed label plane into the acquired plane
and hands the engine a BufferTiming with origin_source='acquired'."""

import dataclasses
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
    svc._last_registration_meta = {}
    return svc


def _meta(k):
    return {
        "gps_time_ns": 1_000_000_000_000 + k * 60_000_000_000,
        "rtp_timesnap": 1_000_000 + k * 60 * SR,
        "sample_rate": SR,
    }


def test_first_minute_bootstraps_then_acquires(tmp_path):
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
    assert s["state"] == "ACQUIRED" and s["raw_pair_residual_ms"] == pytest.approx(
        -250.0, abs=2.0
    )


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
    svc = _service(tmp_path)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    svc.apply_registration(label_timing(T0, 0.0, SR), audio, 1_000_000, MIN, _meta(0))
    r = SimpleNamespace(
        station="WWV",
        ensemble_timing_error_ms=40.0,
        sigma_single_ms=0.5,
        anchor_source="acquired",
    )
    svc.feed_back_ensembles([r])
    svc.feed_back_ensembles([r])
    assert svc.acquirer.state == RegistrationAcquirer.STATE_BOOTSTRAP
