"""
GRAPE RTP Recorder Module

Direct RTP→Digital RF pipeline for GRAPE ionospheric research.
Records IQ samples from ka9q-radio RTP multicast streams, processes them into
24-hour 10 Hz Digital RF datasets with timestamp-based sample placement.

Key Features:
- Direct RTP packet reception and parsing (no pcmrecord dependency)
- Per-SSRC channel separation
- RTP timestamp-based sample placement in UTC-aligned buffers
- Resampling from 12 kHz → 10 Hz with anti-aliasing
- Data loss detection and gap tracking
- Digital RF format output compatible with HamSCI PSWS server
- Metadata generation with quality metrics
"""

import socket
import struct
import logging
import threading
import time
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
import json
import uuid

try:
    import digital_rf as drf
except ImportError:
    drf = None
    logging.warning("digital_rf not available - Digital RF output disabled")

try:
    from scipy import signal as scipy_signal
except ImportError:
    scipy_signal = None
    logging.warning("scipy not available - resampling disabled")

logger = logging.getLogger(__name__)


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
    
    @classmethod
    def parse(cls, data: bytes) -> Tuple['RTPHeader', int]:
        """
        Parse RTP header from packet data
        
        Args:
            data: Raw packet bytes
            
        Returns:
            Tuple of (RTPHeader, header_length)
        """
        if len(data) < 12:
            raise ValueError("Packet too short for RTP header")
        
        # Parse first 32-bit word
        word0 = struct.unpack('!I', data[0:4])[0]
        version = (word0 >> 30) & 0x3
        padding = bool((word0 >> 29) & 0x1)
        extension = bool((word0 >> 28) & 0x1)
        csrc_count = (word0 >> 24) & 0xF
        marker = bool((word0 >> 23) & 0x1)
        payload_type = (word0 >> 16) & 0x7F
        sequence = word0 & 0xFFFF
        
        # Parse timestamp and SSRC
        timestamp, ssrc = struct.unpack('!II', data[4:12])
        
        # Calculate header length (12 bytes + CSRC list + extension if present)
        header_len = 12 + (csrc_count * 4)
        
        if extension:
            # Skip extension header (2 bytes profile + 2 bytes length + data)
            if len(data) < header_len + 4:
                raise ValueError("Packet too short for RTP extension")
            ext_len = struct.unpack('!H', data[header_len+2:header_len+4])[0]
            header_len += 4 + (ext_len * 4)
        
        return cls(
            version=version,
            padding=padding,
            extension=extension,
            csrc_count=csrc_count,
            marker=marker,
            payload_type=payload_type,
            sequence=sequence,
            timestamp=timestamp,
            ssrc=ssrc
        ), header_len


@dataclass
class RTPPacket:
    """Complete RTP packet with header and payload"""
    header: RTPHeader
    payload: bytes
    arrival_time: float  # Unix timestamp when packet arrived
    
    def get_iq_samples(self) -> np.ndarray:
        """
        Extract IQ samples from payload

        Returns:
            Complex numpy array of IQ samples (float32)
        """
        # ka9q-radio sends IQ as interleaved float32 (I, Q, I, Q, ...)
        # Parse as float32 little-endian
        samples = np.frombuffer(self.payload, dtype=np.float32)

        # Ensure even number of samples (I and Q pairs)
        if len(samples) % 2 != 0:
            samples = samples[:-1]

        # Validate samples before conversion
        if len(samples) == 0:
            return np.array([], dtype=np.complex64)

        # Check for invalid float32 values (NaN, inf)
        if np.any(~np.isfinite(samples)):
            logger.warning(f"RTP packet contains non-finite float32 values: {np.sum(~np.isfinite(samples))}")
            # Replace invalid values with zeros
            samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)

        # Convert to complex (I + jQ)
        iq = samples[::2] + 1j * samples[1::2]

        return iq


@dataclass
class GapInfo:
    """Information about a data gap"""
    start_time: datetime
    end_time: datetime
    start_seq: int
    end_seq: int
    missing_packets: int
    missing_samples: int


