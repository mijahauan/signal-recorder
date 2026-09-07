"""The verified registration IS the T3 anchor (spec §11, 2026-09-07).

Live on AC0G-ND, 2026-09-07: six channels acquired and verified a
registration from the received WWV/WWVH tick train, corroborated it
against the 800 ms minute marker every minute, and held it to a
millisecond — while the host clock walked 150 ms away from four NTP
witnesses and the psk decodes died.  The ticks were right and nothing
carried them to the anchor the clients read.

Michael's ruling on the shape of the fix (2026-09-07):

    "Why do we compare things to the host clock?  It is not the ruler or
    the standard but a product of FUSION.  Imagine there is no host clock
    at all, but ONLY FUSION."

So this module does NOT express the anchor as "radiod's host-stamped
(GPS_TIME, RTP_TIMESNAP) pair plus a judge offset".  It expresses the
registration the way T6 already expresses its own anchor — as a
:class:`~hf_timestd.core.native_anchor.NativeAnchor`, a captured
(RTP, UTC) pairing from which every label is pure counter arithmetic:

    utc_ns(rtp) = anchor_utc_ns + (rtp − anchor_rtp) × 10⁹ / sample_rate_hz

``chain_delay_ns`` is 0 because the registration is already a plane, not
an edge: ``utc_ref`` is the UTC of the sample at ``rtp_ref``, with the
propagation model (``expected_delay − fold_position``) already removed by
the acquirer.  There is no second RF term to subtract.

The gates below are all liveness and provenance — never a comparison
against the host clock:

* a T6 native anchor that is AUTHORITATIVE owns the plane, and one
  station publishes ONE registration (mjh, 2026-09-04), so T3 stands
  down while T6 stands up;
* the SUMMARY state must be ACQUIRED.  See ``_verified_state`` for why
  that string, and not the summary's own ``verified`` field, is the
  verified predicate the amendment asks for;
* the summary must be fresh against the store's own stale window —
  ``read_summary`` hands back the last file it finds however old, so a
  dead metrology process otherwise anchors the station forever;
* the registration's ``sample_rate`` must match the channel being
  anchored.  ``rtp_ref`` is stamped in ONE counter domain and
  ``cross_channel_rtp.py`` documents that relating one domain to another
  needs a measured epoch offset nobody has here.  Silence beats a wrong
  plane.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .native_anchor import NativeAnchor

logger = logging.getLogger(__name__)

# The summary state that means "acquired AND verified".
VERIFIED_STATE = "ACQUIRED"


@dataclass(frozen=True)
class T3AnchorDecision:
    """One evaluation of the registration as an anchor.

    ``reason`` names the outcome for the log and for status publication:
    ``acquired`` when the anchor stands, otherwise which gate refused it.
    """

    anchor: Optional[NativeAnchor]
    epoch_id: Optional[str]
    reason: str

    @property
    def in_force(self) -> bool:
        return self.anchor is not None


def _verified_state(summary: dict) -> bool:
    """Is this summary's plane acquired AND verified?

    The amendment asks for "state ACQUIRED with verified=true".  The
    summary's own ``verified`` field cannot carry that: the FUSED
    Registration is built by ``fuse_registrations_with_members``
    (registration_store.py:107) without carrying ``verified`` over from
    its members, so ``RegistrationStore._payload`` writes ``false`` into
    every station summary ever produced.

    The verified predicate lives in the STATE instead.  ``metrology_
    service._publish_registration`` (metrology_service.py:988-996)
    publishes summary state ACQUIRED only when a plane that is itself
    verified contributed, and CANDIDATE when the sole contributor is this
    channel's own not-yet-verified plane.  So ACQUIRED **in the summary**
    is exactly "acquired and verified".  A summary that ever grows a
    truthful ``verified`` field will satisfy this predicate too, since
    ACQUIRED is a precondition of it; nothing here needs changing then.
    """
    return str(summary.get("state")) == VERIFIED_STATE


class T3RegistrationAnchor:
    """Holds the station's T3 label-plane anchor, re-derived on demand.

    Cheap to call: one ``read_summary`` (a tmpfs JSON read) per refresh.
    Never raises — a station with no registration simply has no T3
    anchor, which is the pre-amendment behaviour.
    """

    def __init__(self, store=None, time_fn: Callable[[], float] = time.time):
        if store is None:
            from .registration_store import RegistrationStore

            store = RegistrationStore()
        self._store = store
        self._time = time_fn
        self._decision = T3AnchorDecision(None, None, "not_evaluated")

    # ── the current answer ───────────────────────────────────────────

    @property
    def decision(self) -> T3AnchorDecision:
        return self._decision

    @property
    def anchor(self) -> Optional[NativeAnchor]:
        return self._decision.anchor

    def state(self):
        """``(anchor, epoch_id)`` while an anchor is in force, else None.

        This is the provider shape ``StreamRecorderV2`` consumes: the
        epoch id travels with the anchor because a counter-epoch change
        invalidates ``anchor_rtp`` outright, and a plane comparison
        across two epochs is arithmetic on two different counters.
        """
        d = self._decision
        if d.anchor is None:
            return None
        return (d.anchor, d.epoch_id)

    # ── evaluation ──────────────────────────────────────────────────

    def refresh(
        self, *, t6_authoritative: bool, sample_rate: Optional[int] = None
    ) -> T3AnchorDecision:
        """Re-derive the anchor and log any change of regime."""
        decision = self.evaluate(
            sample_rate=sample_rate, t6_authoritative=t6_authoritative
        )
        prev = self._decision
        self._decision = decision
        self._log_transition(prev, decision)
        return decision

    def evaluate(
        self, *, t6_authoritative: bool, sample_rate: Optional[int] = None
    ) -> T3AnchorDecision:
        """Pure evaluation — no state, no logging.

        ``sample_rate`` names a specific counter domain to accept; None
        (the station-wide refresh) accepts the registration's own domain
        and leaves per-channel matching to the consumer, which knows its
        own configured rate (``StreamRecorderV2._label_anchor_state``).
        """
        if t6_authoritative:
            return T3AnchorDecision(None, None, "t6_authoritative")
        try:
            summary = self._store.read_summary()
        except Exception:  # noqa: BLE001 — a dead store is not an anchor
            return T3AnchorDecision(None, None, "read_failed")
        if not summary:
            return T3AnchorDecision(None, None, "no_summary")
        epoch_id = summary.get("counter_epoch_id")
        epoch_id = None if epoch_id is None else str(epoch_id)
        if not _verified_state(summary):
            return T3AnchorDecision(None, epoch_id, f"state:{summary.get('state')}")
        try:
            rtp_ref = int(summary["rtp_ref"])
            utc_ref = float(summary["utc_ref"])
            reg_rate = int(summary["sample_rate"])
            written_at = float(summary.get("written_at", 0.0))
        except (KeyError, TypeError, ValueError):
            return T3AnchorDecision(None, epoch_id, "incomplete")
        age_s = self._time() - written_at
        if age_s > float(getattr(self._store, "stale_s", 300.0)):
            return T3AnchorDecision(None, epoch_id, "stale")
        if sample_rate is not None and reg_rate != int(sample_rate):
            return T3AnchorDecision(None, epoch_id, "sample_rate_mismatch")
        anchor = NativeAnchor(
            anchor_rtp=rtp_ref & 0xFFFFFFFF,
            anchor_utc_ns=int(round(utc_ref * 1e9)),
            sample_rate_hz=reg_rate,
            # The registration is a PLANE, not an edge: utc_ref already
            # names the UTC of the sample at rtp_ref with the propagation
            # model removed.  No analog chain term remains to subtract.
            chain_delay_ns=0,
            # Provenance only (the wrap-epoch disambiguator): when this
            # registration was published, not a claim about the plane.
            captured_at_utc_ns=int(round(written_at * 1e9)),
            captured_via_tier="T3",
        )
        return T3AnchorDecision(anchor, epoch_id, "acquired")

    # ── logging ─────────────────────────────────────────────────────

    def _log_transition(self, prev: T3AnchorDecision, now: T3AnchorDecision) -> None:
        if prev.reason == now.reason and prev.epoch_id == now.epoch_id:
            return
        if now.anchor is not None:
            logger.info(
                "T3 anchor: the verified registration IS the anchor "
                "(rtp_ref=%d, utc_ref=%.6f, %d Hz, epoch=%s)",
                now.anchor.anchor_rtp,
                now.anchor.anchor_utc_ns / 1e9,
                now.anchor.sample_rate_hz,
                now.epoch_id,
            )
        elif prev.anchor is not None:
            logger.warning(
                "T3 anchor: WITHDRAWN (%s) — the ring falls back to "
                "radiod's pair with the judge's correction",
                now.reason,
            )
        else:
            logger.debug("T3 anchor: none (%s)", now.reason)
