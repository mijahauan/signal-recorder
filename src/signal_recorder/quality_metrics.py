#!/usr/bin/env python3
"""
Quality Metrics and Tracking for GRAPE Data

Comprehensive tracking of data quality, timing accuracy, and gaps
for scientific provenance and validation.
"""

import csv
import json
import time
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict
from enum import Enum

logger = logging.getLogger(__name__)


def format_quality_summary(minute: 'MinuteQualityMetrics') -> str:
    """
    Format minute quality metrics for console/web display
    Focuses on KA9Q timing architecture priorities
    """
    grade_emoji = {
        "A": "✅",
        "B": "✓",
        "C": "⚠️",
        "D": "❌",
        "F": "🔴",
        "UNKNOWN": "?"
    }
    
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"Minute: {minute.minute_start_str}")
    lines.append(f"Quality: {grade_emoji.get(minute.quality_grade, '?')} {minute.quality_grade} ({minute.quality_score:.1f}/100)")
    
    if minute.alerts:
        lines.append(f"\n🚨 ALERTS:")
        for alert in minute.alerts:
            lines.append(f"   {alert}")
    
    lines.append(f"\n📊 Sample Integrity:")
    lines.append(f"   Samples: {minute.actual_samples:,}/{minute.expected_samples:,} ({minute.completeness_percent:.2f}%)")
    if minute.gap_samples_filled > 0:
        lines.append(f"   Gaps filled: {minute.gap_samples_filled:,} samples ({minute.gaps_count} events)")
    
    lines.append(f"\n📡 RTP Continuity:")
    lines.append(f"   Packets: {minute.packets_received}/{minute.packets_expected} ({minute.packet_loss_percent:.3f}% loss)")
    if minute.packets_resequenced > 0:
        lines.append(f"   Resequenced: {minute.packets_resequenced} packets (max depth: {minute.max_resequencing_depth})")
        lines.append(f"   Queue usage: {minute.resequencing_buffer_utilization:.1f}%")
    
    if minute.time_snap_established:
        lines.append(f"\n⏱️  Time_snap Quality:")
        lines.append(f"   Status: {minute.time_snap_source}")
        if minute.time_snap_drift_ms is not None:
            lines.append(f"   Drift: {minute.time_snap_drift_ms:+.1f} ms")
        if minute.time_snap_age_minutes is not None:
            lines.append(f"   Age: {minute.time_snap_age_minutes} minutes")
    
    if minute.wwv_tone_detected is not None:
        lines.append(f"\n📻 WWV/CHU Detection:")
        if minute.wwv_tone_detected:
            lines.append(f"   Detected: YES ✅")
            if minute.wwv_timing_error_ms is not None:
                lines.append(f"   Timing error: {minute.wwv_timing_error_ms:+.1f} ms")
            if minute.wwv_tone_duration_ms is not None:
                lines.append(f"   Duration: {minute.wwv_tone_duration_ms:.1f} ms")
        else:
            lines.append(f"   Detected: NO (propagation/signal)")
    
    lines.append(f"{'='*60}")
    
    return "\n".join(lines)


class DiscontinuityType(Enum):
    """Types of timing discontinuities"""
    GAP = "gap"                    # Missing packets/samples
    OVERLAP = "overlap"            # Duplicate or overlapping data
    SYNC_ADJUST = "sync_adjust"    # Timing correction applied
    RTP_RESET = "rtp_reset"        # RTP sequence/timestamp reset


@dataclass
class TimingDiscontinuity:
    """
    Record of a timing discontinuity in the data stream
    
    Every gap, jump, or correction is logged for scientific provenance.
    """
    timestamp: float  # Unix time when discontinuity was detected
    sample_index: int  # Sample number in output stream where discontinuity occurs
    discontinuity_type: DiscontinuityType
    magnitude_samples: int  # Positive = gap/forward jump, negative = overlap/backward jump
    magnitude_ms: float  # Time equivalent in milliseconds
    
    # RTP packet info
    rtp_sequence_before: Optional[int]
    rtp_sequence_after: Optional[int]
    rtp_timestamp_before: Optional[int]
    rtp_timestamp_after: Optional[int]
    
    # Validation
    wwv_tone_detected: bool  # Was this related to WWV tone detection?
    explanation: str  # Human-readable description
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        d = asdict(self)
        d['discontinuity_type'] = self.discontinuity_type.value
        return d


