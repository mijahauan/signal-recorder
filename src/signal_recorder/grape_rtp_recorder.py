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

logger = logging.getLogger(__name__)

# Global stats file for web UI monitoring
# Default location - will be overridden by config if PathResolver is used
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


class GRAPEChannelRecorder:
    """
    Per-channel GRAPE recorder with Digital RF output
    """
    
    def __init__(self, ssrc: int, channel_name: str, frequency_hz: float, output_dir: Path,
                 station_config: dict, is_wwv_audio_channel: bool = False, path_resolver=None):
        """
        Initialize GRAPE channel recorder
        
        Args:
            ssrc: RTP SSRC identifier
            channel_name: Channel name (e.g., "WWV-10.0")
            frequency_hz: Center frequency
            output_dir: Base output directory for Digital RF
            station_config: Station configuration dict
            is_wwv_audio_channel: True if this is a WWV audio channel (PCM) instead of IQ
            path_resolver: Optional PathResolver for standardized paths
        """
        self.ssrc = ssrc
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.station_config = station_config
        self.is_wwv_audio_channel = is_wwv_audio_channel
        self.path_resolver = path_resolver
        
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
        
        # Performance metrics for status reporting
        self.packets_received = 0
        self.packets_dropped = 0
        self.samples_received = 0
        self.start_time = time.time()
        self.last_packet_time = time.time()
        
        # Time_snap correction tracking
        self.time_snap_corrections = []  # List of (time, error_ms, new_ref) tuples
        self.last_time_snap_correction = None  # Unix time of last correction
        self.time_snap_error_threshold_ms = 10.0  # Correct if error > 10ms (trust WWV over wall clock)
        self.time_snap_min_interval_sec = 60  # Allow corrections every minute (wait for stable detections)
        
        # RTP vs WWV drift tracking (the metric that matters)
        self.last_wwv_rtp_timestamp = None  # RTP timestamp of last WWV detection
        self.last_wwv_detection_time = None  # Wall clock time of last WWV detection
        self.rtp_wwv_intervals = []  # List of (rtp_interval, expected_interval, ppm_error)
        
        # Discontinuity tracking (Phase 1)
        self.discontinuity_tracker = DiscontinuityTracker(channel_name)
        
        # Multi-station tone detection for WWV/CHU IQ channels
        # Detects WWV (1000 Hz), WWVH (1200 Hz), and CHU (1000 Hz)
        self.is_wwv_or_chu_channel = any(x in channel_name.upper() for x in ['WWV', 'CHU'])
        if self.is_wwv_or_chu_channel:
            # Create 3 kHz resampler for tone detection (parallel to main 10 Hz path)
            # Input is 16 kHz complex IQ (after RTP parsing)
            self.tone_resampler = Resampler(input_rate=16000, output_rate=3000)
            self.tone_detector = MultiStationToneDetector(channel_name=channel_name, sample_rate=3000)
            self.tone_accumulator = []  # Buffer for tone detection
            self.tone_accumulator_start_time = None  # Timestamp of first sample in accumulator
            self.tone_samples_per_check = 15000  # Accumulate 5 seconds at 3 kHz to ensure full tone capture
            self.wwv_detections = 0
            self.wwvh_detections = 0
            self.chu_detections = 0
            self.wwv_timing_errors = []  # Track timing errors from primary (WWV/CHU)
            self.differential_delays = []  # Track WWV-WWVH differential delays
            logger.info(f"{channel_name}: Multi-station tone detection ENABLED (WWV/WWVH/CHU, 3 kHz sample rate)")
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
        # Both times should be relative to the same reference point (recording start)
        if self.utc_aligned_start is not None:
            system_elapsed = system_time - self.utc_aligned_start
            rtp_elapsed = sample_time - self.utc_aligned_start
            # Drift is the difference between how much time passed according to each clock
            timing_drift_ms = (rtp_elapsed - system_elapsed) * 1000
        else:
            timing_drift_ms = 0.0  # No drift calculation before sync
        
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
    
    def _apply_time_snap_correction(self, wwv_detection_time: float, timing_error_ms: float, tone_rtp_timestamp: int):
        """
        Apply KA9Q-style time_snap correction based on WWV tone timing.
        
        Updates the time reference (utc_aligned_start, rtp_start_timestamp) when WWV tone
        indicates significant timing error.
        
        Args:
            wwv_detection_time: Unix timestamp when tone was detected (current time reference)
            timing_error_ms: Measured timing error in milliseconds (positive = late)
            tone_rtp_timestamp: RTP timestamp at tone onset
        
        Returns:
            bool: True if correction was applied
        """
        # Check if correction is warranted
        if abs(timing_error_ms) < self.time_snap_error_threshold_ms:
            # Error too small to correct
            logger.info(f"{self.channel_name}: Time_snap correction NOT needed - error {timing_error_ms:+.1f}ms < threshold {self.time_snap_error_threshold_ms}ms")
            return False
        
        # Check if we've corrected recently (avoid oscillation)
        if self.last_time_snap_correction is not None:
            time_since_last = wwv_detection_time - self.last_time_snap_correction
            if time_since_last < self.time_snap_min_interval_sec:
                logger.info(f"{self.channel_name}: Time_snap correction SKIPPED - too soon since last "
                           f"({time_since_last:.1f}s < {self.time_snap_min_interval_sec}s), error was {timing_error_ms:+.1f}ms")
                return False
        
        # Correction is warranted
        logger.warning(f"{self.channel_name}: Time_snap correction WILL BE APPLIED - error {timing_error_ms:+.1f}ms exceeds threshold")
        
        # Calculate new time reference from WWV tone
        # WWV tone should be at exact second 0 of minute
        wwv_minute = int(wwv_detection_time / 60) * 60  # Floor to minute boundary
        
        # Apply correction to time reference
        old_utc_start = self.utc_aligned_start
        old_rtp_start = self.rtp_start_timestamp
        
        # New reference: WWV tone time is our new anchor
        self.utc_aligned_start = wwv_minute
        self.rtp_start_timestamp = tone_rtp_timestamp
        
        # Log correction
        correction_record = (wwv_detection_time, timing_error_ms, wwv_minute)
        self.time_snap_corrections.append(correction_record)
        self.last_time_snap_correction = wwv_detection_time
        
        logger.warning(f"{self.channel_name}: ⚠️  TIME_SNAP CORRECTION APPLIED")
        logger.warning(f"{self.channel_name}:    Timing error: {timing_error_ms:+.1f} ms")
        logger.warning(f"{self.channel_name}:    Old reference: UTC {datetime.fromtimestamp(old_utc_start, timezone.utc).strftime('%H:%M:%S')}, RTP {old_rtp_start}")
        logger.warning(f"{self.channel_name}:    New reference: UTC {datetime.fromtimestamp(wwv_minute, timezone.utc).strftime('%H:%M:%S')}, RTP {tone_rtp_timestamp}")
        logger.warning(f"{self.channel_name}:    Total corrections: {len(self.time_snap_corrections)}")
        
        # Track as discontinuity
        discontinuity = TimingDiscontinuity(
            timestamp=wwv_detection_time,
            sample_index=self.samples_received,
            discontinuity_type=DiscontinuityType.TIME_SNAP_CORRECTION,
            magnitude_samples=0,  # Time correction, not sample gap
            magnitude_ms=timing_error_ms,
            rtp_sequence_before=None,
            rtp_sequence_after=None,
            rtp_timestamp_before=old_rtp_start,
            rtp_timestamp_after=tone_rtp_timestamp,
            wwv_tone_detected=True,
            explanation=f"Time_snap corrected by {timing_error_ms:+.1f}ms from WWV tone"
        )
        self.discontinuity_tracker.add_discontinuity(discontinuity)
        
        return True
    
    def _log_wwv_timing(self, detection_time: float, timing_error_ms: float):
        """
        Log WWV timing data to CSV for analysis and graphing.
        
        Args:
            detection_time: Unix timestamp of detection
            timing_error_ms: Timing error in milliseconds
        """
        import csv
        from pathlib import Path
        
        # CSV file path - use path resolver if available
        if self.path_resolver:
            csv_path = self.path_resolver.get_wwv_timing_csv()
        else:
            # Fallback for backward compatibility
            csv_path = Path(__file__).parent.parent.parent / 'logs' / 'wwv_timing.csv'
        
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Extract frequency from channel name (e.g., "WWV 10 MHz Audio" -> 10.0)
        try:
            freq_str = self.channel_name.split()[1]  # Get "10" from "WWV 10 MHz Audio"
            frequency_mhz = float(freq_str)
        except (IndexError, ValueError):
            frequency_mhz = self.frequency_hz / 1e6
        
        # Append to CSV
        try:
            with open(csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    detection_time,                    # timestamp
                    self.channel_name,                 # channel
                    frequency_mhz,                     # frequency_mhz
                    f"{timing_error_ms:.2f}",         # timing_error_ms
                    self.wwv_detections,              # detection_count
                    "N/A"                              # snr_estimate (can add later)
                ])
        except Exception as e:
            logger.error(f"{self.channel_name}: Failed to log WWV timing: {e}")
    
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
                # Start recording at minute boundary (wall clock as ROUGH estimate only)
                # TRUE time_snap will be established by first WWV/CHU detection
                rough_utc_minute = int(now / 60) * 60
                self.utc_aligned_start = rough_utc_minute
                self.rtp_start_timestamp = header.timestamp
                self.expected_rtp_timestamp = header.timestamp
                self.sync_state = 'active'
                
                utc_time = datetime.fromtimestamp(self.utc_aligned_start, timezone.utc)
                logger.info(f"{self.channel_name}: Started recording at UTC {utc_time.strftime('%Y-%m-%d %H:%M:%S')} (wall clock estimate)")
                logger.info(f"{self.channel_name}: RTP start timestamp = {self.rtp_start_timestamp}")
                logger.info(f"{self.channel_name}: Waiting for WWV/CHU tone to establish precise time_snap...")
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
        self.packets_received += 1
        self.last_packet_time = time.time()  # For freshness monitoring
        
        # Gap detection and filling (wsprdaemon-style)
        if self.last_sequence is not None and self.expected_rtp_timestamp is not None:
            expected_seq = (self.last_sequence + 1) & 0xFFFF
            if header.sequence != expected_seq:
                gap_packets = (header.sequence - expected_seq) & 0xFFFF
                self.packets_dropped += gap_packets
                
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
        
        # Parse samples from RTP payload
        # Audio channels: Real int16 PCM samples (2 bytes each)
        # IQ channels: Complex I/Q pairs (4 bytes each: Q and I int16)
        try:
            if self.is_wwv_audio_channel:
                # PCM Audio: Real int16 samples
                if len(payload) % 2 != 0:
                    logger.warning(f"{self.channel_name}: PCM payload size not multiple of 2 (got {len(payload)} bytes)")
                    return
                
                # Unpack as real int16, normalize to float
                samples_int16 = np.frombuffer(payload, dtype='>i2')  # Big-endian
                # Normalize and convert to complex (imaginary part = 0) for resampler compatibility
                iq_samples = (samples_int16.astype(np.float32) / 32768.0).astype(np.complex64)
            else:
                # IQ channels: Complex Q+jI pairs
                if len(payload) % 4 != 0:
                    logger.warning(f"{self.channel_name}: IQ payload size not multiple of 4 (got {len(payload)} bytes)")
                    return
                
                samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)  # Big-endian
                samples = samples_int16.astype(np.float32) / 32768.0
                # KA9Q sends Q,I pairs - use Q + jI for carrier at DC
                iq_samples = samples[:, 1] + 1j * samples[:, 0]  # Q + jI
        except Exception as e:
            logger.error(f"{self.channel_name}: Failed to parse RTP payload: {e}")
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
                # Resample to 3 kHz for tone detection
                tone_resampled = self.tone_resampler.resample(all_samples)
                
                # DIAGNOSTIC: Confirm this code path is executing
                if not hasattr(self, '_tone_path_confirmed'):
                    logger.warning(f"{self.channel_name}: 🔍 TONE DETECTION PATH IS ACTIVE")
                    self._tone_path_confirmed = True
                
                # Track when accumulator starts
                if self.tone_accumulator_start_time is None:
                    self.tone_accumulator_start_time = unix_time
                
                self.tone_accumulator.append(tone_resampled)
                
                # Track total accumulated samples
                accumulated_tone_samples = sum(len(chunk) for chunk in self.tone_accumulator)
                seconds_in_minute = unix_time % 60
                
                # Periodic logging of accumulator state
                if len(self.tone_accumulator) % 50 == 0:
                    logger.info(f"{self.channel_name}: Tone accumulator: {accumulated_tone_samples}/{self.tone_samples_per_check} samples, "
                               f"chunks={len(self.tone_accumulator)}, :mm.{int(seconds_in_minute):02d}")
                
                # Check if we're in the detection window (around :00 of minute)
                # Window: from :59 to :02 (to ensure we capture the full 0.8s WWV tone)
                in_detection_window = (seconds_in_minute >= 59) or (seconds_in_minute <= 2)
                
                # Clear accumulator if we're past the detection window to prevent unlimited growth
                if seconds_in_minute > 5 and len(self.tone_accumulator) > 0:
                    self.tone_accumulator = []
                    self.tone_accumulator_start_time = None
                
                # Check if we have enough samples for tone detection
                if accumulated_tone_samples >= self.tone_samples_per_check and in_detection_window:
                    # Concatenate and detect
                    tone_buffer = np.concatenate(self.tone_accumulator) if len(self.tone_accumulator) > 1 else self.tone_accumulator[0]
                    # Use current time reference, not stale cached time (corrects for time_snap during accumulation)
                    buffer_start_time = unix_time - (len(tone_buffer) / 3000.0)
                    
                    logger.info(f"{self.channel_name}: Attempting detection - buffer_len={len(tone_buffer)}, "
                               f"buffer_start={buffer_start_time:.1f}, unix_time={unix_time:.1f}, :mm.{int(seconds_in_minute):02d}")
                    
                    self.tone_accumulator = []
                    self.tone_accumulator_start_time = None
                    
                    # Detect all station tones (WWV, WWVH, CHU)
                    detections = self.tone_detector.detect_tones(
                        tone_buffer,
                        buffer_start_time
                    )
                    
                    if detections:
                        logger.info(f"{self.channel_name}: ✅ {len(detections)} tone(s) detected!")
                    else:
                        logger.info(f"{self.channel_name}: ❌ No tones detected this minute (weak/no signal)")
                    
                    if detections:
                            # Separate detections by purpose
                            wwv_only = [d for d in detections if d['station'] == 'WWV']
                            wwvh_only = [d for d in detections if d['station'] == 'WWVH']
                            chu_only = [d for d in detections if d['station'] == 'CHU']
                            
                            # Use WWV or CHU for time_snap (primary timing reference)
                            primary_detections = wwv_only if wwv_only else chu_only
                            
                            if primary_detections:
                                primary = primary_detections[0]  # Strongest signal
                                timing_error_ms = primary['timing_error_ms']
                                onset_sample_idx = primary['onset_sample_idx']
                                
                                # Update detection counts
                                if primary['station'] == 'WWV':
                                    self.wwv_detections += 1
                                else:
                                    self.chu_detections += 1
                                
                                self.wwv_timing_errors.append(timing_error_ms)
                                
                                # Keep only last 60 detections for statistics
                                if len(self.wwv_timing_errors) > 60:
                                    self.wwv_timing_errors.pop(0)
                                
                                logger.info(f"{self.channel_name}: ⏱️ {primary['station']} tone detected! "
                                           f"Timing error: {timing_error_ms:+.1f} ms, "
                                           f"SNR: {primary['snr_db']:.1f} dB "
                                           f"(ref: UTC {datetime.fromtimestamp(self.utc_aligned_start, timezone.utc).strftime('%H:%M:%S')}, "
                                           f"RTP {self.rtp_start_timestamp})")
                                
                                # Calculate RTP timestamp at tone onset
                                tone_onset_time = buffer_start_time + (onset_sample_idx / 3000.0)
                                tone_onset_rtp = self.rtp_start_timestamp + int((tone_onset_time - self.utc_aligned_start) * self.rtp_sample_rate)
                                
                                # Track RTP vs WWV interval (the critical drift metric)
                                if self.last_wwv_rtp_timestamp is not None:
                                    # Calculate actual RTP interval since last detection
                                    rtp_interval = tone_onset_rtp - self.last_wwv_rtp_timestamp
                                    time_interval_sec = tone_onset_time - self.last_wwv_detection_time
                                    
                                    # Only measure drift for consecutive-minute detections (59-61 seconds)
                                    # This gives true minute-to-minute accuracy, not cumulative multi-minute drift
                                    if 59 <= time_interval_sec <= 61:
                                        # Expected RTP interval for one minute (16 kHz sample rate)
                                        expected_rtp_interval = int(time_interval_sec * self.rtp_sample_rate)
                                        
                                        # Calculate error in parts per million (PPM)
                                        rtp_error = rtp_interval - expected_rtp_interval
                                        ppm_error = (rtp_error / expected_rtp_interval) * 1e6
                                        
                                        self.rtp_wwv_intervals.append((rtp_interval, expected_rtp_interval, ppm_error))
                                        
                                        # Keep only last 60 intervals
                                        if len(self.rtp_wwv_intervals) > 60:
                                            self.rtp_wwv_intervals.pop(0)
                                        
                                        logger.info(f"{self.channel_name}: 📊 RTP drift (1-min): {rtp_interval} samples "
                                                   f"(expected {expected_rtp_interval}), error: {rtp_error} samples = {ppm_error:+.2f} PPM")
                                    else:
                                        logger.debug(f"{self.channel_name}: Skipping drift measurement - interval {time_interval_sec:.1f}s (need 59-61s for accuracy)")
                                
                                # Update last detection tracking
                                self.last_wwv_rtp_timestamp = tone_onset_rtp
                                self.last_wwv_detection_time = tone_onset_time
                                
                                # Apply KA9Q time_snap correction if warranted
                                corrected = self._apply_time_snap_correction(
                                    wwv_detection_time=tone_onset_time,
                                    timing_error_ms=timing_error_ms,
                                    tone_rtp_timestamp=tone_onset_rtp
                                )
                                
                                if corrected:
                                    logger.info(f"{self.channel_name}: 🔧 Time reference updated from {primary['station']} tone")
                                
                                # Log to CSV for analysis and graphing
                                self._log_wwv_timing(unix_time, timing_error_ms)
                            
                            # Handle WWVH detection (propagation analysis)
                            if wwvh_only:
                                wwvh = wwvh_only[0]
                                self.wwvh_detections += 1
                                
                                logger.info(f"{self.channel_name}: 📡 WWVH propagation: "
                                           f"timing={wwvh['timing_error_ms']:+.1f}ms, "
                                           f"SNR={wwvh['snr_db']:.1f}dB")
                                
                                # Calculate differential delay (WWV vs WWVH)
                                if wwv_only:
                                    differential_ms = wwv_only[0]['timing_error_ms'] - wwvh['timing_error_ms']
                                    self.differential_delays.append(differential_ms)
                                    
                                    # Keep only last 60 measurements
                                    if len(self.differential_delays) > 60:
                                        self.differential_delays.pop(0)
                                    
                                    logger.info(f"{self.channel_name}: 📊 WWV-WWVH differential: {differential_ms:+.1f}ms "
                                               f"(WWV: {wwv_only[0]['timing_error_ms']:+.1f}ms, "
                                               f"WWVH: {wwvh['timing_error_ms']:+.1f}ms)")
                            
                            # Log all detections for this minute
                            logger.debug(f"{self.channel_name}: Minute summary - "
                                        f"WWV={len(wwv_only)}, WWVH={len(wwvh_only)}, CHU={len(chu_only)}")
                    else:
                        # Outside detection window - discard accumulated samples
                        self.tone_accumulator = []
                        self.tone_accumulator_start_time = None
            
            # Add to daily buffer
            completed_day = self.daily_buffer.add_samples(unix_time, resampled)
            
            # Track timing quality (per-minute stats and drift monitoring)
            self._track_timing_quality(unix_time, len(resampled))
            
            # Write completed day to Digital RF (at midnight rollover)
            if completed_day and HAS_DIGITAL_RF:
                day_date, day_data = completed_day
                self._write_digital_rf(day_date, day_data)
            
            # Also write hourly (to avoid losing data if daemon crashes)
            # DEBUG: Check write conditions
            should_write = self.daily_buffer.should_write_hourly(unix_time)
            current_data = self.daily_buffer.get_current_data()
            
            # DEBUG logging to diagnose why writes aren't happening
            dt = datetime.fromtimestamp(unix_time, tz=timezone.utc)
            if dt.minute == 1 and dt.second < 30:  # Only log during write window
                logger.info(f"{self.channel_name}: DEBUG - HAS_DIGITAL_RF={HAS_DIGITAL_RF}, should_write={should_write}, has_data={current_data is not None}")
                if current_data:
                    day_date, day_data = current_data
                    logger.info(f"{self.channel_name}: DEBUG - buffer has {len(day_data)} samples, {np.count_nonzero(~np.isnan(day_data))} non-NaN")
            
            if HAS_DIGITAL_RF and should_write:
                if current_data:
                    day_date, day_data = current_data
                    logger.info(f"{self.channel_name}: Hourly write triggered")
                    self._write_digital_rf(day_date, day_data)
                else:
                    logger.warning(f"{self.channel_name}: Hourly write triggered but no data in buffer!")
                
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
            
            # Create date-specific Digital RF writer directory
            # Structure: {base}/YYYYMMDD/CALLSIGN_GRID/INSTRUMENT/{channel_name}/
            date_str = day_date.strftime('%Y%m%d')
            callsign = self.station_config.get('callsign', 'UNKNOWN')
            grid = self.station_config.get('grid_square', 'UNKNOWN')
            instrument = self.station_config.get('instrument_id', 'UNKNOWN')
            
            # Build path with date
            # self.channel_dir is already the correct base (e.g., /tmp/grape-test/data/WWV_2.5_MHz)
            # For Digital RF, we need: {data_root}/YYYYMMDD/CALLSIGN_GRID/INSTRUMENT/CHANNEL/
            base_dir = self.channel_dir.parent  # Data root (e.g., /tmp/grape-test/data)
            
            # Sanitize channel name (replace spaces with underscores for filesystem)
            safe_channel_name = self.channel_name.replace(' ', '_')
            
            drf_dir = base_dir / date_str / f"{callsign}_{grid}" / instrument / safe_channel_name
            drf_dir.mkdir(parents=True, exist_ok=True)
            
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
                subdir_cadence_secs=86400,      # 24 hour subdirectories (PSWS requirement)
                file_cadence_millisecs=3600000, # 1 hour files (PSWS requirement)
                start_global_index=start_global_index,  # CRITICAL: Midnight UTC
                sample_rate_numerator=10,
                sample_rate_denominator=1,
                uuid_str=dataset_uuid,
                compression_level=9,            # High compression for upload bandwidth
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
            
            # Write metadata using DigitalMetadataWriter (no context manager support)
            metadata_writer = drf.DigitalMetadataWriter(
                str(metadata_dir),
                subdir_cadence_secs=86400,  # Match data: 24 hour subdirectories
                file_cadence_secs=3600,     # 1 hour metadata files
                sample_rate_numerator=10,
                sample_rate_denominator=1,
                file_name='metadata'
            )
            metadata_writer.write(start_global_index, metadata)
            # Note: DigitalMetadataWriter auto-flushes, no close() method needed
            
            logger.info(f"{self.channel_name}: ✅ Digital RF write complete for {day_date}")
                       
        except Exception as e:
            logger.error(f"{self.channel_name}: Failed to write Digital RF: {e}", exc_info=True)


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
                path_resolver=self.path_resolver
            )
            
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
