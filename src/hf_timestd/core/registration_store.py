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
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .counter_epoch_tracker import COUNTER_EPOCH_STEP_S
from .registration_acquirer import ORIGIN_SIGMA_FLOOR_MS, Registration

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("/run/hf-timestd/registration")
DEFAULT_SUMMARY = Path("/run/hf-timestd/registration.json")
FUSE_OUTLIER_MS = 3.0
DEFAULT_STALE_S = 300.0

# The one summary state that means "acquired AND verified".
AUTHORITATIVE_STATE = "ACQUIRED"

# Corroborated minutes a plane must show before any surface acts on it
# (task 16b).  Live on AC0G-ND, 2026-09-07 20:36Z: the shared channels
# fit a WWV artefact 34 ms away as BPM, called the pair unambiguous,
# verified it against its own ticks and anchored the ring, authority.json
# §18, the sidecar and the FUSE chrony feed on it inside ONE minute
# (n_minutes 0) -- FUSE then reported the host 23-28 ms fast against an
# NTP consensus of 5-13 ms until corroboration reset the plane at 20:42.
# Verification asks "do the ticks land where this plane says?" in a
# single minute; corroboration asks it again, and again, against fresh
# ensembles.  Two minutes of it cost two minutes of the pre-registration
# fallback and buy the station a plane that has survived independent
# evidence.
ADOPT_MIN_CORROBORATED_MINUTES = 2


def registration_refusal(
    summary: Optional[dict],
    *,
    now: float,
    stale_s: float = DEFAULT_STALE_S,
    sample_rate: Optional[int] = None,
) -> Optional[str]:
    """``None`` when this summary is the station's AUTHORITATIVE plane,
    else the name of the gate that refuses it.

    THE one gate (fix round 1, review finding C-1).  Every surface that
    lets the registration place UTC asks this function and nothing else:
    the ring anchor, authority.json §18, the archive sidecar (all three
    via :class:`~hf_timestd.core.t3_registration_anchor.T3RegistrationAnchor`)
    and the FUSE chrony feed (via ``HfAcquiredBench``, whose reading
    populates ``label_plane_anchor``).

    Before this existed the FUSE feed ran a looser gate of its own --
    ACQUIRED **or** WITNESS, and it never read ``verified`` -- so an
    unverified plane that the other three surfaces refused was still
    steering the host clock, and on a T6 station a stood-down WITNESS
    plane could speak to chrony while T6 held the metrology.  A plane
    good enough to discipline the clock is a plane good enough to label
    the samples; there is no honest reading on which those differ.

    The gates, in refusal order:

    ``no_summary``
        Nothing published.
    ``state:<S>``
        Not ACQUIRED.  CANDIDATE is the acquired-but-unverified plane;
        WITNESS means a T6 station publishes the plane without it driving
        metrology; BOOTSTRAP/CONFLICT speak for themselves.
    ``incomplete``
        A field the arithmetic needs is missing or unparseable.
    ``unverified``
        The fused plane does not claim its own verification.  Fail-closed
        on an absent flag: an older metrology process wrote the
        untruthful ``false`` (task 14c), and one revalidation tick of
        legacy behaviour beats anchoring on a fold-lattice phantom.
    ``uncorroborated``
        Verified once, but not yet corroborated for
        ``ADOPT_MIN_CORROBORATED_MINUTES`` minutes (task 16b).  A plane
        verifies against the same minute of audio that acquired it; the
        adoption hysteresis makes it survive independent evidence first.
        Fail-closed on an absent field, as ``unverified`` does.
    ``stale``
        ``read_summary`` returns the last file it finds however old, so a
        dead metrology process would otherwise anchor the station
        forever.
    ``sample_rate_mismatch``
        ``rtp_ref`` is stamped in ONE counter domain; relating one domain
        to another needs a measured epoch offset nobody has here
        (``cross_channel_rtp.py``).  Only checked when the caller names a
        domain.
    """
    if not summary:
        return "no_summary"
    if str(summary.get("state")) != AUTHORITATIVE_STATE:
        return f"state:{summary.get('state')}"
    try:
        int(summary["rtp_ref"])
        float(summary["utc_ref"])
        reg_rate = int(summary["sample_rate"])
        float(summary["sigma_ms"])
        written_at = float(summary.get("written_at", 0.0))
        n_minutes = int(summary.get("n_minutes") or 0)
    except (KeyError, TypeError, ValueError):
        return "incomplete"
    if summary.get("verified") is not True:
        return "unverified"
    if n_minutes < ADOPT_MIN_CORROBORATED_MINUTES:
        return "uncorroborated"
    if (float(now) - written_at) > float(stale_s):
        return "stale"
    if sample_rate is not None and reg_rate != int(sample_rate):
        return "sample_rate_mismatch"
    return None


