#!/usr/bin/env python3
"""
GRAPE Recorder - Two-Phase Recording with Tone Detection

Orchestrates GRAPE-specific recording with:
- Phase 1 (Startup): Buffer samples for tone detection → time_snap
- Phase 2 (Recording): Use RecordingSession with GrapeNPZWriter

This replaces ChannelProcessor with a cleaner separation of concerns:
- RTP reception/resequencing: RecordingSession + ka9q-python
- Time synchronization: StartupToneDetector  
- NPZ storage: GrapeNPZWriter
- GRAPE orchestration: GrapeRecorder (this class)

Architecture:
    RTPReceiver → GrapeRecorder (startup) → RecordingSession → GrapeNPZWriter
"""

import numpy as np
import logging
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ka9q import ChannelInfo, RTPHeader

from .rtp_receiver import RTPReceiver
from .packet_resequencer import PacketResequencer, RTPPacket, GapInfo
from .recording_session import RecordingSession, SessionConfig, SegmentInfo, SessionState
from .grape_npz_writer import GrapeNPZWriter
from .startup_tone_detector import StartupToneDetector, StartupTimeSnap

logger = logging.getLogger(__name__)


class GrapeState(Enum):
    """GRAPE recorder states"""
    IDLE = "idle"              # Not started
    STARTUP = "startup"        # Buffering for time_snap
    RECORDING = "recording"    # Normal recording
    STOPPING = "stopping"      # Graceful shutdown


@dataclass
class GrapeConfig:
    """Configuration for GRAPE recorder"""
    # Channel identification
    ssrc: int
    frequency_hz: float
    sample_rate: int
    description: str
    
    # Output
    output_dir: Path
    station_config: Dict[str, Any]
    
    # Startup
    startup_buffer_duration: float = 120.0  # Seconds to buffer for tone detection
    
    # Periodic tone validation
    tone_check_interval: float = 300.0      # Check every 5 minutes
    tone_check_buffer_duration: float = 60.0  # Buffer 60s for tone check


