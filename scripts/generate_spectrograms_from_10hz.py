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
from dataclasses import dataclass
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


@dataclass
class DayData:
    """Container for a day's worth of 10 Hz data with power metrics."""
    timestamps: np.ndarray          # Full 24-hour timestamp array
    iq_samples: np.ndarray          # Complex IQ array (gaps = zeros)
    coverage_pct: float             # Percentage of day with data
    power_timestamps: np.ndarray    # Per-minute timestamps (Unix)
    power_db: np.ndarray            # Per-minute mean power (dB)
    power_valid: np.ndarray         # Boolean mask: True if minute has data


def read_10hz_day(npz_files: List[Path], date_str: str) -> Optional[DayData]:
    """
    Read 10 Hz NPZ files into a TIME-ALIGNED 24-hour array with power metrics.
    
    Creates a full 24-hour array (864,000 samples at 10 Hz) and places each
    file's data at the correct time position. Gaps in data remain as zeros.
    Also computes per-minute power for the combined power/spectrogram chart.
    
    Args:
        npz_files: List of 10 Hz NPZ file paths (sorted chronologically)
        date_str: Date string in YYYYMMDD format
        
    Returns:
        DayData object with timestamps, IQ samples, coverage, and power metrics.
        Returns None if no valid data found.
    """
    if not npz_files:
        logger.warning("No 10 Hz NPZ files to read")
        return None
    
    # Parse date to get day boundaries
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
    
    day_start_unix = day_start.timestamp()
    
    logger.info(f"Reading 10 Hz data for: {day_start.strftime('%Y-%m-%d')} UTC")
    
    # Create FULL 24-hour arrays
    # 24 hours * 60 min * 60 sec * 10 Hz = 864,000 samples
    sample_rate = 10  # 10 Hz decimated
    total_samples = 24 * 60 * 60 * sample_rate  # 864,000
    total_minutes = 24 * 60  # 1440
    
    # Pre-allocate IQ array with zeros (gaps will appear as no signal)
    iq_samples = np.zeros(total_samples, dtype=np.complex64)
    
    # Create full timestamp array (00:00:00.0 to 23:59:59.9)
    timestamps = day_start_unix + np.arange(total_samples) * (1.0 / sample_rate)
    
    # Per-minute power arrays (for combined chart)
    power_timestamps = day_start_unix + np.arange(total_minutes) * 60 + 30  # Center of each minute
    power_db = np.full(total_minutes, np.nan, dtype=np.float32)  # NaN for missing
    power_valid = np.zeros(total_minutes, dtype=bool)
    
    files_loaded = 0
    samples_placed = 0
    
    logger.info(f"Reading {len(npz_files)} 10 Hz NPZ files into time-aligned array...")
    
    for i, npz_file in enumerate(npz_files):
        try:
            with np.load(npz_file, allow_pickle=True) as data:
                iq = data['iq']  # Already complex IQ at 10 Hz
                
                # Get timing information from metadata
                timing_metadata = data['timing_metadata'].item() if 'timing_metadata' in data else {}
                file_unix_ts = timing_metadata.get('utc_timestamp', None)
                
                # If no timing metadata, parse from filename
                if file_unix_ts is None:
                    # Filename format: YYYYMMDDTHHMMSSZ_freq_iq_10hz.npz
                    filename = npz_file.name
                    timestamp_str = filename.split('_')[0]  # YYYYMMDDTHHMMSSZ
                    dt = datetime.strptime(timestamp_str, '%Y%m%dT%H%M%SZ')
                    dt = dt.replace(tzinfo=timezone.utc)
                    file_unix_ts = dt.timestamp()
                
                # Calculate index position in the 24-hour array
                offset_seconds = file_unix_ts - day_start_unix
                
                # Skip files outside the target day
                if offset_seconds < 0 or offset_seconds >= 86400:
                    continue
                
                # Calculate start index (10 samples per second)
                start_idx = int(offset_seconds * sample_rate)
                end_idx = start_idx + len(iq)
                
                # Bounds check (in case file extends past midnight)
                if end_idx > total_samples:
                    iq = iq[:total_samples - start_idx]
                    end_idx = total_samples
                
                # Place data at correct time position
                iq_samples[start_idx:end_idx] = iq
                files_loaded += 1
                samples_placed += len(iq)
                
                # Compute per-minute power (for combined chart)
                minute_idx = int(offset_seconds / 60)
                if 0 <= minute_idx < total_minutes and len(iq) > 0:
                    mean_power = np.mean(np.abs(iq) ** 2)
                    power_db[minute_idx] = 10 * np.log10(mean_power + 1e-12)
                    power_valid[minute_idx] = True
                
            if (i + 1) % 100 == 0:
                logger.info(f"  Processed {i+1}/{len(npz_files)} files...")
                
        except Exception as e:
            logger.warning(f"Error reading {npz_file.name}: {e}")
            continue
    
    if files_loaded == 0:
        logger.error("No valid data read from NPZ files")
        return None
    
    # Report coverage statistics
    coverage_pct = (samples_placed / total_samples) * 100
    minutes_with_data = samples_placed / 600  # 600 samples per minute
    gap_minutes = (total_samples - samples_placed) / 600
    
    logger.info(f"Loaded {files_loaded} files, {samples_placed:,} samples")
    logger.info(f"Coverage: {coverage_pct:.1f}% ({minutes_with_data:.0f} min data, {gap_minutes:.0f} min gaps)")
    
    return DayData(
        timestamps=timestamps,
        iq_samples=iq_samples,
        coverage_pct=coverage_pct,
        power_timestamps=power_timestamps,
        power_db=power_db,
        power_valid=power_valid
    )