def registration_is_authoritative(
    summary: Optional[dict],
    *,
    now: float,
    stale_s: float = DEFAULT_STALE_S,
    sample_rate: Optional[int] = None,
) -> bool:
    """Is this summary the station's authoritative plane?  See
    :func:`registration_refusal` for the gates and why there is one."""
    return (
        registration_refusal(summary, now=now, stale_s=stale_s, sample_rate=sample_rate)
        is None
    )


def _same_counter_space(regs: List[Registration]) -> List[Registration]:
    """The registrations that share one physical counter epoch.

    Grouped by the MEASURED epoch offset, not by ``counter_epoch_id``
    (final review, C1).  One metrology process per channel means each
    channel runs its own ``CounterEpochTracker``, sampling the ring's
    anchor at its own phase, so two channels in one epoch routinely carry
    two different id strings -- and the old majority-string filter then saw
    every count tied at 1, took whichever key ``max`` reached first, and
    discarded every other channel.  Inverse-variance combination across
    channels (spec §4.6) silently became "pick one channel", and the
    ``FUSE_OUTLIER_MS`` median test that exists to reject a wrong sibling
    plane never saw a second plane to compare against.

    Every channel on one radiod observes the same pair stream, so their
    offsets agree to the pair skew (1.937 ms measured across ND's six
    24 kHz channels, ``cross_channel_rtp.py``).  Cluster within
    ``COUNTER_EPOCH_STEP_S``; the largest cluster wins, and a tie goes to
    the cluster holding the tightest plane rather than to insertion order.

    Falls back to the id string only when some offset is unknown (NaN) --
    a file written before this field existed, or by a tracker that never
    saw a valid pair.
    """
    offsets = [float(getattr(r, "epoch_offset_s", float("nan"))) for r in regs]
    if not all(math.isfinite(o) for o in offsets):
        epochs: Dict[str, int] = {}
        for r in regs:
            epochs[r.counter_epoch_id] = epochs.get(r.counter_epoch_id, 0) + 1
        epoch = max(epochs, key=lambda k: epochs[k])
        return [r for r in regs if r.counter_epoch_id == epoch]
    best: List[Registration] = []
    best_sigma = float("inf")
    for centre in offsets:
        members = [
            r for r, o in zip(regs, offsets) if abs(o - centre) <= COUNTER_EPOCH_STEP_S
        ]
        sigma = min(r.sigma_ms for r in members)
        if len(members) > len(best) or (
            len(members) == len(best) and sigma < best_sigma
        ):
            best, best_sigma = members, sigma
    return best


