#!/usr/bin/env python3
"""Diagnose why matched filter gives zero correlation"""

import numpy as np
from scipy import signal as scipy_signal
from scipy.signal import correlate
import struct
import sys

# Read a minute file to check actual signal
import glob
files = glob.glob('/tmp/grape-test/data/*/WWV_10_MHz_*.cf32')
if not files:
    print("No data files found!")
    sys.exit(1)

file = files[0]
print(f"Reading: {file}")

# Read IQ samples (complex64 = 2 floats per sample)
with open(file, 'rb') as f:
    data = f.read(960000 * 8)  # 1 minute at 16 kHz complex

iq = np.frombuffer(data, dtype=np.complex64)[:160000]  # First 10 seconds
print(f"IQ samples: {len(iq)}")

# 1. AM demodulation
magnitude = np.abs(iq)
audio = magnitude - np.mean(magnitude)
print(f"AM demod - mean: {np.mean(audio):.6f}, std: {np.std(audio):.6f}, max: {np.max(np.abs(audio)):.6f}")

# 2. Resample to 3 kHz
audio_3k = scipy_signal.resample_poly(audio, 3, 16)
print(f"Resampled to 3kHz: {len(audio_3k)} samples")
print(f"  mean: {np.mean(audio_3k):.6f}, std: {np.std(audio_3k):.6f}, max: {np.max(np.abs(audio_3k)):.6f}")

# 3. Check spectrum
from scipy.fft import rfft, rfftfreq
spectrum = np.abs(rfft(audio_3k))
freqs = rfftfreq(len(audio_3k), 1/3000)
peak_idx = np.argmax(spectrum[:1500])  # Up to 1500 Hz
peak_freq = freqs[peak_idx]
print(f"\nSpectrum analysis:")
print(f"  Peak frequency: {peak_freq:.1f} Hz")
print(f"  Power at 1000 Hz: {spectrum[int(1000 * len(audio_3k) / 3000)]:.2f}")
print(f"  Power at 1200 Hz: {spectrum[int(1200 * len(audio_3k) / 3000)]:.2f}")

# 4. Create template and test correlation
t = np.arange(0, 0.8, 1/3000)
template = np.sin(2 * np.pi * 1000 * t)
template *= scipy_signal.windows.tukey(len(template), alpha=0.1)
template /= np.linalg.norm(template)
print(f"\nTemplate: {len(template)} samples, energy={np.linalg.norm(template):.6f}")

corr = correlate(audio_3k, template, mode='valid')
peak = np.max(corr)
print(f"Correlation peak: {peak:.6f}")
print(f"Expected for 1% amplitude signal: ~0.34")

if peak < 0.01:
    print("\n❌ PROBLEM: Correlation peak is essentially zero!")
    print("Signal does not contain expected 1000 Hz tone, or processing is wrong.")
else:
    print(f"\n✅ Correlation working! Peak is {peak:.3f}")
