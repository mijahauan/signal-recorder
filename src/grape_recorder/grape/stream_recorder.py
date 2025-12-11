#!/usr/bin/env python3
"""
Stream Recorder - RadiodStream-based Data Acquisition

Uses ka9q-python's RadiodStream for RTP reception with automatic:
- Packet resequencing
- Gap detection via StreamQuality
- GPS-disciplined timestamps

This replaces the custom RTPReceiver + PacketResequencer with the
standardized ka9q interface used by time-manager.

Architecture:
    radiod → RadiodStream → BinaryArchiveWriter → Phase 1 files
                  ↓
           StreamQuality (gaps, RTP timestamps)
                  ↓
           Gap annotations for Phase 3

Usage:
    from grape_recorder.grape.stream_recorder import StreamRecorder
    
    recorder = StreamRecorder(
        status_address='grape.local',
        data_root=Path('/tmp/grape-test'),
        station_config={'callsign': 'AC0G', ...}
    )
    recorder.start()
    # ... runs until stopped
    recorder.stop()
"""

import logging
import signal
import sys
import time
import json
import threading
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any, Callable
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)

# Import ka9q-python
try:
    from ka9q import (
        discover_channels,
        RadiodStream,
        StreamQuality,
        ChannelInfo,
        GapEvent,
    )
    KA9Q_AVAILABLE = True
except ImportError:
    KA9Q_AVAILABLE = False
    logger.warning("ka9q-python not available - StreamRecorder disabled")


class RecorderState(str, Enum):
    """Recorder operational states."""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ChannelRecorderConfig:
    """Configuration for a single channel recorder."""
    channel_name: str
    frequency_hz: float
    sample_rate: int = 20000
    ssrc: int = 0
    multicast_address: str = ""
    port: int = 5004


@dataclass
class GapRecord:
    """Record of a gap in the data stream."""
    start_sample: int
    duration_samples: int
    unix_time: float
    source: str  # 'rtp_loss', 'late_packet', 'stream_restart'
    
    def to_dict(self) -> Dict:
        return {
            'start_sample': self.start_sample,
            'duration_samples': self.duration_samples,
            'unix_time': self.unix_time,
            'source': self.source
        }


@dataclass
class StreamRecorderConfig:
    """Configuration for the stream recorder."""
    status_address: str
    data_root: Path
    station_config: Dict[str, Any]
    
    # Channel selection (if empty, discover all)
    channel_frequencies: List[float] = field(default_factory=list)
    
    # Sample parameters
    sample_rate: int = 20000
    samples_per_packet: int = 400  # 20ms at 20kHz
    
    # File parameters
    file_duration_sec: int = 60  # 1-minute files
    
    def __post_init__(self):
        self.data_root = Path(self.data_root)


