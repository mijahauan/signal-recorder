#!/usr/bin/env python3
"""
Core NPZ Archive Writer - Scientific Grade Data Preservation

Writes gap-filled IQ samples with RTP timestamps for precise time reconstruction.
This is the ONLY output of the core recorder - a complete scientific record.
"""

import numpy as np
import logging
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
                 sample_rate: int, ssrc: int, station_config: dict = None):
        """
        Initialize NPZ writer
        
        Args:
            output_dir: Base directory for archives
            channel_name: Channel identifier (e.g., "WWV 2.5 MHz")
            frequency_hz: Center frequency (Hz)
            sample_rate: Sample rate (Hz, should be 16000 for IQ)
            ssrc: RTP SSRC identifier
            station_config: Station metadata (callsign, grid, instrument_id)
        """
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.ssrc = ssrc
        self.station_config = station_config or {}
        
        self.samples_per_minute = sample_rate * 60
        
        # Current minute accumulation
        self.current_minute_samples: List[np.complex64] = []
        self.current_minute_timestamp: Optional[datetime] = None
        self.current_minute_rtp_start: Optional[int] = None
        self.current_minute_gaps: List[GapRecord] = []
        self.current_minute_packets_rx = 0
        self.current_minute_packets_expected = 0
        
        # Statistics
        self.minutes_written = 0
        self.total_samples_written = 0
        self.last_file_written = None
        
        logger.info(f"{channel_name}: CoreNPZWriter initialized")
        logger.info(f"{channel_name}: Sample rate: {sample_rate} Hz, SSRC: {ssrc}")
    
    def add_samples(self, rtp_timestamp: int, samples: np.ndarray, 
                   gap_record: Optional[GapRecord] = None) -> Optional[Tuple[datetime, Path]]:
        """
        Add samples to current minute buffer
        
        Args:
            rtp_timestamp: RTP timestamp of first sample in this batch
            samples: Complex IQ samples
            gap_record: If this batch includes gap-fill, provide gap details
        
        Returns:
            If minute completed: (minute_timestamp, file_path)
            Otherwise: None
        """
        # Determine minute boundary
        # Note: We use RTP timestamp as primary reference, but wall clock for file organization
        wall_clock = datetime.now(tz=timezone.utc)
        minute_boundary = wall_clock.replace(second=0, microsecond=0)
        
        # Check for minute rollover
        completed_minute = None
        if self.current_minute_timestamp is not None and minute_boundary != self.current_minute_timestamp:
            # Minute complete - write it
            if len(self.current_minute_samples) > 0:
                file_path = self._write_minute_file()
                completed_minute = (self.current_minute_timestamp, file_path)
            
            # Reset for new minute
            self._reset_minute_buffer(minute_boundary, rtp_timestamp)
        elif self.current_minute_timestamp is None:
            # First samples
            self._reset_minute_buffer(minute_boundary, rtp_timestamp)
        
        # Record gap if present
        if gap_record:
            self.current_minute_gaps.append(gap_record)
        
        # Add samples to buffer
        self.current_minute_samples.extend(samples)
        self.current_minute_packets_rx += 1
        
        # Check if minute is complete
        if len(self.current_minute_samples) >= self.samples_per_minute:
            # Trim to exactly one minute
            self.current_minute_samples = self.current_minute_samples[:self.samples_per_minute]
            
            # Write file
            file_path = self._write_minute_file()
            completed_minute = (self.current_minute_timestamp, file_path)
            
            # Start new minute
            next_minute = self._calculate_next_minute(minute_boundary)
            next_rtp = rtp_timestamp + self.samples_per_minute
            self._reset_minute_buffer(next_minute, next_rtp)
        
        return completed_minute
    
    def _reset_minute_buffer(self, minute_timestamp: datetime, rtp_start: int):
        """Reset buffer for new minute"""
        self.current_minute_samples = []
        self.current_minute_timestamp = minute_timestamp
        self.current_minute_rtp_start = rtp_start
        self.current_minute_gaps = []
        self.current_minute_packets_rx = 0
        # Expected packets = samples_per_minute / samples_per_packet
        # Assume 320 samples per packet @ 16 kHz
        self.current_minute_packets_expected = self.samples_per_minute // 320
    
    def _calculate_next_minute(self, current: datetime) -> datetime:
        """Calculate next minute boundary"""
        from datetime import timedelta
        next_min = current + timedelta(minutes=1)
        return next_min.replace(second=0, microsecond=0)
    
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
        channel_dir = self.channel_name.replace(' ', '_').replace('.', '')
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
            
            # === METADATA ===
            frequency_hz=self.frequency_hz,              # Center frequency
            channel_name=self.channel_name,              # Channel identifier
            unix_timestamp=self.current_minute_timestamp.timestamp(),  # Wall clock (approximate)
            
            # === QUALITY INDICATORS ===
            gaps_filled=total_gap_samples,               # Total samples filled with zeros
            gaps_count=total_gaps,                       # Number of discontinuities
            packets_received=self.current_minute_packets_rx,    # Actual packets
            packets_expected=self.current_minute_packets_expected,  # Expected packets
            
            # === PROVENANCE ===
            recorder_version="2.0.0-core",               # Core recorder version
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
    
    def flush(self) -> Optional[Path]:
        """Force write current buffer (for graceful shutdown)"""
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
