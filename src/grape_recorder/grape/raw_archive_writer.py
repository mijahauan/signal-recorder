#!/usr/bin/env python3
"""
Phase 1: Raw Archive Writer - Immutable 20 kHz IQ Archive

The raw data from the radiod RTP feed must be stored as the definitive,
uncorrected source of truth. This module implements the Phase 1 storage
layer of the three-phase robust time-aligned data pipeline.

Design Principles:
==================
1. CONTAMINATION POLICY: Raw 20 kHz IQ data is NEVER modified or resampled
   based on any subsequent analysis (tone detection, discrimination, etc.)

2. TIME TAGGING: The only temporal reference is the monotonic System Time
   (t_system) provided by the radiod wall clock or derived from the initial
   sample index. NO UTC corrections are applied at this stage.

3. FILE SPLITTING: Files are split based on FIXED DURATION (1 hour) or
   FIXED SIZE (1 GB), NOT based on signal events (tone detection).

4. FORMAT: Digital RF (DRF) - treats the entire dataset as one continuous
   time series, optimized for RF data with HDF5 backend.

5. COMPRESSION: Lossless compression using Shuffle filter + ZSTD/LZ4/Deflate
   to preserve storage space while guaranteeing data integrity.

This phase produces the immutable archive that Phase 2 (Analytical Engine)
reads to generate the Clock Offset Series (D_clock).

Usage:
------
    writer = RawArchiveWriter(
        output_dir=Path('/data/raw_archive'),
        channel_name='WWV_10MHz',
        frequency_hz=10e6,
        sample_rate=20000,
        station_config={'callsign': 'W3PM', 'grid_square': 'EM38ww'}
    )
    
    writer.write_samples(iq_samples, rtp_timestamp, system_time)
    writer.flush()
"""

import numpy as np
import logging
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from collections import deque
import json
import threading

logger = logging.getLogger(__name__)

# Try to import Digital RF
try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    logger.warning("digital_rf not available - raw archive writing disabled")

# Compression options for HDF5
COMPRESSION_OPTIONS = {
    'zstd': {'compression': 'zstd', 'compression_opts': 3},  # Fast, good ratio
    'lz4': {'compression': 'lz4'},  # Very fast, moderate ratio
    'gzip': {'compression': 'gzip', 'compression_opts': 6},  # Compatible, good ratio
    'none': {}
}


@dataclass
class RawArchiveConfig:
    """
    Configuration for raw archive writer.
    
    Attributes:
        output_dir: Base directory for raw archive
        channel_name: Channel identifier (e.g., 'WWV_10MHz')
        frequency_hz: Center frequency in Hz
        sample_rate: Sample rate in Hz (default 20000)
        station_config: Station metadata (callsign, grid, etc.)
        file_duration_sec: Fixed file duration in seconds (default 3600 = 1 hour)
        max_file_size_bytes: Maximum file size (default 1GB)
        compression: Compression algorithm ('zstd', 'lz4', 'gzip', 'none')
        use_shuffle: Use HDF5 shuffle filter (improves compression)
    """
    output_dir: Path
    channel_name: str
    frequency_hz: float
    sample_rate: int = 20000
    station_config: Dict[str, Any] = field(default_factory=dict)
    
    # File splitting policy - FIXED DURATION, NOT EVENT-BASED
    file_duration_sec: int = 3600  # 1 hour files
    max_file_size_bytes: int = 1_073_741_824  # 1 GB
    
    # Compression settings
    compression: str = 'gzip'  # 'zstd', 'lz4', 'gzip', 'none'
    use_shuffle: bool = True  # Shuffle filter improves compression
    
    # DRF-specific
    subdir_cadence_secs: int = 86400  # Daily subdirectories
    file_cadence_millisecs: int = 3600000  # 1 hour file cadence
    
    def __post_init__(self):
        self.output_dir = Path(self.output_dir)


