from hf_timestd.core.authority_manager import registration_block
from hf_timestd.core.registration_acquirer import Registration
from hf_timestd.core.registration_store import RegistrationStore


def test_block_from_acquired_summary(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_summary(
        Registration("ep-1", 1000, 100.0, 24000, 0.7, channel="fused"),
        ["SHARED_10000", "WWV_20000"],
        "ACQUIRED",
        {"raw_pair_residual_ms": 16.7},
    )
    b = registration_block(st)
    assert b == {
        "source": "hf_acquired",
        "state": "ACQUIRED",
        "sigma_ms": 0.7,
        "counter_epoch_id": "ep-1",
        "raw_pair_residual_ms": 16.7,
        "contributing": ["SHARED_10000", "WWV_20000"],
        "stations": [],
    }


def test_block_without_summary_is_label(tmp_path):
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    assert registration_block(st) == {
        "source": "label",
        "state": "UNKNOWN",
        "sigma_ms": None,
        "counter_epoch_id": None,
        "raw_pair_residual_ms": None,
        "contributing": [],
        "stations": [],
    }


def test_block_witness_state_carries_t6_residual(tmp_path):
    """WITNESS: the plane in force is T6's -- the acquired plane only
    witnesses it, so source stays "label" but the state and the residual
    against T6 surface for provenance (controller ruling, task 10)."""
    st = RegistrationStore(tmp_path / "reg", tmp_path / "registration.json")
    st.write_summary(
        Registration("ep-1", 1000, 100.0, 24000, 0.7, channel="fused"),
        ["SHARED_10000", "WWV_20000"],
        "WITNESS",
        {"witness_of": "T6", "residual_vs_t6_ms": 2.4},
    )
    b = registration_block(st)
    assert b == {
        "source": "label",
        "state": "WITNESS",
        "sigma_ms": 0.7,
        "counter_epoch_id": "ep-1",
        "raw_pair_residual_ms": None,
        "contributing": ["SHARED_10000", "WWV_20000"],
        "stations": [],
        "residual_vs_t6_ms": 2.4,
    }
