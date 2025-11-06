#!/usr/bin/env python3
"""Test if chunked processing itself causes choppiness"""
import socket, struct, numpy as np, wave, time

ssrc = 5000000
duration = 5

print("Capturing IQ...")
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', 5004))
mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

all_iq = []
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
    all_iq.extend(iq)

sock.close()
all_iq = np.array(all_iq)

print(f"Collected {len(all_iq)} IQ samples\n")

# Test 1: Process all at once (like test-simple-am-16k.wav - this works)
print("=== Test 1: All at once (like test-simple-am-16k.wav) ===")
audio_all = np.abs(all_iq)
audio_all = audio_all / np.max(audio_all) * 0.5
audio_all_8k = audio_all[::2]
audio_int16 = (audio_all_8k * 32767).astype(np.int16)

with wave.open('/tmp/test-all-at-once.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(audio_int16.tobytes())
print("Saved: /tmp/test-all-at-once.wav")

# Test 2: Process in chunks of 640, THEN normalize and decimate
print("\n=== Test 2: Chunked processing (640 IQ samples/chunk) ===")
chunk_size = 640
audio_chunks = []

for i in range(0, len(all_iq), chunk_size):
    chunk_iq = all_iq[i:i+chunk_size]
    if len(chunk_iq) < chunk_size:
        break  # Skip incomplete chunk
    
    # Process exactly like audio_streamer.py
    envelope = np.abs(chunk_iq)
    audio_16k = envelope * 2.0
    audio_8k_chunk = audio_16k[::2]
    audio_limited = np.tanh(audio_8k_chunk)
    audio_int16_chunk = (audio_limited * 32767).astype(np.int16)
    
    audio_chunks.append(audio_int16_chunk)

all_chunked = np.concatenate(audio_chunks)

with wave.open('/tmp/test-chunked.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_chunked.tobytes())
print("Saved: /tmp/test-chunked.wav")

print("\n" + "="*60)
print("COMPARE IN AUDACITY:")
print("1. /tmp/test-all-at-once.wav - Should be smooth")
print("2. /tmp/test-chunked.wav     - If choppy, chunking is the problem")
print("="*60)
