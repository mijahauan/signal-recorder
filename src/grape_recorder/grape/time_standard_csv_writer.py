#!/usr/bin/env python3
"""
Time Standard CSV Writer - Log Primary Time Standard Results

Writes time standard results to CSV for analysis and visualization.
Captures:
- Per-minute emission time calculations
- Propagation mode identification
- Cross-channel consensus
- UTC(NIST) verification status

CSV Schema:
-----------
timestamp_utc, station, frequency_mhz, arrival_time_utc, emission_time_utc,
propagation_delay_ms, mode, n_hops, mode_confidence, snr_db, accuracy_ms,
second_aligned, utc_offset_ms, n_channels, consensus_confidence,
cross_verified, time_transfer_accuracy_ms
"""

import csv
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TimeStandardRecord:
    """Single time standard measurement record"""
    timestamp_utc: str
    station: str
    frequency_mhz: float
    arrival_time_utc: float
    emission_time_utc: float
    propagation_delay_ms: float
    mode: str
    n_hops: int
    mode_confidence: float
    snr_db: float
    accuracy_ms: float
    second_aligned: bool
    utc_offset_ms: float
    n_channels: int
    consensus_confidence: float
    cross_verified: bool
    time_transfer_accuracy_ms: float


class TimeStandardCSVWriter:
    """
    Writes time standard results to daily CSV files.
    """
    
    # CSV columns
    COLUMNS = [
        'timestamp_utc',
        'station',
        'frequency_mhz',
        'arrival_time_utc',
        'emission_time_utc',
        'propagation_delay_ms',
        'mode',
        'n_hops',
        'mode_confidence',
        'snr_db',
        'accuracy_ms',
        'second_aligned',
        'utc_offset_ms',
        'n_channels',
        'consensus_confidence',
        'cross_verified',
        'time_transfer_accuracy_ms'
    ]
    
    def __init__(
        self,
        output_dir: Path,
        channel_name: str = 'all_channels'
    ):
        """
        Initialize CSV writer.
        
        Args:
            output_dir: Directory for CSV files
            channel_name: Channel identifier (for filename)
        """
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name.replace(' ', '_')
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Current file tracking
        self._current_date: Optional[str] = None
        self._current_file: Optional[Path] = None
        self._file_handle = None
        self._writer = None
        
        logger.info(f"TimeStandardCSVWriter initialized: {self.output_dir}")
    
    def _get_csv_path(self, date_str: str) -> Path:
        """Get CSV file path for a date"""
        return self.output_dir / f"time_standard_{self.channel_name}_{date_str}.csv"
    
    def _ensure_file_open(self, timestamp: datetime):
        """Ensure correct daily file is open"""
        date_str = timestamp.strftime('%Y%m%d')
        
        if date_str != self._current_date:
            # Close current file
            if self._file_handle:
                self._file_handle.close()
            
            # Open new file
            self._current_date = date_str
            self._current_file = self._get_csv_path(date_str)
            
            # Check if file exists (to know if we need header)
            write_header = not self._current_file.exists()
            
            self._file_handle = open(self._current_file, 'a', newline='')
            self._writer = csv.DictWriter(self._file_handle, fieldnames=self.COLUMNS)
            
            if write_header:
                self._writer.writeheader()
                logger.info(f"Created new CSV: {self._current_file}")
    
    def write_record(self, record: TimeStandardRecord):
        """Write a single record to CSV"""
        timestamp = datetime.fromisoformat(record.timestamp_utc.replace('Z', '+00:00'))
        self._ensure_file_open(timestamp)
        
        self._writer.writerow({
            'timestamp_utc': record.timestamp_utc,
            'station': record.station,
            'frequency_mhz': f"{record.frequency_mhz:.2f}",
            'arrival_time_utc': f"{record.arrival_time_utc:.6f}",
            'emission_time_utc': f"{record.emission_time_utc:.6f}",
            'propagation_delay_ms': f"{record.propagation_delay_ms:.3f}",
            'mode': record.mode,
            'n_hops': record.n_hops,
            'mode_confidence': f"{record.mode_confidence:.3f}",
            'snr_db': f"{record.snr_db:.1f}",
            'accuracy_ms': f"{record.accuracy_ms:.3f}",
            'second_aligned': 'true' if record.second_aligned else 'false',
            'utc_offset_ms': f"{record.utc_offset_ms:.3f}",
            'n_channels': record.n_channels,
            'consensus_confidence': f"{record.consensus_confidence:.3f}",
            'cross_verified': 'true' if record.cross_verified else 'false',
            'time_transfer_accuracy_ms': f"{record.time_transfer_accuracy_ms:.3f}"
        })
        
        self._file_handle.flush()
    
    def write_minute_result(self, result: 'MinuteTimeStandardResult'):
        """
        Write all records from a minute result.
        
        Writes one row per station with consensus data.
        """
        from .primary_time_standard import MinuteTimeStandardResult, StationConsensus
        
        timestamp_str = result.minute_utc.isoformat()
        
        for consensus in [result.wwv_consensus, result.wwvh_consensus, result.chu_consensus]:
            if consensus is None or consensus.n_channels == 0:
                continue
            
            # Get best channel result for frequency info
            best_result = max(
                consensus.channel_results,
                key=lambda r: r.snr_db * r.mode_confidence
            )
            
            record = TimeStandardRecord(
                timestamp_utc=timestamp_str,
                station=consensus.station,
                frequency_mhz=best_result.frequency_mhz,
                arrival_time_utc=best_result.arrival_time_utc,
                emission_time_utc=consensus.emission_time_utc,
                propagation_delay_ms=best_result.propagation_delay_ms,
                mode=best_result.mode.value,
                n_hops=best_result.n_hops,
                mode_confidence=best_result.mode_confidence,
                snr_db=best_result.snr_db,
                accuracy_ms=consensus.emission_time_std_ms,
                second_aligned=abs(consensus.utc_offset_ms) < 2.0,
                utc_offset_ms=consensus.utc_offset_ms,
                n_channels=consensus.n_channels,
                consensus_confidence=consensus.consensus_confidence,
                cross_verified=result.cross_verified,
                time_transfer_accuracy_ms=result.time_transfer_accuracy_ms
            )
            
            self.write_record(record)
    
    def close(self):
        """Close current file"""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
            self._writer = None
    
    def __del__(self):
        self.close()


