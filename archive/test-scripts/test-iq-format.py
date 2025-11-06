#!/usr/bin/env python3
"""Test if IQ format is the issue"""
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
    
    # Test 1: Q + jI (current)
    iq_qji = samples[:, 1] + 1j * samples[:, 0]
    
    # Test 2: I + jQ (alternative)
    iq_ijq = samples[:, 0] + 1j * samples[:, 1]
    
    # Test 3: Just use magnitude directly (no complex)
    mag = np.sqrt(samples[:, 0]**2 + samples[:, 1]**2)
    
    all_iq.append((iq_qji, iq_ijq, mag))

sock.close()

print(f"\nCollected {len(all_iq)} packets")

# Process each format
formats = [
    ("Q+jI (current)", np.concatenate([iq[0] for iq in all_iq])),
    ("I+jQ (alternative)", np.concatenate([iq[1] for iq in all_iq])),
    ("Magnitude (no complex)", np.concatenate([iq[2] for iq in all_iq]))
]

for name, iq in formats:
    print(f"\n=== Testing {name} ===")
    
    # Simple AM demodulation
    if "Magnitude" in name:
        audio = iq  # Already magnitude
    else:
        audio = np.abs(iq)
    
    # Normalize
    audio = audio / np.max(audio) * 0.5
    
    # Decimate to 8kHz
    audio_8k = audio[::2]
    audio_int16 = (audio_8k * 32767).astype(np.int16)
    
    filename = f"/tmp/test-{name.replace(' ', '_').replace('(', '').replace(')', '').replace('/', '_')}.wav"
    with wave.open(filename, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(audio_int16.tobytes())
    
    print(f"Saved: {filename}")

print("\n" + "="*60)
print("TEST ALL THREE FILES:")
print("1. /tmp/test-Q_jI_current.wav")
print("2. /tmp/test-I_jQ_alternative.wav") 
print("3. /tmp/test-Magnitude_no_complex.wav")
print("="*60)