@dataclass
class MinuteQualityMetrics:
    """Quality metrics for each 1-minute recording"""
    
    # Timing
    minute_timestamp_utc: float       # Unix time at minute boundary
    minute_start_str: str             # ISO format: YYYY-MM-DDTHH:MM:SSZ
    
    # Completeness
    expected_samples: int             # Expected samples (e.g., 480,000 @ 8 kHz)
    actual_samples: int               # Actual samples recorded
    completeness_percent: float       # (actual/expected) * 100
    
    # RTP Statistics
    packets_expected: int
    packets_received: int
    packets_dropped: int
    packet_loss_percent: float
    sequence_resets: int              # RTP sequence discontinuities
    
    # Gaps & Discontinuities
    gaps_count: int
    total_gap_duration_ms: float
    largest_gap_ms: float
    gap_samples_filled: int           # Silence/zeros inserted
    
    # Timing Quality
    rtp_jitter_mean_ms: float         # Inter-packet arrival jitter
    rtp_jitter_std_ms: float
    rtp_jitter_max_ms: float
    
    # WWV Timing (Fort Collins, 1000 Hz)
    wwv_tone_detected: Optional[bool] = None
    wwv_timing_error_ms: Optional[float] = None
    wwv_tone_snr_db: Optional[float] = None
    wwv_tone_duration_ms: Optional[float] = None
    
    # WWVH Timing (Hawaii, 1200 Hz) - on 2.5, 5, 10, 15 MHz
    wwvh_tone_detected: Optional[bool] = None
    wwvh_timing_error_ms: Optional[float] = None
    wwvh_tone_snr_db: Optional[float] = None
    wwvh_tone_duration_ms: Optional[float] = None
    
    # CHU Timing (Canada, 1000 Hz) - on 3.33, 7.85, 14.67 MHz
    chu_tone_detected: Optional[bool] = None
    chu_timing_error_ms: Optional[float] = None
    chu_tone_snr_db: Optional[float] = None
    chu_tone_duration_ms: Optional[float] = None
    
    # Differential Propagation (WWV vs WWVH)
    differential_delay_ms: Optional[float] = None  # WWV_timing - WWVH_timing (propagation difference)
    
    # Time_snap Quality (KA9Q timing architecture)
    time_snap_established: bool = False
    time_snap_source: str = ""              # "wwv_first", "wwv_verified", "fallback"
    time_snap_drift_ms: Optional[float] = None  # Drift from expected (if WWV detected)
    time_snap_age_minutes: Optional[int] = None # Minutes since time_snap established
    
    # Resequencing Statistics
    packets_resequenced: int = 0            # Out-of-order packets fixed
    max_resequencing_depth: int = 0         # Worst case reordering
    resequencing_buffer_utilization: float = 0.0  # Peak % of 64-entry buffer
    
    # Signal Quality
    signal_mean_power_db: float = 0.0
    signal_peak_power_db: float = 0.0
    signal_rms: float = 0.0
    clipping_detected: bool = False
    
    # Quality Grade & Alerts
    quality_grade: str = "UNKNOWN"          # A, B, C, D, F
    quality_score: float = 0.0              # 0-100
    alerts: List[str] = field(default_factory=list)  # Critical issues
    
    # Processing
    processing_notes: List[str] = field(default_factory=list)
    
    def to_dict(self):
        """Convert to dictionary"""
        return asdict(self)
    
    def calculate_quality_grade(self):
        """
        Calculate quality grade based on data completeness and detection success
        
        A (95-100): Excellent - Complete data, tone detected, minimal drift
        B (90-95):  Good - Complete data, may have minor issues
        C (80-90):  Fair - Mostly complete, some packet loss or no detection
        D (70-80):  Poor - Significant data loss
        F (<70):    Failed - Data unusable
        """
        score = 100.0
        alerts = []
        
        # 1. Data Completeness (50 points) - MOST CRITICAL
        sample_error_pct = abs(100.0 - self.completeness_percent)
        if sample_error_pct > 0.5:
            score -= min(50, sample_error_pct / 2)  # Lose 1 point per 1% missing
            if sample_error_pct > 5:
                alerts.append(f"Data incomplete: {sample_error_pct:.1f}% missing")
        
        # 2. Packet Loss (20 points)
        if self.packet_loss_percent > 0.5:
            score -= min(20, self.packet_loss_percent * 4)
            if self.packet_loss_percent > 1.0:
                alerts.append(f"Packet loss: {self.packet_loss_percent:.1f}%")
        
        # 3. WWV Detection Success (20 points) - WWV channels only
        if self.wwv_tone_detected is False:
            score -= 10
            if not self.time_snap_established:
                score -= 10
                alerts.append("No WWV detection, no time_snap")
        
        # 4. Time_snap Drift (10 points) - if detected
        if self.time_snap_drift_ms is not None:
            drift_abs = abs(self.time_snap_drift_ms)
            if drift_abs > 100:
                score -= 10
                alerts.append(f"Large drift: {drift_abs:.0f}ms")
            elif drift_abs > 50:
                score -= 5
        
        # Determine grade
        score = max(0, min(100, score))
        if score >= 95:
            grade = "A"
        elif score >= 90:
            grade = "B"
        elif score >= 80:
            grade = "C"
        elif score >= 70:
            grade = "D"
        else:
            grade = "F"
        
        self.quality_score = score
        self.quality_grade = grade
        self.alerts = alerts
        
        return grade, score, alerts
    
    def to_csv_row(self):
        """Convert to CSV row (flatten complex fields)"""
        return {
            'timestamp_utc': self.minute_timestamp_utc,
            'minute_start': self.minute_start_str,
            'quality_grade': self.quality_grade,
            'quality_score': f"{self.quality_score:.1f}",
            'samples': self.actual_samples,
            'completeness_pct': f"{self.completeness_percent:.2f}",
            'packets_rx': self.packets_received,
            'packets_drop': self.packets_dropped,
            'packet_loss_pct': f"{self.packet_loss_percent:.3f}",
            'gaps': self.gaps_count,
            'gap_duration_ms': f"{self.total_gap_duration_ms:.1f}",
            'rtp_jitter_ms': f"{self.rtp_jitter_mean_ms:.2f}",
            'resequenced': self.packets_resequenced,
            'time_snap': self.time_snap_source,
            'drift_ms': f"{self.time_snap_drift_ms:.1f}" if self.time_snap_drift_ms is not None else "",
            # WWV (Fort Collins, 1000 Hz)
            'wwv_detected': self.wwv_tone_detected,
            'wwv_error_ms': f"{self.wwv_timing_error_ms:.1f}" if self.wwv_timing_error_ms is not None else "",
            'wwv_snr_db': f"{self.wwv_tone_snr_db:.1f}" if self.wwv_tone_snr_db is not None else "",
            # WWVH (Hawaii, 1200 Hz)
            'wwvh_detected': self.wwvh_tone_detected,
            'wwvh_error_ms': f"{self.wwvh_timing_error_ms:.1f}" if self.wwvh_timing_error_ms is not None else "",
            'wwvh_snr_db': f"{self.wwvh_tone_snr_db:.1f}" if self.wwvh_tone_snr_db is not None else "",
            'differential_delay_ms': f"{self.differential_delay_ms:.1f}" if self.differential_delay_ms is not None else "",
            'chu_detected': self.chu_tone_detected,
            'chu_error_ms': f"{self.chu_timing_error_ms:.1f}" if self.chu_timing_error_ms is not None else "",
            'chu_snr_db': f"{self.chu_tone_snr_db:.1f}" if self.chu_tone_snr_db is not None else "",
            # Other
            'signal_power_db': f"{self.signal_mean_power_db:.1f}",
            'alerts': "; ".join(self.alerts) if self.alerts else "",
            'notes': "; ".join(self.processing_notes) if self.processing_notes else ""
        }


