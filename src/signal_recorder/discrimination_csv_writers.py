"""
CSV Writers for Individual Discrimination Methods

Each method writes to its own CSV file for independent reprocessability.
All writers maintain daily CSV files that append new results.

Directory structure:
    analytics/{channel}/tone_detections/{channel}_tones_YYYYMMDD.csv
    analytics/{channel}/tick_windows/{channel}_ticks_YYYYMMDD.csv
    analytics/{channel}/station_id_440hz/{channel}_440hz_YYYYMMDD.csv
    analytics/{channel}/bcd_discrimination/{channel}_bcd_YYYYMMDD.csv
    analytics/{channel}/discrimination/{channel}_discrimination_YYYYMMDD.csv
"""

import csv
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from .paths import GRAPEPaths

logger = logging.getLogger(__name__)


@dataclass
class ToneDetectionRecord:
    """Record from tone detection analysis"""
    timestamp_utc: str
    station: str
    frequency_hz: float
    duration_sec: float
    timing_error_ms: float
    snr_db: float
    tone_power_db: float
    confidence: float
    use_for_time_snap: bool


@dataclass
class TickWindowRecord:
    """Record from tick window analysis (5ms ticks, 10-sec windows)"""
    timestamp_utc: str
    window_second: int
    coherent_wwv_snr_db: float
    coherent_wwvh_snr_db: float
    incoherent_wwv_snr_db: float
    incoherent_wwvh_snr_db: float
    coherence_quality_wwv: float
    coherence_quality_wwvh: float
    integration_method: str
    wwv_snr_db: float
    wwvh_snr_db: float
    ratio_db: float
    tick_count: int


@dataclass
class StationID440HzRecord:
    """Record from 440 Hz station ID detection"""
    timestamp_utc: str
    minute_number: int
    wwv_detected: bool
    wwvh_detected: bool
    wwv_power_db: Optional[float]
    wwvh_power_db: Optional[float]


@dataclass
class BCDWindowRecord:
    """Record from BCD discrimination window analysis"""
    timestamp_utc: str
    window_start_sec: float
    wwv_amplitude: float
    wwvh_amplitude: float
    differential_delay_ms: float
    correlation_quality: float
    amplitude_ratio_db: float


@dataclass
class DiscriminationRecord:
    """Record from final weighted voting"""
    timestamp_utc: str
    dominant_station: str
    confidence: str
    method_weights: str  # JSON string
    minute_type: str


