#!/usr/bin/env python3
"""
Comprehensive WWV Signal Chain Diagnostic

Tests every step of the data pipeline to find where WWV detection fails.
"""

import sys
import numpy as np
import scipy.signal as signal
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

def analyze_iq_file(filepath):
    """Analyze an IQ minute file step by step"""
    
    print("="*80)
    print(f"ANALYZING: {filepath.name}")
    print("="*80)
    
    # Load data
    data = np.load(filepath)
    iq = data['iq']
    
    print(f"\n1. RAW IQ DATA:")
    print(f"   Total samples: {len(iq):,}")
    print(f"   Data type: {iq.dtype}")
    print(f"   Sample rate: 16000 Hz")
    print(f"   Duration: {len(iq)/16000:.1f} seconds")
    
    # Check if data is valid
    print(f"\n2. DATA VALIDITY:")
    print(f"   Complex? {np.iscomplexobj(iq)}")
    print(f"   Has NaN? {np.any(np.isnan(iq))}")
    print(f"   Has Inf? {np.any(np.isinf(iq))}")
    print(f"   All zeros? {np.all(iq == 0)}")
    print(f"   Non-zero samples: {np.count_nonzero(iq):,} ({np.count_nonzero(iq)/len(iq)*100:.1f}%)")
    
    # Signal level
    magnitude = np.abs(iq)
    print(f"\n3. SIGNAL LEVEL:")
    print(f"   Min magnitude: {np.min(magnitude):.6f}")
    print(f"   Max magnitude: {np.max(magnitude):.6f}")
    print(f"   Mean magnitude: {np.mean(magnitude):.6f}")
    print(f"   Std magnitude: {np.std(magnitude):.6f}")
    
    # Focus on first 2 seconds (where tone should be)
    first_2s = iq[:32000]  # 2s at 16 kHz
    magnitude_2s = np.abs(first_2s)
    
    print(f"\n4. FIRST 2 SECONDS (where WWV tone broadcasts):")
    print(f"   Max magnitude: {np.max(magnitude_2s):.6f}")
    print(f"   Mean magnitude: {np.mean(magnitude_2s):.6f}")
    
    # AM demodulation (what detector does)
    am_demod = np.abs(first_2s)
    am_demod_dc_removed = am_demod - np.mean(am_demod)
    
    print(f"\n5. AM DEMODULATION (np.abs(iq)):")
    print(f"   Signal after DC removal:")
    print(f"   Min: {np.min(am_demod_dc_removed):.6f}")
    print(f"   Max: {np.max(am_demod_dc_removed):.6f}")
    print(f"   RMS: {np.sqrt(np.mean(am_demod_dc_removed**2)):.6f}")
    
    # Spectrum analysis
    print(f"\n6. FREQUENCY CONTENT (first 2s):")
    freqs, psd = signal.welch(first_2s, fs=16000, nperseg=16384, noverlap=8192)
    
    # Find peaks
    peaks, properties = signal.find_peaks(psd, height=np.max(psd)*0.1)
    print(f"   Peaks found: {len(peaks)}")
    if len(peaks) > 0:
        for i, peak_idx in enumerate(peaks[:5]):  # Top 5
            peak_freq = freqs[peak_idx]
            peak_power = 10*np.log10(psd[peak_idx])
            print(f"   Peak {i+1}: {peak_freq:.1f} Hz at {peak_power:.1f} dB")
    
    # Check specifically at 1000 Hz
    idx_1k = np.argmin(np.abs(freqs - 1000))
    power_1k = 10*np.log10(psd[idx_1k])
    print(f"\n   Power at 1000 Hz: {power_1k:.1f} dB")
    
    # Compare to noise floor
    noise_floor = np.median(psd)
    noise_floor_db = 10*np.log10(noise_floor)
    snr_1k = power_1k - noise_floor_db
    print(f"   Noise floor: {noise_floor_db:.1f} dB")
    print(f"   SNR at 1000 Hz: {snr_1k:.1f} dB")
    
    # Bandpass filter 950-1050 Hz (what detector does)
    print(f"\n7. BANDPASS FILTER (950-1050 Hz):")
    sos = signal.butter(5, [950, 1050], btype='band', fs=16000, output='sos')
    filtered = signal.sosfiltfilt(sos, am_demod_dc_removed)
    
    print(f"   Filtered signal:")
    print(f"   Min: {np.min(filtered):.6f}")
    print(f"   Max: {np.max(filtered):.6f}")
    print(f"   RMS: {np.sqrt(np.mean(filtered**2)):.6f}")
    
    # Envelope detection
    print(f"\n8. ENVELOPE DETECTION:")
    analytic = signal.hilbert(filtered)
    envelope = np.abs(analytic)
    
    print(f"   Envelope:")
    print(f"   Min: {np.min(envelope):.6f}")
    print(f"   Max: {np.max(envelope):.6f}")
    print(f"   Mean: {np.mean(envelope):.6f}")
    
    # Normalize and threshold
    max_env = np.max(envelope)
    if max_env > 0:
        envelope_norm = envelope / max_env
        threshold = 0.5
        above_thresh = np.sum(envelope_norm > threshold)
        print(f"\n   Normalized envelope (max=1.0):")
        print(f"   Threshold: {threshold}")
        print(f"   Samples above threshold: {above_thresh} ({above_thresh/len(envelope_norm)*100:.1f}%)")
        
        # Find edges
        above = envelope_norm > threshold
        edges = np.diff(above.astype(int))
        rising = np.where(edges == 1)[0]
        falling = np.where(edges == -1)[0]
        
        print(f"   Rising edges: {len(rising)}")
        print(f"   Falling edges: {len(falling)}")
        
        if len(rising) > 0 and len(falling) > 0:
            onset = rising[0]
            offset = falling[falling > onset][0] if np.any(falling > onset) else None
            if offset:
                duration = (offset - onset) / 16000
                print(f"\n   TONE CANDIDATE:")
                print(f"   Start: {onset/16000:.3f}s")
                print(f"   End: {offset/16000:.3f}s")
                print(f"   Duration: {duration:.3f}s")
                if 0.5 <= duration <= 1.2:
                    print(f"   ✅ DURATION VALID (0.5-1.2s range)")
                    detection_success = True
                else:
                    print(f"   ❌ DURATION INVALID (need 0.5-1.2s)")
                    detection_success = False
        else:
            print(f"   ❌ NO EDGES - threshold never crossed")
    else:
        print(f"   ❌ ZERO ENVELOPE - no signal after filtering")
    
    # Create diagnostic plots
    fig, axes = plt.subplots(4, 2, figsize=(16, 12))
    
    # Time domain
    t = np.arange(len(first_2s)) / 16000
    axes[0, 0].plot(t, np.real(first_2s), alpha=0.7, label='I')
    axes[0, 0].plot(t, np.imag(first_2s), alpha=0.7, label='Q')
    axes[0, 0].set_title('Raw IQ (first 2s)')
    axes[0, 0].set_xlabel('Time (s)')
    axes[0, 0].legend()
    axes[0, 0].grid(True)
    
    # Magnitude
    axes[0, 1].plot(t, magnitude_2s)
    axes[0, 1].set_title('IQ Magnitude (AM Demod)')
    axes[0, 1].set_xlabel('Time (s)')
    axes[0, 1].grid(True)
    
    # Spectrum
    axes[1, 0].semilogy(freqs, psd)
    axes[1, 0].axvline(1000, color='r', linestyle='--', label='1000 Hz')
    axes[1, 0].set_xlim(0, 2000)
    axes[1, 0].set_title('Power Spectrum')
    axes[1, 0].set_xlabel('Frequency (Hz)')
    axes[1, 0].legend()
    axes[1, 0].grid(True)
    
    # Spectrum zoom
    idx_low = np.argmin(np.abs(freqs - 800))
    idx_high = np.argmin(np.abs(freqs - 1200))
    axes[1, 1].plot(freqs[idx_low:idx_high], 10*np.log10(psd[idx_low:idx_high]))
    axes[1, 1].axvline(1000, color='r', linestyle='--')
    axes[1, 1].set_title('Spectrum 800-1200 Hz')
    axes[1, 1].set_xlabel('Frequency (Hz)')
    axes[1, 1].set_ylabel('Power (dB)')
    axes[1, 1].grid(True)
    
    # Spectrogram
    axes[2, 0].specgram(am_demod_dc_removed, NFFT=2048, Fs=16000, noverlap=1024)
    axes[2, 0].set_ylim(800, 1200)
    axes[2, 0].set_title('Spectrogram 800-1200 Hz')
    axes[2, 0].set_ylabel('Frequency (Hz)')
    axes[2, 0].set_xlabel('Time (s)')
    
    # Filtered signal
    axes[2, 1].plot(t, filtered)
    axes[2, 1].set_title('After 950-1050 Hz Bandpass')
    axes[2, 1].set_xlabel('Time (s)')
    axes[2, 1].grid(True)
    
    # Envelope
    axes[3, 0].plot(t, envelope)
    axes[3, 0].set_title('Envelope of Filtered Signal')
    axes[3, 0].set_xlabel('Time (s)')
    axes[3, 0].grid(True)
    
    # Normalized envelope with threshold
    if max_env > 0:
        axes[3, 1].plot(t, envelope_norm)
        axes[3, 1].axhline(threshold, color='r', linestyle='--', label=f'Threshold {threshold}')
        axes[3, 1].set_title('Normalized Envelope + Threshold')
        axes[3, 1].set_xlabel('Time (s)')
        axes[3, 1].set_ylim(-0.1, 1.1)
        axes[3, 1].legend()
        axes[3, 1].grid(True)
    
    plt.tight_layout()
    output_path = f"/tmp/wwv_diagnostic_{filepath.stem}.png"
    plt.savefig(output_path, dpi=150)
    print(f"\n9. DIAGNOSTIC PLOT:")
    print(f"   Saved to: {output_path}")
    
    return detection_success if 'detection_success' in locals() else False


