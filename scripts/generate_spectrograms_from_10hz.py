#!/usr/bin/env python3
"""
Generate spectrograms from 10 Hz decimated NPZ files

Reads decimated IQ data from analytics/{channel}/decimated/ directory
and generates spectrograms for web UI display.

Usage:
    python3 scripts/generate_spectrograms_from_10hz.py --date 20251119
    python3 scripts/generate_spectrograms_from_10hz.py --date 20251119 --channel "WWV 10 MHz"
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


def find_10hz_files_for_date(decimated_dir: Path, date_str: str) -> List[Path]:
    """
    Find all 10 Hz decimated NPZ files for a specific date
    
    Args:
        decimated_dir: Channel decimated directory (e.g., analytics/WWV_5_MHz/decimated)
        date_str: Date in YYYYMMDD format
        
    Returns:
        Sorted list of 10 Hz NPZ file paths for that date
    """
    if not decimated_dir.exists():
        logger.warning(f"Decimated directory not found: {decimated_dir}")
        return []
    
    # 10 Hz NPZ files are named: YYYYMMDDTHHMMSSZ_freq_iq_10hz.npz
    npz_files = []
    
    for npz_file in decimated_dir.glob(f"{date_str}*_iq_10hz.npz"):
        npz_files.append(npz_file)
    
    # Sort by filename (which sorts by timestamp)
    npz_files.sort()
    
    logger.info(f"Found {len(npz_files)} 10 Hz NPZ files for {date_str}")
    
    return npz_files


def read_10hz_day(npz_files: List[Path], date_str: str) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Read and concatenate 10 Hz NPZ files for a full day
    
    Args:
        npz_files: List of 10 Hz NPZ file paths (sorted chronologically)
        date_str: Date string in YYYYMMDD format
        
    Returns:
        Tuple of (timestamps, iq_samples) or None if error
    """
    if not npz_files:
        logger.warning("No 10 Hz NPZ files to read")
        return None
    
    # Parse date to get day boundaries
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
    
    day_start_unix = day_start.timestamp()
    day_end_unix = day_end.timestamp()
    
    logger.info(f"Reading 10 Hz data: {day_start.isoformat()} to {day_end.isoformat()}")
    
    # Read and concatenate data
    all_timestamps = []
    all_samples = []
    sample_rate = 10  # 10 Hz decimated
    
    logger.info(f"Reading {len(npz_files)} 10 Hz NPZ files...")
    
    for i, npz_file in enumerate(npz_files):
        try:
            with np.load(npz_file, allow_pickle=True) as data:
                iq = data['iq']  # Already complex IQ at 10 Hz
                
                # Get timing information from metadata
                timing_metadata = data['timing_metadata'].item() if 'timing_metadata' in data else {}
                file_unix_ts = timing_metadata.get('utc_timestamp', None)
                
                # If no timing metadata, try to parse from filename
                if file_unix_ts is None:
                    # Filename format: YYYYMMDDTHHMMSSZ_freq_iq_10hz.npz
                    filename = npz_file.name
                    timestamp_str = filename.split('_')[0]  # YYYYMMDDTHHMMSSZ
                    dt = datetime.strptime(timestamp_str, '%Y%m%dT%H%M%SZ')
                    dt = dt.replace(tzinfo=timezone.utc)
                    file_unix_ts = dt.timestamp()
                
                # Generate timestamps for this file (10 Hz = 0.1s per sample)
                num_samples = len(iq)
                file_timestamps = file_unix_ts + np.arange(num_samples) * 0.1
                
                # Only include samples within the target day
                mask = (file_timestamps >= day_start_unix) & (file_timestamps <= day_end_unix)
                all_timestamps.append(file_timestamps[mask])
                all_samples.append(iq[mask])
                
            if (i + 1) % 100 == 0:
                logger.info(f"  Processed {i+1}/{len(npz_files)} files...")
                
        except Exception as e:
            logger.warning(f"Error reading {npz_file.name}: {e}")
            continue
    
    if not all_timestamps:
        logger.error("No valid data read from NPZ files")
        return None
    
    # Concatenate all data
    timestamps = np.concatenate(all_timestamps)
    iq_samples = np.concatenate(all_samples)
    
    logger.info(f"Loaded {len(timestamps)} samples ({len(timestamps)/600:.1f} minutes)")
    
    return timestamps, iq_samples


