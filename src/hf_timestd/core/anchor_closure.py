"""Is the T3 registration anchor closure in force?  (task 17a)

Spec §11 (2026-09-07) closed the loop between the acquired registration
and the surfaces that place UTC: the ring, authority.json §18, the
archive sidecar, and the FUSE chrony feed.  It went to AC0G-ND the same
day and the anchor-direct FUSE feed engaged twice -- 20:41Z and 21:21Z.
Both times it reported the host clock SLOW (+23..28 ms, then +60.5 ms)
while four NTP witnesses put the host FAST (+13, +30 ms).  chrony
followed FUSE and slewed the host the wrong way; corroboration then
reset the registration and the anchor withdrew on its own, so each
episode lasted one to two minutes.  Nothing in the station's own frame
noticed, because every surface had been moved onto the same plane at
once -- there was no longer an independent reading to disagree.

Until the closure has passed a live acceptance it is OPT-IN::

    [timing.registration]
    anchor_closure = true

Absent, malformed, or false, the answer is FALSE, and every consumer
behaves exactly as it did at c7b2106 -- the commit before task 13.  The
acquirer still runs, the channel files and the station summary are still
published, and every witness still reads them; what stands down is the
right to place UTC.

One flag, resolved once per process at construction time and handed to
the pieces that need it, rather than each piece reading the file: the
recorder, the metrology processes and the fusion service must never
disagree about the regime, and a per-call file read on the judge's tick
thread and the writer's hot path would be its own defect.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("/etc/hf-timestd/timestd-config.toml")

# ``[timing.registration] anchor_closure``
CONFIG_SECTION = ("timing", "registration")
CLOSURE_KEY = "anchor_closure"

ENABLED_MESSAGE = (
    "registration anchor closure: ENABLED (spec §11 — the verified "
    "registration places UTC on the ring, §18, the sidecar and the "
    "FUSE feed)"
)
DISABLED_MESSAGE = "registration anchor closure: DISABLED (witness only)"

_logged = False


def reset_log_state() -> None:
    """Forget that the regime has been logged (tests only)."""
    global _logged
    _logged = False


def closure_from_config(config: Optional[dict]) -> bool:
    """The flag out of an already-loaded config dict.

    Fails closed on every shape a hand-edited TOML can take: a missing
    section, a scalar where a table belongs, a non-boolean value.  A
    station that meant to enable the closure and mistyped the section
    gets the safe regime and a config that reads as it behaves.
    """
    node: object = config or {}
    for key in CONFIG_SECTION:
        if not isinstance(node, dict):
            return False
        node = node.get(key) or {}
    if not isinstance(node, dict):
        return False
    return node.get(CLOSURE_KEY) is True


def _load(path: Path) -> dict:
    try:
        if not Path(path).exists():
            return {}
        import toml

        return toml.load(str(path)) or {}
    except Exception as exc:  # noqa: BLE001 — an unreadable config is not a regime
        logger.warning(
            "anchor closure: could not read %s (%s) — closure stays off", path, exc
        )
        return {}


def anchor_closure_enabled(
    config: Optional[dict] = None, *, path: Optional[Path] = None
) -> bool:
    """Resolve the flag, announcing the regime once per process.

    Hand in the config dict the process already loaded whenever there is
    one; ``path`` (or its default) is the fallback for a process that
    does not carry the whole TOML.
    """
    if config is None:
        config = _load(path or DEFAULT_CONFIG_PATH)
    enabled = closure_from_config(config)
    global _logged
    if not _logged:
        _logged = True
        logger.info(ENABLED_MESSAGE if enabled else DISABLED_MESSAGE)
    return enabled
