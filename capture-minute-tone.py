#!/usr/bin/env python3
"""Capture WWV audio at minute boundary and analyze for 1000 Hz tone"""
import socket, struct, numpy as np, time, wave
from scipy import signal as scipy_signal

def capture_minute_boundary(ssrc=5000000):
    """Wait for :55 and capture through :05 to get the minute marker tone"""
    print("Waiting for :55 seconds...")
    while int(time.time()) % 60 != 55:
        time.sleep(0.1)
    
    print("Capturing from :55 to :05 (10 seconds)...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    all_samples = []
    start_time = time.time()
    
    while len(all_samples) < 80000:  # 10 seconds @ 8 kHz
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
        iq_samples = samples[:, 1] + 1j * samples[:, 0]  # Q + jI
        
        all_samples.extend(iq_samples)
    
    sock.close()
    all_samples = np.array(all_samples[:80000])
    
    return all_samples, start_time

def analyze_for_tone(iq_samples, start_time):
    """Analyze for 1000 Hz tone at minute boundary"""
    # Resample to 3 kHz
    sos_lp = scipy_signal.butter(8, 1500, btype='low', fs=8000, output='sos')
    resampled = scipy_signal.sosfilt(sos_lp, iq_samples)[::2]
    resampled = resampled[::1]  # Approximately 3 kHz
    
    # AM demodulation
    am_audio = np.abs(resampled)
    am_audio_dc = am_audio - np.mean(am_audio)
    
    print(f"\n=== AM AUDIO @ 3 kHz ===")
    print(f"Length: {len(am_audio)} samples ({len(am_audio)/3000:.1f}s)")
    print(f"AM magnitude range: {np.min(am_audio):.6f} to {np.max(am_audio):.6f}")
    print(f"AM mean: {np.mean(am_audio):.6f}, std: {np.std(am_audio):.6f}")
    
    # Apply 1000 Hz bandpass filter
    sos_1k = scipy_signal.butter(4, [950, 1050], btype='band', fs=3000, output='sos')
    filtered_1k = scipy_signal.sosfiltfilt(sos_1k, am_audio_dc)
    
    print(f"\n=== AFTER 1000 Hz BANDPASS ===")
    print(f"Filtered range: {np.min(filtered_1k):.6f} to {np.max(filtered_1k):.6f}")
    print(f"Filtered RMS: {np.sqrt(np.mean(filtered_1k**2)):.6f}")
    
    # Envelope detection
    analytic = scipy_signal.hilbert(filtered_1k)
    envelope = np.abs(analytic)
    envelope_norm = envelope / np.max(envelope) if np.max(envelope) > 0 else envelope
    
    print(f"\n=== 1000 Hz ENVELOPE ===")
    print(f"Max envelope: {np.max(envelope):.6f}")
    print(f"Mean envelope: {np.mean(envelope):.6f}")
    print(f"95th percentile: {np.percentile(envelope, 95):.6f}")
    
    # Find sections above 15% threshold
    above_15 = envelope_norm > 0.15
    edges = np.diff(above_15.astype(int))
    rising = np.where(edges == 1)[0]
    falling = np.where(edges == -1)[0]
    
    print(f"\nRising edges: {len(rising)}, Falling edges: {len(falling)}")
    
    # Analyze each detection
    if len(rising) > 0 and len(falling) > 0:
        print(f"\nDetected tone bursts (15% threshold):")
        for i, r in enumerate(rising[:10]):  # First 10
            f_candidates = falling[falling > r]
            if len(f_candidates) > 0:
                f = f_candidates[0]
                duration = (f - r) / 3000
                time_offset = r / 3000
                minute_second = (start_time + time_offset) % 60
                print(f"  {i+1}. Duration: {duration:.3f}s, at +{time_offset:.1f}s (:mm:{int(minute_second):02d}.{int((minute_second%1)*10)})")
    
    # Save audio for listening
    audio_8k = np.abs(iq_samples)
    audio_8k = audio_8k - np.mean(audio_8k)
    max_val = np.max(np.abs(audio_8k))
    if max_val > 0:
        audio_8k = audio_8k / max_val * 0.5
    audio_int16 = np.clip(audio_8k * 32767, -32768, 32767).astype(np.int16)
    
    with wave.open('/tmp/wwv-minute-marker.wav', 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(audio_int16.tobytes())
    
    print(f"\n✓ Audio saved to /tmp/wwv-minute-marker.wav")
    print(f"  Play with: aplay /tmp/wwv-minute-marker.wav")
    print(f"  You should hear the 1000 Hz tone at :00 seconds (5 seconds into the file)")

if __name__ == '__main__':
    import sys
    ssrc = int(sys.argv[1]) if len(sys.argv) > 1 else 5000000
    iq, start = capture_minute_boundary(ssrc)
    analyze_for_tone(iq, start)
