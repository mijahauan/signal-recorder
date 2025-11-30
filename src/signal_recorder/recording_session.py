#!/usr/bin/env python3
"""
Generic Recording Session

Provides a clean interface for recording RTP streams with:
- Packet resequencing and gap detection
- Time-based segmentation
- Transport timing from radiod (GPS_TIME/RTP_TIMESNAP)
- Callbacks for application-specific storage

This module is application-agnostic. GRAPE, WSPR, CODAR, etc. 
implement their own storage and processing via callbacks.

Architecture:
    ka9q-python (RTP, timing) → RecordingSession (resequencing, segmentation) → App (storage)
"""

import numpy as np
import logging
import time
import threading
from typing import Optional, Callable, Dict, Any, Protocol
from dataclasses import dataclass, field
from enum import Enum

from ka9q import ChannelInfo, RTPHeader

from .rtp_receiver import RTPReceiver
from .packet_resequencer import PacketResequencer, RTPPacket, GapInfo

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Recording session states"""
    IDLE = "idle"              # Not started
    WAITING = "waiting"        # Waiting for segment boundary
    RECORDING = "recording"    # Actively recording
    STOPPING = "stopping"      # Graceful shutdown in progress


@dataclass
class SegmentInfo:
    """Information about a recording segment"""
    segment_id: int                      # Sequential segment number
    start_time: float                    # Unix timestamp of first sample
    start_rtp_timestamp: int             # RTP timestamp of first sample
    sample_count: int = 0                # Samples written so far
    gap_count: int = 0                   # Number of gaps in segment
    gap_samples: int = 0                 # Total samples filled as gaps
    wallclock_start: Optional[float] = None  # Transport timing if available


@dataclass
class SessionMetrics:
    """Cumulative session metrics"""
    segments_completed: int = 0
    total_samples: int = 0
    total_gaps: int = 0
    total_gap_samples: int = 0
    packets_received: int = 0
    packets_resequenced: int = 0
    session_start_time: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'segments_completed': self.segments_completed,
            'total_samples': self.total_samples,
            'total_gaps': self.total_gaps,
            'total_gap_samples': self.total_gap_samples,
            'packets_received': self.packets_received,
            'packets_resequenced': self.packets_resequenced,
            'uptime_seconds': time.time() - self.session_start_time,
        }


class SegmentWriter(Protocol):
    """
    Protocol for segment writers - applications implement this.
    
    Example implementations:
    - NPZWriter for GRAPE
    - WAVWriter for WSPR/FT8
    - RawWriter for CODAR
    """
    
    def start_segment(self, segment_info: SegmentInfo, metadata: Dict[str, Any]) -> None:
        """Called when a new segment begins"""
        ...
    
    def write_samples(self, samples: np.ndarray, rtp_timestamp: int, 
                      gap_info: Optional[GapInfo] = None) -> None:
        """Called for each batch of samples (may include gap fill)"""
        ...
    
    def finish_segment(self, segment_info: SegmentInfo) -> Optional[Any]:
        """Called when segment completes. Returns result (e.g., file path)"""
        ...


@dataclass
class SessionConfig:
    """Configuration for a recording session"""
    # Channel identification
    ssrc: int
    sample_rate: int
    description: str = ""
    
    # Segmentation
    segment_duration_sec: Optional[float] = 60.0  # None = continuous
    align_to_boundary: bool = True                # Align to wall clock
    boundary_offset_sec: float = 0.0              # Offset from boundary
    
    # Resequencing
    resequencer_buffer_size: int = 64
    samples_per_packet: int = 320
    
    # Payload format
    payload_type: int = 120  # Default: int16 IQ
    
    def __post_init__(self):
        if self.segment_duration_sec is not None and self.segment_duration_sec <= 0:
            raise ValueError("segment_duration_sec must be positive or None")


class RecordingSession:
    """
    Generic recording session manager.
    
    Handles:
    - RTP packet reception and resequencing
    - Gap detection and filling
    - Time-based segmentation
    - Transport timing (from radiod)
    
    Applications provide a SegmentWriter to handle storage.
    
    Example:
        config = SessionConfig(ssrc=10000000, sample_rate=16000)
        session = RecordingSession(
            config=config,
            rtp_receiver=receiver,
            writer=MyNPZWriter(output_dir),
        )
        session.start()
    """
    
    def __init__(
        self,
        config: SessionConfig,
        rtp_receiver: RTPReceiver,
        writer: SegmentWriter,
        channel_info: Optional[ChannelInfo] = None,
        on_segment_complete: Optional[Callable[[SegmentInfo, Any], None]] = None,
        metadata_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        """
        Initialize recording session.
        
        Args:
            config: Session configuration
            rtp_receiver: Shared RTP receiver instance
            writer: Application-provided segment writer
            channel_info: Optional timing info from radiod
            on_segment_complete: Callback when segment finishes
            metadata_provider: Callback to get metadata for each segment
        """
        self.config = config
        self.rtp_receiver = rtp_receiver
        self.writer = writer
        self.channel_info = channel_info
        self.on_segment_complete = on_segment_complete
        self.metadata_provider = metadata_provider
        
        # State
        self.state = SessionState.IDLE
        self.current_segment: Optional[SegmentInfo] = None
        self.segment_counter = 0
        self.metrics = SessionMetrics()
        
        # Resequencer
        self.resequencer = PacketResequencer(
            buffer_size=config.resequencer_buffer_size,
            samples_per_packet=config.samples_per_packet
        )
        
        # Segment timing
        self.segment_start_rtp: Optional[int] = None
        self.segment_sample_count = 0
        self.samples_per_segment = (
            int(config.segment_duration_sec * config.sample_rate)
            if config.segment_duration_sec else None
        )
        
        # Thread safety
        self._lock = threading.Lock()
        
        logger.info(f"RecordingSession initialized: {config.description} (SSRC {config.ssrc})")
    
    def start(self):
        """Start the recording session"""
        with self._lock:
            if self.state != SessionState.IDLE:
                logger.warning(f"Cannot start session in state {self.state}")
                return
            
            # Register callback with RTP receiver
            self.rtp_receiver.register_callback(
                ssrc=self.config.ssrc,
                callback=self._handle_rtp_packet,
                channel_info=self.channel_info
            )
            
            self.state = SessionState.WAITING
            self.metrics = SessionMetrics()
            
            logger.info(f"Session started: {self.config.description}")
    
    def stop(self):
        """Stop the recording session gracefully"""
        with self._lock:
            if self.state == SessionState.IDLE:
                return
            
            self.state = SessionState.STOPPING
            
            # Finish current segment if active
            if self.current_segment:
                self._finish_segment()
            
            # Unregister callback
            self.rtp_receiver.unregister_callback(self.config.ssrc)
            
            self.state = SessionState.IDLE
            
            logger.info(f"Session stopped: {self.config.description}")
    
    def _handle_rtp_packet(self, header: RTPHeader, payload: bytes, 
                           wallclock: Optional[float] = None):
        """
        Handle incoming RTP packet (called from RTP receiver thread).
        
        Args:
            header: Parsed RTP header
            payload: Raw payload bytes
            wallclock: Transport timing from radiod (if available)
        """
        try:
            with self._lock:
                if self.state not in (SessionState.WAITING, SessionState.RECORDING):
                    return
                
                self.metrics.packets_received += 1
                
                # Decode payload to IQ samples
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
                output_samples, gap_info = self.resequencer.process_packet(rtp_pkt)
                
                if output_samples is None:
                    # Still buffering
                    return
                
                # Handle segment boundaries
                if self.state == SessionState.WAITING:
                    self._start_segment(header.timestamp, wallclock)
                
                # Write samples
                self._write_samples(output_samples, header.timestamp, gap_info)
                
                # Check if segment complete
                if self._is_segment_complete():
                    self._finish_segment()
                    
                    # Start next segment if not stopping
                    if self.state != SessionState.STOPPING:
                        self.state = SessionState.WAITING
                        
        except Exception as e:
            logger.error(f"Error processing RTP packet: {e}", exc_info=True)
    
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
    
    def _start_segment(self, rtp_timestamp: int, wallclock: Optional[float]):
        """Start a new recording segment"""
        self.segment_counter += 1
        self.segment_sample_count = 0
        self.segment_start_rtp = rtp_timestamp
        
        # Determine start time
        start_time = wallclock if wallclock else time.time()
        
        self.current_segment = SegmentInfo(
            segment_id=self.segment_counter,
            start_time=start_time,
            start_rtp_timestamp=rtp_timestamp,
            wallclock_start=wallclock
        )
        
        # Get metadata from provider
        metadata = {}
        if self.metadata_provider:
            try:
                metadata = self.metadata_provider()
            except Exception as e:
                logger.warning(f"Metadata provider error: {e}")
        
        # Notify writer
        try:
            self.writer.start_segment(self.current_segment, metadata)
        except Exception as e:
            logger.error(f"Writer start_segment error: {e}", exc_info=True)
        
        self.state = SessionState.RECORDING
        
        logger.debug(f"Segment {self.segment_counter} started at RTP {rtp_timestamp}")
    
    def _write_samples(self, samples: np.ndarray, rtp_timestamp: int, 
                       gap_info: Optional[GapInfo]):
        """Write samples to current segment"""
        if not self.current_segment:
            return
        
        # Update segment stats
        self.current_segment.sample_count += len(samples)
        self.segment_sample_count += len(samples)
        
        if gap_info and gap_info.gap_samples > 0:
            self.current_segment.gap_count += 1
            self.current_segment.gap_samples += gap_info.gap_samples
            self.metrics.total_gaps += 1
            self.metrics.total_gap_samples += gap_info.gap_samples
        
        self.metrics.total_samples += len(samples)
        
        # Write to application writer
        try:
            self.writer.write_samples(samples, rtp_timestamp, gap_info)
        except Exception as e:
            logger.error(f"Writer write_samples error: {e}", exc_info=True)
    
    def _is_segment_complete(self) -> bool:
        """Check if current segment is complete"""
        if self.samples_per_segment is None:
            return False  # Continuous mode
        return self.segment_sample_count >= self.samples_per_segment
    
    def _finish_segment(self):
        """Finish current segment"""
        if not self.current_segment:
            return
        
        # Flush resequencer
        buffered = self.resequencer.flush()
        for samples, gap_info in buffered:
            self._write_samples(samples, 0, gap_info)
        
        # Notify writer
        result = None
        try:
            result = self.writer.finish_segment(self.current_segment)
        except Exception as e:
            logger.error(f"Writer finish_segment error: {e}", exc_info=True)
        
        # Update metrics
        self.metrics.segments_completed += 1
        reseq_stats = self.resequencer.get_stats()
        self.metrics.packets_resequenced = reseq_stats.get('packets_resequenced', 0)
        
        logger.info(
            f"Segment {self.current_segment.segment_id} complete: "
            f"{self.current_segment.sample_count} samples, "
            f"{self.current_segment.gap_count} gaps"
        )
        
        # Callback
        if self.on_segment_complete:
            try:
                self.on_segment_complete(self.current_segment, result)
            except Exception as e:
                logger.error(f"Segment complete callback error: {e}", exc_info=True)
        
        self.current_segment = None
    
    def update_channel_info(self, channel_info: ChannelInfo):
        """Update timing info (call when status stream refreshes)"""
        with self._lock:
            self.channel_info = channel_info
            self.rtp_receiver.update_channel_info(self.config.ssrc, channel_info)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current session metrics"""
        with self._lock:
            return self.metrics.to_dict()
    
    def get_state(self) -> SessionState:
        """Get current session state"""
        with self._lock:
            return self.state