def generate_spectrogram(timestamps: np.ndarray, iq_samples: np.ndarray, 
                         output_path: Path, channel_name: str, date_str: str, 
                         date_obj: datetime, grid_square: str = 'EM38ww'):
    """
    Generate spectrogram from 10 Hz IQ data and save to PNG with solar zenith overlay
    
    Args:
        timestamps: Unix timestamps (seconds)
        iq_samples: Complex IQ samples at 10 Hz
        output_path: Output PNG file path
        channel_name: Channel name for title
        date_str: Date string for title (YYYY-MM-DD)
        date_obj: Datetime object for the day (used for x-axis limits)
        grid_square: Maidenhead grid square for receiver location (for solar zenith)
    """
    try:
        sample_rate = 10  # 10 Hz
        
        # Compute spectrogram
        logger.info("Computing spectrogram...")
        nperseg = 128  # ~12.8 seconds per segment at 10 Hz
        noverlap = 64  # 50% overlap
        
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
        
        # Convert spectrogram time to absolute timestamps
        # t is relative time in seconds from start
        spectrogram_timestamps = timestamps[0] + t
        
        # Convert to datetime for plotting
        dt_times = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in spectrogram_timestamps]
        
        # Create plot - wider format for better 24-hour spread
        logger.info("Creating plot...")
        fig, ax = plt.subplots(figsize=(30, 6), dpi=120)
        
        # Plot spectrogram with FIXED dB range for consistent comparison
        # Range based on observed power levels (typically -60 to 0 dB relative)
        FIXED_DB_MIN = -60   # dB floor (noise floor)
        FIXED_DB_MAX = 0     # dB ceiling (strong carriers)
        
        im = ax.pcolormesh(
            dt_times,
            f_shifted,
            Sxx_db_shifted,
            shading='auto',
            cmap='viridis',
            vmin=FIXED_DB_MIN,
            vmax=FIXED_DB_MAX
        )
        
        # Labels and title
        ax.set_xlabel('Time (UTC)', fontsize=12)
        ax.set_ylabel('Frequency (Hz)', fontsize=12)
        ax.set_title(f'{channel_name} - {date_str} - 10 Hz Decimated Spectrogram', fontsize=14, fontweight='bold')
        
        # Set x-axis to always show full 24-hour UTC day
        day_start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        ax.set_xlim(day_start, day_end)
        
        # Format x-axis with explicit 3-hour ticks to match power chart
        from matplotlib.dates import HourLocator
        ax.xaxis.set_major_locator(HourLocator(byhour=[0, 3, 6, 9, 12, 15, 18, 21]))
        ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
        fig.autofmt_xdate()
        
        # Add colorbar
        cbar = fig.colorbar(im, ax=ax, label='Power (dB)')
        
        # Add grid
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # === Add Solar Zenith Overlay ===
        try:
            from signal_recorder.solar_zenith_calculator import calculate_solar_zenith_for_day
            
            logger.info(f"Calculating solar zenith for grid {grid_square}...")
            solar_data = calculate_solar_zenith_for_day(date_obj.strftime('%Y%m%d'), grid_square)
            
            if solar_data and 'timestamps' in solar_data:
                # Create secondary y-axis for solar elevation
                ax2 = ax.twinx()
                
                # Convert solar timestamps to datetime
                solar_times = [datetime.fromisoformat(ts.replace('Z', '+00:00')) for ts in solar_data['timestamps']]
                
                # Determine channel type to show appropriate solar paths
                is_chu = channel_name.upper().startswith('CHU')
                
                if is_chu and 'chu_solar_elevation' in solar_data:
                    # CHU channel: show CHU path solar elevation
                    ax2.plot(solar_times, solar_data['chu_solar_elevation'], 
                            color='#e67e22', linewidth=2, linestyle='-', alpha=0.8,
                            label=f"Solar Elev. (CHU path)")
                    logger.info(f"Added solar zenith overlay for CHU path")
                else:
                    # WWV channel: show WWV and WWVH path solar elevations
                    ax2.plot(solar_times, solar_data['wwv_solar_elevation'], 
                            color='#e74c3c', linewidth=2, linestyle='-', alpha=0.8,
                            label=f"Solar Elev. (WWV path)")
                    ax2.plot(solar_times, solar_data['wwvh_solar_elevation'], 
                            color='#9b59b6', linewidth=2, linestyle='--', alpha=0.8,
                            label=f"Solar Elev. (WWVH path)")
                    logger.info(f"Added solar zenith overlay for WWV/WWVH paths")
                
                # Configure secondary y-axis
                ax2.set_ylabel('Solar Elevation (°)', fontsize=10, color='#666')
                ax2.set_ylim(-90, 90)
                ax2.axhline(y=0, color='gray', linewidth=0.5, linestyle=':')  # Horizon line
                ax2.legend(loc='upper right', fontsize=8)
                ax2.tick_params(axis='y', labelcolor='#666')
                
        except Exception as e:
            logger.warning(f"Could not add solar zenith overlay: {e}")
        
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
    parser = argparse.ArgumentParser(description='Generate spectrograms from 10 Hz decimated NPZ files')
    parser.add_argument('--date', required=True,
                       help='Date in YYYYMMDD format')
    parser.add_argument('--channel', default=None,
                       help='Channel name (e.g., "WWV 5 MHz", default: all channels)')
    parser.add_argument('--data-root', default='/tmp/grape-test',
                       help='Data root directory (default: /tmp/grape-test)')
    parser.add_argument('--grid', default=None,
                       help='Maidenhead grid square for receiver (default: from config)')
    
    args = parser.parse_args()
    date_str = args.date
    
    # Get grid square from config or argument
    grid_square = args.grid
    if not grid_square:
        try:
            import tomllib
            config_path = Path(__file__).parent.parent / 'config' / 'grape-config.toml'
            if config_path.exists():
                with open(config_path, 'rb') as f:
                    config = tomllib.load(f)
                    grid_square = config.get('station', {}).get('grid_square', 'EM38ww')
                    logger.info(f"Using grid square from config: {grid_square}")
            else:
                grid_square = 'EM38ww'
        except Exception as e:
            logger.warning(f"Could not read config, using default grid: {e}")
            grid_square = 'EM38ww'
    
    # Parse date for display and datetime object
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    date_display = f"{year}-{month:02d}-{day:02d}"
    date_obj = datetime(year, month, day, tzinfo=timezone.utc)
    
    logger.info(f"Generating spectrograms from 10 Hz data for: {date_display}")
    
    # Setup paths using GRAPEPaths
    from signal_recorder.paths import GRAPEPaths
    paths = GRAPEPaths(args.data_root)
    analytics_base = Path(args.data_root) / 'analytics'  # For iteration only
    output_dir = Path(args.data_root) / 'spectrograms'
    
    # Determine channels to process
    if args.channel:
        channels = [args.channel]
    else:
        # Process all WWV and CHU channels
        channels = [
            'WWV 2.5 MHz',
            'WWV 5 MHz',
            'WWV 10 MHz',
            'WWV 15 MHz',
            'WWV 20 MHz',
            'WWV 25 MHz',
            'CHU 3.33 MHz',
            'CHU 7.85 MHz',
            'CHU 14.67 MHz'
        ]
    
    success_count = 0
    
    for channel_name in channels:
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {channel_name}")
            logger.info(f"{'='*60}")
            
            # Find decimated directory (convert spaces to underscores)
            decimated_dir = paths.get_decimated_dir(channel_name)
            
            if not decimated_dir.exists():
                logger.warning(f"Skipping {channel_name} - decimated directory not found: {decimated_dir}")
                continue
            
            # Find 10 Hz NPZ files for date
            npz_files = find_10hz_files_for_date(decimated_dir, date_str)
            if not npz_files:
                logger.warning(f"Skipping {channel_name} - no 10 Hz NPZ files for {date_str}")
                continue
            
            # Read 10 Hz data
            result = read_10hz_day(npz_files, date_str)
            if result is None:
                logger.warning(f"Skipping {channel_name} - read failed")
                continue
            
            timestamps, iq_samples = result
            
            # Create output directory (unified path structure, no subdirectories)
            output_dir = Path(args.data_root) / 'spectrograms' / args.date
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate spectrogram with unified naming: {channel}_{date}_decimated_spectrogram.png
            safe_channel_name = channel_name.replace(' ', '_')
            output_path = output_dir / f'{safe_channel_name}_{args.date}_decimated_spectrogram.png'
            
            generate_spectrogram(
                timestamps=timestamps,
                iq_samples=iq_samples,
                output_path=output_path,
                channel_name=channel_name,
                date_str=date_display,
                date_obj=date_obj,
                grid_square=grid_square
            )
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"Failed to process {channel_name}: {e}")
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Completed: {success_count}/{len(channels)} spectrograms generated")
    logger.info(f"Output directory: {Path(args.data_root) / 'spectrograms' / date_str}")
    logger.info(f"{'='*60}")
    
    return 0 if success_count > 0 else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
