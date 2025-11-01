#!/usr/bin/env python3
"""Test 8 kHz decimated audio for web streaming"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer
import wave
import time

# Create audio streamer for WWV 5 MHz (SSRC 5000000)
streamer = AudioStreamer(
    multicast_address='239.192.152.141',
    multicast_port=5004,
    mode='AM',
    audio_rate=8000
)

print("Starting audio streamer...")
streamer.start()

# Collect audio chunks
chunks = []
target_duration = 5  # 5 seconds
chunks_needed = target_duration * 8000 // 320  # 320 samples per chunk @ 8kHz (640 IQ decimated)

print(f"Collecting {chunks_needed} chunks ({target_duration} seconds @ 8kHz)...")

for i in range(chunks_needed):
    chunk = streamer.get_audio_chunk(timeout=0.1)
    chunks.append(chunk)
    if (i+1) % 20 == 0:
        print(f"  {i+1}/{chunks_needed} chunks collected")

streamer.stop()

# Save to WAV
import numpy as np
all_data = b''.join(chunks)
audio_array = np.frombuffer(all_data, dtype=np.int16)

output_file = '/tmp/wwv-8khz-decimated.wav'
with wave.open(output_file, 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_data)

print(f"\n✓ Saved {len(audio_array)} samples to {output_file}")
print(f"  Duration: {len(audio_array)/8000:.2f} seconds")
print(f"  Sample rate: 8000 Hz")
print(f"\nPlay with: aplay {output_file}")
print("\nThis is the same audio the browser receives!")
