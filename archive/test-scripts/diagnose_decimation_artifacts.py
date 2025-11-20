#!/usr/bin/env python3
"""
Diagnose decimation artifacts in 10 Hz output

Checks for:
1. Fixed-point overflow (should be impossible with float arithmetic)
2. Filter frequency response issues
3. Aliasing from insufficient stopband rejection
4. Edge effects and transients
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.decimation import decimate_for_upload, _design_cic_filter, _apply_cic_filter
from signal_recorder.decimation import _design_compensation_fir, _design_final_fir


def check_data_types(npz_16k_path: Path, npz_10hz_path: Path):
    """Verify dtypes throughout processing chain"""
    print("=" * 80)
    print("DATA TYPE VERIFICATION")
    print("=" * 80)
    
    # Load 16 kHz archive
    data_16k = np.load(npz_16k_path)
    iq_16k = data_16k['iq']
    
    print(f"16 kHz NPZ:")
    print(f"  dtype: {iq_16k.dtype}")
    print(f"  shape: {iq_16k.shape}")
    print(f"  max magnitude: {np.max(np.abs(iq_16k)):.6f}")
    print(f"  min magnitude: {np.min(np.abs(iq_16k[iq_16k != 0])):.6e}")
    
    # Check for clipping (should never happen with float)
    if np.any(np.abs(iq_16k) >= 1.0):
        print("  ⚠️  WARNING: Samples at or above 1.0 (clipping in input!)")
    else:
        print("  ✅ No clipping at input")
    
    # Load 10 Hz archive
    data_10hz = np.load(npz_10hz_path)
    iq_10hz = data_10hz['iq']
    
    print(f"\n10 Hz NPZ:")
    print(f"  dtype: {iq_10hz.dtype}")
    print(f"  shape: {iq_10hz.shape}")
    print(f"  max magnitude: {np.max(np.abs(iq_10hz)):.6f}")
    print(f"  min magnitude: {np.min(np.abs(iq_10hz[iq_10hz != 0])):.6e}")
    
    # Check dynamic range
    non_zero = iq_10hz[iq_10hz != 0]
    if len(non_zero) > 0:
        dynamic_range_db = 20 * np.log10(np.max(np.abs(non_zero)) / np.min(np.abs(non_zero)))
        print(f"  Dynamic range: {dynamic_range_db:.1f} dB")
        if dynamic_range_db < 90:
            print(f"  ⚠️  Low dynamic range suggests quantization issues")
        else:
            print(f"  ✅ Excellent dynamic range (float arithmetic working)")


def analyze_filter_responses():
    """Analyze frequency response of each filter stage"""
    print("\n" + "=" * 80)
    print("FILTER FREQUENCY RESPONSE ANALYSIS")
    print("=" * 80)
    
    # Stage 1: CIC filter (16 kHz → 400 Hz)
    print("\nStage 1: CIC Filter (16 kHz → 400 Hz, R=40)")
    cic_params = _design_cic_filter(decimation_factor=40, order=4)
    
    # Approximate CIC response (boxcar implementation)
    R = 40
    b_cic = np.ones(R) / R
    w, h_cic = signal.freqz(b_cic, worN=8192, fs=16000)
    
    # True CIC response for comparison
    true_cic_response = np.abs(np.sinc(w * R / 16000)) ** 4
    
    # Find passband ripple (0-5 Hz)
    passband_mask = w <= 5
    passband_ripple_db = 20 * np.log10(np.max(np.abs(h_cic[passband_mask])) / 
                                        np.min(np.abs(h_cic[passband_mask])))
    
    # Find stopband attenuation at first alias (400 Hz)
    alias_idx = np.argmin(np.abs(w - 400))
    stopband_atten_db = -20 * np.log10(np.abs(h_cic[alias_idx]))
    
    print(f"  Passband ripple (0-5 Hz): {passband_ripple_db:.2f} dB")
    print(f"  Stopband attenuation @ 400 Hz: {stopband_atten_db:.1f} dB")
    
    if stopband_atten_db < 60:
        print(f"  ⚠️  INSUFFICIENT stopband rejection! Aliasing likely.")
    else:
        print(f"  ✅ Good stopband rejection")
    
    # Stage 2: Compensation FIR
    print("\nStage 2: Compensation FIR (400 Hz, R=1)")
    comp_taps = _design_compensation_fir(
        sample_rate=400,
        passband_width=5.0,
        cic_order=4,
        cic_decimation=40,
        num_taps=63
    )
    w_comp, h_comp = signal.freqz(comp_taps, worN=4096, fs=400)
    
    # Check if compensation is correct
    passband_mask_comp = w_comp <= 5
    passband_flatness_db = 20 * np.log10(np.max(np.abs(h_comp[passband_mask_comp])) / 
                                          np.min(np.abs(h_comp[passband_mask_comp])))
    print(f"  Passband flatness (0-5 Hz): {passband_flatness_db:.2f} dB")
    
    if passband_flatness_db > 0.2:
        print(f"  ⚠️  Passband not flat! Doppler measurements affected.")
    else:
        print(f"  ✅ Flat passband")
    
    # Stage 3: Final FIR
    print("\nStage 3: Final FIR (400 Hz → 10 Hz, R=40)")
    final_taps = _design_final_fir(
        sample_rate=400,
        cutoff=5.0,
        transition_width=1.0,
        stopband_attenuation_db=90
    )
    w_final, h_final = signal.freqz(final_taps, worN=4096, fs=400)
    
    # Check transition band
    passband_edge = np.argmin(np.abs(w_final - 5.0))
    stopband_start = np.argmin(np.abs(w_final - 6.0))
    
    passband_gain_db = 20 * np.log10(np.abs(h_final[passband_edge]))
    stopband_gain_db = 20 * np.log10(np.abs(h_final[stopband_start]))
    
    print(f"  Gain @ 5 Hz (passband edge): {passband_gain_db:.2f} dB")
    print(f"  Gain @ 6 Hz (stopband start): {stopband_gain_db:.2f} dB")
    print(f"  Rejection: {passband_gain_db - stopband_gain_db:.1f} dB")
    
    if (passband_gain_db - stopband_gain_db) < 80:
        print(f"  ⚠️  Insufficient transition band rejection")
    else:
        print(f"  ✅ Sharp transition")
    
    return {
        'cic': (w, h_cic, true_cic_response),
        'comp': (w_comp, h_comp),
        'final': (w_final, h_final)
    }


def test_synthetic_signal():
    """Test decimation with known synthetic input"""
    print("\n" + "=" * 80)
    print("SYNTHETIC SIGNAL TEST")
    print("=" * 80)
    
    # Create 60 seconds of test signal: DC + 2 Hz tone + 100 Hz interferer
    sample_rate = 16000
    duration = 60
    t = np.arange(sample_rate * duration) / sample_rate
    
    # DC offset
    dc_level = 0.1 + 0j
    
    # 2 Hz Doppler signal (inside passband)
    doppler_signal = 0.5 * np.exp(2j * np.pi * 2.0 * t)
    
    # 100 Hz interferer (should be rejected)
    interferer = 0.3 * np.exp(2j * np.pi * 100 * t)
    
    test_signal = dc_level + doppler_signal + interferer
    
    print(f"Input signal: {len(test_signal)} samples @ {sample_rate} Hz")
    print(f"  DC level: {np.abs(dc_level):.2f}")
    print(f"  2 Hz tone: 0.50 (inside passband)")
    print(f"  100 Hz interferer: 0.30 (should be rejected)")
    
    # Decimate
    decimated = decimate_for_upload(test_signal, input_rate=16000, output_rate=10)
    
    if decimated is None:
        print("  ❌ Decimation failed!")
        return
    
    print(f"Output signal: {len(decimated)} samples @ 10 Hz")
    
    # Analyze output spectrum
    fft_out = np.fft.fft(decimated)
    freqs_out = np.fft.fftfreq(len(decimated), d=0.1)  # 10 Hz sample rate
    
    # Find peaks
    dc_idx = 0
    doppler_idx = np.argmin(np.abs(freqs_out - 2.0))
    interferer_idx = np.argmin(np.abs(freqs_out - 100 % 10))  # Aliased position
    
    dc_power = 20 * np.log10(np.abs(fft_out[dc_idx]) / len(decimated))
    doppler_power = 20 * np.log10(np.abs(fft_out[doppler_idx]) / len(decimated))
    interferer_power = 20 * np.log10(np.abs(fft_out[interferer_idx]) / len(decimated))
    
    print(f"\nOutput spectrum:")
    print(f"  DC power: {dc_power:.1f} dB (expected: ~-20 dB)")
    print(f"  2 Hz Doppler: {doppler_power:.1f} dB (expected: ~-6 dB)")
    print(f"  100 Hz leakage: {interferer_power:.1f} dB (expected: < -80 dB)")
    
    if interferer_power > -60:
        print(f"  ⚠️  HIGH ALIASING! 100 Hz leaking through at {interferer_power:.1f} dB")
        print(f"  🎯 THIS IS YOUR PROBLEM: Insufficient anti-aliasing in CIC stage")
    else:
        print(f"  ✅ Good alias rejection")


def plot_filter_responses(responses: dict, output_path: Path):
    """Generate diagnostic plots"""
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    
    # CIC filter
    w, h_cic, true_cic = responses['cic']
    axes[0].plot(w, 20*np.log10(np.abs(h_cic)), label='Boxcar approximation (current)')
    axes[0].plot(w, 20*np.log10(true_cic), '--', label='True CIC response', alpha=0.7)
    axes[0].axhline(-60, color='r', linestyle=':', label='-60 dB threshold')
    axes[0].set_xlim(0, 500)
    axes[0].set_ylim(-100, 5)
    axes[0].set_xlabel('Frequency (Hz)')
    axes[0].set_ylabel('Magnitude (dB)')
    axes[0].set_title('Stage 1: CIC Filter (16 kHz → 400 Hz)')
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()
    
    # Compensation FIR
    w_comp, h_comp = responses['comp']
    axes[1].plot(w_comp, 20*np.log10(np.abs(h_comp)))
    axes[1].axvline(5, color='r', linestyle=':', label='5 Hz passband edge')
    axes[1].set_xlim(0, 50)
    axes[1].set_ylim(-20, 10)
    axes[1].set_xlabel('Frequency (Hz)')
    axes[1].set_ylabel('Magnitude (dB)')
    axes[1].set_title('Stage 2: Compensation FIR (400 Hz)')
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    
    # Final FIR
    w_final, h_final = responses['final']
    axes[2].plot(w_final, 20*np.log10(np.abs(h_final)))
    axes[2].axvline(5, color='g', linestyle=':', label='5 Hz cutoff')
    axes[2].axvline(6, color='r', linestyle=':', label='6 Hz stopband')
    axes[2].set_xlim(0, 20)
    axes[2].set_ylim(-120, 5)
    axes[2].set_xlabel('Frequency (Hz)')
    axes[2].set_ylabel('Magnitude (dB)')
    axes[2].set_title('Stage 3: Final FIR (400 Hz → 10 Hz)')
    axes[2].grid(True, alpha=0.3)
    axes[2].legend()
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"\n📊 Filter response plots saved to: {output_path}")


def main():
    """Run full diagnostic suite"""
    print("GRAPE Decimation Artifact Diagnostic Tool")
    print("=" * 80)
    
    # Test with synthetic signal first (no file dependencies)
    test_synthetic_signal()
    
    # Analyze filter designs
    responses = analyze_filter_responses()
    
    # Generate plots
    output_dir = Path(__file__).parent.parent / 'logs'
    output_dir.mkdir(exist_ok=True)
    plot_path = output_dir / 'decimation_filter_response.png'
    plot_filter_responses(responses, plot_path)
    
    # If NPZ files provided, analyze them
    if len(sys.argv) >= 3:
        npz_16k = Path(sys.argv[1])
        npz_10hz = Path(sys.argv[2])
        
        if npz_16k.exists() and npz_10hz.exists():
            check_data_types(npz_16k, npz_10hz)
        else:
            print(f"\n⚠️  NPZ files not found, skipping dtype verification")
    
    print("\n" + "=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)
    print("\n🔍 RECOMMENDATION:")
    print("If synthetic test shows >-60 dB at 100 Hz interferer:")
    print("  1. Replace boxcar CIC approximation with true multi-rate CIC")
    print("  2. Or increase CIC stage decimation factor and add intermediate stage")
    print("  3. Verify no aliasing from 200-8000 Hz band")


if __name__ == '__main__':
    main()
