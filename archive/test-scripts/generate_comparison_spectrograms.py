#!/usr/bin/env python3
"""
Generate 24-hour spectrogram comparison for WWV 5 MHz on 2025-11-19
Compares original decimation.py vs decimation_improved.py
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import sys
from scipy import signal as sp_signal
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.decimation import decimate_for_upload as decimate_original
from signal_recorder.decimation_improved import decimate_for_upload_improved


def load_day_data(archive_dir: Path, date_str: str = "20251119"):
    """Load all NPZ files for a given date"""
    pattern = f"{date_str}*_iq.npz"
    files = sorted(archive_dir.glob(pattern))
    
    print(f"Found {len(files)} files for {date_str}")
    
    iq_data = []
    timestamps = []
    
    for i, f in enumerate(files):
        if i % 100 == 0:
            print(f"  Loading file {i}/{len(files)}...")
        
        try:
            data = np.load(f)
            iq = data['iq']
            iq_data.append(iq)
            
            # Extract timestamp from filename: 20251119T165700Z_5000000_iq.npz
            fname = f.stem
            ts_str = fname.split('_')[0]  # "20251119T165700Z"
            dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ")
            timestamps.append(dt.timestamp())
            
        except Exception as e:
            print(f"  ⚠️  Failed to load {f.name}: {e}")
    
    print(f"✅ Loaded {len(iq_data)} files")
    return iq_data, timestamps


def decimate_all(iq_data_list, method='original'):
    """Decimate all minute files"""
    decimated = []
    func = decimate_original if method == 'original' else decimate_for_upload_improved
    
    print(f"\nDecimating with {method} method...")
    for i, iq in enumerate(iq_data_list):
        if i % 100 == 0:
            print(f"  Processing {i}/{len(iq_data_list)}...")
        
        result = func(iq, 16000, 10)
        if result is not None:
            decimated.append(result)
    
    # Concatenate all
    all_iq = np.concatenate(decimated)
    print(f"✅ {method}: {len(all_iq)} samples @ 10 Hz")
    return all_iq


def create_spectrogram(iq_data, sample_rate=10):
    """Create spectrogram"""
    # Use 128-point FFT with 50% overlap (match original script)
    nperseg = 128
    noverlap = nperseg // 2
    
    f, t, Sxx = sp_signal.spectrogram(
        iq_data,
        fs=sample_rate,
        nperseg=nperseg,
        noverlap=noverlap,
        window='hann',
        scaling='density',
        mode='magnitude',
        return_onesided=False  # Critical for complex IQ data
    )
    
    # Convert to dB
    Sxx_db = 10 * np.log10(Sxx + 1e-10)
    
    # Shift frequencies to center at 0 (CRITICAL - matches original code)
    f_shifted = np.fft.fftshift(f)
    Sxx_db_shifted = np.fft.fftshift(Sxx_db, axes=0)
    
    return f_shifted, t, Sxx_db_shifted


def plot_comparison(f_orig, t_orig, Sxx_orig, f_imp, t_imp, Sxx_imp, output_path: Path):
    """Create comparison plot"""
    fig, axes = plt.subplots(2, 1, figsize=(20, 10))
    
    # Convert time to hours
    t_orig_hr = t_orig / 3600
    t_imp_hr = t_imp / 3600
    
    # Common color scale based on percentiles (match original method)
    vmin = np.percentile(np.concatenate([Sxx_orig.flatten(), Sxx_imp.flatten()]), 5)
    vmax = np.percentile(np.concatenate([Sxx_orig.flatten(), Sxx_imp.flatten()]), 95)
    
    # Original method
    im1 = axes[0].pcolormesh(
        t_orig_hr, f_orig, Sxx_orig,
        shading='auto',
        cmap='viridis',
        vmin=vmin,
        vmax=vmax
    )
    axes[0].set_ylabel('Frequency (Hz)', fontsize=12)
    axes[0].set_title('Original Decimation (decimation.py) - WWV 5 MHz 2025-11-19', 
                     fontsize=14, fontweight='bold')
    axes[0].set_ylim(-5, 5)
    axes[0].grid(True, alpha=0.3, color='white', linewidth=0.5)
    axes[0].axhline(0, color='red', linestyle='--', alpha=0.7, linewidth=1.5)
    
    # Highlight artifact regions
    axes[0].axhspan(-4.5, -3.5, alpha=0.15, color='red')
    axes[0].axhspan(3.5, 4.5, alpha=0.15, color='red')
    axes[0].text(0.5, 4.0, '← Artifact Region', color='white', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='red', alpha=0.5))
    
    cbar1 = fig.colorbar(im1, ax=axes[0], label='Magnitude (dB)')
    
    # Improved method
    im2 = axes[1].pcolormesh(
        t_imp_hr, f_imp, Sxx_imp,
        shading='auto',
        cmap='viridis',
        vmin=vmin,
        vmax=vmax
    )
    axes[1].set_ylabel('Frequency (Hz)', fontsize=12)
    axes[1].set_xlabel('Time (hours since 00:00 UTC)', fontsize=12)
    axes[1].set_title('Improved Decimation (decimation_improved.py) - WWV 5 MHz 2025-11-19', 
                     fontsize=14, fontweight='bold')
    axes[1].set_ylim(-5, 5)
    axes[1].grid(True, alpha=0.3, color='white', linewidth=0.5)
    axes[1].axhline(0, color='red', linestyle='--', alpha=0.7, linewidth=1.5)
    
    cbar2 = fig.colorbar(im2, ax=axes[1], label='Magnitude (dB)')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n📊 Comparison saved: {output_path}")


def main():
    print("=" * 80)
    print("SPECTROGRAM COMPARISON: ORIGINAL VS IMPROVED DECIMATION")
    print("=" * 80)
    print("\nWWV 5 MHz - November 19, 2025 (24 hours)")
    
    # Load data
    archive_dir = Path("/tmp/grape-test/archives/WWV_5_MHz")
    iq_data_list, timestamps = load_day_data(archive_dir, "20251119")
    
    if len(iq_data_list) == 0:
        print("❌ No data found!")
        return
    
    # Decimate with both methods
    iq_orig = decimate_all(iq_data_list, 'original')
    iq_imp = decimate_all(iq_data_list, 'improved')
    
    # Create spectrograms
    print("\nGenerating spectrograms...")
    print("  Original method...")
    f_orig, t_orig, Sxx_orig = create_spectrogram(iq_orig)
    
    print("  Improved method...")
    f_imp, t_imp, Sxx_imp = create_spectrogram(iq_imp)
    
    # Plot comparison
    output_dir = Path("logs")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "WWV_5MHz_20251119_decimation_comparison.png"
    
    print("\nCreating comparison plot...")
    plot_comparison(f_orig, t_orig, Sxx_orig, f_imp, t_imp, Sxx_imp, output_path)
    
    print("\n" + "=" * 80)
    print("COMPLETE")
    print("=" * 80)
    print(f"\n✅ Comparison spectrogram: {output_path}")
    print("\nKey differences to observe:")
    print("  - Original: Spectral artifacts around ±4 Hz (horizontal bands)")
    print("  - Improved: Clean spectrum, no artifacts")
    print("  - Both: Preserve Doppler variations (natural frequency drifts)")


if __name__ == '__main__':
    main()
