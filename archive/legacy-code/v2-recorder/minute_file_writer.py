#!/usr/bin/env python3
"""
Minute File Writer for GRAPE Data

Writes 1-minute compressed files of full-bandwidth (8 kHz) IQ data.
Replaces the in-memory DailyBuffer approach with continuous file writes.
"""

import numpy as np
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple
from collections import deque

logger = logging.getLogger(__name__)


class MinuteFileWriter:
    """
    Write 1-minute compressed numpy files of 8 kHz IQ data
    
    This preserves full bandwidth for:
    - WWV tone detection and timing analysis
    - High-quality offline decimation
    - Reprocessing if needed
    
    Storage: ~1-2 MB per minute compressed = ~2 GB/day per channel
    """
    
    def __init__(self, output_dir: Path, channel_name: str, frequency_hz: float,
                 sample_rate: int = 8000, station_config: dict = None):
        """
        Initialize minute file writer
        
        Args:
            output_dir: Base directory for archives
            channel_name: Channel name (e.g., "WWV 2.5 MHz")
            frequency_hz: Center frequency
            sample_rate: Sample rate (default 8000 Hz)
            station_config: Station metadata
        """
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.station_config = station_config or {}
        
        self.samples_per_minute = sample_rate * 60
        
        # Current minute buffer
        self.minute_buffer: deque = deque()
        self.minute_start_time: Optional[float] = None
        self.current_minute_timestamp: Optional[datetime] = None
        
        # Statistics
        self.minutes_written = 0
        self.total_samples_written = 0
        self.last_write_time = None
        
        logger.info(f"{channel_name}: MinuteFileWriter initialized")
        logger.info(f"{channel_name}: Sample rate: {sample_rate} Hz, samples/minute: {self.samples_per_minute}")
        logger.info(f"{channel_name}: Output directory: {output_dir}")
    
    def add_samples(self, timestamp: float, samples: np.ndarray) -> Optional[Tuple[datetime, Path]]:
        """
        Add samples to buffer and write when minute complete
        
        Args:
            timestamp: Unix timestamp of first sample
            samples: Complex IQ samples (8 kHz)
        
        Returns:
            If minute was written: (minute_timestamp, file_path)
            Otherwise: None
        """
        # Determine which minute these samples belong to
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        minute_boundary = dt.replace(second=0, microsecond=0)
        
        # Check for minute rollover
        completed_minute = None
        if self.current_minute_timestamp is not None and minute_boundary != self.current_minute_timestamp:
            # New minute - write previous
            if len(self.minute_buffer) > 0:
                file_path = self._write_minute_file()
                completed_minute = (self.current_minute_timestamp, file_path)
            
            # Reset for new minute
            self.minute_buffer.clear()
            self.minute_start_time = timestamp
            self.current_minute_timestamp = minute_boundary
        elif self.current_minute_timestamp is None:
            # First samples
            self.minute_start_time = timestamp
            self.current_minute_timestamp = minute_boundary
        
        # Add samples to buffer
        self.minute_buffer.extend(samples)
        
        # Check if minute is complete (or overflowing)
        if len(self.minute_buffer) >= self.samples_per_minute:
            # Trim to exactly one minute
            samples_to_keep = self.samples_per_minute
            trimmed_buffer = deque(list(self.minute_buffer)[:samples_to_keep])
            
            # Write this minute
            file_path = self._write_minute_file()
            completed_minute = (self.current_minute_timestamp, file_path)
            
            # Keep overflow for next minute
            overflow = list(self.minute_buffer)[samples_to_keep:]
            self.minute_buffer = deque(overflow)
            
            # Update to next minute
            next_minute = self.current_minute_timestamp.replace(
                minute=(self.current_minute_timestamp.minute + 1) % 60
            )
            if next_minute.minute == 0:
                next_minute = next_minute.replace(hour=(next_minute.hour + 1) % 24)
                if next_minute.hour == 0:
                    # Day rollover
                    from datetime import timedelta
                    next_minute = next_minute + timedelta(days=1)
            
            self.current_minute_timestamp = next_minute
            self.minute_start_time = timestamp + (samples_to_keep / self.sample_rate)
        
        return completed_minute
    
    def _write_minute_file(self) -> Path:
        """Write current minute buffer to compressed file"""
        if not self.current_minute_timestamp:
            raise ValueError("No current minute timestamp")
        
        # Convert buffer to numpy array
        data = np.array(list(self.minute_buffer), dtype=np.complex64)
        
        # Create directory structure: YYYYMMDD/CALLSIGN_GRID/RECEIVER/CHANNEL/
        date_str = self.current_minute_timestamp.strftime("%Y%m%d")
        callsign = self.station_config.get('callsign', 'UNKNOWN')
        grid = self.station_config.get('grid_square', 'UNKNOWN')
        receiver = self.station_config.get('instrument_id', 'UNKNOWN')
        
        dir_path = (self.output_dir / date_str / f"{callsign}_{grid}" / 
                    receiver / self.channel_name.replace(' ', '_'))
        dir_path.mkdir(parents=True, exist_ok=True)
        
        # Filename: YYYYMMDDTHHmmSSZ_FREQ_iq.npz
        time_str = self.current_minute_timestamp.strftime("%Y%m%dT%H%M%SZ")
        freq_str = f"{int(self.frequency_hz)}"
        filename = f"{time_str}_{freq_str}_iq.npz"
        file_path = dir_path / filename
        
        # Write compressed
        np.savez_compressed(
            file_path,
            iq=data,
            sample_rate=self.sample_rate,
            timestamp=self.current_minute_timestamp.timestamp(),
            frequency_hz=self.frequency_hz,
            channel_name=self.channel_name
        )
        
        # Update stats
        self.minutes_written += 1
        self.total_samples_written += len(data)
        self.last_write_time = time.time()
        
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        logger.info(f"{self.channel_name}: Wrote {filename} ({len(data)} samples, {file_size_mb:.2f} MB)")
        
        return file_path
    
    def flush(self) -> Optional[Path]:
        """Force write current buffer (at end of recording)"""
        if len(self.minute_buffer) == 0:
            return None
        
        # Pad with zeros if incomplete minute
        if len(self.minute_buffer) < self.samples_per_minute:
            samples_needed = self.samples_per_minute - len(self.minute_buffer)
            zeros = np.zeros(samples_needed, dtype=np.complex64)
            self.minute_buffer.extend(zeros)
            logger.warning(f"{self.channel_name}: Padded incomplete minute with {samples_needed} zero samples")
        
        return self._write_minute_file()
    
    def get_stats(self) -> dict:
        """Get writer statistics"""
        return {
            'minutes_written': self.minutes_written,
            'total_samples_written': self.total_samples_written,
            'buffer_samples': len(self.minute_buffer),
            'last_write_time': self.last_write_time,
            'expected_size_mb_per_day': (self.sample_rate * 86400 * 8) / (1024 * 1024),  # Complex64 = 8 bytes
            'estimated_compressed_mb_per_day': (self.sample_rate * 86400 * 8 * 0.5) / (1024 * 1024)  # ~50% compression
        }


def load_minute_file(file_path: Path) -> Tuple[np.ndarray, dict]:
    """
    Load a minute file
    
    Returns:
        (iq_data, metadata)
    """
    data = np.load(file_path)
    
    iq = data['iq']
    metadata = {
        'sample_rate': int(data['sample_rate']),
        'timestamp': float(data['timestamp']),
        'frequency_hz': float(data['frequency_hz']),
        'channel_name': str(data['channel_name'])
    }
    
    return iq, metadata
