"""RegistrationStore — the acquired registration crosses processes.

Metrology runs one process per channel (timestd-metrology@<channel>).
Every channel on one radiod shares one ADC and one RTP counter, so they
share one origin (spec §4.6).  Each process writes its own estimate to
<dir>/<channel>.json and reads its siblings; ``fuse_registrations``
gives every reader the same answer.  The last writer also refreshes the
station summary /run/hf-timestd/registration.json (spec §7), which the
Offset Judge's HfAcquiredBench and the provenance sidecar read.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from .registration_acquirer import ORIGIN_SIGMA_FLOOR_MS, Registration

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("/run/hf-timestd/registration")
DEFAULT_SUMMARY = Path("/run/hf-timestd/registration.json")
FUSE_OUTLIER_MS = 3.0


def fuse_registrations(regs: List[Registration], at_rtp: int) -> Optional[Registration]:
    if not regs:
        return None
    epochs: Dict[str, int] = {}
    for r in regs:
        epochs[r.counter_epoch_id] = epochs.get(r.counter_epoch_id, 0) + 1
    epoch = max(epochs, key=epochs.get)
    same = [r for r in regs if r.counter_epoch_id == epoch]
    utc = np.array([r.sample0_utc_for(at_rtp) for r in same])
    med = np.median(utc)
    keep = [
        (r, u) for r, u in zip(same, utc) if abs(u - med) * 1000.0 <= FUSE_OUTLIER_MS
    ]
    if not keep:
        return None
    w = np.array(
        [1.0 / max(r.sigma_ms, ORIGIN_SIGMA_FLOOR_MS * 0.1) ** 2 for r, _ in keep]
    )
    u = np.array([u for _, u in keep])
    fused_utc = float(np.sum(w * u) / np.sum(w))
    return Registration(
        counter_epoch_id=epoch,
        rtp_ref=int(at_rtp),
        utc_ref=fused_utc,
        sample_rate=keep[0][0].sample_rate,
        sigma_ms=float(1.0 / np.sqrt(np.sum(w))),
        n_minutes=max(r.n_minutes for r, _ in keep),
        channel="fused",
        hypotheses_open=sum(r.hypotheses_open for r, _ in keep),
        stations=tuple(sorted({st for r, _ in keep for st in r.stations})),
    )


class RegistrationStore:
    def __init__(
        self,
        directory: Path = DEFAULT_DIR,
        summary_path: Path = DEFAULT_SUMMARY,
        stale_s: float = 300.0,
        time_fn: Callable[[], float] = time.time,
    ):
        self.directory = Path(directory)
        self.summary_path = Path(summary_path)
        self.stale_s = float(stale_s)
        self._time = time_fn
        self.write_failures = 0

    # ── writing ────────────────────────────────────────────────────
    def _atomic_write(self, path: Path, payload: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(payload, tmp, separators=(",", ":"))
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name
            os.replace(tmp_path, path)
        except OSError as e:
            self.write_failures += 1
            if self.write_failures == 1 or self.write_failures % 60 == 0:
                logger.error(f"registration write failed for {path}: {e}")
            else:
                logger.warning(f"registration write failed for {path}: {e}")

    @staticmethod
    def _payload(reg: Optional[Registration]) -> dict:
        if reg is None:
            return {
                "counter_epoch_id": None,
                "rtp_ref": None,
                "utc_ref": None,
                "sample_rate": None,
                "sigma_ms": None,
                "method": None,
                "n_minutes": 0,
                "hypotheses_open": 0,
            }
        # strict JSON: a BOOTSTRAP channel file carries sigma inf -> null
        sigma = float(reg.sigma_ms) if math.isfinite(reg.sigma_ms) else None
        return {
            "counter_epoch_id": reg.counter_epoch_id,
            "rtp_ref": int(reg.rtp_ref),
            "utc_ref": float(reg.utc_ref),
            "sample_rate": int(reg.sample_rate),
            "sigma_ms": sigma,
            "method": reg.method,
            "n_minutes": int(reg.n_minutes),
            "hypotheses_open": int(reg.hypotheses_open),
            "stations": list(reg.stations),
        }

    def write_channel(self, reg: Registration, state: str, extra: dict) -> None:
        payload = {
            "channel": reg.channel,
            "state": state,
            "written_at": self._time(),
            **self._payload(reg),
            **extra,
        }
        self._atomic_write(self.directory / f"{reg.channel}.json", payload)

    def write_summary(
        self,
        fused: Optional[Registration],
        contributing: List[str],
        state: str,
        extra: dict,
    ) -> None:
        payload = {
            "state": state,
            "contributing": list(contributing),
            "written_at": self._time(),
            **self._payload(fused),
            **extra,
        }
        self._atomic_write(self.summary_path, payload)

    # ── reading ────────────────────────────────────────────────────
    def read_siblings(self, exclude_channel: str = "") -> List[Registration]:
        out: List[Registration] = []
        if not self.directory.is_dir():
            return out
        now = self._time()
        for p in sorted(self.directory.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if d.get("channel") == exclude_channel or d.get("utc_ref") is None:
                continue
            if d.get("sigma_ms") is None:
                continue
            if now - float(d.get("written_at", 0)) > self.stale_s:
                continue
            if d.get("state") != "ACQUIRED":
                continue
            if d.get("method") == "adopted":
                # A purely derived plane (this channel echoing a sibling
                # fusion back under its own name) is not new evidence;
                # letting it re-enter fusion understates sigma by
                # sqrt(n_adopters+1) (review C1).
                continue
            try:
                out.append(
                    Registration(
                        counter_epoch_id=str(d["counter_epoch_id"]),
                        rtp_ref=int(d["rtp_ref"]),
                        utc_ref=float(d["utc_ref"]),
                        sample_rate=int(d["sample_rate"]),
                        sigma_ms=float(d["sigma_ms"]),
                        method=str(d.get("method") or "fold+template"),
                        n_minutes=int(d.get("n_minutes", 0)),
                        channel=str(d["channel"]),
                        hypotheses_open=int(d.get("hypotheses_open", 0)),
                        stations=tuple(d.get("stations", [])),
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.debug(f"registration file {p} unreadable; skipped")
                continue
        return out

    def read_summary(self) -> Optional[dict]:
        try:
            return json.loads(self.summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def summary_age_s(self, summary: dict) -> float:
        """Seconds since ``summary`` (as returned by :meth:`read_summary`)
        was written, per this store's own clock. A caller compares this
        against ``self.stale_s`` to tell a live summary from one whose
        writer died — ``read_summary`` returns the last file it finds
        exactly as written, however old (review F1/F2, task 10)."""
        return self._time() - float(summary.get("written_at", 0))
