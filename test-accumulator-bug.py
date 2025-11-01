#!/usr/bin/env python3
"""Test if the accumulator logic is the problem"""
import socket, struct, numpy as np, wave, time

ssrc = 5000000
duration = 5

print("Capturing IQ...")
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', 5004))
mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

# Capture all packets first
all_packets = []
start = time.time()

while time.time() - start < duration:
    data, _ = sock.recvfrom(8192)
    if len(data) < 12:
        continue
        
    pkt_ssrc = struct.unpack('>I', data[8:12])[0]
    if pkt_ssrc != ssrc:
        continue
    
    header_byte0 = data[0]
    csrc_count = header_byte0 & 0x0F
    has_extension = (header_byte0 & 0x10) != 0
    payload_offset = 12 + (csrc_count * 4)
    if has_extension and len(data) >= payload_offset + 4:
        ext_length_words = struct.unpack('>H', data[payload_offset+2:payload_offset+4])[0]
        payload_offset += 4 + (ext_length_words * 4)
    
    payload = data[payload_offset:]
    if len(payload) % 4 != 0:
        continue
    
    samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
    samples = samples_int16.astype(np.float32) / 32768.0
    iq = samples[:, 1] + 1j * samples[:, 0]
    
    all_packets.append(iq)

sock.close()

print(f"Captured {len(all_packets)} packets")

# Test 1: Process all at once (should work)
all_iq = np.concatenate(all_packets)
audio_all = np.abs(all_iq)
audio_all = audio_all / np.max(audio_all) * 0.5
audio_all_8k = audio_all[::2]
audio_int16 = (audio_all_8k * 32767).astype(np.int16)

with wave.open('/tmp/test-all-at-once.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(audio_int16.tobytes())

print("Saved: /tmp/test-all-at-once.wav (should be smooth)")

# Test 2: Process in 640-sample chunks using accumulator (like AudioStreamer)
audio_chunks = []
sample_accumulator = []

for packet_iq in all_packets:
    sample_accumulator.append(packet_iq)
    accumulated = sum(len(s) for s in sample_accumulator)
    
    if accumulated >= 640:
        all_samples = np.concatenate(sample_accumulator)
        samples_to_process = all_samples[:640]
        remainder = all_samples[640:]
        
        # Reset accumulator with remainder
        if len(remainder) > 0:
            sample_accumulator = [remainder]
        else:
            sample_accumulator = []
        
        # Process chunk
        audio_chunk = np.abs(samples_to_process)
        audio_chunk = audio_chunk * 0.5
        audio_chunk_8k = audio_chunk[::2]
        audio_chunk_int16 = (audio_chunk_8k * 32767).astype(np.int16)
        audio_chunks.append(audio_chunk_int16)

all_chunked = np.concatenate(audio_chunks)

with wave.open('/tmp/test-with-accumulator.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_chunked.tobytes())

print("Saved: /tmp/test-with-accumulator.wav (like AudioStreamer)")

# Test 3: Process in exact 2-packet chunks (no accumulator)
audio_chunks2 = []

for i in range(0, len(all_packets) - 1, 2):
    if i + 1 < len(all_packets):
        chunk_iq = np.concatenate([all_packets[i], all_packets[i+1]])
        audio_chunk = np.abs(chunk_iq)
        audio_chunk = audio_chunk * 0.5
        audio_chunk_8k = audio_chunk[::2]
        audio_chunk_int16 = (audio_chunk_8k * 32767).astype(np.int16)
        audio_chunks2.append(audio_chunk_int16)

all_chunked2 = np.concatenate(audio_chunks2)

with wave.open('/tmp/test-exact-pairs.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_chunked2.tobytes())

print("Saved: /tmp/test-exact-pairs.wav (no accumulator)")

print("\n" + "="*60)
print("COMPARE:")
print("1. /tmp/test-all-at-once.wav - Should be smooth")
print("2. /tmp/test-with-accumulator.wav - If choppy, accumulator is the problem")
print("3. /tmp/test-exact-pairs.wav - If smooth, accumulator logic is buggy")
print("="*60)
