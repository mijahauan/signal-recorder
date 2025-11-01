"""
Continuous Audio Streamer - Processes signal continuously, chunks only for output

This maintains the continuous nature of the signal throughout processing.
"""

import socket
import struct
import time
import logging
import numpy as np
from scipy import signal as scipy_signal

logger = logging.getLogger(__name__)


class AudioStreamer:
    """
    Stream audio with continuous processing to avoid chunk boundary artifacts
    """
    
    def __init__(self, multicast_address, multicast_port, mode='AM', audio_rate=8000):
        self.multicast_address = multicast_address
        self.multicast_port = multicast_port
        self.mode = mode
        self.audio_rate = audio_rate
        
        # RTP state
        self.socket = None
        self.running = False
        self.iq_sample_rate = 16000
        self.output_audio_rate = 8000
        
        # Continuous processing buffer
        self.iq_buffer = []
        self.audio_buffer = []
        self.processing_position = 0
        
        logger.info(f"Audio streamer initialized: {multicast_address}:{multicast_port} "
                   f"mode={mode}, continuous processing")
    
    def start(self):
        """Start receiving audio"""
        if self.running:
            return
        
        # Create socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Join multicast
        mreq = struct.pack('4sl', socket.inet_aton(self.multicast_address), socket.INADDR_ANY)
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.socket.bind(('', self.multicast_port))
        
        self.running = True
        logger.info(f"Audio streamer started: {self.multicast_address}:{self.multicast_port}")
    
    def stop(self):
        """Stop streaming"""
        self.running = False
        if self.socket:
            self.socket.close()
        logger.info("Audio streamer stopped")
    
    def _parse_rtp_packet(self, data):
        """Parse RTP packet and return IQ samples"""
        if len(data) < 12:
            return None
        
        header_byte0 = data[0]
        csrc_count = header_byte0 & 0x0F
        has_extension = (header_byte0 & 0x10) != 0
        
        payload_offset = 12 + (csrc_count * 4)
        if has_extension and len(data) >= payload_offset + 4:
            ext_length_words = struct.unpack('>H', data[payload_offset+2:payload_offset+4])[0]
            payload_offset += 4 + (ext_length_words * 4)
        
        if payload_offset >= len(data):
            return None
        
        payload = data[payload_offset:]
        if len(payload) % 4 != 0:
            return None
        
        samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
        samples = samples_int16.astype(np.float32) / 32768.0
        iq_samples = samples[:, 1] + 1j * samples[:, 0]
        
        return iq_samples
    
    def _demodulate(self, iq_samples):
        """Demodulate IQ to audio"""
        if self.mode == 'AM':
            envelope = np.abs(iq_samples)
            audio = envelope * 3.0
            return audio
        elif self.mode == 'USB':
            return iq_samples.real
        elif self.mode == 'LSB':
            return (-iq_samples).real
        else:
            return np.abs(iq_samples)
    
    def get_audio_chunk(self, timeout=1.0):
        """Get next audio chunk with continuous processing"""
        if not self.running or not self.socket:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
        
        # Collect new packets
        try:
            self.socket.setblocking(False)
            while True:
                try:
                    data, _ = self.socket.recvfrom(8192)
                    iq_samples = self._parse_rtp_packet(data)
                    if iq_samples is not None:
                        # Add to IQ buffer
                        self.iq_buffer.extend(iq_samples)
                        
                        # Process new samples continuously
                        new_audio = self._demodulate(np.array(iq_samples))
                        self.audio_buffer.extend(new_audio)
                        
                except socket.error:
                    break
        finally:
            self.socket.setblocking(True)
        
        # Check if we have enough processed audio for a chunk
        needed_samples = 640  # 640 at 16kHz = 320 at 8kHz after decimation
        
        if len(self.audio_buffer) < needed_samples:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
        
        # Take continuous chunk from processed audio
        chunk_audio = self.audio_buffer[:needed_samples]
        self.audio_buffer = self.audio_buffer[needed_samples:]
        
        # Decimate to 8kHz
        chunk_8k = np.array(chunk_audio[::2])
        
        # Convert to int16
        audio_int16 = (chunk_8k * 32767).astype(np.int16)
        
        return audio_int16.tobytes()
