#!/usr/bin/env python3
"""
Generate daily spectrograms from GRAPE archive data - Memory-efficient version

Processes data in chunks to handle gaps and large datasets without OOM.
Creates full 24-hour spectrograms with proper gap handling.

Usage:
    python3 scripts/generate_spectrograms_v2.py --date 20251116 --channel "WWV 2.5 MHz"
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List
import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False
    print("ERROR: matplotlib package required")
    exit(1)

from scipy import signal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def read_npz_minute(file_path: Path) -> Tuple[Optional[float], Optional[np.ndarray]]:
    """
    Read a single minute NPZ file
    
    Returns:
        (timestamp, iq_samples) or (None, None) if error
    """
    try:
        data = np.load(file_path)
        
        # Check for new format (complex64 'iq' field)
        if 'iq' in data:
            iq_samples = data['iq']
            timestamp = float(data['unix_timestamp'])
            return timestamp, iq_samples
        
        # Old format (separate real/imag)
        elif 'iq_real' in data:
            iq_real = data['iq_real']
            iq_imag = data['iq_imag']
            timestamps = data['timestamps']
            return float(timestamps[0]), iq_real + 1j * iq_imag
        
        else:
            logger.warning(f"Unknown NPZ format in {file_path.name}")
            return None, None
            
    except Exception as e:
        logger.warning(f"Error reading {file_path.name}: {e}")
        return None, None


def compute_minute_spectrogram(iq_samples: np.ndarray, sample_rate: float = 16000) -> np.ndarray:
    """
    Compute spectrogram for one minute of IQ data
    
    Returns:
        Sxx_db: Spectrogram in dB (frequency x time)
    """
    nperseg = 1024
    noverlap = nperseg // 2
    
    f, t, Sxx = signal.spectrogram(
        iq_samples,
        fs=sample_rate,
        nperseg=nperseg,
        noverlap=noverlap,
        window='hann',
        scaling='density',
        mode='magnitude',
        return_onesided=False
    )
    
    # Convert to dB
    Sxx_db = 10 * np.log10(Sxx + 1e-10)
    
    # Shift frequencies to center at 0
    f_shifted = np.fft.fftshift(f)
    Sxx_db_shifted = np.fft.fftshift(Sxx_db, axes=0)
    
    return f_shifted, Sxx_db_shifted


def generate_daily_spectrogram(archive_dir: Path, date_str: str, channel_name: str, 
                               output_path: Path):
    """
    Generate full 24-hour spectrogram by processing minute-by-minute
    
    Args:
        archive_dir: Directory containing NPZ files
        date_str: Date in YYYYMMDD format
        channel_name: Channel name
        output_path: Where to save PNG
    """
    logger.info(f"Generating spectrogram for {channel_name} on {date_str}")
    
    # Parse date
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
    
    # Create list of expected minutes (1440 per day)
    expected_minutes = []
    current = day_start
    for i in range(1440):
        expected_minutes.append(current.strftime("%Y%m%dT%H%M%SZ"))
        current += timedelta(minutes=1)
    
    # Find available files
    npz_files = list(archive_dir.glob(f"{date_str}T*.npz"))
    file_dict = {f.name.split('_')[0]: f for f in npz_files}
    
    logger.info(f"Found {len(npz_files)} / 1440 minute files")
    
    # Process first VALID file to get frequency array (skip files with <100K samples)
    f_shifted = None
    for minute_ts in expected_minutes:
        if minute_ts in file_dict:
            _, iq = read_npz_minute(file_dict[minute_ts])
            if iq is not None and len(iq) > 100000:  # Require substantial data
                f_shifted, _ = compute_minute_spectrogram(iq)
                if f_shifted is not None:
                    break
    
    if f_shifted is None:
        logger.error("No valid data found!")
        return
    
    num_freqs = len(f_shifted)
    logger.info(f"Spectrogram dimensions: {num_freqs} frequencies x 1440 minutes")
    
    # Initialize full spectrogram array (freq x time)
    Sxx_full = np.full((num_freqs, 1440), np.nan)
    
    # Process each minute
    logger.info("Processing minutes...")
    for i, minute_ts in enumerate(expected_minutes):
        if (i + 1) % 100 == 0:
            logger.info(f"  Progress: {i+1}/1440 minutes")
        
        if minute_ts in file_dict:
            _, iq = read_npz_minute(file_dict[minute_ts])
            if iq is not None and len(iq) > 100000:  # Skip incomplete files
                _, Sxx_minute = compute_minute_spectrogram(iq)
                # Average across time within the minute
                Sxx_full[:, i] = np.mean(Sxx_minute, axis=1)
    
    logger.info("Creating plot...")
    
    # Create time grid for x-axis
    time_grid = [day_start + timedelta(minutes=i) for i in range(1440)]
    
    # Limit frequency range to ±5 Hz for Grape-style narrow spectrum
    freq_mask = (f_shifted >= -5) & (f_shifted <= 5)
    f_narrow = f_shifted[freq_mask]
    Sxx_narrow = Sxx_full[freq_mask, :]
    
    # Create figure - wider for better 24-hour spread
    fig, ax = plt.subplots(figsize=(30, 6), dpi=120)
    
    # Create Grape-style colormap (green → yellow → red)
    from matplotlib.colors import LinearSegmentedColormap
    colors = [(0.0, 0.3, 0.0), (0.0, 0.6, 0.0), (0.5, 1.0, 0.0), 
              (1.0, 1.0, 0.0), (1.0, 0.5, 0.0), (1.0, 0.0, 0.0)]
    grape_cmap = LinearSegmentedColormap.from_list('grape', colors, N=256)
    
    # Plot spectrogram
    im = ax.pcolormesh(
        time_grid,
        f_narrow,
        Sxx_narrow,
        shading='nearest',
        cmap=grape_cmap,
        vmin=np.nanpercentile(Sxx_narrow[~np.isnan(Sxx_narrow)], 1),
        vmax=np.nanpercentile(Sxx_narrow[~np.isnan(Sxx_narrow)], 99)
    )
    
    # Format axes - Grape style
    ax.set_ylabel('Doppler Shift (Hz)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Hours, UTC', fontsize=12, fontweight='bold')
    
    # Grape-style title
    freq_mhz = float(channel_name.split()[1]) if 'MHz' in channel_name else 0
    title = f'Grape Narrow Spectrum, Freq. = {freq_mhz:.1f} MHz, {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}T00-00'
    ax.set_title(title, fontsize=12, fontweight='bold', pad=10)
    
    # Force 24-hour range
    day_end = day_start + timedelta(hours=24)
    ax.set_xlim(day_start, day_end)
    ax.set_ylim(-5, 5)
    
    # Format x-axis - show hours only
    from matplotlib.dates import HourLocator
    ax.xaxis.set_major_locator(HourLocator(interval=2))
    ax.xaxis.set_major_formatter(DateFormatter('%H'))
    ax.tick_params(axis='both', labelsize=11)
    
    # Add colorbar
    cbar = fig.colorbar(im, ax=ax, label='Power (dB)', pad=0.01)
    cbar.ax.tick_params(labelsize=10)
    
    # Grid - subtle white lines like Grape
    ax.grid(True, alpha=0.2, linestyle='-', linewidth=0.5, color='white')
    
    # Save
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    
    logger.info(f"✅ Saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Generate daily spectrograms (memory-efficient)')
    parser.add_argument('--date', required=True, help='Date in YYYYMMDD format')
    parser.add_argument('--channel', required=True, help='Channel name (e.g., "WWV 2.5 MHz")')
    parser.add_argument('--data-root', default='/tmp/grape-test', help='Data root directory')
    args = parser.parse_args()
    
    # Convert channel name to directory name
    from grape_recorder.paths import GRAPEPaths
    paths = GRAPEPaths(args.data_root)
    archive_dir = paths.get_archive_dir(args.channel)
    
    if not archive_dir.exists():
        logger.error(f"Archive directory not found: {archive_dir}")
        return
    
    # Output directory
    output_dir = Path(args.data_root) / 'spectrograms' / args.date
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / f"{channel_dir}_{args.date}_carrier_spectrogram.png"
    
    generate_daily_spectrogram(archive_dir, args.date, args.channel, output_file)


if __name__ == '__main__':
    main()
