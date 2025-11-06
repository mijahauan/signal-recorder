#!/usr/bin/env python3
"""
Diagnose IQ Spectrum Issues

Tests different IQ formations to determine correct processing:
1. Normal: samples[:, 0] + 1j * samples[:, 1]  (I + jQ)
2. Swapped: samples[:, 1] + 1j * samples[:, 0]  (Q + jI)
3. Conjugate normal: samples[:, 0] - 1j * samples[:, 1]  (I - jQ)
4. Conjugate swapped: samples[:, 1] - 1j * samples[:, 0]  (Q - jI)

For WWV AM with 100 Hz tone (nearly continuous), proper double-sideband should show:
- Strong peaks at BOTH +100 Hz and -100 Hz
- Symmetric spectrum around 0 Hz carrier

If only one side has energy, either:
- Radiod is sending SSB (one sideband)
- Our IQ processing needs conjugation
"""

import socket
import struct
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal as scipy_signal

def capture_iq(ssrc=5000000, duration=10):
    """Capture IQ samples"""
    print(f"Capturing {duration}s of IQ data from SSRC {ssrc}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    target_samples = duration * 8000
    all_samples_raw = []
    total_samples = 0
    
    while total_samples < target_samples:
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
        
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        payload = data[12:]
        if len(payload) % 4 == 0:
            # Just get raw int16 pairs - DON'T form complex yet
            samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
            all_samples_raw.append(samples_int16)
            total_samples += len(samples_int16)
            
            if total_samples % 8000 == 0 or (total_samples % 1600 == 0 and total_samples < 8000):
                print(f"  Progress: {total_samples}/{target_samples} samples")
    
    sock.close()
    
    # Concatenate and normalize
    samples_raw = np.concatenate(all_samples_raw)[:target_samples]
    samples_norm = samples_raw.astype(np.float32) / 32768.0
    
    print(f"Captured {len(samples_norm)} sample pairs")
    return samples_norm


def compute_spectrum(iq_complex, label):
    """Compute power spectrum"""
    f, Pxx = scipy_signal.welch(iq_complex, fs=8000, nperseg=4096, scaling='density')
    return f, 10 * np.log10(Pxx + 1e-12), label


def main():
    # Capture raw I/Q data
    samples = capture_iq(duration=10)
    
    # Try all 4 combinations
    iq_variants = {
        'I + jQ (Normal)': samples[:, 0] + 1j * samples[:, 1],
        'Q + jI (Swapped)': samples[:, 1] + 1j * samples[:, 0],
        'I - jQ (Conj Normal)': samples[:, 0] - 1j * samples[:, 1],
        'Q - jI (Conj Swapped)': samples[:, 1] - 1j * samples[:, 0],
    }
    
    # Compute spectra
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    axes = axes.flatten()
    
    for idx, (label, iq) in enumerate(iq_variants.items()):
        f, Pxx, _ = compute_spectrum(iq, label)
        
        ax = axes[idx]
        ax.plot(f, Pxx, linewidth=0.5)
        ax.axvline(0, color='red', linestyle='--', alpha=0.5, linewidth=2, label='DC (carrier)')
        ax.axvline(100, color='green', linestyle='--', alpha=0.5, linewidth=1, label='+100 Hz tone')
        ax.axvline(-100, color='blue', linestyle='--', alpha=0.5, linewidth=1, label='-100 Hz tone')
        ax.set_xlim(-4000, 4000)
        ax.set_ylim(-100, -40)
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Power (dB)')
        ax.set_title(label)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')
        
        # Measure symmetry
        # Get power in +/- 100 Hz bands (50 Hz wide)
        pos_band = np.where((f >= 75) & (f <= 125))[0]
        neg_band = np.where((f >= -125) & (f <= -75))[0]
        
        pos_power = np.mean(Pxx[pos_band]) if len(pos_band) > 0 else -999
        neg_power = np.mean(Pxx[neg_band]) if len(neg_band) > 0 else -999
        
        symmetry = abs(pos_power - neg_power)
        
        textstr = f'Power @ +100Hz: {pos_power:.1f} dB\n'
        textstr += f'Power @ -100Hz: {neg_power:.1f} dB\n'
        textstr += f'Asymmetry: {symmetry:.1f} dB'
        
        ax.text(0.02, 0.98, textstr, transform=ax.transAxes, 
                fontsize=9, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    plt.suptitle('IQ Phase Diagnosis - WWV 5 MHz\n' + 
                 'CORRECT: Should show SYMMETRIC peaks at ±100 Hz (WWV tone)', 
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    filename = '/tmp/iq_spectrum_diagnosis.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"\nDiagnosis plot saved: {filename}")
    print("\nWhat to look for:")
    print("  ✓ CORRECT: Similar power at +100 Hz and -100 Hz (symmetric)")
    print("  ✗ WRONG: All power on one side only (asymmetric)")
    print("\nIf all variants show asymmetry, radiod may be sending SSB.")
    print("If one variant is symmetric, that's the correct IQ formation!")
    
if __name__ == '__main__':
    main()