def generate_combined_chart(day_data: DayData, output_path: Path, channel_name: str,
                            date_str: str, date_obj: datetime, grid_square: str = 'EM38ww'):
    """
    Generate combined power + spectrogram chart with perfectly aligned x-axes.
    
    Creates a 2-panel figure:
    - Top panel: Carrier power (dB) line chart with solar zenith overlay
    - Bottom panel: Spectrogram (frequency vs time)
    Both panels share the same x-axis for perfect alignment.
    
    Args:
        day_data: DayData object with IQ samples and power metrics
        output_path: Output PNG file path
        channel_name: Channel name for title
        date_str: Date string for title (YYYY-MM-DD)
        date_obj: Datetime object for the day (used for x-axis limits)
        grid_square: Maidenhead grid square for receiver location (for solar zenith)
    """
    try:
        from matplotlib.dates import HourLocator
        
        sample_rate = 10  # 10 Hz
        
        # === Compute spectrogram ===
        logger.info("Computing spectrogram...")
        nperseg = 128  # ~12.8 seconds per segment at 10 Hz
        noverlap = 64  # 50% overlap
        
        f, t, Sxx = signal.spectrogram(
            day_data.iq_samples,
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
        spectrogram_timestamps = day_data.timestamps[0] + t
        spec_dt_times = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in spectrogram_timestamps]
        
        # Convert power timestamps to datetime
        power_dt_times = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in day_data.power_timestamps]
        
        # === Create 2-panel figure with shared x-axis ===
        logger.info("Creating combined chart...")
        fig, (ax_power, ax_spec) = plt.subplots(
            2, 1, 
            figsize=(30, 10),  # Taller to accommodate both panels
            dpi=120,
            sharex=True,
            gridspec_kw={'height_ratios': [1, 2.5], 'hspace': 0.08},
            layout='constrained'  # Better layout handling with twinx axes
        )
        
        # === TOP PANEL: Power Chart ===
        # Only plot valid power points (where we have data)
        valid_times = [power_dt_times[i] for i in range(len(power_dt_times)) if day_data.power_valid[i]]
        valid_power = day_data.power_db[day_data.power_valid]
        
        if len(valid_times) > 0:
            ax_power.plot(valid_times, valid_power, 
                         color='#3b82f6', linewidth=1.0, alpha=0.9,
                         label='Mean Power')
            
            # Calculate and display power range
            power_min = np.nanmin(valid_power)
            power_max = np.nanmax(valid_power)
            power_mean = np.nanmean(valid_power)
            
            # Set y-axis limits with some padding
            y_range = power_max - power_min
            ax_power.set_ylim(power_min - 0.1 * y_range - 5, power_max + 0.1 * y_range + 5)
        
        ax_power.set_ylabel('Power (dB)', fontsize=11)
        ax_power.grid(True, alpha=0.3, linestyle='--')
        
        # Title with coverage info
        if day_data.coverage_pct < 99.5:
            title = f'{channel_name} - {date_str} ({day_data.coverage_pct:.0f}% coverage)'
        else:
            title = f'{channel_name} - {date_str}'
        ax_power.set_title(title, fontsize=14, fontweight='bold', pad=10)
        
        # === Add Solar Zenith Overlay to Power Panel ===
        try:
            from grape_recorder.grape.solar_zenith_calculator import calculate_solar_zenith_for_day
            
            logger.info(f"Calculating solar zenith for grid {grid_square}...")
            solar_data = calculate_solar_zenith_for_day(date_obj.strftime('%Y%m%d'), grid_square)
            
            if solar_data and 'timestamps' in solar_data:
                ax_solar = ax_power.twinx()
                
                # Convert solar timestamps to datetime
                solar_times = [datetime.fromisoformat(ts.replace('Z', '+00:00')) for ts in solar_data['timestamps']]
                
                # Determine channel type
                is_chu = channel_name.upper().startswith('CHU')
                
                if is_chu and 'chu_solar_elevation' in solar_data:
                    ax_solar.plot(solar_times, solar_data['chu_solar_elevation'], 
                                 color='#f97316', linewidth=1.5, linestyle='--', alpha=0.7,
                                 label='Solar Elev. (CHU path)')
                else:
                    ax_solar.plot(solar_times, solar_data['wwv_solar_elevation'], 
                                 color='#ef4444', linewidth=1.5, linestyle='--', alpha=0.7,
                                 label='Solar Elev. (WWV)')
                    ax_solar.plot(solar_times, solar_data['wwvh_solar_elevation'], 
                                 color='#a855f7', linewidth=1.5, linestyle=':', alpha=0.7,
                                 label='Solar Elev. (WWVH)')
                
                ax_solar.set_ylabel('Solar Elevation (°)', fontsize=9, color='#666')
                ax_solar.set_ylim(-90, 90)
                ax_solar.axhline(y=0, color='gray', linewidth=0.5, linestyle=':')
                ax_solar.tick_params(axis='y', labelcolor='#666', labelsize=8)
                ax_solar.legend(loc='upper right', fontsize=8, framealpha=0.9)
                logger.info("Added solar zenith overlay to power panel")
                
        except Exception as e:
            logger.warning(f"Could not add solar zenith overlay: {e}")
        
        # === BOTTOM PANEL: Spectrogram ===
        FIXED_DB_MIN = -60   # dB floor
        FIXED_DB_MAX = 0     # dB ceiling
        
        im = ax_spec.pcolormesh(
            spec_dt_times,
            f_shifted,
            Sxx_db_shifted,
            shading='auto',
            cmap='viridis',
            vmin=FIXED_DB_MIN,
            vmax=FIXED_DB_MAX
        )
        
        ax_spec.set_ylabel('Frequency (Hz)', fontsize=11)
        ax_spec.set_xlabel('Time (UTC)', fontsize=11)
        ax_spec.grid(True, alpha=0.2, linestyle='--')
        
        # Add colorbar for spectrogram
        cbar = fig.colorbar(im, ax=ax_spec, label='Spectral Power (dB)', shrink=0.8)
        
        # === Shared X-axis configuration ===
        day_start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        ax_spec.set_xlim(day_start, day_end)
        
        # Format x-axis with 3-hour ticks
        ax_spec.xaxis.set_major_locator(HourLocator(byhour=[0, 3, 6, 9, 12, 15, 18, 21]))
        ax_spec.xaxis.set_major_formatter(DateFormatter('%H:%M'))
        
        # Rotate x-axis labels for readability
        plt.setp(ax_spec.xaxis.get_majorticklabels(), rotation=0, ha='center')
        
        # Save (layout already handled by constrained_layout)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=100, bbox_inches='tight', facecolor='white')
        plt.close()
        
        logger.info(f"✅ Combined chart saved: {output_path}")
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
    from grape_recorder.paths import GRAPEPaths
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
            
            # Read 10 Hz data into time-aligned 24-hour array with power metrics
            day_data = read_10hz_day(npz_files, date_str)
            if day_data is None:
                logger.warning(f"Skipping {channel_name} - read failed")
                continue
            
            # Create output directory
            output_dir = Path(args.data_root) / 'spectrograms' / args.date
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate combined power + spectrogram chart
            safe_channel_name = channel_name.replace(' ', '_')
            output_path = output_dir / f'{safe_channel_name}_{args.date}_decimated_spectrogram.png'
            
            generate_combined_chart(
                day_data=day_data,
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
