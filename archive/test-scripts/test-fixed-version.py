#!/usr/bin/env python3
"""Test the fixed AudioStreamer with buffering"""
import sys, os, time, wave, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer_fixed import AudioStreamer

streamer = AudioStreamer('239.192.152.141', 5004, 'AM')
streamer.start()

# Wait for buffer to fill
time.sleep(4)

# Collect chunks
chunks = []
for i in range(100):
    chunk = streamer.get_audio_chunk()
    chunks.append(chunk)
    if (i+1) % 20 == 0:
        print(f"  {i+1}/100 chunks collected")

streamer.stop()

# Save
all_data = b''.join(chunks)
with wave.open('/tmp/test-fixed-version.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_data)

print(f"\n✓ Saved to /tmp/test-fixed-version.wav")
print(f"  Duration: {len(all_data)//2/8000:.2f} seconds")
print("\nPlay with: aplay /tmp/test-fixed-version.wav")
