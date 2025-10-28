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
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass, asdict
from collections import deque
from enum import Enum
from .channel_manager import ChannelManager
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


# ===== Discontinuity Tracking =====

class DiscontinuityType(Enum):
    """Types of discontinuities in the data stream"""
    GAP = "gap"                    # Missed packets, samples lost
    SYNC_ADJUST = "sync_adjust"    # Time sync adjustment
    RTP_RESET = "rtp_reset"        # RTP sequence/timestamp reset
    OVERFLOW = "overflow"          # Buffer overflow, samples dropped
    UNDERFLOW = "underflow"        # Buffer underflow, samples duplicated


@dataclass
class TimingDiscontinuity:
    """
    Record of a timing discontinuity in the data stream
    
    Every gap, jump, or correction is logged for scientific provenance.
    """
    timestamp: float  # Unix time when discontinuity was detected
    sample_index: int  # Sample number in output stream where discontinuity occurs
    discontinuity_type: DiscontinuityType
    magnitude_samples: int  # Positive = gap/forward jump, negative = overlap/backward jump
    magnitude_ms: float  # Time equivalent in milliseconds
    
    # RTP packet info
    rtp_sequence_before: Optional[int]
    rtp_sequence_after: Optional[int]
    rtp_timestamp_before: Optional[int]
    rtp_timestamp_after: Optional[int]
    
    # Validation
    wwv_tone_detected: bool  # Was this related to WWV tone detection?
    explanation: str  # Human-readable description
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        d = asdict(self)
        d['discontinuity_type'] = self.discontinuity_type.value
        return d


class DiscontinuityTracker:
    """Track and log all timing discontinuities in the data stream"""
    
    def __init__(self, channel_name: str):
        self.channel_name = channel_name
        self.discontinuities: List[TimingDiscontinuity] = []
        
    def add_discontinuity(self, disc: TimingDiscontinuity):
        """Add a discontinuity to the log"""
        self.discontinuities.append(disc)
        
        # Log based on severity
        if disc.discontinuity_type == DiscontinuityType.GAP:
            if abs(disc.magnitude_ms) > 100:
                logger.warning(f"{self.channel_name}: {disc.explanation}")
            else:
                logger.info(f"{self.channel_name}: {disc.explanation}")
        else:
            logger.info(f"{self.channel_name}: {disc.explanation}")
    
    def get_stats(self):
        """Get summary statistics"""
        if not self.discontinuities:
            return {
                'total_count': 0,
                'gaps': 0,
                'sync_adjustments': 0,
                'rtp_resets': 0,
                'total_samples_affected': 0,
                'total_gap_duration_ms': 0,
                'largest_gap_samples': 0,
                'last_discontinuity': None
            }
        
        gaps = [d for d in self.discontinuities if d.discontinuity_type == DiscontinuityType.GAP]
        sync_adjusts = [d for d in self.discontinuities if d.discontinuity_type == DiscontinuityType.SYNC_ADJUST]
        rtp_resets = [d for d in self.discontinuities if d.discontinuity_type == DiscontinuityType.RTP_RESET]
        
        total_samples = sum(abs(d.magnitude_samples) for d in self.discontinuities)
        total_gap_ms = sum(d.magnitude_ms for d in gaps if d.magnitude_samples > 0)
        largest_gap = max((abs(d.magnitude_samples) for d in gaps), default=0)
        
        return {
            'total_count': len(self.discontinuities),
            'gaps': len(gaps),
            'sync_adjustments': len(sync_adjusts),
            'rtp_resets': len(rtp_resets),
            'total_samples_affected': total_samples,
            'total_gap_duration_ms': total_gap_ms,
            'largest_gap_samples': largest_gap,
            'last_discontinuity': self.discontinuities[-1].to_dict() if self.discontinuities else None
        }
    
    def export_to_csv(self, output_path):
        """Export discontinuity log to CSV for analysis"""
        import csv
        
        with open(output_path, 'w', newline='') as f:
            if not self.discontinuities:
                return
            
            fieldnames = [
                'timestamp', 'sample_index', 'type', 
                'magnitude_samples', 'magnitude_ms',
                'rtp_seq_before', 'rtp_seq_after',
                'rtp_ts_before', 'rtp_ts_after',
                'wwv_validated', 'explanation'
            ]
            
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for disc in self.discontinuities:
                row = {
                    'timestamp': disc.timestamp,
                    'sample_index': disc.sample_index,
                    'type': disc.discontinuity_type.value,
                    'magnitude_samples': disc.magnitude_samples,
                    'magnitude_ms': disc.magnitude_ms,
                    'rtp_seq_before': disc.rtp_sequence_before,
                    'rtp_seq_after': disc.rtp_sequence_after,
                    'rtp_ts_before': disc.rtp_timestamp_before,
                    'rtp_ts_after': disc.rtp_timestamp_after,
                    'wwv_validated': disc.wwv_tone_detected,
                    'explanation': disc.explanation
                }
                writer.writerow(row)
        
        logger.info(f"{self.channel_name}: Exported {len(self.discontinuities)} discontinuities to {output_path}")


# ===== WWV/CHU Tone Detection =====

