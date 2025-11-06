#!/usr/bin/env python3
"""Test with large buffer like the continuous test"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer
import wave, numpy as np

# Create a modified AudioStreamer that uses large buffer
class LargeBufferStreamer(AudioStreamer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.large_buffer = []
        self.buffer_filled = False
    
    def fill_buffer(self, duration=4.0):
        """Fill buffer with 4 seconds of data like continuous test"""
        print(f"Filling buffer for {duration} seconds...")
        start = time.time()
        
        while time.time() - start < duration:
            try:
                data, _ = self.socket.recvfrom(8192)
                iq_samples = self._parse_rtp_packet(data)
                if iq_samples is not None:
                    self.large_buffer.extend(iq_samples)
            except:
                continue
        
        self.buffer_filled = True
        print(f"Buffer filled: {len(self.large_buffer)} samples")
    
    def get_audio_chunk(self, timeout=1.0):
        """Get chunk from pre-filled buffer"""
        if not self.buffer_filled:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
        
        if len(self.large_buffer) < 640:
            silence = np.zeros(320, dtype=np.int16)
            return silence.tobytes()
        
        # Take exactly 640 samples
        samples_to_process = self.large_buffer[:640]
        self.large_buffer = self.large_buffer[640:]
        
        # Process
        iq_array = np.array(samples_to_process)
        audio_16k = self._demodulate(iq_array)
        audio_8k = audio_16k[::2]
        audio_int16 = (audio_8k * 32767).astype(np.int16)
        
        return audio_int16.tobytes()

# Test
streamer = LargeBufferStreamer('239.192.152.141', 5004, 'AM')
streamer.start()
streamer.fill_buffer(4.0)

# Get chunks
chunks = []
for i in range(100):
    chunk = streamer.get_audio_chunk()
    chunks.append(chunk)

streamer.stop()

# Save
all_data = b''.join(chunks)
with wave.open('/tmp/test-large-buffer.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_data)

print(f"Saved: /tmp/test-large-buffer.wav")
print(f"Duration: {len(all_data)//2/8000:.2f}s")
