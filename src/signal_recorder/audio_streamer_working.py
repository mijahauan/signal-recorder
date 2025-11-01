"""
Working Audio Streamer - Continuous processing for smooth, intelligible audio

This version processes audio continuously to avoid chunk boundary artifacts.
Accepts 2-second latency for perfectly smooth playback.
"""

import socket
import struct
import time
import threading
import logging
import numpy as np
from queue import Queue, Full

logger = logging.getLogger(__name__)


class AudioStreamer:
    """
    Stream audio with continuous processing for smooth playback
    """
    
    def __init__(self, multicast_address, multicast_port, mode='AM', audio_rate=8000):
        self.multicast_address = multicast_address
        self.multicast_port = multicast_port
        self.mode = mode
        self.audio_rate = audio_rate
        
        # Audio queue
        self.audio_queue = Queue(maxsize=100)
        
        # RTP state
        self.socket = None
        self.running = False
        self.thread = None
        self.iq_sample_rate = 16000
        self.output_audio_rate = 8000
        
        # Continuous processing buffers
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        
        logger.info(f"Audio streamer initialized: {multicast_address}:{multicast_port} "
                   f"mode={mode}, continuous processing with 2s latency")
    
    def start(self):
        """Start receiving and streaming audio"""
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
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        
        logger.info(f"Audio streamer started: {self.multicast_address}:{self.multicast_port}")
    
    def stop(self):
        """Stop audio streaming"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.socket:
            self.socket.close()
        logger.info("Audio streamer stopped")
    
    def _receive_loop(self):
        """Continuous packet reception and processing"""
        # Fill initial buffer
        print("Building 2-second buffer for smooth audio...")
        buffer_start = time.time()
        
        while self.running and (time.time() - buffer_start) < 2.5:
            try:
                data, _ = self.socket.recvfrom(8192)
                iq_samples = self._parse_rtp_packet(data)
                if iq_samples is not None:
                    with self.buffer_lock:
                        # Process immediately to maintain continuity
                        new_audio = self._demodulate(np.array(iq_samples))
                        self.audio_buffer.extend(new_audio)
            except:
                continue
        
        print(f"Buffer ready: {len(self.audio_buffer)} audio samples")
        
        # Continue receiving and processing
        while self.running:
            try:
                data, _ = self.socket.recvfrom(8192)
                iq_samples = self._parse_rtp_packet(data)
                if iq_samples is not None:
                    with self.buffer_lock:
                        # Process immediately
                        new_audio = self._demodulate(np.array(iq_samples))
                        self.audio_buffer.extend(new_audio)
                        
                        # Generate chunks when we have enough
                        while len(self.audio_buffer) >= 640:
                            chunk_audio = self.audio_buffer[:640]
                            self.audio_buffer = self.audio_buffer[640:]
                            
                            # Decimate to 8kHz
                            chunk_8k = np.array(chunk_audio[::2])
                            audio_int16 = (chunk_8k * 32767).astype(np.int16)
                            
                            # Add to queue
                            try:
                                self.audio_queue.put(audio_int16.tobytes(), block=False)
                            except Full:
                                try:
                                    self.audio_queue.get_nowait()
                                    self.audio_queue.put(audio_int16.tobytes(), block=False)
                                except:
                                    pass
                                    
            except Exception as e:
                if self.running:
                    logger.error(f"Error in receive loop: {e}")
    
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
        elif self.mode == 'FM':
            phase = np.angle(iq_samples)
            audio = np.diff(phase)
            audio = np.append(audio, 0)
            return audio
        else:
            return np.abs(iq_samples)
    
    def get_audio_chunk(self, timeout=1.0):
        """Get next audio chunk from queue"""
        try:
            return self.audio_queue.get(timeout=timeout)
        except:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
