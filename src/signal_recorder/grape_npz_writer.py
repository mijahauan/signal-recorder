#!/usr/bin/env python3
"""
GRAPE NPZ Writer - SegmentWriter Implementation

Implements the SegmentWriter protocol for GRAPE-specific NPZ archives.
This is the storage layer for GRAPE recordings, handling:
- Complex IQ sample accumulation
- Gap tracking with RTP timestamps
- NPZ file writing with time_snap metadata
- Scientific metadata preservation

Architecture:
    RecordingSession (segmentation) → GrapeNPZWriter (storage) → NPZ files

This replaces the CoreNPZWriter minute-based logic with segment-based
writes that integrate with RecordingSession.
"""

import numpy as np
import logging
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

from .recording_session import SegmentWriter, SegmentInfo
from .packet_resequencer import GapInfo
from .startup_tone_detector import StartupTimeSnap

logger = logging.getLogger(__name__)


@dataclass
class GrapeGapRecord:
    """Record of a gap filled with zeros"""
    rtp_timestamp: int      # RTP timestamp where gap started
    sample_index: int       # Sample index in segment where gap starts
    samples_filled: int     # Number of zero samples inserted
    packets_lost: int       # Number of RTP packets lost


class GrapeNPZWriter:
    """
    GRAPE-specific NPZ writer implementing SegmentWriter protocol.
    
    Writes scientifically complete NPZ archives with:
    - Gap-filled IQ samples (complex64)
    - RTP timestamp of first sample (critical for time reconstruction)
    - time_snap for RTP→UTC conversion
    - Gap statistics (provenance)
    - Tone power measurements (for analytics)
    
    Each segment (typically 60 seconds) becomes one NPZ file.
    """
    
    def __init__(
        self,
        output_dir: Path,
        channel_name: str,
        frequency_hz: float,
        sample_rate: int,
        ssrc: int,
        time_snap: StartupTimeSnap,
        station_config: Optional[Dict[str, Any]] = None,
        get_ntp_status: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        """
        Initialize GRAPE NPZ writer.
        
        Args:
            output_dir: Base directory for archives
            channel_name: Channel identifier (e.g., "WWV 2.5 MHz")
            frequency_hz: Center frequency (Hz)
            sample_rate: Sample rate (Hz, should be 16000 for IQ)
            ssrc: RTP SSRC identifier
            time_snap: Time synchronization anchor
            station_config: Station metadata (callsign, grid, instrument_id)
            get_ntp_status: Callable that returns centralized NTP status dict
        """
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.ssrc = ssrc
        self.time_snap = time_snap
        self.station_config = station_config or {}
        self.get_ntp_status = get_ntp_status
        
        self.samples_per_minute = sample_rate * 60
        
        # Thread safety lock
        self._lock = threading.Lock()
        
        # Pending time_snap (applied at next segment boundary)
        self.pending_time_snap: Optional[StartupTimeSnap] = None
        
        # Current segment state
        self._segment_samples: List[np.complex64] = []
        self._segment_gaps: List[GrapeGapRecord] = []
        self._segment_packets_rx = 0
        self._segment_info: Optional[SegmentInfo] = None
        self._segment_metadata: Dict[str, Any] = {}
        self._segment_rtp_start: Optional[int] = None
        self._segment_wall_clock_start: Optional[float] = None
        
        # Statistics
        self.segments_written = 0
        self.total_samples_written = 0
        self.last_file_written: Optional[Path] = None
        
        logger.info(f"{channel_name}: GrapeNPZWriter initialized")
        logger.info(f"{channel_name}: Sample rate: {sample_rate} Hz, SSRC: {ssrc}")
        logger.info(f"{channel_name}: time_snap: {time_snap.source} (confidence={time_snap.confidence:.2f})")
    
    # === SegmentWriter Protocol Implementation ===
    
    def start_segment(self, segment_info: SegmentInfo, metadata: Dict[str, Any]) -> None:
        """Called when a new segment begins"""
        with self._lock:
            # Apply pending time_snap at segment boundary
            if self.pending_time_snap is not None:
                logger.info(
                    f"{self.channel_name}: Applying pending time_snap at segment boundary "
                    f"(source: {self.time_snap.source} -> {self.pending_time_snap.source})"
                )
                self.time_snap = self.pending_time_snap
                self.pending_time_snap = None
            
            # Reset segment state
            self._segment_samples = []
            self._segment_gaps = []
            self._segment_packets_rx = 0
            self._segment_info = segment_info
            self._segment_metadata = metadata
            self._segment_rtp_start = segment_info.start_rtp_timestamp
            self._segment_wall_clock_start = segment_info.wallclock_start or time.time()
            
            logger.debug(
                f"{self.channel_name}: Segment {segment_info.segment_id} started "
                f"at RTP {segment_info.start_rtp_timestamp}"
            )
    
    def write_samples(
        self,
        samples: np.ndarray,
        rtp_timestamp: int,
        gap_info: Optional[GapInfo] = None
    ) -> None:
        """Called for each batch of samples"""
        with self._lock:
            if self._segment_info is None:
                logger.warning(f"{self.channel_name}: write_samples called without active segment")
                return
            
            # Record gap if present
            if gap_info and gap_info.gap_samples > 0:
                gap_record = GrapeGapRecord(
                    rtp_timestamp=gap_info.expected_timestamp,
                    sample_index=len(self._segment_samples),
                    samples_filled=gap_info.gap_samples,
                    packets_lost=gap_info.gap_packets
                )
                self._segment_gaps.append(gap_record)
            
            # Accumulate samples
            self._segment_samples.extend(samples)
            self._segment_packets_rx += 1
    
    def finish_segment(self, segment_info: SegmentInfo) -> Optional[Path]:
        """Called when segment completes. Returns file path."""
        with self._lock:
            if not self._segment_samples:
                logger.warning(f"{self.channel_name}: finish_segment called with no samples")
                return None
            
            return self._write_segment_file(segment_info)
    
    # === GRAPE-Specific Methods ===
    
    def update_time_snap(self, new_time_snap: StartupTimeSnap) -> None:
        """
        Schedule a time_snap update to be applied at the next segment boundary.
        
        CRITICAL: Never apply time_snap updates mid-segment! This would cause
        phase discontinuities in the RTP→UTC mapping within a single file.
        """
        with self._lock:
            logger.info(
                f"{self.channel_name}: Scheduling time_snap update for next segment boundary "
                f"(source: {self.time_snap.source} -> {new_time_snap.source}, "
                f"confidence: {self.time_snap.confidence:.2f} -> {new_time_snap.confidence:.2f})"
            )
            self.pending_time_snap = new_time_snap
    
    def _calculate_utc_from_rtp(self, rtp_timestamp: int) -> float:
        """
        Calculate UTC timestamp from RTP timestamp using current time_snap.
        
        Handles 32-bit RTP wraparound correctly using signed arithmetic.
        """
        rtp_diff = rtp_timestamp - self.time_snap.rtp_timestamp
        
        # Handle 32-bit wrap-around
        if rtp_diff > 0x80000000:
            rtp_diff -= 0x100000000
        elif rtp_diff < -0x80000000:
            rtp_diff += 0x100000000
        
        elapsed_seconds = rtp_diff / self.time_snap.sample_rate
        return self.time_snap.utc_timestamp + elapsed_seconds
    
    def _get_ntp_offset_cached(self) -> Optional[float]:
        """Get NTP offset from centralized cache (no subprocess calls)."""
        if self.get_ntp_status is None:
            return None
        
        try:
            ntp_status = self.get_ntp_status()
            return ntp_status.get('offset_ms')
        except Exception as e:
            logger.warning(f"{self.channel_name}: Failed to get NTP status: {e}")
            return None
    
    def _write_segment_file(self, segment_info: SegmentInfo) -> Path:
        """Write current segment to NPZ file"""
        # Convert to numpy array
        data = np.array(self._segment_samples, dtype=np.complex64)
        
        # Calculate UTC timestamp for file naming
        utc_timestamp = self._calculate_utc_from_rtp(self._segment_rtp_start)
        minute_boundary = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
        minute_boundary = minute_boundary.replace(second=0, microsecond=0)
        
        # Create directory structure: archives/CHANNEL/
        channel_dir = self.channel_name.replace(' ', '_')
        dir_path = self.output_dir / 'archives' / channel_dir
        dir_path.mkdir(parents=True, exist_ok=True)
        
        # Filename: YYYYMMDDTHHmmSSZ_FREQ_iq.npz
        time_str = minute_boundary.strftime("%Y%m%dT%H%M%SZ")
        freq_str = f"{int(self.frequency_hz)}"
        filename = f"{time_str}_{freq_str}_iq.npz"
        file_path = dir_path / filename
        
        # Calculate gap statistics
        total_gaps = len(self._segment_gaps)
        total_gap_samples = sum(g.samples_filled for g in self._segment_gaps)
        
        # Calculate expected packets
        samples_per_packet = max(1, int(320 * (self.sample_rate / 16000)))
        packets_expected = len(data) // samples_per_packet
        
        # Get NTP offset
        ntp_offset_ms = self._get_ntp_offset_cached()
        
        # Calculate wall clock time at segment start (stable prediction)
        ntp_offset_s = (ntp_offset_ms / 1000.0) if ntp_offset_ms is not None else 0.0
        wall_clock_at_segment = utc_timestamp + ntp_offset_s
        
        # Write NPZ with scientific metadata
        np.savez_compressed(
            file_path,
            
            # === PRIMARY DATA ===
            iq=data,
            
            # === CRITICAL TIMING REFERENCE ===
            rtp_timestamp=self._segment_rtp_start,
            rtp_ssrc=self.ssrc,
            sample_rate=self.sample_rate,
            
            # === TIME_SNAP (EMBEDDED - Self-Contained File) ===
            time_snap_rtp=self.time_snap.rtp_timestamp,
            time_snap_utc=self.time_snap.utc_timestamp,
            time_snap_source=self.time_snap.source,
            time_snap_confidence=self.time_snap.confidence,
            time_snap_station=self.time_snap.station,
            
            # === TONE POWERS (for analytics - avoids re-detection) ===
            tone_power_1000_hz_db=self.time_snap.tone_power_1000_hz_db,
            tone_power_1200_hz_db=self.time_snap.tone_power_1200_hz_db,
            wwvh_differential_delay_ms=self.time_snap.wwvh_differential_delay_ms,
            
            # === METADATA ===
            frequency_hz=self.frequency_hz,
            channel_name=self.channel_name,
            unix_timestamp=minute_boundary.timestamp(),
            ntp_wall_clock_time=wall_clock_at_segment,
            ntp_offset_ms=ntp_offset_ms,
            
            # === QUALITY INDICATORS ===
            gaps_filled=total_gap_samples,
            gaps_count=total_gaps,
            packets_received=self._segment_packets_rx,
            packets_expected=packets_expected,
            
            # === SEGMENT INFO ===
            segment_id=segment_info.segment_id,
            segment_sample_count=segment_info.sample_count,
            
            # === PROVENANCE ===
            recorder_version="3.0.0-refactored",
            created_timestamp=datetime.now(tz=timezone.utc).timestamp(),
            
            # === GAP DETAILS (for scientific provenance) ===
            gap_rtp_timestamps=np.array([g.rtp_timestamp for g in self._segment_gaps], dtype=np.uint32),
            gap_sample_indices=np.array([g.sample_index for g in self._segment_gaps], dtype=np.uint32),
            gap_samples_filled=np.array([g.samples_filled for g in self._segment_gaps], dtype=np.uint32),
            gap_packets_lost=np.array([g.packets_lost for g in self._segment_gaps], dtype=np.uint32)
        )
        
        # Update statistics
        self.segments_written += 1
        self.total_samples_written += len(data)
        self.last_file_written = file_path
        
        # Log completion
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        completeness_pct = 100.0 * (len(data) - total_gap_samples) / len(data) if len(data) > 0 else 0.0
        
        logger.info(
            f"{self.channel_name}: Wrote {filename} "
            f"({len(data)} samples, {file_size_mb:.2f} MB, "
            f"{completeness_pct:.1f}% complete, {total_gaps} gaps)"
        )
        
        return file_path
    
    def flush(self) -> Optional[Path]:
        """Force write current segment (for graceful shutdown)"""
        with self._lock:
            if not self._segment_samples or self._segment_info is None:
                return None
            
            # Pad to expected segment size if needed
            expected_samples = self.samples_per_minute
            current_samples = len(self._segment_samples)
            
            if current_samples < expected_samples:
                samples_needed = expected_samples - current_samples
                
                # Add gap record for padding
                gap = GrapeGapRecord(
                    rtp_timestamp=(self._segment_rtp_start or 0) + current_samples,
                    sample_index=current_samples,
                    samples_filled=samples_needed,
                    packets_lost=0
                )
                self._segment_gaps.append(gap)
                
                # Pad with zeros
                padding = np.zeros(samples_needed, dtype=np.complex64)
                self._segment_samples.extend(padding)
            
            return self._write_segment_file(self._segment_info)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current writer statistics"""
        with self._lock:
            return {
                'segments_written': self.segments_written,
                'total_samples_written': self.total_samples_written,
                'last_file_written': str(self.last_file_written) if self.last_file_written else None,
                'time_snap_source': self.time_snap.source,
                'time_snap_confidence': self.time_snap.confidence,
            }
