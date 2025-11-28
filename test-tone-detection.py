#!/usr/bin/env python3
"""
Test tone detection on a recent NPZ file
"""
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from signal_recorder.startup_tone_detector import StartupToneDetector

# Load a recent NPZ file
import glob
files = sorted(glob.glob('/tmp/grape-test/archives/WWV_5_MHz/2025*.npz'))
if not files:
    print("No NPZ files found")
    sys.exit(1)

latest = files[-1]
print(f"Testing with: {latest}")
print()

npz = np.load(latest)
iq_samples = npz['iq']
sample_rate = int(npz['sample_rate'])
freq_hz = float(npz['frequency_hz'])

print(f"File info:")
print(f"  Samples: {len(iq_samples):,}")
print(f"  Duration: {len(iq_samples)/sample_rate:.1f}s")
print(f"  Frequency: {freq_hz/1e6:.1f} MHz")
print(f"  Sample rate: {sample_rate} Hz")
print()

# Analyze signal
print("Signal analysis:")
print(f"  Mean power: {np.mean(np.abs(iq_samples)**2):.6f}")
print(f"  Max amplitude: {np.max(np.abs(iq_samples)):.6f}")
print(f"  Data type: {iq_samples.dtype}")
print()

# Do FFT to check for tones
print("FFT analysis (looking for 1000 Hz and 1200 Hz tones):")
# Take first 16000 samples (1 second)
chunk = iq_samples[:16000]
fft = np.fft.fft(chunk)
freqs = np.fft.fftfreq(len(chunk), 1/sample_rate)

# Look at positive frequencies
pos_mask = freqs > 0
pos_freqs = freqs[pos_mask]
pos_fft = np.abs(fft[pos_mask])

# Find peaks near 1000 Hz and 1200 Hz
for target_freq in [1000, 1200]:
    mask = (pos_freqs > target_freq - 100) & (pos_freqs < target_freq + 100)
    if np.any(mask):
        peak_power = np.max(pos_fft[mask])
        peak_freq = pos_freqs[mask][np.argmax(pos_fft[mask])]
        print(f"  {target_freq} Hz region: peak at {peak_freq:.1f} Hz, power={peak_power:.6f}")
    else:
        print(f"  {target_freq} Hz region: no data in range")

print()

# Try the detector
print("Testing StartupToneDetector...")
detector = StartupToneDetector(sample_rate=sample_rate, frequency_hz=freq_hz)
print(f"  Expected station: {detector.expected_station}")
print(f"  Tone frequencies to try: {detector.tone_frequencies}")
print()

# Test detection
result = detector.detect_time_snap(
    iq_samples=iq_samples[:16000*60],  # Use 60 seconds
    first_rtp_timestamp=int(npz['rtp_timestamp']),
    wall_clock_start=float(npz['unix_timestamp'])
)

print()
if result:
    print("✅ TONE DETECTED!")
    print(f"  Source: {result.source}")
    print(f"  Station: {result.station}")
    print(f"  Confidence: {result.confidence:.2f}")
    print(f"  SNR: {result.detection_snr_db:.1f} dB")
else:
    print("❌ NO TONE DETECTED")
    print("This is the problem we need to fix!")
