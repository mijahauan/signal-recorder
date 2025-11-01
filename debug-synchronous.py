#!/usr/bin/env python3
"""Debug synchronous processing with packet tracking"""
import sys, os, time, socket, struct, numpy as np, wave
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer

# Monkey patch to track packets
original_parse = AudioStreamer._parse_rtp_packet
packet_count = 0
total_samples = []

def debug_parse(self, data):
    global packet_count
    iq = original_parse(self, data)
    if iq is not None:
        packet_count += 1
        total_samples.append(len(iq))
        if packet_count <= 10:
            print(f"Packet {packet_count}: {len(iq)} samples")
    return iq

AudioStreamer._parse_rtp_packet = debug_parse

# Test
streamer = AudioStreamer('239.192.152.141', 5004, 'AM')
streamer.start()

chunks = []
for i in range(100):
    chunk = streamer.get_audio_chunk(timeout=0.1)
    chunks.append(chunk)
    if i == 0:
        print(f"\nFirst chunk: {len(chunk)} bytes")

streamer.stop()

print(f"\nTotal packets processed: {packet_count}")
print(f"Samples per packet: {set(total_samples[:10]) if total_samples else 'None'}")

# Save
all_data = b''.join(chunks)
with wave.open('/tmp/debug-sync.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_data)

print(f"\nSaved: /tmp/debug-sync.wav")
print(f"Duration: {len(all_data)//2/8000:.2f}s")
