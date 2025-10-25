"""
GRAPE Metadata and Quality Tracking Module

Generates metadata files with quality metrics, gap information, and data
completeness statistics for GRAPE Digital RF datasets.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GapRecord:
    """Record of a data gap in the recording"""
    start_time: str  # ISO format
    end_time: str  # ISO format
    duration_seconds: float
    start_sequence: int
    end_sequence: int
    missing_packets: int
    estimated_missing_samples: int
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class QualityMetrics:
    """Quality metrics for a recording session"""
    recording_date: str  # YYYY-MM-DD
    channel_name: str
    frequency_hz: float
    ssrc: str  # Hex format
    
    # Time coverage
    start_time: str  # ISO format
    end_time: str  # ISO format
    expected_duration_seconds: float
    actual_duration_seconds: float
    
    # Sample statistics
    total_samples_expected: int
    total_samples_received: int
    total_samples_missing: int
    data_completeness_percent: float
    
    # Packet statistics
    total_packets_received: int
    total_packets_dropped: int
    total_packets_duplicate: int
    packet_loss_rate_percent: float
    
    # Gap statistics
    total_gaps: int
    total_gap_duration_seconds: float
    longest_gap_seconds: float
    average_gap_seconds: float
    
    # Signal quality (if available)
    mean_signal_level: Optional[float] = None
    max_signal_level: Optional[float] = None
    snr_estimate_db: Optional[float] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


class GRAPEMetadataGenerator:
    """
    Generates metadata and quality reports for GRAPE recordings
    """
    
    def __init__(self, channel_name: str, frequency_hz: float, ssrc: int):
        """
        Initialize metadata generator
        
        Args:
            channel_name: Channel name (e.g., "WWV_2_5")
            frequency_hz: Center frequency
            ssrc: RTP SSRC
        """
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.ssrc = ssrc
        
        # Gap tracking
        self.gaps: List[GapRecord] = []
        self.current_gap_start: Optional[datetime] = None
        self.current_gap_start_seq: Optional[int] = None
        
        # Statistics
        self.packets_received = 0
        self.packets_dropped = 0
        self.packets_duplicate = 0
        self.samples_received = 0
        
        # Time tracking
        self.first_packet_time: Optional[datetime] = None
        self.last_packet_time: Optional[datetime] = None
        
        logger.info(f"Initialized metadata generator for {channel_name}")
    
    def record_packet(self, timestamp: datetime, sequence: int, sample_count: int,
                     is_dropped: bool = False, is_duplicate: bool = False):
        """
        Record a packet for statistics
        
        Args:
            timestamp: Packet timestamp
            sequence: RTP sequence number
            sample_count: Number of samples in packet
            is_dropped: Whether this represents dropped packet(s)
            is_duplicate: Whether this is a duplicate packet
        """
        if is_duplicate:
            self.packets_duplicate += 1
            return
        
        if is_dropped:
            self.packets_dropped += 1
            # Start or continue gap
            if self.current_gap_start is None:
                self.current_gap_start = timestamp
                self.current_gap_start_seq = sequence
            return
        
        # Normal packet
        self.packets_received += 1
        self.samples_received += sample_count
        
        # Update time range
        if self.first_packet_time is None:
            self.first_packet_time = timestamp
        self.last_packet_time = timestamp
        
        # End gap if one was in progress
        if self.current_gap_start is not None:
            self._finalize_gap(timestamp, sequence)
    
    def _finalize_gap(self, end_time: datetime, end_sequence: int):
        """
        Finalize a gap record
        
        Args:
            end_time: Gap end time
            end_sequence: Gap end sequence number
        """
        if self.current_gap_start is None:
            return
        
        duration = (end_time - self.current_gap_start).total_seconds()
        missing_packets = (end_sequence - self.current_gap_start_seq) & 0xFFFF
        
        # Estimate missing samples (assume typical packet size)
        # For 12 kHz IQ at ~100 packets/sec, typical packet has ~120 samples
        estimated_samples = missing_packets * 120
        
        gap = GapRecord(
            start_time=self.current_gap_start.isoformat(),
            end_time=end_time.isoformat(),
            duration_seconds=duration,
            start_sequence=self.current_gap_start_seq,
            end_sequence=end_sequence,
            missing_packets=missing_packets,
            estimated_missing_samples=estimated_samples
        )
        
        self.gaps.append(gap)
        logger.info(f"Recorded gap: {duration:.2f}s, {missing_packets} packets")
        
        # Reset gap tracking
        self.current_gap_start = None
        self.current_gap_start_seq = None
    
    def generate_quality_metrics(self, recording_date: datetime,
                                 buffer_data: Optional[np.ndarray] = None) -> QualityMetrics:
        """
        Generate quality metrics for a recording session
        
        Args:
            recording_date: Date of recording (midnight UTC)
            buffer_data: Optional buffer data for signal analysis
            
        Returns:
            QualityMetrics object
        """
        # Calculate time coverage
        expected_duration = 86400.0  # 24 hours
        actual_duration = 0.0
        if self.first_packet_time and self.last_packet_time:
            actual_duration = (self.last_packet_time - self.first_packet_time).total_seconds()
        
        # Calculate sample statistics
        expected_samples = 864000  # 24 hours at 10 Hz
        missing_samples = expected_samples - self.samples_received
        completeness = 100.0 * self.samples_received / expected_samples if expected_samples > 0 else 0.0
        
        # Calculate packet loss rate
        total_packets = self.packets_received + self.packets_dropped
        loss_rate = 100.0 * self.packets_dropped / total_packets if total_packets > 0 else 0.0
        
        # Calculate gap statistics
        total_gap_duration = sum(gap.duration_seconds for gap in self.gaps)
        longest_gap = max((gap.duration_seconds for gap in self.gaps), default=0.0)
        avg_gap = total_gap_duration / len(self.gaps) if self.gaps else 0.0
        
        # Signal quality analysis (if buffer provided)
        mean_level = None
        max_level = None
        snr_db = None
        
        if buffer_data is not None:
            # Calculate signal levels (magnitude)
            magnitudes = np.abs(buffer_data)
            valid_magnitudes = magnitudes[~np.isnan(magnitudes)]
            
            if len(valid_magnitudes) > 0:
                mean_level = float(np.mean(valid_magnitudes))
                max_level = float(np.max(valid_magnitudes))
                
                # Estimate SNR (very rough - assumes noise floor is minimum)
                noise_floor = np.percentile(valid_magnitudes, 10)
                signal_level = np.percentile(valid_magnitudes, 90)
                if noise_floor > 0:
                    snr_db = 20 * np.log10(signal_level / noise_floor)
        
        metrics = QualityMetrics(
            recording_date=recording_date.strftime('%Y-%m-%d'),
            channel_name=self.channel_name,
            frequency_hz=self.frequency_hz,
            ssrc=f"0x{self.ssrc:08x}",
            start_time=self.first_packet_time.isoformat() if self.first_packet_time else "",
            end_time=self.last_packet_time.isoformat() if self.last_packet_time else "",
            expected_duration_seconds=expected_duration,
            actual_duration_seconds=actual_duration,
            total_samples_expected=expected_samples,
            total_samples_received=self.samples_received,
            total_samples_missing=missing_samples,
            data_completeness_percent=completeness,
            total_packets_received=self.packets_received,
            total_packets_dropped=self.packets_dropped,
            total_packets_duplicate=self.packets_duplicate,
            packet_loss_rate_percent=loss_rate,
            total_gaps=len(self.gaps),
            total_gap_duration_seconds=total_gap_duration,
            longest_gap_seconds=longest_gap,
            average_gap_seconds=avg_gap,
            mean_signal_level=mean_level,
            max_signal_level=max_level,
            snr_estimate_db=snr_db
        )
        
        return metrics
    
    def write_metadata_file(self, output_dir: Path, recording_date: datetime,
                           buffer_data: Optional[np.ndarray] = None):
        """
        Write metadata JSON file
        
        Args:
            output_dir: Directory to write metadata
            recording_date: Date of recording
            buffer_data: Optional buffer data for signal analysis
        """
        try:
            # Generate metrics
            metrics = self.generate_quality_metrics(recording_date, buffer_data)
            
            # Create metadata structure
            metadata = {
                'version': '1.0',
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'quality_metrics': metrics.to_dict(),
                'gaps': [gap.to_dict() for gap in self.gaps]
            }
            
            # Write to file
            output_dir.mkdir(parents=True, exist_ok=True)
            metadata_file = output_dir / f"{self.channel_name}_{recording_date.strftime('%Y%m%d')}_quality.json"
            
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Wrote metadata to {metadata_file}")
            
            # Also write a human-readable summary
            self._write_summary_file(output_dir, recording_date, metrics)
            
        except Exception as e:
            logger.error(f"Error writing metadata file: {e}", exc_info=True)
    
    def _write_summary_file(self, output_dir: Path, recording_date: datetime,
                           metrics: QualityMetrics):
        """
        Write human-readable summary file
        
        Args:
            output_dir: Directory to write summary
            recording_date: Date of recording
            metrics: Quality metrics
        """
        try:
            summary_file = output_dir / f"{self.channel_name}_{recording_date.strftime('%Y%m%d')}_summary.txt"
            
            with open(summary_file, 'w') as f:
                f.write(f"GRAPE Recording Quality Summary\n")
                f.write(f"{'=' * 70}\n\n")
                
                f.write(f"Channel: {metrics.channel_name}\n")
                f.write(f"Frequency: {metrics.frequency_hz / 1e6:.3f} MHz\n")
                f.write(f"SSRC: {metrics.ssrc}\n")
                f.write(f"Date: {metrics.recording_date}\n\n")
                
                f.write(f"Time Coverage:\n")
                f.write(f"  Start: {metrics.start_time}\n")
                f.write(f"  End: {metrics.end_time}\n")
                f.write(f"  Duration: {metrics.actual_duration_seconds / 3600:.2f} hours "
                       f"({metrics.actual_duration_seconds / metrics.expected_duration_seconds * 100:.1f}%)\n\n")
                
                f.write(f"Data Completeness:\n")
                f.write(f"  Expected samples: {metrics.total_samples_expected:,}\n")
                f.write(f"  Received samples: {metrics.total_samples_received:,}\n")
                f.write(f"  Missing samples: {metrics.total_samples_missing:,}\n")
                f.write(f"  Completeness: {metrics.data_completeness_percent:.2f}%\n\n")
                
                f.write(f"Packet Statistics:\n")
                f.write(f"  Received: {metrics.total_packets_received:,}\n")
                f.write(f"  Dropped: {metrics.total_packets_dropped:,}\n")
                f.write(f"  Duplicate: {metrics.total_packets_duplicate:,}\n")
                f.write(f"  Loss rate: {metrics.packet_loss_rate_percent:.3f}%\n\n")
                
                f.write(f"Gap Analysis:\n")
                f.write(f"  Total gaps: {metrics.total_gaps}\n")
                f.write(f"  Total gap duration: {metrics.total_gap_duration_seconds:.2f} seconds\n")
                f.write(f"  Longest gap: {metrics.longest_gap_seconds:.2f} seconds\n")
                f.write(f"  Average gap: {metrics.average_gap_seconds:.2f} seconds\n\n")
                
                if metrics.mean_signal_level is not None:
                    f.write(f"Signal Quality:\n")
                    f.write(f"  Mean level: {metrics.mean_signal_level:.6f}\n")
                    f.write(f"  Max level: {metrics.max_signal_level:.6f}\n")
                    if metrics.snr_estimate_db is not None:
                        f.write(f"  Estimated SNR: {metrics.snr_estimate_db:.1f} dB\n")
                    f.write("\n")
                
                if self.gaps:
                    f.write(f"Gap Details:\n")
                    f.write(f"{'Start Time':<25} {'Duration (s)':<15} {'Missing Packets':<15}\n")
                    f.write(f"{'-' * 70}\n")
                    for gap in self.gaps[:20]:  # Show first 20 gaps
                        f.write(f"{gap.start_time:<25} {gap.duration_seconds:<15.2f} "
                               f"{gap.missing_packets:<15}\n")
                    if len(self.gaps) > 20:
                        f.write(f"... and {len(self.gaps) - 20} more gaps\n")
            
            logger.info(f"Wrote summary to {summary_file}")
            
        except Exception as e:
            logger.error(f"Error writing summary file: {e}", exc_info=True)
    
    def reset(self):
        """Reset statistics for new recording session"""
        self.gaps.clear()
        self.current_gap_start = None
        self.current_gap_start_seq = None
        self.packets_received = 0
        self.packets_dropped = 0
        self.packets_duplicate = 0
        self.samples_received = 0
        self.first_packet_time = None
        self.last_packet_time = None
        logger.info(f"Reset metadata generator for {self.channel_name}")


def generate_daily_report(metadata_dir: Path, date: datetime, channels: List[str]):
    """
    Generate a daily summary report across all channels
    
    Args:
        metadata_dir: Directory containing metadata files
        date: Date to generate report for
        channels: List of channel names
    """
    try:
        date_str = date.strftime('%Y%m%d')
        report_file = metadata_dir / f"daily_report_{date_str}.txt"
        
        with open(report_file, 'w') as f:
            f.write(f"GRAPE Daily Recording Report\n")
            f.write(f"{'=' * 70}\n")
            f.write(f"Date: {date.strftime('%Y-%m-%d')}\n\n")
            
            total_completeness = 0.0
            total_channels = 0
            
            for channel in channels:
                metadata_file = metadata_dir / f"{channel}_{date_str}_quality.json"
                
                if not metadata_file.exists():
                    f.write(f"\n{channel}: NO DATA\n")
                    continue
                
                # Load metadata
                with open(metadata_file, 'r') as mf:
                    metadata = json.load(mf)
                
                metrics = metadata['quality_metrics']
                
                f.write(f"\n{channel} ({metrics['frequency_hz'] / 1e6:.3f} MHz):\n")
                f.write(f"  Completeness: {metrics['data_completeness_percent']:.2f}%\n")
                f.write(f"  Packet loss: {metrics['packet_loss_rate_percent']:.3f}%\n")
                f.write(f"  Gaps: {metrics['total_gaps']}\n")
                
                total_completeness += metrics['data_completeness_percent']
                total_channels += 1
            
            if total_channels > 0:
                avg_completeness = total_completeness / total_channels
                f.write(f"\n{'=' * 70}\n")
                f.write(f"Average completeness across {total_channels} channels: {avg_completeness:.2f}%\n")
        
        logger.info(f"Generated daily report: {report_file}")
        
    except Exception as e:
        logger.error(f"Error generating daily report: {e}", exc_info=True)

