"""
ChronyRefclockGate — toggles the Fusion SHM refclock between enabled
and disabled (via `chronyc selectopts <refid> ±noselect`) based on
the current authority state.

The policy, per METROLOGY.md §4.6: enable the refclock only when the
active T-level is one where Fusion is actually producing a useful
UTC reference — T3 or T6. Any other state (T5/T4/T2/T1 active, or no
level active) disables the refclock so chrony stops offering it as
an upstream source to clients, and stops using it to discipline the
local system clock.

A second rule sits beside the tier rule (2026-09-04, step 0.5 of the
host-clock program; docs/design/HOST_CLOCK_INTEGRITY.md).  The product
FUSE feeds chrony follows the host clock: fusion labels its ticks in the
frame the host clock gave the samples, so when the host clock walks,
FUSE walks with it and reports the walk as "on time".  On 2026-09-04
that let chrony steer AC0G-B4 11.6 s and AC0G-ND 4 s off UTC under a
refclock that measured the clock it steered.  The host-clock verdict
(host_clock_integrity.assess) sees the walk from witnesses that do not
share the frame.  So: while the verdict reads ``suspect`` or ``fault``
the gate withdraws the refclock (+noselect) whatever the tier, and it
re-offers the refclock only after ``ok`` has held for
``host_clock_clear_sec``.  ``unwitnessed`` changes nothing.  The gate
does not step the clock; it removes the source that would have kept
chrony from following the witnesses that can.

That rule assumed a feed that FOLLOWED the host clock, and spec §11.2
(2026-09-07) replaced it.  The anchor-direct FUSE sample carries no host
frame at all: it states the anchor's UTC of an arrival against what the
host clock read at that instant, so it reports the very error the
verdict reports.  Worse, the change makes the pair witness read the FULL
host error instead of ~0 -- the witness compares the host against the
rtp-frame active tier, whose plane moved from "radiod's pair plus a judge
offset" to "the registration".  So the verdict STAYS ``suspect``, and the
old rule would keep ``+noselect`` on the one refclock that could fix it
(review finding C-2, fix round 1).

So the gate reads ``chrony_gate.feed_regime`` from fusion_status.json.
While it reads ``anchor``, a ``suspect`` verdict does NOT withdraw the
refclock -- suspect is the normal state of a clock that needs correcting,
and the refclock IS the correction.  ``fault`` still withdraws: a faulted
verdict says the witnesses disagree with each other, and then no source
in this station's frame should steer anything.  Under the legacy regime,
and when the regime cannot be read at all, behaviour is unchanged.

Task 17a made the closure opt-in, and this rule opt-in with it:
``anchor_closure=False`` (the default) never reads the regime at all and
keeps the legacy withdrawal rule exactly as c7b2106 wrote it.  The
regime is a fact about the OTHER process's last cycle; a
fusion_status.json left behind by an earlier enabled run would otherwise
disarm the legacy rule on a station that never opted in.

This is the runtime-mutable half of the chrony integration. Stratum,
refid, and precision remain static per-install (chrony does not expose
runtime setters for those) and follow the install-time convention
table in §4.6.

Safety properties:

  - Only issues subprocess calls on actual state transitions. Steady
    state adds no system call overhead.
  - All chronyc failures are caught and surfaced in GateResult.reason
    without raising. The authority manager's tick() keeps running.
  - Respects dry_run for first-time deployments and CI.
  - ``sudo=True`` prefixes ``sudo -n``: on a stock Debian install the
    timestd user cannot open chrony's command socket (see __init__).

Measurement-model note (docs/design/MEASUREMENT_MODEL.md §7.1): this
module handles the HOST CLOCK.  Every offset it reads or writes — chrony's
``D_clock``, an SHM ``reference_time - system_time``, a coarse UTC estimate
— describes how far the host clock sits from the station's registration.
That is a derived quantity.  The measurand stays the UTC label of each
sample against the GPSDO ruler; chrony never sees it and never sets it.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    target_state: str   # "enabled" | "disabled"
    applied: bool       # True iff a chronyc call happened this tick
    reason: str = ""


class ChronyRefclockGate:
    # Active T-levels for which the refclock is -noselect. See §4.6.
    ENABLED_T_LEVELS = ("T3", "T6")
    # Host-clock verdicts that withdraw the refclock whatever the tier.
    WITHDRAW_VERDICTS = ("suspect", "fault")
    # ...and the subset that still withdraws under the anchor-direct
    # feed, where "suspect" is the expected reading of a clock being
    # corrected.  A FAULT is the witnesses disagreeing with each other,
    # which no plane can answer (review C-2).
    ANCHOR_DIRECT_WITHDRAW_VERDICTS = ("fault",)
    ANCHOR_REGIME = "anchor"

    def __init__(
        self,
        refid: str = "FUSE",
        chronyc_bin: Optional[str] = None,
        dry_run: bool = False,
        timeout_sec: float = 5.0,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        withdraw_on_host_clock: bool = True,
        host_clock_clear_sec: float = 600.0,
        now_fn: Callable[[], float] = time.monotonic,
        sudo: bool = False,
        feed_regime_fn: Optional[Callable[[], Optional[str]]] = None,
        anchor_closure: bool = False,
    ):
        self.refid = refid
        self.chronyc_bin = chronyc_bin or shutil.which("chronyc") or "chronyc"
        # chrony 4 takes privileged commands (selectopts) only over its Unix
        # command socket.  Debian 13 keeps /run/chrony at 0700 and chronyd
        # makes chronyd.sock owner-only, so membership in _chrony does not
        # reach it.  `sudo=True` runs chronyc through `sudo -n`; the grant is
        # config/sudoers-timestd-chrony-gate (two exact commands, no wildcard).
        self.sudo = bool(sudo)
        self.dry_run = bool(dry_run)
        self.timeout_sec = float(timeout_sec)
        self._run = runner or subprocess.run
        self._last_state: Optional[str] = None  # "enabled"|"disabled" after a successful apply
        self.withdraw_on_host_clock = bool(withdraw_on_host_clock)
        self.host_clock_clear_sec = float(host_clock_clear_sec)
        self._now = now_fn
        # Host-clock withdrawal: latched by suspect/fault, cleared only
        # after `ok` has held for host_clock_clear_sec.
        self._hc_withdrawn: bool = False
        self._hc_ok_since: Optional[float] = None
        self._hc_verdict: Optional[str] = None
        # Which FUSE feed regime is live (spec §11.2).  Injectable for
        # tests; by default read from fusion_status.json, which the
        # fusion process -- the same process that owns this gate -- writes
        # every cycle.
        self._feed_regime_fn = feed_regime_fn or self._default_feed_regime
        self._last_regime: Optional[str] = None
        # Task 17a: the anchor-direct rule exists only for the anchor
        # closure, so it applies only while the closure does.  A
        # fusion_status.json left behind by an earlier enabled run can
        # still read ``anchor``; believing it would leave the legacy
        # withdrawal rule off on a station that never opted in.
        self.anchor_closure = bool(anchor_closure)

    @property
    def host_clock_withdrawn(self) -> bool:
        """True while the host-clock verdict is keeping the refclock withdrawn."""
        return self._hc_withdrawn

    @staticmethod
    def _default_feed_regime() -> Optional[str]:
        """``chrony_gate.feed_regime`` from fusion_status.json, or None."""
        try:
            from .fusion_status_writer import read_feed_regime
            return read_feed_regime()
        except Exception:  # noqa: BLE001 — an unreadable regime is None
            return None

    def _feed_regime(self) -> Optional[str]:
        try:
            return self._feed_regime_fn()
        except Exception as e:  # noqa: BLE001 — never break the gate
            log.debug("feed regime unavailable: %s", e)
            return None

    def _update_host_clock(self, verdict: Optional[str]) -> Optional[str]:
        """Advance the withdrawal latch; return a reason fragment when the
        latch is the deciding factor this tick, else None."""
        if not self.withdraw_on_host_clock or verdict is None:
            return None
        self._hc_verdict = verdict
        regime = self._feed_regime() if self.anchor_closure else None
        if regime == self.ANCHOR_REGIME:
            return self._update_host_clock_anchor_direct(verdict)
        if self._last_regime == self.ANCHOR_REGIME:
            log.info(
                "Chrony refclock gate: FUSE feed left anchor-direct "
                "(regime=%s) — the host-clock withdrawal rule applies "
                "again", regime,
            )
        self._last_regime = regime
        if verdict in self.WITHDRAW_VERDICTS:
            self._hc_withdrawn = True
            self._hc_ok_since = None
            return f"host_clock:{verdict}"
        if verdict == "ok" and self._hc_withdrawn:
            now = self._now()
            if self._hc_ok_since is None:
                self._hc_ok_since = now
            held = now - self._hc_ok_since
            if held >= self.host_clock_clear_sec:
                self._hc_withdrawn = False
                self._hc_ok_since = None
                return "host_clock:cleared"
            return f"host_clock:clearing {self.host_clock_clear_sec - held:.0f}s"
        # "unwitnessed" (or any other value) holds whatever state we have.
        if self._hc_withdrawn:
            return f"host_clock:held ({verdict})"
        return None

    def _update_host_clock_anchor_direct(
        self, verdict: str
    ) -> Optional[str]:
        """The anchor-direct rule (review C-2).

        The sample chrony holds carries no host frame, and the verdict
        reports the error this refclock exists to remove — so ``suspect``
        is the EXPECTED reading of a clock that is being corrected, and
        withdrawing on it would refuse the correction.  A latch inherited
        from the legacy regime is released here for the same reason:
        otherwise a station that switches to anchor-direct while already
        withdrawn would stay withdrawn forever, since ``suspect`` no
        longer starts the 600 s clearing window.

        ``fault`` still withdraws.  A faulted verdict means the witnesses
        disagree with EACH OTHER; no plane in this station's frame can
        answer that, and the honest move is to hand chrony back to its
        NTP sources.
        """
        if verdict in self.ANCHOR_DIRECT_WITHDRAW_VERDICTS:
            self._hc_withdrawn = True
            self._hc_ok_since = None
            self._last_regime = self.ANCHOR_REGIME
            return f"host_clock:{verdict}"
        released = self._hc_withdrawn
        self._hc_withdrawn = False
        self._hc_ok_since = None
        if self._last_regime != self.ANCHOR_REGIME or released:
            log.info(
                "Chrony refclock gate: anchor-direct feed, host %s is "
                "expected while correcting — FUSE stays selectable%s",
                verdict,
                " (released a legacy withdrawal)" if released else "",
            )
        self._last_regime = self.ANCHOR_REGIME
        if verdict in self.WITHDRAW_VERDICTS:
            return (f"host_clock:{verdict} (anchor-direct"
                    + (", released)" if released else ")"))
        if released:
            return "host_clock:released (anchor-direct)"
        return None

    def apply(
        self,
        t_level_active: Optional[str],
        host_clock_verdict: Optional[str] = None,
    ) -> GateResult:
        hc_reason = self._update_host_clock(host_clock_verdict)
        tier_ok = t_level_active in self.ENABLED_T_LEVELS
        target = "enabled" if (tier_ok and not self._hc_withdrawn) else "disabled"
        suffix = f" ({hc_reason})" if hc_reason else ""
        if target == self._last_state:
            return GateResult(target_state=target, applied=False, reason="no change" + suffix)

        flag = "-noselect" if target == "enabled" else "+noselect"

        if self.dry_run:
            self._last_state = target
            return GateResult(target_state=target, applied=False, reason=f"dry_run:{flag}{suffix}")

        try:
            argv = [self.chronyc_bin, "selectopts", self.refid, flag]
            if self.sudo:
                argv = ["sudo", "-n", *argv]
            proc = self._run(
                argv,
                capture_output=True, text=True,
                timeout=self.timeout_sec, check=False,
            )
        except FileNotFoundError:
            missing = "sudo" if self.sudo else "chronyc"
            return GateResult(target_state=target, applied=False, reason=f"{missing} not found")
        except subprocess.TimeoutExpired:
            return GateResult(target_state=target, applied=False, reason="chronyc timeout")
        except OSError as e:
            return GateResult(target_state=target, applied=False, reason=f"exec error: {e}")

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
            return GateResult(
                target_state=target, applied=False,
                reason=f"chronyc exit {proc.returncode}: {stderr[0]}",
            )

        # Successful apply — latch state.
        self._last_state = target
        return GateResult(target_state=target, applied=True, reason=f"applied {flag}{suffix}")
