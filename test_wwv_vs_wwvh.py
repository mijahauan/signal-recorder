#!/usr/bin/env python3
"""Test if we're receiving WWV (1000Hz) or WWVH (1200Hz)"""
import socket, struct, numpy as np, matplotlib.pyplot as plt
from scipy import signal as scipy_signal
import time

def capture_minute_boundary(ssrc=5000000):
    print("Waiting for :55 seconds...")
    while int(time.time()) % 60 != 55:
        time.sleep(0.1)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    print("Capturing 10 seconds...")
    samples = []
    start = time.time()
    
    while len(samples) < 80000:
        data, _ = sock.recvfrom(8192)
        if len(data) >= 12 and struct.unpack('>I', data[8:12])[0] == ssrc:
            payload = data[12:]
            if len(payload) % 4 == 0:
                s = np.frombuffer(payload, dtype='>i2').reshape(-1, 2).astype(np.float32) / 32768.0
                samples.extend(s[:, 1] + 1j * s[:, 0])
    
    sock.close()
    return np.array(samples[:80000]), start

def test_frequency(iq, freq_low, freq_high, freq_name):
    """Test for tone at specific frequency"""
    # Resample to 3 kHz
    sos = scipy_signal.butter(8, 1500, btype='low', fs=8000, output='sos')
    filt = scipy_signal.sosfilt(sos, iq)[::2]
    filt = filt[::1]
    
    # AM demod
    am = np.abs(filt) - np.mean(np.abs(filt))
    
    # Bandpass filter
    sos_tone = scipy_signal.butter(4, [freq_low, freq_high], btype='band', fs=3000, output='sos')
    tone = scipy_signal.sosfiltfilt(sos_tone, am)
    
    # Envelope
    env = np.abs(scipy_signal.hilbert(tone))
    max_env = np.max(env)
    env_norm = env / max_env if max_env > 0 else env
    
    # Find peak around :00 (5 seconds into capture)
    window_start = int(4.5 * 3000)  # 4.5 seconds
    window_end = int(5.5 * 3000)    # 5.5 seconds
    window_peak = np.max(env_norm[window_start:window_end])
    
    print(f"\n{freq_name} ({freq_low}-{freq_high} Hz):")
    print(f"  Max envelope (overall): {max_env:.6f}")
    print(f"  Peak at :00 window: {window_peak:.4f}")
    
    return env_norm, max_env, window_peak

if __name__ == '__main__':
    print("=== WWV vs WWVH Minute Marker Test ===\n")
    
    iq, start = capture_minute_boundary()
    
    # Test both frequencies
    env_1000, max_1000, peak_1000 = test_frequency(iq, 950, 1050, "WWV (1000 Hz)")
    env_1200, max_1200, peak_1200 = test_frequency(iq, 1150, 1250, "WWVH (1200 Hz)")
    
    # Also test second tick (100 Hz clicks)
    env_100, max_100, peak_100 = test_frequency(iq, 50, 150, "Second ticks (100 Hz)")
    
    print("\n=== CONCLUSION ===")
    if peak_1000 > 0.5:
        print("✓ WWV detected (1000 Hz tone present)")
    elif peak_1200 > 0.5:
        print("✓ WWVH detected (1200 Hz tone present)")
    elif peak_100 > 0.3:
        print("✓ Signal present but no clear minute marker")
        print("  (Second ticks detected, but no 1000Hz or 1200Hz tone)")
    else:
        print("✗ No clear time signal detected")
        print("  Possible causes:")
        print("  - Poor propagation")
        print("  - Station not transmitting")
        print("  - Selective fading")
    
    if peak_1000 > peak_1200:
        print(f"\nStronger signal: WWV (1000 Hz) - peak {peak_1000:.3f} vs {peak_1200:.3f}")
    else:
        print(f"\nStronger signal: WWVH (1200 Hz) - peak {peak_1200:.3f} vs {peak_1000:.3f}")
    
    # Plot comparison
    t = np.arange(len(env_1000)) / 3000
    fig, ax = plt.subplots(3, 1, figsize=(14, 9))
    
    ax[0].plot(t, env_1000, label='WWV (1000 Hz)', linewidth=1.5)
    ax[0].axvline(5, color='red', linestyle='--', label=':00 boundary')
    ax[0].axhline(0.5, color='green', linestyle='--', alpha=0.5, label='Strong tone threshold')
    ax[0].set_title('WWV (Fort Collins) - 1000 Hz Minute Marker', fontweight='bold')
    ax[0].set_ylabel('Normalized Envelope')
    ax[0].legend()
    ax[0].grid(True, alpha=0.3)
    
    ax[1].plot(t, env_1200, label='WWVH (1200 Hz)', color='orange', linewidth=1.5)
    ax[1].axvline(5, color='red', linestyle='--', label=':00 boundary')
    ax[1].axhline(0.5, color='green', linestyle='--', alpha=0.5, label='Strong tone threshold')
    ax[1].set_title('WWVH (Hawaii) - 1200 Hz Minute Marker', fontweight='bold')
    ax[1].set_ylabel('Normalized Envelope')
    ax[1].legend()
    ax[1].grid(True, alpha=0.3)
    
    ax[2].plot(t, env_100, label='Second Ticks (100 Hz)', color='purple', linewidth=1.5)
    ax[2].axvline(5, color='red', linestyle='--', label=':00 boundary')
    ax[2].axhline(0.3, color='green', linestyle='--', alpha=0.5, label='Tick threshold')
    ax[2].set_title('Second Tick Pulses (100 Hz)', fontweight='bold')
    ax[2].set_ylabel('Normalized Envelope')
    ax[2].set_xlabel('Time (seconds from :55)')
    ax[2].legend()
    ax[2].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('/tmp/wwv_vs_wwvh_test.png', dpi=150)
    print("\n✓ Plot saved: /tmp/wwv_vs_wwvh_test.png")
