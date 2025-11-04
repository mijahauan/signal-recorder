#!/usr/bin/env python3
"""
GRAPE Channel Recorder V2

New architecture:
- Store full 8 kHz IQ in 1-minute compressed files
- Track comprehensive quality metrics
- WWV timing analysis in real-time
- Decimation done offline (8 kHz → 10 Hz)
"""

import time
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, NamedTuple
from collections import deque
from scipy import signal as scipy_signal

from .minute_file_writer import MinuteFileWriter
from .quality_metrics import (
    QualityMetricsTracker, TimingDiscontinuity, DiscontinuityType
)
from .live_quality_status import get_live_status

logger = logging.getLogger(__name__)

# Resequencing queue entry
class ReseqEntry(NamedTuple):
    """Entry in the packet resequencing queue"""
    sequence: int          # RTP sequence number
    timestamp: int         # RTP timestamp
    samples: np.ndarray    # IQ samples
    arrival_time: float    # Unix time when packet arrived
    inuse: bool            # True if slot contains valid data


class GRAPEChannelRecorderV2:
    """
    Per-channel recorder with quality tracking and minute-file archive
    
    Key differences from V1:
    - No real-time decimation (stores full 8 kHz)
    - Writes 1-minute compressed files continuously
    - Comprehensive quality metrics
    - Decimation done offline in batch
    """
    
    def __init__(self, ssrc: int, channel_name: str, frequency_hz: float,
                 archive_dir: Path, analytics_dir: Path, station_config: dict,
                 is_wwv_channel: bool = False, path_resolver=None):
        """
        Initialize channel recorder
        
        Args:
            ssrc: RTP SSRC identifier
            channel_name: Channel name (e.g., "WWV 2.5 MHz")
            frequency_hz: Center frequency in Hz
            archive_dir: Directory for minute file archives
            analytics_dir: Directory for quality metrics
            station_config: Station metadata
            is_wwv_channel: True if WWV (enables tone detection)
            path_resolver: Optional PathResolver
        """
        self.ssrc = ssrc
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.station_config = station_config
        self.is_wwv_channel = is_wwv_channel
        self.path_resolver = path_resolver
        
        # Sample rate: From radiod config (typically 16 kHz IQ)
        # NOTE: Config sample_rate is the actual IQ sample rate, not real samples
        self.sample_rate = 16000  # TODO: Get from channel config
        self.samples_per_minute = 16000 * 60  # 960,000
        
        # File writer for 1-minute archives
        self.file_writer = MinuteFileWriter(
            output_dir=archive_dir,
            channel_name=channel_name,
            frequency_hz=frequency_hz,
            sample_rate=self.sample_rate,
            station_config=station_config
        )
        
        # Quality metrics tracker
        quality_output = analytics_dir / "quality" / datetime.now(timezone.utc).strftime("%Y%m%d")
        self.quality_tracker = QualityMetricsTracker(
            channel_name=channel_name,
            frequency_hz=frequency_hz,
            output_dir=quality_output
        )
        
        # RTP state
        self.last_sequence = None
        self.last_rtp_timestamp = None
        self.expected_rtp_timestamp = None
        self.rtp_sample_rate = 16000  # RTP timestamp rate (real samples)
        
        # Resequencing queue (KA9Q-style)
        # Circular buffer for handling out-of-order and missing packets
        self.RESEQ_SIZE = 64  # Same as KA9Q pcmrecord.c
        self.reseq_queue = [ReseqEntry(0, 0, None, 0.0, False) for _ in range(self.RESEQ_SIZE)]
        self.expected_sequence = None  # Next sequence number we expect to process
        self.rtp_state_init = False    # True after first packet received
        
        # Current minute tracking
        self.current_minute_start = None
        self.current_minute_samples = 0
        self.current_minute_packets_rx = 0
        self.current_minute_packets_drop = 0
        
        # Per-packet timing for jitter calculation
        self.packet_arrival_times = deque(maxlen=100)
        
        # WWV/CHU tone detection (if enabled)
        # Both WWV and CHU broadcast 1000 Hz tones at minute boundaries
        # WWV: 0.8s duration, CHU: 0.5s duration
        self.tone_detector = None
        if is_wwv_channel:
            from .grape_rtp_recorder import WWVToneDetector, Resampler
            # Downsample to 3 kHz for tone detection (saves CPU)
            # Buffered WWV detection approach
            # Instead of real-time streaming detection, buffer samples and post-process
            self.wwv_minute_buffer = {}  # minute_timestamp -> list of (rtp_ts, iq_samples)
            self.wwv_current_minute = None
            self.wwv_buffer_start_second = 55  # Start buffering at :55 (10 second window)
            self.wwv_buffer_end_second = 5     # Process at :05
            tone_type = "WWV/CHU" if "CHU" in channel_name else "WWV"
            logger.info(f"{channel_name}: {tone_type} BUFFERED tone detection ENABLED (:55-:05 window, 10s)")
        
        # Statistics
        self.total_samples = 0
        self.total_packets = 0
        self.packets_dropped = 0
        self.start_time = time.time()
        
        # WWV tracking
        self.last_wwv_detection = None
        self.wwv_detections_today = 0
        self.current_minute_wwv_drift_ms = None  # Drift for current minute
        self.wwv_results_by_minute = {}  # minute_timestamp -> wwv_result (persist until finalized)
        
        # Predictive detection (after first successful detection)
        self.wwv_reference_rtp = None  # RTP timestamp of first detected tone
        self.wwv_reference_minute = None  # Minute timestamp of first detection
        
        # Resequencing statistics (for quality tracking)
        self.current_minute_resequenced = 0
        self.current_minute_max_reseq_depth = 0
        self.current_minute_max_queue_used = 0
        
        # Time snap reference (Phase 2: WWV-based timing)
        # Anchors RTP timestamp to UTC time using WWV tone rising edge
        self.time_snap_rtp = None       # RTP timestamp at snap point
        self.time_snap_utc = None       # UTC time (seconds) at snap point
        self.time_snap_established = False
        self.time_snap_source = None    # "wwv_first" or "wwv_verified"
        
        # Live status updates
        self.live_status_file = analytics_dir / "live_quality_status.json"
        self.live_status_update_counter = 0
        
        logger.info(f"{channel_name}: Recorder V2 initialized (16 kHz archive, quality tracking)")
    
    def process_rtp_packet(self, header, payload: bytes):
        """
        Process incoming RTP packet with resequencing (KA9Q-style)
        
        Args:
            header: RTP header (from RTPPacketInfo)
            payload: RTP payload bytes
        """
        arrival_time = time.time()
        self.packet_arrival_times.append(arrival_time)
        self.total_packets += 1
        
        # Parse samples from payload
        # IQ channels: Complex I/Q pairs (4 bytes each: Q,I as int16 big-endian)
        if len(payload) % 4 != 0:
            logger.warning(f"{self.channel_name}: Invalid payload size {len(payload)}")
            return
        
        samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
        samples_float = samples_int16.astype(np.float32) / 32768.0
        iq_samples = samples_float[:, 1] + 1j * samples_float[:, 0]  # Q + jI
        
        # Initialize RTP state on first packet
        if not self.rtp_state_init:
            self.expected_sequence = header.sequence
            self.expected_rtp_timestamp = header.timestamp
            self.rtp_state_init = True
            logger.info(f"{self.channel_name}: RTP init - seq={header.sequence}, ts={header.timestamp}")
        
        # Enqueue packet in resequencing buffer
        self._enqueue_packet(header, iq_samples, arrival_time)
        
        # Process packets from queue in sequence order
        self._process_reseq_queue()
        
        # Update live status periodically (every 100 packets)
        self.live_status_update_counter += 1
        if self.live_status_update_counter >= 100:
            self._update_live_status()
            self.live_status_update_counter = 0
    
    def _enqueue_packet(self, header, iq_samples: np.ndarray, arrival_time: float):
        """
        Place packet in resequencing queue (KA9Q pcmrecord.c:652-679)
        
        Args:
            header: RTP header
            iq_samples: Parsed IQ samples
            arrival_time: Unix timestamp of packet arrival
        """
        seq_diff = (header.sequence - self.expected_sequence) & 0xFFFF
        
        # Handle wraparound for negative differences
        if seq_diff >= 0x8000:
            seq_diff -= 0x10000
        
        # Track resequencing statistics
        if seq_diff > 0:
            self.current_minute_resequenced += 1
            self.current_minute_max_reseq_depth = max(self.current_minute_max_reseq_depth, seq_diff)
        
        if seq_diff < 0:
            # Old/duplicate packet - drop it
            logger.debug(f"{self.channel_name}: Drop old/dup seq {header.sequence} "
                        f"(expected {self.expected_sequence})")
            return
        
        if seq_diff >= self.RESEQ_SIZE:
            # Packet too far ahead - flush queue and resync
            logger.warning(f"{self.channel_name}: Seq jump {seq_diff} packets ahead, "
                          f"flushing queue (seq {header.sequence})")
            self._flush_reseq_queue()
            self.expected_sequence = header.sequence
            self.expected_rtp_timestamp = header.timestamp
        
        # Insert into circular buffer at correct position
        qi = header.sequence % self.RESEQ_SIZE
        self.reseq_queue[qi] = ReseqEntry(
            sequence=header.sequence,
            timestamp=header.timestamp,
            samples=iq_samples.copy(),  # Copy to avoid reference issues
            arrival_time=arrival_time,
            inuse=True
        )
        
        # Track queue utilization
        queue_used = sum(1 for e in self.reseq_queue if e.inuse)
        self.current_minute_max_queue_used = max(self.current_minute_max_queue_used, queue_used)
        
        logger.debug(f"{self.channel_name}: Enqueued seq {header.sequence}, ts {header.timestamp}")
    
    def _process_reseq_queue(self):
        """
        Process packets from resequencing queue in order (KA9Q pcmrecord.c:843-899)
        Handles gaps by filling with zeros based on RTP timestamp jumps
        """
        processed_count = 0
        
        for _ in range(self.RESEQ_SIZE):
            qi = self.expected_sequence % self.RESEQ_SIZE
            entry = self.reseq_queue[qi]
            
            if not entry.inuse:
                # No packet at expected sequence - stop processing
                break
            
            # Check for RTP timestamp jump (indicates missing packets)
            ts_jump = (entry.timestamp - self.expected_rtp_timestamp) & 0xFFFFFFFF
            
            # Handle wraparound
            if ts_jump > 0x7FFFFFFF:
                ts_jump = ts_jump - 0x100000000
            
            if ts_jump > 0:
                # Gap detected - fill with zeros
                gap_samples = ts_jump
                gap_packets = gap_samples // 320  # Approximate packet count
                gap_ms = (gap_samples / self.sample_rate) * 1000
                
                logger.warning(f"{self.channel_name}: RTP timestamp gap: {gap_samples} samples "
                              f"({gap_packets} packets, {gap_ms:.1f}ms)")
                
                # Track gap statistics
                self.packets_dropped += gap_packets
                self.current_minute_packets_drop += gap_packets
                
                # Fill gap with zeros
                zeros = np.zeros(gap_samples, dtype=np.complex64)
                unix_time = self._calculate_sample_time(self.expected_rtp_timestamp)
                
                # Record discontinuity
                discontinuity = TimingDiscontinuity(
                    timestamp=unix_time,
                    sample_index=self.total_samples,
                    discontinuity_type=DiscontinuityType.GAP,
                    magnitude_samples=int(gap_samples),
                    magnitude_ms=gap_ms,
                    rtp_sequence_before=self.expected_sequence - 1,
                    rtp_sequence_after=entry.sequence,
                    rtp_timestamp_before=self.expected_rtp_timestamp,
                    rtp_timestamp_after=entry.timestamp,
                    wwv_tone_detected=False,
                    explanation=f"RTP timestamp jump: {gap_samples} samples filled with zeros"
                )
                self.quality_tracker.add_discontinuity(discontinuity)
                
                # Add zeros to file writer and WWV detector
                self.file_writer.add_samples(unix_time, zeros)
                if self.is_wwv_channel:
                    # Buffer gap zeros for WWV detection
                    self._process_wwv_buffered(unix_time, zeros, self.expected_rtp_timestamp)
                
                # Update totals
                self.total_samples += gap_samples
                self.current_minute_samples += gap_samples
                self.expected_rtp_timestamp = entry.timestamp
            
            # Process actual packet
            unix_time = self._calculate_sample_time(entry.timestamp)
            self._update_minute_tracking(unix_time, len(entry.samples))
            
            # WWV tone detection (buffered approach)
            wwv_result = None
            if self.is_wwv_channel:
                try:
                    wwv_result = self._process_wwv_buffered(unix_time, entry.samples, entry.timestamp)
                except Exception as e:
                    logger.error(f"{self.channel_name}: WWV detection error: {e}", exc_info=True)
            
            # Add to file writer (triggers write when minute complete)
            completed = self.file_writer.add_samples(unix_time, entry.samples)
            if completed:
                minute_time, file_path = completed
                # Get WWV result for the minute being finalized (not current packet's result!)
                minute_key = int(minute_time.timestamp())
                finalize_wwv_result = self.wwv_results_by_minute.pop(minute_key, None)
                self._finalize_minute(minute_time, file_path, finalize_wwv_result)
            
            # Update totals and state
            self.total_samples += len(entry.samples)
            self.last_sequence = entry.sequence
            self.last_rtp_timestamp = entry.timestamp
            
            # Clear queue entry and advance
            self.reseq_queue[qi] = ReseqEntry(0, 0, None, 0.0, False)
            self.expected_sequence = (self.expected_sequence + 1) & 0xFFFF
            self.expected_rtp_timestamp = (entry.timestamp + len(entry.samples)) & 0xFFFFFFFF
            
            processed_count += 1
        
        if processed_count > 0:
            logger.debug(f"{self.channel_name}: Processed {processed_count} packets from queue")
    
    def _flush_reseq_queue(self):
        """Flush all packets from resequencing queue (on major disruption)"""
        logger.info(f"{self.channel_name}: Flushing resequencing queue")
        for i in range(self.RESEQ_SIZE):
            self.reseq_queue[i] = ReseqEntry(0, 0, None, 0.0, False)
    
    def _update_live_status(self):
        """Update live quality status for web UI"""
        try:
            live_status = get_live_status(self.live_status_file)
            
            # Calculate minute progress (0-100%)
            minute_progress = (self.current_minute_samples / self.samples_per_minute * 100) if self.samples_per_minute > 0 else 0
            minute_progress = min(minute_progress, 100.0)  # Cap at 100%
            
            # Calculate RTP timing deviation (placeholder - needs proper implementation)
            rtp_deviation_ms = 0.0  # TODO: Calculate RTP vs system time
            
            # WWV info - always include if this is a WWV channel
            wwv_info = None
            if self.is_wwv_channel:
                wwv_info = {
                    'enabled': True,
                    'last_detection': self.last_wwv_detection,
                    'last_error_ms': None,
                    'detections_today': self.wwv_detections_today
                }
                # Get actual timing if we have detections
                if self.quality_tracker.minute_metrics:
                    last_minute = self.quality_tracker.minute_metrics[-1]
                    if last_minute.wwv_tone_detected and last_minute.wwv_timing_error_ms is not None:
                        wwv_info['last_error_ms'] = last_minute.wwv_timing_error_ms
            
            metrics = {
                'frequency_hz': self.frequency_hz,
                'total_packets': self.total_packets,
                'packets_dropped': self.packets_dropped,
                'total_samples': self.total_samples,
                'minutes_written': self.file_writer.minutes_written,
                'current_minute_packets': self.current_minute_packets_rx,
                'current_minute_samples': self.current_minute_samples,
                'expected_samples_per_minute': self.samples_per_minute,
                'minute_progress_percent': minute_progress,
                'rtp_timing_deviation_ms': rtp_deviation_ms,
                'last_rtp_sequence': self.last_sequence,
                'last_rtp_timestamp': self.last_rtp_timestamp,
                'wwv': wwv_info
            }
            
            # DEBUG: Log first time we update with RTP data
            if self.live_status_update_counter == 0 and self.last_sequence is not None:
                logger.info(f"{self.channel_name}: First live status update - RTP seq={self.last_sequence}, ts={self.last_rtp_timestamp}")
            
            live_status.update_channel(self.channel_name, metrics)
        except Exception as e:
            logger.debug(f"Failed to update live status: {e}")
    
    def _calculate_sample_time(self, rtp_timestamp: int) -> float:
        """
        Calculate Unix time for RTP timestamp using time_snap reference
        
        If time_snap is established (from WWV), converts RTP timestamp to UTC.
        Otherwise falls back to system time.
        
        Formula: utc_time = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate
        """
        if self.time_snap_established:
            # Calculate sample offset from snap point
            delta_samples = (rtp_timestamp - self.time_snap_rtp) & 0xFFFFFFFF
            
            # Handle wraparound (assume < 74 hours of continuous operation)
            if delta_samples > 0x7FFFFFFF:
                delta_samples = delta_samples - 0x100000000
            
            # Convert to seconds and add to snap time
            delta_seconds = delta_samples / self.sample_rate
            return self.time_snap_utc + delta_seconds
        else:
            # No time_snap yet - use system time as approximation
            return time.time()
    
    def _update_minute_tracking(self, unix_time: float, samples_count: int):
        """Track statistics for current minute"""
        dt = datetime.fromtimestamp(unix_time, tz=timezone.utc)
        minute_boundary = dt.replace(second=0, microsecond=0)
        
        if self.current_minute_start != minute_boundary:
            # New minute
            if self.current_minute_start is not None:
                # Start tracking new minute in quality tracker
                self.quality_tracker.start_minute(
                    minute_boundary.timestamp(),
                    self.samples_per_minute
                )
            
            self.current_minute_start = minute_boundary
            self.current_minute_samples = 0
            self.current_minute_packets_rx = 0
            self.current_minute_packets_drop = 0
        
        self.current_minute_samples += samples_count
        self.current_minute_packets_rx += 1
        
        # Update quality tracker
        self.quality_tracker.update_minute_samples(self.current_minute_samples)
    
    def _process_wwv_buffered(self, unix_time: float, iq_samples: np.ndarray, rtp_timestamp: int) -> Optional[Dict]:
        """
        Buffered WWV detection: Collect samples from :58 to :03, then post-process
        
        This uses the same algorithm as our diagnostic script which works perfectly.
        Instead of real-time streaming detection, we buffer and batch-process.
        """
        from scipy import signal as scipy_signal
        
        dt = datetime.fromtimestamp(unix_time, tz=timezone.utc)
        seconds_in_minute = dt.second + (dt.microsecond / 1e6)
        
        # Determine which minute's buffer these samples belong to
        # Samples from :55-:59 belong to the NEXT minute
        # Samples from :00-:05 belong to the CURRENT minute
        if seconds_in_minute >= self.wwv_buffer_start_second:
            # :55-:59 - buffer for NEXT minute
            minute_boundary = (dt + timedelta(minutes=1)).replace(second=0, microsecond=0)
            should_buffer = True
        elif seconds_in_minute <= self.wwv_buffer_end_second:
            # :00-:05 - buffer for CURRENT minute
            minute_boundary = dt.replace(second=0, microsecond=0)
            should_buffer = True
        else:
            should_buffer = False
        
        if should_buffer:
            # Initialize buffer for this minute if needed
            minute_key = int(minute_boundary.timestamp())
            
            if minute_key not in self.wwv_minute_buffer:
                self.wwv_minute_buffer[minute_key] = []
                logger.debug(f"{self.channel_name}: Started WWV buffer for minute {minute_boundary.strftime('%H:%M')}")
            
            # Always update current minute pointer (even if buffer exists)
            self.wwv_current_minute = minute_key
            
            # Add samples to buffer
            self.wwv_minute_buffer[minute_key].append((rtp_timestamp, iq_samples.copy()))
        
        # At :05 seconds, process the complete buffer (only once!)
        if 5.0 <= seconds_in_minute <= 5.5:
            if self.wwv_current_minute is None:
                # Already processed or buffer not created
                return None
            minute_key = self.wwv_current_minute
            
            if minute_key in self.wwv_minute_buffer and len(self.wwv_minute_buffer[minute_key]) > 0:
                # Process this minute's buffer
                result = self._detect_wwv_in_buffer(minute_key)
                
                # Save result for this minute (persist until finalized)
                if result and result.get('detected'):
                    self.wwv_results_by_minute[minute_key] = result
                
                # Clean up processed buffer and old buffers
                # Delete the buffer we just processed
                del self.wwv_minute_buffer[minute_key]
                
                # Also delete any older buffers
                old_keys = [k for k in self.wwv_minute_buffer.keys() if k < minute_key]
                for old_key in old_keys:
                    del self.wwv_minute_buffer[old_key]
                
                # Reset current minute pointer (will be set again at next :55)
                self.wwv_current_minute = None
                
                return result
        
        return None
    
    def _detect_wwv_in_buffer(self, minute_key: int) -> Optional[Dict]:
        """
        Detect WWV tone in buffered samples using post-processing approach
        (same as diagnostic script - this is what works!)
        """
        from scipy import signal as scipy_signal
        
        buffer_entries = self.wwv_minute_buffer[minute_key]
        if len(buffer_entries) == 0:
            return None
        
        # Concatenate all IQ samples
        all_iq = np.concatenate([samples for _, samples in buffer_entries])
        first_rtp_ts = buffer_entries[0][0]
        
        logger.info(f"{self.channel_name}: Processing WWV buffer: {len(all_iq):,} samples ({len(all_iq)/16000:.1f}s)")
        
        # Use 8-second window centered on minute boundary for better discrimination
        # Buffer is :55-:05 (10s), minute boundary at :00 (5s into buffer)
        # Analyze :57-:03 = 6 seconds around the tone
        # That's 2-8 seconds into the buffer
        buffer_duration = len(all_iq) / 16000
        
        if buffer_duration < 6.0:
            logger.warning(f"{self.channel_name}: Buffer too short ({buffer_duration:.1f}s < 6s)")
            return None
        
        # Use 6-second window centered on minute boundary
        # Buffer spans :55-:05 (10s), minute boundary at :00 (5s into buffer)
        # Extract :57-:03 (6 seconds) for detection
        # This is 2-8 seconds into the buffer
        start_sample = min(int(2.0 * 16000), len(all_iq) - 96000)  # Start at 2s (:57)
        end_sample = min(start_sample + 96000, len(all_iq))         # 6 seconds
        
        # Expected tone at 3s into 6s window (the :00 boundary)
        expected_tone_sample = start_sample + int(3.0 * 16000)
        
        detection_window = all_iq[start_sample:end_sample]
        
        logger.debug(f"{self.channel_name}: Detection window: {len(detection_window)/16000:.1f}s "
                    f"({start_sample/16000:.1f}s to {end_sample/16000:.1f}s into buffer)")
        
        # === Same algorithm as diagnostic script ===
        
        # 1. AM demodulation
        magnitude = np.abs(detection_window)
        mag_dc = magnitude - np.mean(magnitude)
        
        # 2. Resample to 3 kHz
        resampled = scipy_signal.resample_poly(mag_dc, 3, 16)
        
        # 3. Bandpass filter 950-1050 Hz
        sos = scipy_signal.butter(5, [950, 1050], btype='band', fs=3000, output='sos')
        filtered = scipy_signal.sosfiltfilt(sos, resampled)
        
        # 4. Hilbert envelope
        envelope = np.abs(scipy_signal.hilbert(filtered))
        
        # 5. Normalize
        max_env = np.max(envelope)
        if max_env == 0:
            logger.debug(f"{self.channel_name}: Zero envelope - no signal")
            return None
        
        normalized = envelope / max_env
        
        # 6. Detect tone above threshold
        threshold = 0.5
        above_threshold = normalized > threshold
        above_count = np.sum(above_threshold)
        above_percent = (above_count / len(normalized)) * 100
        
        logger.info(f"{self.channel_name}: WWV analysis - max_env={max_env:.6f}, "
                   f"above_thresh={above_count}/{len(normalized)} ({above_percent:.1f}%)")
        
        # 7. Apply binary threshold and find edges
        binary_envelope = (normalized > threshold).astype(int)
        rising_edges = np.where(np.diff(binary_envelope) == 1)[0]
        falling_edges = np.where(np.diff(binary_envelope) == -1)[0]
        
        # 8. Measure pulse durations and find best candidate
        # Expected position in resampled (3kHz) coordinates
        expected_in_window_16k = expected_tone_sample - start_sample
        expected_tone_position_3k = int(expected_in_window_16k * (3 / 16))
        
        valid_tones = []
        all_durations = []
        
        for rise_idx in rising_edges:
            # Find next falling edge
            fall_candidates = falling_edges[falling_edges > rise_idx]
            if len(fall_candidates) == 0:
                continue
            
            fall_idx = fall_candidates[0]
            duration_samples = fall_idx - rise_idx
            duration_sec = duration_samples / 3000
            all_durations.append(duration_sec)
            
            # WWV/CHU tone validation
            # CHU: 0.5s nominal, but filtering/edge detection can make it measure 0.29-0.50s
            # WWV: 0.8s nominal
            # Allow 0.25-1.2s to catch weak/filtered CHU tones
            if 0.25 <= duration_sec <= 1.2:
                distance_from_expected = abs(rise_idx - expected_tone_position_3k)
                valid_tones.append({
                    'onset': rise_idx,
                    'offset': fall_idx,
                    'duration': duration_sec,
                    'distance': distance_from_expected
                })
        
        if len(valid_tones) == 0:
            # Log all found durations for debugging
            if len(all_durations) > 0:
                durations_str = ", ".join([f"{d:.3f}s" for d in all_durations[:5]])
                logger.debug(f"{self.channel_name}: No valid tone (found: {durations_str})")
            else:
                logger.debug(f"{self.channel_name}: No pulses found")
            return None
        
        # Pick the tone closest to expected position (minute boundary at ~5s into buffer)
        best_tone = min(valid_tones, key=lambda t: t['distance'])
        best_onset_idx = best_tone['onset']
        best_offset_idx = best_tone['offset']
        best_duration = best_tone['duration']
        
        logger.debug(f"{self.channel_name}: Selected tone at position {best_onset_idx} "
                    f"(distance from expected: {best_tone['distance']} samples = {best_tone['distance']/3:.1f}ms)")
        
        # 9. Calculate timing error
        # Convert expected position from 16 kHz to 3 kHz resampled coordinates
        expected_in_window_16k = expected_tone_sample - start_sample
        expected_tone_position = int(expected_in_window_16k * (3 / 16))  # Convert 16kHz to 3kHz
        timing_error_samples = best_onset_idx - expected_tone_position
        timing_error_ms = (timing_error_samples / 3000) * 1000
        
        logger.debug(f"{self.channel_name}: Tone onset at sample {best_onset_idx} "
                    f"(expected {expected_tone_position}), error: {timing_error_ms:+.1f}ms")
        
        # Calculate RTP timestamp of onset
        # onset_idx is in 3 kHz resampled detection window, convert to 16 kHz
        onset_in_window_16k = int(best_onset_idx * (16000 / 3000))
        # Add the detection window offset (we started at :57, which is 2s into buffer)
        onset_in_buffer_16k = start_sample + onset_in_window_16k
        onset_rtp_timestamp = (first_rtp_ts + onset_in_buffer_16k) & 0xFFFFFFFF
        
        # Calculate UTC time (approximate for now, will be refined by time_snap)
        onset_utc_time = minute_key + (onset_in_buffer_16k / 16000)
        
        logger.info(f"{self.channel_name}: ✅ WWV TONE DETECTED! "
                   f"Duration: {best_duration:.3f}s, "
                   f"Timing error: {timing_error_ms:+.1f} ms, "
                   f"RTP ts: {onset_rtp_timestamp}")
        
        result = {
            'detected': True,
            'timing_error_ms': timing_error_ms,
            'onset_rtp_timestamp': onset_rtp_timestamp,
            'onset_utc_time': onset_utc_time,
            'snr_db': max_env * 1000,  # Rough SNR estimate
            'duration_ms': best_duration * 1000
        }
        
        # Update stats
        self.last_wwv_detection = time.time()
        self.wwv_detections_today += 1
        
        return result
    
    def _process_wwv_tone_OLD(self, unix_time: float, iq_samples: np.ndarray, rtp_timestamp: int) -> Optional[Dict]:
        """
        Process samples for WWV tone detection
        
        Args:
            unix_time: UTC time for samples
            iq_samples: IQ samples at 16 kHz
            rtp_timestamp: RTP timestamp for first sample
        
        Returns:
            Dict with detection results if tone detected, else None
        """
        if not self.tone_detector:
            return None
        
        # Resample to 3 kHz for tone detection
        tone_samples = self.tone_resampler.resample(iq_samples)
        
        # Track buffer start (both time and RTP timestamp)
        if self.tone_buffer_start_time is None:
            self.tone_buffer_start_time = unix_time
            self.tone_buffer_start_rtp = rtp_timestamp
            logger.debug(f"{self.channel_name}: Tone buffer started, resampled {len(tone_samples)} samples from {len(iq_samples)} IQ")
        
        self.tone_buffer.extend(tone_samples)
        
        # Check for tone every 2 seconds
        if len(self.tone_buffer) >= 6000:  # 2 sec @ 3 kHz
            # Only check during detection window (AFTER minute boundary)
            # WWV tone: :00.0 for 0.8s
            # Buffer accumulates from :58, so by :01.0 we have :58-:01 = full tone + context
            # Check from :01.0 to :02.5 to ensure full tone is in buffer
            dt = datetime.fromtimestamp(unix_time, tz=timezone.utc)
            seconds_in_minute = dt.second + (dt.microsecond / 1e6)
            in_window = (1.0 <= seconds_in_minute <= 2.5)
            
            if in_window:
                # Check for WWV tone in accumulated buffer
                tone_array = np.array(list(self.tone_buffer), dtype=np.complex64)
                buffer_duration = len(self.tone_buffer) / 3000
                dt_start = datetime.fromtimestamp(self.tone_buffer_start_time, tz=timezone.utc) if self.tone_buffer_start_time else None
                logger.info(f"{self.channel_name}: WWV check @ {seconds_in_minute:.2f}s - "
                           f"buffer {len(self.tone_buffer)} samples ({buffer_duration:.2f}s), "
                           f"starts at {dt_start.strftime('%M:%S.%f')[:-3] if dt_start else 'None'}")
                
                detected, onset_idx, timing_error = self.tone_detector.detect_tone_onset(
                    tone_array,
                    self.tone_buffer_start_time
                )
                
                if detected:
                    # Calculate RTP timestamp of WWV tone onset
                    # onset_idx is in 3 kHz resampled buffer
                    # Convert back to 16 kHz: onset_samples_16k = onset_idx * (16000/3000)
                    onset_samples_16k = int(onset_idx * (16000 / 3000))
                    onset_rtp_timestamp = (self.tone_buffer_start_rtp + onset_samples_16k) & 0xFFFFFFFF
                    
                    # Calculate precise UTC time of onset
                    onset_utc_time = self.tone_buffer_start_time + (onset_idx / 3000)
                    
                    logger.info(f"{self.channel_name}: WWV tone detected! "
                               f"Timing error: {timing_error:+.1f} ms, "
                               f"RTP ts: {onset_rtp_timestamp}")
                    
                    result = {
                        'detected': True,
                        'timing_error_ms': timing_error,
                        'onset_rtp_timestamp': onset_rtp_timestamp,
                        'onset_utc_time': onset_utc_time,
                        'snr_db': 20.0,  # TODO: Calculate actual SNR
                        'duration_ms': 800.0  # TODO: Measure actual duration
                    }
                    
                    # Store for live status
                    self.last_wwv_detection = time.time()
                    self.wwv_detections_today += 1
                    
                    # Clear buffer after successful detection
                    self.tone_buffer.clear()
                    self.tone_buffer_start_time = None
                    self.tone_buffer_start_rtp = None
                    return result
                else:
                    # No detection - keep accumulating buffer through window
                    return None
            else:
                # Outside detection window
                # After window ends, clear buffer to prepare for next minute
                if seconds_in_minute > 5:  # Well past detection window
                    if len(self.tone_buffer) > 0:
                        self.tone_buffer.clear()
                        self.tone_buffer_start_time = None
                        self.tone_buffer_start_rtp = None
                # Before window or early in minute - keep accumulating
                elif len(self.tone_buffer) > 12000:  # Max 4 seconds
                    excess = len(self.tone_buffer) - 9000  # Trim to 3s
                    for _ in range(excess):
                        self.tone_buffer.popleft()
                    # Update start time and RTP timestamp to reflect trimmed buffer
                    if self.tone_buffer_start_time:
                        self.tone_buffer_start_time += excess / 3000
                        # Update RTP timestamp (excess samples at 3 kHz = excess * 16/3 at 16 kHz)
                        samples_16k = int(excess * (16000 / 3000))
                        self.tone_buffer_start_rtp = (self.tone_buffer_start_rtp + samples_16k) & 0xFFFFFFFF
        
        return None
    
    def _finalize_minute(self, minute_time: datetime, file_path: Path, wwv_result: Optional[Dict]):
        """Finalize quality metrics for completed minute"""
        # Use WWV detection to establish/verify time_snap reference
        if wwv_result and wwv_result.get('detected'):
            self._process_wwv_time_snap(wwv_result)
        
        # Calculate signal power
        # TODO: Calculate from actual samples
        signal_power_db = -40.0  # Placeholder
        
        # Calculate time_snap age
        time_snap_age_minutes = None
        if self.time_snap_established and self.time_snap_utc:
            time_snap_age_minutes = int((minute_time.timestamp() - self.time_snap_utc) / 60)
        
        # Finalize minute in quality tracker with enhanced metrics
        self.quality_tracker.finalize_minute(
            packets_received=self.current_minute_packets_rx,
            packets_dropped=self.current_minute_packets_drop,
            signal_power_db=signal_power_db,
            wwv_result=wwv_result,
            # New KA9Q timing metrics
            time_snap_established=self.time_snap_established,
            time_snap_source=self.time_snap_source or "",
            time_snap_drift_ms=self.current_minute_wwv_drift_ms,
            time_snap_age_minutes=time_snap_age_minutes,
            # Resequencing metrics
            packets_resequenced=self.current_minute_resequenced,
            max_resequencing_depth=self.current_minute_max_reseq_depth,
            resequencing_buffer_utilization=(self.current_minute_max_queue_used / self.RESEQ_SIZE) * 100.0
        )
        
        # Reset per-minute counters
        self.current_minute_wwv_drift_ms = None
        self.current_minute_resequenced = 0
        self.current_minute_max_reseq_depth = 0
        self.current_minute_max_queue_used = 0
        
        # Export CSV every minute for live dashboard updates
        date_str = minute_time.strftime('%Y%m%d')
        self.quality_tracker.export_minute_csv(date_str)
        
        # Log completion with quality grade
        if self.quality_tracker.minute_metrics:
            latest = self.quality_tracker.minute_metrics[-1]
            grade_emoji = {"A": "✅", "B": "✓", "C": "⚠️", "D": "❌", "F": "🔴"}.get(latest.quality_grade, "?")
            logger.info(f"{self.channel_name}: Minute complete: {minute_time.strftime('%H:%M')} → {file_path.name} "
                       f"[{grade_emoji} {latest.quality_grade}]")
        else:
            logger.info(f"{self.channel_name}: Minute complete: {minute_time.strftime('%H:%M')} → {file_path.name}")
    
    def _process_wwv_time_snap(self, wwv_result: Dict):
        """
        Establish or verify time_snap using WWV tone detection
        
        WWV tone rising edge occurs at exactly :00.000 of each minute,
        providing a precise anchor point for RTP timestamp → UTC mapping.
        
        Args:
            wwv_result: Detection result with onset_rtp_timestamp and onset_utc_time
        """
        onset_rtp = wwv_result['onset_rtp_timestamp']
        onset_utc = wwv_result['onset_utc_time']
        
        # Round onset to nearest minute boundary (WWV tone is at :00.000)
        minute_boundary = int(onset_utc / 60) * 60
        
        # Calculate RTP timestamp that should correspond to minute boundary
        # Account for timing error: onset may be slightly off from :00.000
        timing_error_sec = wwv_result['timing_error_ms'] / 1000.0
        offset_from_boundary = (onset_utc - minute_boundary) - timing_error_sec
        offset_samples = int(offset_from_boundary * self.sample_rate)
        
        # Calculate time_snap: RTP timestamp at the minute boundary
        time_snap_rtp = (onset_rtp - offset_samples) & 0xFFFFFFFF
        
        if not self.time_snap_established:
            # First WWV detection - establish time_snap
            self.time_snap_rtp = time_snap_rtp
            self.time_snap_utc = minute_boundary
            self.time_snap_established = True
            self.time_snap_source = "wwv_first"
            
            # For first detection, timing error is just calibration offset, not drift
            # Don't report it as drift to avoid confusion
            self.current_minute_wwv_drift_ms = None
            
            logger.info(f"{self.channel_name}: ⏱️  TIME_SNAP ESTABLISHED from WWV")
            logger.info(f"  RTP timestamp {self.time_snap_rtp} = "
                       f"UTC {datetime.fromtimestamp(minute_boundary, tz=timezone.utc).strftime('%H:%M:%S')}")
            logger.info(f"  Initial calibration offset: {timing_error_sec*1000:+.1f} ms (NOT drift)")
        else:
            # Subsequent detection - verify drift
            # Predict what UTC time this RTP timestamp should map to
            predicted_utc = self._calculate_sample_time(onset_rtp)
            actual_utc = onset_utc
            drift_ms = (predicted_utc - actual_utc) * 1000
            
            # Store drift for quality metrics
            self.current_minute_wwv_drift_ms = drift_ms
            
            logger.info(f"{self.channel_name}: WWV timing verification: "
                       f"drift = {drift_ms:+.1f} ms")
            
            # If drift is significant, consider re-establishing time_snap
            if abs(drift_ms) > 50.0:  # 50ms threshold
                logger.warning(f"{self.channel_name}: Large timing drift detected ({drift_ms:+.1f} ms), "
                              f"re-establishing time_snap")
                self.time_snap_rtp = time_snap_rtp
                self.time_snap_utc = minute_boundary
                self.time_snap_source = "wwv_corrected"
            else:
                self.time_snap_source = "wwv_verified"
    
    def get_stats(self) -> dict:
        """Get recorder statistics"""
        runtime = time.time() - self.start_time
        
        stats = {
            'channel_name': self.channel_name,
            'frequency_hz': self.frequency_hz,
            'runtime_seconds': runtime,
            'total_packets': self.total_packets,
            'packets_dropped': self.packets_dropped,
            'packet_loss_percent': (self.packets_dropped / max(1, self.total_packets)) * 100,
            'total_samples': self.total_samples,
            'sample_rate': self.sample_rate,
            'minutes_written': self.file_writer.minutes_written,
        }
        
        return stats
    
    def finalize_day(self, date_str: str):
        """Finalize day - export quality metrics"""
        # Flush any remaining data
        self.file_writer.flush()
        
        # Export metrics
        self.quality_tracker.export_minute_csv(date_str)
        self.quality_tracker.export_discontinuities_csv(date_str)
        self.quality_tracker.export_daily_summary(date_str)
        
        logger.info(f"{self.channel_name}: Day finalized, metrics exported")
