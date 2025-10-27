#!/usr/bin/env python3
"""
GRAPE RTP→Digital RF Recorder

Direct RTP reception with scipy decimation and Digital RF output.
Replaces the pcmrecord-based approach.
"""

import socket
import struct
import threading
import time
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, Callable
from dataclasses import dataclass
from scipy import signal as scipy_signal

try:
    import digital_rf as drf
    HAS_DIGITAL_RF = True
except ImportError:
    HAS_DIGITAL_RF = False
    logging.warning("digital_rf not available - Digital RF output will not work")

from .grape_metadata import GRAPEMetadataGenerator

logger = logging.getLogger(__name__)

# Global stats file for web UI monitoring
STATS_FILE = Path('/tmp/signal-recorder-stats.json')


@dataclass
class RTPHeader:
    """Parsed RTP header"""
    version: int
    padding: bool
    extension: bool
    csrc_count: int
    marker: bool
    payload_type: int
    sequence: int
    timestamp: int
    ssrc: int


class RTPReceiver:
    """
    Receives RTP packets from multicast and demultiplexes by SSRC
    """
    
    def __init__(self, multicast_address: str, port: int = 5004):
        """
        Initialize RTP receiver
        
        Args:
            multicast_address: Multicast group address
            port: RTP port (default 5004)
        """
        self.multicast_address = multicast_address
        self.port = port
        self.running = False
        self.socket = None
        self.thread = None
        self.callbacks: Dict[int, Callable] = {}  # ssrc -> callback
        
    def register_callback(self, ssrc: int, callback: Callable):
        """Register callback for specific SSRC"""
        self.callbacks[ssrc] = callback
        logger.info(f"Registered callback for SSRC {ssrc}")
        
    def start(self):
        """Start receiving RTP packets"""
        if self.running:
            logger.warning("RTP receiver already running")
            return
            
        # Create UDP socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind to port
        self.socket.bind(('', self.port))
        
        # Join multicast group
        try:
            # Try loopback first (for local radiod)
            mreq = struct.pack("4s4s", 
                              socket.inet_aton(self.multicast_address),
                              socket.inet_aton('127.0.0.1'))
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            logger.info(f"Joined multicast {self.multicast_address} on loopback")
        except OSError:
            # Fallback to any interface
            mreq = struct.pack("4sl",
                              socket.inet_aton(self.multicast_address),
                              socket.INADDR_ANY)
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            logger.info(f"Joined multicast {self.multicast_address} on all interfaces")
        
        # Start receiver thread
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        logger.info(f"RTP receiver started on {self.multicast_address}:{self.port}")
        
    def stop(self):
        """Stop receiving"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.socket:
            self.socket.close()
        logger.info("RTP receiver stopped")
        
    def _receive_loop(self):
        """Main packet reception loop"""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(8192)
                
                # Parse RTP header
                header = self._parse_rtp_header(data)
                if not header:
                    continue
                    
                # Extract payload (after 12-byte header)
                payload = data[12:]
                
                # Dispatch to appropriate callback
                callback = self.callbacks.get(header.ssrc)
                if callback:
                    callback(header, payload)
                    
            except Exception as e:
                if self.running:
                    logger.error(f"Error receiving RTP packet: {e}")
                    
    @staticmethod
    def _parse_rtp_header(data: bytes) -> Optional[RTPHeader]:
        """Parse RTP packet header"""
        if len(data) < 12:
            return None
            
        # Parse fixed header (12 bytes)
        b0, b1, seq, ts, ssrc = struct.unpack('>BBHII', data[:12])
        
        version = (b0 >> 6) & 0x3
        padding = bool((b0 >> 5) & 0x1)
        extension = bool((b0 >> 4) & 0x1)
        csrc_count = b0 & 0xF
        
        marker = bool((b1 >> 7) & 0x1)
        payload_type = b1 & 0x7F
        
        if version != 2:
            return None
            
        return RTPHeader(
            version=version,
            padding=padding,
            extension=extension,
            csrc_count=csrc_count,
            marker=marker,
            payload_type=payload_type,
            sequence=seq,
            timestamp=ts,
            ssrc=ssrc
        )


class Resampler:
    """
    Scipy-based anti-aliasing filter and decimator
    12 kHz IQ → 10 Hz IQ
    """
    
    def __init__(self, input_rate: int = 12000, output_rate: int = 10):
        """
        Initialize resampler
        
        Args:
            input_rate: Input sample rate (Hz)
            output_rate: Output sample rate (Hz)
        """
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.decimation_factor = input_rate // output_rate
        
        # Design anti-aliasing filter (8th order Butterworth)
        # Cutoff at Nyquist frequency of output rate
        nyquist = output_rate / 2.0
        cutoff = nyquist / (input_rate / 2.0)  # Normalized frequency
        
        self.sos = scipy_signal.butter(8, cutoff, btype='low', output='sos')
        
        # Filter state (for continuous filtering across packets)
        self.zi_i = scipy_signal.sosfilt_zi(self.sos)
        self.zi_q = scipy_signal.sosfilt_zi(self.sos)
        
        logger.info(f"Resampler initialized: {input_rate} Hz → {output_rate} Hz "
                   f"(decimation factor {self.decimation_factor})")
        
    def resample(self, iq_samples: np.ndarray) -> np.ndarray:
        """
        Resample IQ data
        
        Args:
            iq_samples: Complex IQ samples at input rate
            
        Returns:
            Resampled complex IQ samples at output rate
        """
        # Split into I and Q
        i_samples = np.real(iq_samples).astype(np.float32)
        q_samples = np.imag(iq_samples).astype(np.float32)
        
        # Apply anti-aliasing filter
        i_filtered, self.zi_i = scipy_signal.sosfilt(self.sos, i_samples, zi=self.zi_i)
        q_filtered, self.zi_q = scipy_signal.sosfilt(self.sos, q_samples, zi=self.zi_q)
        
        # Decimate
        i_decimated = i_filtered[::self.decimation_factor]
        q_decimated = q_filtered[::self.decimation_factor]
        
        # Recombine into complex
        return i_decimated + 1j * q_decimated


class DailyBuffer:
    """
    UTC-aligned 24-hour buffer for Digital RF output
    """
    
    def __init__(self, sample_rate: int = 10):
        """
        Initialize daily buffer
        
        Args:
            sample_rate: Sample rate (Hz)
        """
        self.sample_rate = sample_rate
        self.samples_per_day = sample_rate * 86400  # 864,000 samples for 10 Hz
        
        # Initialize buffer with NaN (for gap detection)
        self.buffer = np.full(self.samples_per_day, np.nan, dtype=np.complex64)
        self.current_day = None
        
        logger.info(f"Daily buffer initialized: {self.samples_per_day} samples @ {sample_rate} Hz")
        
    def add_samples(self, timestamp: float, samples: np.ndarray) -> Optional[np.ndarray]:
        """
        Add samples to buffer at specified timestamp
        
        Args:
            timestamp: Unix timestamp of first sample
            samples: Complex IQ samples
            
        Returns:
            Completed day's data if midnight rollover occurred, else None
        """
        # Convert to UTC datetime
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        day = dt.date()
        
        # Check for midnight rollover
        completed_day = None
        if self.current_day is not None and day != self.current_day:
            logger.info(f"Midnight rollover detected: {self.current_day} → {day}")
            completed_day = (self.current_day, self.buffer.copy())
            # Reset buffer
            self.buffer.fill(np.nan)
            
        self.current_day = day
        
        # Calculate sample index within day
        seconds_since_midnight = (dt.hour * 3600) + (dt.minute * 60) + dt.second + (dt.microsecond / 1e6)
        start_idx = int(seconds_since_midnight * self.sample_rate)
        
        # Place samples in buffer
        end_idx = start_idx + len(samples)
        if end_idx <= self.samples_per_day:
            self.buffer[start_idx:end_idx] = samples
        else:
            # Samples span across midnight - split them
            samples_today = self.samples_per_day - start_idx
            self.buffer[start_idx:] = samples[:samples_today]
            # Remaining samples go to next day
            
        return completed_day
        
    def get_buffer(self) -> np.ndarray:
        """Get current buffer"""
        return self.buffer.copy()


class GRAPEChannelRecorder:
    """
    Per-channel GRAPE recorder with Digital RF output
    """
    
    def __init__(self, ssrc: int, frequency_hz: float, channel_name: str,
                 output_dir: Path, station_config: dict):
        """
        Initialize channel recorder
        
        Args:
            ssrc: RTP SSRC
            frequency_hz: Center frequency
            channel_name: Channel name (e.g., "WWV_2_5")
            output_dir: Base output directory
            station_config: Station configuration dict
        """
        self.ssrc = ssrc
        self.frequency_hz = frequency_hz
        self.channel_name = channel_name
        self.station_config = station_config
        
        # Create channel-specific output directory
        self.channel_dir = output_dir / channel_name
        self.channel_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize components
        self.resampler = Resampler(input_rate=12000, output_rate=10)
        self.daily_buffer = DailyBuffer(sample_rate=10)
        self.metadata_gen = GRAPEMetadataGenerator(channel_name, frequency_hz, ssrc)
        
        # Sample accumulator (for efficient resampling)
        self.sample_accumulator = []
        self.samples_per_packet = 1200  # Accumulate ~100ms before resampling
        
        # RTP timestamp tracking
        self.last_sequence = None
        self.last_timestamp = None
        self.rtp_sample_rate = 12000  # RTP timestamp rate
        
        logger.info(f"Channel recorder initialized: {channel_name} (SSRC {ssrc}, {frequency_hz/1e6:.2f} MHz)")
        
    def process_rtp_packet(self, header: RTPHeader, payload: bytes):
        """
        Process incoming RTP packet
        
        Args:
            header: Parsed RTP header
            payload: RTP payload (IQ samples as float32)
        """
        # Track packet metadata
        self.packets_received = getattr(self, 'packets_received', 0) + 1
        self.samples_received = getattr(self, 'samples_received', 0)
        self.last_packet_time = time.time()  # For freshness monitoring
        
        if self.last_sequence is not None:
            expected_seq = (self.last_sequence + 1) & 0xFFFF
            if header.sequence != expected_seq:
                dropped = (header.sequence - expected_seq) & 0xFFFF
                self.packets_dropped = getattr(self, 'packets_dropped', 0) + dropped
                self.metadata_gen.add_packet_event(
                    timestamp=header.timestamp / self.rtp_sample_rate,
                    sequence=header.sequence,
                    sample_count=0,
                    is_dropped=True
                )
                logger.warning(f"{self.channel_name}: Dropped {dropped} packets "
                             f"(seq {expected_seq} → {header.sequence})")
        else:
            self.packets_dropped = 0
                
        self.last_sequence = header.sequence
        self.last_timestamp = header.timestamp
        
        # Parse IQ samples (float32 I/Q pairs)
        num_samples = len(payload) // 8  # 2 floats per sample
        if len(payload) % 8 != 0:
            logger.warning(f"{self.channel_name}: Payload size not multiple of 8")
            return
            
        # Unpack as interleaved I/Q float32
        samples = np.frombuffer(payload, dtype=np.float32).reshape(-1, 2)
        iq_samples = samples[:, 0] + 1j * samples[:, 1]
        
        # Add to accumulator
        self.sample_accumulator.append(iq_samples)
        accumulated_samples = sum(len(s) for s in self.sample_accumulator)
        
        # Resample when we have enough samples
        if accumulated_samples >= self.samples_per_packet:
            # Concatenate accumulated samples
            all_samples = np.concatenate(self.sample_accumulator)
            self.sample_accumulator = []
            
            # Resample
            resampled = self.resampler.resample(all_samples)
            
            # Convert RTP timestamp to Unix time
            # RTP timestamp is in samples at 12 kHz
            unix_time = time.time()  # Simplified - should use NTP or GPS time
            
            # Add to daily buffer
            completed_day = self.daily_buffer.add_samples(unix_time, resampled)
            
            # Write completed day to Digital RF
            if completed_day and HAS_DIGITAL_RF:
                day_date, day_data = completed_day
                self._write_digital_rf(day_date, day_data)
                
            # Track in metadata
            self.samples_received += len(resampled)
            self.metadata_gen.add_packet_event(
                timestamp=unix_time,
                sequence=header.sequence,
                sample_count=len(iq_samples),
                is_dropped=False
            )
            
    def _write_digital_rf(self, day_date, data: np.ndarray):
        """
        Write completed day to Digital RF format
        
        Args:
            day_date: Date of the data
            data: Complex IQ samples for the full day
        """
        try:
            # Create Digital RF writer
            # Directory structure: output_dir/channel_name/
            drf_dir = self.channel_dir
            
            # Digital RF expects interleaved I/Q as separate samples
            # Convert complex to 2-channel real (I, Q)
            iq_interleaved = np.empty(len(data) * 2, dtype=np.float32)
            iq_interleaved[0::2] = np.real(data)
            iq_interleaved[1::2] = np.imag(data)
            
            # Create writer
            writer = drf.DigitalRFWriter(
                str(drf_dir),
                dtype=np.float32,
                subdir_cadence_secs=86400,  # 1 day subdirectories
                file_cadence_millisecs=3600000,  # 1 hour files
                start_global_index=0,
                sample_rate_numerator=10,
                sample_rate_denominator=1,
                is_complex=True,
                num_subchannels=1,
                is_continuous=True,
                compression_level=9,
                marching_periods=True
            )
            
            # Write data
            # Start time: midnight UTC of the day
            day_start = datetime.combine(day_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            start_sample = int(day_start.timestamp() * 10)  # Sample index at 10 Hz
            
            writer.rf_write(iq_interleaved, start_sample)
            
            # Write metadata
            metadata = {
                'callsign': self.station_config.get('callsign', 'UNKNOWN'),
                'grid_square': self.station_config.get('grid_square', 'UNKNOWN'),
                'receiver_name': self.station_config.get('instrument_id', 'UNKNOWN'),
                'center_frequencies': [self.frequency_hz],
                'sample_rate': 10.0,
                'date': day_date.isoformat()
            }
            
            writer.rf_write_metadata(metadata, start_sample)
            
            logger.info(f"{self.channel_name}: Wrote Digital RF for {day_date} "
                       f"({len(data)} samples, {len(data)/864000*100:.1f}% complete)")
                       
        except Exception as e:
            logger.error(f"{self.channel_name}: Failed to write Digital RF: {e}")


class GRAPERecorderManager:
    """
    Manager for multiple GRAPE channel recorders
    """
    
    def __init__(self, config: dict):
        """
        Initialize recorder manager
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.recorders: Dict[int, GRAPEChannelRecorder] = {}
        self.rtp_receiver = None
        self.running = False
        
    def start(self):
        """Start recording all configured channels"""
        if self.running:
            logger.warning("Recorder already running")
            return
            
        # Get configuration
        station_config = self.config.get('station', {})
        recorder_config = self.config.get('recorder', {})
        channels = recorder_config.get('channels', [])
        
        # Get multicast address
        ka9q_config = self.config.get('ka9q', {})
        multicast_address = ka9q_config.get('status_address', '239.192.152.141')
        if ':' in multicast_address:
            multicast_address = multicast_address.split(':')[0]
            
        # Create output directory
        output_dir = Path(recorder_config.get('archive_dir', '/tmp/grape-data'))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create RTP receiver
        self.rtp_receiver = RTPReceiver(multicast_address, port=5004)
        
        # Create recorder for each channel
        for channel in channels:
            if not channel.get('enabled', True):
                continue
                
            ssrc = channel['ssrc']
            frequency_hz = channel['frequency_hz']
            channel_name = channel.get('description', f'FREQ_{frequency_hz/1e6:.3f}')
            
            # Create recorder
            recorder = GRAPEChannelRecorder(
                ssrc=ssrc,
                frequency_hz=frequency_hz,
                channel_name=channel_name,
                output_dir=output_dir,
                station_config=station_config
            )
            recorder.start_time = time.time()
            recorder.packets_received = 0
            recorder.packets_dropped = 0
            recorder.samples_received = 0
            
            # Register with RTP receiver
            self.rtp_receiver.register_callback(ssrc, recorder.process_rtp_packet)
            
            self.recorders[ssrc] = recorder
            logger.info(f"Started recorder for {channel_name}")
            
        # Start RTP receiver
        self.rtp_receiver.start()
        self.running = True
        logger.info(f"GRAPE recorder manager started with {len(self.recorders)} channels")
        
    def stop(self):
        """Stop all recorders"""
        if not self.running:
            return
            
        self.running = False
        
        if self.rtp_receiver:
            self.rtp_receiver.stop()
            
        logger.info("GRAPE recorder manager stopped")
        
    def get_status(self) -> dict:
        """Get status of all recorders with comprehensive metrics"""
        import json
        
        current_time = time.time()
        
        status = {
            'running': self.running,
            'channels': len(self.recorders),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'recording_duration_sec': 0,
            'total_data_mb': 0.0,
            'total_packets_received': 0,
            'total_packets_dropped': 0,
            'healthy_channels': 0,
            'warning_channels': 0,
            'error_channels': 0,
            'recorders': {}
        }
        
        # Calculate system-wide start time
        if self.recorders:
            earliest_start = min(getattr(rec, 'start_time', current_time) 
                               for rec in self.recorders.values())
            status['recording_duration_sec'] = int(current_time - earliest_start)
        
        for ssrc, rec in self.recorders.items():
            # Basic metrics
            packets_received = getattr(rec, 'packets_received', 0)
            packets_dropped = getattr(rec, 'packets_dropped', 0)
            samples_received = getattr(rec, 'samples_received', 0)
            start_time = getattr(rec, 'start_time', current_time)
            elapsed = current_time - start_time
            
            # Calculate derived metrics
            total_packets = packets_received + packets_dropped
            packet_loss_pct = (packets_dropped / total_packets * 100) if total_packets > 0 else 0.0
            
            expected_samples = int(elapsed * 10)  # 10 Hz output rate
            completeness_pct = min(100.0, (samples_received / expected_samples * 100)) if expected_samples > 0 else 0.0
            
            # Data rate calculation (last 30 seconds)
            samples_rate = samples_received / elapsed if elapsed > 0 else 0.0
            data_rate_kbps = samples_rate * 8 / 1024  # Complex64 = 8 bytes per sample
            
            # Check for stale data (no packets in last 10 seconds)
            last_packet_time = getattr(rec, 'last_packet_time', start_time)
            data_freshness_sec = int(current_time - last_packet_time)
            is_stale = data_freshness_sec > 10
            
            # Count files in output directory
            file_count = 0
            total_size_bytes = 0
            try:
                if rec.channel_dir.exists():
                    for f in rec.channel_dir.rglob('*.h5'):
                        file_count += 1
                        total_size_bytes += f.stat().st_size
            except Exception as e:
                logger.debug(f"Could not scan output dir: {e}")
            
            total_size_mb = total_size_bytes / (1024 * 1024)
            
            # Health status determination
            if is_stale:
                health_status = 'error'
                health_message = f'No data for {data_freshness_sec}s'
            elif completeness_pct < 95:
                health_status = 'error'
                health_message = f'Low completeness: {completeness_pct:.1f}%'
            elif packet_loss_pct > 5:
                health_status = 'error'
                health_message = f'High packet loss: {packet_loss_pct:.1f}%'
            elif completeness_pct < 99:
                health_status = 'warning'
                health_message = f'Completeness: {completeness_pct:.1f}%'
            elif packet_loss_pct > 1:
                health_status = 'warning'
                health_message = f'Packet loss: {packet_loss_pct:.1f}%'
            else:
                health_status = 'healthy'
                health_message = 'Operating normally'
            
            # Update system-wide counters
            status['total_packets_received'] += packets_received
            status['total_packets_dropped'] += packets_dropped
            status['total_data_mb'] += total_size_mb
            
            if health_status == 'healthy':
                status['healthy_channels'] += 1
            elif health_status == 'warning':
                status['warning_channels'] += 1
            else:
                status['error_channels'] += 1
            
            # Per-channel status
            rec_status = {
                'channel_name': rec.channel_name,
                'frequency_hz': rec.frequency_hz,
                'frequency_mhz': rec.frequency_hz / 1e6,
                
                # Data flow
                'packets_received': packets_received,
                'packets_dropped': packets_dropped,
                'packet_loss_pct': round(packet_loss_pct, 2),
                
                # Samples
                'samples_received': samples_received,
                'expected_samples': expected_samples,
                'completeness_pct': round(completeness_pct, 2),
                'samples_per_sec': round(samples_rate, 2),
                
                # Data output
                'output_dir': str(rec.channel_dir),
                'file_count': file_count,
                'total_size_mb': round(total_size_mb, 2),
                'data_rate_kbps': round(data_rate_kbps, 2),
                
                # Timing
                'recording_duration_sec': int(elapsed),
                'data_freshness_sec': data_freshness_sec,
                'is_stale': is_stale,
                
                # Health
                'health_status': health_status,
                'health_message': health_message
            }
            
            # Add gap information if available
            if hasattr(rec, 'metadata_gen'):
                rec_status['gap_count'] = len(getattr(rec.metadata_gen, 'gaps', []))
            
            status['recorders'][ssrc] = rec_status
        
        # Calculate aggregate packet loss
        total_pkts = status['total_packets_received'] + status['total_packets_dropped']
        status['aggregate_packet_loss_pct'] = round(
            (status['total_packets_dropped'] / total_pkts * 100) if total_pkts > 0 else 0.0, 
            2
        )
        
        # Write to stats file for web UI
        try:
            with open(STATS_FILE, 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write stats file: {e}")
        
        return status
