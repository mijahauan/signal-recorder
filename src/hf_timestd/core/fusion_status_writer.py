"""
FusionStatusWriter — publishes /run/hf-timestd/fusion_status.json.

This file is the authority manager's primary input for probing the T3 level
(multi-station HF Fusion). It reflects the most recent fusion cycle's state
as a small, machine-readable JSON snapshot with stable schema v1.

The consumer contract is documented in METROLOGY.md §4.5. This file is
volatile state (tmpfs, /run) — not an archival product. L3 HDF5 remains
the per-minute archival record.

Schema v1:

    {
      "schema": "v1",
      "utc_published": "2026-04-23T14:32:17.123456Z",
      "cycle_interval_sec": 8.0,
      "fusion": {
        "available": true,
        "d_clock_fused_ms": 0.812,
        "uncertainty_ms": 0.94,
        "n_broadcasts": 24,
        "n_stations": 2,
        "stations_used": ["WWV", "WWVH"],
        "single_station_mode": false,
        "kalman_state": "LOCKED",
        "quality_grade": "A",
        "consistency_flag": "OK",
        "calibration_applied": true
      },
      "chrony_gate": {
        "last_fed": true,
        "skip_reasons": [],
        "feed_regime": "anchor",
        "anchor_bench": "hf_acquired",
        "anchor_tier": "T3",
        "anchor_offset_ms": -150.0,
        "anchor_age_s": 2.1
      }
    }

When `fusion.available` is false, the `fusion` object carries only
`available` and `reason`. The authority manager treats this as "T3
unavailable" regardless of why.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from hf_timestd.core.multi_broadcast_fusion import FusedResult
    from hf_timestd.core.offset_judge import LabelPlaneAnchorSample

log = logging.getLogger(__name__)

SCHEMA_VERSION = "v1"


class FusionStatusWriter:
    """Writes fusion_status.json atomically every fusion cycle."""

    def __init__(self, path: Path, cycle_interval_sec: float):
        self.path = Path(path)
        self.cycle_interval_sec = float(cycle_interval_sec)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def update(
        self,
        result: Optional["FusedResult"],
        chrony_fed: bool,
        skip_reasons: List[str],
        anchor_sample: Optional["LabelPlaneAnchorSample"] = None,
    ) -> None:
        """Write the current cycle's fusion status.

        `result` may be None when no fusion output exists for this cycle
        (e.g., empty lookback window). Consumers then see
        fusion.available=false but still get a fresh utc_published — proof
        that the service itself is alive.

        `anchor_sample` names the label-plane anchor that fed chrony this
        cycle (spec §11.2, 2026-09-07), or None for the legacy
        d_clock feed.  Its presence changes `chrony_gate.feed_regime` and
        publishes the anchor's own offset beside `fusion.d_clock_fused_ms`
        — the two answer the same question from different planes, so
        their DIFFERENCE is the ring plane's residual against the
        registration.  Never their sum (see `offset_judge`'s §11.2
        section on double counting).
        """
        utc_now = datetime.now(timezone.utc)

        payload: dict = {
            "schema": SCHEMA_VERSION,
            "utc_published": _iso_z(utc_now),
            "cycle_interval_sec": self.cycle_interval_sec,
        }

        if result is None:
            payload["fusion"] = {
                "available": False,
                "reason": "no fusion result this cycle",
            }
        else:
            stations_used: List[str] = []
            if getattr(result, "wwv_count", 0) > 0:
                stations_used.append("WWV")
            if getattr(result, "wwvh_count", 0) > 0:
                stations_used.append("WWVH")
            if getattr(result, "bpm_count", 0) > 0:
                stations_used.append("BPM")

            payload["fusion"] = {
                "available": True,
                "d_clock_fused_ms": float(result.d_clock_fused_ms),
                "uncertainty_ms": float(result.uncertainty_ms),
                "n_broadcasts": int(result.n_broadcasts),
                "n_stations": int(result.n_stations),
                "stations_used": stations_used,
                "single_station_mode": bool(result.single_station_mode),
                "kalman_state": getattr(result, "kalman_state", None) or "UNKNOWN",
                "quality_grade": result.quality_grade,
                "consistency_flag": result.consistency_flag,
                "calibration_applied": bool(result.calibration_applied),
            }

        payload["chrony_gate"] = {
            "last_fed": bool(chrony_fed),
            "skip_reasons": list(skip_reasons),
            # "anchor": the sample handed to chrony came from the
            # label-plane anchor (T3 registration or T6 native anchor).
            # "fusion_d_clock": the legacy host-relative sample.
            "feed_regime": "anchor" if anchor_sample is not None
            else "fusion_d_clock",
            "anchor_bench": (
                anchor_sample.bench if anchor_sample is not None else None
            ),
            "anchor_tier": (
                anchor_sample.tier if anchor_sample is not None else None
            ),
            # The host clock's error against the tick-aligned UTC, as the
            # anchor states it.  Compare against fusion.d_clock_fused_ms;
            # never add the two.
            "anchor_offset_ms": (
                round(anchor_sample.offset_s * 1e3, 4)
                if anchor_sample is not None else None
            ),
            "anchor_age_s": (
                round(anchor_sample.age_s, 3)
                if anchor_sample is not None else None
            ),
        }

        self._atomic_write(payload)

    def _atomic_write(self, payload: dict) -> None:
        """Write JSON via temp-in-same-dir + os.replace so consumers never
        observe a partial state.
        """
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=str(self.path.parent),
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(payload, tmp, separators=(",", ":"))
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name
            os.replace(tmp_path, self.path)
        except OSError as e:
            log.warning("FusionStatusWriter: failed to write %s: %s", self.path, e)


def _iso_z(dt: datetime) -> str:
    """ISO 8601 with microseconds and explicit Z suffix."""
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
