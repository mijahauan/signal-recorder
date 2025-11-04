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
from typing import Optional, Dict, List, NamedTuple
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
        self.wwv_results_by_minute = {}  # minute_timestamp -> list of detections (WWV, WWVH, CHU)
        
        # Matched filter templates for tone detection (at 3 kHz processing rate)
        if self.is_wwv_channel:
            from scipy import signal as scipy_signal
            fs_proc = 3000  # Processing sample rate after resampling
            
            # WWV: 800ms of 1000 Hz (Fort Collins)
            t_wwv = np.arange(0, 0.8, 1/fs_proc)
            self.template_wwv = np.sin(2 * np.pi * 1000 * t_wwv)
            self.template_wwv *= scipy_signal.windows.tukey(len(t_wwv), alpha=0.1)
            
            # WWVH: 800ms of 1200 Hz (Hawaii)
            t_wwvh = np.arange(0, 0.8, 1/fs_proc)
            self.template_wwvh = np.sin(2 * np.pi * 1200 * t_wwvh)
            self.template_wwvh *= scipy_signal.windows.tukey(len(t_wwvh), alpha=0.1)
            
            # CHU: 500ms of 1000 Hz (Canada)
            t_chu = np.arange(0, 0.5, 1/fs_proc)
            self.template_chu = np.sin(2 * np.pi * 1000 * t_chu)
            self.template_chu *= scipy_signal.windows.tukey(len(t_chu), alpha=0.1)
            
            logger.info(f"{channel_name}: Matched filter templates created (WWV 1000Hz, WWVH 1200Hz, CHU 1000Hz)")
        
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
                # Process this minute's buffer (returns list of detections)
                detections = self._detect_wwv_in_buffer(minute_key)
                
                # Save all detections for this minute (WWV, WWVH, CHU may all be present)
                if detections:
                    self.wwv_results_by_minute[minute_key] = detections
                
                # Clean up processed buffer and old buffers
                # Delete the buffer we just processed
                del self.wwv_minute_buffer[minute_key]
                
                # Also delete any older buffers
                old_keys = [k for k in self.wwv_minute_buffer.keys() if k < minute_key]
                for old_key in old_keys:
                    del self.wwv_minute_buffer[old_key]
                
                # Reset current minute pointer (will be set again at next :55)
                self.wwv_current_minute = None
        
        return None
    
    def _detect_wwv_in_buffer(self, minute_key: int) -> Optional[List[Dict]]:
        """
        Detect WWV/WWVH/CHU tones using matched filtering (cross-correlation)
        
        Returns list of detections (may contain WWV, WWVH, and/or CHU)
        Each detection has: station, onset_rtp_timestamp, timing_error_ms, etc.
        """
        from scipy import signal as scipy_signal
        from scipy.signal import correlate
        
        buffer_entries = self.wwv_minute_buffer[minute_key]
        if len(buffer_entries) == 0:
            return None
        
        # Concatenate all IQ samples
        all_iq = np.concatenate([samples for _, samples in buffer_entries])
        first_rtp_ts = buffer_entries[0][0]
        
        logger.info(f"{self.channel_name}: Processing WWV buffer: {len(all_iq):,} samples ({len(all_iq)/16000:.1f}s)")
        
        # Use 6-second window centered on minute boundary
        # Buffer is :55-:05 (10s), minute boundary at :00 (5s into buffer)
        # Extract :57-:03 (6 seconds) for matched filtering
        buffer_duration = len(all_iq) / 16000
        
        if buffer_duration < 6.0:
            logger.warning(f"{self.channel_name}: Buffer too short ({buffer_duration:.1f}s < 6s)")
            return None
        
        start_sample_16k = min(int(2.0 * 16000), len(all_iq) - 96000)  # Start at 2s (:57)
        end_sample_16k = min(start_sample_16k + 96000, len(all_iq))    # 6 seconds
        detection_window = all_iq[start_sample_16k:end_sample_16k]
        
        # === Matched Filter Detection ===
        
        # 1. AM demodulation (AC-coupled)
        magnitude = np.abs(detection_window)
        audio_signal = magnitude - np.mean(magnitude)
        
        # 2. Resample to 3 kHz for processing
        audio_3k = scipy_signal.resample_poly(audio_signal, 3, 16)
        
        # 3. Cross-correlate with appropriate templates based on channel
        # WWV frequencies: 2.5, 5, 10, 15, 20, 25 MHz -> WWV + WWVH
        # CHU frequencies: 3.33, 7.85, 14.67 MHz -> CHU only
        is_chu_channel = 'CHU' in self.channel_name
        
        detections = []
        expected_pos_3k = int(3.0 * 3000)  # Expected at 3s into 6s window (minute boundary)
        stations = []  # (name, correlation, duration, frequency)
        
        if is_chu_channel:
            # CHU channel: Only correlate with CHU template
            corr_chu = correlate(audio_3k, self.template_chu, mode='valid')
            if len(corr_chu) == 0:
                logger.debug(f"{self.channel_name}: Buffer too short for correlation")
                return None
            stations.append(('CHU', corr_chu, 0.5, 1000))
        else:
            # WWV channel: Correlate with both WWV and WWVH templates
            corr_wwv = correlate(audio_3k, self.template_wwv, mode='valid')
            corr_wwvh = correlate(audio_3k, self.template_wwvh, mode='valid')
            if len(corr_wwv) == 0:
                logger.debug(f"{self.channel_name}: Buffer too short for correlation")
                return None
            stations.append(('WWV', corr_wwv, 0.8, 1000))
            stations.append(('WWVH', corr_wwvh, 0.8, 1200))
        
        # 4. Find peaks and apply noise-adaptive thresholds
        
        for station_name, correlation, expected_dur, freq in stations:
            # Search for peak in ±500ms window around expected position
            # This prevents false detections from noise peaks far from minute boundary
            search_window = int(0.5 * 3000)  # ±500ms at 3kHz
            search_start = max(0, expected_pos_3k - search_window)
            search_end = min(len(correlation), expected_pos_3k + search_window)
            
            if search_start >= search_end:
                continue  # Window invalid
            
            # Find peak within search window
            search_region = correlation[search_start:search_end]
            local_peak_idx = np.argmax(search_region)
            peak_idx = search_start + local_peak_idx
            peak_val = correlation[peak_idx]
            
            # Noise-adaptive threshold: Use noise from OUTSIDE the search window
            # This avoids including the signal peak in noise estimation
            noise_samples = np.concatenate([
                correlation[:max(0, search_start - 100)],
                correlation[min(len(correlation), search_end + 100):]
            ])
            if len(noise_samples) > 100:
                noise_mean = np.mean(noise_samples)
                noise_std = np.std(noise_samples)
                noise_floor = noise_mean + 2.5 * noise_std  # Reduced from 3σ to 2.5σ
            else:
                # Fallback for short correlation
                noise_mean = np.mean(correlation)
                noise_std = np.std(correlation)
                noise_floor = noise_mean + 2.5 * noise_std
            
            # Debug logging for threshold decisions
            logger.debug(f"{self.channel_name}: {station_name} correlation - "
                        f"peak={peak_val:.2f}, noise_floor={noise_floor:.2f} "
                        f"(mean={noise_mean:.2f}, std={noise_std:.2f}), "
                        f"ratio={peak_val/noise_floor:.2f}x")
            
            # Check if peak is significant
            if peak_val > noise_floor:
                # Calculate timing relative to expected position
                timing_offset_samples = peak_idx - expected_pos_3k
                timing_error_ms = (timing_offset_samples / 3000) * 1000
                
                # Convert to 16 kHz coordinates for RTP timestamp
                onset_in_window_16k = int(peak_idx * (16000 / 3000))
                onset_in_buffer_16k = start_sample_16k + onset_in_window_16k
                onset_rtp_timestamp = (first_rtp_ts + onset_in_buffer_16k) & 0xFFFFFFFF
                onset_utc_time = minute_key + (onset_in_buffer_16k / 16000)
                
                # Signal quality: peak relative to noise floor
                # Use the improved noise estimate we calculated above
                if noise_mean > 0 and peak_val > noise_mean:
                    snr_estimate = 20 * np.log10(peak_val / noise_mean)
                else:
                    snr_estimate = 0.0
                
                detection = {
                    'detected': True,
                    'station': station_name,
                    'frequency_hz': freq,
                    'timing_error_ms': timing_error_ms,
                    'onset_rtp_timestamp': onset_rtp_timestamp,
                    'onset_utc_time': onset_utc_time,
                    'snr_db': snr_estimate,
                    'duration_ms': expected_dur * 1000,
                    'correlation_peak': float(peak_val),
                    'correlation_snr': float(snr_estimate)
                }
                
                detections.append(detection)
                
                logger.info(f"{self.channel_name}: ✅ {station_name} TONE DETECTED! "
                           f"Freq: {freq}Hz, Duration: {expected_dur:.1f}s, "
                           f"Timing error: {timing_error_ms:+.1f}ms, "
                           f"SNR: {snr_estimate:.1f}dB, RTP: {onset_rtp_timestamp}")
        
        # Return all detections found (may be WWV + WWVH on same frequency)
        if len(detections) == 0:
            logger.debug(f"{self.channel_name}: No tones above noise threshold")
            return None
        
        # Update stats
        self.last_wwv_detection = time.time()
        self.wwv_detections_today += len(detections)
        
        # Sort by timing accuracy (closest to minute boundary)
        detections.sort(key=lambda d: abs(d['timing_error_ms']))
        
        return detections
    
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
    
    def _finalize_minute(self, minute_time: datetime, file_path: Path, wwv_detections: Optional[List[Dict]]):
        """Finalize quality metrics for completed minute
        
        Args:
            wwv_detections: List of detections (WWV, WWVH, CHU), sorted by timing accuracy
        """
        # Process WWV detections for time_snap establishment/verification
        # Strategy: Use WWV (Fort Collins) for time_snap, WWVH (Hawaii) for propagation study
        if wwv_detections:
            # Separate WWV from WWVH detections
            wwv_only = [d for d in wwv_detections if d['station'] == 'WWV']
            wwvh_only = [d for d in wwv_detections if d['station'] == 'WWVH']
            chu_only = [d for d in wwv_detections if d['station'] == 'CHU']
            
            # Use WWV (or CHU if no WWV) for time_snap establishment
            primary_detections = wwv_only if wwv_only else chu_only
            if primary_detections:
                self._process_wwv_time_snap(primary_detections[0])
                logger.info(f"{self.channel_name}: ⏱️ Time_snap from {primary_detections[0]['station']} "
                           f"(error: {primary_detections[0]['timing_error_ms']:+.1f}ms)")
            
            # Log WWVH for propagation analysis (don't use for time_snap)
            if wwvh_only:
                wwvh_det = wwvh_only[0]
                logger.info(f"{self.channel_name}: 📡 WWVH propagation: "
                           f"timing={wwvh_det['timing_error_ms']:+.1f}ms, "
                           f"SNR={wwvh_det['snr_db']:.1f}dB")
                
                # If we have both WWV and WWVH, calculate differential delay
                if wwv_only:
                    diff_delay = wwv_only[0]['timing_error_ms'] - wwvh_det['timing_error_ms']
                    logger.info(f"{self.channel_name}: 🌍 Differential propagation delay (WWV-WWVH): {diff_delay:+.1f}ms")
            
            # For quality metrics, pass ALL detections so they can be separated by station
            wwv_result = wwv_detections
        else:
            wwv_result = None
        
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
        # onset_utc already includes the actual detected position, so we just
        # need to back-calculate to the minute boundary
        offset_from_boundary = onset_utc - minute_boundary
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
            
            timing_offset_ms = offset_from_boundary * 1000
            logger.info(f"{self.channel_name}: ⏱️  TIME_SNAP ESTABLISHED")
            logger.info(f"  RTP timestamp {self.time_snap_rtp} = "
                       f"UTC {datetime.fromtimestamp(minute_boundary, tz=timezone.utc).strftime('%H:%M:%S')}")
            logger.info(f"  Tone detected at: {timing_offset_ms:+.1f} ms from minute boundary")
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
