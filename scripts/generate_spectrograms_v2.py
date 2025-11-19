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
        iq_real = data['iq_real']
        iq_imag = data['iq_imag']
        timestamps = data['timestamps']
        
        # Return first timestamp and IQ samples
        return float(timestamps[0]), iq_real + 1j * iq_imag
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
    
    # Process first file to get frequency array
    f_shifted = None
    for minute_ts in expected_minutes[:10]:
        if minute_ts in file_dict:
            _, iq = read_npz_minute(file_dict[minute_ts])
            if iq is not None:
                f_shifted, _ = compute_minute_spectrogram(iq)
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
            if iq is not None:
                _, Sxx_minute = compute_minute_spectrogram(iq)
                # Average across time within the minute
                Sxx_full[:, i] = np.mean(Sxx_minute, axis=1)
    
    logger.info("Creating plot...")
    
    # Create time grid for x-axis
    time_grid = [day_start + timedelta(minutes=i) for i in range(1440)]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(16, 6), dpi=100)
    
    # Plot spectrogram
    im = ax.pcolormesh(
        time_grid,
        f_shifted,
        Sxx_full,
        shading='nearest',
        cmap='viridis',
        vmin=np.nanpercentile(Sxx_full, 5),
        vmax=np.nanpercentile(Sxx_full, 95)
    )
    
    # Format axes
    ax.set_ylabel('Frequency Offset (Hz)', fontsize=12)
    ax.set_xlabel('Time (UTC)', fontsize=12)
    ax.set_title(f'{channel_name} - {date_str} - Carrier Spectrogram (16 kHz IQ)', 
                fontsize=14, fontweight='bold')
    
    # Force 24-hour range
    day_end = day_start + timedelta(hours=23, minutes=59, seconds=59)
    ax.set_xlim(day_start, day_end)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
    fig.autofmt_xdate()
    
    # Add colorbar
    cbar = fig.colorbar(im, ax=ax, label='Power (dB)')
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')
    
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
    channel_dir = args.channel.replace(' ', '_').replace('.', '_')
    archive_dir = Path(args.data_root) / 'archives' / channel_dir
    
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