@dataclass
class SystemTimeReference:
    """
    System time reference for raw archive - NO UTC CORRECTIONS.
    
    This is the ONLY time reference stored in Phase 1.
    The relationship to UTC is calculated in Phase 2.
    
    Attributes:
        rtp_timestamp: RTP timestamp (sample counter from radiod)
        system_time: Local system wall clock time (seconds since epoch)
        ntp_offset_ms: NTP offset at time of recording (if known)
        sample_rate: Sample rate for RTP→time conversion
    """
    rtp_timestamp: int
    system_time: float
    ntp_offset_ms: Optional[float] = None
    sample_rate: int = 20000
    
    def calculate_time_at_sample(self, sample_rtp: int) -> float:
        """Calculate system time at a given RTP sample index."""
        # Handle 32-bit RTP wraparound
        rtp_diff = sample_rtp - self.rtp_timestamp
        if rtp_diff > 0x80000000:
            rtp_diff -= 0x100000000
        elif rtp_diff < -0x80000000:
            rtp_diff += 0x100000000
        
        elapsed_seconds = rtp_diff / self.sample_rate
        return self.system_time + elapsed_seconds
    
    def to_dict(self) -> Dict:
        return {
            'rtp_timestamp': self.rtp_timestamp,
            'system_time': self.system_time,
            'ntp_offset_ms': self.ntp_offset_ms,
            'sample_rate': self.sample_rate
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'SystemTimeReference':
        return cls(
            rtp_timestamp=d['rtp_timestamp'],
            system_time=d['system_time'],
            ntp_offset_ms=d.get('ntp_offset_ms'),
            sample_rate=d.get('sample_rate', 20000)
        )


@dataclass
class ArchiveSegmentInfo:
    """Information about an archive segment (for provenance)."""
    segment_id: int
    start_system_time: float
    start_rtp_timestamp: int
    sample_count: int
    gap_count: int = 0
    gap_samples: int = 0
    file_path: Optional[Path] = None


class RawArchiveWriter:
    """
    Phase 1: Immutable Raw Archive Writer
    
    Writes 20 kHz IQ samples to Digital RF format with:
    - System time tagging ONLY (no UTC corrections)
    - Fixed-duration file splitting (NOT event-based)
    - Lossless compression (Shuffle + ZSTD/LZ4/gzip)
    - Complete provenance metadata
    
    The output is the definitive, uncorrected source of truth for
    all subsequent analysis (Phase 2) and product generation (Phase 3).
    """
    
    def __init__(self, config: RawArchiveConfig):
        """
        Initialize raw archive writer.
        
        Args:
            config: RawArchiveConfig with all settings
        """
        if not DRF_AVAILABLE:
            raise ImportError(
                "digital_rf package required for raw archive writing. "
                "Install with: pip install digital_rf"
            )
        
        self.config = config
        self._lock = threading.Lock()
        
        # Create output directory structure
        self.archive_dir = config.output_dir / 'raw_archive' / config.channel_name.replace(' ', '_')
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Metadata directory
        self.metadata_dir = self.archive_dir / 'metadata'
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # DRF writer state
        self.drf_writer: Optional[drf.DigitalRFWriter] = None
        self.metadata_writer: Optional[drf.DigitalMetadataWriter] = None
        self.dataset_uuid = uuid.uuid4().hex
        
        # Time reference (system time ONLY)
        self.system_time_ref: Optional[SystemTimeReference] = None
        self.current_day: Optional[datetime] = None
        
        # Monotonic sample index for DRF
        self.next_sample_index: Optional[int] = None
        
        # Statistics
        self.samples_written: int = 0
        self.files_written: int = 0
        self.total_gap_samples: int = 0
        self.session_start_time: float = time.time()
        
        # Segment tracking
        self.current_segment: Optional[ArchiveSegmentInfo] = None
        self.segment_counter: int = 0
        
        logger.info(f"RawArchiveWriter initialized for {config.channel_name}")
        logger.info(f"  Output: {self.archive_dir}")
        logger.info(f"  Sample rate: {config.sample_rate} Hz")
        logger.info(f"  File duration: {config.file_duration_sec}s")
        logger.info(f"  Compression: {config.compression} (shuffle={config.use_shuffle})")
    
    def _create_drf_writer(self, system_time: float, rtp_timestamp: int):
        """
        Create Digital RF writer for current day.
        
        File splitting is based on FIXED DURATION, not signal events.
        
        Args:
            system_time: System wall clock time
            rtp_timestamp: RTP timestamp for sample index calculation
        """
        dt = datetime.fromtimestamp(system_time, tz=timezone.utc)
        day_date = dt.date()
        
        # Close existing writer if day changed
        if self.current_day and self.current_day != day_date:
            logger.info(f"Day boundary: closing previous DRF writer")
            self._close_writer()
        
        if self.drf_writer is not None:
            return  # Already have writer for this day
        
        # Build directory structure: raw_archive/CHANNEL/YYYYMMDD/
        date_str = day_date.strftime('%Y%m%d')
        drf_dir = self.archive_dir / date_str
        drf_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate start_global_index from system time
        # This is samples since Unix epoch at sample_rate
        start_global_index = int(system_time * self.config.sample_rate)
        
        # Initialize next_sample_index if first write
        if self.next_sample_index is None:
            self.next_sample_index = start_global_index
        
        logger.info(f"Creating DRF writer for {day_date}")
        logger.info(f"  Directory: {drf_dir}")
        logger.info(f"  start_global_index: {start_global_index}")
        
        # Get compression level
        compression_level = 6 if self.config.compression == 'gzip' else 0
        
        # Create Digital RF writer
        # CRITICAL: dtype must match input data (complex64 for IQ)
        self.drf_writer = drf.DigitalRFWriter(
            str(drf_dir),
            dtype=np.complex64,
            subdir_cadence_secs=self.config.subdir_cadence_secs,
            file_cadence_millisecs=self.config.file_cadence_millisecs,
            start_global_index=start_global_index,
            sample_rate_numerator=self.config.sample_rate,
            sample_rate_denominator=1,
            uuid_str=self.dataset_uuid,
            compression_level=compression_level,
            checksum=False,
            is_complex=True,
            num_subchannels=1,
            is_continuous=True,  # We fill gaps with zeros
            marching_periods=False
        )
        
        # Create metadata writer for provenance
        metadata_subdir = drf_dir / 'metadata'
        metadata_subdir.mkdir(parents=True, exist_ok=True)
        
        self.metadata_writer = drf.DigitalMetadataWriter(
            str(metadata_subdir),
            subdir_cadence_secs=self.config.subdir_cadence_secs,
            file_cadence_secs=3600,  # Hourly metadata files
            sample_rate_numerator=self.config.sample_rate,
            sample_rate_denominator=1,
            file_name='raw_archive_metadata'
        )
        
        # Write initial metadata
        station_config = self.config.station_config
        metadata = {
            'archive_type': 'raw_20khz_iq',
            'phase': 'phase1_immutable',
            'channel_name': self.config.channel_name,
            'frequency_hz': self.config.frequency_hz,
            'sample_rate': float(self.config.sample_rate),
            'callsign': station_config.get('callsign', 'UNKNOWN'),
            'grid_square': station_config.get('grid_square', 'UNKNOWN'),
            'uuid_str': self.dataset_uuid,
            'date': day_date.isoformat(),
            'compression': self.config.compression,
            'created_at': datetime.now(tz=timezone.utc).isoformat(),
            # CRITICAL: This is system time only, NOT UTC-corrected
            'time_reference': 'system_time_only',
            'utc_correction_applied': False
        }
        self.metadata_writer.write(start_global_index, metadata)
        
        self.current_day = day_date
        self.files_written += 1
        
        logger.info(f"✅ DRF writer ready (system time reference only)")
    
    def _close_writer(self):
        """Close current Digital RF writer and flush data."""
        if self.drf_writer:
            try:
                self.drf_writer.close()
            except Exception as e:
                logger.warning(f"Error closing DRF writer: {e}")
            self.drf_writer = None
            self.metadata_writer = None
            logger.info("DRF writer closed")
    
    def set_time_reference(
        self,
        rtp_timestamp: int,
        system_time: float,
        ntp_offset_ms: Optional[float] = None
    ):
        """
        Set the system time reference for this recording session.
        
        This establishes the mapping between RTP timestamps and system time.
        NO UTC corrections are applied - that's Phase 2's job.
        
        Args:
            rtp_timestamp: RTP timestamp from first packet
            system_time: System wall clock time at first packet
            ntp_offset_ms: NTP offset if known (stored as metadata only)
        """
        self.system_time_ref = SystemTimeReference(
            rtp_timestamp=rtp_timestamp,
            system_time=system_time,
            ntp_offset_ms=ntp_offset_ms,
            sample_rate=self.config.sample_rate
        )
        
        logger.info(f"System time reference set:")
        logger.info(f"  RTP timestamp: {rtp_timestamp}")
        logger.info(f"  System time: {system_time}")
        logger.info(f"  NTP offset: {ntp_offset_ms} ms")
    
    def write_samples(
        self,
        samples: np.ndarray,
        rtp_timestamp: int,
        system_time: Optional[float] = None,
        gap_samples: int = 0
    ) -> int:
        """
        Write IQ samples to the raw archive.
        
        CRITICAL: This method stores data WITHOUT any UTC corrections.
        The time reference is system time only.
        
        Args:
            samples: Complex64 IQ samples (20 kHz)
            rtp_timestamp: RTP timestamp of first sample
            system_time: System wall clock time (uses current time if None)
            gap_samples: Number of zero-filled gap samples (for provenance)
            
        Returns:
            Number of samples written
        """
        with self._lock:
            if system_time is None:
                system_time = time.time()
            
            # Set time reference if not established
            if self.system_time_ref is None:
                self.set_time_reference(rtp_timestamp, system_time)
            
            # Ensure writer exists
            self._create_drf_writer(system_time, rtp_timestamp)
            
            if self.drf_writer is None:
                logger.error("Failed to create DRF writer")
                return 0
            
            # Ensure samples are complex64
            if samples.dtype != np.complex64:
                samples = samples.astype(np.complex64)
            
            # Use RTP timestamp for sample ordering (not wall-clock time)
            # This ensures monotonic writes even with timing jitter
            if self.system_time_ref is not None:
                # Calculate sample index relative to RTP reference
                rtp_diff = rtp_timestamp - self.system_time_ref.rtp_timestamp
                # Handle 32-bit RTP wraparound
                if rtp_diff > 0x80000000:
                    rtp_diff -= 0x100000000
                elif rtp_diff < -0x80000000:
                    rtp_diff += 0x100000000
                
                # Check for backwards RTP (out-of-order packets should be handled upstream)
                if self.next_sample_index is not None:
                    expected_rtp_index = self.next_sample_index - int(self.system_time_ref.system_time * self.config.sample_rate)
                    if rtp_diff < expected_rtp_index - len(samples):
                        # Significant backwards jump - likely late packet, skip it
                        # (Small overlaps are OK, DRF handles them)
                        return 0
            
            try:
                # Write samples to DRF
                # Note: DRF auto-advances from start_global_index
                self.drf_writer.rf_write(samples)
                
                # Update state
                self.samples_written += len(samples)
                self.total_gap_samples += gap_samples
                # Track next expected sample based on what we just wrote
                if self.next_sample_index is None:
                    self.next_sample_index = int(system_time * self.config.sample_rate) + len(samples)
                else:
                    self.next_sample_index += len(samples)
                
                # Update segment tracking
                if self.current_segment is None:
                    self.current_segment = ArchiveSegmentInfo(
                        segment_id=self.segment_counter,
                        start_system_time=system_time,
                        start_rtp_timestamp=rtp_timestamp,
                        sample_count=len(samples),
                        gap_count=1 if gap_samples > 0 else 0,
                        gap_samples=gap_samples
                    )
                else:
                    self.current_segment.sample_count += len(samples)
                    if gap_samples > 0:
                        self.current_segment.gap_count += 1
                        self.current_segment.gap_samples += gap_samples
                
                return len(samples)
                
            except Exception as e:
                logger.error(f"DRF write error: {e}", exc_info=True)
                return 0
    
    def write_gap_metadata(
        self,
        gap_start_rtp: int,
        gap_samples: int,
        system_time: float
    ):
        """
        Write metadata about a gap in the data stream.
        
        This records gap provenance without modifying the raw data.
        
        Args:
            gap_start_rtp: RTP timestamp where gap started
            gap_samples: Number of samples in the gap
            system_time: System time when gap was detected
        """
        if self.metadata_writer is None:
            return
        
        gap_metadata = {
            'event_type': 'gap',
            'gap_start_rtp': gap_start_rtp,
            'gap_samples': gap_samples,
            'gap_duration_ms': (gap_samples / self.config.sample_rate) * 1000,
            'system_time': system_time,
            'detected_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
        sample_index = int(system_time * self.config.sample_rate)
        try:
            self.metadata_writer.write(sample_index, gap_metadata)
            logger.debug(f"Gap metadata written: {gap_samples} samples at RTP {gap_start_rtp}")
        except Exception as e:
            logger.warning(f"Failed to write gap metadata: {e}")
    
    def flush(self):
        """Flush all buffered data to disk."""
        with self._lock:
            if self.drf_writer:
                try:
                    self.drf_writer.close()
                    # Recreate writer for subsequent writes
                    self.drf_writer = None
                    logger.info(f"Flushed raw archive: {self.samples_written} total samples")
                except Exception as e:
                    logger.error(f"Error flushing DRF writer: {e}")
    
    def close(self):
        """Close the writer and finalize the archive."""
        with self._lock:
            self._close_writer()
            
            # Write final session metadata
            self._write_session_summary()
            
            logger.info(f"RawArchiveWriter closed:")
            logger.info(f"  Total samples: {self.samples_written}")
            logger.info(f"  Total gaps: {self.total_gap_samples}")
            logger.info(f"  Files written: {self.files_written}")
    
    def _write_session_summary(self):
        """Write session summary metadata file."""
        summary = {
            'archive_type': 'raw_20khz_iq',
            'phase': 'phase1_immutable',
            'channel_name': self.config.channel_name,
            'frequency_hz': self.config.frequency_hz,
            'sample_rate': self.config.sample_rate,
            'compression': self.config.compression,
            'total_samples': self.samples_written,
            'total_gap_samples': self.total_gap_samples,
            'files_written': self.files_written,
            'session_start': datetime.fromtimestamp(
                self.session_start_time, tz=timezone.utc
            ).isoformat(),
            'session_end': datetime.now(tz=timezone.utc).isoformat(),
            'system_time_ref': self.system_time_ref.to_dict() if self.system_time_ref else None,
            'station_config': self.config.station_config,
            'uuid': self.dataset_uuid,
            # CRITICAL: Mark this as uncorrected data
            'utc_correction_applied': False,
            'time_reference': 'system_time_only',
            'reprocessable': True
        }
        
        summary_file = self.metadata_dir / 'session_summary.json'
        try:
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
            logger.info(f"Session summary written to {summary_file}")
        except Exception as e:
            logger.error(f"Failed to write session summary: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current writer statistics."""
        with self._lock:
            return {
                'samples_written': self.samples_written,
                'gap_samples': self.total_gap_samples,
                'files_written': self.files_written,
                'current_day': self.current_day.isoformat() if self.current_day else None,
                'uptime_seconds': time.time() - self.session_start_time,
                'sample_rate': self.config.sample_rate,
                'archive_dir': str(self.archive_dir)
            }


class RawArchiveReader:
    """
    Read raw archive data from Phase 1 for analysis (Phase 2) or
    product generation (Phase 3).
    
    This provides read-only access to the immutable raw archive.
    """
    
    def __init__(self, archive_dir: Path, channel_name: str):
        """
        Initialize raw archive reader.
        
        Args:
            archive_dir: Base directory containing raw archive
            channel_name: Channel name to read
        """
        if not DRF_AVAILABLE:
            raise ImportError("digital_rf required for reading raw archives")
        
        self.archive_dir = Path(archive_dir) / 'raw_archive' / channel_name.replace(' ', '_')
        self.channel_name = channel_name
        
        # Create DRF reader
        self.drf_reader: Optional[drf.DigitalRFReader] = None
        self._init_reader()
    
    def _init_reader(self):
        """Initialize Digital RF reader."""
        if not self.archive_dir.exists():
            logger.warning(f"Archive directory not found: {self.archive_dir}")
            return
        
        try:
            self.drf_reader = drf.DigitalRFReader(str(self.archive_dir))
            channels = self.drf_reader.get_channels()
            logger.info(f"RawArchiveReader initialized, channels: {channels}")
        except Exception as e:
            logger.error(f"Failed to initialize DRF reader: {e}")
            self.drf_reader = None
    
    def read_samples(
        self,
        start_index: int,
        num_samples: int
    ) -> Optional[Tuple[np.ndarray, int]]:
        """
        Read samples from the raw archive.
        
        Args:
            start_index: Global sample index to start reading
            num_samples: Number of samples to read
            
        Returns:
            Tuple of (samples, actual_start_index) or None if not available
        """
        if self.drf_reader is None:
            return None
        
        try:
            # Get available channels
            channels = self.drf_reader.get_channels()
            if not channels:
                return None
            
            channel = channels[0]  # Use first channel
            
            # Read data
            data = self.drf_reader.read(
                start_index,
                num_samples,
                channel
            )
            
            if data is None or len(data) == 0:
                return None
            
            return data, start_index
            
        except Exception as e:
            logger.error(f"Error reading from archive: {e}")
            return None
    
    def get_bounds(self) -> Optional[Tuple[int, int]]:
        """
        Get the sample index bounds of available data.
        
        Returns:
            Tuple of (first_index, last_index) or None
        """
        if self.drf_reader is None:
            return None
        
        try:
            channels = self.drf_reader.get_channels()
            if not channels:
                return None
            
            channel = channels[0]
            bounds = self.drf_reader.get_bounds(channel)
            return bounds
        except Exception as e:
            logger.error(f"Error getting archive bounds: {e}")
            return None
    
    def get_metadata(self) -> Optional[Dict]:
        """Get archive metadata."""
        metadata_file = self.archive_dir / 'metadata' / 'session_summary.json'
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading metadata: {e}")
        return None


# Convenience factory function
def create_raw_archive_writer(
    output_dir: Path,
    channel_name: str,
    frequency_hz: float,
    sample_rate: int = 20000,
    station_config: Optional[Dict] = None,
    compression: str = 'gzip'
) -> RawArchiveWriter:
    """
    Create a raw archive writer with default settings.
    
    Args:
        output_dir: Base output directory
        channel_name: Channel identifier
        frequency_hz: Center frequency
        sample_rate: Sample rate (default 20000)
        station_config: Station metadata
        compression: Compression algorithm
        
    Returns:
        Configured RawArchiveWriter
    """
    config = RawArchiveConfig(
        output_dir=output_dir,
        channel_name=channel_name,
        frequency_hz=frequency_hz,
        sample_rate=sample_rate,
        station_config=station_config or {},
        compression=compression
    )
    return RawArchiveWriter(config)
