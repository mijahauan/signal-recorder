#!/usr/bin/env python3
"""Diagnostic tool to analyze WWV 1000 Hz minute marker tone"""
import socket, struct, numpy as np, matplotlib.pyplot as plt
from scipy import signal as scipy_signal
from datetime import datetime, timezone
import time

def capture_minute_boundary(ssrc=5000000):
    print("Waiting for :55 seconds...")
    while True:
        if int(time.time()) % 60 == 55:
            break
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

def analyze(iq, start):
    # Resample to 3 kHz
    sos = scipy_signal.butter(8, 1500, btype='low', fs=8000, output='sos')
    filt = scipy_signal.sosfilt(sos, iq)[::2]
    filt = filt[::1]  # Keep at ~4kHz initially
    filt = filt[::1]  # Then to ~2.67kHz - close to 3kHz
    
    # AM demod
    am = np.abs(filt) - np.mean(np.abs(filt))
    
    # 1000 Hz filter
    sos1k = scipy_signal.butter(4, [950, 1050], btype='band', fs=3000, output='sos')
    tone = scipy_signal.sosfiltfilt(sos1k, am)
    
    # Envelope
    env = np.abs(scipy_signal.hilbert(tone))
    env_norm = env / np.max(env) if np.max(env) > 0 else env
    
    # Detection
    above = env_norm > 0.03
    edges_up = np.where(np.diff(above.astype(int)) == 1)[0]
    edges_down = np.where(np.diff(above.astype(int)) == -1)[0]
    
    print(f"\nResults:")
    print(f"  Max envelope: {np.max(env):.6f}")
    print(f"  Above threshold: {np.sum(above)/len(above)*100:.1f}%")
    print(f"  Rising edges: {len(edges_up)}, Falling edges: {len(edges_down)}")
    
    if len(edges_up) > 0 and len(edges_down) > 0:
        for i, up in enumerate(edges_up[:5]):
            down_cand = edges_down[edges_down > up]
            if len(down_cand) > 0:
                dur = (down_cand[0] - up) / 3000
                t_offset = up / 3000
                print(f"  Tone {i+1}: {dur:.3f}s at +{t_offset:.1f}s (minute second: {(start + t_offset) % 60:.1f})")
    
    # Plot
    t = np.arange(len(am)) / 3000
    fig, ax = plt.subplots(3, 1, figsize=(14, 8))
    ax[0].plot(t, am, lw=0.5); ax[0].set_title('AM Audio'); ax[0].axvline(5, color='r', ls='--')
    ax[1].plot(t, tone, lw=0.5); ax[1].set_title('After 1000Hz Filter'); ax[1].axvline(5, color='r', ls='--')
    ax[2].plot(t, env_norm); ax[2].axhline(0.03, color='orange', ls='--'); ax[2].set_title('Envelope'); ax[2].axvline(5, color='r', ls='--', label=':00 boundary')
    ax[2].legend(); ax[2].set_xlabel('Time (s from :55)')
    plt.tight_layout()
    plt.savefig('/tmp/wwv_tone_diagnosis.png', dpi=150)
    print("\nPlot: /tmp/wwv_tone_diagnosis.png")

if __name__ == '__main__':
    iq, start = capture_minute_boundary()
    analyze(iq, start)