@dataclass
class DailyQualitySummary:
    """Aggregate quality for entire day"""
    
    date_utc: str                     # YYYY-MM-DD
    channel_name: str
    frequency_hz: float
    
    # Overall Completeness
    minutes_expected: int = 1440
    minutes_recorded: int = 0
    minutes_missing: int = 0
    data_completeness_percent: float = 0.0
    
    # Gap Statistics
    total_gaps: int = 0
    total_gap_duration_sec: float = 0.0
    longest_gap_sec: float = 0.0
    longest_gap_timestamp: str = ""
    
    # WWV Timing Statistics (if WWV)
    wwv_detections_expected: int = 1440
    wwv_detections_successful: int = 0
    wwv_detection_rate_percent: float = 0.0
    wwv_timing_error_mean_ms: float = 0.0
    wwv_timing_error_std_ms: float = 0.0
    wwv_timing_error_max_ms: float = 0.0
    
    # Signal Quality
    signal_power_mean_db: float = 0.0
    signal_power_std_db: float = 0.0
    
    # RTP Quality
    total_packets_received: int = 0
    total_packets_dropped: int = 0
    packet_loss_percent: float = 0.0
    rtp_resets: int = 0
    
    # Processing Info
    recorder_version: str = "signal-recorder-0.2.0"
    decimation_method: str = ""
    digital_rf_created: bool = False
    digital_rf_uuid: str = ""
    
    def to_dict(self):
        """Convert to dictionary"""
        return asdict(self)


