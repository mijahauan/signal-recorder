#!/usr/bin/env python3
"""
Compare timing methods: time_snap (TONE_LOCKED) vs NTP (NTP_SYNCED)

Approaches:
1. Cross-correlation between wide and carrier channels (same frequency)
   - Should be perfectly aligned if timing is identical
   - Time offset indicates timing difference
2. Phase comparison over time
   - Both should track same Doppler shifts
   - Phase drift indicates timing error accumulation
3. Metadata analysis
   - Compare time_snap_age vs ntp_offset over 24 hours
   - Show when each method is available
"""

import argparse
import numpy as np
from pathlib import Path
from scipy import signal as scipy_signal
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone


def load_channel_day(decimated_dir, date_str):
    """
    Load all decimated NPZ files for a day and extract timing metadata
    
    Returns:
        timestamps, iq_samples, timing_records
    """
    npz_files = sorted(decimated_dir.glob(f"{date_str}*_10hz.npz"))
    
    if not npz_files:
        return None, None, None
    
    all_iq = []
    all_timestamps = []
    timing_records = []
    
    for npz_file in npz_files:
        data = np.load(npz_file, allow_pickle=True)
        iq = data['iq']
        
        # Parse timestamp from filename
        filename = npz_file.name
        timestamp_str = filename.split('_')[0]  # YYYYMMDDTHHMMSSZ
        dt = datetime.strptime(timestamp_str, '%Y%m%dT%H%M%SZ')
        dt = dt.replace(tzinfo=timezone.utc)
        file_unix_ts = dt.timestamp()
        
        # Extract timing metadata
        timing_meta = data['timing_metadata'].item() if 'timing_metadata' in data else {}
        timing_records.append({
            'timestamp': file_unix_ts,
            'filename': npz_file.name,
            **timing_meta
        })
        
        # Generate timestamps for samples
        num_samples = len(iq)
        file_timestamps = file_unix_ts + np.arange(num_samples) / 10.0
        
        all_timestamps.append(file_timestamps)
        all_iq.append(iq)
    
    timestamps = np.concatenate(all_timestamps)
    iq_samples = np.concatenate(all_iq)
    
    return timestamps, iq_samples, timing_records


def cross_correlate_channels(wide_iq, carrier_iq, max_lag_samples=100):
    """
    Cross-correlate wide and carrier channels to find time offset
    
    Returns:
        time_offset_seconds, correlation_peak
    """
    # Use middle portion (avoid edge effects)
    n = min(len(wide_iq), len(carrier_iq), 6000)  # 10 minutes
    start = (min(len(wide_iq), len(carrier_iq)) - n) // 2
    
    wide_seg = wide_iq[start:start+n]
    carrier_seg = carrier_iq[start:start+n]
    
    # Normalize
    wide_norm = (wide_seg - np.mean(wide_seg)) / np.std(wide_seg)
    carrier_norm = (carrier_seg - np.mean(carrier_seg)) / np.std(carrier_seg)
    
    # Cross-correlation
    correlation = np.correlate(wide_norm, carrier_norm, mode='full')
    lags = np.arange(-len(wide_norm)+1, len(wide_norm))
    
    # Restrict to reasonable lag range
    valid_range = (np.abs(lags) <= max_lag_samples)
    correlation = correlation[valid_range]
    lags = lags[valid_range]
    
    # Find peak
    peak_idx = np.argmax(np.abs(correlation))
    time_offset = lags[peak_idx] / 10.0  # Convert to seconds
    correlation_peak = correlation[peak_idx] / len(wide_norm)  # Normalize
    
    return time_offset, correlation_peak, lags, correlation


def compare_phase_evolution(wide_iq, carrier_iq, timestamps_wide, timestamps_carrier):
    """
    Compare phase evolution between channels
    
    Returns phase difference statistics
    """
    # Resample to common time grid
    n = min(len(wide_iq), len(carrier_iq))
    wide_iq = wide_iq[:n]
    carrier_iq = carrier_iq[:n]
    
    # Unwrap phases
    wide_phase = np.unwrap(np.angle(wide_iq))
    carrier_phase = np.unwrap(np.angle(carrier_iq))
    
    # Phase difference (should be constant if timing perfect)
    phase_diff = wide_phase - carrier_phase
    phase_diff_unwrapped = np.unwrap(phase_diff)
    
    # Detrend (remove constant offset)
    phase_diff_detrend = phase_diff_unwrapped - np.mean(phase_diff_unwrapped)
    
    # Phase drift over time (should be zero)
    t = np.arange(len(phase_diff_detrend)) / 10.0  # seconds
    phase_drift_rate = np.polyfit(t, phase_diff_detrend, 1)[0]  # rad/s
    
    return {
        'phase_diff_std_rad': np.std(phase_diff_detrend),
        'phase_diff_range_rad': np.ptp(phase_diff_detrend),
        'phase_drift_rate_rad_per_s': phase_drift_rate,
        'phase_diff': phase_diff_detrend,
        'time': t
    }


