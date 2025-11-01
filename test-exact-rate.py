#!/usr/bin/env python3
"""Precisely measure RTP rate and save test audio at correct rate"""
import socket, struct, numpy as np, time, wave

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', 5004))
mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

ssrc = 5000000
samples = []
start = time.time()
target = 5.0  # exactly 5 seconds

print(f"Capturing exactly {target} seconds...")

while time.time() - start < target:
    data, _ = sock.recvfrom(8192)
    if len(data) < 12:
        continue
    if struct.unpack('>I', data[8:12])[0] != ssrc:
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
    
    s = np.frombuffer(payload, dtype='>i2').reshape(-1, 2).astype(np.float32) / 32768.0
    iq = s[:, 1] + 1j * s[:, 0]
    samples.extend(iq)

sock.close()
elapsed = time.time() - start

samples = np.array(samples)
rate = len(samples) / elapsed

print(f"\nCaptured {len(samples)} complex IQ samples in {elapsed:.3f} seconds")
print(f"Complex IQ rate: {rate:.1f} Hz")

if 15500 < rate < 16500:
    print("→ Rate is ~16 kHz complex IQ")
    audio_rate = 16000
elif 7500 < rate < 8500:
    print("→ Rate is ~8 kHz complex IQ")
    audio_rate = 8000
else:
    print(f"→ Unexpected rate: {rate:.0f} Hz")
    audio_rate = int(rate)

# Save audio at CORRECT rate
audio = np.abs(samples) - np.mean(np.abs(samples))
audio = audio / np.max(np.abs(audio)) * 0.5
audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

with wave.open('/tmp/wwv-correct-rate.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(audio_rate)
    w.writeframes(audio_int16.tobytes())

print(f"\n✓ Saved audio at {audio_rate} Hz to /tmp/wwv-correct-rate.wav")
print(f"  Duration should be: {len(audio_int16)/audio_rate:.2f} seconds")
print(f"  Play with: aplay /tmp/wwv-correct-rate.wav")