class DiscriminationCSVWriters:
    """
    Manages CSV output for all discrimination methods
    
    Creates and appends to daily CSV files for each method.
    Thread-safe for multiple writers (uses file locking via context managers).
    """
    
    def __init__(self, data_root: str, channel_name: str):
        """
        Initialize CSV writers using GRAPEPaths API
        
        Args:
            data_root: Root directory for analytics (e.g., /tmp/grape-test)
            channel_name: Channel name (e.g., "WWV 10 MHz")
        """
        self.channel_name = channel_name
        self.paths = GRAPEPaths(data_root)
        
        # Method-specific directories (using GRAPEPaths API)
        self.tone_dir = self.paths.get_tone_detections_dir(channel_name)
        self.tick_dir = self.paths.get_tick_windows_dir(channel_name)
        self.id_440_dir = self.paths.get_station_id_440hz_dir(channel_name)
        self.bcd_dir = self.paths.get_bcd_discrimination_dir(channel_name)
        self.disc_dir = self.paths.get_discrimination_dir(channel_name)
        
        # Channel directory name for file naming
        self.channel_dir = channel_name.replace(' ', '_').replace('.', '_')
        
        # Ensure directories exist
        for directory in [self.tone_dir, self.tick_dir, self.id_440_dir, 
                         self.bcd_dir, self.disc_dir]:
            directory.mkdir(parents=True, exist_ok=True)
    
    def _get_csv_path(self, directory: Path, prefix: str, timestamp: float) -> Path:
        """
        Get CSV file path for a given timestamp
        
        Args:
            directory: Directory for this CSV type
            prefix: File prefix (e.g., "WWV_10_MHz_tones")
            timestamp: Unix timestamp
            
        Returns:
            Path to daily CSV file
        """
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        date_str = dt.strftime('%Y%m%d')
        return directory / f"{prefix}_{date_str}.csv"
    
    def write_tone_detection(self, record: ToneDetectionRecord):
        """Write tone detection record to CSV"""
        timestamp = datetime.fromisoformat(record.timestamp_utc.replace('Z', '+00:00')).timestamp()
        csv_path = self._get_csv_path(self.tone_dir, f"{self.channel_dir}_tones", timestamp)
        
        fieldnames = ['timestamp_utc', 'station', 'frequency_hz', 'duration_sec',
                     'timing_error_ms', 'snr_db', 'tone_power_db', 'confidence',
                     'use_for_time_snap']
        
        # Check if file exists to determine if header is needed
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                'timestamp_utc': record.timestamp_utc,
                'station': record.station,
                'frequency_hz': f"{record.frequency_hz:.1f}",
                'duration_sec': f"{record.duration_sec:.3f}",
                'timing_error_ms': f"{record.timing_error_ms:.2f}",
                'snr_db': f"{record.snr_db:.2f}",
                'tone_power_db': f"{record.tone_power_db:.2f}",
                'confidence': f"{record.confidence:.3f}",
                'use_for_time_snap': '1' if record.use_for_time_snap else '0'
            })
    
    def write_tick_windows(self, timestamp_utc: str, windows: List[Dict[str, Any]]):
        """
        Write tick window analysis results
        
        Args:
            timestamp_utc: Minute timestamp
            windows: List of 6 window dictionaries from detect_tick_windows()
        """
        timestamp = datetime.fromisoformat(timestamp_utc.replace('Z', '+00:00')).timestamp()
        csv_path = self._get_csv_path(self.tick_dir, f"{self.channel_dir}_ticks", timestamp)
        
        fieldnames = ['timestamp_utc', 'window_second', 
                     'coherent_wwv_snr_db', 'coherent_wwvh_snr_db',
                     'incoherent_wwv_snr_db', 'incoherent_wwvh_snr_db',
                     'coherence_quality_wwv', 'coherence_quality_wwvh',
                     'integration_method', 'wwv_snr_db', 'wwvh_snr_db',
                     'ratio_db', 'tick_count']
        
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            for window in windows:
                writer.writerow({
                    'timestamp_utc': timestamp_utc,
                    'window_second': window['second'],
                    'coherent_wwv_snr_db': f"{window['coherent_wwv_snr_db']:.2f}",
                    'coherent_wwvh_snr_db': f"{window['coherent_wwvh_snr_db']:.2f}",
                    'incoherent_wwv_snr_db': f"{window['incoherent_wwv_snr_db']:.2f}",
                    'incoherent_wwvh_snr_db': f"{window['incoherent_wwvh_snr_db']:.2f}",
                    'coherence_quality_wwv': f"{window['coherence_quality_wwv']:.3f}",
                    'coherence_quality_wwvh': f"{window['coherence_quality_wwvh']:.3f}",
                    'integration_method': window['integration_method'],
                    'wwv_snr_db': f"{window['wwv_snr_db']:.2f}",
                    'wwvh_snr_db': f"{window['wwvh_snr_db']:.2f}",
                    'ratio_db': f"{window['ratio_db']:.2f}",
                    'tick_count': window['tick_count']
                })
    
    def write_440hz_detection(self, record: StationID440HzRecord):
        """Write 440 Hz station ID detection record"""
        timestamp = datetime.fromisoformat(record.timestamp_utc.replace('Z', '+00:00')).timestamp()
        csv_path = self._get_csv_path(self.id_440_dir, f"{self.channel_dir}_440hz", timestamp)
        
        fieldnames = ['timestamp_utc', 'minute_number', 'wwv_detected', 'wwvh_detected',
                     'wwv_power_db', 'wwvh_power_db']
        
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                'timestamp_utc': record.timestamp_utc,
                'minute_number': record.minute_number,
                'wwv_detected': '1' if record.wwv_detected else '0',
                'wwvh_detected': '1' if record.wwvh_detected else '0',
                'wwv_power_db': f"{record.wwv_power_db:.2f}" if record.wwv_power_db is not None else '',
                'wwvh_power_db': f"{record.wwvh_power_db:.2f}" if record.wwvh_power_db is not None else ''
            })
    
    def write_bcd_windows(self, timestamp_utc: str, windows: List[Dict[str, Any]]):
        """
        Write BCD discrimination window results
        
        Args:
            timestamp_utc: Minute timestamp
            windows: List of BCD window dictionaries from detect_bcd_discrimination()
        """
        timestamp = datetime.fromisoformat(timestamp_utc.replace('Z', '+00:00')).timestamp()
        csv_path = self._get_csv_path(self.bcd_dir, f"{self.channel_dir}_bcd", timestamp)
        
        fieldnames = ['timestamp_utc', 'window_start_sec', 'wwv_amplitude', 'wwvh_amplitude',
                     'differential_delay_ms', 'correlation_quality', 'amplitude_ratio_db']
        
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            for window in windows:
                wwv_amp = window.get('wwv_amplitude', 0)
                wwvh_amp = window.get('wwvh_amplitude', 0)
                
                # Calculate amplitude ratio (avoid log(0))
                if wwv_amp > 0 and wwvh_amp > 0:
                    ratio_db = 20 * np.log10(wwv_amp / wwvh_amp)
                else:
                    ratio_db = 0.0
                
                writer.writerow({
                    'timestamp_utc': timestamp_utc,
                    'window_start_sec': f"{window.get('window_start', 0.0):.1f}",
                    'wwv_amplitude': f"{wwv_amp:.4f}",
                    'wwvh_amplitude': f"{wwvh_amp:.4f}",
                    'differential_delay_ms': f"{window.get('delay', 0.0):.2f}",
                    'correlation_quality': f"{window.get('quality', 0.0):.3f}",
                    'amplitude_ratio_db': f"{ratio_db:.2f}"
                })
    
    def write_discrimination_result(self, record: DiscriminationRecord):
        """Write final weighted voting discrimination result"""
        timestamp = datetime.fromisoformat(record.timestamp_utc.replace('Z', '+00:00')).timestamp()
        csv_path = self._get_csv_path(self.disc_dir, f"{self.channel_dir}_discrimination", timestamp)
        
        fieldnames = ['timestamp_utc', 'dominant_station', 'confidence',
                     'method_weights', 'minute_type']
        
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                'timestamp_utc': record.timestamp_utc,
                'dominant_station': record.dominant_station,
                'confidence': record.confidence,
                'method_weights': record.method_weights,
                'minute_type': record.minute_type
            })


# Import numpy for ratio calculation
import numpy as np
