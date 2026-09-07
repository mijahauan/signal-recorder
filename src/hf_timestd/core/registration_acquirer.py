"""RegistrationAcquirer — the received ticks place the second boundary.

Spec: docs/superpowers/specs/2026-09-06-t3-self-registration-design.md.

The registration ``utc(sample) = sample0_utc + sample/sample_rate`` has a
rate (the GPSDO's, needs no help) and an origin (a measurement).  Before
this module the origin came from radiod's non-atomic (GPS_TIME,
RTP_TIMESNAP) pair, and the ±20 ms tick search around it could not
re-find the second when the pair landed off (232 ms on ND, 701 ms on
B4, 2026-09-06).  Here the tick train itself places the second: fold the
band-limited envelope at one second, find the peaks, fit them to the
expected station delays by a common shift, hold the result in the RTP
frame, and corroborate or correct it every minute.

Sign convention (pinned in the plan's Global Constraints):
    correction_s = expected_delay_s - fold_position_s, wrapped to (-0.5, 0.5]
    sample0_utc_acquired = sample0_utc_label + correction_s
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import butter, sosfiltfilt

from .tick_edge_detector import TickEdgeDetector

logger = logging.getLogger(__name__)

ACQ_MIN_FOLD_SNR_DB = 10.0
FOLD_LENGTHS_S = (60, 120, 180)
TONE_BANDS_HZ: Dict[str, Tuple[float, float]] = {
    "1000": (900.0, 1100.0),  # WWV and BPM ticks
    "1200": (1100.0, 1300.0),  # WWVH ticks
}
BAND_OF_STATION: Dict[str, str] = {"WWV": "1000", "BPM": "1000", "WWVH": "1200"}
# Label seconds-in-minute excluded from the fold: 0 (marker), 29/59 (no
# tick), each widened by ±1 s because the label may be ~0.7 s wrong.
FOLD_SKIP_SECONDS = frozenset({59, 0, 1, 28, 29, 30})
# Fold-peak geometry: a 5 ms tick through a 200 Hz band is a ~10 ms bump.
# PEAK_MIN_SEPARATION_MS is a GUARD BAND, added on each side of a peak's own
# measured half-max width when marking samples taken -- it is not itself the
# two-peak resolving floor.  Two ticks resolve once separated by roughly
# (the weaker tick's half-max width + 2 * PEAK_MIN_SEPARATION_MS), which is
# usually well under PEAK_MAX_WIDTH_MS but scales with the actual bump, not
# with a fixed 25 ms exclusion regardless of width.
PEAK_MIN_SEPARATION_MS = 8.0
PEAK_MAX_WIDTH_MS = 25.0
ENVELOPE_LPF_HZ = 400.0
ORIGIN_SIGMA_FLOOR_MS = 1.0

# Same-site broadcasts (WWV on 2.5-25 MHz, all from Fort Collins) share the
# great-circle path, so their corrections agree far more tightly than those
# derived from different sites (Fort Collins / Kauai / Lintong) -- mjh 2026-09-06.
SAME_SITE_AGREE_MS = 1.5
CROSS_SITE_AGREE_MS = 4.0


@dataclass(frozen=True)
class FoldPeak:
    band: str
    position_s: float  # onset (half-rise) position within the label second
    snr_db: float
    width_ms: float


def _band_envelope(audio: np.ndarray, sample_rate: int, band: str) -> np.ndarray:
    lo, hi = TONE_BANDS_HZ[band]
    sos = butter(4, [lo, hi], btype="bandpass", fs=sample_rate, output="sos")
    x = sosfiltfilt(sos, np.asarray(audio, dtype=np.float64))
    env = np.abs(x)
    sos_lp = butter(2, ENVELOPE_LPF_HZ, btype="lowpass", fs=sample_rate, output="sos")
    return sosfiltfilt(sos_lp, env)


def fold_tick_train(
    audio: np.ndarray,
    sample_rate: int,
    sample0_utc_label: float,
    band: str,
    n_seconds: int,
) -> Tuple[np.ndarray, int]:
    """Average ``n_seconds`` label-seconds of the band envelope into one
    second.  Rows whose label second-in-minute is in FOLD_SKIP_SECONDS
    are left out.  Returns (profile[sample_rate], rows_used)."""
    env = _band_envelope(audio, sample_rate, band)
    first_sec = int(np.ceil(sample0_utc_label))
    i0 = int(round((first_sec - sample0_utc_label) * sample_rate))
    rows = []
    for k in range(n_seconds):
        utc_sec = first_sec + k
        if utc_sec % 60 in FOLD_SKIP_SECONDS:
            continue
        a = i0 + k * sample_rate
        b = a + sample_rate
        if b > len(env):
            break
        rows.append(env[a:b])
    if not rows:
        return np.zeros(sample_rate), 0
    return np.mean(np.stack(rows), axis=0), len(rows)


def find_fold_peaks(
    profile: np.ndarray,
    sample_rate: int,
    band: str,
    min_snr_db: float = ACQ_MIN_FOLD_SNR_DB,
) -> List[FoldPeak]:
    """Peaks above ``min_snr_db`` over a robust baseline.  SNR is
    20·log10(peak_above_baseline / MAD·1.4826).  Position is the half-rise
    sample on the leading edge, which sits on the tick onset; the apex
    would sit ~5 ms late."""
    if profile.size == 0 or not np.any(profile):
        return []
    baseline = np.median(profile)
    dev = profile - baseline
    mad = np.median(np.abs(dev)) * 1.4826
    if mad <= 0:
        return []
    # ACQ_MIN_FOLD_SNR_DB is a FLOOR.  The profile has ~len/30 independent
    # bins after the 400 Hz envelope LPF (24000 -> ~800), and pure noise
    # reaches sqrt(2 ln n_eff) ≈ 3.7σ somewhere among them; one extra σ of
    # margin puts the effective threshold near 13 dB, so noise alone never
    # names a tick.  A real tick folds far above this (a 5 dB tick gains
    # ~17 dB over 54 rows).
    n_eff = max(16.0, len(dev) * 2.0 * ENVELOPE_LPF_HZ / sample_rate)
    noise_extreme = np.sqrt(2.0 * np.log(n_eff)) + 1.0
    thr = mad * max(10 ** (min_snr_db / 20.0), noise_extreme)
    sep = int(PEAK_MIN_SEPARATION_MS * sample_rate / 1000)
    max_w = int(PEAK_MAX_WIDTH_MS * sample_rate / 1000)
    n = len(dev)
    order = np.argsort(dev)[::-1]
    taken = np.zeros_like(dev, dtype=bool)
    peaks: List[FoldPeak] = []
    for idx in order:
        if dev[idx] < thr:
            break
        # exclusion zone wraps circularly: position_s is defined mod 1 s,
        # so a peak near sample 0 and one near sample n-1 can be neighbors.
        if taken[(np.arange(idx - sep, idx + sep + 1)) % n].any():
            continue
        half = dev[idx] / 2.0
        # walk back to the half-rise point (circular within the second)
        j = idx
        steps = 0
        while dev[j % len(dev)] > half and steps < max_w:
            j -= 1
            steps += 1
        onset = (j + 1) % len(dev)
        # width at half max
        k = idx
        steps2 = 0
        while dev[k % len(dev)] > half and steps2 < max_w:
            k += 1
            steps2 += 1
        width_samples = steps + steps2
        width_ms = width_samples * 1000.0 / sample_rate
        if width_ms > PEAK_MAX_WIDTH_MS:
            continue  # a plateau, not a tick
        # Taken zone is the MEASURED bump plus PEAK_MIN_SEPARATION_MS of
        # guard on each side (circular within the second, as the
        # acceptance check above already is) -- not a fixed ±max_w, which
        # would force unrelated ticks apart by ~sep+max_w instead of the
        # intended ~width+2*sep.
        taken[(np.arange(onset - sep, onset + width_samples + sep + 1)) % n] = True
        peaks.append(
            FoldPeak(
                band=band,
                position_s=onset / sample_rate,
                snr_db=float(20 * np.log10(dev[idx] / mad)),
                width_ms=width_ms,
            )
        )
    peaks.sort(key=lambda p: -p.snr_db)
    return peaks


BAND_ARBITRATION_MS = 6.0


def arbitrate_bands(
    peaks_by_band: Dict[str, List[FoldPeak]], agree_ms: float = BAND_ARBITRATION_MS
) -> List[FoldPeak]:
    """Assign each fold position to ONE tone band.  A 5 ms tick has a sinc
    main lobe ~200 Hz wide, so a 1200 Hz tick leaks into 900-1100 Hz and a
    1000 Hz tick into 1100-1300 Hz; no filter separates them.  The band
    whose centre matches the tone responds more strongly, so when two
    bands carry a peak at the same position the weaker one is the leak.
    agree_ms=6.0: a measured WWVH leak's onset sat ~2.75 ms from its true
    1200-band peak (a real, same-tick artifact); distinct stations in
    different bands are >=18 ms apart in the tests here, so 6 ms merges
    the former without any real risk of merging the latter."""
    allp = [p for ps in peaks_by_band.values() for p in ps]
    allp.sort(key=lambda p: -p.snr_db)
    kept: List[FoldPeak] = []
    for p in allp:
        clash = any(
            k.band != p.band
            and abs(((p.position_s - k.position_s) + 0.5) % 1.0 - 0.5) * 1000.0
            <= agree_ms
            for k in kept
        )
        if not clash:
            kept.append(p)
    return kept


@dataclass(frozen=True)
class Hypothesis:
    correction_s: float
    sigma_ms: float
    assignments: tuple  # ((station, band, position_s, snr_db), ...)
    support: int
    unambiguous: bool


def wrap_half_second(x_s: float) -> float:
    """Wrap into (-0.5, 0.5]."""
    y = (x_s + 0.5) % 1.0 - 0.5
    return 0.5 if y == -0.5 else y


def _sigma_ms_from_snr(snr_db: float) -> float:
    # Tick rise through a 200 Hz band ~5 ms; timing sigma ≈ rise / (S/N).
    rise_ms = 5.0
    return max(ORIGIN_SIGMA_FLOOR_MS, rise_ms / (10 ** (snr_db / 20.0)) * 3.0)


def fit_template(
    peaks: List[FoldPeak],
    expected_delays_s: Dict[str, float],
    agree_ms: float = CROSS_SITE_AGREE_MS,
) -> List[Hypothesis]:
    """Fit the peak set to the station delay template by a common shift.

    Every (peak, station) pairing whose tone bands agree proposes a
    correction; pairings whose corrections agree within ``agree_ms`` form
    one hypothesis with support = number of peaks.  A hypothesis is
    unambiguous with support >= 2 or when the peak's band admits exactly
    one eligible station.

    ``agree_ms`` defaults to ``CROSS_SITE_AGREE_MS``: every pairing this
    function forms compares two DIFFERENT stations (WWV vs. BPM, or WWV
    vs. WWVH) sharing one tone band, which is a cross-site comparison by
    definition (task-11 fix round 1, controller ruling 2026-09-07) --
    the earlier literal ``3.0`` was a plan error, not a deliberately
    chosen tolerance, and sat marginally below the jitter a weak (14-18
    dB) secondary station's fold position carries at 180 s of
    integration, intermittently stalling real acquisitions that should
    have resolved."""
    pairings = []
    for p in peaks:
        compatible = [s for s in expected_delays_s if BAND_OF_STATION.get(s) == p.band]
        for s in compatible:
            corr = wrap_half_second(expected_delays_s[s] - p.position_s)
            pairings.append((corr, s, p, len(compatible)))
    if not pairings:
        return []
    pairings.sort(key=lambda x: x[0])
    used = [False] * len(pairings)
    hyps: List[Hypothesis] = []
    for i, (corr_i, _, _, _) in enumerate(pairings):
        if used[i]:
            continue
        group = []
        seen_peaks = set()
        for j, (corr_j, s_j, p_j, n_comp) in enumerate(pairings):
            if used[j] or id(p_j) in seen_peaks:
                continue
            if abs(wrap_half_second(corr_j - corr_i)) * 1000.0 <= agree_ms:
                group.append(j)
                seen_peaks.add(id(p_j))
        for j in group:
            used[j] = True
        members = [pairings[j] for j in group]
        w = np.array([10 ** (m[2].snr_db / 10.0) for m in members])
        corr = float(np.sum(w * np.array([m[0] for m in members])) / np.sum(w))
        sig = float(
            min(_sigma_ms_from_snr(m[2].snr_db) for m in members)
            / np.sqrt(len(members))
        )
        support = len(members)
        unamb = support >= 2 or (support == 1 and members[0][3] == 1)
        hyps.append(
            Hypothesis(
                correction_s=wrap_half_second(corr),
                sigma_ms=max(ORIGIN_SIGMA_FLOOR_MS, sig),
                assignments=tuple(
                    (m[1], m[2].band, m[2].position_s, m[2].snr_db) for m in members
                ),
                support=support,
                unambiguous=unamb,
            )
        )
    hyps.sort(key=lambda h: (-h.support, -sum(a[3] for a in h.assignments)))
    return hyps


MARKER_SEARCH_HALF_S = 1.5
MARKER_LEN_S = 0.800
MARKER_MIN_SNR_DB = 6.0
MARKER_BIN_S = 0.001


def locate_minute_marker(
    audio: np.ndarray,
    sample_rate: int,
    sample0_utc_label: float,
    band: str,
    minute_utc: int,
) -> Optional[Tuple[float, float]]:
    """Find the 800 ms marker near where the label puts second 0 of
    ``minute_utc``.  Decimates the band envelope to MARKER_BIN_S bins over
    the ±MARKER_SEARCH_HALF_S search segment and scores each MARKER_LEN_S
    window by its bin-median (a regular tick occupies too few bins to
    move a median; only a sustained ~800 ms tone lifts one). Returns
    (onset offset from the label's minute_utc in seconds, SNR dB) or
    None."""
    env = _band_envelope(audio, sample_rate, band)
    centre = int(round((minute_utc - sample0_utc_label) * sample_rate))
    half = int(MARKER_SEARCH_HALF_S * sample_rate)
    bin_len = max(1, int(round(sample_rate * MARKER_BIN_S)))
    window_bins = int(round(MARKER_LEN_S / MARKER_BIN_S))
    L = window_bins * bin_len
    a = centre - half
    b = centre + half + L
    if a < 0 or b > len(env):
        return None
    seg = env[a:b]
    # Score is a sliding MEDIAN over the 800 ms window, taken on a 1 ms
    # decimation of the envelope -- not a windowed MEAN over the raw
    # envelope, and not a ratio against the raw envelope's per-sample
    # MAD.  Both of those were tried first and both leak: a regular 5 ms
    # tick recurs every second and can only ever nudge a MEAN over 800
    # 1 ms bins by ~5/800 of its amplitude, but a windowed-mean score's
    # own MAD shrinks just as fast as a per-sample MAD when tick SNR
    # rises, so the ratio between them stays roughly constant instead of
    # closing -- measured on the shipped (now-replaced) version: the
    # marker-absent case read +9.4 dB at 30 dB tick SNR and +19 dB at 40
    # dB, both above the 6 dB gate.  A tick occupies ~5 of 800 one-ms
    # bins in any window; a MEDIAN over that window cannot be moved by
    # so small a minority no matter how strong the tick, so only a
    # genuine ~800 ms tone -- which owns the whole window -- lifts it.
    n_bins = len(seg) // bin_len
    decimated = seg[: n_bins * bin_len].reshape(n_bins, bin_len).mean(axis=1)
    windows = np.lib.stride_tricks.sliding_window_view(decimated, window_bins)
    score = np.median(windows, axis=1)
    k = int(np.argmax(score))
    baseline = np.median(decimated)
    mad = np.median(np.abs(decimated - baseline)) * 1.4826
    if mad <= 0:
        return None
    snr_db = float(20 * np.log10((score[k] - baseline) / mad))
    if snr_db < MARKER_MIN_SNR_DB:
        return None
    # refine to the half-rise onset of the full-rate envelope inside the
    # winning (bin-resolution) window
    onset_bin_sample = k * bin_len
    win = seg[onset_bin_sample : onset_bin_sample + L]
    thr = baseline + 0.5 * (np.max(win) - baseline)
    rise = int(np.argmax(win > thr))
    onset_sample = a + onset_bin_sample + rise
    return (onset_sample / sample_rate) - (minute_utc - sample0_utc_label), snr_db


def integer_second_correction(
    marker_offset_s: float, expected_delay_s: float, fractional_correction_s: float
) -> int:
    """Whole seconds to add to the label plane on top of the fold's
    fractional correction.  The marker appears at ``expected_delay + walk``
    in the label frame, so the total correction is ``expected_delay −
    marker_offset``; the fold already supplied its fractional part."""
    total = expected_delay_s - marker_offset_s
    return int(round(total - fractional_correction_s))


@dataclass
class Registration:
    """The acquired origin, held in the RTP frame: utc(sample at rtp) =
    utc_ref + (rtp − rtp_ref) / sample_rate, valid within one counter epoch."""

    counter_epoch_id: str
    rtp_ref: int
    utc_ref: float
    sample_rate: int
    sigma_ms: float
    method: str = "fold+template"
    n_minutes: int = 0
    channel: str = ""
    hypotheses_open: int = 0
    stations: tuple = ()

    def sample0_utc_for(self, start_rtp: int) -> float:
        return self.utc_ref + (int(start_rtp) - int(self.rtp_ref)) / float(
            self.sample_rate
        )


class RegistrationAcquirer:
    """Acquire from the signal, hold on the ruler, corroborate or correct
    every minute (spec §2 rules 1-3)."""

    STATE_BOOTSTRAP = "BOOTSTRAP"
    STATE_ACQUIRED = "ACQUIRED"
    CORRECT_K_SIGMA = 3.0
    CORRECT_MINUTES = 2
    CORRECT_MIN_CHANNELS = 2  # here: stations on this channel's ensembles
    FILTER_MEMORY_MINUTES = 30
    # TickEdgeDetector.LABEL_ANCHOR_MAX_SIGMA_MS = 6.0: tick-like ensembles only.
    TIMING_SIGMA_MAX_MS = TickEdgeDetector.LABEL_ANCHOR_MAX_SIGMA_MS

    def __init__(self, channel: str, sample_rate: int):
        self.channel = channel
        self.sample_rate = int(sample_rate)
        self._state = self.STATE_BOOTSTRAP
        self._reg: Optional[Registration] = None
        self._epoch: Optional[str] = None
        self._buf: List[Tuple[np.ndarray, float, int, int]] = (
            []
        )  # (audio, label_s0, start_rtp, minute)
        self._bad_minutes = 0
        self._open: List[Hypothesis] = []

    @property
    def state(self) -> str:
        return self._state

    @property
    def registration(self) -> Optional[Registration]:
        return self._reg

    def reset(self, why: str) -> None:
        logger.info(f"[{self.channel}] registration reset -> BOOTSTRAP ({why})")
        self._state = self.STATE_BOOTSTRAP
        self._reg = None
        self._buf.clear()
        self._bad_minutes = 0
        self._open.clear()

    def adopt(self, reg: Registration) -> None:
        """Adopt a sibling's (usually fused) plane as this channel's own.

        Stamped ``channel=self.channel`` (never the donor's -- a sibling
        fusion carries ``channel="fused"``, and writing that verbatim would
        make ``RegistrationStore`` file this channel's plane under
        ``fused.json`` instead of ``<channel>.json``, silently dropping this
        channel's own provenance) and ``method="adopted"`` so
        ``RegistrationStore.read_siblings`` can recognise and skip a purely
        derived plane -- otherwise an adopted echo of the fusion re-enters
        the next fusion as if it were independent corroborating evidence,
        understating sigma by sqrt(n_adopters+1) (T3 self-registration
        review, C1, 2026-09-06)."""
        self._reg = Registration(
            **{**reg.__dict__, "channel": self.channel, "method": "adopted"}
        )
        self._epoch = reg.counter_epoch_id
        self._state = self.STATE_ACQUIRED
        self._buf.clear()
        self._bad_minutes = 0

    # ── acquisition ────────────────────────────────────────────────
    def offer_minute(
        self,
        audio: np.ndarray,
        label,
        start_rtp: int,
        minute_utc: int,
        expected_delays_s: Dict[str, float],
        counter_epoch_id: str,
    ) -> Optional[Registration]:
        if self._epoch is not None and counter_epoch_id != self._epoch:
            self.reset(f"counter epoch {self._epoch} -> {counter_epoch_id}")
        self._epoch = counter_epoch_id
        if self._state == self.STATE_ACQUIRED and self._reg is not None:
            return self._reg
        self._buf.append(
            (
                np.asarray(audio, dtype=np.float64),
                float(label.sample0_utc),
                int(start_rtp),
                int(minute_utc),
            )
        )
        self._buf = self._buf[-3:]
        return self._try_acquire(expected_delays_s)

    def _try_acquire(
        self, expected_delays_s: Dict[str, float]
    ) -> Optional[Registration]:
        # Concatenate the buffered minutes in the frame of the OLDEST label;
        # each minute is re-labelled onto that frame through RTP, so a ring
        # anchor refresh between minutes cannot smear the fold.
        a0, s0, rtp0, _ = self._buf[0]
        pieces = []
        for audio, s_lbl, rtp, _ in self._buf:
            # gap/overlap between consecutive buffers, in samples, from RTP
            want = rtp - rtp0
            have = sum(len(p) for p in pieces)
            if want > have:
                pieces.append(np.zeros(want - have))
            elif want < have:
                audio = audio[have - want :]
            pieces.append(audio)
        audio_all = np.concatenate(pieces)
        n_sec = min(180, len(audio_all) // self.sample_rate)
        by_band: Dict[str, List[FoldPeak]] = {}
        for band in TONE_BANDS_HZ:
            # fold EVERY band, even one with no eligible station: the leak of a
            # 1200 Hz tick into 900-1100 Hz is only recognisable by comparison
            profile, rows = fold_tick_train(
                audio_all, self.sample_rate, s0, band, n_sec
            )
            if rows == 0:
                continue
            by_band[band] = find_fold_peaks(profile, self.sample_rate, band)
        best = [
            p
            for p in arbitrate_bands(by_band)
            if any(BAND_OF_STATION.get(s) == p.band for s in expected_delays_s)
        ]
        hyps = fit_template(best, expected_delays_s)
        self._open = [h for h in hyps if not h.unambiguous]
        winners = [h for h in hyps if h.unambiguous]
        if not winners:
            logger.info(
                f"[{self.channel}] BOOTSTRAP: {n_sec} s folded, "
                f"{len(best)} peaks, {len(self._open)} ambiguous hypotheses"
            )
            return None
        h = winners[0]
        # integer second from the marker of the most recent minute, located in
        # the OLDEST label's frame (re-labelled through RTP) so that a ring
        # anchor refresh between minutes cannot shift the whole-second answer
        k_int = 0
        a_last, _s_last_unused, rtp_last, minute_last = self._buf[-1]
        s_last_in_frame0 = s0 + (rtp_last - rtp0) / self.sample_rate
        st0 = h.assignments[0][0]
        mk = locate_minute_marker(
            a_last,
            self.sample_rate,
            s_last_in_frame0,
            BAND_OF_STATION[st0],
            minute_last,
        )
        if mk is not None:
            k_int = integer_second_correction(
                mk[0], expected_delays_s[st0], h.correction_s
            )
        corr = h.correction_s + k_int
        self._reg = Registration(
            counter_epoch_id=self._epoch or "unregistered",
            rtp_ref=rtp0,
            utc_ref=s0 + corr,
            sample_rate=self.sample_rate,
            sigma_ms=h.sigma_ms,
            channel=self.channel,
            hypotheses_open=len(self._open),
            stations=tuple(sorted({a[0] for a in h.assignments})),
        )
        self._state = self.STATE_ACQUIRED
        self._bad_minutes = 0
        logger.info(
            f"[{self.channel}] ACQUIRED: correction {corr*1000:+.1f} ms "
            f"(int {k_int:+d} s), σ {h.sigma_ms:.2f} ms, support {h.support}, "
            f"stations {[a[0] for a in h.assignments]}, fold {n_sec} s"
        )
        return self._reg

    def resolve_ambiguity(
        self, sibling: Registration, start_rtp: int, label_s0: float
    ) -> Optional[Registration]:
        """A shared channel with one peak carries two or more hypotheses; a
        sibling channel's plane names the right one.  Same-site agreement
        is tight (SAME_SITE_AGREE_MS); cross-site looser (CROSS_SITE_AGREE_MS).
        The sibling also supplies the whole second."""
        if self._state == self.STATE_ACQUIRED or not self._open:
            return None
        sib_s0 = sibling.sample0_utc_for(int(start_rtp))
        matches = []
        for h in self._open:
            st = h.assignments[0][0]
            tol = SAME_SITE_AGREE_MS if st in sibling.stations else CROSS_SITE_AGREE_MS
            frac = wrap_half_second((label_s0 + h.correction_s) - sib_s0)
            if abs(frac) * 1000.0 <= tol:
                matches.append((h, frac))
        if len(matches) != 1:
            return None
        h, frac = matches[0]
        # own fractional correction + the sibling's whole second
        s0 = sib_s0 + frac
        self._reg = Registration(
            counter_epoch_id=self._epoch or sibling.counter_epoch_id,
            rtp_ref=int(start_rtp),
            utc_ref=s0,
            sample_rate=self.sample_rate,
            sigma_ms=h.sigma_ms,
            channel=self.channel,
            hypotheses_open=0,
            stations=(h.assignments[0][0],),
        )
        self._state = self.STATE_ACQUIRED
        self._open.clear()
        self._bad_minutes = 0
        logger.info(
            f"[{self.channel}] ACQUIRED via sibling {sibling.channel}: "
            f"hypothesis {h.assignments[0][0]} agrees within {abs(frac)*1000:.2f} ms"
        )
        return self._reg

    # ── corroboration ──────────────────────────────────────────────
    def corroborate(self, residuals_ms: Dict[str, Tuple[float, float]]) -> str:
        """``residuals_ms``: station -> (ensemble timing error vs the
        ACQUIRED plane, per-tick sigma).  Only tick-like ensembles
        (sigma ≤ TIMING_SIGMA_MAX_MS) count."""
        if self._reg is None:
            return "held"
        good = {
            s: r for s, r in residuals_ms.items() if r[1] <= self.TIMING_SIGMA_MAX_MS
        }
        if not good:
            return "held"
        thr = self.CORRECT_K_SIGMA * max(self._reg.sigma_ms, ORIGIN_SIGMA_FLOOR_MS)
        far = [s for s, (e, _) in good.items() if abs(e) > thr]
        if len(far) >= self.CORRECT_MIN_CHANNELS or (len(good) == 1 and far):
            self._bad_minutes += 1
            if self._bad_minutes >= self.CORRECT_MINUTES:
                self.reset(
                    f"residual > {self.CORRECT_K_SIGMA}σ for "
                    f"{self.CORRECT_MINUTES} minutes on {far}"
                )
                return "reacquire"
            return "held"
        self._bad_minutes = 0
        # slow filter: running weighted mean with long memory (the true origin
        # is constant on the GPSDO; this is a smoother, not a tracker)
        w_new = sum(1.0 / max(sig, 0.1) ** 2 for _, sig in good.values())
        e_new = sum(e / max(sig, 0.1) ** 2 for e, sig in good.values()) / w_new
        n = min(self._reg.n_minutes, self.FILTER_MEMORY_MINUTES)
        w_old = (n / max(self._reg.sigma_ms, ORIGIN_SIGMA_FLOOR_MS) ** 2) if n else 0.0
        shift_ms = (w_new * e_new) / (w_new + w_old)
        # tick_edge_detector.timing_error_ms = front_edge - expected: a
        # POSITIVE residual means the plane's labels ran LATE (the edge
        # arrived after the plane said it would), so the plane must move
        # EARLIER to correct it -- subtract, don't add (T3 self-registration
        # review, C2, 2026-09-06: the prior `+=` doubled the error instead
        # of cancelling it).
        self._reg.utc_ref -= shift_ms / 1000.0
        self._reg.n_minutes += 1
        new_sigma = (
            1.0 / np.sqrt(w_new + w_old) if (w_new + w_old) > 0 else self._reg.sigma_ms
        )
        self._reg.sigma_ms = float(
            max(ORIGIN_SIGMA_FLOOR_MS * 0.1, min(self._reg.sigma_ms, new_sigma))
        )
        return "tightened"
