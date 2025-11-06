#!/usr/bin/env python3
"""Test AudioStreamer methods on exact same data as continuous test"""
import sys, os, time, socket, struct, numpy as np, wave
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer

# Capture the exact same data as continuous test
def capture_data():
    ssrc = 5000000
    duration = 4
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    all_samples = []
    start = time.time()
    
    while time.time() - start < duration:
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
            
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        # Parse RTP (same as AudioStreamer)
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
        
        all_samples.extend(iq)
    
    sock.close()
    return np.array(all_samples)

print("Capturing data...")
all_iq = capture_data()
print(f"Captured {len(all_iq)} IQ samples")

# Create AudioStreamer instance to use its methods
streamer = AudioStreamer('239.192.152.141', 5004, 'AM')

# Test 1: Use AudioStreamer._demodulate on chunks
print("\n=== Test 1: AudioStreamer._demodulate on chunks ===")
audio_chunks = []

for i in range(0, len(all_iq) - 640 + 1, 640):
    chunk_iq = all_iq[i:i+640]
    audio_16k = streamer._demodulate(chunk_iq)
    audio_8k = audio_16k[::2]
    audio_int16 = (audio_8k * 32767).astype(np.int16)
    audio_chunks.append(audio_int16)

all_audio1 = np.concatenate(audio_chunks)

with wave.open('/tmp/test-streamer-methods.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_audio1.tobytes())

print("Saved: /tmp/test-streamer-methods.wav")

# Test 2: Direct processing (like continuous test)
print("\n=== Test 2: Direct processing (like continuous) ===")
audio_direct = np.abs(all_iq)
audio_direct = audio_direct * 3.0
audio_direct_8k = audio_direct[::2]
audio_direct_int16 = (audio_direct_8k * 32767).astype(np.int16)

# Chunk it after processing
audio_chunks2 = []
for i in range(0, len(audio_direct_int16) - 320 + 1, 320):
    audio_chunks2.append(audio_direct_int16[i:i+320])

all_audio2 = np.concatenate(audio_chunks2)

with wave.open('/tmp/test-direct-chunked.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_audio2.tobytes())

print("Saved: /tmp/test-direct-chunked.wav")

print("\n" + "="*60)
print("COMPARE:")
print("1. /tmp/test-streamer-methods.wav - Using AudioStreamer methods")
print("2. /tmp/test-direct-chunked.wav - Direct processing then chunked")
print("If #1 is choppy and #2 is smooth, the issue is in _demodulate!")
print("="*60)
