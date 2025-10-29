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
        self.rtp_sample_rate = 16000  # WWV channels are 16 kHz IQ
        self.output_audio_rate = 8000  # Decimate to 8 kHz for audio output
        
        logger.info(f"Audio streamer initialized: {multicast_address}:{multicast_port} "
                   f"mode={mode}, rtp_rate=16kHz, output_rate=8kHz")
    
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
                
                # Parse RTP header (skip for now, just get payload)
                payload = data[12:]  # Skip 12-byte RTP header
                
                # Unpack IQ samples (int16 interleaved I/Q)
                if len(payload) % 4 != 0:
                    continue
                
                samples_int16 = np.frombuffer(payload, dtype=np.int16).reshape(-1, 2)
                samples = samples_int16.astype(np.float32) / 32768.0
                iq_samples = samples[:, 0] + 1j * samples[:, 1]
                
                # Accumulate samples
                sample_accumulator.append(iq_samples)
                
                # Process when we have enough (e.g., 1600 samples @ 16kHz = 100ms)
                accumulated = sum(len(s) for s in sample_accumulator)
                if accumulated >= 1600:
                    all_samples = np.concatenate(sample_accumulator)
                    sample_accumulator = []
                    
                    # Demodulate to audio at 16 kHz
                    audio_16k = self._demodulate(all_samples)
                    
                    # Decimate from 16 kHz to 8 kHz (factor of 2)
                    audio_8k = scipy_signal.decimate(audio_16k, 2, ftype='fir')
                    
                    if len(audio_8k) > 0:
                        # Convert to int16 PCM
                        audio_int16 = (audio_8k * 32767).astype(np.int16)
                        
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
            # AM: magnitude of IQ (envelope detection)
            envelope = np.abs(iq_samples)
            
            # Remove DC component to extract modulation (audio)
            audio = envelope - np.mean(envelope)
            
            # Apply audio bandpass filter (300-3000 Hz for voice)
            # This removes sub-audio rumble and high-frequency noise
            sos = scipy_signal.butter(4, [300, 3000], btype='band', fs=16000, output='sos')
            audio = scipy_signal.sosfilt(sos, audio)
            
            # Normalize to prevent clipping
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio = audio / max_val * 0.8  # Leave headroom
            
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
