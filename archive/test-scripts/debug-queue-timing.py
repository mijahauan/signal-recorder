#!/usr/bin/env python3
"""Debug why we're getting too many chunks"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer

streamer = AudioStreamer(
    multicast_address='239.192.152.141',
    multicast_port=5004,
    mode='AM',
    audio_rate=8000
)

print("Starting streamer...")
streamer.start()
time.sleep(0.5)  # Let buffer fill

# Count chunks for 4 seconds
start = time.time()
chunk_count = 0
while time.time() - start < 4.0:
    chunk = streamer.get_audio_chunk(timeout=0.1)
    if chunk:
        chunk_count += 1
        if chunk_count <= 10:
            print(f"Chunk {chunk_count}: {len(chunk)} bytes")
    else:
        print("Got empty chunk")

streamer.stop()

print(f"\nIn 4 seconds, got {chunk_count} chunks")
print(f"Expected: 4s * 25 chunks/s = 100 chunks")
print(f"Actual rate: {chunk_count/4:.1f} chunks/sec")

if chunk_count > 100:
    print("\n⚠️  TOO MANY CHUNKS - AudioStreamer is overproducing!")
    print("This means chunks are smaller or more frequent than expected")
