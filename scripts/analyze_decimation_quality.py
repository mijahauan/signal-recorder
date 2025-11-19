#!/usr/bin/env python3
"""
Analyze decimation quality by comparing 200Hz→10Hz vs 16kHz→10Hz

Metrics:
1. Spectral purity - measure peak sharpness, spurious peaks
2. Noise floor - compare regions away from carrier
3. Phase continuity - unwrapped phase smoothness
4. Frequency stability - variance in instantaneous frequency
"""

import argparse
import numpy as np
from pathlib import Path
from scipy import signal as scipy_signal
from scipy.stats import entropy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def analyze_spectral_purity(iq_samples, fs, label):
    """
    Measure spectral purity metrics
    
    Returns:
        dict with peak_snr, spurious_free_dynamic_range, spectral_entropy
    """
    # Power spectral density
    freqs, psd = scipy_signal.welch(iq_samples, fs=fs, nperseg=min(512, len(iq_samples)))
    psd_db = 10 * np.log10(psd + 1e-10)
    
    # Find main peak
    peak_idx = np.argmax(psd_db)
    peak_power = psd_db[peak_idx]
    peak_freq = freqs[peak_idx]
    
    # Noise floor (median of lower 20% of power)
    noise_floor = np.percentile(psd_db, 20)
    peak_snr = peak_power - noise_floor
    
    # Spurious-free dynamic range (distance to second highest peak)
    # Exclude region around main peak (±0.5 Hz)
    mask = np.abs(freqs - peak_freq) > 0.5
    if np.any(mask):
        spurious_peak = np.max(psd_db[mask])
        sfdr = peak_power - spurious_peak
    else:
        sfdr = np.inf
    
    # Spectral entropy (measure of spectral concentration)
    psd_norm = psd / np.sum(psd)
    spec_entropy = entropy(psd_norm)
    
    return {
        'peak_freq': peak_freq,
        'peak_snr_db': peak_snr,
        'sfdr_db': sfdr,
        'spectral_entropy': spec_entropy,
        'noise_floor_db': noise_floor,
        'psd_freqs': freqs,
        'psd_db': psd_db
    }


def analyze_phase_continuity(iq_samples, fs):
    """
    Measure phase smoothness (proxy for decimation artifacts)
    
    Returns:
        dict with phase_variance, phase_jitter, freq_std
    """
    # Unwrap phase
    phase = np.unwrap(np.angle(iq_samples))
    
    # Phase derivative (instantaneous frequency)
    inst_freq = np.diff(phase) * fs / (2 * np.pi)
    
    # Metrics
    phase_diff = np.diff(phase)
    phase_var = np.var(phase_diff)
    
    # Phase jitter (high-frequency phase noise)
    # Apply high-pass filter to phase
    sos = scipy_signal.butter(4, 0.5, btype='high', fs=fs, output='sos')
    phase_hp = scipy_signal.sosfilt(sos, phase)
    phase_jitter = np.std(phase_hp)
    
    # Frequency stability
    freq_std = np.std(inst_freq)
    freq_mean = np.mean(inst_freq)
    
    return {
        'phase_variance': phase_var,
        'phase_jitter_rad': phase_jitter,
        'freq_std_hz': freq_std,
        'freq_mean_hz': freq_mean,
        'inst_freq': inst_freq
    }


def analyze_time_domain_quality(iq_samples):
    """
    Measure amplitude stability and discontinuities
    """
    amplitude = np.abs(iq_samples)
    
    # Amplitude variance (should be low for carrier)
    amp_var = np.var(amplitude)
    amp_std = np.std(amplitude)
    amp_mean = np.mean(amplitude)
    
    # Detect discontinuities (large amplitude jumps)
    amp_diff = np.abs(np.diff(amplitude))
    discontinuities = np.sum(amp_diff > 3 * np.std(amp_diff))
    
    return {
        'amplitude_mean': amp_mean,
        'amplitude_std': amp_std,
        'amplitude_cv': amp_std / amp_mean if amp_mean > 0 else np.inf,
        'discontinuities': discontinuities
    }


