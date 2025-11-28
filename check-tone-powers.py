#!/usr/bin/env python3
"""Check if tone powers are being saved in NPZ files"""
import numpy as np
import glob

# Find latest NPZ file
files = sorted(glob.glob('/tmp/grape-test/archives/WWV_5_MHz/2025*.npz'))
if not files:
    print("No NPZ files found")
    exit(1)

latest = files[-1]
print(f"Checking: {latest.split('/')[-1]}")
print()

npz = np.load(latest)

print("NPZ Contents:")
for key in sorted(npz.files):
    val = npz[key]
    if isinstance(val, np.ndarray):
        if val.size == 1:
            print(f"  {key:30s} = {val}")
        else:
            print(f"  {key:30s} = array[{val.shape}]")
    else:
        print(f"  {key:30s} = {val}")

print()
print("Tone Power Fields:")
if 'tone_power_1000_hz_db' in npz.files:
    print(f"  ✅ tone_power_1000_hz_db = {float(npz['tone_power_1000_hz_db']):.1f} dB")
else:
    print(f"  ❌ tone_power_1000_hz_db not found")

if 'tone_power_1200_hz_db' in npz.files:
    print(f"  ✅ tone_power_1200_hz_db = {float(npz['tone_power_1200_hz_db']):.1f} dB")
else:
    print(f"  ❌ tone_power_1200_hz_db not found")
