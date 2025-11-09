#!/usr/bin/env python3
"""
RTP Packet Resequencer - Handle Out-of-Order Delivery

Implements circular buffer for packet resequencing and gap detection.
Follows KA9Q timing architecture: RTP timestamps are primary reference.
"""

import numpy as np
import logging
from collections import deque
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RTPPacket:
    """Parsed RTP packet"""
    sequence: int           # RTP sequence number (16-bit, wraps)
    timestamp: int          # RTP timestamp (32-bit, wraps)
    ssrc: int              # RTP SSRC identifier
    samples: np.ndarray    # IQ samples (complex64)


@dataclass
class GapInfo:
    """Information about a detected gap"""
    expected_timestamp: int     # RTP timestamp we expected
    actual_timestamp: int       # RTP timestamp we received
    gap_samples: int           # Number of missing samples
    gap_packets: int           # Number of missing packets (estimate)
    prev_sequence: int         # Last good sequence number
    curr_sequence: int         # Current sequence number


class PacketResequencer:
    """
    Resequence out-of-order RTP packets and detect gaps
    
    Design:
    - Circular buffer of 64 packets (handles ~2 second jitter @ 320 samples/packet)
    - Process packets in sequence order
    - Detect gaps via RTP timestamp jumps
    - Fill gaps with zeros to maintain sample count integrity
    
    Key principle: Sample count integrity > real-time delivery
    """
    
    def __init__(self, buffer_size: int = 64, samples_per_packet: int = 320):
        """
        Initialize resequencer
        
        Args:
            buffer_size: Circular buffer size (packets)
            samples_per_packet: Expected samples per packet (320 @ 16 kHz)
        """
        self.buffer_size = buffer_size
        self.samples_per_packet = samples_per_packet
        
        # Circular buffer: sequence_num -> packet
        self.buffer: deque = deque(maxlen=buffer_size)
        self.buffer_seq_nums: set = set()  # Quick lookup
        
        # State tracking
        self.initialized = False
        self.next_expected_seq: Optional[int] = None
        self.next_expected_ts: Optional[int] = None
        self.last_output_ts: Optional[int] = None
        
        # Statistics
        self.packets_received = 0
        self.packets_resequenced = 0
        self.gaps_detected = 0
        self.samples_filled = 0
        
        logger.debug(f"PacketResequencer initialized: buffer={buffer_size}, samples/pkt={samples_per_packet}")
    
    def process_packet(self, packet: RTPPacket) -> Tuple[Optional[np.ndarray], Optional[GapInfo]]:
        """
        Process incoming RTP packet
        
        Args:
            packet: Parsed RTP packet
        
        Returns:
            (samples, gap_info) tuple:
            - samples: IQ samples ready for output (None if buffering)
            - gap_info: If gap detected, info about the gap
        """
        self.packets_received += 1
        
        # Initialize on first packet
        if not self.initialized:
            self._initialize(packet)
            return None, None  # Buffer first packet
        
        # Check for duplicate
        if packet.sequence in self.buffer_seq_nums:
            logger.debug(f"Duplicate packet seq={packet.sequence}, ignoring")
            return None, None
        
        # Add to buffer
        self._add_to_buffer(packet)
        
        # Try to output packets in sequence order
        return self._try_output()
    
    def _initialize(self, packet: RTPPacket):
        """Initialize sequencer with first packet"""
        self.next_expected_seq = packet.sequence
        self.next_expected_ts = packet.timestamp
        self.last_output_ts = packet.timestamp
        self._add_to_buffer(packet)
        self.initialized = True
        logger.info(f"Sequencer initialized: seq={packet.sequence}, ts={packet.timestamp}")
    
    def _add_to_buffer(self, packet: RTPPacket):
        """Add packet to circular buffer"""
        self.buffer.append(packet)
        self.buffer_seq_nums.add(packet.sequence)
        
        # If buffer full, remove oldest
        if len(self.buffer) > self.buffer_size:
            oldest = self.buffer.popleft()
            self.buffer_seq_nums.discard(oldest.sequence)
    
    def _try_output(self) -> Tuple[Optional[np.ndarray], Optional[GapInfo]]:
        """Try to output next packet in sequence"""
        # Look for next expected sequence number
        next_pkt = None
        for pkt in self.buffer:
            if pkt.sequence == self.next_expected_seq:
                next_pkt = pkt
                break
        
        if next_pkt is None:
            # Packet not in buffer yet - keep waiting
            # But check if we should give up (packet lost)
            if len(self.buffer) >= self.buffer_size // 2:
                # Buffer is filling up - probably lost packet
                # Output gap-fill and skip ahead
                return self._handle_lost_packet()
            else:
                # Keep waiting
                return None, None
        
        # Found next packet - check for gap
        gap_info = None
        gap_samples = None
        
        if next_pkt.timestamp != self.next_expected_ts:
            # RTP timestamp jump - gap detected!
            gap_info = self._detect_gap(next_pkt)
            gap_samples = self._create_gap_fill(gap_info)
            logger.warning(
                f"Gap detected: {gap_info.gap_samples} samples "
                f"({gap_info.gap_packets} packets), "
                f"ts {self.next_expected_ts} -> {next_pkt.timestamp}"
            )
        
        # Remove from buffer
        self.buffer.remove(next_pkt)
        self.buffer_seq_nums.discard(next_pkt.sequence)
        
        # Update state
        self.next_expected_seq = (next_pkt.sequence + 1) & 0xFFFF  # 16-bit wrap
        self.next_expected_ts = next_pkt.timestamp + self.samples_per_packet
        self.last_output_ts = next_pkt.timestamp
        
        # Return samples (gap-fill + packet data)
        if gap_samples is not None:
            # Concatenate gap fill + real samples
            output = np.concatenate([gap_samples, next_pkt.samples])
            return output, gap_info
        else:
            return next_pkt.samples, None
    
    def _detect_gap(self, next_pkt: RTPPacket) -> GapInfo:
        """Detect and characterize gap"""
        self.gaps_detected += 1
        
        # Calculate gap in RTP timestamp units (samples)
        ts_gap = next_pkt.timestamp - self.next_expected_ts
        
        # Handle timestamp wrap (32-bit)
        if ts_gap < 0:
            ts_gap += 2**32
        
        # Estimate packets lost
        packets_lost = ts_gap // self.samples_per_packet
        
        self.samples_filled += ts_gap
        
        return GapInfo(
            expected_timestamp=self.next_expected_ts,
            actual_timestamp=next_pkt.timestamp,
            gap_samples=ts_gap,
            gap_packets=packets_lost,
            prev_sequence=self.next_expected_seq - 1,
            curr_sequence=next_pkt.sequence
        )
    
    def _create_gap_fill(self, gap_info: GapInfo) -> np.ndarray:
        """Create zero-filled samples for gap"""
        return np.zeros(gap_info.gap_samples, dtype=np.complex64)
    
    def _handle_lost_packet(self) -> Tuple[Optional[np.ndarray], Optional[GapInfo]]:
        """Handle case where expected packet is lost"""
        # Find next available packet in buffer
        if len(self.buffer) == 0:
            return None, None
        
        # Get earliest packet by sequence (accounting for wrap)
        earliest_pkt = min(self.buffer, key=lambda p: self._seq_distance(self.next_expected_seq, p.sequence))
        
        # Create gap info
        gap_info = GapInfo(
            expected_timestamp=self.next_expected_ts,
            actual_timestamp=earliest_pkt.timestamp,
            gap_samples=earliest_pkt.timestamp - self.next_expected_ts,
            gap_packets=(earliest_pkt.sequence - self.next_expected_seq) & 0xFFFF,
            prev_sequence=(self.next_expected_seq - 1) & 0xFFFF,
            curr_sequence=earliest_pkt.sequence
        )
        
        # Create gap fill
        gap_samples = self._create_gap_fill(gap_info)
        
        # Remove packet from buffer
        self.buffer.remove(earliest_pkt)
        self.buffer_seq_nums.discard(earliest_pkt.sequence)
        
        # Update state
        self.next_expected_seq = (earliest_pkt.sequence + 1) & 0xFFFF
        self.next_expected_ts = earliest_pkt.timestamp + self.samples_per_packet
        self.last_output_ts = earliest_pkt.timestamp
        
        self.packets_resequenced += 1
        
        logger.warning(
            f"Lost packet recovery: skipped to seq={earliest_pkt.sequence}, "
            f"gap={gap_info.gap_samples} samples"
        )
        
        # Return gap fill + packet
        output = np.concatenate([gap_samples, earliest_pkt.samples])
        return output, gap_info
    
    def _seq_distance(self, from_seq: int, to_seq: int) -> int:
        """Calculate forward distance between sequence numbers (handles wrap)"""
        dist = (to_seq - from_seq) & 0xFFFF
        return dist if dist < 32768 else dist - 65536
    
    def flush(self) -> List[Tuple[np.ndarray, Optional[GapInfo]]]:
        """Flush remaining packets in buffer (for shutdown)"""
        results = []
        
        # Sort buffer by sequence number
        sorted_pkts = sorted(self.buffer, key=lambda p: p.sequence)
        
        for pkt in sorted_pkts:
            # Check for gap
            gap_info = None
            gap_samples = None
            
            if pkt.timestamp != self.next_expected_ts:
                gap_info = self._detect_gap(pkt)
                gap_samples = self._create_gap_fill(gap_info)
            
            # Update state
            self.next_expected_ts = pkt.timestamp + self.samples_per_packet
            
            # Add result
            if gap_samples is not None:
                output = np.concatenate([gap_samples, pkt.samples])
            else:
                output = pkt.samples
            
            results.append((output, gap_info))
        
        # Clear buffer
        self.buffer.clear()
        self.buffer_seq_nums.clear()
        
        return results
    
    def get_stats(self) -> dict:
        """Get resequencer statistics"""
        return {
            'packets_received': self.packets_received,
            'packets_resequenced': self.packets_resequenced,
            'gaps_detected': self.gaps_detected,
            'samples_filled': self.samples_filled,
            'buffer_used': len(self.buffer),
            'buffer_size': self.buffer_size
        }
