"""
Direct control of radiod via TLV command protocol

This module sends commands directly to radiod's control socket using the
TLV (Type-Length-Value) protocol, based on ka9q-radio's status.c encoding.
"""

import socket
import struct
import random
import logging
from typing import Optional
from .control_discovery import discover_channels_via_control

logger = logging.getLogger(__name__)


# Status types from ka9q-radio/src/status.h
# These MUST match the enum values in status.h exactly!
class StatusType:
    EOL = 0
    COMMAND_TAG = 1
    CMD_CNT = 2
    GPS_TIME = 3
    DESCRIPTION = 4
    STATUS_DEST_SOCKET = 5
    SETOPTS = 6
    CLEAROPTS = 7
    RTP_TIMESNAP = 8
    UNUSED4 = 9
    INPUT_SAMPRATE = 10
    UNUSED6 = 11
    UNUSED7 = 12
    INPUT_SAMPLES = 13
    UNUSED8 = 14
    UNUSED9 = 15
    OUTPUT_DATA_SOURCE_SOCKET = 16
    OUTPUT_DATA_DEST_SOCKET = 17
    OUTPUT_SSRC = 18  # Was 14 - WRONG!
    OUTPUT_TTL = 19
    OUTPUT_SAMPRATE = 20  # Was 16 - WRONG!
    OUTPUT_METADATA_PACKETS = 21
    OUTPUT_DATA_PACKETS = 22
    OUTPUT_ERRORS = 23
    CALIBRATE = 24
    LNA_GAIN = 25
    MIXER_GAIN = 26
    IF_GAIN = 27
    DC_I_OFFSET = 28
    DC_Q_OFFSET = 29
    IQ_IMBALANCE = 30
    IQ_PHASE = 31
    DIRECT_CONVERSION = 32
    RADIO_FREQUENCY = 33  # Was 25 - WRONG!
    FIRST_LO_FREQUENCY = 34
    SECOND_LO_FREQUENCY = 35
    SHIFT_FREQUENCY = 36
    DOPPLER_FREQUENCY = 37
    DOPPLER_FREQUENCY_RATE = 38
    LOW_EDGE = 39  # Was 42 - WRONG!
    HIGH_EDGE = 40  # Was 43 - WRONG!
    KAISER_BETA = 41
    FILTER_BLOCKSIZE = 42
    FILTER_FIR_LENGTH = 43
    FILTER2 = 44
    # ... (skipping many intermediate values)
    PRESET = 87  # Was 29 - COMPLETELY WRONG!


# Command packet type
CMD = 1


def encode_int64(buf: bytearray, type_val: int, x: int) -> int:
    """
    Encode a 64-bit integer in TLV format
    
    Format: [type:1][length:1][value:variable]
    Value is big-endian, with leading zeros compressed
    """
    buf.append(type_val)
    
    if x == 0:
        # Compress zero to zero length
        buf.append(0)
        return 2
    
    # Convert to bytes and remove leading zeros
    x_bytes = x.to_bytes(8, byteorder='big')
    # Find first non-zero byte
    start = 0
    while start < len(x_bytes) and x_bytes[start] == 0:
        start += 1
    
    value_bytes = x_bytes[start:]
    length = len(value_bytes)
    
    buf.append(length)
    buf.extend(value_bytes)
    
    return 2 + length


def encode_int(buf: bytearray, type_val: int, x: int) -> int:
    """Encode an integer"""
    return encode_int64(buf, type_val, x)


def encode_double(buf: bytearray, type_val: int, x: float) -> int:
    """
    Encode a double (float64) in TLV format
    
    The float is converted to its IEEE 754 representation and encoded as int64
    """
    # Pack as double, unpack as uint64
    packed = struct.pack('>d', x)  # big-endian double
    value = struct.unpack('>Q', packed)[0]  # big-endian uint64
    return encode_int64(buf, type_val, value)


def encode_float(buf: bytearray, type_val: int, x: float) -> int:
    """
    Encode a float (float32) in TLV format
    """
    # Pack as float, unpack as uint32
    packed = struct.pack('>f', x)  # big-endian float
    value = struct.unpack('>I', packed)[0]  # big-endian uint32
    return encode_int64(buf, type_val, value)


def encode_string(buf: bytearray, type_val: int, s: str) -> int:
    """
    Encode a string in TLV format
    """
    buf.append(type_val)
    
    s_bytes = s.encode('utf-8')
    length = len(s_bytes)
    
    if length < 128:
        buf.append(length)
    elif length < 65536:
        # Multi-byte length encoding
        buf.append(0x80 | (length >> 8))
        buf.append(length & 0xff)
    else:
        raise ValueError(f"String too long: {length} bytes")
    
    buf.extend(s_bytes)
    return 2 + length


