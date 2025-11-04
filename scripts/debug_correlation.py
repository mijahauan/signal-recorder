#!/usr/bin/env python3
"""Quick diagnostic to check if correlation is working"""

import numpy as np
from scipy import signal as scipy_signal
from scipy.signal import correlate

# Create template (normalized)
fs = 3000
t = np.arange(0, 0.8, 1/fs)
template = np.sin(2 * np.pi * 1000 * t)
template *= scipy_signal.windows.tukey(len(template), alpha=0.1)
template /= np.linalg.norm(template)

print(f"Template: {len(template)} samples")
print(f"Template energy (should be 1.0): {np.linalg.norm(template):.6f}")
print(f"Template peak amplitude: {np.max(np.abs(template)):.6f}")
print()

# Create test signal: 1000 Hz tone at various amplitudes
for amp in [1.0, 0.1, 0.01]:
    signal_test = amp * np.sin(2 * np.pi * 1000 * np.arange(0, 6.0, 1/fs))
    
    # Correlate
    corr = correlate(signal_test, template, mode='valid')
    peak = np.max(corr)
    peak_idx = np.argmax(corr)
    
    # Expected peak for normalized matched filter
    expected_peak = amp * np.sqrt(len(template))
    
    print(f"Signal amplitude: {amp:.3f}")
    print(f"  Correlation peak: {peak:.6f}")
    print(f"  Expected peak: {expected_peak:.6f}")
    print(f"  Peak position: {peak_idx} (expected ~{int(3.0 * fs)})")
    print()