class QualityMetricsTracker:
    """Track quality metrics per minute and aggregate daily"""
    
    def __init__(self, channel_name: str, frequency_hz: float, output_dir: Path):
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Current minute being tracked
        self.current_minute: Optional[MinuteQualityMetrics] = None
        self.minute_metrics: List[MinuteQualityMetrics] = []
        
        # Discontinuities
        self.discontinuities: List[TimingDiscontinuity] = []
        
        logger.info(f"{channel_name}: Quality metrics tracker initialized, output: {output_dir}")
    
    def start_minute(self, timestamp: float, expected_samples: int):
        """Start tracking a new minute"""
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        minute_start = dt.replace(second=0, microsecond=0)
        
        self.current_minute = MinuteQualityMetrics(
            minute_timestamp_utc=minute_start.timestamp(),
            minute_start_str=minute_start.isoformat().replace('+00:00', 'Z'),
            expected_samples=expected_samples,
            actual_samples=0,
            completeness_percent=0.0,
            packets_expected=0,
            packets_received=0,
            packets_dropped=0,
            packet_loss_percent=0.0,
            sequence_resets=0,
            gaps_count=0,
            total_gap_duration_ms=0.0,
            largest_gap_ms=0.0,
            gap_samples_filled=0,
            rtp_jitter_mean_ms=0.0,
            rtp_jitter_std_ms=0.0,
            rtp_jitter_max_ms=0.0
        )
    
    def update_minute_samples(self, actual_samples: int):
        """Update sample count for current minute"""
        if self.current_minute:
            self.current_minute.actual_samples = actual_samples
            self.current_minute.completeness_percent = (
                actual_samples / self.current_minute.expected_samples * 100
            )
    
    def add_discontinuity(self, disc: TimingDiscontinuity):
        """Record a discontinuity"""
        self.discontinuities.append(disc)
        
        if self.current_minute and disc.discontinuity_type == DiscontinuityType.GAP:
            self.current_minute.gaps_count += 1
            self.current_minute.total_gap_duration_ms += disc.magnitude_ms
            self.current_minute.largest_gap_ms = max(
                self.current_minute.largest_gap_ms, 
                disc.magnitude_ms
            )
            self.current_minute.gap_samples_filled += abs(disc.magnitude_samples)
    
    def finalize_minute(self, actual_samples: int, packets_received: int, packets_dropped: int,
                        signal_power_db: float, wwv_result: Optional[Dict] = None,
                        differential_delay_ms: Optional[float] = None,
                        time_snap_established: bool = False, time_snap_source: str = "",
                        time_snap_drift_ms: Optional[float] = None, time_snap_age_minutes: Optional[int] = None,
                        packets_resequenced: int = 0, max_resequencing_depth: int = 0,
                        resequencing_buffer_utilization: float = 0.0):
        """Finalize current minute metrics with enhanced KA9Q timing data"""
        if not self.current_minute:
            return
        
        # Update actual sample count
        self.current_minute.actual_samples = actual_samples
        
        # RTP stats
        self.current_minute.packets_received = packets_received
        self.current_minute.packets_dropped = packets_dropped
        total_packets = packets_received + packets_dropped
        self.current_minute.packets_expected = total_packets
        if total_packets > 0:
            self.current_minute.packet_loss_percent = (
                packets_dropped / total_packets * 100
            )
        
        # Signal quality
        self.current_minute.signal_mean_power_db = signal_power_db
        
        # WWV/WWVH/CHU results (if applicable)
        # wwv_result can be a single detection dict or a list of detections
        if wwv_result:
            # Handle both single detection and list of detections
            detections = wwv_result if isinstance(wwv_result, list) else [wwv_result]
            
            for detection in detections:
                station = detection.get('station', 'WWV')  # Default to WWV for backward compat
                
                if station == 'WWV':
                    self.current_minute.wwv_tone_detected = detection.get('detected', False)
                    self.current_minute.wwv_timing_error_ms = detection.get('timing_error_ms')
                    self.current_minute.wwv_tone_snr_db = detection.get('snr_db')
                    self.current_minute.wwv_tone_duration_ms = detection.get('duration_ms')
                elif station == 'WWVH':
                    self.current_minute.wwvh_tone_detected = detection.get('detected', False)
                    self.current_minute.wwvh_timing_error_ms = detection.get('timing_error_ms')
                    self.current_minute.wwvh_tone_snr_db = detection.get('snr_db')
                    self.current_minute.wwvh_tone_duration_ms = detection.get('duration_ms')
                elif station == 'CHU':
                    self.current_minute.chu_tone_detected = detection.get('detected', False)
                    self.current_minute.chu_timing_error_ms = detection.get('timing_error_ms')
                    self.current_minute.chu_tone_snr_db = detection.get('snr_db')
                    self.current_minute.chu_tone_duration_ms = detection.get('duration_ms')
        
        # WWV-WWVH differential propagation delay
        self.current_minute.differential_delay_ms = differential_delay_ms
        
        # Time_snap quality (KA9Q timing architecture)
        self.current_minute.time_snap_established = time_snap_established
        self.current_minute.time_snap_source = time_snap_source
        self.current_minute.time_snap_drift_ms = time_snap_drift_ms
        self.current_minute.time_snap_age_minutes = time_snap_age_minutes
        
        # Resequencing statistics
        self.current_minute.packets_resequenced = packets_resequenced
        self.current_minute.max_resequencing_depth = max_resequencing_depth
        self.current_minute.resequencing_buffer_utilization = resequencing_buffer_utilization
        
        # Calculate quality grade
        self.current_minute.calculate_quality_grade()
        
        # Add to list
        self.minute_metrics.append(self.current_minute)
        self.current_minute = None
    
    def export_minute_csv(self, date_str: str):
        """Export per-minute metrics to CSV"""
        csv_path = self.output_dir / f"{self.channel_name}_minute_quality_{date_str}.csv"
        
        if not self.minute_metrics:
            logger.warning(f"{self.channel_name}: No minute metrics to export")
            return
        
        with open(csv_path, 'w', newline='') as f:
            fieldnames = list(self.minute_metrics[0].to_csv_row().keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for minute in self.minute_metrics:
                writer.writerow(minute.to_csv_row())
        
        logger.info(f"{self.channel_name}: Exported {len(self.minute_metrics)} minute metrics to {csv_path}")
        return csv_path
    
    def export_discontinuities_csv(self, date_str: str):
        """Export discontinuities to CSV"""
        csv_path = self.output_dir / f"{self.channel_name}_discontinuities_{date_str}.csv"
        
        if not self.discontinuities:
            logger.info(f"{self.channel_name}: No discontinuities to export (perfect recording!)")
            return None
        
        with open(csv_path, 'w', newline='') as f:
            fieldnames = [
                'timestamp_utc', 'sample_index', 'type',
                'magnitude_samples', 'magnitude_ms',
                'rtp_seq_before', 'rtp_seq_after',
                'rtp_ts_before', 'rtp_ts_after',
                'wwv_validated', 'explanation'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for disc in self.discontinuities:
                writer.writerow({
                    'timestamp_utc': disc.timestamp,
                    'sample_index': disc.sample_index,
                    'type': disc.discontinuity_type.value,
                    'magnitude_samples': disc.magnitude_samples,
                    'magnitude_ms': f"{disc.magnitude_ms:.2f}",
                    'rtp_seq_before': disc.rtp_sequence_before,
                    'rtp_seq_after': disc.rtp_sequence_after,
                    'rtp_ts_before': disc.rtp_timestamp_before,
                    'rtp_ts_after': disc.rtp_timestamp_after,
                    'wwv_validated': disc.wwv_tone_detected,
                    'explanation': disc.explanation
                })
        
        logger.info(f"{self.channel_name}: Exported {len(self.discontinuities)} discontinuities to {csv_path}")
        return csv_path
    
    def generate_daily_summary(self, date_str: str) -> DailyQualitySummary:
        """Generate daily summary from minute metrics"""
        summary = DailyQualitySummary(
            date_utc=date_str,
            channel_name=self.channel_name,
            frequency_hz=self.frequency_hz
        )
        
        if not self.minute_metrics:
            return summary
        
        # Completeness
        summary.minutes_recorded = len(self.minute_metrics)
        summary.minutes_missing = 1440 - summary.minutes_recorded
        summary.data_completeness_percent = (summary.minutes_recorded / 1440) * 100
        
        # Gaps
        summary.total_gaps = sum(m.gaps_count for m in self.minute_metrics)
        summary.total_gap_duration_sec = sum(m.total_gap_duration_ms for m in self.minute_metrics) / 1000
        
        if summary.total_gaps > 0:
            largest_gap_minute = max(self.minute_metrics, key=lambda m: m.largest_gap_ms)
            summary.longest_gap_sec = largest_gap_minute.largest_gap_ms / 1000
            summary.longest_gap_timestamp = largest_gap_minute.minute_start_str
        
        # WWV statistics
        wwv_minutes = [m for m in self.minute_metrics if m.wwv_tone_detected is not None]
        if wwv_minutes:
            summary.wwv_detections_successful = sum(1 for m in wwv_minutes if m.wwv_tone_detected)
            summary.wwv_detection_rate_percent = (
                summary.wwv_detections_successful / len(wwv_minutes) * 100
            )
            
            errors = [m.wwv_timing_error_ms for m in wwv_minutes 
                     if m.wwv_timing_error_ms is not None]
            if errors:
                import numpy as np
                summary.wwv_timing_error_mean_ms = float(np.mean(errors))
                summary.wwv_timing_error_std_ms = float(np.std(errors))
                summary.wwv_timing_error_max_ms = float(np.max(np.abs(errors)))
        
        # RTP statistics
        summary.total_packets_received = sum(m.packets_received for m in self.minute_metrics)
        summary.total_packets_dropped = sum(m.packets_dropped for m in self.minute_metrics)
        total = summary.total_packets_received + summary.total_packets_dropped
        if total > 0:
            summary.packet_loss_percent = (summary.total_packets_dropped / total) * 100
        
        # Signal quality
        powers = [m.signal_mean_power_db for m in self.minute_metrics]
        if powers:
            import numpy as np
            summary.signal_power_mean_db = float(np.mean(powers))
            summary.signal_power_std_db = float(np.std(powers))
        
        return summary
    
    def export_daily_summary(self, date_str: str):
        """Export daily summary to JSON"""
        summary = self.generate_daily_summary(date_str)
        
        json_path = self.output_dir / f"{self.channel_name}_daily_summary_{date_str}.json"
        with open(json_path, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2)
        
        logger.info(f"{self.channel_name}: Exported daily summary to {json_path}")
        logger.info(f"{self.channel_name}: Data completeness: {summary.data_completeness_percent:.2f}%")
        logger.info(f"{self.channel_name}: Packet loss: {summary.packet_loss_percent:.3f}%")
        if summary.wwv_detection_rate_percent > 0:
            logger.info(f"{self.channel_name}: WWV detection rate: {summary.wwv_detection_rate_percent:.1f}%")
            logger.info(f"{self.channel_name}: WWV timing error: {summary.wwv_timing_error_mean_ms:.1f} ± {summary.wwv_timing_error_std_ms:.1f} ms")
        
        return json_path