@dataclass
class ChannelStats:
    """Statistics for a recording channel"""
    ssrc: int
    frequency_hz: float
    description: str
    start_time: datetime
    packets_received: int = 0
    packets_dropped: int = 0
    packets_duplicate: int = 0
    samples_recorded: int = 0
    gaps: List[GapInfo] = field(default_factory=list)
    last_sequence: Optional[int] = None
    last_timestamp: Optional[int] = None
    
    def data_completeness(self) -> float:
        """Calculate data completeness percentage"""
        total_expected = self.packets_received + self.packets_dropped
        if total_expected == 0:
            return 0.0
        return 100.0 * self.packets_received / total_expected


class Resampler:
    """
    Resample IQ data from 12 kHz to 10 Hz with anti-aliasing filter
    
    Uses scipy.signal for high-quality resampling with proper anti-aliasing.
    """
    
    def __init__(self, input_rate: int = 12000, output_rate: int = 10):
        """
        Initialize resampler
        
        Args:
            input_rate: Input sample rate (Hz)
            output_rate: Output sample rate (Hz)
        """
        if scipy_signal is None:
            raise RuntimeError("scipy is required for resampling")
        
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.decimation_factor = input_rate // output_rate  # 1200
        
        # Design anti-aliasing filter (8th order Butterworth)
        # Cutoff at Nyquist frequency of output rate (5 Hz)
        nyquist = input_rate / 2.0
        cutoff = output_rate / 2.0
        normalized_cutoff = cutoff / nyquist
        
        self.filter_b, self.filter_a = scipy_signal.butter(
            8, normalized_cutoff, btype='low', analog=False
        )
        
        # Filter state for continuous operation
        self.filter_state = None
        
        logger.info(f"Initialized resampler: {input_rate} Hz → {output_rate} Hz "
                   f"(decimation by {self.decimation_factor})")
    
    def resample(self, iq_samples: np.ndarray) -> np.ndarray:
        """
        Resample IQ data with anti-aliasing
        
        Args:
            iq_samples: Complex IQ samples at input rate
            
        Returns:
            Complex IQ samples at output rate
        """
        # Apply anti-aliasing filter to I and Q separately
        i_samples = np.real(iq_samples)
        q_samples = np.imag(iq_samples)
        
        # Filter with state preservation for continuous operation
        if self.filter_state is None:
            # Initialize filter state
            self.filter_state = scipy_signal.lfilter_zi(self.filter_b, self.filter_a)
            i_filtered, self.filter_state_i = scipy_signal.lfilter(
                self.filter_b, self.filter_a, i_samples, zi=self.filter_state * i_samples[0]
            )
            q_filtered, self.filter_state_q = scipy_signal.lfilter(
                self.filter_b, self.filter_a, q_samples, zi=self.filter_state * q_samples[0]
            )
        else:
            # Continue with existing state
            i_filtered, self.filter_state_i = scipy_signal.lfilter(
                self.filter_b, self.filter_a, i_samples, zi=self.filter_state_i
            )
            q_filtered, self.filter_state_q = scipy_signal.lfilter(
                self.filter_b, self.filter_a, q_samples, zi=self.filter_state_q
            )
        
        # Decimate (keep every Nth sample)
        i_decimated = i_filtered[::self.decimation_factor]
        q_decimated = q_filtered[::self.decimation_factor]
        
        # Recombine into complex
        return i_decimated + 1j * q_decimated


