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


def read_npz_day(npz_files: List[Path]) -> Optional[Tuple[np.ndarray, np.ndarray, int]]:
    """
    Read and concatenate NPZ files for a full day
    
    Args:
        npz_files: List of NPZ file paths (sorted chronologically)
        
    Returns:
        Tuple of (timestamps, iq_samples, sample_rate) or None if error
    """
    if not npz_files:
        logger.warning("No NPZ files to read")
        return None
    
    all_timestamps = []
    all_samples = []
    sample_rate = None
    
    logger.info(f"Reading {len(npz_files)} NPZ files...")
    
    for i, npz_file in enumerate(npz_files):
        try:
            with np.load(npz_file) as data:
                # NPZ format from core_npz_writer: iq, unix_timestamp, sample_rate, etc.
                iq = data['iq']
                file_unix_ts = float(data['unix_timestamp'])
                file_sample_rate = int(data['sample_rate'])
                
                # Get sample rate from metadata
                if sample_rate is None:
                    sample_rate = file_sample_rate
                elif sample_rate != file_sample_rate:
                    logger.warning(f"Sample rate mismatch: expected {sample_rate}, got {file_sample_rate}")
                
                # Generate timestamps for this file
                num_samples = len(iq)
                file_timestamps = file_unix_ts + np.arange(num_samples) / sample_rate
                
                all_timestamps.append(file_timestamps)
                all_samples.append(iq)
                
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
    
    logger.info(f"✅ Read {len(iq_samples)} samples ({len(timestamps)/3600:.1f} hours)")
    logger.info(f"   Sample rate: {sample_rate} Hz")
    
    return timestamps, iq_samples, sample_rate


def generate_spectrogram(timestamps: np.ndarray, iq_samples: np.ndarray,
                        sample_rate: float, output_path: Path,
                        channel_name: str, date_str: str):
    """
    Generate spectrogram PNG from IQ samples
    
    Args:
        timestamps: Unix timestamps for each sample
        iq_samples: Complex IQ samples
        sample_rate: Sample rate in Hz
        output_path: Path to save PNG
        channel_name: Channel name for title
        date_str: Date string for title
    """
    try:
        logger.info(f"Generating spectrogram for {len(iq_samples)} samples...")
        
        # Spectrogram parameters for 16 kHz data
        # With 16 kHz sample rate, we can see ±8 kHz around carrier
        # Use longer FFT for better frequency resolution
        nperseg = min(2048, len(iq_samples))  # FFT window size
        noverlap = nperseg // 2  # 50% overlap
        
        # Compute spectrogram
        f, t, Sxx = signal.spectrogram(
            iq_samples,
            fs=sample_rate,
            nperseg=nperseg,
            noverlap=noverlap,
            window='hann',
            scaling='density',
            mode='magnitude'
        )
        
        # Convert to dB scale
        Sxx_db = 10 * np.log10(Sxx + 1e-10)  # Add small value to avoid log(0)
        
        # Create figure
        fig, ax = plt.subplots(figsize=(16, 6), dpi=100)
        
        # Convert time indices to actual timestamps
        time_offsets = t  # Offset in seconds from start
        start_timestamp = timestamps[0]
        plot_times = [datetime.fromtimestamp(start_timestamp + offset, tz=timezone.utc) 
                     for offset in time_offsets]
        
        # Create spectrogram plot
        im = ax.pcolormesh(
            plot_times, 
            f, 
            Sxx_db,
            shading='gouraud',
            cmap='viridis',
            vmin=np.percentile(Sxx_db, 5),  # Auto-scale to remove noise floor
            vmax=np.percentile(Sxx_db, 95)
        )
        
        # Format axes
        ax.set_ylabel('Frequency Offset (Hz)', fontsize=12)
        ax.set_xlabel('Time (UTC)', fontsize=12)
        ax.set_title(f'{channel_name} - {date_str} - Carrier Spectrogram (16 kHz IQ)', 
                    fontsize=14, fontweight='bold')
        
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
        # Process all WWV channels (skip CHU for now)
        channels = [
            'WWV_2.5_MHz',
            'WWV_5_MHz',
            'WWV_10_MHz',
            'WWV_15_MHz',
            'WWV_20_MHz',
            'WWV_25_MHz'
        ]
    
    success_count = 0
    
    for channel_name in channels:
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {channel_name}")
            logger.info(f"{'='*60}")
            
            # Find archive directory
            archive_dir = archive_base / channel_name
            if not archive_dir.exists():
                logger.warning(f"Skipping {channel_name} - archive directory not found")
                continue
            
            # Find NPZ files for date
            npz_files = find_npz_files_for_date(archive_dir, date_str)
            if not npz_files:
                logger.warning(f"Skipping {channel_name} - no NPZ files for {date_str}")
                continue
            
            # Read data
            result = read_npz_day(npz_files)
            if result is None:
                logger.warning(f"Skipping {channel_name} - read failed")
                continue
            
            timestamps, iq_samples, sample_rate = result
            
            # Generate spectrogram
            output_filename = f"{channel_name}_{date_str}_spectrogram.png"
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
