#!/usr/bin/env python3
"""
Comprehensive test of improved decimation vs original

Tests both methods on identical synthetic signal with known spectral content.
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import sys

sys.path.insert(0, 'src')

from signal_recorder.decimation import decimate_for_upload as decimate_original
from signal_recorder.decimation_improved import decimate_for_upload_improved


def create_test_signal(duration_sec=60):
    """
    Create test signal with:
    - DC offset: 0.1
    - 2 Hz tone: 0.5 (inside passband, should pass)
    - 100 Hz tone: 0.3 (outside passband, should be rejected)
    - 500 Hz tone: 0.2 (far outside, should be heavily rejected)
    """
    sr = 16000
    t = np.arange(sr * duration_sec) / sr
    
    dc = 0.1 + 0j
    tone_2hz = 0.5 * np.exp(2j * np.pi * 2.0 * t)
    tone_100hz = 0.3 * np.exp(2j * np.pi * 100.0 * t)
    tone_500hz = 0.2 * np.exp(2j * np.pi * 500.0 * t)
    
    signal = dc + tone_2hz + tone_100hz + tone_500hz
    
    return signal, t


def analyze_spectrum(iq, sample_rate, label="Signal"):
    """Analyze and print spectrum"""
    fft_result = np.fft.fft(iq)
    freqs = np.fft.fftfreq(len(iq), d=1/sample_rate)
    
    # Sort by frequency
    sort_idx = np.argsort(freqs)
    freqs_sorted = freqs[sort_idx]
    fft_sorted = fft_result[sort_idx]
    
    # Find peaks
    magnitude_db = 20 * np.log10(np.abs(fft_sorted) / len(iq) + 1e-10)
    
    print(f"\n{label} Spectrum (sample rate = {sample_rate} Hz):")
    print(f"  Frequency bins: {len(freqs)}")
    print(f"  Frequency resolution: {sample_rate / len(freqs):.4f} Hz")
    
    # Show top 10 peaks
    peak_indices = np.argsort(magnitude_db)[-10:][::-1]
    
    print(f"\n  Top 10 spectral peaks:")
    for i, idx in enumerate(peak_indices[:10]):
        freq = freqs_sorted[idx]
        power = magnitude_db[idx]
        print(f"    {i+1}. {freq:7.3f} Hz: {power:6.1f} dB")
    
    return freqs_sorted, magnitude_db


def main():
    print("=" * 80)
    print("IMPROVED DECIMATION TEST")
    print("=" * 80)
    
    # Create test signal
    print("\nGenerating test signal (60 seconds @ 16 kHz)...")
    print("  Components:")
    print("    DC:      0.10 (-20.0 dB)")
    print("    2 Hz:    0.50 (-6.0 dB)  ← inside passband, should PASS")
    print("    100 Hz:  0.30 (-10.5 dB) ← outside passband, should REJECT")
    print("    500 Hz:  0.20 (-14.0 dB) ← far outside, should HEAVILY REJECT")
    
    test_signal, t = create_test_signal(duration_sec=60)
    
    # Analyze input
    print("\nInput signal:")
    print(f"  Length: {len(test_signal)} samples")
    print(f"  Duration: {len(test_signal)/16000:.1f} seconds")
    print(f"  RMS: {np.sqrt(np.mean(np.abs(test_signal)**2)):.3f}")
    
    # Test original method
    print("\n" + "=" * 80)
    print("METHOD 1: ORIGINAL (decimation.py)")
    print("=" * 80)
    
    result_original = decimate_original(test_signal, 16000, 10)
    if result_original is not None:
        print(f"✅ Output: {len(result_original)} samples @ 10 Hz")
        freqs_orig, mag_orig = analyze_spectrum(result_original, 10, "Original Method")
    else:
        print("❌ Original decimation failed")
        return
    
    # Test improved method
    print("\n" + "=" * 80)
    print("METHOD 2: IMPROVED (decimation_improved.py)")
    print("=" * 80)
    
    result_improved = decimate_for_upload_improved(test_signal, 16000, 10)
    if result_improved is not None:
        print(f"✅ Output: {len(result_improved)} samples @ 10 Hz")
        freqs_imp, mag_imp = analyze_spectrum(result_improved, 10, "Improved Method")
    else:
        print("❌ Improved decimation failed")
        return
    
    # Compare results
    print("\n" + "=" * 80)
    print("COMPARISON")
    print("=" * 80)
    
    # Find specific frequencies in output (10 Hz sample rate, so -5 to +5 Hz range)
    def find_peak_near(freqs, mags, target_freq, window=0.5):
        """Find peak power near target frequency"""
        mask = (freqs >= target_freq - window) & (freqs <= target_freq + window)
        if np.any(mask):
            peak_idx = np.argmax(mags[mask])
            actual_freq = freqs[mask][peak_idx]
            power = mags[mask][peak_idx]
            return actual_freq, power
        return None, -999
    
    # Expected output (after aliasing):
    # DC: 0 Hz (passes through)
    # 2 Hz: 2 Hz (passes through)
    # 100 Hz: aliases to 100 % 10 = 0 Hz (DC) [if it leaks through]
    # 500 Hz: aliases to 500 % 10 = 0 Hz (DC) [if it leaks through]
    
    print("\nOriginal Method:")
    dc_freq, dc_power = find_peak_near(freqs_orig, mag_orig, 0.0, 0.2)
    tone_freq, tone_power = find_peak_near(freqs_orig, mag_orig, 2.0, 0.5)
    print(f"  DC (0 Hz):    {dc_power:6.1f} dB (expected: -20.0 dB)")
    print(f"  2 Hz tone:    {tone_power:6.1f} dB (expected: -6.0 dB)")
    print(f"  Leakage: DC contains 100 Hz and 500 Hz aliases")
    
    print("\nImproved Method:")
    dc_freq_imp, dc_power_imp = find_peak_near(freqs_imp, mag_imp, 0.0, 0.2)
    tone_freq_imp, tone_power_imp = find_peak_near(freqs_imp, mag_imp, 2.0, 0.5)
    print(f"  DC (0 Hz):    {dc_power_imp:6.1f} dB (expected: -20.0 dB)")
    print(f"  2 Hz tone:    {tone_power_imp:6.1f} dB (expected: -6.0 dB)")
    
    # Check if DC is elevated (indicating leakage)
    dc_expected = -20.0
    if dc_power > dc_expected + 5:
        print(f"\n  ⚠️  ORIGINAL: DC elevated by {dc_power - dc_expected:.1f} dB (aliasing!)")
    else:
        print(f"\n  ✅ ORIGINAL: DC level acceptable")
    
    if dc_power_imp > dc_expected + 5:
        print(f"  ⚠️  IMPROVED: DC elevated by {dc_power_imp - dc_expected:.1f} dB (aliasing!)")
    else:
        print(f"  ✅ IMPROVED: DC level acceptable")
    
    # Generate plots
    print("\n" + "=" * 80)
    print("GENERATING PLOTS")
    print("=" * 80)
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # Plot 1: Time domain comparison (first 5 seconds)
    n_samples = 50  # 5 seconds @ 10 Hz
    t_out = np.arange(n_samples) / 10
    
    axes[0, 0].plot(t_out, np.abs(result_original[:n_samples]), 'b-', label='Original', alpha=0.7)
    axes[0, 0].plot(t_out, np.abs(result_improved[:n_samples]), 'r--', label='Improved', alpha=0.7)
    axes[0, 0].set_xlabel('Time (s)')
    axes[0, 0].set_ylabel('Magnitude')
    axes[0, 0].set_title('Time Domain: First 5 Seconds')
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=0.3)
    
    # Plot 2: Frequency domain (full spectrum)
    axes[0, 1].plot(freqs_orig, mag_orig, 'b-', label='Original', alpha=0.7)
    axes[0, 1].plot(freqs_imp, mag_imp, 'r--', label='Improved', alpha=0.7)
    axes[0, 1].axvline(0, color='g', linestyle=':', alpha=0.5, label='DC')
    axes[0, 1].axvline(2, color='g', linestyle=':', alpha=0.5, label='2 Hz')
    axes[0, 1].axvline(-2, color='g', linestyle=':', alpha=0.5)
    axes[0, 1].set_xlabel('Frequency (Hz)')
    axes[0, 1].set_ylabel('Magnitude (dB)')
    axes[0, 1].set_title('Frequency Spectrum (Full Range)')
    axes[0, 1].set_xlim(-5, 5)
    axes[0, 1].set_ylim(-100, 0)
    axes[0, 1].legend()
    axes[0, 1].grid(True, alpha=0.3)
    
    # Plot 3: Zoom on DC region
    dc_mask = (freqs_orig >= -0.5) & (freqs_orig <= 0.5)
    axes[1, 0].plot(freqs_orig[dc_mask], mag_orig[dc_mask], 'b-', label='Original', alpha=0.7, linewidth=2)
    axes[1, 0].plot(freqs_imp[dc_mask], mag_imp[dc_mask], 'r--', label='Improved', alpha=0.7, linewidth=2)
    axes[1, 0].axhline(-20, color='g', linestyle=':', label='Expected DC level')
    axes[1, 0].set_xlabel('Frequency (Hz)')
    axes[1, 0].set_ylabel('Magnitude (dB)')
    axes[1, 0].set_title('DC Region Zoom (Aliasing Check)')
    axes[1, 0].legend()
    axes[1, 0].grid(True, alpha=0.3)
    
    # Plot 4: Zoom on 2 Hz region
    tone_mask = (freqs_orig >= 1.5) & (freqs_orig <= 2.5)
    axes[1, 1].plot(freqs_orig[tone_mask], mag_orig[tone_mask], 'b-', label='Original', alpha=0.7, linewidth=2)
    axes[1, 1].plot(freqs_imp[tone_mask], mag_imp[tone_mask], 'r--', label='Improved', alpha=0.7, linewidth=2)
    axes[1, 1].axhline(-6, color='g', linestyle=':', label='Expected 2 Hz level')
    axes[1, 1].set_xlabel('Frequency (Hz)')
    axes[1, 1].set_ylabel('Magnitude (dB)')
    axes[1, 1].set_title('2 Hz Tone Region (Passband Check)')
    axes[1, 1].legend()
    axes[1, 1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    output_path = Path('logs/decimation_comparison.png')
    output_path.parent.mkdir(exist_ok=True)
    plt.savefig(output_path, dpi=150)
    print(f"\n📊 Comparison plots saved to: {output_path}")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
