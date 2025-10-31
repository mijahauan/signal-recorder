#!/usr/bin/env python3
"""
Test AM Preset (SSRC 1000) vs IQ Preset (SSRC 5000000)

Compare if the AM preset shows 100 Hz tone that IQ preset is missing.
"""

import socket
import struct
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal as scipy_signal

def capture_ssrc(ssrc, duration=5):
    """Capture audio/IQ from specific SSRC"""
    print(f"Capturing {duration}s from SSRC {ssrc}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    samples_list = []
    packets_captured = 0
    target_packets = duration * 100  # ~100 packets/sec
    
    while packets_captured < target_packets:
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
        
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        payload = data[12:]
        if len(payload) % 4 == 0 and len(payload) > 0:
            # Parse as int16 pairs
            samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
            samples_norm = samples_int16.astype(np.float32) / 32768.0
            
            if ssrc == 1000:
                # AM preset: mono audio, treat as one channel
                audio = samples_norm[:, 0]
                samples_list.append(audio)
            else:
                # IQ preset: complex IQ
                iq = samples_norm[:, 1] + 1j * samples_norm[:, 0]  # Q + jI
                samples_list.append(iq)
            
            packets_captured += 1
    
    sock.close()
    
    all_samples = np.concatenate(samples_list)
    print(f"Captured {len(all_samples)} samples from {packets_captured} packets")
    return all_samples

def plot_spectrum(samples, sample_rate, title):
    """Plot power spectrum"""
    # Use longer FFT for better frequency resolution
    f, Pxx = scipy_signal.welch(samples, fs=sample_rate, nperseg=8192, scaling='density')
    Pxx_dB = 10 * np.log10(Pxx + 1e-12)
    
    plt.figure(figsize=(14, 5))
    plt.plot(f, Pxx_dB, linewidth=0.5)
    plt.axvline(0, color='red', linestyle='--', alpha=0.5, linewidth=2, label='DC')
    plt.axvline(100, color='green', linestyle='--', alpha=0.5, linewidth=1, label='+100 Hz')
    plt.axvline(-100, color='blue', linestyle='--', alpha=0.5, linewidth=1, label='-100 Hz')
    plt.xlim(-4000, 4000)
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Power (dB)')
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend()
    
    # Find peaks near ±100 Hz
    pos_band = np.where((f >= 75) & (f <= 125))[0]
    neg_band = np.where((f >= -125) & (f <= -75))[0]
    
    if len(pos_band) > 0:
        pos_power = np.max(Pxx_dB[pos_band])
        pos_freq = f[pos_band[np.argmax(Pxx_dB[pos_band])]]
        print(f"  Peak near +100 Hz: {pos_power:.1f} dB at {pos_freq:.1f} Hz")
    
    if len(neg_band) > 0:
        neg_power = np.max(Pxx_dB[neg_band])
        neg_freq = f[neg_band[np.argmax(Pxx_dB[neg_band])]]
        print(f"  Peak near -100 Hz: {neg_power:.1f} dB at {neg_freq:.1f} Hz")

def main():
    print("=== Testing AM Preset (SSRC 1000) ===")
    am_samples = capture_ssrc(1000, duration=5)
    plot_spectrum(am_samples, 12000, "SSRC 1000 - AM Preset (demodulated audio)")
    
    print("\n=== Testing IQ Preset (SSRC 5000000) ===")
    iq_samples = capture_ssrc(5000000, duration=5)
    plot_spectrum(iq_samples, 8000, "SSRC 5000000 - IQ Preset (baseband IQ)")
    
    plt.tight_layout()
    plt.savefig('/tmp/am_vs_iq_comparison.png', dpi=150)
    print(f"\nComparison saved: /tmp/am_vs_iq_comparison.png")
    
    print("\n=== INTERPRETATION ===")
    print("If AM preset shows 100 Hz tone but IQ doesn't:")
    print("  → radiod's 'iq' preset bandwidth is too narrow")
    print("If NEITHER shows 100 Hz tone:")
    print("  → WWV may not be transmitting the tone right now")
    print("If BOTH show 100 Hz tone:")
    print("  → Something wrong with our diagnostic script")

if __name__ == '__main__':
    main()
