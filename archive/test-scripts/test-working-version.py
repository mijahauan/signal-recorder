#!/usr/bin/env python3
"""Test the working continuous processing AudioStreamer"""
import sys, os, time, wave
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer_working import AudioStreamer

streamer = AudioStreamer('239.192.152.141', 5004, 'AM')
streamer.start()

# Wait for buffer to fill
print("Waiting for buffer to fill...")
time.sleep(3)

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
with wave.open('/tmp/test-working-version.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_data)

print(f"\n✓ Saved to /tmp/test-working-version.wav")
print(f"  Duration: {len(all_data)//2/8000:.2f} seconds")
print("\nThis should be smooth and intelligible!")
print("Play with: aplay /tmp/test-working-version.wav")