def analyze_timing_metadata(timing_records_wide, timing_records_carrier):
    """
    Analyze timing quality over 24 hours
    """
    print("\n" + "="*60)
    print("TIMING METADATA ANALYSIS")
    print("="*60)
    
    # Count by timing quality
    wide_qualities = [r.get('quality', 'unknown') for r in timing_records_wide]
    carrier_qualities = [r.get('quality', 'unknown') for r in timing_records_carrier]
    
    print(f"\nWide channel timing distribution:")
    for quality in set(wide_qualities):
        count = wide_qualities.count(quality)
        pct = 100 * count / len(wide_qualities)
        print(f"  {quality}: {count}/{len(wide_qualities)} ({pct:.1f}%)")
    
    print(f"\nCarrier channel timing distribution:")
    for quality in set(carrier_qualities):
        count = carrier_qualities.count(quality)
        pct = 100 * count / len(carrier_qualities)
        print(f"  {quality}: {count}/{len(carrier_qualities)} ({pct:.1f}%)")
    
    # Extract offsets
    wide_snap_ages = [r.get('time_snap_age_seconds', np.nan) for r in timing_records_wide]
    carrier_ntp_offsets = [r.get('ntp_offset_ms', np.nan) for r in timing_records_carrier]
    
    # Time series
    wide_times = [r['timestamp'] for r in timing_records_wide]
    carrier_times = [r['timestamp'] for r in timing_records_carrier]
    
    return {
        'wide_times': wide_times,
        'wide_snap_ages': wide_snap_ages,
        'carrier_times': carrier_times,
        'carrier_ntp_offsets': carrier_ntp_offsets
    }


