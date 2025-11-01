#!/usr/bin/env python3
"""Test RAW IQ and simple AM demodulation without any processing"""
import socket, struct, numpy as np, wave, time

ssrc = 5000000
duration = 5

print("Capturing RAW IQ...")
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
    
    # Parse payload
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
    iq = samples[:, 1] + 1j * samples[:, 0]  # Q + jI
    
    all_iq.extend(iq)

sock.close()

all_iq = np.array(all_iq)

print(f"\nCollected {len(all_iq)} IQ samples")
print(f"Rate: {len(all_iq)/duration:.0f} Hz")

# Test 1: Simplest possible AM demodulation
print("\n=== Test 1: ABSOLUTE SIMPLEST AM (just magnitude) ===")
audio_simple = np.abs(all_iq)
audio_simple = audio_simple / np.max(audio_simple) * 0.5
audio_int16 = (audio_simple * 32767).astype(np.int16)

with wave.open('/tmp/test-simple-am-16k.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(audio_int16.tobytes())

print("Saved: /tmp/test-simple-am-16k.wav (16 kHz, no DC removal, no decimation)")

# Test 2: With basic DC removal
print("\n=== Test 2: With DC removal ===")
audio_dc = np.abs(all_iq)
audio_dc = audio_dc - np.mean(audio_dc)  # Simple DC removal on FULL file
audio_dc = audio_dc / np.max(np.abs(audio_dc)) * 0.5
audio_int16 = (audio_dc * 32767).astype(np.int16)

with wave.open('/tmp/test-dc-removed-16k.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(audio_int16.tobytes())

print("Saved: /tmp/test-dc-removed-16k.wav (16 kHz, DC removed)")

# Test 3: Decimated to 8kHz
print("\n=== Test 3: Decimated to 8 kHz ===")
audio_8k = audio_dc[::2]  # Simple decimation
audio_int16 = (audio_8k * 32767).astype(np.int16)

with wave.open('/tmp/test-decimated-8k.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(audio_int16.tobytes())

print("Saved: /tmp/test-decimated-8k.wav (8 kHz, DC removed, decimated)")

print("\n" + "="*60)
print("TEST IN AUDACITY:")
print("1. /tmp/test-simple-am-16k.wav  - If this is choppy, ka9q stream is bad")
print("2. /tmp/test-dc-removed-16k.wav - If this is choppy, DC removal is bad")
print("3. /tmp/test-decimated-8k.wav   - If this is choppy, decimation is bad")
print("="*60)