def encode_eol(buf: bytearray) -> int:
    """Encode end-of-list marker"""
    buf.append(StatusType.EOL)
    return 1


class RadiodControl:
    """
    Control interface for radiod
    
    Sends TLV-encoded commands to radiod's control socket to create
    and configure channels.
    """
    
    def __init__(self, status_address: str):
        """
        Initialize radiod control
        
        Args:
            status_address: mDNS name or IP:port of radiod status stream
        """
        self.status_address = status_address
        self.socket = None
        self._connect()
    
    def _connect(self):
        """Connect to radiod control socket"""
        # Resolve the status address
        import subprocess
        import re
        
        try:
            # Check if it's already an IP address
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', self.status_address):
                mcast_addr = self.status_address
                logger.info(f"Using direct IP address: {mcast_addr}")
            else:
                # Try avahi-resolve first
                try:
                    result = subprocess.run(
                        ['avahi-resolve', '-n', self.status_address],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        # Parse output: "hostname    ip_address"
                        parts = result.stdout.strip().split()
                        if len(parts) >= 2:
                            mcast_addr = parts[1]
                        else:
                            raise ValueError(f"Unexpected avahi-resolve output: {result.stdout}")
                    else:
                        raise ValueError(f"avahi-resolve failed: {result.stderr}")
                except (subprocess.TimeoutExpired, FileNotFoundError, ValueError) as e:
                    # Try getaddrinfo as fallback
                    logger.warning(f"avahi-resolve failed ({e}), trying getaddrinfo")
                    import socket as sock
                    addr_info = sock.getaddrinfo(self.status_address, None, sock.AF_INET, sock.SOCK_DGRAM)
                    mcast_addr = addr_info[0][4][0]
            
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Allow multiple sockets to bind to the same port
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Set socket options for multicast
            # Use loopback interface with proper ip_mreqn structure
            # This is critical - we need to specify BOTH the IP and interface index
            import struct
            # Get loopback interface index
            lo_index = socket.if_nametoindex('lo')
            # Create ip_mreqn structure matching ka9q-radio's setup_ipv4_loopback:
            # struct ip_mreqn { imr_multiaddr (4 bytes), imr_address (4 bytes), imr_ifindex (4 bytes) }
            # imr_address = 127.0.0.1 (INADDR_LOOPBACK), imr_ifindex = loopback interface
            # Note: imr_multiaddr is not used for IP_MULTICAST_IF, can be 0
            mreqn = struct.pack('=4sIi',  # Use 'I' for network byte order uint32
                               b'\x00\x00\x00\x00',  # imr_multiaddr (not used)
                               socket.htonl(0x7F000001),  # imr_address = 127.0.0.1 in network byte order
                               lo_index)  # imr_ifindex (loopback interface index)
            logger.debug(f"Setting IP_MULTICAST_IF with ip_mreqn: lo_index={lo_index}, mreqn={mreqn.hex()}")
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, mreqn)
            logger.debug(f"IP_MULTICAST_IF set successfully")
            
            # Join the multicast group (required for sending on some systems)
            # This matches what ka9q-radio's control utility does
            mreq = struct.pack('=4s4s', 
                              socket.inet_aton(mcast_addr),  # multicast group address
                              socket.inet_aton('127.0.0.1'))  # interface address (loopback)
            try:
                self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                logger.debug(f"Joined multicast group {mcast_addr} on 127.0.0.1")
            except OSError as e:
                # EADDRINUSE is not fatal - group already joined
                if e.errno != 98:  # EADDRINUSE
                    logger.warning(f"Failed to join multicast group: {e}")
            
            # Enable multicast loopback so we can send to ourselves
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            # Set TTL for multicast packets
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            
            self.dest_addr = (mcast_addr, 5006)  # Standard radiod control port
            
            logger.info(f"Connected to radiod at {mcast_addr}:5006 via loopback")
            logger.debug(f"Socket options: REUSEADDR=1, MULTICAST_IF=127.0.0.1, MULTICAST_LOOP=1, MULTICAST_TTL=2")
            
        except Exception as e:
            logger.error(f"Failed to connect to radiod: {e}")
            raise
    
    def send_command(self, cmdbuffer: bytearray):
        """Send a command packet to radiod"""
        if not self.socket:
            raise RuntimeError("Not connected to radiod")
        
        try:
            # Log hex dump of the command
            hex_dump = ' '.join(f'{b:02x}' for b in cmdbuffer)
            logger.debug(f"Sending {len(cmdbuffer)} bytes to {self.dest_addr}: {hex_dump}")
            
            sent = self.socket.sendto(bytes(cmdbuffer), self.dest_addr)
            logger.debug(f"Sent {sent} bytes to radiod")
            return sent
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            raise
    
    def set_frequency(self, ssrc: int, frequency_hz: float):
        """
        Set the frequency of a channel
        
        Args:
            ssrc: SSRC of the channel
            frequency_hz: Frequency in Hz
        """
        cmdbuffer = bytearray()
        cmdbuffer.append(CMD)  # Command packet type
        
        encode_double(cmdbuffer, StatusType.RADIO_FREQUENCY, frequency_hz)
        encode_int(cmdbuffer, StatusType.OUTPUT_SSRC, ssrc)
        encode_int(cmdbuffer, StatusType.COMMAND_TAG, random.randint(1, 2**31))
        encode_eol(cmdbuffer)
        
        logger.info(f"Setting frequency for SSRC {ssrc} to {frequency_hz/1e6:.3f} MHz")
        self.send_command(cmdbuffer)
    
    def set_preset(self, ssrc: int, preset: str):
        """
        Set the preset (mode) of a channel
        
        Args:
            ssrc: SSRC of the channel
            preset: Preset name (e.g., "iq", "usb", "lsb")
        """
        cmdbuffer = bytearray()
        cmdbuffer.append(CMD)
        
        encode_string(cmdbuffer, StatusType.PRESET, preset)
        encode_int(cmdbuffer, StatusType.OUTPUT_SSRC, ssrc)
        encode_int(cmdbuffer, StatusType.COMMAND_TAG, random.randint(1, 2**31))
        encode_eol(cmdbuffer)
        
        logger.info(f"Setting preset for SSRC {ssrc} to {preset}")
        self.send_command(cmdbuffer)
    
    def set_sample_rate(self, ssrc: int, sample_rate: int):
        """
        Set the sample rate of a channel
        
        Args:
            ssrc: SSRC of the channel
            sample_rate: Sample rate in Hz
        """
        cmdbuffer = bytearray()
        cmdbuffer.append(CMD)
        
        encode_int(cmdbuffer, StatusType.OUTPUT_SAMPRATE, sample_rate)
        encode_int(cmdbuffer, StatusType.OUTPUT_SSRC, ssrc)
        encode_int(cmdbuffer, StatusType.COMMAND_TAG, random.randint(1, 2**31))
        encode_eol(cmdbuffer)
        
        logger.info(f"Setting sample rate for SSRC {ssrc} to {sample_rate} Hz")
        self.send_command(cmdbuffer)
    
    def create_and_configure_channel(self, ssrc: int, frequency_hz: float, 
                                     preset: str = "iq", sample_rate: Optional[int] = None):
        """
        Create a new channel and configure it
        
        This sends commands to create the SSRC and set its parameters.
        Note: radiod will create the channel when it receives the first command
        for a new SSRC.
        
        Args:
            ssrc: SSRC for the new channel
            frequency_hz: Frequency in Hz
            preset: Preset/mode (default: "iq")
            sample_rate: Sample rate in Hz (optional)
        """
        logger.info(f"Creating channel: SSRC={ssrc}, freq={frequency_hz/1e6:.3f} MHz, preset={preset}")
        
        # Set frequency (this will create the channel if it doesn't exist)
        self.set_frequency(ssrc, frequency_hz)
        
        # Wait a moment for radiod to process
        import time
        time.sleep(0.1)
        
        # Set preset
        self.set_preset(ssrc, preset)
        time.sleep(0.1)
        
        # Set sample rate if specified
        if sample_rate:
            self.set_sample_rate(ssrc, sample_rate)
            time.sleep(0.1)
        
        logger.info(f"Channel {ssrc} created and configured")
    
    def verify_channel(self, ssrc: int, expected_freq: Optional[float] = None) -> bool:
        """
        Verify that a channel exists and is configured correctly
        
        Args:
            ssrc: SSRC to verify
            expected_freq: Expected frequency in Hz (optional)
        
        Returns:
            True if channel exists and matches expectations
        """
        # Discover current channels
        channels = discover_channels_via_control(self.status_address)
        
        if ssrc not in channels:
            logger.warning(f"Channel {ssrc} not found")
            return False
        
        channel = channels[ssrc]
        
        if expected_freq and abs(channel.frequency - expected_freq) > 1:  # 1 Hz tolerance
            logger.warning(
                f"Channel {ssrc} frequency mismatch: "
                f"expected {expected_freq/1e6:.3f} MHz, "
                f"got {channel.frequency/1e6:.3f} MHz"
            )
            return False
        
        logger.info(f"Channel {ssrc} verified: {channel.frequency/1e6:.3f} MHz, {channel.preset}")
        return True
    
    def close(self):
        """Close the control socket"""
        if self.socket:
            self.socket.close()
            self.socket = None

