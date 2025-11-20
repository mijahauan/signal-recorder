#!/usr/bin/env python3
"""
Verify that the two decimation methods actually produce different outputs
"""

import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.decimation import decimate_for_upload as decimate_original
from signal_recorder.decimation_improved import decimate_for_upload_improved


def test_single_file():
    """Test both methods on a single real file"""
    
    # Load one file
    archive_dir = Path("/tmp/grape-test/archives/WWV_5_MHz")
    files = sorted(archive_dir.glob("20251119*_iq.npz"))
    
    # Find a complete file (not 320 samples)
    test_file = None
    for f in files:
        data = np.load(f)
        if len(data['iq']) > 1000:
            test_file = f
            break
    
    if not test_file:
        print("No suitable test file found")
        return
    
    print(f"Testing with: {test_file.name}")
    
    data = np.load(test_file)
    iq_input = data['iq']
    
    print(f"Input: {len(iq_input)} samples")
    
    # Decimate with both methods
    print("\nDecimating with original method...")
    iq_orig = decimate_original(iq_input, 16000, 10)
    
    print("Decimating with improved method...")
    iq_imp = decimate_for_upload_improved(iq_input, 16000, 10)
    
    if iq_orig is None or iq_imp is None:
        print("One method failed!")
        return
    
    print(f"\nOriginal output: {len(iq_orig)} samples")
    print(f"Improved output: {len(iq_imp)} samples")
    
    # Compare outputs
    min_len = min(len(iq_orig), len(iq_imp))
    
    # Check if identical
    if np.allclose(iq_orig[:min_len], iq_imp[:min_len], rtol=1e-10):
        print("\n⚠️  OUTPUTS ARE IDENTICAL!")
        print("The two methods are producing the same result.")
        return
    
    # Calculate difference
    diff = iq_orig[:min_len] - iq_imp[:min_len]
    rms_diff = np.sqrt(np.mean(np.abs(diff)**2))
    rms_orig = np.sqrt(np.mean(np.abs(iq_orig[:min_len])**2))
    
    print(f"\nRMS difference: {rms_diff:.6e}")
    print(f"RMS original: {rms_orig:.6e}")
    print(f"Relative difference: {100 * rms_diff / rms_orig:.2f}%")
    print(f"Difference in dB: {20*np.log10(rms_diff / rms_orig):.1f} dB")
    
    # Spectral comparison
    from scipy import signal
    
    # FFT of original output
    fft_orig = np.fft.fft(iq_orig[:min_len])
    freqs = np.fft.fftfreq(min_len, d=0.1)
    mag_orig = 20 * np.log10(np.abs(fft_orig) / min_len + 1e-10)
    
    # FFT of improved output
    fft_imp = np.fft.fft(iq_imp[:min_len])
    mag_imp = 20 * np.log10(np.abs(fft_imp) / min_len + 1e-10)
    
    # Check specific frequencies
    freq_mask = (freqs >= 3.5) & (freqs <= 4.5)
    
    if np.any(freq_mask):
        orig_power_4hz = np.mean(mag_orig[freq_mask])
        imp_power_4hz = np.mean(mag_imp[freq_mask])
        
        print(f"\nAverage power @ 4 Hz region:")
        print(f"  Original: {orig_power_4hz:.1f} dB")
        print(f"  Improved: {imp_power_4hz:.1f} dB")
        print(f"  Difference: {orig_power_4hz - imp_power_4hz:.1f} dB")
        
        if abs(orig_power_4hz - imp_power_4hz) < 1.0:
            print("\n⚠️  Less than 1 dB difference - methods are essentially the same!")
    
    # Check DC region
    dc_mask = (np.abs(freqs) < 0.5)
    orig_dc = np.mean(mag_orig[dc_mask])
    imp_dc = np.mean(mag_imp[dc_mask])
    
    print(f"\nDC region power:")
    print(f"  Original: {orig_dc:.1f} dB")
    print(f"  Improved: {imp_dc:.1f} dB")
    

if __name__ == '__main__':
    test_single_file()
