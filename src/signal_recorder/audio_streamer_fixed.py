"""
Fixed Audio Streamer - Processes with delay for smooth playback

This version pre-buffers 2 seconds of data, then processes it smoothly.
The trade-off is 2-second latency for perfectly smooth audio.
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
    Stream audio from KA9Q radio with buffering for smooth playback
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
        
        # Buffer for smooth playback
        self.sample_buffer = []
        self.buffer_size = 16000 * 3  # 3 seconds at 16kHz
        self.buffer_ready = False
        
        logger.info(f"Audio streamer initialized: {multicast_address}:{multicast_port} "
                   f"mode={mode}, buffer=3s delay")
    
    def start(self):
        """Start receiving and buffering audio"""
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
        
        # Fill initial buffer
        print("Filling 3-second buffer for smooth playback...")
        start_time = time.time()
        while len(self.sample_buffer) < self.buffer_size and (time.time() - start_time) < 10.0:
            try:
                data, _ = self.socket.recvfrom(8192)
                iq_samples = self._parse_rtp_packet(data)
                if iq_samples is not None:
                    self.sample_buffer.extend(iq_samples)
            except:
                continue
        
        if len(self.sample_buffer) >= self.buffer_size:
            self.buffer_ready = True
            print(f"Buffer ready: {len(self.sample_buffer)} samples")
        else:
            print("Warning: Could not fill buffer completely")
        
        logger.info(f"Audio streamer started with {len(self.sample_buffer)} samples buffered")
    
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
        """Get next audio chunk from buffer"""
        if not self.running or not self.buffer_ready:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
        
        # Add new packets to buffer (non-blocking)
        try:
            self.socket.setblocking(False)
            while True:
                try:
                    data, _ = self.socket.recvfrom(8192)
                    iq_samples = self._parse_rtp_packet(data)
                    if iq_samples is not None:
                        self.sample_buffer.extend(iq_samples)
                except socket.error:
                    break
        finally:
            self.socket.setblocking(True)
        
        # Check if we have enough samples
        if len(self.sample_buffer) < 640:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
        
        # Process chunk
        samples_to_process = self.sample_buffer[:640]
        self.sample_buffer = self.sample_buffer[640:]
        
        iq_array = np.array(samples_to_process)
        audio_16k = self._demodulate(iq_array)
        
        if len(audio_16k) == 0:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
        
        audio_8k = audio_16k[::2]
        audio_int16 = (audio_8k * 32767).astype(np.int16)
        
        return audio_int16.tobytes()
