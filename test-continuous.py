#!/usr/bin/env python3
"""Test continuous processing without chunk boundaries"""
import sys, os, time, socket, struct, numpy as np, wave
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Create a continuous processor
def continuous_processor():
    ssrc = 5000000
    duration = 4
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    print("Starting continuous processing...")
    
    # Collect all samples first (like offline tests)
    all_samples = []
    start = time.time()
    
    while time.time() - start < duration:
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
            
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        # Parse RTP
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
    
    print(f"Collected {len(all_samples)} IQ samples")
    
    # Now process in chunks but from the continuous buffer
    audio_chunks = []
    
    for i in range(0, len(all_samples) - 640 + 1, 640):
        chunk_samples = all_samples[i:i+640]
        
        # Process exactly like AudioStreamer
        audio = np.abs(chunk_samples)
        audio = audio * 0.5
        audio_8k = audio[::2]
        audio_int16 = (audio_8k * 32767).astype(np.int16)
        
        audio_chunks.append(audio_int16)
    
    all_audio = np.concatenate(audio_chunks)
    
    with wave.open('/tmp/test-continuous.wav', 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(all_audio.tobytes())
    
    print(f"Saved: /tmp/test-continuous.wav")
    print(f"Chunks: {len(audio_chunks)}, Duration: {len(all_audio)/8000:.2f}s")

continuous_processor()