class GrapeRecorder:
    """
    GRAPE recorder with two-phase operation.
    
    Phase 1 (Startup):
    - Register raw RTP callback
    - Buffer samples for startup_buffer_duration (120s)
    - Run tone detection to establish time_snap
    - Process buffered samples through RecordingSession
    
    Phase 2 (Recording):
    - RecordingSession handles RTP → segments
    - GrapeNPZWriter handles segment → NPZ
    - Periodic tone re-validation
    
    Usage:
        config = GrapeConfig(ssrc=20100, frequency_hz=10e6, ...)
        recorder = GrapeRecorder(config, rtp_receiver, get_ntp_status)
        recorder.start()
        # ... runs until stop() called
        recorder.stop()
    """
    
    def __init__(
        self,
        config: GrapeConfig,
        rtp_receiver: RTPReceiver,
        get_ntp_status: Optional[Callable[[], Dict[str, Any]]] = None,
        channel_info: Optional[ChannelInfo] = None,
    ):
        """
        Initialize GRAPE recorder.
        
        Args:
            config: GRAPE-specific configuration
            rtp_receiver: Shared RTP receiver instance
            get_ntp_status: Callable for NTP status (avoids subprocess calls)
            channel_info: Optional timing info from radiod
        """
        self.config = config
        self.rtp_receiver = rtp_receiver
        self.get_ntp_status = get_ntp_status
        self.channel_info = channel_info
        
        # State
        self.state = GrapeState.IDLE
        self._lock = threading.Lock()
        
        # Startup phase components
        self.startup_resequencer = PacketResequencer(
            buffer_size=64,
            samples_per_packet=320
        )
        self.startup_buffer: list = []  # List of (rtp_timestamp, samples, gap_info)
        self.startup_buffer_start_time: Optional[float] = None
        self.startup_buffer_first_rtp: Optional[int] = None
        
        # Tone detection
        self.tone_detector = StartupToneDetector(
            sample_rate=config.sample_rate,
            frequency_hz=config.frequency_hz
        )
        self.time_snap: Optional[StartupTimeSnap] = None
        
        # Recording phase components (created after time_snap established)
        self.session: Optional[RecordingSession] = None
        self.npz_writer: Optional[GrapeNPZWriter] = None
        
        # Periodic tone checking
        self.tone_check_buffer: list = []  # Rolling buffer for periodic checks
        self.last_tone_check_time: Optional[float] = None
        
        # Statistics
        self.packets_received = 0
        self.last_packet_time: float = 0.0
        
        logger.info(f"GrapeRecorder initialized: {config.description} (SSRC {config.ssrc})")
        logger.info(f"  Startup buffer: {config.startup_buffer_duration}s")
        logger.info(f"  Tone check interval: {config.tone_check_interval}s")
    
    def start(self):
        """Start the GRAPE recorder (enters startup phase)"""
        with self._lock:
            if self.state != GrapeState.IDLE:
                logger.warning(f"Cannot start in state {self.state}")
                return
            
            # Reset startup state
            self.startup_buffer = []
            self.startup_buffer_start_time = None
            self.startup_buffer_first_rtp = None
            self.startup_resequencer = PacketResequencer(
                buffer_size=64,
                samples_per_packet=320
            )
            
            # Register callback for startup buffering
            self.rtp_receiver.register_callback(
                ssrc=self.config.ssrc,
                callback=self._handle_startup_packet,
                channel_info=self.channel_info
            )
            
            self.state = GrapeState.STARTUP
            logger.info(f"{self.config.description}: Started (startup phase)")
    
    def stop(self):
        """Stop the GRAPE recorder gracefully"""
        with self._lock:
            if self.state == GrapeState.IDLE:
                return
            
            self.state = GrapeState.STOPPING
        
        # Stop components (outside lock to avoid deadlock)
        if self.session:
            self.session.stop()
        
        if self.npz_writer:
            self.npz_writer.flush()
        
        # Unregister callback
        self.rtp_receiver.unregister_callback(self.config.ssrc)
        
        with self._lock:
            self.state = GrapeState.IDLE
        
        logger.info(f"{self.config.description}: Stopped")
    
    def flush(self):
        """Flush any buffered data (for shutdown)"""
        with self._lock:
            if self.state == GrapeState.STARTUP:
                logger.warning(f"{self.config.description}: Cannot flush during startup")
                return
        
        if self.session:
            self.session.stop()
        
        if self.npz_writer:
            self.npz_writer.flush()
    
    # === Startup Phase ===
    
    def _handle_startup_packet(
        self,
        header: RTPHeader,
        payload: bytes,
        wallclock: Optional[float] = None
    ):
        """Handle RTP packet during startup phase"""
        try:
            with self._lock:
                if self.state != GrapeState.STARTUP:
                    return
                
                self.packets_received += 1
                self.last_packet_time = time.time()
                
                # Decode payload
                iq_samples = self._decode_payload(header.payload_type, payload)
                if iq_samples is None:
                    return
                
                # Create packet for resequencer
                rtp_pkt = RTPPacket(
                    sequence=header.sequence,
                    timestamp=header.timestamp,
                    ssrc=header.ssrc,
                    samples=iq_samples
                )
                
                # Resequence
                output_samples, gap_info = self.startup_resequencer.process_packet(rtp_pkt)
                
                if output_samples is None:
                    return  # Still buffering
                
                # Track first RTP timestamp
                if self.startup_buffer_start_time is None:
                    self.startup_buffer_start_time = time.time()
                    self.startup_buffer_first_rtp = header.timestamp
                    logger.info(f"{self.config.description}: Starting startup buffer...")
                
                # Add to buffer
                self.startup_buffer.append((header.timestamp, output_samples, gap_info))
                
                # Check if startup complete
                elapsed = time.time() - self.startup_buffer_start_time
                if elapsed >= self.config.startup_buffer_duration:
                    self._complete_startup()
                    
        except Exception as e:
            logger.error(f"{self.config.description}: Startup packet error: {e}", exc_info=True)
    
    def _complete_startup(self):
        """Complete startup phase: detect tones, create session"""
        logger.info(f"{self.config.description}: Startup buffer complete, establishing time_snap...")
        
        # Concatenate samples for tone detection
        all_samples = np.concatenate([samples for _, samples, _ in self.startup_buffer])
        
        # Run tone detection
        self.time_snap = self.tone_detector.detect_time_snap(
            iq_samples=all_samples,
            first_rtp_timestamp=self.startup_buffer_first_rtp,
            wall_clock_start=self.startup_buffer_start_time
        )
        
        if self.time_snap:
            logger.info(f"{self.config.description}: ✅ time_snap established")
            logger.info(f"  Source: {self.time_snap.source}")
            logger.info(f"  Station: {self.time_snap.station}")
            logger.info(f"  Confidence: {self.time_snap.confidence:.2f}")
            logger.info(f"  SNR: {self.time_snap.detection_snr_db:.1f} dB")
        else:
            # Fallback to NTP or wall clock
            self._create_fallback_time_snap()
        
        # Create NPZ writer
        self.npz_writer = GrapeNPZWriter(
            output_dir=self.config.output_dir,
            channel_name=self.config.description,
            frequency_hz=self.config.frequency_hz,
            sample_rate=self.config.sample_rate,
            ssrc=self.config.ssrc,
            time_snap=self.time_snap,
            station_config=self.config.station_config,
            get_ntp_status=self.get_ntp_status
        )
        
        # Create recording session
        session_config = SessionConfig(
            ssrc=self.config.ssrc,
            sample_rate=self.config.sample_rate,
            description=self.config.description,
            segment_duration_sec=60.0,  # 1-minute segments
            align_to_boundary=True,
            resequencer_buffer_size=64,
            samples_per_packet=320
        )
        
        self.session = RecordingSession(
            config=session_config,
            rtp_receiver=self.rtp_receiver,
            writer=self.npz_writer,
            channel_info=self.channel_info,
            on_segment_complete=self._on_segment_complete,
            metadata_provider=self._get_segment_metadata
        )
        
        # Transition to recording state
        self.state = GrapeState.RECORDING
        
        # Re-register callback (now handled by RecordingSession)
        # The session will register its own callback
        self.rtp_receiver.unregister_callback(self.config.ssrc)
        self.session.start()
        
        # Process buffered samples through session
        logger.info(f"{self.config.description}: Processing {len(self.startup_buffer)} buffered packets...")
        self._process_buffered_samples()
        
        # Clear startup buffer
        self.startup_buffer = []
        
        # Initialize periodic tone checking
        self.last_tone_check_time = time.time()
        
        logger.info(f"{self.config.description}: Startup complete, normal recording started")
    
    def _create_fallback_time_snap(self):
        """Create time_snap from NTP or wall clock"""
        logger.warning(f"{self.config.description}: No tone detected, using fallback...")
        
        if self.get_ntp_status:
            ntp_status = self.get_ntp_status()
            ntp_synced = ntp_status.get('synced', False)
            ntp_offset_ms = ntp_status.get('offset_ms')
        else:
            ntp_synced = False
            ntp_offset_ms = None
        
        if ntp_synced:
            logger.info(f"{self.config.description}: Using NTP sync (offset={ntp_offset_ms:.1f}ms)")
            self.time_snap = self.tone_detector.create_ntp_time_snap(
                first_rtp_timestamp=self.startup_buffer_first_rtp,
                ntp_synced=True,
                ntp_offset_ms=ntp_offset_ms
            )
        else:
            logger.warning(f"{self.config.description}: No NTP sync, using wall clock (low accuracy)")
            self.time_snap = self.tone_detector.create_wall_clock_time_snap(
                first_rtp_timestamp=self.startup_buffer_first_rtp
            )
    
    def _process_buffered_samples(self):
        """
        Process startup-buffered samples through the recording session.
        
        This replays the buffered packets so they get written to NPZ files.
        The RecordingSession handles resequencing, so we inject samples
        directly into the session's write path.
        """
        # The RecordingSession has its own resequencer, but we already
        # resequenced during startup. We need to inject samples directly.
        # 
        # Approach: Create synthetic segments from buffered data and write them.
        
        if not self.startup_buffer or not self.npz_writer:
            return
        
        # Calculate samples per minute
        samples_per_minute = self.config.sample_rate * 60
        
        # Group samples into minute-sized chunks
        all_samples = []
        all_gaps = []
        first_rtp = self.startup_buffer[0][0]
        
        current_sample_idx = 0
        for rtp_ts, samples, gap_info in self.startup_buffer:
            if gap_info and gap_info.gap_samples > 0:
                all_gaps.append((current_sample_idx, gap_info))
            all_samples.append(samples)
            current_sample_idx += len(samples)
        
        # Concatenate all samples
        combined = np.concatenate(all_samples)
        
        # Write minute-sized segments
        offset = 0
        segment_id = 0
        
        while offset < len(combined):
            # Calculate segment size (might be partial at end)
            segment_size = min(samples_per_minute, len(combined) - offset)
            segment_samples = combined[offset:offset + segment_size]
            
            # Create segment info
            segment_rtp = first_rtp + offset
            utc_at_segment = self._calculate_utc_from_rtp(segment_rtp)
            
            segment_info = SegmentInfo(
                segment_id=segment_id,
                start_time=utc_at_segment,
                start_rtp_timestamp=segment_rtp,
                sample_count=len(segment_samples)
            )
            
            # Collect gaps for this segment
            segment_gaps = []
            for gap_idx, gap_info in all_gaps:
                if offset <= gap_idx < offset + segment_size:
                    segment_gaps.append((gap_idx - offset, gap_info))
            
            # Write segment directly (bypass RecordingSession for buffered data)
            self.npz_writer.start_segment(segment_info, {})
            
            # Write samples with gaps
            sample_offset = 0
            for gap_sample_idx, gap_info in segment_gaps:
                # Write samples before gap
                if gap_sample_idx > sample_offset:
                    self.npz_writer.write_samples(
                        segment_samples[sample_offset:gap_sample_idx],
                        segment_rtp + sample_offset,
                        None
                    )
                    sample_offset = gap_sample_idx
                
                # Write gap-filled samples
                gap_end = gap_sample_idx + gap_info.gap_samples
                self.npz_writer.write_samples(
                    segment_samples[gap_sample_idx:min(gap_end, segment_size)],
                    segment_rtp + gap_sample_idx,
                    gap_info
                )
                sample_offset = min(gap_end, segment_size)
            
            # Write remaining samples
            if sample_offset < segment_size:
                self.npz_writer.write_samples(
                    segment_samples[sample_offset:],
                    segment_rtp + sample_offset,
                    None
                )
            
            # Finish segment (only if full minute)
            if segment_size >= samples_per_minute:
                self.npz_writer.finish_segment(segment_info)
            
            offset += segment_size
            segment_id += 1
    
    def _calculate_utc_from_rtp(self, rtp_timestamp: int) -> float:
        """Calculate UTC from RTP using time_snap"""
        if not self.time_snap:
            return time.time()
        
        rtp_diff = rtp_timestamp - self.time_snap.rtp_timestamp
        
        if rtp_diff > 0x80000000:
            rtp_diff -= 0x100000000
        elif rtp_diff < -0x80000000:
            rtp_diff += 0x100000000
        
        elapsed = rtp_diff / self.time_snap.sample_rate
        return self.time_snap.utc_timestamp + elapsed
    
    # === Recording Phase Callbacks ===
    
    def _on_segment_complete(self, segment_info: SegmentInfo, result: Any):
        """Called when RecordingSession completes a segment"""
        # Update last packet time
        self.last_packet_time = time.time()
        
        # Run periodic tone check
        self._maybe_check_tones()
        
        logger.debug(
            f"{self.config.description}: Segment {segment_info.segment_id} complete, "
            f"{segment_info.sample_count} samples"
        )
    
    def _get_segment_metadata(self) -> Dict[str, Any]:
        """Provide metadata for each segment"""
        return {
            'time_snap_source': self.time_snap.source if self.time_snap else 'none',
            'time_snap_confidence': self.time_snap.confidence if self.time_snap else 0.0,
        }
    
    def _maybe_check_tones(self):
        """Periodically run tone detection to update time_snap"""
        if not self.last_tone_check_time:
            return
        
        elapsed = time.time() - self.last_tone_check_time
        if elapsed < self.config.tone_check_interval:
            return
        
        # TODO: Implement periodic tone checking
        # This requires maintaining a rolling buffer of recent samples
        # For now, just update the timestamp
        self.last_tone_check_time = time.time()
    
    # === Utility Methods ===
    
    def _decode_payload(self, payload_type: int, payload: bytes) -> Optional[np.ndarray]:
        """Decode RTP payload to complex IQ samples"""
        try:
            if payload_type in (120, 97):
                # int16 IQ format
                if len(payload) % 4 != 0:
                    return None
                samples_int16 = np.frombuffer(payload, dtype=np.int16)
                samples = samples_int16.astype(np.float32) / 32768.0
                
            elif payload_type == 11:
                # float32 IQ format
                if len(payload) % 8 != 0:
                    return None
                samples = np.frombuffer(payload, dtype=np.float32)
                
            else:
                # Unknown - try float32
                if len(payload) % 8 != 0:
                    return None
                samples = np.frombuffer(payload, dtype=np.float32)
            
            # Convert interleaved I/Q to complex
            i_samples = samples[0::2]
            q_samples = samples[1::2]
            return (i_samples + 1j * q_samples).astype(np.complex64)
            
        except Exception as e:
            logger.warning(f"Payload decode error: {e}")
            return None
    
    # === Status Methods ===
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        with self._lock:
            writer_stats = self.npz_writer.get_stats() if self.npz_writer else {}
            session_metrics = self.session.get_metrics() if self.session else {}
            
            # Get packet count from session if in recording phase, else from startup
            if self.session:
                total_packets = session_metrics.get('packets_received', 0) + self.packets_received
            else:
                total_packets = self.packets_received
            
            return {
                'state': self.state.value,
                'packets_received': total_packets,
                'minutes_written': writer_stats.get('segments_written', 0),
                'time_snap_source': self.time_snap.source if self.time_snap else 'none',
                'time_snap_confidence': self.time_snap.confidence if self.time_snap else 0.0,
                **session_metrics,
                **writer_stats,
            }
    
    def get_status(self) -> Dict[str, Any]:
        """Get detailed status for web-ui"""
        with self._lock:
            last_packet_iso = (
                datetime.fromtimestamp(self.last_packet_time, timezone.utc).isoformat()
                if self.last_packet_time > 0 else None
            )
            
            # Get packet count from session if in recording phase
            session_metrics = self.session.get_metrics() if self.session else {}
            if self.session:
                total_packets = session_metrics.get('packets_received', 0) + self.packets_received
            else:
                total_packets = self.packets_received
            
            return {
                'description': self.config.description,
                'frequency_hz': self.config.frequency_hz,
                'sample_rate': self.config.sample_rate,
                'state': self.state.value,
                'packets_received': total_packets,
                'npz_files_written': self.npz_writer.segments_written if self.npz_writer else 0,
                'last_npz_file': str(self.npz_writer.last_file_written) if self.npz_writer else None,
                'time_snap_source': self.time_snap.source if self.time_snap else 'none',
                'time_snap_confidence': self.time_snap.confidence if self.time_snap else 0.0,
                'last_packet_time': last_packet_iso,
            }
    
    def is_healthy(self, timeout_sec: float = 120.0) -> bool:
        """Check if channel is receiving packets"""
        with self._lock:
            if self.last_packet_time == 0:
                return True  # Never received - give it time
            
            silence = time.time() - self.last_packet_time
            return silence < timeout_sec
    
    def get_silence_duration(self) -> float:
        """Get seconds since last packet"""
        with self._lock:
            if self.last_packet_time == 0:
                return 0.0
            return time.time() - self.last_packet_time
    
    def reset_health(self):
        """Reset health timestamp after channel recreation"""
        with self._lock:
            self.last_packet_time = time.time()
        logger.debug(f"{self.config.description}: Health timer reset")
