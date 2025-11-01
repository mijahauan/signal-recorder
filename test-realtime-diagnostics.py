#!/usr/bin/env python3
"""Diagnose real-time audio streaming to find choppiness cause"""
import sys, os, time, wave
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer

streamer = AudioStreamer(
    multicast_address='239.192.152.141',
    multicast_port=5004,
    mode='AM',
    audio_rate=8000
)

print("Starting audio streamer...")
streamer.start()

# Give it time to fill buffer
time.sleep(0.5)

# Collect chunks and measure timing
chunks = []
chunk_times = []
chunk_sizes = []

start = time.time()
for i in range(100):
    before = time.time()
    chunk = streamer.get_audio_chunk(timeout=0.1)
    after = time.time()
    
    chunks.append(chunk)
    chunk_times.append(after - before)
    chunk_sizes.append(len(chunk) // 2)  # int16 = 2 bytes per sample

streamer.stop()

# Analyze timing
chunk_times = np.array(chunk_times)
chunk_sizes = np.array(chunk_sizes)

print(f"\n=== CHUNK TIMING ANALYSIS ===")
print(f"Total chunks: {len(chunks)}")
print(f"Chunk sizes: min={np.min(chunk_sizes)}, max={np.max(chunk_sizes)}, unique={np.unique(chunk_sizes)}")
print(f"\nget_audio_chunk() latency:")
print(f"  Mean: {np.mean(chunk_times)*1000:.2f} ms")
print(f"  Min:  {np.min(chunk_times)*1000:.2f} ms")
print(f"  Max:  {np.max(chunk_times)*1000:.2f} ms")
print(f"  Std:  {np.std(chunk_times)*1000:.2f} ms")

# Check for delays
slow_chunks = chunk_times > 0.05  # >50ms is slow
if np.any(slow_chunks):
    print(f"\n⚠️  {np.sum(slow_chunks)} chunks took >50ms (should be ~40ms)")
    print(f"  Indices: {np.where(slow_chunks)[0][:10]}")

# Save audio
all_data = b''.join(chunks)
with wave.open('/tmp/realtime-test.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_data)

print(f"\n✓ Saved to /tmp/realtime-test.wav")
print(f"  Total samples: {len(all_data) // 2}")
print(f"  Duration: {len(all_data) // 2 / 8000:.2f}s")

# Check if all chunks are same size
if len(np.unique(chunk_sizes)) == 1:
    print(f"\n✓ All chunks same size: {chunk_sizes[0]} samples")
else:
    print(f"\n⚠️  Variable chunk sizes: {np.unique(chunk_sizes)}")