# Summary CSV for daily statistics
class TimeStandardSummaryWriter:
    """
    Writes daily summary statistics for time standard performance.
    """
    
    COLUMNS = [
        'date',
        'total_minutes',
        'high_confidence_minutes',
        'cross_verified_minutes',
        'wwv_detections',
        'wwvh_detections',
        'chu_detections',
        'mean_accuracy_ms',
        'min_accuracy_ms',
        'max_accuracy_ms',
        'mean_utc_offset_ms',
        'std_utc_offset_ms'
    ]
    
    def __init__(self, output_dir: Path):
        """Initialize summary writer"""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.summary_file = self.output_dir / 'time_standard_daily_summary.csv'
        
        # Create file with header if needed
        if not self.summary_file.exists():
            with open(self.summary_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.COLUMNS)
                writer.writeheader()
    
    def write_daily_summary(
        self,
        date: str,
        results: List['MinuteTimeStandardResult']
    ):
        """
        Write daily summary from list of minute results.
        """
        if not results:
            return
        
        # Calculate statistics
        total_minutes = len(results)
        high_confidence = sum(1 for r in results if r.high_confidence)
        cross_verified = sum(1 for r in results if r.cross_verified)
        
        wwv_detections = sum(1 for r in results if r.wwv_consensus and r.wwv_consensus.n_channels > 0)
        wwvh_detections = sum(1 for r in results if r.wwvh_consensus and r.wwvh_consensus.n_channels > 0)
        chu_detections = sum(1 for r in results if r.chu_consensus and r.chu_consensus.n_channels > 0)
        
        # Accuracy stats (only high confidence)
        accuracies = [r.time_transfer_accuracy_ms for r in results if r.high_confidence]
        offsets = [r.utc_nist_offset_ms for r in results if r.high_confidence]
        
        import numpy as np
        
        row = {
            'date': date,
            'total_minutes': total_minutes,
            'high_confidence_minutes': high_confidence,
            'cross_verified_minutes': cross_verified,
            'wwv_detections': wwv_detections,
            'wwvh_detections': wwvh_detections,
            'chu_detections': chu_detections,
            'mean_accuracy_ms': f"{np.mean(accuracies):.3f}" if accuracies else '',
            'min_accuracy_ms': f"{np.min(accuracies):.3f}" if accuracies else '',
            'max_accuracy_ms': f"{np.max(accuracies):.3f}" if accuracies else '',
            'mean_utc_offset_ms': f"{np.mean(offsets):.3f}" if offsets else '',
            'std_utc_offset_ms': f"{np.std(offsets):.3f}" if offsets else ''
        }
        
        with open(self.summary_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.COLUMNS)
            writer.writerow(row)
        
        logger.info(f"Daily summary written: {date}, {high_confidence}/{total_minutes} high-confidence")