def main():
    import glob
    import sys
    
    # Allow specifying test directory
    test_dir = sys.argv[1] if len(sys.argv) > 1 else '/tmp/grape-16khz-test'
    
    # Find WWV 10 MHz files
    pattern = f'{test_dir}/data/*/*/*/WWV_10_MHz/*.npz'
    files = sorted(glob.glob(pattern))
    
    if not files:
        print(f"❌ No files found matching: {pattern}")
        print(f"\nRun a capture first:")
        print(f"  python3 scripts/test_v2_recorder_filtered.py --config config/grape-S000171.toml --duration 120 --output-dir {test_dir}")
        return 1
    
    print(f"Found {len(files)} WWV 10 MHz files\n")
    
    # Analyze the most recent complete minute
    for f in reversed(files):
        filepath = Path(f)
        data = np.load(filepath)
        if len(data['iq']) == 960000:  # Full minute at 16 kHz
            print(f"Analyzing most recent complete minute:")
            detected = analyze_iq_file(filepath)
            if detected:
                print(f"\n{'='*80}")
                print(f"✅ TONE DETECTED - System is working!")
                print(f"{'='*80}")
            else:
                print(f"\n{'='*80}")
                print(f"❌ NO TONE DETECTED - Check diagnostic plot for clues")
                print(f"{'='*80}")
            return 0
    
    print("❌ No complete minute files found (all padded)")
    return 1


if __name__ == '__main__':
    sys.exit(main())
