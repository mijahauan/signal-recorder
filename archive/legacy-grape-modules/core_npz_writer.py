#!/usr/bin/env python3
"""
Core NPZ Archive Writer - Scientific Grade Data Preservation

Writes gap-filled IQ samples with RTP timestamps for precise time reconstruction.
This is the ONLY output of the core recorder - a complete scientific record.
"""

import numpy as np
import logging
import subprocess
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GapRecord:
    """Record of a gap that was filled with zeros"""
    rtp_timestamp: int      # RTP timestamp where gap started
    sample_index: int       # Sample index in output where gap starts
    samples_filled: int     # Number of zero samples inserted
    packets_lost: int       # Number of RTP packets lost


class CoreNPZWriter:
    """
    Write scientifically complete NPZ archives
    
    Includes:
    - Gap-filled IQ samples (complex64)
    - RTP timestamp of first sample (critical for time reconstruction)
    - Gap statistics (provenance)
    - Packet reception statistics (quality assessment)
    
    Does NOT include:
    - Quality metrics (analytics responsibility)
    - Tone detection results (analytics responsibility)
    - Decimated data (analytics responsibility)
    """
    
    def __init__(self, output_dir: Path, channel_name: str, frequency_hz: float,
                 sample_rate: int, ssrc: int, time_snap: 'StartupTimeSnap', station_config: dict = None,
                 get_ntp_status: callable = None):
        """
        Initialize NPZ writer
        
        Args:
            output_dir: Base directory for archives
            channel_name: Channel identifier (e.g., "WWV 2.5 MHz")
            frequency_hz: Center frequency (Hz)
            sample_rate: Sample rate (Hz, should be 16000 for IQ)
            ssrc: RTP SSRC identifier
            station_config: Station metadata (callsign, grid, instrument_id)
            get_ntp_status: Callable that returns centralized NTP status dict
                           (avoids subprocess calls - performance critical)
        """
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.ssrc = ssrc
        self.station_config = station_config or {}
        self.get_ntp_status = get_ntp_status  # Centralized NTP accessor
        
        self.samples_per_minute = sample_rate * 60
        
        # Thread safety lock (critical for concurrent RTP packet processing)
        self._lock = threading.Lock()
        
        # Time-snap anchors (updated at minute boundaries only)
        self.time_snap = time_snap  # Current active anchor
        self.pending_time_snap = None  # New anchor to apply at next boundary
        
        # Current minute accumulation
        self.current_minute_samples: List[np.complex64] = []
        self.current_minute_timestamp: Optional[datetime] = None
        self.current_minute_rtp_start: Optional[int] = None
        self.current_minute_wall_clock_time: Optional[float] = None  # NTP time when minute detected
        self.current_minute_gaps: List[GapRecord] = []
        self.current_minute_packets_rx = 0
        self.current_minute_packets_expected = 0
        
        # Statistics
        self.minutes_written = 0
        self.total_samples_written = 0
        self.last_file_written = None
        
        logger.info(f"{channel_name}: CoreNPZWriter initialized")
        logger.info(f"{channel_name}: Sample rate: {sample_rate} Hz, SSRC: {ssrc}")
        logger.info(f"{channel_name}: time_snap: {time_snap.source} (confidence={time_snap.confidence:.2f})")
        logger.info(f"{channel_name}: time_snap anchor: RTP={time_snap.rtp_timestamp}, UTC={datetime.fromtimestamp(time_snap.utc_timestamp, timezone.utc).isoformat()}")
    
    def add_samples(self, rtp_timestamp: int, samples: np.ndarray, 
                   gap_record: Optional[GapRecord] = None) -> Optional[Tuple[datetime, Path]]:
        """
        Add samples to minute buffer (thread-safe)
        
        Args:
            rtp_timestamp: RTP timestamp of first sample in this batch
            samples: Complex IQ samples
            gap_record: If this batch includes gap-fill, provide gap details
        
        Returns:
            If minute completed: (minute_timestamp, file_path)
            Otherwise: None
        """
        with self._lock:
            # Initialize minute buffer on first samples
            completed_minute = None
            if self.current_minute_timestamp is None:
                # Calculate UTC timestamp using timing hierarchy
                utc_timestamp = self._calculate_utc_from_rtp(rtp_timestamp)
                minute_boundary = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc).replace(second=0, microsecond=0)
                # Calculate RTP at minute boundary (round down to boundary)
                rtp_at_boundary = rtp_timestamp - int((utc_timestamp % 60) * self.sample_rate)
                self._reset_minute_buffer(minute_boundary, rtp_at_boundary, rtp_timestamp)
            
            # Record gap if present
            if gap_record:
                self.current_minute_gaps.append(gap_record)
            
            # Add samples to buffer
            self.current_minute_samples.extend(samples)
            self.current_minute_packets_rx += 1
            
            # Check if minute is complete (ONLY completion trigger)
            if len(self.current_minute_samples) >= self.samples_per_minute:
                # Trim to exactly one minute
                self.current_minute_samples = self.current_minute_samples[:self.samples_per_minute]
                
                # Write file with CURRENT time_snap
                file_path = self._write_minute_file()
                completed_minute = (self.current_minute_timestamp, file_path)
                
                # CRITICAL: Apply pending time_snap ONLY at minute boundary
                # This prevents phase discontinuities mid-file
                if self.pending_time_snap is not None:
                    logger.info(
                        f"{self.channel_name}: Applying pending time_snap at minute boundary "
                        f"(source: {self.time_snap.source} -> {self.pending_time_snap.source}, "
                        f"confidence: {self.time_snap.confidence:.2f} -> {self.pending_time_snap.confidence:.2f})"
                    )
                    self.time_snap = self.pending_time_snap
                    self.pending_time_snap = None
                
                # Start new minute - calculate UTC from RTP for next file
                next_rtp = self.current_minute_rtp_start + self.samples_per_minute
                next_utc = self._calculate_utc_from_rtp(next_rtp)
                next_minute = datetime.fromtimestamp(next_utc, tz=timezone.utc).replace(second=0, microsecond=0)
                
                # STABLE WALL CLOCK PREDICTION
                # Instead of capturing jittery time.time() at packet arrival, we PREDICT
                # the wall clock at the minute boundary using the stable RTP-derived time
                # plus the NTP offset. This gives a phase-aligned reference.
                #
                # next_utc = RTP-derived UTC at minute boundary (stable, from tone-snap)
                # ntp_offset = difference between system clock and NTP (typically <1ms)
                # predicted_wall_clock = next_utc + ntp_offset
                #
                # This ensures ntp_wall_clock_time metadata is stable and phase-aligned
                # with the RTP-derived unix_timestamp, so drift measurements reflect
                # true hardware clock stability, not network/OS jitter.
                ntp_offset_ms = self._get_ntp_offset_cached()
                ntp_offset_s = (ntp_offset_ms / 1000.0) if ntp_offset_ms is not None else 0.0
                predicted_wall_clock = next_utc + ntp_offset_s
                
                self._reset_minute_buffer_with_wall_clock(next_minute, next_rtp, predicted_wall_clock)
            
            return completed_minute

    def update_time_snap(self, new_time_snap: 'StartupTimeSnap'):
        """
        Schedule a time_snap update to be applied at the next minute boundary.
        
        CRITICAL: Never apply time_snap updates mid-file! This would cause
        phase discontinuities in the RTP->UTC mapping within a single minute.
        
        The pending time_snap is applied in add_samples() after writing the
        completed minute file and before starting the next minute.

        Args:
            new_time_snap: The new StartupTimeSnap object to apply at next boundary.
        """
        with self._lock:
            logger.info(
                f"{self.channel_name}: Scheduling time_snap update for next minute boundary "
                f"(source: {self.time_snap.source} -> {new_time_snap.source}, "
                f"confidence: {self.time_snap.confidence:.2f} -> {new_time_snap.confidence:.2f})"
            )
            self.pending_time_snap = new_time_snap
    
    def _reset_minute_buffer(self, minute_timestamp: datetime, rtp_start: int, current_rtp: int):
        """
        Reset buffer for new minute (used for first minute initialization)
        
        Uses stable wall clock prediction based on RTP-derived time + NTP offset,
        rather than jittery time.time() capture at packet arrival.
        
        This ensures the ntp_wall_clock_time metadata is phase-aligned with the
        RTP-derived unix_timestamp from the start.
        """
        self.current_minute_samples = []
        self.current_minute_timestamp = minute_timestamp
        self.current_minute_rtp_start = rtp_start
        
        # STABLE WALL CLOCK PREDICTION for first minute
        # Calculate the RTP-derived UTC at the minute boundary, then add NTP offset
        minute_utc = self._calculate_utc_from_rtp(rtp_start)
        ntp_offset_ms = self._get_ntp_offset_cached()
        ntp_offset_s = (ntp_offset_ms / 1000.0) if ntp_offset_ms is not None else 0.0
        self.current_minute_wall_clock_time = minute_utc + ntp_offset_s
        
        self.current_minute_gaps = []
        self.current_minute_packets_rx = 0
        # Expected packets = samples_per_minute / samples_per_packet
        # samples_per_packet scales with sample rate (320 @ 16 kHz, 4 @ 200 Hz, etc.)
        samples_per_packet = max(1, int(320 * (self.sample_rate / 16000)))
        self.current_minute_packets_expected = self.samples_per_minute // samples_per_packet
    
    def _reset_minute_buffer_with_wall_clock(self, minute_timestamp: datetime, rtp_start: int, 
                                              wall_clock_time: float):
        """
        Reset buffer for new minute with predicted wall clock time.
        
        Used when transitioning between minutes. The wall_clock_time is the
        PREDICTED wall clock at the minute boundary, calculated as:
            predicted_wall_clock = rtp_derived_utc + ntp_offset
        
        This gives a stable, phase-aligned reference that eliminates
        network/OS jitter from the timing measurements.
        
        Args:
            minute_timestamp: The minute boundary (datetime)
            rtp_start: RTP timestamp at minute boundary
            wall_clock_time: Predicted wall clock at minute boundary
        """
        self.current_minute_samples = []
        self.current_minute_timestamp = minute_timestamp
        self.current_minute_rtp_start = rtp_start
        self.current_minute_wall_clock_time = wall_clock_time
        
        self.current_minute_gaps = []
        self.current_minute_packets_rx = 0
        samples_per_packet = max(1, int(320 * (self.sample_rate / 16000)))
        self.current_minute_packets_expected = self.samples_per_minute // samples_per_packet
    
    def _calculate_utc_from_rtp(self, rtp_timestamp: int) -> float:
        """
        Calculate UTC timestamp from RTP timestamp using current time_snap.
        
        Handles 32-bit RTP wraparound correctly using signed arithmetic.
        RTP wraps at 2^32 samples, which is ~74 hours at 16kHz.
        
        Formula: utc = time_snap_utc + (rtp - time_snap_rtp) / sample_rate
        
        Returns:
            UTC timestamp (seconds since epoch)
        """
        # Calculate difference using Python's natural signed arithmetic
        rtp_diff = rtp_timestamp - self.time_snap.rtp_timestamp
        
        # Check for 32-bit wrap-around and correct
        # If difference is very large positive (>2^31), we missed a wrap (went backwards)
        if rtp_diff > 0x80000000:
            rtp_diff -= 0x100000000
        # If difference is very large negative (<-2^31), false wrap (actually forward)
        elif rtp_diff < -0x80000000:
            rtp_diff += 0x100000000
        
        # Convert samples to seconds using sample rate from time_snap
        elapsed_seconds = rtp_diff / self.time_snap.sample_rate
        utc = self.time_snap.utc_timestamp + elapsed_seconds
        
        return utc
    
    def _write_minute_file(self) -> Path:
        """Write current minute buffer to NPZ file"""
        if not self.current_minute_timestamp:
            raise ValueError("No current minute timestamp")
        if not self.current_minute_rtp_start:
            raise ValueError("No RTP timestamp for minute start")
        
        # Convert to numpy array
        data = np.array(self.current_minute_samples, dtype=np.complex64)
        
        # Create directory structure: archives/CHANNEL/
        # Simple structure for dual-service architecture compatibility
        # Preserve dots in channel names (WWV 2.5 MHz -> WWV_2.5_MHz)
        channel_dir = self.channel_name.replace(' ', '_')
        dir_path = self.output_dir / 'archives' / channel_dir
        dir_path.mkdir(parents=True, exist_ok=True)
        
        # Filename: YYYYMMDDTHHmmSSZ_FREQ_iq.npz
        time_str = self.current_minute_timestamp.strftime("%Y%m%dT%H%M%SZ")
        freq_str = f"{int(self.frequency_hz)}"
        filename = f"{time_str}_{freq_str}_iq.npz"
        file_path = dir_path / filename
        
        # Calculate gap statistics
        total_gaps = len(self.current_minute_gaps)
        total_gap_samples = sum(g.samples_filled for g in self.current_minute_gaps)
        
        # Write NPZ with scientific metadata
        np.savez_compressed(
            file_path,
            
            # === PRIMARY DATA ===
            iq=data,                                    # Complex IQ samples
            
            # === CRITICAL TIMING REFERENCE ===
            rtp_timestamp=self.current_minute_rtp_start,  # RTP timestamp of iq[0]
            rtp_ssrc=self.ssrc,                          # RTP stream ID
            sample_rate=self.sample_rate,                # Sample rate (Hz)
            
            # === TIME_SNAP (EMBEDDED - Self-Contained File) ===
            time_snap_rtp=self.time_snap.rtp_timestamp,    # RTP at time anchor
            time_snap_utc=self.time_snap.utc_timestamp,    # UTC at time anchor
            time_snap_source=self.time_snap.source,        # How established (wwv_startup, ntp, etc.)
            time_snap_confidence=self.time_snap.confidence,  # Confidence 0-1
            time_snap_station=self.time_snap.station,      # Station or method (WWV, CHU, NTP)
            
            # === TONE POWERS (for analytics - avoids re-detection) ===
            tone_power_1000_hz_db=self.time_snap.tone_power_1000_hz_db,  # WWV/CHU 1000 Hz
            tone_power_1200_hz_db=self.time_snap.tone_power_1200_hz_db,  # WWVH 1200 Hz
            wwvh_differential_delay_ms=self.time_snap.wwvh_differential_delay_ms,  # WWVH-WWV propagation delay
            
            # === METADATA ===
            frequency_hz=self.frequency_hz,              # Center frequency
            channel_name=self.channel_name,              # Channel identifier
            unix_timestamp=self.current_minute_timestamp.timestamp(),  # File timestamp (RTP-derived)
            ntp_wall_clock_time=self.current_minute_wall_clock_time,  # Wall clock when minute detected (independent)
            ntp_offset_ms=self._get_ntp_offset_cached(),  # NTP offset from centralized cache
            
            # === QUALITY INDICATORS ===
            gaps_filled=total_gap_samples,               # Total samples filled with zeros
            gaps_count=total_gaps,                       # Number of discontinuities
            packets_received=self.current_minute_packets_rx,    # Actual packets
            packets_expected=self.current_minute_packets_expected,  # Expected packets
            
            # === PROVENANCE ===
            recorder_version="2.0.0-core-timesnap",      # Core recorder version
            created_timestamp=datetime.now(tz=timezone.utc).timestamp(),  # File creation
            
            # === GAP DETAILS (for scientific provenance) ===
            gap_rtp_timestamps=np.array([g.rtp_timestamp for g in self.current_minute_gaps], dtype=np.uint32),
            gap_sample_indices=np.array([g.sample_index for g in self.current_minute_gaps], dtype=np.uint32),
            gap_samples_filled=np.array([g.samples_filled for g in self.current_minute_gaps], dtype=np.uint32),
            gap_packets_lost=np.array([g.packets_lost for g in self.current_minute_gaps], dtype=np.uint32)
        )
        
        # Update statistics
        self.minutes_written += 1
        self.total_samples_written += len(data)
        self.last_file_written = file_path  # Track for status reporting
        
        # Log completion
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        completeness_pct = 100.0 * (len(data) - total_gap_samples) / len(data) if len(data) > 0 else 0.0
        
        logger.info(
            f"{self.channel_name}: Wrote {filename} "
            f"({len(data)} samples, {file_size_mb:.2f} MB, "
            f"{completeness_pct:.1f}% complete, {total_gaps} gaps)"
        )
        
        return file_path
    
    def _get_ntp_offset_cached(self) -> Optional[float]:
        """
        Get NTP offset from centralized cache (no subprocess calls).
        
        This eliminates the performance bottleneck of calling subprocess
        for every minute file written.
        
        Returns:
            NTP offset in ms (positive = system ahead of NTP)
            None if NTP not available or get_ntp_status not provided
        """
        if self.get_ntp_status is None:
            # Fallback for testing or when CoreRecorder not available
            return None
        
        try:
            ntp_status = self.get_ntp_status()
            return ntp_status.get('offset_ms')
        except Exception as e:
            logger.warning(f"{self.channel_name}: Failed to get NTP status: {e}")
            return None
    
    def flush(self) -> Optional[Path]:
        """Force write current buffer (for graceful shutdown) - thread-safe"""
        with self._lock:
            if len(self.current_minute_samples) == 0:
                return None
            
            # Pad to full minute if needed
            samples_needed = self.samples_per_minute - len(self.current_minute_samples)
            if samples_needed > 0:
                # Add gap record for padding
                gap = GapRecord(
                    rtp_timestamp=self.current_minute_rtp_start + len(self.current_minute_samples),
                    sample_index=len(self.current_minute_samples),
                    samples_filled=samples_needed,
                    packets_lost=0  # Unknown - shutdown gap
                )
                self.current_minute_gaps.append(gap)
                
                # Pad with zeros
                padding = np.zeros(samples_needed, dtype=np.complex64)
                self.current_minute_samples.extend(padding)
            
            return self._write_minute_file()
