"""
HTTP Audio Streaming for KA9Q Radio Channels

Provides live audio streaming from multicast RTP channels.
Inspired by ka9q-web but implemented in Python for simplicity.
"""

import socket
import struct
import threading
import logging
from queue import Queue, Full
import numpy as np
from scipy import signal as scipy_signal

logger = logging.getLogger(__name__)


class AudioStreamer:
    """
    Stream audio from a KA9Q radio multicast channel
    
    Receives RTP IQ data, demodulates to audio, and provides
    audio chunks for HTTP streaming.
    """
    
    def __init__(self, multicast_address, multicast_port, mode='AM', audio_rate=12000):
        """
        Args:
            multicast_address: Multicast IP address for the channel
            multicast_port: Multicast port
            mode: Demodulation mode ('AM', 'USB', 'LSB', 'FM')
            audio_rate: Output audio sample rate (Hz)
        """
        self.multicast_address = multicast_address
        self.multicast_port = multicast_port
        self.mode = mode
        self.audio_rate = audio_rate
        
        # Audio buffer queue
        self.audio_queue = Queue(maxsize=100)  # ~2 seconds @ 8kHz with 256-sample chunks
        
        # RTP state
        self.socket = None
        self.running = False
        self.thread = None
        # Note: Radiod sample_rate=16000 means 16k REAL samples = 8k COMPLEX IQ samples
        self.iq_sample_rate = 8000  # Complex IQ sample rate
        self.output_audio_rate = 8000  # Output audio rate (no decimation needed!)
        
        logger.info(f"Audio streamer initialized: {multicast_address}:{multicast_port} "
                   f"mode={mode}, iq_rate=8kHz complex, output_rate=8kHz")
    
    def start(self):
        """Start receiving and streaming audio"""
        if self.running:
            return
        
        # Create multicast socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind to multicast group
        self.socket.bind(('', self.multicast_port))
        mreq = struct.pack('4sl', socket.inet_aton(self.multicast_address), socket.INADDR_ANY)
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        # Start receiver thread
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        
        logger.info(f"Audio streamer started: {self.multicast_address}:{self.multicast_port}")
    
    def stop(self):
        """Stop streaming"""
        self.running = False
        if self.socket:
            self.socket.close()
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info(f"Audio streamer stopped: {self.multicast_address}:{self.multicast_port}")
    
    def _receive_loop(self):
        """Main RTP receive loop"""
        sample_accumulator = []
        
        while self.running:
            try:
                # Receive RTP packet
                data, addr = self.socket.recvfrom(8192)
                
                if len(data) < 12:
                    continue  # Too short for RTP header
                
                # Parse RTP header to calculate correct payload offset
                # RTP header format:
                #   Byte 0: V(2) P(1) X(1) CC(4)
                #   Byte 1: M(1) PT(7)
                #   Bytes 2-3: Sequence number
                #   Bytes 4-7: Timestamp
                #   Bytes 8-11: SSRC
                #   + Optional CSRC list (CC * 4 bytes)
                #   + Optional extension header (if X=1)
                
                header_byte0 = data[0]
                csrc_count = header_byte0 & 0x0F  # Lower 4 bits
                has_extension = (header_byte0 & 0x10) != 0  # X bit
                
                # Start after fixed 12-byte header + CSRC list
                payload_offset = 12 + (csrc_count * 4)
                
                # Handle extension header if present
                if has_extension and len(data) >= payload_offset + 4:
                    # Extension header: 2 bytes profile + 2 bytes length (in 32-bit words)
                    ext_length_words = struct.unpack('>H', data[payload_offset+2:payload_offset+4])[0]
                    payload_offset += 4 + (ext_length_words * 4)
                
                if payload_offset >= len(data):
                    continue  # Malformed packet
                
                payload = data[payload_offset:]
                
                # Unpack IQ samples (int16 I/Q pairs from KA9Q radio)
                # Each IQ sample = 2 int16 values (I and Q) = 4 bytes
                # CRITICAL: RTP payloads use network byte order (BIG-ENDIAN)
                if len(payload) % 4 != 0:
                    continue
                
                samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)  # Big-endian!
                samples = samples_int16.astype(np.float32) / 32768.0
                # CRITICAL: KA9Q sends Q,I pairs (not I,Q) for proper phase
                # Use Q + jI to get carrier centered at DC
                iq_samples = samples[:, 1] + 1j * samples[:, 0]  # Q + jI
                
                # Accumulate samples
                sample_accumulator.append(iq_samples)
                
                # Process when we have enough (e.g., 1600 samples @ 8kHz = 200ms for balanced latency/smoothness)
                accumulated = sum(len(s) for s in sample_accumulator)
                if accumulated >= 1600:
                    all_samples = np.concatenate(sample_accumulator)
                    sample_accumulator = []
                    
                    # Demodulate IQ to audio (both at 8 kHz, no decimation needed)
                    audio = self._demodulate(all_samples)
                    
                    if len(audio) > 0:
                        # Clamp to [-1, 1] and convert to int16 PCM
                        audio_clamped = np.clip(audio, -1.0, 1.0)
                        audio_int16 = (audio_clamped * 32767).astype(np.int16)
                        
                        # Add to queue (drop if full)
                        try:
                            self.audio_queue.put(audio_int16.tobytes(), block=False)
                        except Full:
                            # Drop oldest chunk
                            try:
                                self.audio_queue.get_nowait()
                                self.audio_queue.put(audio_int16.tobytes(), block=False)
                            except:
                                pass
            
            except Exception as e:
                if self.running:
                    logger.error(f"Error in audio receive loop: {e}")
    
    def _demodulate(self, iq_samples):
        """Demodulate IQ to audio based on mode"""
        if self.mode == 'AM':
            # For radiod "iq" preset: baseband IQ with carrier at DC
            # AM demodulation: simple envelope detection (magnitude)
            envelope = np.abs(iq_samples)
            
            # Remove DC and normalize in one pass for efficiency
            audio = envelope - np.mean(envelope)
            
            # Simple normalization using max value for speed
            max_val = np.max(np.abs(audio))
            if max_val > 0.001:
                audio = audio / max_val * 0.5  # Normalize to 50% to leave headroom
            
            return audio
        
        elif self.mode == 'USB':
            # USB: real part only (upper sideband)
            return iq_samples.real
        
        elif self.mode == 'LSB':
            # LSB: real part, but conjugate first
            return (-iq_samples).real
        
        elif self.mode == 'FM':
            # FM: instantaneous frequency (phase derivative)
            phase = np.angle(iq_samples)
            audio = np.diff(phase)
            audio = np.append(audio, 0)  # Pad to same length
            return audio
        
        else:
            # Default to AM
            return np.abs(iq_samples)
    
    def get_audio_chunk(self, timeout=1.0):
        """
        Get next audio chunk for streaming
        
        Returns:
            bytes: PCM audio data (int16, mono)
        """
        try:
            return self.audio_queue.get(timeout=timeout)
        except:
            # Return silence if no data
            silence = np.zeros(256, dtype=np.int16)
            return silence.tobytes()
