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
from datetime import datetime, timezone, date
from typing import Dict, Optional, Tuple, Callable, List
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
from .grape_channel_recorder_v2 import GRAPEChannelRecorderV2
from .radiod_health import RadiodHealthChecker
from .session_tracker import SessionBoundaryTracker

logger = logging.getLogger(__name__)

# Global stats file for web UI monitoring
# Default location - will be overridden by config if PathResolver is used
STATS_FILE = Path('/tmp/signal-recorder-stats.json')


# ===== Discontinuity Tracking =====

class DiscontinuityType(Enum):
    """Types of discontinuities in the data stream"""
    GAP = "gap"                              # Missed packets, samples lost
    SYNC_ADJUST = "sync_adjust"              # Time sync adjustment
    RTP_RESET = "rtp_reset"                  # RTP sequence/timestamp reset
    OVERFLOW = "overflow"                    # Buffer overflow, samples dropped
    UNDERFLOW = "underflow"                  # Buffer underflow, samples duplicated
    SOURCE_UNAVAILABLE = "source_unavailable"  # radiod down/channel missing
    RECORDER_OFFLINE = "recorder_offline"    # signal-recorder daemon not running


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


# ===== Multi-Station Tone Detection =====

class MultiStationToneDetector:
    """
    Detect time signal tones from multiple stations using matched filtering
    
    Stations:
    - WWV (Fort Collins): 1000 Hz, 0.8s duration - PRIMARY for time_snap
    - WWVH (Hawaii): 1200 Hz, 0.8s duration - Propagation analysis
    - CHU (Canada): 1000 Hz, 0.5s duration - Alternate time_snap
    
    Uses phase-invariant quadrature matched filtering for robust detection
    in poor SNR conditions and with phase-shifted signals.
    """
    
    def __init__(self, channel_name: str, sample_rate=3000):
        """
        Initialize multi-station tone detector
        
        Args:
            channel_name: Channel name to determine which stations to detect
            sample_rate: Processing sample rate (Hz), default 3000 Hz
        """
        self.channel_name = channel_name
        self.sample_rate = sample_rate
        self.is_chu_channel = 'CHU' in channel_name
        
        # Create matched filter templates (quadrature for phase-invariance)
        self.templates = {}
        
        if self.is_chu_channel:
            # CHU frequencies: 3.33, 7.85, 14.67 MHz
            # Only detect CHU 1000 Hz (0.5s)
            self.templates['CHU'] = self._create_template(1000, 0.5)
        else:
            # WWV frequencies: 2.5, 5, 10, 15, 20, 25 MHz
            # Detect BOTH WWV and WWVH
            self.templates['WWV'] = self._create_template(1000, 0.8)
            self.templates['WWVH'] = self._create_template(1200, 0.8)
        
        # State tracking
        self.last_detections_by_minute = {}  # minute_boundary -> [detections]
        self.detection_count = 0
        
        logger.info(f"{channel_name}: MultiStationToneDetector initialized - "
                   f"stations={list(self.templates.keys())}")
    
    def _create_template(self, frequency_hz: float, duration_sec: float):
        """
        Create quadrature matched filter templates (sin and cos)
        
        Args:
            frequency_hz: Tone frequency (1000 or 1200 Hz)
            duration_sec: Tone duration (0.5 or 0.8 seconds)
            
        Returns:
            dict with 'sin', 'cos', 'frequency', 'duration'
        """
        from scipy import signal as scipy_signal
        
        t = np.arange(0, duration_sec, 1/self.sample_rate)
        
        # Apply Tukey window for smooth edges
        window = scipy_signal.windows.tukey(len(t), alpha=0.1)
        
        # Create quadrature pair
        template_sin = np.sin(2 * np.pi * frequency_hz * t) * window
        template_cos = np.cos(2 * np.pi * frequency_hz * t) * window
        
        # Normalize to unit energy for proper matched filtering
        template_sin /= np.linalg.norm(template_sin)
        template_cos /= np.linalg.norm(template_cos)
        
        return {
            'sin': template_sin,
            'cos': template_cos,
            'frequency': frequency_hz,
            'duration': duration_sec
        }
    
    def detect_tones(self, iq_samples: np.ndarray, current_unix_time: float):
        """
        Detect all applicable station tones in IQ samples
        
        Args:
            iq_samples: Complex IQ samples at self.sample_rate
            current_unix_time: UTC time for first sample
            
        Returns:
            List[dict]: All detected tones, sorted by SNR (strongest first)
            Each detection contains:
            - station: 'WWV', 'WWVH', or 'CHU'
            - frequency_hz: 1000 or 1200 Hz
            - onset_sample_idx: Sample index of rising edge
            - timing_error_ms: Error vs UTC :00.000
            - snr_db: Signal-to-noise ratio estimate
            - duration_sec: Expected tone duration
            - correlation_peak: Peak correlation value
        """
        from scipy.signal import correlate
        
        # Get minute boundary for the EXPECTED tone (around :00.0)
        # Buffer starts ~:58-:59, so tone is in the NEXT minute
        # Find the nearest minute boundary that's within our buffer
        buffer_duration_sec = len(iq_samples) / self.sample_rate
        buffer_end_time = current_unix_time + buffer_duration_sec
        
        # The tone should be within our buffer - find which minute boundary
        minute_boundary = int((current_unix_time + buffer_duration_sec/2) / 60) * 60
        
        # Check if we already detected this minute (prevent duplicates)
        if minute_boundary in self.last_detections_by_minute:
            # Already processed this minute
            return []
        
        # Step 1: AM demodulation (extract envelope)
        magnitude = np.abs(iq_samples)
        audio_signal = magnitude - np.mean(magnitude)  # AC coupling
        
        # Diagnostic: Check if we have signal energy
        audio_rms = np.sqrt(np.mean(audio_signal**2))
        logger.info(f"AM demod: iq_len={len(iq_samples)}, audio_rms={audio_rms:.6f}, mag_mean={np.mean(magnitude):.6f}")
        
        detections = []
        
        # Step 2: Correlate with each station template
        for station_name, template in self.templates.items():
            detection = self._correlate_with_template(
                audio_signal,
                station_name,
                template,
                current_unix_time,
                minute_boundary
            )
            
            if detection:
                detections.append(detection)
        
        # Sort by SNR (strongest signal first)
        detections.sort(key=lambda d: d['snr_db'], reverse=True)
        
        # Cache detections for this minute
        if detections:
            self.last_detections_by_minute[minute_boundary] = detections
            self.detection_count += len(detections)
            
            # Cleanup old minutes (keep last 10)
            if len(self.last_detections_by_minute) > 10:
                oldest_minute = min(self.last_detections_by_minute.keys())
                del self.last_detections_by_minute[oldest_minute]
        
        return detections
    
    def _correlate_with_template(self, audio_signal: np.ndarray, station_name: str,
                                 template: dict, current_unix_time: float,
                                 minute_boundary: int):
        """
        Correlate audio signal with station template
        
        Returns:
            dict with detection info, or None if no detection
        """
        from scipy.signal import correlate
        
        template_sin = template['sin']
        template_cos = template['cos']
        frequency = template['frequency']
        duration = template['duration']
        
        # Perform quadrature correlation (phase-invariant)
        try:
            corr_sin = correlate(audio_signal, template_sin, mode='valid')
            corr_cos = correlate(audio_signal, template_cos, mode='valid')
        except ValueError as e:
            # Buffer too short for correlation
            logger.warning(f"{station_name} @ {frequency}Hz: Correlation failed: {e}")
            return None
        
        if len(corr_sin) == 0 or len(corr_cos) == 0:
            logger.warning(f"{station_name} @ {frequency}Hz: Empty correlation result")
            return None
        
        # Combine to get phase-invariant magnitude: sqrt(sin^2 + cos^2)
        min_len = min(len(corr_sin), len(corr_cos))
        correlation = np.sqrt(corr_sin[:min_len]**2 + corr_cos[:min_len]**2)
        
        # Expected position: tone should be at start of minute
        # Account for buffer start time
        buffer_offset_sec = current_unix_time - minute_boundary
        expected_pos_samples = int(-buffer_offset_sec * self.sample_rate)
        
        # Search window: ±500ms around expected position
        search_window = int(0.5 * self.sample_rate)
        search_start = max(0, expected_pos_samples - search_window)
        search_end = min(len(correlation), expected_pos_samples + search_window)
        
        logger.info(f"{station_name} @ {frequency}Hz: corr_len={len(correlation)}, expected_pos={expected_pos_samples}, "
                   f"search_window=[{search_start}:{search_end}], buffer_offset={buffer_offset_sec:.2f}s")
        
        if search_start >= search_end:
            logger.warning(f"{station_name} @ {frequency}Hz: Invalid search window!")
            return None
        
        # Find peak within search window
        search_region = correlation[search_start:search_end]
        local_peak_idx = np.argmax(search_region)
        peak_idx = search_start + local_peak_idx
        peak_val = correlation[peak_idx]
        
        # Noise-adaptive threshold: Use noise from OUTSIDE the search window
        noise_samples = np.concatenate([
            correlation[:max(0, search_start - 100)],
            correlation[min(len(correlation), search_end + 100):]
        ])
        
        if len(noise_samples) > 100:
            noise_mean = np.mean(noise_samples)
            noise_std = np.std(noise_samples)
            noise_floor = noise_mean + 2.0 * noise_std  # Lowered from 2.5 for weak signal detection
        else:
            noise_mean = np.mean(correlation)
            noise_std = np.std(correlation)
            noise_floor = noise_mean + 2.0 * noise_std
        
        # Calculate timing relative to minute boundary
        onset_sample_idx = peak_idx
        onset_time = current_unix_time + (onset_sample_idx / self.sample_rate)
        timing_error_sec = onset_time - minute_boundary
        
        # Handle wraparound
        if timing_error_sec > 30:
            timing_error_sec -= 60
        elif timing_error_sec < -30:
            timing_error_sec += 60
        
        timing_error_ms = timing_error_sec * 1000
        
        # Calculate SNR
        if noise_mean > 0 and peak_val > noise_mean:
            snr_db = 20 * np.log10(peak_val / noise_mean)
        else:
            snr_db = 0.0
        
        # Diagnostic logging BEFORE threshold check
        logger.info(f"{station_name} @ {frequency}Hz: peak={peak_val:.2f}, noise_floor={noise_floor:.2f}, "
                   f"SNR={snr_db:.1f}dB, timing_err={timing_error_ms:+.1f}ms")
        
        # Check if peak is significant
        if peak_val <= noise_floor:
            logger.info(f"  -> REJECTED (peak <= threshold)")
            return None
        
        detection = {
            'station': station_name,
            'frequency_hz': frequency,
            'onset_sample_idx': onset_sample_idx,
            'timing_error_ms': timing_error_ms,
            'snr_db': snr_db,
            'duration_sec': duration,
            'correlation_peak': float(peak_val),
            'onset_time': onset_time
        }
        
        logger.info(f"{self.channel_name}: ✅ {station_name} DETECTED! "
                   f"Freq: {frequency}Hz, Duration: {duration:.1f}s, "
                   f"Timing error: {timing_error_ms:+.1f}ms, SNR: {snr_db:.1f}dB")
        
        return detection
    
    def detect_tone_onset(self, iq_samples: np.ndarray, buffer_start_time: float):
        """
        Compatibility wrapper for V2 recorder's old API
        
        Returns:
            tuple: (detected: bool, onset_idx: int, timing_error_ms: float)
        """
        detections = self.detect_tones(iq_samples, buffer_start_time)
        
        if detections:
            # Return first (strongest) detection
            det = detections[0]
            return (True, det['onset_sample_idx'], det['timing_error_ms'])
        else:
            return (False, 0, 0.0)


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
                    
                # Extract payload - account for CSRC list and extension headers
                payload_offset = 12 + (header.csrc_count * 4)  # Base header + CSRC list
                
                # Handle extension header if present
                if header.extension:
                    if len(data) >= payload_offset + 4:
                        # Extension header: 2 bytes profile + 2 bytes length (in 32-bit words)
                        ext_header = struct.unpack('>HH', data[payload_offset:payload_offset+4])
                        ext_length_words = ext_header[1]
                        payload_offset += 4 + (ext_length_words * 4)
                
                if payload_offset >= len(data):
                    logger.warning(f"Invalid RTP packet: payload_offset={payload_offset}, len={len(data)}")
                    continue
                
                payload = data[payload_offset:]
                
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
        self.samples_per_hour = sample_rate * 3600  # 36,000 samples per hour
        
        # Initialize buffer with NaN (for gap detection)
        self.buffer = np.full(self.samples_per_day, np.nan, dtype=np.complex64)
        self.current_day = None
        self.last_write_hour = None  # Track last hourly write
        
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
    
    def should_write_hourly(self, timestamp: float) -> bool:
        """Check if we should perform an hourly write"""
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        current_hour = (dt.date(), dt.hour)
        
        if self.last_write_hour != current_hour and dt.minute >= 1:  # Write 1 min past the hour
            self.last_write_hour = current_hour
            return True
        return False
    
    def get_current_data(self) -> Optional[Tuple[date, np.ndarray]]:
        """Get current day's data for periodic writes"""
        if self.current_day is not None:
            # Return copy of current buffer
            return (self.current_day, self.buffer.copy())
        return None
        
    def get_buffer(self) -> np.ndarray:
        """Get current buffer"""
        return self.buffer.copy()



