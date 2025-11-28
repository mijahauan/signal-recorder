#!/usr/bin/env python3
"""
Timing Metrics Writer for Web-UI Timing Analysis

Collects and writes timing metrics for visualization:
- Time_snap status and quality
- RTP drift measurements
- NTP comparison
- Time source transitions
"""

import csv
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
import time

logger = logging.getLogger(__name__)


@dataclass
class TimingSnapshot:
    """Single timing measurement snapshot"""
    timestamp_utc: str
    channel: str
    source_type: str  # 'wwv_startup', 'chu_startup', 'ntp', 'wall_clock'
    quality: str  # 'TONE_LOCKED', 'NTP_SYNCED', 'INTERPOLATED', 'WALL_CLOCK'
    snr_db: Optional[float]
    confidence: float
    age_seconds: float
    rtp_anchor: int
    utc_anchor: float
    drift_ms: float
    jitter_ms: float
    ntp_offset_ms: Optional[float]
    health_score: int


@dataclass
class TimingTransition:
    """Time source transition event"""
    timestamp: str
    channel: str
    from_source: str
    to_source: str
    from_quality: str
    to_quality: str
    reason: str
    last_snr_db: Optional[float]
    last_confidence: float
    duration_on_previous_source_minutes: float


class TimingMetricsWriter:
    """
    Write timing metrics for web-UI analysis
    
    Creates two outputs:
    1. timing_metrics_YYYYMMDD.csv - Minute-by-minute metrics
    2. timing_transitions_YYYYMMDD.json - Transition events
    """
    
    def __init__(self, output_dir: Path, channel_name: str):
        """
        Initialize timing metrics writer
        
        Args:
            output_dir: Directory for timing metrics (e.g., /analytics/{CHANNEL}/timing/)
            channel_name: Channel identifier
        """
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        
        # Ensure directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Track previous state for transition detection
        self.previous_source = None
        self.previous_quality = None
        self.previous_source_start_time = None
        self.previous_snr_db = None
        self.previous_confidence = None
        
        # Track previous archive for minute-to-minute drift calculation
        self.previous_rtp = None
        self.previous_utc = None  # UTC calculated from time_snap + RTP
        self.previous_time_snap_rtp = None  # Track if time_snap changed
        
        # Track tone-to-tone measurements (gold standard for A/D clock stability)
        self.last_tone_snap = None  # Previous tone-based time_snap
        self.tone_to_tone_drift_ppm = None  # A/D clock drift in ppm
        
        # Drift tracking for jitter calculation
        # Use 60 measurements (1 hour) for better statistical averaging
        # This helps smooth out short-term noise from host clock jitter
        self.drift_history = []
        self.max_drift_history = 60
        
        logger.info(f"{channel_name}: TimingMetricsWriter initialized at {output_dir}")
    
    def write_snapshot(self, time_snap: 'TimeSnapReference', 
                      current_rtp: int, current_utc: float,
                      ntp_offset_ms: Optional[float] = None,
                      ntp_synced: bool = False):
        """
        Write current timing snapshot
        
        Args:
            time_snap: Current time_snap reference (tone-locked precision)
            current_rtp: Current RTP timestamp
            current_utc: Current system time (NTP-synced if available)
            ntp_offset_ms: NTP offset for comparison
            ntp_synced: Whether system time is NTP-synchronized
            
        Note:
            Drift measurement hierarchy:
            1. RTP clock (what we're testing) via time_snap anchor
            2. vs NTP-synced time (±10ms precision) - preferred
            3. vs Unsynchronized wall clock (±seconds) - fallback
            
            This shows if RTP clock is drifting from real time.
            Drift reliability depends on reference quality (NTP > wall clock).
        """
        if time_snap is None:
            logger.debug(f"{self.channel_name}: No time_snap available for metrics")
            return
        
        try:
            # Check if we have a new tone detection (gold standard reference)
            self._check_tone_to_tone_drift(time_snap)
            
            # Calculate drift: RTP clock vs real time (NTP-synced or wall clock)
            # Note: This measures combined (RTP + reference) drift, not pure RTP stability
            # For pure A/D clock stability, use tone_to_tone_drift_ppm
            drift_ms = self._calculate_drift_minute_to_minute(
                time_snap, current_rtp, current_utc, ntp_synced
            )
            
            # Track drift for jitter calculation
            self.drift_history.append(drift_ms)
            if len(self.drift_history) > self.max_drift_history:
                self.drift_history.pop(0)
            
            # Calculate jitter (peak-to-peak variation)
            jitter_ms = self._calculate_jitter()
            
            # Classify quality
            quality = self._classify_quality(time_snap, drift_ms)
            
            # Calculate health score using UTC timestamp age (when tone was detected)
            age_seconds = time.time() - time_snap.utc_timestamp
            health_score = self._calculate_health_score(
                time_snap, drift_ms, jitter_ms, age_seconds
            )
            
            # Get SNR if available
            snr_db = getattr(time_snap, 'detection_snr_db', None)
            
            # Create snapshot
            snapshot = TimingSnapshot(
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                channel=self.channel_name,
                source_type=time_snap.source,
                quality=quality,
                snr_db=snr_db,
                confidence=time_snap.confidence,
                age_seconds=age_seconds,
                rtp_anchor=time_snap.rtp_timestamp,
                utc_anchor=time_snap.utc_timestamp,
                drift_ms=drift_ms,
                jitter_ms=jitter_ms,
                ntp_offset_ms=ntp_offset_ms,
                health_score=health_score
            )
            
            # Write to CSV
            self._write_csv(snapshot)
            
            # Check for transition
            self._check_transition(snapshot, snr_db, time_snap.confidence)
            
        except Exception as e:
            logger.error(f"{self.channel_name}: Error writing timing snapshot: {e}")
    
    def _calculate_drift_minute_to_minute(self, time_snap: 'TimeSnapReference',
                                          current_rtp: int, current_time_utc: float,
                                          ntp_synced: bool) -> float:
        """
        Calculate ADC clock DRIFT RATE against wall clock reference
        
        This measures the CHANGE in phase offset between RTP-derived time and
        wall clock time since the last measurement. The absolute offset is not
        meaningful (varies by channel due to packet arrival timing), but the
        rate of change indicates ADC clock frequency error.
        
        Measurement:
        1. offset = wall_clock - rtp_predicted (phase difference)
        2. drift_rate = current_offset - previous_offset (change in phase)
        
        Interpretation:
        - drift_rate ≈ 0: ADC clock running at exactly 16000 Hz
        - drift_rate > 0: ADC clock slow (RTP falling behind wall clock)
        - drift_rate < 0: ADC clock fast (RTP running ahead of wall clock)
        
        Limitations:
        - Host clock jitter directly affects measurement noise
        - For sub-ms precision, host needs quality NTP/PTP synchronization
        - Use tone-to-tone measurement for gold-standard ADC characterization
        
        Returns:
            Accumulated drift in milliseconds since last measurement.
            This is written to the 'drift_ms' CSV column.
        """
        # Calculate current offset between wall clock and RTP-predicted time
        rtp_predicted_utc = time_snap.calculate_sample_time(current_rtp)
        current_offset_ms = (current_time_utc - rtp_predicted_utc) * 1000.0
        
        # Initialize baseline on first call
        if not hasattr(self, '_last_offset_ms'):
            self._last_offset_ms = current_offset_ms
            self._last_offset_time = current_time_utc
            logger.info(f"{self.channel_name}: Drift baseline established, offset={current_offset_ms:.1f}ms")
            return 0.0
        
        # Calculate drift rate (change in offset)
        offset_change_ms = current_offset_ms - self._last_offset_ms
        time_elapsed = current_time_utc - self._last_offset_time
        
        # Update baseline for next measurement
        self._last_offset_ms = current_offset_ms
        self._last_offset_time = current_time_utc
        
        # Sanity check: offset change should be small (< 1 second per minute for reasonable clocks)
        # Only suppress if this is a short interval (< 2 minutes) - longer gaps may legitimately
        # accumulate more drift
        if abs(offset_change_ms) > 1000 and time_elapsed < 120.0:
            logger.warning(f"{self.channel_name}: Large offset change ({offset_change_ms:.1f}ms over {time_elapsed:.0f}s) - "
                          f"possible time_snap discontinuity or clock jump")
            return 0.0
        
        # Log drift rate if significant
        if abs(offset_change_ms) > 10 and time_elapsed > 30:
            drift_ppm = (offset_change_ms / 1000.0) / time_elapsed * 1e6
            logger.debug(f"{self.channel_name}: Drift rate {offset_change_ms:.1f}ms over {time_elapsed:.0f}s "
                        f"({drift_ppm:.1f} ppm)")
        
        return offset_change_ms
    
    def _check_tone_to_tone_drift(self, time_snap: 'TimeSnapReference'):
        """
        Calculate A/D clock drift using tone-to-tone measurement (gold standard)
        
        This is the definitive measurement of RTP clock stability:
        - Uses consecutive tone detections as ground truth
        - Measures: Is the A/D clock running at exactly 16000 Hz?
        - Result in PPM (parts per million) frequency error
        
        Example:
            Tone A: RTP=1000000, UTC=100.0 (WWV tone)
            Tone B: RTP=5760000, UTC=400.0 (WWV tone)
            
            Expected samples = (400.0 - 100.0) * 16000 = 4,800,000
            Actual samples = 5760000 - 1000000 = 4,760,000
            
            Drift = 4,760,000 / 4,800,000 = 0.9917
            Error = (0.9917 - 1.0) * 1e6 = -8333 ppm (clock running slow)
        """
        # Only process tone-based time_snaps
        source_lower = time_snap.source.lower() if time_snap.source else ''
        is_tone = any(station in source_lower for station in ['wwv', 'chu'])
        
        if not is_tone:
            return  # Not a tone detection
        
        # First tone detection - establish baseline
        if self.last_tone_snap is None:
            self.last_tone_snap = time_snap
            logger.info(f"{self.channel_name}: Baseline tone established for A/D clock measurement")
            return
        
        # Check if this is a NEW tone detection (not just re-using old time_snap)
        if time_snap.rtp_timestamp == self.last_tone_snap.rtp_timestamp:
            return  # Same tone, no new measurement
        
        # Calculate tone-to-tone drift
        # Time between tones (ground truth from WWV/CHU)
        tone_time_elapsed = time_snap.utc_timestamp - self.last_tone_snap.utc_timestamp
        
        # RTP samples between tones (A/D clock measurement)
        rtp_samples_elapsed = time_snap.rtp_timestamp - self.last_tone_snap.rtp_timestamp
        if rtp_samples_elapsed < 0:  # Handle wraparound
            rtp_samples_elapsed += 0x100000000
        
        # Expected samples based on tone times
        expected_samples = tone_time_elapsed * time_snap.sample_rate
        
        # A/D clock frequency ratio
        clock_ratio = rtp_samples_elapsed / expected_samples
        
        # Drift in PPM (parts per million)
        # 1.000000 = perfect
        # 1.000010 = +10 ppm (clock running fast)
        # 0.999990 = -10 ppm (clock running slow)
        drift_ppm = (clock_ratio - 1.0) * 1e6
        
        self.tone_to_tone_drift_ppm = drift_ppm
        self.last_tone_snap = time_snap
        
        logger.info(f"{self.channel_name}: Tone-to-tone A/D clock drift: {drift_ppm:+.2f} ppm "
                   f"(over {tone_time_elapsed:.1f}s, {rtp_samples_elapsed} samples)")
    
    def _calculate_jitter(self) -> float:
        """
        Calculate jitter (short-term timing instability)
        
        Uses RMS (Root Mean Square) of drift differences for robustness:
        - More statistically sound than peak-to-peak
        - Less sensitive to outliers
        - Represents typical variation, not worst-case
        
        Returns: RMS jitter in milliseconds
        """
        if len(self.drift_history) < 2:
            return 0.0
        
        # Calculate successive differences (Δdrift)
        drift_diffs = []
        for i in range(1, len(self.drift_history)):
            diff = self.drift_history[i] - self.drift_history[i-1]
            drift_diffs.append(diff * diff)  # Square for RMS
        
        # RMS of differences
        if drift_diffs:
            mean_square = sum(drift_diffs) / len(drift_diffs)
            rms_jitter = mean_square ** 0.5
            return rms_jitter
        
        return 0.0
    
    def _classify_quality(self, time_snap: 'TimeSnapReference', drift_ms: float) -> str:
        """
        Classify timing quality based on source and age
        
        Quality hierarchy:
        1. TONE_LOCKED - Fresh tone detection (< 5 min, low drift)
        2. INTERPOLATED - Aging tone reference (5 min - 1 hour)
        3. NTP_SYNCED - NTP anchor OR aged tone with NTP fallback available
        4. WALL_CLOCK - No recent tone, no NTP (poorest quality)
        
        Note: This classifies the ANCHOR quality, not the drift measurement.
        - TONE_LOCKED anchor + large drift = indicates A/D clock problem
        - NTP_SYNCED anchor + large drift = indicates system clock problem
        
        Returns: 'TONE_LOCKED', 'INTERPOLATED', 'NTP_SYNCED', 'WALL_CLOCK'
        """
        # Use UTC timestamp age (when tone was detected), not established_at (when stored)
        age_seconds = time.time() - time_snap.utc_timestamp
        
        # Check if source is tone-based (wwv, chu, wwvh in any form)
        source_lower = time_snap.source.lower() if time_snap.source else ''
        is_tone_source = any(station in source_lower for station in ['wwv', 'chu'])
        
        # Thresholds chosen to match propagation reality:
        # - Tone precision degrades ~1ms/hour due to ADC clock drift
        # - 30 min = still within ±0.5ms, clearly "locked"
        # - 2 hours = still better than NTP (±10ms), but aging
        TONE_LOCKED_MAX_AGE = 1800    # 30 minutes
        TONE_DERIVED_MAX_AGE = 7200   # 2 hours
        
        # Tone-based classifications (best quality)
        if is_tone_source:
            # Fresh tone with low drift = actively tone-locked
            if age_seconds < TONE_LOCKED_MAX_AGE and abs(drift_ms) < 5.0:
                return 'TONE_LOCKED'
            # Aging tone but still valid (better than NTP)
            elif age_seconds < TONE_DERIVED_MAX_AGE:
                return 'INTERPOLATED'
            # Very old tone - fall through to check NTP fallback
        
        # NTP-based anchor (explicit NTP source)
        if time_snap.source == 'ntp':
            return 'NTP_SYNCED'
        
        # Aged tone (>2 hours) - check if NTP available as fallback
        # This allows graceful degradation: TONE → NTP → WALL_CLOCK
        if is_tone_source and age_seconds >= TONE_DERIVED_MAX_AGE:
            ntp_offset = self.get_ntp_offset()
            if ntp_offset is not None:
                return 'NTP_SYNCED'  # Fallback to NTP for aged tone
        
        # No good anchor available - wall clock only
        return 'WALL_CLOCK'
    
    def _calculate_health_score(self, time_snap: 'TimeSnapReference',
                                drift_ms: float, jitter_ms: float,
                                age_seconds: float) -> int:
        """
        Calculate health score (0-100)
        
        Higher is better. Considers:
        - Time_snap source quality
        - Drift magnitude
        - Jitter (stability)
        - Age of reference
        - SNR (if tone-locked)
        """
        health = 100.0
        
        # Age penalty (older references less reliable)
        age_minutes = age_seconds / 60.0
        health -= min(age_minutes * 0.1, 30.0)  # Max 30 point penalty
        
        # Drift penalty
        health -= min(abs(drift_ms) * 2.0, 30.0)  # Max 30 points
        
        # Jitter penalty (instability)
        health -= min(jitter_ms * 5.0, 20.0)  # Max 20 points
        
        # Source quality penalty
        if time_snap.source in ['wwv_startup', 'chu_startup', 'wwvh_startup']:
            health += 0  # Best source, no penalty
        elif time_snap.source == 'ntp':
            health -= 10
        elif time_snap.source == 'wall_clock':
            health -= 40
        
        # SNR bonus (strong signal = more reliable)
        snr_db = getattr(time_snap, 'detection_snr_db', None)
        if snr_db and snr_db > 20:
            health += min((snr_db - 20) * 0.5, 10.0)  # Max 10 point bonus
        
        # Confidence factor
        health *= time_snap.confidence
        
        return max(0, min(100, int(health)))
    
    def _write_csv(self, snapshot: TimingSnapshot):
        """Write snapshot to daily CSV file"""
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        csv_path = self.output_dir / f"{self.channel_name.replace(' ', '_')}_timing_metrics_{date_str}.csv"
        
        fieldnames = [
            'timestamp_utc', 'channel', 'source_type', 'quality', 'snr_db',
            'confidence', 'age_seconds', 'rtp_anchor', 'utc_anchor',
            'drift_ms', 'jitter_ms', 'ntp_offset_ms', 'health_score'
        ]
        
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                'timestamp_utc': snapshot.timestamp_utc,
                'channel': snapshot.channel,
                'source_type': snapshot.source_type,
                'quality': snapshot.quality,
                'snr_db': f"{snapshot.snr_db:.1f}" if snapshot.snr_db else '',
                'confidence': f"{snapshot.confidence:.2f}",
                'age_seconds': f"{snapshot.age_seconds:.1f}",
                'rtp_anchor': snapshot.rtp_anchor,
                'utc_anchor': f"{snapshot.utc_anchor:.3f}",
                'drift_ms': f"{snapshot.drift_ms:.3f}",
                'jitter_ms': f"{snapshot.jitter_ms:.3f}",
                'ntp_offset_ms': f"{snapshot.ntp_offset_ms:.2f}" if snapshot.ntp_offset_ms else '',
                'health_score': snapshot.health_score
            })
    
    def _check_transition(self, snapshot: TimingSnapshot, 
                         current_snr_db: Optional[float],
                         current_confidence: float):
        """Check if time source transitioned and log event"""
        current_source = snapshot.source_type
        current_quality = snapshot.quality
        
        # First call - just store state
        if self.previous_source is None:
            self.previous_source = current_source
            self.previous_quality = current_quality
            self.previous_source_start_time = time.time()
            self.previous_snr_db = current_snr_db
            self.previous_confidence = current_confidence
            return
        
        # Check for transition
        if current_source != self.previous_source or current_quality != self.previous_quality:
            # Calculate duration on previous source
            duration_minutes = (time.time() - self.previous_source_start_time) / 60.0
            
            # Determine reason
            reason = self._determine_transition_reason(
                self.previous_source, current_source,
                self.previous_snr_db, current_snr_db,
                self.previous_confidence, current_confidence
            )
            
            # Create transition event
            transition = TimingTransition(
                timestamp=snapshot.timestamp_utc,
                channel=self.channel_name,
                from_source=self.previous_source,
                to_source=current_source,
                from_quality=self.previous_quality,
                to_quality=current_quality,
                reason=reason,
                last_snr_db=self.previous_snr_db,
                last_confidence=self.previous_confidence,
                duration_on_previous_source_minutes=duration_minutes
            )
            
            # Log transition
            self._write_transition(transition)
            
            logger.info(
                f"{self.channel_name}: Time source transition: "
                f"{self.previous_source} ({self.previous_quality}) → "
                f"{current_source} ({current_quality}), reason: {reason}"
            )
            
            # Update state
            self.previous_source = current_source
            self.previous_quality = current_quality
            self.previous_source_start_time = time.time()
        
        # Always update SNR/confidence
        self.previous_snr_db = current_snr_db
        self.previous_confidence = current_confidence
    
    def _determine_transition_reason(self, from_source: str, to_source: str,
                                    from_snr: Optional[float], to_snr: Optional[float],
                                    from_conf: float, to_conf: float) -> str:
        """Determine why transition occurred"""
        # Tone → NTP/Wall clock
        if from_source in ['wwv_startup', 'chu_startup', 'wwvh_startup']:
            if to_source == 'ntp':
                if from_snr and from_snr < 10:
                    return f"tone_snr_low (SNR={from_snr:.1f}dB)"
                elif from_conf < 0.7:
                    return f"tone_confidence_low (conf={from_conf:.2f})"
                else:
                    return "tone_lost"
            elif to_source == 'wall_clock':
                return "ntp_unavailable"
        
        # NTP → Tone (upgrade)
        if from_source == 'ntp' and to_source in ['wwv_startup', 'chu_startup', 'wwvh_startup']:
            if to_snr:
                return f"tone_detected (SNR={to_snr:.1f}dB, conf={to_conf:.2f})"
            return "tone_recovered"
        
        # Tone → Tone (better reference)
        if (from_source in ['wwv_startup', 'chu_startup', 'wwvh_startup'] and
            to_source in ['wwv_startup', 'chu_startup', 'wwvh_startup']):
            if to_conf > from_conf + 0.05:
                return f"better_confidence (conf={to_conf:.2f})"
            if to_snr and from_snr and to_snr > from_snr + 5:
                return f"better_snr (SNR={to_snr:.1f}dB)"
            return "tone_upgrade"
        
        # Wall clock → NTP (recovery)
        if from_source == 'wall_clock' and to_source == 'ntp':
            return "ntp_restored"
        
        return "source_changed"
    
    def _write_transition(self, transition: TimingTransition):
        """Append transition to daily JSON log"""
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        json_path = self.output_dir / f"{self.channel_name.replace(' ', '_')}_timing_transitions_{date_str}.json"
        
        # Load existing transitions
        transitions = []
        if json_path.exists():
            try:
                with open(json_path, 'r') as f:
                    data = json.load(f)
                    transitions = data.get('transitions', [])
            except Exception as e:
                logger.warning(f"Error reading transitions file: {e}")
        
        # Append new transition
        transitions.append({
            'timestamp': transition.timestamp,
            'channel': transition.channel,
            'from_source': transition.from_source,
            'to_source': transition.to_source,
            'from_quality': transition.from_quality,
            'to_quality': transition.to_quality,
            'reason': transition.reason,
            'last_snr_db': transition.last_snr_db,
            'last_confidence': transition.last_confidence,
            'duration_on_previous_source_minutes': round(transition.duration_on_previous_source_minutes, 1)
        })
        
        # Write back
        with open(json_path, 'w') as f:
            json.dump({'transitions': transitions}, f, indent=2)
    
    # NOTE: get_ntp_offset() has been removed.
    # NTP offset is now obtained from the centralized NTPStatusCache in CoreRecorder
    # and passed to write_snapshot() via the ntp_offset_ms parameter.
    # This eliminates blocking subprocess calls in the analytics path.
