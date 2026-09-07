from hf_timestd.core.offset_judge import HfAcquiredBench
from hf_timestd.core.registration_acquirer import Registration
from hf_timestd.core.registration_store import RegistrationStore

SR = 24000


def _store(tmp_path, clock):
    return RegistrationStore(
        tmp_path / "reg", tmp_path / "registration.json", time_fn=lambda: clock[0]
    )


def test_bench_projects_the_registration_to_the_arrival(tmp_path):
    clock = [5000.0]
    st = _store(tmp_path, clock)
    st.write_summary(
        Registration(
            "ep-1",
            rtp_ref=1000,
            utc_ref=100.0,
            sample_rate=SR,
            sigma_ms=0.8,
            channel="fused",
        ),
        ["SHARED_10000"],
        "ACQUIRED",
        {"raw_pair_residual_ms": 16.7},
    )
    bench = HfAcquiredBench(
        provider=lambda: (1000 + 10 * SR, 42.0),
        store=st,
        mono_fn=lambda: 42.5,
        time_fn=lambda: clock[0],
    )
    r = bench.poll()
    assert r is not None
    assert r.utc == 110.0 and r.mono == 42.0
    assert r.sigma_ns == 0.8e6 and r.tier == "T3"
    assert (
        r.detail["bench"] == "hf_acquired" and r.detail["raw_pair_residual_ms"] == 16.7
    )


def test_bench_answers_on_witness_state_too(tmp_path):
    """A T6 station publishes WITNESS: the acquired plane exists but does
    not drive metrology.  The bench still answers so the judge gets the
    hf_acquired-vs-T6 residual (controller ruling, task 9)."""
    clock = [5000.0]
    st = _store(tmp_path, clock)
    st.write_summary(
        Registration(
            "ep-1",
            rtp_ref=1000,
            utc_ref=100.0,
            sample_rate=SR,
            sigma_ms=0.8,
            channel="fused",
        ),
        ["SHARED_10000"],
        "WITNESS",
        {"raw_pair_residual_ms": 4.2},
    )
    bench = HfAcquiredBench(
        provider=lambda: (1000 + 10 * SR, 42.0),
        store=st,
        mono_fn=lambda: 42.5,
        time_fn=lambda: clock[0],
    )
    r = bench.poll()
    assert r is not None
    assert r.utc == 110.0 and r.mono == 42.0
    assert r.sigma_ns == 0.8e6 and r.tier == "T3"
    assert (
        r.detail["bench"] == "hf_acquired" and r.detail["raw_pair_residual_ms"] == 4.2
    )


def test_bench_silent_in_bootstrap_or_when_stale(tmp_path):
    clock = [5000.0]
    st = _store(tmp_path, clock)
    st.write_summary(None, [], "BOOTSTRAP", {})
    bench = HfAcquiredBench(
        provider=lambda: (1, 1.0),
        store=st,
        mono_fn=lambda: 1.0,
        time_fn=lambda: clock[0],
    )
    assert bench.poll() is None
    st.write_summary(
        Registration("ep-1", 1000, 100.0, SR, 0.8, channel="fused"),
        ["x"],
        "ACQUIRED",
        {},
    )
    clock[0] += 200.0
    assert bench.poll() is None
    assert HfAcquiredBench(provider=lambda: None, store=st).poll() is None