class DailyBuffer:
    """
    UTC-aligned 24-hour buffer for GRAPE data
    
    Accumulates resampled IQ samples in a daily buffer with timestamp-based
    placement. Handles midnight rollover and Digital RF file writing.
    """
    
    def __init__(self, output_rate: int = 10):
        """
        Initialize daily buffer
        
        Args:
            output_rate: Sample rate (Hz)
        """
        self.output_rate = output_rate
        self.samples_per_day = output_rate * 86400  # 864,000 samples for 10 Hz
        
        # Current day's buffer (initialized with NaN for gap detection)
        self.current_date: Optional[datetime] = None
        self.buffer: Optional[np.ndarray] = None
        self.sample_count = 0
        
        logger.info(f"Initialized daily buffer: {self.samples_per_day} samples/day @ {output_rate} Hz")
    
    def add_samples(self, samples: np.ndarray, timestamp: datetime):
        """
        Add samples to buffer at timestamp-based position
        
        Args:
            samples: IQ samples to add
            timestamp: UTC timestamp for first sample
        """
        # Get date for this timestamp
        sample_date = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Check if we need to start a new day
        if self.current_date is None or sample_date != self.current_date:
            if self.buffer is not None:
                # Rollover - return completed buffer
                logger.info(f"Day rollover: {self.current_date} → {sample_date}")
                return self.buffer, self.current_date
            
            # Initialize new day
            self.current_date = sample_date
            self.buffer = np.full(self.samples_per_day, np.nan, dtype=np.complex64)
            self.sample_count = 0
            logger.info(f"Started new daily buffer for {self.current_date}")
        
        # Calculate buffer index from timestamp
        seconds_since_midnight = (timestamp - self.current_date).total_seconds()
        start_index = int(seconds_since_midnight * self.output_rate)

        # Bounds checking to prevent overflow
        if start_index < 0:
            logger.warning(f"Negative start_index: {start_index}, timestamp issue")
            return None, None

        if start_index >= self.samples_per_day:
            logger.warning(f"Start_index {start_index} exceeds buffer size {self.samples_per_day}")
            return None, None

        # Add samples to buffer
        end_index = start_index + len(samples)
        if end_index <= self.samples_per_day:
            # Ensure samples are compatible with buffer dtype
            try:
                safe_samples = samples.astype(np.complex64, copy=False)
                self.buffer[start_index:end_index] = safe_samples
                self.sample_count += len(samples)
            except (ValueError, OverflowError) as e:
                logger.error(f"Error casting samples to complex64: {e}")
                return None, None
        else:
            # Samples span midnight - split them
            samples_today = self.samples_per_day - start_index
            if samples_today > 0:
                try:
                    safe_samples = samples[:samples_today].astype(np.complex64, copy=False)
                    self.buffer[start_index:] = safe_samples
                    self.sample_count += samples_today
                except (ValueError, OverflowError) as e:
                    logger.error(f"Error in midnight split: {e}")
                    return None, None

            logger.warning(f"Samples span midnight: {len(samples)} samples, "
                         f"wrote {samples_today} to current day")
        
        return None, None
    
    def finalize_day(self) -> Tuple[Optional[np.ndarray], Optional[datetime]]:
        """
        Finalize current day and return buffer
        
        Returns:
            Tuple of (buffer, date) or (None, None)
        """
        if self.buffer is None:
            return None, None
        
        result = (self.buffer.copy(), self.current_date)
        self.buffer = None
        self.current_date = None
        self.sample_count = 0
        
        return result


