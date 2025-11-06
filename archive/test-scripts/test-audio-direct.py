#!/usr/bin/env python3
"""
Quick audio test - capture RTP directly and save to WAV
This bypasses the web UI to test if the audio processing itself works
"""
import socket, struct, numpy as np, wave, sys

def test_audio_capture(ssrc=5000000, duration_sec=5):
    """Capture audio and save to WAV file"""
    print(f"Capturing {duration_sec} seconds from SSRC {ssrc}...")
    
    # Setup socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    # Collect samples
    all_audio = []
    target_samples = 8000 * duration_sec
    packet_count = 0
    
    while len(all_audio) < target_samples:
        data, _ = sock.recvfrom(8192)
        
        if len(data) < 12:
            continue
            
        # Check SSRC
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        packet_count += 1
        
        # Parse RTP header to find payload
        header_byte0 = data[0]
        csrc_count = header_byte0 & 0x0F
        has_extension = (header_byte0 & 0x10) != 0
        
        payload_offset = 12 + (csrc_count * 4)
        
        if has_extension and len(data) >= payload_offset + 4:
            ext_length_words = struct.unpack('>H', data[payload_offset+2:payload_offset+4])[0]
            payload_offset += 4 + (ext_length_words * 4)
        
        if payload_offset >= len(data):
            continue
        
        payload = data[payload_offset:]
        
        # Parse IQ samples
        if len(payload) % 4 != 0:
            continue
        
        samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
        samples = samples_int16.astype(np.float32) / 32768.0
        iq_samples = samples[:, 1] + 1j * samples[:, 0]  # Q + jI
        
        # AM demodulation
        envelope = np.abs(iq_samples)
        audio = envelope - np.mean(envelope)
        
        # Normalize
        max_val = np.max(np.abs(audio))
        if max_val > 0.001:
            audio = audio / max_val * 0.5
        
        all_audio.extend(audio)
        
        if packet_count % 100 == 0:
            print(f"  Packets: {packet_count}, samples: {len(all_audio)}")
    
    sock.close()
    
    # Convert to int16 and save
    audio_array = np.array(all_audio[:target_samples], dtype=np.float32)
    audio_int16 = np.clip(audio_array * 32767, -32768, 32767).astype(np.int16)
    
    output_file = '/tmp/wwv-audio-test.wav'
    with wave.open(output_file, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(audio_int16.tobytes())
    
    print(f"\n✓ Saved to {output_file}")
    print(f"  Duration: {len(audio_int16)/8000:.1f} seconds")
    print(f"  Packets received: {packet_count}")
    print(f"  Sample range: {np.min(audio_array):.4f} to {np.max(audio_array):.4f}")
    print("\nPlay with: aplay /tmp/wwv-audio-test.wav")

if __name__ == '__main__':
    ssrc = int(sys.argv[1]) if len(sys.argv) > 1 else 5000000
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    test_audio_capture(ssrc, duration)