def compare_decimation_methods(wide_file, carrier_file, output_dir):
    """
    Load both files and generate comparison report
    """
    print(f"\nAnalyzing decimation quality comparison")
    print("="*60)
    
    # Load data
    wide_data = np.load(wide_file)
    carrier_data = np.load(carrier_file)
    
    wide_iq = wide_data['iq']
    carrier_iq = carrier_data['iq']
    
    print(f"\nWide (16kHz→10Hz):   {len(wide_iq)} samples")
    print(f"Carrier (200Hz→10Hz): {len(carrier_iq)} samples")
    
    # Take matching segments
    n_samples = min(len(wide_iq), len(carrier_iq))
    wide_iq = wide_iq[:n_samples]
    carrier_iq = carrier_iq[:n_samples]
    
    # Analyze both
    print("\n" + "="*60)
    print("SPECTRAL PURITY ANALYSIS")
    print("="*60)
    
    wide_spectral = analyze_spectral_purity(wide_iq, 10.0, "Wide")
    carrier_spectral = analyze_spectral_purity(carrier_iq, 10.0, "Carrier")
    
    print(f"\nWide (16kHz→10Hz):")
    print(f"  Peak frequency: {wide_spectral['peak_freq']:.3f} Hz")
    print(f"  Peak SNR: {wide_spectral['peak_snr_db']:.1f} dB")
    print(f"  SFDR: {wide_spectral['sfdr_db']:.1f} dB")
    print(f"  Spectral entropy: {wide_spectral['spectral_entropy']:.3f}")
    print(f"  Noise floor: {wide_spectral['noise_floor_db']:.1f} dB")
    
    print(f"\nCarrier (200Hz→10Hz):")
    print(f"  Peak frequency: {carrier_spectral['peak_freq']:.3f} Hz")
    print(f"  Peak SNR: {carrier_spectral['peak_snr_db']:.1f} dB")
    print(f"  SFDR: {carrier_spectral['sfdr_db']:.1f} dB")
    print(f"  Spectral entropy: {carrier_spectral['spectral_entropy']:.3f}")
    print(f"  Noise floor: {carrier_spectral['noise_floor_db']:.1f} dB")
    
    print(f"\nΔ SNR: {carrier_spectral['peak_snr_db'] - wide_spectral['peak_snr_db']:+.1f} dB (carrier advantage)")
    print(f"Δ SFDR: {carrier_spectral['sfdr_db'] - wide_spectral['sfdr_db']:+.1f} dB (carrier advantage)")
    
    # Phase continuity
    print("\n" + "="*60)
    print("PHASE CONTINUITY ANALYSIS")
    print("="*60)
    
    wide_phase = analyze_phase_continuity(wide_iq, 10.0)
    carrier_phase = analyze_phase_continuity(carrier_iq, 10.0)
    
    print(f"\nWide (16kHz→10Hz):")
    print(f"  Phase jitter: {wide_phase['phase_jitter_rad']:.6f} rad")
    print(f"  Frequency std: {wide_phase['freq_std_hz']:.6f} Hz")
    print(f"  Mean frequency: {wide_phase['freq_mean_hz']:.6f} Hz")
    
    print(f"\nCarrier (200Hz→10Hz):")
    print(f"  Phase jitter: {carrier_phase['phase_jitter_rad']:.6f} rad")
    print(f"  Frequency std: {carrier_phase['freq_std_hz']:.6f} Hz")
    print(f"  Mean frequency: {carrier_phase['freq_mean_hz']:.6f} Hz")
    
    jitter_ratio = wide_phase['phase_jitter_rad'] / carrier_phase['phase_jitter_rad']
    print(f"\nPhase jitter ratio (wide/carrier): {jitter_ratio:.2f}x")
    
    # Time domain
    print("\n" + "="*60)
    print("TIME DOMAIN QUALITY")
    print("="*60)
    
    wide_time = analyze_time_domain_quality(wide_iq)
    carrier_time = analyze_time_domain_quality(carrier_iq)
    
    print(f"\nWide (16kHz→10Hz):")
    print(f"  Amplitude CV: {wide_time['amplitude_cv']:.4f}")
    print(f"  Discontinuities: {wide_time['discontinuities']}")
    
    print(f"\nCarrier (200Hz→10Hz):")
    print(f"  Amplitude CV: {carrier_time['amplitude_cv']:.4f}")
    print(f"  Discontinuities: {carrier_time['discontinuities']}")
    
    # Generate plots
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # PSD comparison
    ax = axes[0, 0]
    ax.plot(wide_spectral['psd_freqs'], wide_spectral['psd_db'], 
            label='Wide (16kHz→10Hz)', alpha=0.7)
    ax.plot(carrier_spectral['psd_freqs'], carrier_spectral['psd_db'],
            label='Carrier (200Hz→10Hz)', alpha=0.7)
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Power (dB)')
    ax.set_title('Power Spectral Density Comparison')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-5, 5)
    
    # Instantaneous frequency
    ax = axes[0, 1]
    t_wide = np.arange(len(wide_phase['inst_freq'])) / 10.0
    t_carrier = np.arange(len(carrier_phase['inst_freq'])) / 10.0
    ax.plot(t_wide, wide_phase['inst_freq'], label='Wide', alpha=0.7)
    ax.plot(t_carrier, carrier_phase['inst_freq'], label='Carrier', alpha=0.7)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Instantaneous Frequency (Hz)')
    ax.set_title('Frequency Stability Comparison')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Amplitude over time
    ax = axes[1, 0]
    t = np.arange(min(500, len(wide_iq))) / 10.0
    ax.plot(t, np.abs(wide_iq[:len(t)]), label='Wide', alpha=0.7)
    ax.plot(t, np.abs(carrier_iq[:len(t)]), label='Carrier', alpha=0.7)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Amplitude')
    ax.set_title('Amplitude Stability (first 50s)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Summary bar chart
    ax = axes[1, 1]
    metrics = ['SNR\n(dB)', 'SFDR\n(dB)', 'Phase Jitter\n(×100 rad)', 'Freq Std\n(×100 Hz)']
    wide_vals = [
        wide_spectral['peak_snr_db'],
        wide_spectral['sfdr_db'],
        wide_phase['phase_jitter_rad'] * 100,
        wide_phase['freq_std_hz'] * 100
    ]
    carrier_vals = [
        carrier_spectral['peak_snr_db'],
        carrier_spectral['sfdr_db'],
        carrier_phase['phase_jitter_rad'] * 100,
        carrier_phase['freq_std_hz'] * 100
    ]
    
    x = np.arange(len(metrics))
    width = 0.35
    ax.bar(x - width/2, wide_vals, width, label='Wide (16kHz→10Hz)', alpha=0.7)
    ax.bar(x + width/2, carrier_vals, width, label='Carrier (200Hz→10Hz)', alpha=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_ylabel('Value')
    ax.set_title('Quality Metrics Summary')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    output_file = output_dir / 'decimation_quality_comparison.png'
    plt.savefig(output_file, dpi=150)
    print(f"\n✅ Saved comparison plot: {output_file}")
    
    return {
        'wide': {
            'spectral': wide_spectral,
            'phase': wide_phase,
            'time': wide_time
        },
        'carrier': {
            'spectral': carrier_spectral,
            'phase': carrier_phase,
            'time': carrier_time
        }
    }


def main():
    parser = argparse.ArgumentParser(description='Analyze decimation quality')
    parser.add_argument('--wide-file', required=True, help='Wide channel decimated NPZ file')
    parser.add_argument('--carrier-file', required=True, help='Carrier channel decimated NPZ file')
    parser.add_argument('--output-dir', default='/tmp', help='Output directory for plots')
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = compare_decimation_methods(
        Path(args.wide_file),
        Path(args.carrier_file),
        output_dir
    )


if __name__ == '__main__':
    main()