class RTPReceiver:
    """
    RTP multicast receiver for ka9q-radio streams
    
    Receives RTP packets from a multicast address and demultiplexes by SSRC.
    """
    
    def __init__(self, multicast_addr: str, multicast_port: int = 5004):
        """
        Initialize RTP receiver
        
        Args:
            multicast_addr: Multicast group address (e.g., "239.251.200.1")
            multicast_port: Multicast port (default 5004)
        """
        self.multicast_addr = multicast_addr
        self.multicast_port = multicast_port
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.receive_thread: Optional[threading.Thread] = None
        self.callbacks: Dict[int, callable] = {}  # ssrc -> callback function
        
    def register_callback(self, ssrc: int, callback: callable):
        """
        Register a callback for packets with specific SSRC
        
        Args:
            ssrc: SSRC to filter for
            callback: Function to call with RTPPacket
        """
        self.callbacks[ssrc] = callback
        logger.info(f"Registered callback for SSRC 0x{ssrc:08x}")
    
    def start(self):
        """Start receiving RTP packets"""
        if self.running:
            logger.warning("RTP receiver already running")
            return
        
        # Create UDP socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Enable multicast loopback (important for local testing)
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        
        # Bind to multicast port
        self.socket.bind(('', self.multicast_port))
        
        # Join multicast group
        mreq = struct.pack('4sl', socket.inet_aton(self.multicast_addr), socket.INADDR_ANY)
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        logger.info(f"Joined multicast group {self.multicast_addr}:{self.multicast_port}")
        
        # Start receive thread
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.receive_thread.start()
        
        logger.info("RTP receiver started")
    
    def stop(self):
        """Stop receiving RTP packets"""
        if not self.running:
            return
        
        logger.info("Stopping RTP receiver")
        self.running = False
        
        if self.receive_thread:
            self.receive_thread.join(timeout=5.0)
        
        if self.socket:
            self.socket.close()
            self.socket = None
        
        logger.info("RTP receiver stopped")
    
    def _receive_loop(self):
        """Main receive loop (runs in separate thread)"""
        logger.info("RTP receive loop started")
        
        while self.running:
            try:
                # Receive packet (64KB buffer for jumbo frames)
                data, addr = self.socket.recvfrom(65536)
                arrival_time = time.time()
                
                # Parse RTP header
                try:
                    header, header_len = RTPHeader.parse(data)
                    payload = data[header_len:]

                    # Validate header
                    if header.payload_type not in [96, 97, 98, 99]:  # Common RTP payload types for audio
                        logger.debug(f"Unexpected RTP payload type: {header.payload_type}")
                    if len(payload) == 0:
                        logger.debug("Empty RTP payload, skipping")
                        continue

                    # Create packet object
                    packet = RTPPacket(
                        header=header,
                        payload=payload,
                        arrival_time=arrival_time
                    )
                    
                    # Dispatch to registered callback
                    callback = self.callbacks.get(header.ssrc)
                    if callback:
                        callback(packet)
                    else:
                        # Log unknown SSRC (but only occasionally to avoid spam)
                        if header.sequence % 1000 == 0:
                            logger.debug(f"Received packet from unknown SSRC 0x{header.ssrc:08x}")
                
                except Exception as e:
                    logger.error(f"Error parsing RTP packet: {e}")
                    continue
            
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Error in receive loop: {e}")
                break
        
        logger.info("RTP receive loop ended")


