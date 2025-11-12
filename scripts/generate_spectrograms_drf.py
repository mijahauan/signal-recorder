#!/usr/bin/env python3
"""
Generate daily spectrograms from Digital RF carrier data (10 Hz IQ)

Reads decimated 10 Hz IQ data from Digital RF HDF5 files and generates
spectrogram PNGs for web UI carrier visualization.

Usage:
    python3 scripts/generate_spectrograms_drf.py --date 20251112
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List
import numpy as np

try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    print("ERROR: digital_rf package required")
    exit(1)

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


def find_drf_channels(analytics_dir: Path, date_str: str) -> List[Tuple[str, Path]]:
    """
    Find all Digital RF channel directories for a given date
    
    Args:
        analytics_dir: Base analytics directory
        date_str: Date in YYYYMMDD format
        
    Returns:
        List of (channel_name, drf_channel_path) tuples
    """
    channels = []
    
    # Look for channel directories
    for channel_dir in analytics_dir.glob('*'):
        if not channel_dir.is_dir():
            continue
        
        # Check for digital_rf subdirectory with date
        drf_date_dir = channel_dir / 'digital_rf' / date_str
        if not drf_date_dir.exists():
            continue
        
        # Find the actual channel directory (deep in PSWS structure)
        # Structure: YYYYMMDD/CALLSIGN_GRID/RECEIVER@STATION/OBS.../CHANNEL/
        for drf_channel_dir in drf_date_dir.rglob('drf_properties.h5'):
            channel_path = drf_channel_dir.parent
            channel_name = channel_path.name
            channels.append((channel_name, channel_path))
            logger.info(f"Found channel: {channel_name} at {channel_path}")
            break  # Only need one per channel
    
    return channels


def read_drf_day(drf_channel_path: Path, date_str: str) -> Optional[Tuple[np.ndarray, np.ndarray, float]]:
    """
    Read full day of Digital RF data for a channel
    
    Args:
        drf_channel_path: Path to Digital RF channel directory (with drf_properties.h5)
        date_str: Date in YYYYMMDD format
        
    Returns:
        Tuple of (timestamps, iq_samples, sample_rate) or None if error
    """
    try:
        # Parse date
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        
        start_dt = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(days=1)
        
        # Open Digital RF reader on parent directory
        parent_dir = drf_channel_path.parent
        reader = drf.DigitalRFReader(str(parent_dir))
        
        channel_name = drf_channel_path.name
        
        # Get properties
        properties = reader.get_properties(channel_name)
        sample_rate = float(properties['samples_per_second'])
        
        logger.info(f"Reading {channel_name}")
        logger.info(f"  Sample rate: {sample_rate} Hz")
        logger.info(f"  Date range: {start_dt} to {end_dt}")
        
        # Get data bounds for this channel
        bounds = reader.get_bounds(channel_name)
        if bounds[0] is None or bounds[1] is None:
            logger.warning(f"  No data bounds available")
            return None
        
        # Calculate sample indices for the day
        start_sample = int(start_dt.timestamp() * sample_rate)
        end_sample = int(end_dt.timestamp() * sample_rate)
        
        # Constrain to actual data bounds
        if start_sample < bounds[0]:
            start_sample = bounds[0]
        if end_sample > bounds[1]:
            end_sample = bounds[1]
        
        logger.info(f"  Reading samples {start_sample} to {end_sample}")
        
        # Read data
        try:
            data = reader.read_vector(start_sample, end_sample - start_sample, channel_name)
            iq_samples = data[channel_name]
        except Exception as e:
            logger.error(f"  Failed to read data: {e}")
            return None
        
        # Generate timestamps
        num_samples = len(iq_samples)
        timestamps = start_sample / sample_rate + np.arange(num_samples) / sample_rate
        
        logger.info(f"  ✅ Read {num_samples:,} samples ({num_samples / 3600:.1f} hours)")
        
        return timestamps, iq_samples, sample_rate
        
    except Exception as e:
        logger.error(f"Error reading Digital RF: {e}", exc_info=True)
        return None


def generate_spectrogram(timestamps: np.ndarray, iq_samples: np.ndarray,
                        sample_rate: float, output_path: Path,
                        channel_name: str, date_str: str):
    """
    Generate carrier spectrogram PNG from 10 Hz IQ samples
    
    Args:
        timestamps: Unix timestamps for each sample
        iq_samples: Complex IQ samples at 10 Hz
        sample_rate: Sample rate (should be 10 Hz)
        output_path: Path to save PNG
        channel_name: Channel name for title
        date_str: Date string for title (YYYY-MM-DD)
    """
    try:
        logger.info(f"  Generating spectrogram for {len(iq_samples):,} samples...")
        
        # Spectrogram parameters for 10 Hz carrier data
        # With 10 Hz sample rate, we can see ±5 Hz around carrier
        # Use appropriate window for slow carrier variations
        nperseg = min(512, len(iq_samples))  # ~51 seconds per segment at 10 Hz
        noverlap = nperseg * 3 // 4  # 75% overlap for smooth visualization
        
        # Compute spectrogram
        f, t, Sxx = signal.spectrogram(
            iq_samples,
            fs=sample_rate,
            nperseg=nperseg,
            noverlap=noverlap,
            window='hann',
            scaling='density',
            mode='magnitude',
            return_onesided=False  # Complex data, need both sides
        )
        
        # Convert to dB scale
        Sxx_db = 10 * np.log10(Sxx + 1e-10)
        
        # Create figure
        fig, ax = plt.subplots(figsize=(16, 6), dpi=100)
        
        # Convert time offsets to actual UTC datetime
        start_timestamp = timestamps[0]
        plot_times = [datetime.fromtimestamp(start_timestamp + offset, tz=timezone.utc) 
                     for offset in t]
        
        # Shift frequencies to be centered at 0
        f_shifted = np.fft.fftshift(f)
        Sxx_db_shifted = np.fft.fftshift(Sxx_db, axes=0)
        
        # Create spectrogram plot
        im = ax.pcolormesh(
            plot_times,
            f_shifted,
            Sxx_db_shifted,
            shading='gouraud',
            cmap='viridis',
            vmin=np.percentile(Sxx_db_shifted, 5),
            vmax=np.percentile(Sxx_db_shifted, 95)
        )
        
        # Format axes
        ax.set_ylabel('Frequency Offset (Hz)', fontsize=12)
        ax.set_xlabel('Time (UTC)', fontsize=12)
        ax.set_title(f'{channel_name} - {date_str} - Carrier Spectrogram (10 Hz IQ)', 
                    fontsize=14, fontweight='bold')
        
        # Format x-axis as time
        ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        fig.autofmt_xdate()
        
        # Add colorbar
        cbar = fig.colorbar(im, ax=ax, label='Power (dB)')
        
        # Tight layout
        plt.tight_layout()
        
        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        plt.close()
        
        logger.info(f"  ✅ Saved: {output_path.name} ({output_path.stat().st_size / 1024:.0f} KB)")
        
    except Exception as e:
        logger.error(f"  Error generating spectrogram: {e}", exc_info=True)
        raise


def main():
    parser = argparse.ArgumentParser(description='Generate spectrograms from Digital RF carrier data')
    parser.add_argument('--date', default=None, 
                       help='Date in YYYYMMDD format (default: today)')
    parser.add_argument('--data-root', default='/tmp/grape-test',
                       help='Data root directory (default: /tmp/grape-test)')
    parser.add_argument('--output-dir', default=None,
                       help='Output directory for PNGs (default: {data-root}/spectrograms)')
    parser.add_argument('--channels', nargs='+', default=None,
                       help='Specific channels to process (default: all)')
    
    args = parser.parse_args()
    
    # Determine date
    if args.date:
        date_str = args.date
    else:
        # Default to today
        today = datetime.now(timezone.utc)
        date_str = today.strftime('%Y%m%d')
    
    # Parse date for display
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    date_display = f"{year}-{month:02d}-{day:02d}"
    
    logger.info(f"Generating carrier spectrograms for: {date_display}")
    
    # Setup paths
    analytics_dir = Path(args.data_root) / 'analytics'
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(args.data_root) / 'spectrograms'
    
    if not analytics_dir.exists():
        logger.error(f"Analytics directory not found: {analytics_dir}")
        return 1
    
    # Discover Digital RF channels
    channels = find_drf_channels(analytics_dir, date_str)
    
    if not channels:
        logger.warning(f"No Digital RF data found for {date_str}")
        return 1
    
    # Filter channels if specified
    if args.channels:
        channels = [(name, path) for name, path in channels if name in args.channels]
    
    logger.info(f"Found {len(channels)} channels to process")
    
    success_count = 0
    
    for channel_name, channel_path in channels:
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {channel_name}")
            logger.info(f"{'='*60}")
            
            # Read data
            result = read_drf_day(channel_path, date_str)
            if result is None:
                logger.warning(f"  Skipping - no data available")
                continue
            
            timestamps, iq_samples, sample_rate = result
            
            # Generate spectrogram
            output_filename = f"{channel_name}_{date_str}_carrier_spectrogram.png"
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
    
    return 0 if success_count > 0 else 1


if __name__ == '__main__':
    exit(main())
