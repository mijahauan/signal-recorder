#!/usr/bin/env python3
"""
Digital RF Writer for GRAPE Data

Writes decimated IQ data to Digital RF format (PSWS/wsprdaemon-compatible).
Continuous writing approach (not daily batches like V1).
"""

import numpy as np
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple
from collections import deque
import uuid

try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    logging.warning("digital_rf not available - upload functionality disabled")

from .decimation import get_decimator

logger = logging.getLogger(__name__)


class DigitalRFWriter:
    """
    Write decimated IQ samples to Digital RF format for upload
    
    This writer:
    - Decimates 16 kHz IQ → 10 Hz
    - Writes continuously to Digital RF HDF5
    - PSWS/wsprdaemon-compatible format
    - Handles time_snap-corrected timestamps
    """
    
    def __init__(self, output_dir: Path, channel_name: str, frequency_hz: float,
                 input_sample_rate: int = 16000, output_sample_rate: int = 10,
                 station_config: dict = None):
        """
        Initialize Digital RF writer
        
        Args:
            output_dir: Base directory for Digital RF files
            channel_name: Channel name (e.g., "WWV 2.5 MHz")
            frequency_hz: Center frequency
            input_sample_rate: Input IQ sample rate (16 kHz)
            output_sample_rate: Output decimated rate (10 Hz)
            station_config: Station metadata dict with keys:
                - callsign: Station callsign
                - grid_square: Maidenhead grid square
                - receiver_name: Receiver identifier
                - psws_station_id: PSWS station ID
                - psws_instrument_id: PSWS instrument number
        """
        if not DRF_AVAILABLE:
            raise ImportError("digital_rf package required for upload functionality")
        
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.station_config = station_config or {}
        
        # Get decimator function
        self.decimator = get_decimator(input_sample_rate, output_sample_rate)
        self.decimation_factor = input_sample_rate // output_sample_rate
        
        # Accumulator for samples (need enough for clean decimation)
        self.sample_buffer: deque = deque()
        self.last_timestamp: Optional[float] = None  # Track last archive timestamp
        
        # Digital RF writer (created on first write)
        self.drf_writer = None
        self.drf_channel_name = None
        self.metadata_writer = None
        self.dataset_uuid = uuid.uuid4().hex
        
        # Statistics
        self.samples_written = 0
        self.last_write_time = None
        self.current_day = None
        # Monotonic DRF index state (seeded on first writer creation)
        # We intentionally advance by sample count rather than recomputing
        # from UTC every block to avoid overlaps/backwards jumps when
        # time_snap or timing jitter shifts slightly.
        self.next_index: Optional[int] = None
        
        logger.info(f"{channel_name}: DigitalRFWriter initialized")
        logger.info(f"{channel_name}: Decimation: {input_sample_rate} Hz → {output_sample_rate} Hz")
        logger.info(f"{channel_name}: Output directory: {output_dir}")
    
    def _create_writer(self, timestamp: float):
        """
        Create Digital RF writer for current day
        
        Args:
            timestamp: Unix timestamp of first sample
        """
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        day_date = dt.date()
        
        # Close existing writer if day changed
        if self.current_day and self.current_day != day_date:
            logger.info(f"{self.channel_name}: Day boundary, closing previous DRF writer")
            self._close_writer()
        
        if self.drf_writer:
            return  # Already created for this day
        
        # Build PSWS-compatible directory structure (matches wsprdaemon wav2grape.py)
        # {base}/YYYYMMDD/CALLSIGN_GRID/RECEIVER@STATION_ID_INSTRUMENT_ID/OBS{timestamp}/CHANNEL/
        date_str = day_date.strftime('%Y%m%d')
        callsign = self.station_config.get('callsign', 'UNKNOWN')
        grid = self.station_config.get('grid_square', 'UNKNOWN')
        receiver_name = self.station_config.get('receiver_name', 'GRAPE')
        psws_station_id = self.station_config.get('psws_station_id', 'UNKNOWN')
        psws_instrument_id = self.station_config.get('psws_instrument_id', '1')
        safe_channel_name = self.channel_name.replace(' ', '_')
        
        # Build receiver_info: RECEIVER@STATION_ID_INSTRUMENT_ID
        receiver_info = f"{receiver_name}@{psws_station_id}_{psws_instrument_id}"
        
        # Build OBS timestamp subdirectory (format: OBS2024-11-09T19-00)
        obs_timestamp = dt.strftime('OBS%Y-%m-%dT%H-%M')
        
        # Full path matching wsprdaemon
        drf_dir = (self.output_dir / date_str / f"{callsign}_{grid}" / 
                   receiver_info / obs_timestamp / safe_channel_name)
        drf_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate start_global_index (samples since Unix epoch at output rate)
        # Seed once from the first UTC timestamp; subsequent blocks advance
        # by sample count to keep indices strictly monotonic for DRF.
        start_global_index = int(timestamp * self.output_sample_rate)
        
        logger.info(f"{self.channel_name}: Creating Digital RF writer for {day_date}")
        logger.info(f"{self.channel_name}: Directory: {drf_dir}")
        logger.info(f"{self.channel_name}: start_global_index: {start_global_index}")
        
        # Create writer
        self.drf_writer = drf.DigitalRFWriter(
            str(drf_dir),
            dtype=np.complex64,
            subdir_cadence_secs=86400,      # 24 hour subdirectories
            file_cadence_millisecs=3600000, # 1 hour files
            start_global_index=start_global_index,
            sample_rate_numerator=self.output_sample_rate,
            sample_rate_denominator=1,
            uuid_str=self.dataset_uuid,
            compression_level=9,            # High compression for upload
            checksum=False,
            is_complex=True,
            num_subchannels=1,
            is_continuous=True,             # Valid because we fill gaps
            marching_periods=False
        )
        
        # Create metadata writer
        metadata_dir = drf_dir / 'metadata'
        metadata_dir.mkdir(parents=True, exist_ok=True)
        
        self.metadata_writer = drf.DigitalMetadataWriter(
            str(metadata_dir),
            subdir_cadence_secs=86400,
            file_cadence_secs=3600,
            sample_rate_numerator=self.output_sample_rate,
            sample_rate_denominator=1,
            file_name='metadata'
        )
        
        # Write initial metadata (matches wsprdaemon metadata format)
        metadata = {
            'callsign': callsign,
            'grid_square': grid,
            'receiver_name': receiver_name,
            'center_frequencies': np.array([self.frequency_hz], dtype=np.float64),
            'uuid_str': self.dataset_uuid,
            'sample_rate': float(self.output_sample_rate),
            'date': day_date.isoformat()
        }
        self.metadata_writer.write(start_global_index, metadata)
        
        self.current_day = day_date
        self.drf_channel_name = safe_channel_name
        # Initialize monotonic index if not already set
        if self.next_index is None:
            self.next_index = start_global_index
        
        logger.info(f"{self.channel_name}: ✅ Digital RF writer ready")
    
    def _close_writer(self):
        """Close current Digital RF writer"""
        if self.drf_writer:
            # Digital RF writers auto-close, no explicit close needed
            self.drf_writer = None
            self.metadata_writer = None
            logger.info(f"{self.channel_name}: Digital RF writer closed")
    
    def add_samples(self, timestamp: float, samples: np.ndarray):
        """
        Add samples to buffer and write when enough accumulated
        
        Args:
            timestamp: Unix timestamp of first sample (time_snap-corrected)
            samples: Complex IQ samples at input_sample_rate (16 kHz)
        """
        # Ensure writer exists for this day
        self._create_writer(timestamp)
        
        # Track this archive's timestamp for flush operations
        self.last_timestamp = timestamp
        
        # Add to buffer
        self.sample_buffer.extend(samples)
        
        # Process when we have enough samples for decimation
        # Need at least 1 second of data (16000 samples) for clean decimation
        min_samples = self.input_sample_rate
        samples_processed = 0
        
        while len(self.sample_buffer) >= min_samples:
            # Extract chunk for decimation
            chunk = np.array(list(self.sample_buffer)[:min_samples], dtype=np.complex64)
            # Calculate timestamp for this chunk
            # Use the current archive timestamp plus offset for samples already processed from this archive
            chunk_timestamp = timestamp + (samples_processed / self.input_sample_rate)
            
            # Remove from buffer
            for _ in range(min_samples):
                self.sample_buffer.popleft()
            samples_processed += min_samples
            
            # Decimate
            try:
                decimated = self.decimator(chunk)
                
                # Use monotonic index sequence for DRF writes. We advance
                # by the number of decimated samples rather than
                # recomputing from UTC to prevent index overlaps when
                # time_snap or clock adjustments occur.
                if self.next_index is None:
                    self.next_index = int(chunk_timestamp * self.output_sample_rate)
                
                # Safety check: Detect backwards time jump (archive processed out of order)
                calculated_index = int(chunk_timestamp * self.output_sample_rate)
                if calculated_index < self.next_index:
                    logger.warning(f"{self.channel_name}: ⚠️  Archive out of order! "
                                 f"Calculated index {calculated_index} < next_index {self.next_index}. "
                                 f"Skipping {len(decimated)} samples to maintain monotonic sequence.")
                    # Skip this chunk - better to drop data than corrupt the DRF timeline
                    continue

                self.drf_writer.rf_write(decimated, int(self.next_index))
                self.samples_written += len(decimated)
                self.next_index += len(decimated)
                self.last_write_time = time.time()
                
                logger.debug(f"{self.channel_name}: Wrote {len(decimated)} decimated samples "
                           f"(global_index={self.next_index})")
                
            except Exception as e:
                logger.error(f"{self.channel_name}: Decimation/write error: {e}", exc_info=True)
        
        # Buffer state maintained for next add_samples call
    
    def flush(self):
        """
        Flush remaining buffered samples
        
        Call at shutdown or day boundary to ensure all data written
        """
        if len(self.sample_buffer) > 0:
            # Process any remaining samples (may be partial)
            remaining = np.array(list(self.sample_buffer), dtype=np.complex64)
            # Use last known timestamp plus offset for buffered samples
            chunk_timestamp = self.last_timestamp if self.last_timestamp else time.time()
            
            try:
                decimated = self.decimator(remaining)
                if self.next_index is None:
                    self.next_index = int(chunk_timestamp * self.output_sample_rate)
                
                # Safety check for backwards time jump
                calculated_index = int(chunk_timestamp * self.output_sample_rate)
                if calculated_index < self.next_index:
                    logger.warning(f"{self.channel_name}: ⚠️  Flush would go backwards "
                                 f"(calculated={calculated_index}, next={self.next_index}). Skipping.")
                    return

                if self.drf_writer:
                    self.drf_writer.rf_write(decimated, int(self.next_index))
                    self.samples_written += len(decimated)
                    self.next_index += len(decimated)
                    logger.info(f"{self.channel_name}: Flushed {len(decimated)} remaining samples")
            except Exception as e:
                logger.warning(f"{self.channel_name}: Error flushing: {e}")
            
            self.sample_buffer.clear()
            self.buffer_timestamps.clear()
        
        self._close_writer()
    
    def get_stats(self) -> dict:
        """Get writer statistics"""
        return {
            'samples_written': self.samples_written,
            'last_write_time': self.last_write_time,
            'buffer_size': len(self.sample_buffer),
            'current_day': self.current_day.isoformat() if self.current_day else None,
            'decimation_factor': self.decimation_factor,
            'output_sample_rate': self.output_sample_rate
        }