class GRAPEChannelRecorder:
    """
    Records a single GRAPE channel to Digital RF format
    
    Receives RTP packets for one SSRC, resamples to 10 Hz, and writes
    UTC-aligned 24-hour Digital RF datasets with metadata.
    """
    
    def __init__(self, ssrc: int, frequency_hz: float, description: str, 
                 output_dir: Path, station_config: dict, sample_rate: int = 12000):
        """
        Initialize GRAPE channel recorder
        
        Args:
            ssrc: RTP SSRC for this channel
            frequency_hz: Center frequency in Hz
            description: Channel description (e.g., "WWV 2.5 MHz")
            output_dir: Directory to write Digital RF files
            station_config: Station configuration (callsign, grid, etc.)
            sample_rate: Input sample rate (default 12000 Hz)
        """
        if drf is None:
            raise RuntimeError("digital_rf package is required")
        
        self.ssrc = ssrc
        self.frequency_hz = frequency_hz
        self.description = description
        self.output_dir = Path(output_dir)
        self.station_config = station_config
        self.input_sample_rate = sample_rate
        self.output_sample_rate = 10  # GRAPE target rate
        
        # Initialize resampler
        self.resampler = Resampler(sample_rate, self.output_sample_rate)
        
        # Initialize daily buffer
        self.daily_buffer = DailyBuffer(self.output_sample_rate)
        
        # Accumulator for input samples (need enough for at least 1 output sample)
        self.input_accumulator = np.array([], dtype=np.complex64)
        self.min_input_samples = self.resampler.decimation_factor
        
        # Statistics
        self.stats = ChannelStats(
            ssrc=ssrc,
            frequency_hz=frequency_hz,
            description=description,
            start_time=datetime.now(timezone.utc)
        )
        
        # RTP timestamp tracking for sample placement
        self.rtp_timestamp_base: Optional[int] = None
        self.unix_time_base: Optional[float] = None
        
        # Track warnings to avoid spam
        self.warned_non_finite = False

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized GRAPE recorder for {description} (SSRC 0x{ssrc:08x})")
    
    def process_packet(self, packet: RTPPacket):
        """
        Process an incoming RTP packet
        
        Args:
            packet: RTP packet to process
        """
        # Update statistics
        self.stats.packets_received += 1
        
        # Check for packet loss
        if self.stats.last_sequence is not None:
            expected_seq = (self.stats.last_sequence + 1) & 0xFFFF
            if packet.header.sequence != expected_seq:
                if packet.header.sequence > expected_seq or \
                   (packet.header.sequence < 100 and self.stats.last_sequence > 65400):
                    # Packet(s) dropped
                    dropped = (packet.header.sequence - expected_seq) & 0xFFFF
                    self.stats.packets_dropped += dropped
                    logger.warning(f"SSRC 0x{self.ssrc:08x}: Dropped {dropped} packet(s) "
                                 f"(seq {self.stats.last_sequence} → {packet.header.sequence})")
                else:
                    # Duplicate or out-of-order packet
                    self.stats.packets_duplicate += 1
                    logger.debug(f"SSRC 0x{self.ssrc:08x}: Duplicate/OOO packet "
                               f"(seq {packet.header.sequence})")
                    return  # Skip duplicate
        
        self.stats.last_sequence = packet.header.sequence
        self.stats.last_timestamp = packet.header.timestamp
        
        # Initialize RTP timestamp base on first packet
        if self.rtp_timestamp_base is None:
            self.rtp_timestamp_base = packet.header.timestamp
            self.unix_time_base = packet.arrival_time
            logger.info(f"SSRC 0x{self.ssrc:08x}: RTP timestamp base = {self.rtp_timestamp_base}, "
                       f"Unix time base = {self.unix_time_base}")
            return  # Don't process first packet to avoid timestamp issues
        
        # Check if RTP timestamp base is initialized
        if self.rtp_timestamp_base is None:
            logger.warning(f"SSRC 0x{self.ssrc:08x}: RTP timestamp base not initialized, skipping packet")
            return

        # Extract IQ samples
        try:
            iq_samples = packet.get_iq_samples()
            self.stats.samples_recorded += len(iq_samples)

            # Validate IQ samples before processing
            if len(iq_samples) == 0:
                logger.debug(f"SSRC 0x{self.ssrc:08x}: Empty IQ samples, skipping")
                return

            # Check for invalid IQ values
            if np.any(~np.isfinite(iq_samples)):
                logger.warning(f"SSRC 0x{self.ssrc:08x}: Non-finite IQ samples: {np.sum(~np.isfinite(iq_samples))} values")
                # Replace invalid values with zeros
                iq_samples = np.nan_to_num(iq_samples, nan=0.0, posinf=0.0, neginf=0.0)

            # Check for unreasonably large values (likely corrupted data)
            max_reasonable_amplitude = 1e6  # Much larger than typical signal levels
            if np.any(np.abs(iq_samples) > max_reasonable_amplitude):
                large_count = np.sum(np.abs(iq_samples) > max_reasonable_amplitude)
                logger.warning(f"SSRC 0x{self.ssrc:08x}: Unreasonably large IQ values: {large_count} samples")
                # Clamp large values
                iq_samples = np.clip(iq_samples, -max_reasonable_amplitude, max_reasonable_amplitude)
            
            # Add to input accumulator
            self.input_accumulator = np.concatenate([self.input_accumulator, iq_samples])

            # Prevent accumulator from growing too large (max 10x minimum samples)
            max_accumulator_size = self.min_input_samples * 10
            if len(self.input_accumulator) > max_accumulator_size:
                logger.warning(f"SSRC 0x{self.ssrc:08x}: Input accumulator grew too large ({len(self.input_accumulator)} samples), truncating")
                # Keep only the most recent samples
                self.input_accumulator = self.input_accumulator[-self.min_input_samples:]
            
            # Process when we have enough samples
            if len(self.input_accumulator) >= self.min_input_samples:
                # Resample to 10 Hz
                resampled = self.resampler.resample(self.input_accumulator)

                # Validate resampled data
                if len(resampled) == 0:
                    logger.warning("Empty resampled data, skipping")
                    return

                # Check for invalid values (NaN, inf)
                if np.any(~np.isfinite(resampled)):
                    if not self.warned_non_finite:
                        logger.warning(f"SSRC 0x{self.ssrc:08x}: Non-finite values in resampled data: {np.sum(~np.isfinite(resampled))} values (will suppress further warnings)")
                        self.warned_non_finite = True
                    # Replace invalid values with zeros
                    resampled = np.nan_to_num(resampled, nan=0.0, posinf=0.0, neginf=0.0)
                
                # Calculate timestamp for resampled data
                # RTP timestamp is in units of input sample rate
                rtp_elapsed = (packet.header.timestamp - self.rtp_timestamp_base) / self.input_sample_rate
                unix_timestamp = self.unix_time_base + rtp_elapsed

                # Debug logging for first few packets
                if self.stats.packets_received < 10:
                    logger.info(f"SSRC 0x{self.ssrc:08x}: "
                              f"timestamp_calc: packet_ts={packet.header.timestamp}, "
                              f"rtp_base={self.rtp_timestamp_base}, "
                              f"elapsed={rtp_elapsed:.6f}s, "
                              f"unix_time={unix_timestamp}")

                # Validate timestamp is reasonable (prevent overflow)
                if unix_timestamp < 0 or unix_timestamp > time.time() + 3600:  # Allow 1 hour in future
                    logger.warning(f"Invalid timestamp calculated: {unix_timestamp}, "
                                 f"packet_timestamp={packet.header.timestamp}, "
                                 f"rtp_base={self.rtp_timestamp_base}")
                    return  # Skip this packet

                try:
                    sample_timestamp = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)

                    # Validate timestamp is within reasonable bounds
                    now = datetime.now(timezone.utc)
                    if abs((sample_timestamp - now).total_seconds()) > 86400:  # 24 hours
                        logger.warning(f"Timestamp too far from current time: {sample_timestamp}")
                        return  # Skip this packet

                    # Add to daily buffer
                    completed_buffer, completed_date = self.daily_buffer.add_samples(
                        resampled, sample_timestamp
                    )

                except (ValueError, OSError) as e:
                    logger.error(f"Error creating timestamp: {e}")
                    return  # Skip this packet
                
                # Write completed day to Digital RF
                if completed_buffer is not None:
                    self._write_digital_rf(completed_buffer, completed_date)
                
                # Clear accumulator (keep remainder for next iteration)
                remainder_samples = len(self.input_accumulator) % self.min_input_samples
                if remainder_samples > 0:
                    self.input_accumulator = self.input_accumulator[-remainder_samples:]
                else:
                    self.input_accumulator = np.array([], dtype=np.complex64)
            
        except Exception as e:
            logger.error(f"Error processing packet: {e}", exc_info=True)
    
    def _write_digital_rf(self, buffer: np.ndarray, date: datetime):
        """
        Write completed daily buffer to Digital RF format
        
        Args:
            buffer: Daily IQ buffer
            date: UTC date for this buffer
        """
        logger.info(f"Writing Digital RF for {self.description} on {date.strftime('%Y-%m-%d')}")
        
        try:
            # Create output directory structure
            # Format: <output_dir>/<YYYYMMDD>/<site>_<grid>/<receiver>@<station>_<instrument>/<channel>
            date_str = date.strftime('%Y%m%d')
            site_str = f"{self.station_config['callsign']}_{self.station_config['grid_square']}"
            receiver_str = f"{self.station_config['instrument_id']}@{self.station_config['id']}_0"
            channel_name = self._get_channel_name()
            
            dataset_dir = self.output_dir / date_str / site_str / receiver_str
            dataset_dir.mkdir(parents=True, exist_ok=True)
            
            # Create channel directory
            channel_dir = dataset_dir / channel_name
            channel_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate UUID for this dataset
            uuid_str = uuid.uuid4().hex
            
            # Calculate start time (midnight UTC)
            start_timestamp = date.timestamp()
            start_global_index = int(start_timestamp * self.output_sample_rate)
            
            # Prepare data for Digital RF (convert NaN to zeros for now)
            # TODO: Better gap handling
            data = np.nan_to_num(buffer, nan=0.0)
            
            # Separate I and Q for Digital RF (expects interleaved format)
            i_samples = np.real(data).astype(np.float32)
            q_samples = np.imag(data).astype(np.float32)
            interleaved = np.empty(len(data) * 2, dtype=np.float32)
            interleaved[0::2] = i_samples
            interleaved[1::2] = q_samples
            
            # Reshape for Digital RF (samples × channels)
            drf_data = interleaved.reshape(-1, 2)
            
            # Write Digital RF dataset
            with drf.DigitalRFWriter(
                str(channel_dir),
                'f32',  # float32 dtype
                86400,  # subdir_cadence_secs (1 day)
                3600000,  # file_cadence_millisecs (1 hour)
                start_global_index,
                self.output_sample_rate,  # sample_rate_numerator
                1,  # sample_rate_denominator
                uuid_str,
                9,  # compression_level (max)
                False,  # checksum
                True,  # is_complex (2 channels = I/Q)
                1,  # num_subchannels
                True,  # is_continuous
                False  # marching_periods
            ) as writer:
                writer.rf_write(drf_data)
            
            # Write metadata
            self._write_metadata(channel_dir, start_global_index, uuid_str)
            
            logger.info(f"Successfully wrote Digital RF dataset to {channel_dir}")
            
        except Exception as e:
            logger.error(f"Error writing Digital RF: {e}", exc_info=True)
    
    def _write_metadata(self, channel_dir: Path, start_global_index: int, uuid_str: str):
        """
        Write Digital RF metadata
        
        Args:
            channel_dir: Channel directory
            start_global_index: Start sample index
            uuid_str: UUID for this dataset
        """
        try:
            metadata_dir = channel_dir / 'metadata'
            metadata_dir.mkdir(parents=True, exist_ok=True)
            
            # Convert grid square to lat/lon
            grid = self.station_config['grid_square']
            lon = (ord(grid[0]) - ord('A')) * 20 + (ord(grid[2]) - ord('0')) * 2 - 180
            lat = (ord(grid[1]) - ord('A')) * 10 + (ord(grid[3]) - ord('0')) - 90
            if len(grid) >= 6:
                lon += (ord(grid[4].upper()) - ord('A')) * 5.0 / 60.0
                lat += (ord(grid[5].upper()) - ord('A')) * 2.5 / 60.0
            
            # Create metadata dictionary
            metadata = {
                'callsign': self.station_config['callsign'],
                'grid_square': self.station_config['grid_square'],
                'lat': np.single(lat),
                'long': np.single(lon),
                'receiver_name': self.station_config['instrument_id'],
                'center_frequencies': np.array([self.frequency_hz], dtype=np.float64),
                'uuid_str': uuid_str
            }
            
            # Write metadata
            with drf.DigitalMetadataWriter(
                str(metadata_dir),
                86400,  # subdir_cadence_secs
                86400,  # file_cadence_secs
                self.output_sample_rate,  # sample_rate_numerator
                1,  # sample_rate_denominator
                'metadata'  # file_name
            ) as writer:
                writer.write(start_global_index, metadata)
            
            logger.info(f"Successfully wrote metadata to {metadata_dir}")
            
        except Exception as e:
            logger.error(f"Error writing metadata: {e}", exc_info=True)
    
    def _get_channel_name(self) -> str:
        """Get channel name from frequency"""
        freq_mhz = self.frequency_hz / 1e6
        
        # WWV frequencies
        wwv_freqs = {
            2.5: "WWV_2_5",
            5.0: "WWV_5",
            10.0: "WWV_10",
            15.0: "WWV_15",
            20.0: "WWV_20",
            25.0: "WWV_25",
        }
        
        # CHU frequencies
        chu_freqs = {
            3.33: "CHU_3",
            7.85: "CHU_7",
            14.67: "CHU_14",
        }
        
        # Check WWV frequencies (100 kHz tolerance)
        for wwv_freq, name in wwv_freqs.items():
            if abs(freq_mhz - wwv_freq) < 0.1:
                return name
        
        # Check CHU frequencies (100 kHz tolerance)
        for chu_freq, name in chu_freqs.items():
            if abs(freq_mhz - chu_freq) < 0.1:
                return name
        
        # Fallback
        return f"FREQ_{freq_mhz:.3f}"
    
    def get_stats_dict(self) -> dict:
        """Get statistics as dictionary"""
        return {
            'ssrc': f"0x{self.stats.ssrc:08x}",
            'frequency_hz': self.stats.frequency_hz,
            'description': self.stats.description,
            'start_time': self.stats.start_time.isoformat(),
            'packets_received': self.stats.packets_received,
            'packets_dropped': self.stats.packets_dropped,
            'packets_duplicate': self.stats.packets_duplicate,
            'samples_recorded': self.stats.samples_recorded,
            'data_completeness': f"{self.stats.data_completeness():.2f}%",
            'gaps': len(self.stats.gaps)
        }


