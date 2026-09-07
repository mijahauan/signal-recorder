"""T3 self-registration, spec §5: an ensemble measured on an acquired
plane (``BufferTiming.origin_source == 'acquired'``) is labelled
``anchor_source='acquired'`` and carries the plane's registration
sigma on ``anchor_sigma_ms``.  ``timing_admissible`` accepts it only
when that sigma is tight (< 2 ms) AND the ensemble itself looks like
ticks, not window scatter (sigma_single_ms still gates junk on a good
plane).  ``minute_marker`` and ``host_label`` rules are unchanged.
"""

from __future__ import annotations

import dataclasses

from hf_timestd.core.tick_edge_detector import EdgeEnsembleResult, TickEdgeDetector
from synth_ticks import make_tick_audio, label_timing

SR = 24000
MIN = 1_800_000_000
T0 = MIN - 1.0


def _res(anchor_source, anchor_sigma_ms, sigma_single_ms=0.5):
    return EdgeEnsembleResult(
        station="WWV",
        frequency_hz=1e7,
        minute_number=MIN,
        ensemble_timing_error_ms=0.0,
        ensemble_uncertainty_ms=0.1,
        ensemble_n_edges=50,
        n_attempted=57,
        n_detected=50,
        n_clean=50,
        mean_edge_snr_db=30.0,
        confidence=0.9,
        anchor_source=anchor_source,
        sigma_single_ms=sigma_single_ms,
        anchor_sigma_ms=anchor_sigma_ms,
    )


def test_acquired_admitted_when_registration_is_tight():
    ok, why = TickEdgeDetector.timing_admissible(_res("acquired", 0.8))
    assert ok and "acquired" in why


def test_acquired_refused_when_registration_is_loose_or_ensemble_is_junk():
    assert not TickEdgeDetector.timing_admissible(_res("acquired", 2.5))[0]
    assert not TickEdgeDetector.timing_admissible(
        _res("acquired", 0.8, sigma_single_ms=15.0)
    )[0]


def test_marker_and_label_rules_unchanged():
    assert TickEdgeDetector.timing_admissible(_res("minute_marker", float("inf")))[0]
    assert TickEdgeDetector.timing_admissible(_res("host_label", float("inf"), 3.0))[0]
    assert not TickEdgeDetector.timing_admissible(
        _res("host_label", float("inf"), 9.0)
    )[0]


def test_detector_labels_an_acquired_plane():
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0045}, snr_db=25.0)
    bt = dataclasses.replace(
        label_timing(T0, 0.0, SR), origin_source="acquired", origin_sigma_ms=0.9
    )
    det = TickEdgeDetector(sample_rate=SR)
    res = det.detect_edges(
        audio_signal=audio,
        station="WWV",
        minute_number=MIN,
        buffer_timing=bt,
        expected_delay_sec=0.0045,
        is_dedicated_channel=True,
        iq_samples=None,
    )
    assert res is not None
    assert res.anchor_source == "acquired" and res.anchor_sigma_ms == 0.9
    assert abs(res.ensemble_timing_error_ms) < 1.0
