"""The refclock gate stops letting the host clock veto the anchor
(fix round 1, review finding C-2).

`WITHDRAW_VERDICTS = ("suspect", "fault")` dates from 2026-09-04 and fit
the old feed exactly: a host-relative d_clock measured the clock it
steered, so withdrawing it let chrony follow witnesses that did not share
the frame.

Spec §11.2 inverted the premise.  The anchor-direct sample carries no
host frame at all, and it states the very error the verdict reports.
Worse, the same change makes the pair witness read the FULL host error
instead of ~0 -- the witness compares the host against the rtp-frame
active tier, and that tier's plane moved from "radiod's pair plus a judge
offset" to "the registration".  So the verdict stays `suspect`, and the
old rule holds `+noselect` on the one refclock that could fix it.

In the no-host-clock model the refclock IS the correction.  `suspect` is
the normal reading of a clock being corrected; `fault` -- the witnesses
disagreeing with each other -- still withdraws.
"""

import json

import pytest

from hf_timestd.core.chrony_refclock_gate import ChronyRefclockGate
from hf_timestd.core.fusion_status_writer import FusionStatusWriter


class _Runner:
    """Records the chronyc argv the gate would run."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))

        class _P:
            returncode = 0
            stdout = ""
            stderr = ""

        return _P()

    @property
    def flags(self):
        return [a[-1] for a in self.calls]


def _gate(regime, clock=None, **kw):
    return ChronyRefclockGate(
        runner=_Runner() if "runner" not in kw else kw.pop("runner"),
        feed_regime_fn=(regime if callable(regime) else (lambda: regime)),
        now_fn=(lambda: clock[0]) if clock else (lambda: 0.0),
        **kw,
    )


# ── anchor-direct: suspect is expected, not disqualifying ────────────


def test_suspect_keeps_fuse_selectable_under_the_anchor_feed(caplog):
    runner = _Runner()
    g = _gate("anchor", runner=runner)
    res = g.apply("T3", "suspect")
    assert res.target_state == "enabled"
    assert g.host_clock_withdrawn is False
    assert runner.flags == ["-noselect"]
    assert "anchor-direct" in res.reason


def test_the_expected_note_is_logged_once_per_regime_entry(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="hf_timestd.core.chrony_refclock_gate")
    g = _gate("anchor")
    g.apply("T3", "suspect")
    g.apply("T3", "suspect")
    g.apply("T3", "suspect")
    notes = [r for r in caplog.records if "expected while correcting" in r.getMessage()]
    assert len(notes) == 1


def test_fault_still_withdraws_under_the_anchor_feed():
    runner = _Runner()
    g = _gate("anchor", runner=runner)
    res = g.apply("T3", "fault")
    assert res.target_state == "disabled"
    assert g.host_clock_withdrawn is True
    assert runner.flags == ["+noselect"]
    assert res.reason.endswith("host_clock:fault)")


def test_a_legacy_withdrawal_is_released_when_the_anchor_takes_over():
    """The deadlock the review found: a station already withdrawn under
    the legacy rule would stay withdrawn forever, because `suspect` no
    longer starts the 600 s clearing window."""
    regime = {"v": "fusion_d_clock"}
    runner = _Runner()
    g = _gate(lambda: regime["v"], runner=runner)
    g.apply("T3", "suspect")
    assert g.host_clock_withdrawn is True and runner.flags == ["+noselect"]
    regime["v"] = "anchor"
    res = g.apply("T3", "suspect")
    assert g.host_clock_withdrawn is False
    assert res.target_state == "enabled" and runner.flags[-1] == "-noselect"
    assert "released" in res.reason


def test_the_tier_rule_still_governs_under_the_anchor_feed():
    """The anchor exception is about the host clock only.  A tier that
    Fusion does not serve still disables the refclock (§4.6)."""
    runner = _Runner()
    g = _gate("anchor", runner=runner)
    assert g.apply("T4", "suspect").target_state == "disabled"
    assert runner.flags == ["+noselect"]


# ── legacy regime: byte-identical behaviour ──────────────────────────


@pytest.mark.parametrize("regime", ["fusion_d_clock", None, "something_else"])
def test_suspect_still_withdraws_off_the_anchor_feed(regime):
    runner = _Runner()
    g = _gate(regime, runner=runner)
    res = g.apply("T3", "suspect")
    assert res.target_state == "disabled"
    assert g.host_clock_withdrawn is True
    assert runner.flags == ["+noselect"]
    assert res.reason.endswith("host_clock:suspect)")


def test_the_600s_clearing_window_is_untouched_off_the_anchor_feed():
    clock = [1000.0]
    runner = _Runner()
    g = _gate("fusion_d_clock", clock=clock, runner=runner)
    g.apply("T3", "suspect")
    assert runner.flags == ["+noselect"]
    # the clearing window starts at the first `ok`, not at the withdrawal
    assert g.apply("T3", "ok").target_state == "disabled"
    clock[0] += 599.0
    assert g.apply("T3", "ok").target_state == "disabled"
    clock[0] += 2.0
    res = g.apply("T3", "ok")
    assert res.target_state == "enabled" and "host_clock:cleared" in res.reason


def test_leaving_the_anchor_regime_restores_the_rule(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="hf_timestd.core.chrony_refclock_gate")
    regime = {"v": "anchor"}
    runner = _Runner()
    g = _gate(lambda: regime["v"], runner=runner)
    assert g.apply("T3", "suspect").target_state == "enabled"
    regime["v"] = "fusion_d_clock"
    assert g.apply("T3", "suspect").target_state == "disabled"
    assert g.host_clock_withdrawn is True
    assert any("left anchor-direct" in r.getMessage() for r in caplog.records)


def test_withdraw_on_host_clock_false_bypasses_everything():
    runner = _Runner()
    g = _gate("anchor", runner=runner, withdraw_on_host_clock=False)
    assert g.apply("T3", "fault").target_state == "enabled"
    assert g.host_clock_withdrawn is False


# ── the regime really does come from fusion_status.json ──────────────


def test_the_gate_reads_the_regime_the_writer_publishes(tmp_path, monkeypatch):
    from hf_timestd.core import fusion_status_writer as fsw
    from hf_timestd.core.offset_judge import LabelPlaneAnchorSample

    path = tmp_path / "fusion_status.json"
    monkeypatch.setattr(fsw, "DEFAULT_STATUS_PATH", path)
    w = FusionStatusWriter(path, 8.0)

    w.update(None, chrony_fed=False, skip_reasons=[])
    assert fsw.read_feed_regime(path) == "fusion_d_clock"
    runner = _Runner()
    g = ChronyRefclockGate(
        runner=runner, feed_regime_fn=lambda: fsw.read_feed_regime(path)
    )
    assert g.apply("T3", "suspect").target_state == "disabled"

    w.update(
        None,
        chrony_fed=True,
        skip_reasons=[],
        anchor_sample=LabelPlaneAnchorSample(
            bench="hf_acquired",
            tier="T3",
            reference_time=1_800_000_000.0,
            system_time=1_800_000_000.150,
            sigma_ns=1e6,
            age_s=2.0,
            anchor_mono=998.0,
        ),
    )
    assert fsw.read_feed_regime(path) == "anchor"
    assert g.apply("T3", "suspect").target_state == "enabled"
    assert runner.flags == ["+noselect", "-noselect"]


def test_an_unreadable_status_file_reads_as_no_regime(tmp_path):
    from hf_timestd.core.fusion_status_writer import read_feed_regime

    assert read_feed_regime(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert read_feed_regime(bad) is None
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"schema": "v1", "chrony_gate": {"last_fed": True}}))
    assert read_feed_regime(old) is None
    wrong = tmp_path / "wrong.json"
    wrong.write_text(
        json.dumps({"schema": "v99", "chrony_gate": {"feed_regime": "anchor"}})
    )
    assert read_feed_regime(wrong) is None


def test_a_raising_regime_reader_never_breaks_the_gate():
    def boom():
        raise RuntimeError("nope")

    runner = _Runner()
    g = ChronyRefclockGate(runner=runner, feed_regime_fn=boom)
    # unreadable regime == legacy behaviour
    assert g.apply("T3", "suspect").target_state == "disabled"