class GRAPERecorderManager:
    """
    Manages multiple GRAPE channel recorders
    
    Coordinates RTP reception and per-channel recording for all GRAPE channels.
    """
    
    def __init__(self, config: dict):
        """
        Initialize GRAPE recorder manager
        
        Args:
            config: Configuration dictionary from TOML
        """
        self.config = config
        self.receiver: Optional[RTPReceiver] = None
        self.recorders: Dict[int, GRAPEChannelRecorder] = {}  # ssrc -> recorder
        self.running = False
    
    def start(self):
        """Start all GRAPE recorders"""
        if self.running:
            logger.warning("GRAPE recorder manager already running")
            return
        
        # Get multicast address from config
        # For GRAPE, all channels share the same multicast group (239.251.200.0/24)
        # We'll use the first channel's address or a default
        multicast_addr = "239.251.200.1"  # Default, will be updated from actual streams
        
        # Create RTP receiver
        self.receiver = RTPReceiver(multicast_addr)
        
        # Create recorders for each enabled GRAPE channel
        output_dir = Path(self.config['recorder']['archive_dir'])
        station_config = self.config['station']
        
        for channel_config in self.config['recorder']['channels']:
            if not channel_config.get('enabled', True):
                continue
            
            if channel_config.get('processor') != 'grape':
                continue
            
            ssrc = channel_config['ssrc']
            freq_hz = channel_config['frequency_hz']
            description = channel_config['description']
            sample_rate = channel_config.get('sample_rate', 12000)
            
            # Create recorder
            recorder = GRAPEChannelRecorder(
                ssrc=ssrc,
                frequency_hz=freq_hz,
                description=description,
                output_dir=output_dir,
                station_config=station_config,
                sample_rate=sample_rate
            )
            
            # Register callback with receiver
            self.receiver.register_callback(ssrc, recorder.process_packet)
            
            self.recorders[ssrc] = recorder
            logger.info(f"Created GRAPE recorder for {description}")
        
        # Start receiver
        self.receiver.start()
        self.running = True
        
        logger.info(f"Started GRAPE recorder manager with {len(self.recorders)} channels")
    
    def stop(self):
        """Stop all GRAPE recorders"""
        if not self.running:
            return
        
        logger.info("Stopping GRAPE recorder manager")
        
        # Stop receiver
        if self.receiver:
            self.receiver.stop()
        
        self.running = False
        logger.info("GRAPE recorder manager stopped")
    
    def get_status(self) -> dict:
        """Get status of all recorders"""
        return {
            'running': self.running,
            'channels': {
                ssrc: recorder.get_stats_dict()
                for ssrc, recorder in self.recorders.items()
            }
        }