def compare_timing(wide_decimated_dir, carrier_decimated_dir, date_str, output_dir):
    """
    Full timing comparison between wide (time_snap) and carrier (NTP)
    """
    print(f"\nTiming Method Comparison: {date_str}")
    print("="*60)
    print(f"Wide channel: {wide_decimated_dir}")
    print(f"Carrier channel: {carrier_decimated_dir}")
    
    # Load data
    print("\nLoading data...")
    wide_ts, wide_iq, timing_wide = load_channel_day(wide_decimated_dir, date_str)
    carrier_ts, carrier_iq, timing_carrier = load_channel_day(carrier_decimated_dir, date_str)
    
    if wide_iq is None or carrier_iq is None:
        print("ERROR: Could not load data")
        return
    
    print(f"Wide: {len(wide_iq):,} samples")
    print(f"Carrier: {len(carrier_iq):,} samples")
    
    # Cross-correlation
    print("\n" + "="*60)
    print("CROSS-CORRELATION ANALYSIS")
    print("="*60)
    
    time_offset, corr_peak, lags, correlation = cross_correlate_channels(wide_iq, carrier_iq)
    
    print(f"\nTime offset (wide - carrier): {time_offset*1000:.2f} ms")
    print(f"Correlation peak: {corr_peak:.4f}")
    
    if abs(time_offset) < 0.01:  # Within 10 ms
        print("✅ Excellent alignment (<10 ms)")
    elif abs(time_offset) < 0.1:  # Within 100 ms
        print("⚠️  Moderate offset (10-100 ms)")
    else:
        print("❌ Large offset (>100 ms)")
    
    # Phase evolution
    print("\n" + "="*60)
    print("PHASE COHERENCE ANALYSIS")
    print("="*60)
    
    phase_results = compare_phase_evolution(wide_iq, carrier_iq, wide_ts, carrier_ts)
    
    print(f"\nPhase difference std: {phase_results['phase_diff_std_rad']:.6f} rad")
    print(f"Phase difference range: {phase_results['phase_diff_range_rad']:.6f} rad")
    print(f"Phase drift rate: {phase_results['phase_drift_rate_rad_per_s']:.9f} rad/s")
    print(f"  (= {phase_results['phase_drift_rate_rad_per_s']*3600:.6f} rad/hour)")
    
    # Convert drift to timing error
    # For 10 MHz carrier: 1 cycle = 2π rad = 100 ns
    # drift_rate [rad/s] * (100 ns / 2π) = timing drift [ns/s]
    if 'MHz' in str(carrier_decimated_dir):
        freq_mhz = float(str(carrier_decimated_dir).split('_')[1])
        freq_hz = freq_mhz * 1e6
        timing_drift_ns_per_s = phase_results['phase_drift_rate_rad_per_s'] / (2 * np.pi * freq_hz) * 1e9
        print(f"\nTiming drift: {timing_drift_ns_per_s:.3f} ns/s")
        print(f"  (= {timing_drift_ns_per_s*3600:.1f} ns/hour)")
    
    # Metadata analysis
    metadata = analyze_timing_metadata(timing_wide, timing_carrier)
    
    # Generate plots
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)
    
    # Cross-correlation
    ax = fig.add_subplot(gs[0, :])
    ax.plot(lags / 10.0 * 1000, correlation / len(wide_iq[:6000]))  # Convert to ms
    ax.axvline(time_offset * 1000, color='red', linestyle='--', label=f'Peak: {time_offset*1000:.2f} ms')
    ax.set_xlabel('Time Offset (ms)')
    ax.set_ylabel('Normalized Correlation')
    ax.set_title('Cross-Correlation: Wide vs Carrier (time_snap vs NTP)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Phase difference over time
    ax = fig.add_subplot(gs[1, 0])
    t_hours = phase_results['time'] / 3600
    ax.plot(t_hours, phase_results['phase_diff'] * 180/np.pi, alpha=0.7)
    ax.set_xlabel('Time (hours)')
    ax.set_ylabel('Phase Difference (degrees)')
    ax.set_title('Phase Difference Evolution (detrended)')
    ax.grid(True, alpha=0.3)
    
    # Instantaneous frequency comparison
    ax = fig.add_subplot(gs[1, 1])
    n_show = min(6000, len(wide_iq))
    wide_freq = np.diff(np.unwrap(np.angle(wide_iq[:n_show]))) * 10 / (2*np.pi)
    carrier_freq = np.diff(np.unwrap(np.angle(carrier_iq[:n_show]))) * 10 / (2*np.pi)
    t_show = np.arange(len(wide_freq)) / 10 / 60  # minutes
    ax.plot(t_show, wide_freq, label='Wide (time_snap)', alpha=0.7)
    ax.plot(t_show, carrier_freq, label='Carrier (NTP)', alpha=0.7)
    ax.set_xlabel('Time (minutes)')
    ax.set_ylabel('Instantaneous Frequency (Hz)')
    ax.set_title('Frequency Tracking Comparison (first 10 min)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Timing metadata over day
    ax = fig.add_subplot(gs[2, 0])
    wide_hours = [(t - metadata['wide_times'][0]) / 3600 for t in metadata['wide_times']]
    ax.plot(wide_hours, metadata['wide_snap_ages'], 'o', markersize=2, alpha=0.5)
    ax.set_xlabel('Time (hours into day)')
    ax.set_ylabel('Time Snap Age (seconds)')
    ax.set_title('Wide Channel: Time Snap Freshness')
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    
    ax = fig.add_subplot(gs[2, 1])
    carrier_hours = [(t - metadata['carrier_times'][0]) / 3600 for t in metadata['carrier_times']]
    ax.plot(carrier_hours, metadata['carrier_ntp_offsets'], 'o', markersize=2, alpha=0.5)
    ax.set_xlabel('Time (hours into day)')
    ax.set_ylabel('NTP Offset (ms)')
    ax.set_title('Carrier Channel: NTP Sync Quality')
    ax.grid(True, alpha=0.3)
    ax.axhline(0, color='red', linestyle='--', alpha=0.5)
    
    plt.suptitle(f'Timing Comparison: time_snap vs NTP ({date_str})', fontsize=14, fontweight='bold')
    
    output_file = output_dir / f'timing_comparison_{date_str}.png'
    plt.savefig(output_file, dpi=150)
    print(f"\n✅ Saved timing comparison plot: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Compare timing methods (time_snap vs NTP)')
    parser.add_argument('--wide-dir', required=True, help='Wide channel decimated directory')
    parser.add_argument('--carrier-dir', required=True, help='Carrier channel decimated directory')
    parser.add_argument('--date', required=True, help='Date (YYYYMMDD)')
    parser.add_argument('--output-dir', default='/tmp', help='Output directory for plots')
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    compare_timing(
        Path(args.wide_dir),
        Path(args.carrier_dir),
        args.date,
        output_dir
    )


if __name__ == '__main__':
    main()