class ChannelStreamRecorder:
    """
    Records a single channel using RadiodStream.
    
    Receives IQ samples via callback, writes to binary files,
    and tracks gap information from StreamQuality.
    """
    
    def __init__(
        self,
        channel_info: ChannelInfo,
        data_root: Path,
        channel_name: str,
        station_config: Dict[str, Any]
    ):
        """
        Initialize channel recorder.
        
        Args:
            channel_info: ka9q ChannelInfo for this channel
            data_root: Root data directory
            channel_name: Human-readable channel name
            station_config: Station metadata
        """
        self.channel_info = channel_info
        self.data_root = data_root
        self.channel_name = channel_name
        self.station_config = station_config
        
        self.stream: Optional[RadiodStream] = None
        self.state = RecorderState.IDLE
        self._lock = threading.Lock()
        
        # Initialize paths
        from ..paths import GRAPEPaths, channel_name_to_dir
        self.paths = GRAPEPaths(data_root)
        self.channel_dir = channel_name_to_dir(channel_name)
        
        # Initialize binary archive writer
        from .binary_archive_writer import BinaryArchiveWriter
        
        raw_buffer_dir = self.paths.get_raw_buffer_dir(channel_name)
        raw_buffer_dir.mkdir(parents=True, exist_ok=True)
        
        self.archive_writer = BinaryArchiveWriter(
            output_dir=raw_buffer_dir,
            channel_name=channel_name,
            sample_rate=channel_info.sample_rate,
            file_duration_sec=60
        )
        
        # Gap tracking
        self.gaps: List[GapRecord] = []
        self.current_minute_gaps: List[GapRecord] = []
        
        # Statistics
        self.samples_received = 0
        self.samples_written = 0
        self.packets_received = 0
        self.start_time: Optional[float] = None
        self.last_sample_time: float = 0.0
        self.last_quality: Optional[StreamQuality] = None
        
        logger.info(f"ChannelStreamRecorder initialized: {channel_name}")
        logger.info(f"  SSRC: {channel_info.ssrc}")
        logger.info(f"  Frequency: {channel_info.frequency / 1e6:.3f} MHz")
        logger.info(f"  Sample rate: {channel_info.sample_rate} Hz")
    
    def start(self):
        """Start recording this channel."""
        with self._lock:
            if self.state != RecorderState.IDLE:
                logger.warning(f"{self.channel_name}: Cannot start in state {self.state}")
                return
            
            self.state = RecorderState.STARTING
        
        # Calculate samples per packet for 20kHz @ 20ms blocktime
        samples_per_packet = int(self.channel_info.sample_rate * 0.020)
        
        # Create RadiodStream with sample callback
        self.stream = RadiodStream(
            channel=self.channel_info,
            on_samples=self._on_samples,
            samples_per_packet=samples_per_packet,
            resequence_buffer_size=64,
            deliver_interval_packets=5  # Deliver every 100ms
        )
        
        self.stream.start()
        self.start_time = time.time()
        
        with self._lock:
            self.state = RecorderState.RUNNING
        
        logger.info(f"{self.channel_name}: Recording started")
    
    def stop(self):
        """Stop recording this channel."""
        with self._lock:
            if self.state != RecorderState.RUNNING:
                return
            
            self.state = RecorderState.STOPPING
        
        if self.stream:
            self.stream.stop()
        
        # Flush any pending data
        self.archive_writer.flush()
        
        # Write final gap summary
        self._write_gap_summary()
        
        with self._lock:
            self.state = RecorderState.IDLE
        
        logger.info(f"{self.channel_name}: Recording stopped")
        logger.info(f"  Samples received: {self.samples_received}")
        logger.info(f"  Gaps detected: {len(self.gaps)}")
    
    def _on_samples(self, samples: np.ndarray, quality: StreamQuality):
        """
        Callback for RadiodStream sample delivery.
        
        Args:
            samples: Complex64 IQ samples
            quality: StreamQuality with gap and timing info
        """
        try:
            with self._lock:
                if self.state != RecorderState.RUNNING:
                    return
            
            now = time.time()
            self.samples_received += len(samples)
            self.packets_received = quality.rtp_packets_received
            self.last_sample_time = now
            self.last_quality = quality
            
            # Extract gap information from StreamQuality
            if quality.batch_gaps:
                for gap in quality.batch_gaps:
                    gap_record = GapRecord(
                        start_sample=gap.start_sample,
                        duration_samples=gap.duration_samples,
                        unix_time=now,
                        source=gap.source.name if hasattr(gap, 'source') else 'unknown'
                    )
                    self.gaps.append(gap_record)
                    self.current_minute_gaps.append(gap_record)
            
            # Write samples to binary archive
            # Get RTP timestamp from quality
            rtp_timestamp = quality.last_rtp_timestamp
            
            samples_written = self.archive_writer.write_samples(
                samples=samples,
                rtp_timestamp=rtp_timestamp,
                system_time=now,
                gaps=self.current_minute_gaps if self.current_minute_gaps else None
            )
            
            self.samples_written += samples_written
            
            # Check for minute boundary - clear per-minute gaps
            current_minute = int(now / 60)
            if hasattr(self, '_last_minute') and current_minute != self._last_minute:
                self.current_minute_gaps = []
            self._last_minute = current_minute
            
        except Exception as e:
            logger.error(f"{self.channel_name}: Sample callback error: {e}", exc_info=True)
    
    def _write_gap_summary(self):
        """Write gap summary for the session."""
        if not self.gaps:
            return
        
        gap_dir = self.data_root / 'phase2' / self.channel_dir / 'gaps'
        gap_dir.mkdir(parents=True, exist_ok=True)
        
        session_id = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        gap_file = gap_dir / f'gaps_{session_id}.json'
        
        summary = {
            'channel': self.channel_name,
            'session_start': self.start_time,
            'session_end': time.time(),
            'total_gaps': len(self.gaps),
            'total_gap_samples': sum(g.duration_samples for g in self.gaps),
            'gaps': [g.to_dict() for g in self.gaps]
        }
        
        with open(gap_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"{self.channel_name}: Wrote gap summary to {gap_file}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        with self._lock:
            uptime = time.time() - self.start_time if self.start_time else 0
            
            stats = {
                'channel_name': self.channel_name,
                'state': self.state.value,
                'samples_received': self.samples_received,
                'samples_written': self.samples_written,
                'packets_received': self.packets_received,
                'gaps_detected': len(self.gaps),
                'uptime_seconds': uptime,
                'last_sample_age': time.time() - self.last_sample_time if self.last_sample_time else 0
            }
            
            if self.last_quality:
                stats['rtp_packets_lost'] = self.last_quality.rtp_packets_lost
                stats['total_gap_samples'] = self.last_quality.total_gaps_filled
            
            return stats
    
    def is_healthy(self, timeout_sec: float = 60.0) -> bool:
        """Check if channel is receiving data."""
        with self._lock:
            if self.last_sample_time == 0:
                return True  # Not started yet
            
            silence = time.time() - self.last_sample_time
            return silence < timeout_sec


class StreamRecorder:
    """
    Multi-channel stream recorder using ka9q RadiodStream.
    
    Discovers radiod channels and creates a ChannelStreamRecorder
    for each configured channel.
    """
    
    def __init__(self, config: StreamRecorderConfig):
        """
        Initialize stream recorder.
        
        Args:
            config: StreamRecorderConfig with all settings
        """
        if not KA9Q_AVAILABLE:
            raise ImportError(
                "ka9q-python required for StreamRecorder. "
                "Install with: pip install ka9q-python"
            )
        
        self.config = config
        self.state = RecorderState.IDLE
        self._lock = threading.Lock()
        
        # Channel recorders
        self.channels: Dict[int, ChannelStreamRecorder] = {}  # ssrc -> recorder
        
        # Status
        self.start_time: Optional[float] = None
        self.status_file = config.data_root / 'status' / 'stream-recorder-status.json'
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Signal handling
        self._shutdown_event = threading.Event()
        
        logger.info("StreamRecorder initialized")
        logger.info(f"  Status address: {config.status_address}")
        logger.info(f"  Data root: {config.data_root}")
    
    def discover_and_init_channels(self) -> int:
        """
        Discover radiod channels and initialize recorders.
        
        Returns:
            Number of channels initialized
        """
        logger.info(f"Discovering channels from {self.config.status_address}...")
        
        try:
            # Discover all channels
            channels = discover_channels(
                status_address=self.config.status_address,
                listen_duration=3.0
            )
            
            logger.info(f"Discovered {len(channels)} channels")
            
            # Filter to configured frequencies if specified
            target_frequencies = set(self.config.channel_frequencies) if self.config.channel_frequencies else None
            
            for ssrc, channel_info in channels.items():
                freq_hz = channel_info.frequency
                
                # Skip if not in target list
                if target_frequencies and freq_hz not in target_frequencies:
                    continue
                
                # Determine channel name from frequency
                channel_name = self._frequency_to_channel_name(freq_hz)
                if not channel_name:
                    logger.debug(f"Skipping unknown frequency: {freq_hz / 1e6:.3f} MHz")
                    continue
                
                # Create channel recorder
                recorder = ChannelStreamRecorder(
                    channel_info=channel_info,
                    data_root=self.config.data_root,
                    channel_name=channel_name,
                    station_config=self.config.station_config
                )
                
                self.channels[ssrc] = recorder
                logger.info(f"  Initialized: {channel_name} (SSRC {ssrc:x})")
            
            return len(self.channels)
            
        except Exception as e:
            logger.error(f"Channel discovery failed: {e}", exc_info=True)
            return 0
    
    def _frequency_to_channel_name(self, freq_hz: float) -> Optional[str]:
        """Map frequency to standard channel name."""
        # Standard GRAPE frequencies
        freq_map = {
            2500000: 'WWV 2.5 MHz',
            3330000: 'CHU 3.33 MHz',
            5000000: 'WWV 5 MHz',
            7850000: 'CHU 7.85 MHz',
            10000000: 'WWV 10 MHz',
            14670000: 'CHU 14.67 MHz',
            15000000: 'WWV 15 MHz',
            20000000: 'WWV 20 MHz',
            25000000: 'WWV 25 MHz',
        }
        
        # Allow 1 kHz tolerance
        for target_freq, name in freq_map.items():
            if abs(freq_hz - target_freq) < 1000:
                return name
        
        return None
    
    def start(self):
        """Start all channel recorders."""
        with self._lock:
            if self.state != RecorderState.IDLE:
                logger.warning(f"Cannot start in state {self.state}")
                return
            
            self.state = RecorderState.STARTING
        
        # Discover channels if not already done
        if not self.channels:
            count = self.discover_and_init_channels()
            if count == 0:
                logger.error("No channels initialized - cannot start")
                with self._lock:
                    self.state = RecorderState.ERROR
                return
        
        # Start all recorders
        for ssrc, recorder in self.channels.items():
            try:
                recorder.start()
            except Exception as e:
                logger.error(f"Failed to start channel {ssrc}: {e}")
        
        self.start_time = time.time()
        
        with self._lock:
            self.state = RecorderState.RUNNING
        
        # Start status writer thread
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()
        
        logger.info(f"StreamRecorder started with {len(self.channels)} channels")
    
    def stop(self):
        """Stop all channel recorders."""
        with self._lock:
            if self.state != RecorderState.RUNNING:
                return
            
            self.state = RecorderState.STOPPING
        
        self._shutdown_event.set()
        
        # Stop all recorders
        for ssrc, recorder in self.channels.items():
            try:
                recorder.stop()
            except Exception as e:
                logger.error(f"Error stopping channel {ssrc}: {e}")
        
        with self._lock:
            self.state = RecorderState.IDLE
        
        logger.info("StreamRecorder stopped")
    
    def run(self):
        """Run recorder until interrupted."""
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.start()
        
        if self.state != RecorderState.RUNNING:
            logger.error("Failed to start - exiting")
            return
        
        logger.info("StreamRecorder running. Press Ctrl+C to stop.")
        
        try:
            while not self._shutdown_event.is_set():
                self._shutdown_event.wait(timeout=1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self._shutdown_event.set()
    
    def _status_loop(self):
        """Periodically write status file."""
        while not self._shutdown_event.is_set():
            try:
                self._write_status()
            except Exception as e:
                logger.error(f"Status write error: {e}")
            
            self._shutdown_event.wait(timeout=10.0)
    
    def _write_status(self):
        """Write current status to JSON file."""
        status = {
            'service': 'stream_recorder',
            'version': '2.0',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime_seconds': int(time.time() - self.start_time) if self.start_time else 0,
            'state': self.state.value,
            'channels': {},
            'overall': {
                'channels_active': 0,
                'channels_total': len(self.channels),
                'total_samples': 0,
                'total_gaps': 0
            }
        }
        
        for ssrc, recorder in self.channels.items():
            stats = recorder.get_stats()
            status['channels'][hex(ssrc)] = stats
            
            if stats.get('samples_received', 0) > 0:
                status['overall']['channels_active'] += 1
            status['overall']['total_samples'] += stats.get('samples_received', 0)
            status['overall']['total_gaps'] += stats.get('gaps_detected', 0)
        
        # Atomic write
        temp_file = self.status_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(status, f, indent=2)
        temp_file.replace(self.status_file)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics."""
        stats = {
            'state': self.state.value,
            'channels': len(self.channels),
            'uptime_seconds': time.time() - self.start_time if self.start_time else 0
        }
        
        total_samples = 0
        total_gaps = 0
        
        for recorder in self.channels.values():
            ch_stats = recorder.get_stats()
            total_samples += ch_stats.get('samples_received', 0)
            total_gaps += ch_stats.get('gaps_detected', 0)
        
        stats['total_samples'] = total_samples
        stats['total_gaps'] = total_gaps
        
        return stats


def main():
    """CLI entry point for stream recorder."""
    import argparse
    
    parser = argparse.ArgumentParser(description='GRAPE Stream Recorder')
    parser.add_argument('--status-address', default='grape.local',
                       help='radiod status address')
    parser.add_argument('--data-root', default='/tmp/grape-test',
                       help='Data root directory')
    parser.add_argument('--callsign', default='UNKNOWN',
                       help='Station callsign')
    parser.add_argument('--grid', default='XX00xx',
                       help='Grid square')
    
    args = parser.parse_args()
    
    config = StreamRecorderConfig(
        status_address=args.status_address,
        data_root=Path(args.data_root),
        station_config={
            'callsign': args.callsign,
            'grid_square': args.grid
        }
    )
    
    recorder = StreamRecorder(config)
    recorder.run()


if __name__ == '__main__':
    main()
