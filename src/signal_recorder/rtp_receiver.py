#!/usr/bin/env python3
"""
Generic RTP Receiver

Receives RTP packets from multicast and demultiplexes by SSRC.
Designed for reuse across different applications.

This module was extracted from grape_rtp_recorder.py to provide
a generic, application-independent RTP reception capability.
"""

import socket
import struct
import threading
import logging
from typing import Dict, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RTPHeader:
    """Parsed RTP header fields"""
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
    Receives RTP packets from multicast and demultiplexes by SSRC.
    
    This is a generic RTP receiver that can be used for any application
    requiring multicast RTP reception. Callbacks are registered per-SSRC
    to handle different streams independently.
    
    Example:
        receiver = RTPReceiver('239.192.152.141', port=5004)
        receiver.register_callback(ssrc=10000000, callback=my_handler)
        receiver.start()
        # ... later ...
        receiver.stop()
    """
    
    def __init__(self, multicast_address: str, port: int = 5004):
        """
        Initialize RTP receiver.
        
        Args:
            multicast_address: Multicast group address to join
            port: RTP port (default 5004)
        """
        self.multicast_address = multicast_address
        self.port = port
        self.running = False
        self.socket = None
        self.thread = None
        self.callbacks: Dict[int, Callable] = {}  # ssrc -> callback
        
    def register_callback(self, ssrc: int, callback: Callable):
        """
        Register callback for specific SSRC.
        
        Args:
            ssrc: RTP SSRC identifier
            callback: Function to call with (RTPHeader, payload_bytes)
        """
        self.callbacks[ssrc] = callback
        logger.info(f"Registered callback for SSRC {ssrc}")
        
    def unregister_callback(self, ssrc: int):
        """
        Unregister callback for specific SSRC.
        
        Args:
            ssrc: RTP SSRC identifier to remove
        """
        if ssrc in self.callbacks:
            del self.callbacks[ssrc]
            logger.info(f"Unregistered callback for SSRC {ssrc}")
        
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
        """
        Parse RTP packet header.
        
        Args:
            data: Raw packet bytes
            
        Returns:
            RTPHeader if valid, None otherwise
        """
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
