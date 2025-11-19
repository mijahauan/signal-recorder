#!/usr/bin/env python3
"""
Generate daily spectrograms from GRAPE archive data

Reads 16 kHz IQ data from NPZ archive files and generates
spectrogram PNGs for web UI display.

Usage:
    python3 scripts/generate_spectrograms.py [--date YYYYMMDD] [--channel "WWV 5 MHz"]
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List
import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False
    print("ERROR: matplotlib package required")
    exit(1)

from scipy import signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def find_npz_files_for_date(archive_dir: Path, date_str: str) -> List[Path]:
    """
    Find all NPZ files for a specific date in archive directory
    
    Args:
        archive_dir: Channel archive directory (e.g., archives/WWV_5_MHz)
        date_str: Date in YYYYMMDD format
        
    Returns:
        Sorted list of NPZ file paths for that date
    """
    if not archive_dir.exists():
        logger.error(f"Archive directory not found: {archive_dir}")
        return []
    
    # NPZ files are named: YYYYMMDDTHHMMSSZ_freq_iq.npz
    npz_files = []
    
    for npz_file in archive_dir.glob(f"{date_str}*.npz"):
        npz_files.append(npz_file)
    
    # Sort by filename (which sorts by timestamp)
    npz_files.sort()
    
    logger.info(f"Found {len(npz_files)} NPZ files for {date_str}")
    
    return npz_files


def read_npz_day(npz_files: List[Path], date_str: str) -> Optional[Tuple[np.ndarray, np.ndarray, int]]:
    """
    Read and concatenate NPZ files for a full day with 24-hour coverage
    
    Args:
        npz_files: List of NPZ file paths (sorted chronologically)
        date_str: Date string in YYYYMMDD format
        
    Returns:
        Tuple of (timestamps, iq_samples, sample_rate) with full 24-hour coverage
    """
    if not npz_files:
        logger.warning("No NPZ files to read")
        return None
    
    # Parse date to get day boundaries (00:00:00 to 23:59:59 UTC)
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
    
    day_start_unix = day_start.timestamp()
    day_end_unix = day_end.timestamp()
    
    logger.info(f"Creating 24-hour spectrogram: {day_start.isoformat()} to {day_end.isoformat()}")
    
    # Read and concatenate data directly (memory efficient)
    all_timestamps = []
    all_samples = []
    sample_rate = None
    
    logger.info(f"Reading {len(npz_files)} NPZ files...")
    
    for i, npz_file in enumerate(npz_files):
        try:
            with np.load(npz_file) as data:
                iq = data['iq']
                file_unix_ts = float(data['unix_timestamp'])
                file_sample_rate = int(data['sample_rate'])
                
                if sample_rate is None:
                    sample_rate = file_sample_rate
                elif sample_rate != file_sample_rate:
                    logger.warning(f"Sample rate mismatch: expected {sample_rate}, got {file_sample_rate}")
                
                # Generate timestamps for this file
                num_samples = len(iq)
                file_timestamps = file_unix_ts + np.arange(num_samples) / sample_rate
                
                # Only include samples within the target day
                mask = (file_timestamps >= day_start_unix) & (file_timestamps <= day_end_unix)
                all_timestamps.append(file_timestamps[mask])
                all_samples.append(iq[mask])
                
            if (i + 1) % 100 == 0:
                logger.info(f"  Progress: {i+1}/{len(npz_files)} files")
                
        except Exception as e:
            logger.warning(f"Error reading {npz_file.name}: {e}")
            continue
    
    if not all_samples:
        logger.error("No samples read from NPZ files")
        return None
    
    # Concatenate all data
    timestamps = np.concatenate(all_timestamps)
    iq_samples = np.concatenate(all_samples)
    
    # Check coverage
    if len(timestamps) > 0:
        data_start = datetime.fromtimestamp(timestamps[0], tz=timezone.utc)
        data_end = datetime.fromtimestamp(timestamps[-1], tz=timezone.utc)
        duration_hours = (timestamps[-1] - timestamps[0]) / 3600
        coverage_pct = 100.0 * len(timestamps) / (sample_rate * 86400)  # Expected samples in 24h
        
        logger.info(f"✅ Read {len(iq_samples)} samples ({duration_hours:.1f} hours, {coverage_pct:.1f}% of day)")
        logger.info(f"   Data range: {data_start.isoformat()} to {data_end.isoformat()}")
        logger.info(f"   Day range: {day_start.isoformat()} to {day_end.isoformat()}")
    else:
        logger.error("No timestamps in data")
        return None
    
    logger.info(f"   Sample rate: {sample_rate} Hz")
    
    return timestamps, iq_samples, sample_rate


def generate_spectrogram(timestamps: np.ndarray, iq_samples: np.ndarray,
                        sample_rate: float, output_path: Path,
                        channel_name: str, date_str: str):
    """
    Generate spectrogram PNG from IQ samples with 24-hour x-axis
    
    Handles gaps in data by creating a full 24-hour time grid and placing
    data at correct positions, with NaN for missing time periods.
    
    Args:
        timestamps: Unix timestamps for each sample
        iq_samples: Complex IQ samples
        sample_rate: Sample rate in Hz
        output_path: Path to save PNG
        channel_name: Channel name for title
        date_str: Date string for title (YYYY-MM-DD format)
    """
    try:
        logger.info(f"Generating spectrogram for {len(iq_samples)} samples...")
        
        # Parse date for 24-hour range
        year = int(date_str.split('-')[0])
        month = int(date_str.split('-')[1])
        day = int(date_str.split('-')[2])
        day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        day_end = datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
        day_start_ts = day_start.timestamp()
        day_end_ts = day_end.timestamp()
        
        # Spectrogram parameters for 16 kHz data
        nperseg = min(2048, len(iq_samples))  # FFT window size
        noverlap = nperseg // 2  # 50% overlap
        
        # Compute spectrogram (complex IQ data)
        f, t, Sxx = signal.spectrogram(
            iq_samples,
            fs=sample_rate,
            nperseg=nperseg,
            noverlap=noverlap,
            window='hann',
            scaling='density',
            mode='magnitude',
            return_onesided=False  # Required for complex IQ data
        )
        
        # Convert to dB scale
        Sxx_db = 10 * np.log10(Sxx + 1e-10)
        
        # Shift frequencies to be centered at 0 (for complex IQ data)
        f_shifted = np.fft.fftshift(f)
        Sxx_db_shifted = np.fft.fftshift(Sxx_db, axes=0)
        
        # Convert time indices to actual timestamps
        start_timestamp = timestamps[0]
        data_times = start_timestamp + t  # Actual data timestamps
        
        # Create full 24-hour time grid (1 minute resolution)
        full_time_grid = np.arange(day_start_ts, day_end_ts + 60, 60)  # Every minute
        full_datetime_grid = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in full_time_grid]
        
        # Create output spectrogram array with NaN for missing data
        num_freqs = len(f_shifted)
        num_time_bins = len(full_time_grid)
        Sxx_full = np.full((num_freqs, num_time_bins), np.nan)
        
        # Map data to correct time bins
        for i, data_t in enumerate(data_times):
            # Find closest time bin in full grid
            time_idx = np.argmin(np.abs(full_time_grid - data_t))
            if time_idx < num_time_bins:
                Sxx_full[:, time_idx] = Sxx_db_shifted[:, i]
        
        # Create figure
        fig, ax = plt.subplots(figsize=(16, 6), dpi=100)
        
        # Create spectrogram plot with full 24-hour grid
        im = ax.pcolormesh(
            full_datetime_grid, 
            f_shifted, 
            Sxx_full,
            shading='nearest',
            cmap='viridis',
            vmin=np.nanpercentile(Sxx_db_shifted, 5),
            vmax=np.nanpercentile(Sxx_db_shifted, 95)
        )
        
        # Format axes
        ax.set_ylabel('Frequency Offset (Hz)', fontsize=12)
        ax.set_xlabel('Time (UTC)', fontsize=12)
        ax.set_title(f'{channel_name} - {date_str} - Carrier Spectrogram (16 kHz IQ)', 
                    fontsize=14, fontweight='bold')
        
        # Force 24-hour x-axis range (00:00-23:59 UTC)
        ax.set_xlim(day_start, day_end)
        
        # Format x-axis as time
        ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
        fig.autofmt_xdate()
        
        # Add colorbar
        cbar = fig.colorbar(im, ax=ax, label='Power (dB)')
        
        # Add grid
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # Tight layout
        plt.tight_layout()
        
        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        plt.close()
        
        logger.info(f"✅ Spectrogram saved: {output_path}")
        logger.info(f"   Size: {output_path.stat().st_size / 1024:.1f} KB")
        
    except Exception as e:
        logger.error(f"Error generating spectrogram: {e}", exc_info=True)
        raise


def main():
    parser = argparse.ArgumentParser(description='Generate spectrograms from Digital RF data')
    parser.add_argument('--date', default=None, 
                       help='Date in YYYYMMDD format (default: yesterday)')
    parser.add_argument('--channel', default=None,
                       help='Channel name (e.g., "WWV 5 MHz", default: all channels)')
    parser.add_argument('--data-root', default='/tmp/grape-test',
                       help='Data root directory (default: /tmp/grape-test)')
    parser.add_argument('--output-dir', default=None,
                       help='Output directory for PNGs (default: {data-root}/spectrograms)')
    
    args = parser.parse_args()
    
    # Determine date
    if args.date:
        date_str = args.date
    else:
        # Default to yesterday (data usually complete)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        date_str = yesterday.strftime('%Y%m%d')
    
    # Parse date for display
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    date_display = f"{year}-{month:02d}-{day:02d}"
    
    logger.info(f"Generating spectrograms for date: {date_display}")
    
    # Setup paths
    archive_base = Path(args.data_root) / 'archives'
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(args.data_root) / 'spectrograms'
    
    # Determine channels to process
    if args.channel:
        channels = [args.channel]
    else:
        # Process all WWV and CHU channels
        channels = [
            'WWV_2.5_MHz',
            'WWV_5_MHz',
            'WWV_10_MHz',
            'WWV_15_MHz',
            'WWV_20_MHz',
            'WWV_25_MHz',
            'CHU_3.33_MHz',
            'CHU_7.85_MHz',
            'CHU_14.67_MHz'
        ]
    
    success_count = 0
    
    for channel_name in channels:
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {channel_name}")
            logger.info(f"{'='*60}")
            
            # Find archive directory (convert spaces to underscores)
            archive_dir_name = channel_name.replace(' ', '_')
            archive_dir = archive_base / archive_dir_name
            if not archive_dir.exists():
                logger.warning(f"Skipping {channel_name} - archive directory not found: {archive_dir}")
                continue
            
            # Find NPZ files for date
            npz_files = find_npz_files_for_date(archive_dir, date_str)
            if not npz_files:
                logger.warning(f"Skipping {channel_name} - no NPZ files for {date_str}")
                continue
            
            # Read data with 24-hour coverage
            result = read_npz_day(npz_files, date_str)
            if result is None:
                logger.warning(f"Skipping {channel_name} - read failed")
                continue
            
            timestamps, iq_samples, sample_rate = result
            
            # Generate spectrogram
            output_filename = f"{archive_dir_name}_{date_str}_spectrogram.png"
            output_path = output_dir / date_str / output_filename
            
            generate_spectrogram(
                timestamps=timestamps,
                iq_samples=iq_samples,
                sample_rate=sample_rate,
                output_path=output_path,
                channel_name=channel_name,
                date_str=date_display
            )
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"Failed to process {channel_name}: {e}")
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Completed: {success_count}/{len(channels)} spectrograms generated")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"{'='*60}")


if __name__ == '__main__':
    main()
