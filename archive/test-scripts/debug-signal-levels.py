#!/usr/bin/env python3
"""Debug signal levels - check if we're seeing the WWV signal at all"""
import socket, struct, numpy as np
import time

def check_signal_levels(ssrc=5000000, duration=5):
    """Check raw IQ signal levels"""
    print(f"Checking signal levels for SSRC {ssrc}...")
    
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
        
        # Parse payload offset
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
    
    all_samples = np.array(all_samples)
    
    # Analyze signal
    print(f"\n=== RAW IQ SAMPLES ===")
    print(f"Samples collected: {len(all_samples)}")
    print(f"IQ magnitude min: {np.min(np.abs(all_samples)):.6f}")
    print(f"IQ magnitude max: {np.max(np.abs(all_samples)):.6f}")
    print(f"IQ magnitude mean: {np.mean(np.abs(all_samples)):.6f}")
    print(f"IQ magnitude std: {np.std(np.abs(all_samples)):.6f}")
    
    # AM demodulation
    envelope = np.abs(all_samples)
    print(f"\n=== AM ENVELOPE (magnitude) ===")
    print(f"Envelope min: {np.min(envelope):.6f}")
    print(f"Envelope max: {np.max(envelope):.6f}")
    print(f"Envelope mean: {np.mean(envelope):.6f}")
    print(f"Envelope std: {np.std(envelope):.6f}")
    
    # DC removed
    env_dc_removed = envelope - np.mean(envelope)
    print(f"\n=== AFTER DC REMOVAL ===")
    print(f"DC-removed min: {np.min(env_dc_removed):.6f}")
    print(f"DC-removed max: {np.max(env_dc_removed):.6f}")
    print(f"DC-removed mean: {np.mean(env_dc_removed):.6f}")
    print(f"DC-removed std: {np.std(env_dc_removed):.6f}")
    
    # Check signal strength percentiles
    print(f"\n=== ENVELOPE PERCENTILES ===")
    print(f"1%:   {np.percentile(envelope, 1):.6f}")
    print(f"50%:  {np.percentile(envelope, 50):.6f}")
    print(f"99%:  {np.percentile(envelope, 99):.6f}")
    print(f"99.9%: {np.percentile(envelope, 99.9):.6f}")
    
    # Simple 1000 Hz tone test
    from scipy import signal as scipy_signal
    
    # Resample to 3 kHz
    sos_lp = scipy_signal.butter(8, 1500, btype='low', fs=8000, output='sos')
    filtered_3k = scipy_signal.sosfilt(sos_lp, all_samples)[::2]
    filtered_3k = filtered_3k[::1]  # Keep close to 3 kHz
    
    # AM demod on resampled
    am_3k = np.abs(filtered_3k)
    am_3k_dc = am_3k - np.mean(am_3k)
    
    # 1000 Hz filter
    sos_1k = scipy_signal.butter(4, [950, 1050], btype='band', fs=3000, output='sos')
    tone_1k = scipy_signal.sosfiltfilt(sos_1k, am_3k_dc)
    
    # Envelope of 1000 Hz component
    tone_env = np.abs(scipy_signal.hilbert(tone_1k))
    
    print(f"\n=== 1000 Hz TONE COMPONENT @ 3 kHz ===")
    print(f"Tone envelope max: {np.max(tone_env):.6f}")
    print(f"Tone envelope mean: {np.mean(tone_env):.6f}")
    print(f"Tone envelope 99%: {np.percentile(tone_env, 99):.6f}")
    
    # Normalized
    if np.max(tone_env) > 0:
        tone_env_norm = tone_env / np.max(tone_env)
        above_15pct = np.sum(tone_env_norm > 0.15) / len(tone_env_norm) * 100
        above_30pct = np.sum(tone_env_norm > 0.30) / len(tone_env_norm) * 100
        print(f"\nNormalized tone envelope:")
        print(f"  > 15% threshold: {above_15pct:.1f}% of samples")
        print(f"  > 30% threshold: {above_30pct:.1f}% of samples")

if __name__ == '__main__':
    import sys
    ssrc = int(sys.argv[1]) if len(sys.argv) > 1 else 5000000
    check_signal_levels(ssrc, duration=5)