def fuse_registrations_with_members(
    regs: List[Registration], at_rtp: int
) -> Tuple[Optional[Registration], List[str]]:
    """``(fused, channels_kept)``.

    The second element is what fusion ACTUALLY kept -- the channels inside
    the winning counter-space cluster that also survived the outlier test.
    ``metrology_service`` publishes it as the summary's ``contributing``,
    which previously named every sibling read from disk and so claimed
    corroboration the station had not performed (final review, C1).
    """
    if not regs:
        return None, []
    same = _same_counter_space(regs)
    if not same:
        return None, []
    utc = np.array([r.sample0_utc_for(at_rtp) for r in same])
    med = np.median(utc)
    keep = [
        (r, u) for r, u in zip(same, utc) if abs(u - med) * 1000.0 <= FUSE_OUTLIER_MS
    ]
    if not keep:
        return None, []
    w = np.array(
        [1.0 / max(r.sigma_ms, ORIGIN_SIGMA_FLOOR_MS * 0.1) ** 2 for r, _ in keep]
    )
    u = np.array([u for _, u in keep])
    fused_utc = float(np.sum(w * u) / np.sum(w))
    offsets = [float(getattr(r, "epoch_offset_s", float("nan"))) for r, _ in keep]
    finite = [o for o in offsets if math.isfinite(o)]
    fused = Registration(
        counter_epoch_id=keep[0][0].counter_epoch_id,
        rtp_ref=int(at_rtp),
        utc_ref=fused_utc,
        sample_rate=keep[0][0].sample_rate,
        sigma_ms=float(1.0 / np.sqrt(np.sum(w))),
        # task 16b: the WEAKEST member's corroboration, as ``verified``
        # below already takes the weakest provenance.  ``max`` let one
        # channel's long history vouch for a sibling that had corroborated
        # nothing, which is precisely what the adoption gate refuses.
        n_minutes=min(r.n_minutes for r, _ in keep),
        channel="fused",
        hypotheses_open=sum(r.hypotheses_open for r, _ in keep),
        stations=tuple(sorted({st for r, _ in keep for st in r.stations})),
        # task-14c: the fused plane is verified exactly when EVERY member
        # it kept is verified.  This field used to be left at its
        # ``False`` default, which made ``verified`` false in every station
        # summary ever written -- so a reader that believed the field
        # could never see a verified registration, and the whole verified
        # predicate had to be inferred from the summary STATE instead
        # (metrology_service publishes ACQUIRED only when a verified plane
        # contributed).  ``all`` and not ``any``: a fused plane inherits
        # the weakest provenance among its members, because an unverified
        # member's origin could be a fold-lattice phantom and
        # inverse-variance combination cannot detect that.
        verified=all(bool(r.verified) for r, _ in keep),
        # the cluster's own offset: its members agree to the pair skew, so
        # the minimum (the least-late pair anyone saw) is the truest
        epoch_offset_s=min(finite) if finite else float("nan"),
    )
    return fused, [r.channel for r, _ in keep]


def fuse_registrations(regs: List[Registration], at_rtp: int) -> Optional[Registration]:
    """The fused plane alone -- see :func:`fuse_registrations_with_members`
    for the channels it kept."""
    return fuse_registrations_with_members(regs, at_rtp)[0]


class RegistrationStore:
    def __init__(
        self,
        directory: Path = DEFAULT_DIR,
        summary_path: Path = DEFAULT_SUMMARY,
        stale_s: float = DEFAULT_STALE_S,
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
                "verified": None,
                "epoch_offset_s": None,
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
            # task-11b fix round 1 (M5): round-trip verified so a future
            # direct adopt(sibling) doesn't silently reconstruct a
            # permanently-unverified plane from a file that was, in fact,
            # verified when written.
            "verified": bool(reg.verified),
            # C1: the epoch as a measured offset, so another PROCESS can
            # tell "same counter space" from "same id string".  strict
            # JSON again: NaN (no valid pair seen) -> null.
            "epoch_offset_s": (
                float(reg.epoch_offset_s) if math.isfinite(reg.epoch_offset_s) else None
            ),
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
                        # M5: default False when absent (older files, or a
                        # schema-incomplete write) rather than raising.
                        verified=bool(d.get("verified", False)),
                        epoch_offset_s=(
                            float(d["epoch_offset_s"])
                            if d.get("epoch_offset_s") is not None
                            else float("nan")
                        ),
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