class WWVToneDetector:
    """
    Detect WWV 1200 Hz tone onset for timing validation
    
    WWV broadcasts a 1200 Hz tone for 1 second at the start of each minute (UTC).
    This provides an independent ground truth for timing validation.
    """
    
    def __init__(self, sample_rate=3000):
        """
        Initialize detector
        
        Args:
            sample_rate: Input sample rate (Hz), must be ≥ 2.4 kHz for 1200 Hz tone
                        (default 3000 Hz provides good margin)
        """
        self.sample_rate = sample_rate
        
        # Design bandpass filter for 1200 Hz ± 50 Hz
        self.sos = scipy_signal.butter(
            N=4,
            Wn=[1150, 1250],
            btype='band',
            fs=sample_rate,
            output='sos'
        )
        
        # Detection parameters
        self.envelope_threshold = 0.05  # Relative to max envelope (lowered from 0.3 - signal is noisy)
        self.min_tone_duration_sec = 0.5  # WWV tone is 1 sec, but allow weaker detection (relaxed from 0.8)
        self.max_tone_duration_sec = 1.5  # Allow some tolerance (relaxed from 1.2)
        
        # State
        self.last_detection_time = 0
        self.detection_count = 0
        
    def detect_tone_onset(self, iq_samples, current_unix_time):
        """
        Detect 1200 Hz tone onset in IQ sample buffer
        
        Args:
            iq_samples: Complex IQ samples (numpy array)
            current_unix_time: Unix timestamp corresponding to first sample
            
        Returns:
            tuple: (detected: bool, onset_sample_idx: int or None, timing_error_ms: float or None)
        """
        # 1. AM demodulation: extract envelope (audio) from IQ
        am_audio = np.abs(iq_samples)
        
        # DEBUG: Check input
        if np.random.random() < 0.01:
            logger.debug(f"WWV detector step 1: IQ samples min={np.min(np.abs(iq_samples)):.6f}, max={np.max(np.abs(iq_samples)):.6f}, mean={np.mean(am_audio):.6f}")
        
        # Remove DC component to get just the modulation
        am_audio_dc_removed = am_audio - np.mean(am_audio)
        
        # DEBUG: Check after DC removal
        if np.random.random() < 0.01:
            logger.debug(f"WWV detector step 2: After DC removal min={np.min(am_audio_dc_removed):.6f}, max={np.max(am_audio_dc_removed):.6f}")
        
        # 2. Bandpass filter around 1200 Hz in the demodulated audio
        filtered = scipy_signal.sosfiltfilt(self.sos, am_audio_dc_removed)
        
        # DEBUG: Check after filtering
        if np.random.random() < 0.01:
            logger.debug(f"WWV detector step 3: After filter min={np.min(filtered):.6f}, max={np.max(filtered):.6f}, has_nan={np.any(np.isnan(filtered))}")
        
        # 3. Envelope detection of the 1200 Hz component
        analytic = scipy_signal.hilbert(filtered)
        envelope = np.abs(analytic)
        
        # DEBUG: Check envelope
        if np.random.random() < 0.01:
            logger.debug(f"WWV detector step 4: Envelope min={np.min(envelope):.6f}, max={np.max(envelope):.6f}, has_nan={np.any(np.isnan(envelope))}")
        
        # Normalize envelope
        max_envelope = np.max(envelope)
        if max_envelope > 0:
            envelope = envelope / max_envelope
        
        # 3. Threshold detection
        above_threshold = envelope > self.envelope_threshold
        
        # DEBUG: Log detection attempts periodically
        if np.random.random() < 0.01:  # 1% sampling to avoid log spam
            above_count = np.sum(above_threshold)
            logger.debug(f"WWV detector: max_envelope={max_envelope:.6f}, above_threshold={above_count}/{len(above_threshold)} samples ({above_count/len(above_threshold)*100:.1f}%)")
        
        # Find edges (transitions)
        edges = np.diff(above_threshold.astype(int))
        rising_edges = np.where(edges == 1)[0]
        falling_edges = np.where(edges == -1)[0]
        
        if len(rising_edges) == 0 or len(falling_edges) == 0:
            # DEBUG: Log why detection failed
            if np.random.random() < 0.01:  # 1% sampling
                logger.debug(f"WWV detector: No edges found (rising={len(rising_edges)}, falling={len(falling_edges)})")
            return False, None, None
        
        # Take first rising edge as onset candidate
        onset_idx = rising_edges[0]
        
        # Find corresponding falling edge
        offset_candidates = falling_edges[falling_edges > onset_idx]
        if len(offset_candidates) == 0:
            # Tone continues beyond buffer
            return False, None, None
        
        offset_idx = offset_candidates[0]
        
        # 4. Validate tone duration
        tone_duration_samples = offset_idx - onset_idx
        tone_duration_sec = tone_duration_samples / self.sample_rate
        
        # DEBUG: Always log duration validation (not sampled - need to see rejections!)
        if tone_duration_sec < self.min_tone_duration_sec or tone_duration_sec > self.max_tone_duration_sec:
            logger.debug(f"WWV detector: REJECTED duration={tone_duration_sec:.3f}s (need {self.min_tone_duration_sec}-{self.max_tone_duration_sec}s), edges found: rising={len(rising_edges)}, falling={len(falling_edges)}")
        
        if tone_duration_sec < self.min_tone_duration_sec:
            return False, None, None  # Too short
        
        if tone_duration_sec > self.max_tone_duration_sec:
            return False, None, None  # Too long
        
        # 5. Calculate timing error
        # Onset should occur at a minute boundary (0 seconds past the minute)
        onset_time = current_unix_time + (onset_idx / self.sample_rate)
        
        # Get the minute boundary
        minute_boundary = int(onset_time / 60) * 60
        
        # Calculate error (how far from the minute boundary)
        timing_error_sec = onset_time - minute_boundary
        
        # Handle case where onset is near the end of previous minute
        if timing_error_sec > 30:
            timing_error_sec -= 60  # It was actually late in previous minute
        
        timing_error_ms = timing_error_sec * 1000
        
        # Update state
        self.last_detection_time = onset_time
        self.detection_count += 1
        
        return True, onset_idx, timing_error_ms


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
        packet_count = 0
        ssrc_seen = set()
        
        while self.running:
            try:
                data, addr = self.socket.recvfrom(8192)
                packet_count += 1
                
                # Parse RTP header
                header = self._parse_rtp_header(data)
                if not header:
                    continue
                
                # Log first packet from each SSRC for diagnostics (DEBUG level)
                if header.ssrc not in ssrc_seen:
                    ssrc_seen.add(header.ssrc)
                    has_callback = header.ssrc in self.callbacks
                    logger.debug(f"First packet from SSRC {header.ssrc}: "
                                f"seq={header.sequence}, ts={header.timestamp}, "
                                f"payload={len(data)-12} bytes, callback={'YES' if has_callback else 'NO'}")
                    if not has_callback:
                        logger.debug(f"No callback registered for SSRC {header.ssrc}. "
                                    f"Registered SSRCs: {list(self.callbacks.keys())}")
                
                # Log periodic stats every 10000 packets (reduced verbosity)
                if packet_count % 10000 == 0:
                    logger.info(f"RTP receiver: {packet_count} packets, "
                               f"{len(ssrc_seen)} SSRCs ({len(self.callbacks)} registered)")
                    
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
            input_rate: Input sample rate in Hz
            output_rate: Output sample rate in Hz
        """
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.decimation_factor = input_rate // output_rate
        
        # Design anti-aliasing filter (8th order Butterworth)
        # Cutoff at Nyquist frequency of output rate
        nyquist_out = output_rate / 2
        normalized_cutoff = nyquist_out / (input_rate / 2)
        self.sos = scipy_signal.butter(8, normalized_cutoff, output='sos')
        
        # Initialize filter state
        self.zi_i = scipy_signal.sosfilt_zi(self.sos)
        self.zi_q = scipy_signal.sosfilt_zi(self.sos)
        
        # Buffer for accumulating samples across packets
        self.sample_buffer = np.array([], dtype=np.complex64)
        self.decimation_phase = 0  # Tracks position within decimation cycle
        
        logger.info(f"Resampler initialized: {input_rate} Hz → {output_rate} Hz "
                   f"(decimation factor {self.decimation_factor})")
        
    def resample(self, iq_samples: np.ndarray) -> np.ndarray:
        """
        Resample IQ data
        
        Args:
            iq_samples: Complex IQ samples at input rate
            
        Returns:
            Decimated IQ samples at output rate
        """
        # Add new samples to buffer
        self.sample_buffer = np.concatenate([self.sample_buffer, iq_samples])
        
        # Calculate how many output samples we can produce
        # We need decimation_factor input samples for each output sample
        num_output_samples = len(self.sample_buffer) // self.decimation_factor
        
        if num_output_samples == 0:
            # Not enough samples yet, return empty array
            return np.array([], dtype=np.complex64)
        
        # Process enough samples to produce num_output_samples outputs
        num_input_samples = num_output_samples * self.decimation_factor
        samples_to_process = self.sample_buffer[:num_input_samples]
        self.sample_buffer = self.sample_buffer[num_input_samples:]  # Keep remainder
        
        # Split into I and Q
        i_samples = samples_to_process.real
        q_samples = samples_to_process.imag
        
        # Apply anti-aliasing filter
        i_filtered, self.zi_i = scipy_signal.sosfilt(self.sos, i_samples, zi=self.zi_i)
        q_filtered, self.zi_q = scipy_signal.sosfilt(self.sos, q_samples, zi=self.zi_q)
        
        # Decimate by taking every Nth sample starting from decimation_phase offset
        # decimation_phase maintains alignment across buffer boundaries
        i_decimated = i_filtered[self.decimation_phase::self.decimation_factor]
        q_decimated = q_filtered[self.decimation_phase::self.decimation_factor]
        
        # Update phase for next buffer
        # Track how many input samples we've used modulo decimation_factor
        consumed_samples = num_input_samples
        self.decimation_phase = (self.decimation_phase + consumed_samples) % self.decimation_factor
        
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
        # Note: Radiod reports 16 kHz sample rate, but that's for REAL samples (I+Q combined)
        # For complex I/Q: 16 kHz real / 2 = 8 kHz complex samples
        # Resampler: 8 kHz complex IQ → 10 Hz output (GRAPE standard)
        self.resampler = Resampler(input_rate=8000, output_rate=10)
        self.daily_buffer = DailyBuffer(sample_rate=10)
        
        # Sample accumulator (for efficient resampling)
        self.sample_accumulator = []
        self.samples_per_packet = 800  # Accumulate ~100ms at 8 kHz before resampling
        
        # RTP timestamp tracking
        self.last_sequence = None
        self.last_timestamp = None
        self.rtp_sample_rate = 16000  # RTP timestamp rate (real samples, I+Q combined) - GRAPE standard
        
        # UTC synchronization (wsprdaemon-style)
        self.sync_state = 'startup'  # startup → armed → active
        self.utc_aligned_start = None  # UTC-aligned recording start time
        self.rtp_start_timestamp = None  # RTP timestamp at recording start
        self.expected_rtp_timestamp = None  # For gap detection
        
        # Timing quality monitoring
        self.current_minute_start = None  # Start of current UTC minute
        self.current_minute_samples = 0  # Samples received in current minute
        self.timing_drift_samples = []  # Track timing drift over time
        self.last_timing_report = None  # Last timing quality report time
        
        # Discontinuity tracking (Phase 1)
        self.discontinuity_tracker = DiscontinuityTracker(channel_name)
        
        # WWV tone detection (Phase 1) - detect 1200 Hz tone for timing validation
        self.is_wwv_channel = 'WWV' in channel_name.upper()
        if self.is_wwv_channel:
            # Create 3 kHz resampler for tone detection (parallel to main 10 Hz path)
            # Need at least 2.4 kHz for 1200 Hz tone (Nyquist), use 3 kHz for margin
            self.tone_resampler = Resampler(input_rate=8000, output_rate=3000)
            self.tone_detector = WWVToneDetector(sample_rate=3000)
            self.tone_accumulator = []  # Buffer for tone detection
            self.tone_samples_per_check = 6000  # Check for tone every 2 seconds at 3 kHz
            self.wwv_detections = 0
            self.wwv_timing_errors = []  # Track timing errors from WWV tone
            logger.info(f"{channel_name}: WWV tone detection ENABLED (1200 Hz at 3 kHz sample rate)")
        else:
            self.tone_detector = None
        
        logger.info(f"Channel recorder initialized: {channel_name} (SSRC {ssrc}, {frequency_hz/1e6:.2f} MHz)")
        logger.info(f"{channel_name}: Sync state = startup, waiting for UTC boundary alignment")
    
    def _calculate_sample_time(self, rtp_timestamp: int) -> float:
        """
        Calculate Unix time for samples based on RTP timestamp.
        This provides accurate timing independent of system clock drift.
        
        Args:
            rtp_timestamp: RTP timestamp (12 kHz clock for real samples)
            
        Returns:
            Unix timestamp (seconds since epoch)
        """
        if self.sync_state != 'active' or self.rtp_start_timestamp is None:
            # Before sync, fall back to system time
            return time.time()
        
        # Calculate elapsed time since recording started
        # RTP timestamps wrap at 2^32, handle rollover
        rtp_elapsed = (rtp_timestamp - self.rtp_start_timestamp) & 0xFFFFFFFF
        
        # Convert to seconds (12 kHz is for REAL samples, not complex)
        elapsed_seconds = rtp_elapsed / self.rtp_sample_rate
        
        # Add to UTC-aligned start time
        return self.utc_aligned_start + elapsed_seconds
    
    def _track_timing_quality(self, sample_time: float, num_output_samples: int):
        """
        Track timing quality metrics for monitoring.
        Reports per-minute statistics and timing drift.
        
        Args:
            sample_time: Unix timestamp from RTP calculation
            num_output_samples: Number of 10 Hz samples added
        """
        if self.sync_state != 'active':
            return
        
        system_time = time.time()
        
        # Calculate current UTC minute boundary
        current_minute = int(sample_time / 60) * 60
        
        # Initialize or rollover to new minute
        if self.current_minute_start != current_minute:
            # Log previous minute statistics
            if self.current_minute_start is not None and self.current_minute_samples > 0:
                expected_samples = 600  # 10 Hz × 60 seconds
                completeness = self.current_minute_samples / expected_samples * 100
                minute_time = datetime.fromtimestamp(self.current_minute_start, timezone.utc)
                
                logger.info(f"{self.channel_name}: Minute {minute_time.strftime('%H:%M')} complete: "
                          f"{self.current_minute_samples}/{expected_samples} samples ({completeness:.1f}%)")
            
            # Start new minute
            self.current_minute_start = current_minute
            self.current_minute_samples = 0
        
        # Accumulate samples for this minute
        self.current_minute_samples += num_output_samples
        
        # Calculate timing drift (RTP time vs system time)
        timing_drift_ms = (sample_time - system_time) * 1000
        self.timing_drift_samples.append(timing_drift_ms)
        
        # Keep only last 100 samples for drift statistics
        if len(self.timing_drift_samples) > 100:
            self.timing_drift_samples.pop(0)
        
        # Report timing quality every 5 minutes
        if self.last_timing_report is None or (system_time - self.last_timing_report) >= 300:
            if len(self.timing_drift_samples) > 10:
                try:
                    drift_array = np.array(self.timing_drift_samples)
                    mean_drift = np.mean(drift_array)
                    std_drift = np.std(drift_array)
                    min_drift = np.min(drift_array)
                    max_drift = np.max(drift_array)
                    
                    # Single-line log to avoid multi-line issues
                    logger.info(f"{self.channel_name}: Timing Quality - "
                               f"drift: {mean_drift:+.1f}±{std_drift:.1f}ms, "
                               f"range: [{min_drift:+.1f}, {max_drift:+.1f}]ms, "
                               f"n={len(self.timing_drift_samples)}")
                except Exception as e:
                    logger.error(f"{self.channel_name}: Timing quality calculation failed: {e}")
                
                self.last_timing_report = system_time
    
    def _check_sync_state(self, header: RTPHeader) -> bool:
        """
        Implement wsprdaemon-style UTC boundary synchronization.
        
        Returns:
            True if packet should be processed, False if dropped during sync
        """
        now = time.time()
        current_second = int(now) % 60
        
        if self.sync_state == 'startup':
            # Wait for second 59 to arm
            if current_second == 59:
                self.sync_state = 'armed'
                logger.info(f"{self.channel_name}: Armed at :59, waiting for :00 to start recording")
            return False  # Drop packets during startup
            
        elif self.sync_state == 'armed':
            # Drop samples until second 0
            if current_second == 0:
                # Start recording at exact UTC minute boundary
                self.utc_aligned_start = int(now / 60) * 60
                self.rtp_start_timestamp = header.timestamp
                self.expected_rtp_timestamp = header.timestamp
                self.sync_state = 'active'
                
                utc_time = datetime.fromtimestamp(self.utc_aligned_start, timezone.utc)
                logger.info(f"{self.channel_name}: Started recording at UTC {utc_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{self.channel_name}: RTP start timestamp = {self.rtp_start_timestamp}")
                return True  # Process this packet
            return False  # Drop packets until :00
            
        elif self.sync_state == 'active':
            return True  # Normal processing
            
        return False
        
    def process_rtp_packet(self, header: RTPHeader, payload: bytes):
        """
        Process incoming RTP packet
        
        Args:
            header: Parsed RTP header
            payload: RTP payload (IQ samples as float32)
        """
        # Check UTC synchronization state
        if not self._check_sync_state(header):
            # Drop packet during startup/armed states
            return
        
        # Track packet metadata
        self.packets_received = getattr(self, 'packets_received', 0) + 1
        self.samples_received = getattr(self, 'samples_received', 0)
        self.last_packet_time = time.time()  # For freshness monitoring
        
        # Gap detection and filling (wsprdaemon-style)
        if self.last_sequence is not None and self.expected_rtp_timestamp is not None:
            expected_seq = (self.last_sequence + 1) & 0xFFFF
            if header.sequence != expected_seq:
                gap_packets = (header.sequence - expected_seq) & 0xFFFF
                self.packets_dropped = getattr(self, 'packets_dropped', 0) + gap_packets
                
                # Verify RTP timestamp jump is consistent with sequence gap
                expected_rtp_ts = self.expected_rtp_timestamp
                actual_rtp_ts = header.timestamp
                rtp_jump = (actual_rtp_ts - expected_rtp_ts) & 0xFFFFFFFF
                expected_jump = gap_packets * 160  # 160 real samples per packet @ 16 kHz (10ms packets)
                
                # If timestamp jump is reasonable, fill gap with silence
                if abs(rtp_jump - expected_jump) < 320:  # Allow 2 packet tolerance (2*160)
                    # Insert silence for missing data
                    # 160 real samples per packet @ 16 kHz = 80 complex I/Q samples per packet
                    gap_input_samples = gap_packets * 80  # At 8 kHz complex
                    gap_output_samples = gap_input_samples // 800  # After 800:1 decimation (8000→10)
                    
                    if gap_output_samples > 0:
                        silence = np.zeros(gap_output_samples, dtype=np.complex64)
                        gap_time = self._calculate_sample_time(expected_rtp_ts)
                        
                        self.daily_buffer.add_samples(gap_time, silence)
                        self.samples_received += gap_output_samples
                        
                        # Track discontinuity
                        discontinuity = TimingDiscontinuity(
                            timestamp=time.time(),
                            sample_index=self.samples_received - gap_output_samples,
                            discontinuity_type=DiscontinuityType.GAP,
                            magnitude_samples=gap_output_samples,
                            magnitude_ms=(gap_output_samples / 10.0) * 1000,  # 10 Hz output rate
                            rtp_sequence_before=self.last_sequence,
                            rtp_sequence_after=header.sequence,
                            rtp_timestamp_before=expected_rtp_ts,
                            rtp_timestamp_after=actual_rtp_ts,
                            wwv_tone_detected=False,
                            explanation=f"Missed {gap_packets} packets, {gap_output_samples} samples lost"
                        )
                        self.discontinuity_tracker.add_discontinuity(discontinuity)
                        
                        logger.warning(f"{self.channel_name}: Filled {gap_packets} dropped packets "
                                     f"({gap_output_samples} output samples) with silence at "
                                     f"{datetime.fromtimestamp(gap_time, timezone.utc).strftime('%H:%M:%S')}")
                else:
                    logger.warning(f"{self.channel_name}: {gap_packets} packets dropped but timestamp "
                                 f"jump ({rtp_jump}) doesn't match expected ({expected_jump})")
        else:
            self.packets_dropped = 0
                
        self.last_sequence = header.sequence
        self.last_timestamp = header.timestamp
        # Update expected timestamp for next packet (160 real samples @ 16 kHz = 10ms packets)
        self.expected_rtp_timestamp = (header.timestamp + 160) & 0xFFFFFFFF
        
        # Parse IQ samples (int16 I/Q pairs from KA9Q radio)
        # Each IQ sample = 2 int16 values (I and Q) = 4 bytes
        if len(payload) % 4 != 0:
            logger.warning(f"{self.channel_name}: Payload size not multiple of 4 (got {len(payload)} bytes)")
            return
            
        # Unpack as interleaved I/Q int16, then normalize to float
        try:
            samples_int16 = np.frombuffer(payload, dtype=np.int16).reshape(-1, 2)
            # Normalize int16 (-32768 to 32767) to float (-1.0 to 1.0)
            samples = samples_int16.astype(np.float32) / 32768.0
            iq_samples = samples[:, 0] + 1j * samples[:, 1]
        except Exception as e:
            logger.error(f"{self.channel_name}: Failed to parse RTP payload as int16: {e}")
            return
        
        # DEBUG: Check for huge values right after RTP extraction
        if self.packets_received % 1000 == 0:
            logger.debug(f"{self.channel_name}: RTP PAYLOAD EXTRACT: len={len(iq_samples)}, "
                        f"min={np.min(np.abs(iq_samples)):.6f}, max={np.max(np.abs(iq_samples)):.6f}, "
                        f"has_nan={np.any(np.isnan(iq_samples))}, has_inf={np.any(np.isinf(iq_samples))}")
        
        # Add to accumulator
        self.sample_accumulator.append(iq_samples)
        accumulated_samples = sum(len(s) for s in self.sample_accumulator)
        
        # Verbose packet logging removed - use DEBUG level if needed
        # Log only every 1000th packet at DEBUG level
        if self.packets_received % 1000 == 0:
            logger.debug(f"{self.channel_name}: RTP packet #{self.packets_received}: "
                        f"{len(iq_samples)} samples, accumulated={accumulated_samples}")
        
        # Resample when we have enough samples
        if accumulated_samples >= self.samples_per_packet:
            # Get all accumulated samples - concatenate to avoid dimension mismatch
            all_samples = np.concatenate(self.sample_accumulator) if len(self.sample_accumulator) > 1 else self.sample_accumulator[0]
            self.sample_accumulator = []
            
            # DEBUG: Check all_samples before resampling
            if np.random.random() < 0.01:
                logger.debug(f"{self.channel_name}: ALL_SAMPLES BEFORE RESAMPLE: len={len(all_samples)}, "
                            f"min={np.min(np.abs(all_samples)):.6f}, max={np.max(np.abs(all_samples)):.6f}, "
                            f"has_nan={np.any(np.isnan(all_samples))}, has_inf={np.any(np.isinf(all_samples))}")
            
            # Main path: Resample to 10 Hz for Digital RF
            resampled = self.resampler.resample(all_samples)
            
            if len(resampled) == 0:
                logger.warning(f"{self.channel_name}: ⚠️  Resampler returned 0 samples from {len(all_samples)} inputs!")
            
            # Calculate Unix time from RTP timestamp (precise, not system clock)
            unix_time = self._calculate_sample_time(header.timestamp)
            
            # WWV tone detection path (parallel to main 10 Hz path)
            if self.tone_detector is not None:
                # DEBUG: Check input to tone resampler
                if np.random.random() < 0.01:
                    logger.debug(f"{self.channel_name}: TONE RESAMPLE INPUT: len={len(all_samples)}, min={np.min(np.abs(all_samples)):.6f}, max={np.max(np.abs(all_samples)):.6f}, has_nan={np.any(np.isnan(all_samples))}")
                
                # Resample to 3 kHz for tone detection
                tone_resampled = self.tone_resampler.resample(all_samples)
                
                # DEBUG: Check output from tone resampler
                if np.random.random() < 0.01:
                    logger.debug(f"{self.channel_name}: TONE RESAMPLE OUTPUT: len={len(tone_resampled)}, min={np.min(np.abs(tone_resampled)) if len(tone_resampled) > 0 else 'empty'}, max={np.max(np.abs(tone_resampled)) if len(tone_resampled) > 0 else 'empty'}, has_nan={np.any(np.isnan(tone_resampled)) if len(tone_resampled) > 0 else 'N/A'}")
                
                self.tone_accumulator.append(tone_resampled)
                
                # Check for tone every 2 seconds worth of data
                accumulated_tone_samples = sum(len(s) for s in self.tone_accumulator)
                if accumulated_tone_samples >= self.tone_samples_per_check:
                    # Only check during narrow window around minute boundary
                    # WWV tone occurs at :00-:01, so check :58-:03 (5 second window)
                    seconds_in_minute = unix_time % 60
                    in_detection_window = (seconds_in_minute >= 58) or (seconds_in_minute <= 3)
                    
                    if in_detection_window:
                        # Concatenate and detect
                        tone_buffer = np.concatenate(self.tone_accumulator) if len(self.tone_accumulator) > 1 else self.tone_accumulator[0]
                        self.tone_accumulator = []
                        
                        # DEBUG: Log tone detection attempts
                        logger.debug(f"{self.channel_name}: Checking for WWV tone (buffer={len(tone_buffer)} samples @ 3 kHz, time={unix_time}, seconds_in_minute={seconds_in_minute:.1f})")
                        
                        # Detect WWV tone
                        detected, onset_idx, timing_error_ms = self.tone_detector.detect_tone_onset(
                            tone_buffer,
                            unix_time
                        )
                        
                        if detected:
                            self.wwv_detections += 1
                            self.wwv_timing_errors.append(timing_error_ms)
                            
                            # Keep only last 60 detections for statistics
                            if len(self.wwv_timing_errors) > 60:
                                self.wwv_timing_errors.pop(0)
                            
                            logger.info(f"{self.channel_name}: WWV tone detected! "
                                       f"Timing error: {timing_error_ms:+.1f} ms "
                                       f"(detection #{self.wwv_detections})")
                    else:
                        # Outside detection window - discard accumulated samples
                        self.tone_accumulator = []
            
            # Add to daily buffer
            completed_day = self.daily_buffer.add_samples(unix_time, resampled)
            
            # Track timing quality (per-minute stats and drift monitoring)
            self._track_timing_quality(unix_time, len(resampled))
            
            # Write completed day to Digital RF
            if completed_day and HAS_DIGITAL_RF:
                day_date, day_data = completed_day
                self._write_digital_rf(day_date, day_data)
                
            # Track received samples
            self.samples_received += len(resampled)
            
    def _write_digital_rf(self, day_date, data: np.ndarray):
        """
        Write completed day to Digital RF format (wsprdaemon-compatible)
        
        Args:
            day_date: Date of the data
            data: Complex IQ samples for the full day
        """
        try:
            # Calculate midnight UTC timestamp for this date (wsprdaemon-style)
            day_start = datetime.combine(day_date, datetime.min.time(), tzinfo=timezone.utc)
            start_time = day_start.timestamp()
            
            # Digital RF start_global_index must be tied to midnight UTC
            # This is critical for PSWS compatibility
            start_global_index = int(start_time * 10)  # 10 Hz sample rate
            
            # Create Digital RF writer directory
            drf_dir = self.channel_dir
            
            # Generate UUID for this dataset
            import uuid
            dataset_uuid = uuid.uuid4().hex
            
            logger.info(f"{self.channel_name}: Writing Digital RF for {day_date}")
            logger.info(f"{self.channel_name}: start_global_index = {start_global_index} (midnight UTC)")
            logger.info(f"{self.channel_name}: {len(data)} complex samples (~{len(data)/864000*100:.1f}% of day)")
            
            # Create writer (wsprdaemon-compatible parameters)
            with drf.DigitalRFWriter(
                str(drf_dir),
                dtype=np.complex64,
                subdir_cadence_secs=3600,      # 1 hour subdirectories (wsprdaemon uses 3600)
                file_cadence_millisecs=1000,    # 1 second files (wsprdaemon uses 1000)
                start_global_index=start_global_index,  # CRITICAL: Midnight UTC
                sample_rate_numerator=10,
                sample_rate_denominator=1,
                uuid_str=dataset_uuid,
                compression_level=6,            # wsprdaemon uses 6
                checksum=False,
                is_complex=True,                # True for I/Q data
                num_subchannels=1,
                is_continuous=True,             # Now valid because we fill gaps!
                marching_periods=False          # wsprdaemon uses False
            ) as writer:
                # Write data as complex64
                writer.rf_write(data)
            
            # Write metadata (wsprdaemon-compatible format)
            metadata_dir = drf_dir / 'metadata'
            metadata_dir.mkdir(parents=True, exist_ok=True)
            
            metadata = {
                'callsign': self.station_config.get('callsign', 'UNKNOWN'),
                'grid_square': self.station_config.get('grid_square', 'UNKNOWN'),
                'receiver_name': self.station_config.get('instrument_id', 'UNKNOWN'),
                'center_frequencies': np.array([self.frequency_hz], dtype=np.float64),
                'uuid_str': dataset_uuid,
                'sample_rate': 10.0,
                'date': day_date.isoformat()
            }
            
            # Write metadata using DigitalMetadataWriter
            with drf.DigitalMetadataWriter(
                str(metadata_dir),
                subdir_cadence_secs=3600,
                file_cadence_secs=3600,
                sample_rate_numerator=10,
                sample_rate_denominator=1,
                file_name='metadata'
            ) as metadata_writer:
                metadata_writer.write(start_global_index, metadata)
            
            logger.info(f"{self.channel_name}: ✅ Digital RF write complete for {day_date}")
                       
        except Exception as e:
            logger.error(f"{self.channel_name}: Failed to write Digital RF: {e}", exc_info=True)


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
        print("🔍 DEBUG: GRAPERecorderManager.start() called")
        if self.running:
            logger.warning("Recorder already running")
            return
            
        # Get configuration
        print("🔍 DEBUG: Getting configuration...")
        station_config = self.config.get('station', {})
        recorder_config = self.config.get('recorder', {})
        channels = recorder_config.get('channels', [])
        print(f"🔍 DEBUG: Found {len(channels)} channels in config")
        
        # Get addresses
        ka9q_config = self.config.get('ka9q', {})
        status_address = ka9q_config.get('status_address', '239.192.152.141')
        print(f"🔍 DEBUG: Status address: {status_address}")
        
        # Data multicast address: where RTP streams are broadcast
        # This is different from status_address (which is for control/discovery)
        # If status_address is mDNS (e.g., bee1-hf-status.local), we need to get
        # the actual data multicast from radiod's channel configuration
        data_address = ka9q_config.get('data_address')
        
        if data_address:
            # Explicit data address in config
            multicast_address = data_address.split(':')[0] if ':' in data_address else data_address
            print(f"🔍 DEBUG: Using explicit data_address: {multicast_address}")
        elif '.' in status_address and not status_address.endswith('.local'):
            # Status address is already an IP address, use it
            multicast_address = status_address.split(':')[0] if ':' in status_address else status_address
            print(f"🔍 DEBUG: Using status_address as data address: {multicast_address}")
        else:
            # Status address is mDNS name, query radiod to get data multicast
            # For now, use default GRAPE data multicast
            multicast_address = '239.192.152.141'
            print(f"🔍 DEBUG: Status address is mDNS, using default data multicast: {multicast_address}")
            logger.info(f"Using default data multicast {multicast_address} (status_address is mDNS: {status_address})")
            
        # Create output directory
        print("🔍 DEBUG: Creating output directory...")
        output_dir = Path(recorder_config.get('archive_dir', '/tmp/grape-data'))
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"🔍 DEBUG: Output dir created: {output_dir}")
        
        # Ensure all channels exist in radiod before starting recording
        print("🔍 DEBUG: About to check radiod channels...")
        logger.info("Checking radiod channels...")
        # ChannelManager uses status_address for control/discovery
        channel_manager = ChannelManager(status_address)
        
        # Build channel specifications from config
        required_channels = []
        for channel in channels:
            if not channel.get('enabled', True):
                continue
            
            required_channels.append({
                'ssrc': channel['ssrc'],
                'frequency_hz': channel['frequency_hz'],
                'preset': channel.get('preset', 'iq'),
                'sample_rate': channel.get('sample_rate', 16000),
                'agc': channel.get('agc', 0),
                'gain': channel.get('gain', 0),
                'description': channel.get('description', '')
            })
        
        # Create/verify channels
        if required_channels:
            logger.info(f"Ensuring {len(required_channels)} channels exist in radiod...")
            if not channel_manager.ensure_channels_exist(required_channels, update_existing=False):
                logger.error("Failed to ensure all channels exist. Recording may not work correctly.")
                # Continue anyway - some channels might exist
        else:
            logger.warning("No enabled channels configured")
        
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
            
            # Timing quality metrics
            timing_drift_mean = 0.0
            timing_drift_std = 0.0
            timing_drift_samples_count = len(getattr(rec, 'timing_drift_samples', []))
            
            if timing_drift_samples_count > 0:
                drift_array = np.array(rec.timing_drift_samples)
                timing_drift_mean = float(np.mean(drift_array))
                timing_drift_std = float(np.std(drift_array))
            
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
                'sync_state': getattr(rec, 'sync_state', 'unknown'),
                
                # Timing Quality
                'timing_drift_mean_ms': round(timing_drift_mean, 2),
                'timing_drift_std_ms': round(timing_drift_std, 2),
                'timing_samples_count': timing_drift_samples_count,
                
                # Health
                'health_status': health_status,
                'health_message': health_message
            }
            
            # Discontinuity tracking stats
            if hasattr(rec, 'discontinuity_tracker'):
                disc_stats = rec.discontinuity_tracker.get_stats()
                rec_status['discontinuities'] = disc_stats
            
            # WWV timing validation stats
            if hasattr(rec, 'tone_detector') and rec.tone_detector is not None:
                wwv_timing_error_mean = 0.0
                wwv_timing_error_std = 0.0
                wwv_timing_error_max = 0.0
                
                if hasattr(rec, 'wwv_timing_errors') and len(rec.wwv_timing_errors) > 0:
                    error_array = np.array(rec.wwv_timing_errors)
                    wwv_timing_error_mean = float(np.mean(error_array))
                    wwv_timing_error_std = float(np.std(error_array))
                    wwv_timing_error_max = float(np.max(np.abs(error_array)))
                
                # Calculate expected detections (1 per minute if recording for >1 minute)
                expected_detections = max(1, int(elapsed / 60))
                detection_rate = (getattr(rec, 'wwv_detections', 0) / expected_detections) if expected_detections > 0 else 0.0
                
                rec_status['timing_validation'] = {
                    'enabled': True,
                    'tone_type': 'wwv_1200hz',
                    'tone_detections_total': getattr(rec, 'wwv_detections', 0),
                    'tone_detections_expected': expected_detections,
                    'detection_rate': round(detection_rate, 2),
                    'timing_error_mean_ms': round(wwv_timing_error_mean, 2),
                    'timing_error_std_ms': round(wwv_timing_error_std, 2),
                    'timing_error_max_ms': round(wwv_timing_error_max, 2),
                    'last_detection_time': datetime.fromtimestamp(
                        getattr(rec.tone_detector, 'last_detection_time', 0),
                        timezone.utc
                    ).isoformat() if getattr(rec.tone_detector, 'last_detection_time', 0) > 0 else None,
                    'last_timing_error_ms': round(rec.wwv_timing_errors[-1], 2) if len(rec.wwv_timing_errors) > 0 else None
                }
            
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