# ===== GRAPEChannelRecorder V1 ARCHIVED =====
# The original GRAPEChannelRecorder class (867 lines) has been archived to
# archive/legacy-code/grape_channel_recorder_v1/ due to:
#   1. Never used in production (GRAPERecorderManager uses V2)
#   2. Contains critical 8 kHz bug (should be 16 kHz complex IQ)
#   3. Fixed in GRAPEChannelRecorderV2 (grape_channel_recorder_v2.py)
# See archive README for details. Use V2 instead.
# =============================================

class GRAPERecorderManager:
    """
    Manager for multiple GRAPE channel recorders
    """
    
    def __init__(self, config: dict, path_resolver=None):
        """
        Initialize recorder manager
        
        Args:
            config: Configuration dictionary
            path_resolver: Optional PathResolver for standardized paths
        """
        self.config = config
        self.path_resolver = path_resolver
        self.recorders: Dict[int, GRAPEChannelRecorder] = {}
        self.rtp_receiver = None
        self.running = False
        
        # Health monitoring
        ka9q_config = config.get('ka9q', {})
        status_address = ka9q_config.get('status_address', '239.192.152.141')
        self._health_checker = RadiodHealthChecker(status_address)
        self._recovery_thread = None
        self._channel_configs = {}  # Store configs for recreation
        
        # Set global stats file location
        global STATS_FILE
        if path_resolver:
            STATS_FILE = path_resolver.get_status_file()
            logger.info(f"Stats file: {STATS_FILE}")
        else:
            logger.info(f"Using default stats file: {STATS_FILE}")
        
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
        if self.path_resolver:
            output_dir = self.path_resolver.get_data_dir()
        else:
            # Backward compatibility
            output_dir = Path(recorder_config.get('archive_dir', '/tmp/grape-data'))
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"🔍 DEBUG: Output dir created: {output_dir}")
        
        # Setup upload directory for Digital RF (optional)
        upload_dir = None
        upload_config = recorder_config.get('upload_dir', None)
        if upload_config:
            upload_dir = Path(upload_config)
            upload_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Digital RF upload directory: {upload_dir}")
        else:
            logger.info("Digital RF upload disabled (no upload_dir configured)")
        
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
            
            # Check if WWV channel for tone detection
            is_wwv = 'WWV' in channel_name or 'CHU' in channel_name
            
            # Setup analytics directory
            if self.path_resolver:
                analytics_dir = self.path_resolver.get_analytics_dir()
            else:
                analytics_dir = output_dir.parent / 'analytics'
            analytics_dir.mkdir(parents=True, exist_ok=True)
            
            # Create V2 recorder with 30-second window architecture for tone detection
            recorder = GRAPEChannelRecorderV2(
                ssrc=ssrc,
                channel_name=channel_name,
                frequency_hz=frequency_hz,
                archive_dir=output_dir,
                analytics_dir=analytics_dir,
                station_config=station_config,
                is_wwv_channel='WWV' in channel_name or 'CHU' in channel_name,
                path_resolver=self.path_resolver,
                upload_dir=upload_dir  # Digital RF upload (optional)
            )
            
            # Register with RTP receiver
            self.rtp_receiver.register_callback(ssrc, recorder.process_rtp_packet)
            
            self.recorders[ssrc] = recorder
            
            # Store channel config for potential recreation
            self._channel_configs[ssrc] = channel
            
            logger.info(f"Started recorder for {channel_name}")
            
        # Start RTP receiver
        self.rtp_receiver.start()
        self.running = True
        
        # Start health monitoring thread
        self._recovery_thread = threading.Thread(target=self._health_monitor_loop, daemon=True)
        self._recovery_thread.start()
        logger.info("Health monitoring thread started")
        
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
            output_dir_path = None
            try:
                # V2 has file_writer.output_dir, V1 has channel_dir
                if hasattr(rec, 'file_writer') and hasattr(rec.file_writer, 'output_dir'):
                    output_dir_path = rec.file_writer.output_dir  # V2
                    file_pattern = '*.npz'
                elif hasattr(rec, 'channel_dir'):
                    output_dir_path = rec.channel_dir  # V1
                    file_pattern = '*.h5'
                
                if output_dir_path and output_dir_path.exists():
                    for f in output_dir_path.rglob(file_pattern):
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
                
                # Multicast info (for audio streaming)
                'multicast_address': self.rtp_receiver.multicast_address,
                'multicast_port': self.rtp_receiver.port,
                
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
                'output_dir': str(output_dir_path) if output_dir_path else 'N/A',
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
            
            # Multi-station timing validation stats
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
                
                # Primary timing station (WWV or CHU)
                wwv_det = getattr(rec, 'wwv_detections', 0)
                chu_det = getattr(rec, 'chu_detections', 0)
                primary_det = wwv_det + chu_det
                detection_rate = (primary_det / expected_detections) if expected_detections > 0 else 0.0
                
                # Determine which stations are active
                stations_active = []
                if wwv_det > 0:
                    stations_active.append('WWV')
                if chu_det > 0:
                    stations_active.append('CHU')
                if getattr(rec, 'wwvh_detections', 0) > 0:
                    stations_active.append('WWVH')
                
                # Differential delay statistics (WWV vs WWVH)
                differential_mean = 0.0
                differential_std = 0.0
                if hasattr(rec, 'differential_delays') and len(rec.differential_delays) > 0:
                    diff_array = np.array(rec.differential_delays)
                    differential_mean = float(np.mean(diff_array))
                    differential_std = float(np.std(diff_array))
                
                # RTP vs WWV drift statistics (sample rate accuracy)
                rtp_drift_ppm_mean = 0.0
                rtp_drift_ppm_std = 0.0
                rtp_drift_samples = 0
                if hasattr(rec, 'rtp_wwv_intervals') and len(rec.rtp_wwv_intervals) > 0:
                    ppm_values = [interval[2] for interval in rec.rtp_wwv_intervals]
                    rtp_drift_ppm_mean = float(np.mean(ppm_values))
                    rtp_drift_ppm_std = float(np.std(ppm_values))
                    rtp_drift_samples = len(ppm_values)
                
                rec_status['timing_validation'] = {
                    'enabled': True,
                    'stations_active': stations_active,
                    'wwv_detections': wwv_det,
                    'wwvh_detections': getattr(rec, 'wwvh_detections', 0),
                    'chu_detections': chu_det,
                    'total_detections': primary_det,
                    'expected_detections': expected_detections,
                    'detection_rate': round(detection_rate, 2),
                    'timing_error_mean_ms': round(wwv_timing_error_mean, 2),
                    'timing_error_std_ms': round(wwv_timing_error_std, 2),
                    'timing_error_max_ms': round(wwv_timing_error_max, 2),
                    'wwv_wwvh_differential_mean_ms': round(differential_mean, 2),
                    'wwv_wwvh_differential_std_ms': round(differential_std, 2),
                    'last_timing_error_ms': round(rec.wwv_timing_errors[-1], 2) if hasattr(rec, 'wwv_timing_errors') and len(rec.wwv_timing_errors) > 0 else None,
                    'rtp_drift_ppm_mean': round(rtp_drift_ppm_mean, 3),
                    'rtp_drift_ppm_std': round(rtp_drift_ppm_std, 3),
                    'rtp_drift_samples': rtp_drift_samples
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
    
    def _health_monitor_loop(self):
        """
        Background thread: Monitor channel health and recover from failures.
        
        Checks every 30 seconds for:
        - Radiod liveness (status multicast active)
        - Channel health (receiving packets)
        - Channel existence in radiod
        
        Automatically recreates missing channels.
        """
        logger.info("Health monitoring loop starting...")
        
        while self.running:
            try:
                time.sleep(30)
                
                if not self.running:
                    break
                
                # Check if radiod is alive
                if not self._health_checker.is_radiod_alive(timeout_sec=3.0):
                    logger.warning("Radiod appears down - waiting for restart")
                    time.sleep(30)
                    continue
                
                # Check each channel
                for ssrc, recorder in self.recorders.items():
                    if not recorder._check_channel_health():
                        # Channel silent - verify it exists in radiod
                        if not self._health_checker.verify_channel_exists(ssrc):
                            logger.error(
                                f"Channel {recorder.channel_name} (SSRC {ssrc}) "
                                f"missing from radiod - attempting recreation"
                            )
                            self._recreate_channel(ssrc)
                        else:
                            logger.warning(
                                f"Channel {recorder.channel_name} exists in radiod but no data - "
                                f"possible multicast issue"
                            )
                
            except Exception as e:
                logger.error(f"Health monitoring error: {e}", exc_info=True)
                time.sleep(30)
        
        logger.info("Health monitoring loop exiting")
    
    def _recreate_channel(self, ssrc: int):
        """
        Recreate a missing channel in radiod.
        
        Args:
            ssrc: SSRC of the channel to recreate
        """
        if ssrc not in self._channel_configs:
            logger.error(f"No config found for SSRC {ssrc} - cannot recreate")
            return
        
        channel_config = self._channel_configs[ssrc]
        
        try:
            from signal_recorder.channel_manager import ChannelManager
            
            ka9q_config = self.config.get('ka9q', {})
            status_address = ka9q_config.get('status_address', '239.192.152.141')
            
            channel_manager = ChannelManager(status_address)
            
            # Build channel spec
            channel_spec = {
                'ssrc': channel_config['ssrc'],
                'frequency_hz': channel_config['frequency_hz'],
                'preset': channel_config.get('preset', 'iq'),
                'sample_rate': channel_config.get('sample_rate', 16000),
                'agc': channel_config.get('agc', 0),
                'gain': channel_config.get('gain', 0),
                'description': channel_config.get('description', '')
            }
            
            success = channel_manager.ensure_channel_exists(channel_spec)
            
            if success:
                logger.info(f"Successfully recreated channel {channel_config.get('description')} (SSRC {ssrc})")
                
                # Reset packet timer to avoid immediate re-trigger
                if ssrc in self.recorders:
                    self.recorders[ssrc]._last_packet_time = time.time()
            else:
                logger.error(f"Failed to recreate channel {channel_config.get('description')} (SSRC {ssrc})")
                
        except Exception as e:
            logger.error(f"Channel recreation exception for SSRC {ssrc}: {e}", exc_info=True)
