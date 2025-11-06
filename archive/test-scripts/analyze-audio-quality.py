#!/usr/bin/env python3
"""Analyze audio file for choppiness issues"""
import wave
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def analyze_audio(filename):
    """Analyze audio for gaps, discontinuities, and quality issues"""
    print(f"Analyzing {filename}...")
    
    # Load WAV file
    with wave.open(filename, 'r') as w:
        rate = w.getframerate()
        frames = w.getnframes()
        audio_bytes = w.readframes(frames)
    
    # Convert to numpy array
    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    
    print(f"\n=== BASIC INFO ===")
    print(f"Sample rate: {rate} Hz")
    print(f"Samples: {len(audio)}")
    print(f"Duration: {len(audio)/rate:.2f} seconds")
    print(f"Value range: {np.min(audio):.0f} to {np.max(audio):.0f}")
    
    # Check for zeros (silence/dropouts)
    zero_samples = np.sum(audio == 0)
    zero_percent = zero_samples / len(audio) * 100
    print(f"\n=== SILENCE/DROPOUTS ===")
    print(f"Zero samples: {zero_samples} ({zero_percent:.1f}%)")
    
    # Find consecutive zero runs (gaps)
    is_zero = (audio == 0)
    zero_changes = np.diff(is_zero.astype(int))
    gap_starts = np.where(zero_changes == 1)[0] + 1
    gap_ends = np.where(zero_changes == -1)[0] + 1
    
    if len(gap_starts) > 0 and len(gap_ends) > 0:
        # Handle edge cases
        if len(gap_ends) < len(gap_starts):
            gap_ends = np.append(gap_ends, len(audio))
        if gap_starts[0] > gap_ends[0]:
            gap_starts = np.insert(gap_starts, 0, 0)
        
        gap_lengths = gap_ends[:len(gap_starts)] - gap_starts
        gap_durations = gap_lengths / rate * 1000  # in ms
        
        significant_gaps = gap_durations > 10  # >10ms gaps
        if np.any(significant_gaps):
            print(f"\nSignificant gaps (>10ms):")
            for i, (start, length, dur) in enumerate(zip(gap_starts[significant_gaps], 
                                                          gap_lengths[significant_gaps],
                                                          gap_durations[significant_gaps])):
                if i < 10:  # Show first 10
                    print(f"  Gap at {start/rate:.3f}s: {length} samples ({dur:.1f}ms)")
            if np.sum(significant_gaps) > 10:
                print(f"  ... and {np.sum(significant_gaps) - 10} more gaps")
    
    # Check for discontinuities (sudden jumps)
    diff = np.abs(np.diff(audio))
    mean_diff = np.mean(diff)
    std_diff = np.std(diff)
    threshold = mean_diff + 5 * std_diff
    
    discontinuities = np.where(diff > threshold)[0]
    print(f"\n=== DISCONTINUITIES ===")
    print(f"Mean change: {mean_diff:.1f}")
    print(f"Large jumps (>5σ): {len(discontinuities)}")
    if len(discontinuities) > 0:
        print(f"First 10 discontinuities:")
        for i, idx in enumerate(discontinuities[:10]):
            print(f"  At {idx/rate:.3f}s: jump of {diff[idx]:.0f}")
    
    # Check RMS level over time
    chunk_size = rate // 10  # 100ms chunks
    num_chunks = len(audio) // chunk_size
    rms_levels = []
    
    for i in range(num_chunks):
        chunk = audio[i*chunk_size:(i+1)*chunk_size]
        rms = np.sqrt(np.mean(chunk**2))
        rms_levels.append(rms)
    
    rms_levels = np.array(rms_levels)
    
    print(f"\n=== SIGNAL LEVEL (RMS per 100ms) ===")
    print(f"Mean RMS: {np.mean(rms_levels):.1f}")
    print(f"Min RMS: {np.min(rms_levels):.1f}")
    print(f"Max RMS: {np.max(rms_levels):.1f}")
    print(f"Std dev: {np.std(rms_levels):.1f}")
    
    # Check for very low level chunks (might sound like dropout)
    low_level_chunks = rms_levels < (np.mean(rms_levels) * 0.1)
    print(f"Very low level chunks (<10% of mean): {np.sum(low_level_chunks)}/{len(rms_levels)}")
    
    # Plot waveform and RMS
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))
    
    # Waveform
    time = np.arange(len(audio)) / rate
    axes[0].plot(time, audio, linewidth=0.5)
    axes[0].set_title('Audio Waveform')
    axes[0].set_xlabel('Time (s)')
    axes[0].set_ylabel('Amplitude')
    axes[0].grid(True, alpha=0.3)
    
    # RMS over time
    rms_time = np.arange(len(rms_levels)) * 0.1  # 100ms chunks
    axes[1].plot(rms_time, rms_levels, linewidth=2)
    axes[1].set_title('RMS Level (100ms windows)')
    axes[1].set_xlabel('Time (s)')
    axes[1].set_ylabel('RMS')
    axes[1].grid(True, alpha=0.3)
    axes[1].axhline(y=np.mean(rms_levels), color='r', linestyle='--', label='Mean')
    axes[1].legend()
    
    # Discontinuities
    axes[2].plot(time[:-1], diff, linewidth=0.5)
    axes[2].axhline(y=threshold, color='r', linestyle='--', label=f'Threshold (5σ)')
    axes[2].set_title('Sample-to-sample differences (discontinuities)')
    axes[2].set_xlabel('Time (s)')
    axes[2].set_ylabel('Abs difference')
    axes[2].set_yscale('log')
    axes[2].grid(True, alpha=0.3)
    axes[2].legend()
    
    plt.tight_layout()
    plt.savefig('/tmp/audio-analysis.png', dpi=150)
    print(f"\n✓ Plot saved to /tmp/audio-analysis.png")
    
    # DIAGNOSIS
    print(f"\n=== DIAGNOSIS ===")
    issues = []
    
    if zero_percent > 10:
        issues.append(f"⚠️ HIGH SILENCE: {zero_percent:.1f}% zeros (gaps in audio)")
    
    if len(discontinuities) > len(audio) / 1000:
        issues.append(f"⚠️ MANY DISCONTINUITIES: {len(discontinuities)} large jumps")
    
    if np.sum(low_level_chunks) > len(rms_levels) * 0.2:
        issues.append(f"⚠️ FREQUENT DROPOUTS: {np.sum(low_level_chunks)} low-level chunks")
    
    if len(issues) == 0:
        print("✓ No obvious issues detected - audio should be smooth")
    else:
        print("Issues found:")
        for issue in issues:
            print(f"  {issue}")
        
        print("\nLikely cause of choppiness:")
        if zero_percent > 10:
            print("  → Silence/gaps in audio stream (queue starvation?)")
        if len(discontinuities) > 100:
            print("  → Abrupt transitions (packet loss or buffer underrun?)")

if __name__ == '__main__':
    import sys
    filename = sys.argv[1] if len(sys.argv) > 1 else '/tmp/wwv-8khz-decimated.wav'
    analyze_audio(filename)
