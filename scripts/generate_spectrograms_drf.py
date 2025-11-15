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
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List
import numpy as np
import toml

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# CRITICAL: Use centralized paths API
from src.signal_recorder.paths import get_paths, GRAPEPaths

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


def find_drf_channels(paths: GRAPEPaths) -> List[Tuple[str, Path]]:
    """Discover channels that have Digital RF output using paths API.

    Returns:
        List of (channel_name, drf_base_path) tuples
    """
    channels: List[Tuple[str, Path]] = []

    # Use paths API to discover all channels
    all_channels = paths.discover_channels()
    
    for channel_name in all_channels:
        drf_base = paths.get_digital_rf_dir(channel_name)
        if drf_base.exists():
            channels.append((channel_name, drf_base))
            logger.info(f"Found Digital RF channel: {channel_name} at {drf_base}")

    return channels


def read_drf_day(drf_base: Path, date_str: str, safe_channel_name: str) -> Optional[Tuple[np.ndarray, np.ndarray, float]]:
    """Read 10 Hz IQ samples for a given day directly from Digital RF.

    Args:
        drf_base: Base Digital RF directory for this logical channel
        date_str: Date in YYYYMMDD format
        safe_channel_name: Channel name with spaces replaced by underscores

    Returns:
        (timestamps_unix, iq_10hz, sample_rate) or None if no data.
    """
    try:
        if not drf_base.exists():
            logger.warning(f"Digital RF base directory not found: {drf_base}")
            return None

        # DigitalRFWriter writes channel data under:
        #   {drf_base}/{YYYYMMDD}/CALL_GRID/RECEIVER@ID/OBS.../{CHANNEL}
        # and uses that deepest CHANNEL directory as the top-level path when
        # constructing the DigitalRFWriter. To mirror that on read, we scan
        # for drf_properties.h5 under the requested date and create readers
        # rooted at each CHANNEL directory that matches safe_channel_name.

        date_dir = drf_base / date_str
        if not date_dir.exists():
            logger.warning(f"No Digital RF directory for date {date_str}: {date_dir}")
            return None

        prop_files = list(date_dir.rglob('drf_properties.h5'))
        if not prop_files:
            logger.warning(f"No drf_properties.h5 files found for {date_str} under {date_dir}")
            return None

        all_samples: List[np.ndarray] = []
        all_indices: List[np.ndarray] = []
        sample_rate: Optional[float] = None

        for prop_file in sorted(prop_files):
            channel_dir = prop_file.parent
            if channel_dir.name != safe_channel_name:
                # Different logical channel under same date tree
                continue

            # digital_rf expects the top-level directory that contains
            # channel subdirectories (OBS directory), not the deepest
            # channel directory itself.
            obs_dir = channel_dir.parent
            logger.info(f"    Probing OBS directory: {obs_dir}")

            try:
                try:
                    reader = drf.DigitalRFReader(str(obs_dir))
                except ValueError as ve:
                    logger.warning(f"    Skipping {obs_dir} (DigitalRFReader error): {ve}")
                    continue

                channel_keys = reader.get_channels()
                logger.info(f"    Channels under {obs_dir}: {channel_keys}")
                if not channel_keys:
                    logger.warning(f"    No channels found in {obs_dir}")
                    continue

                if safe_channel_name not in channel_keys:
                    logger.warning(f"    Channel {safe_channel_name} not present under {obs_dir} (found: {channel_keys})")
                    continue

                ch = safe_channel_name

                try:
                    props = reader.get_properties(ch)
                    fs_num = props.get('sample_rate_numerator', 10)
                    fs_den = props.get('sample_rate_denominator', 1)
                    fs = fs_num / fs_den
                    sample_rate = fs

                    start, end = reader.get_bounds(ch)
                    logger.info(f"    get_bounds({ch!r}) -> start={start}, end={end}")
                    if start is None or end is None:
                        logger.warning(f"    Channel {ch}: empty bounds")
                        continue

                    count = int(end - start + 1)
                    logger.info(f"    About to read {count:,} samples from {ch} (indices {start}–{end})")

                    # DigitalRFReader.read(start_sample, end_sample, channel)
                    # Returns OrderedDict: {sample_index: numpy_array}
                    data_dict = reader.read(start, end, ch)
                    if not data_dict:
                        logger.warning(f"    Channel {ch}: read returned no data")
                        continue

                    # Concatenate all data segments and extract indices
                    data_segments = []
                    index_list = []
                    for idx, segment in data_dict.items():
                        # Segment shape is (N, 1) for complex data, squeeze to 1D
                        segment_1d = segment.squeeze()
                        data_segments.append(segment_1d)
                        index_list.extend(range(idx, idx + len(segment_1d)))
                    
                    if not data_segments:
                        logger.warning(f"    Channel {ch}: no data segments found")
                        continue
                    
                    data = np.concatenate(data_segments)
                    indices = np.array(index_list, dtype=np.int64)
                    all_samples.append(data)
                    all_indices.append(indices)
                except Exception as e:
                    logger.error(f"    Error reading Digital RF channel {ch}: {e}", exc_info=True)
                    continue
            except Exception as e:
                logger.error(f"    Error processing Digital RF directory {obs_dir}: {e}", exc_info=True)
                continue

        if not all_samples:
            logger.warning(f"No usable Digital RF samples found for {date_str} under {drf_base}")
            return None

        iq_10hz = np.concatenate(all_samples)
        indices = np.concatenate(all_indices)

        if sample_rate is None or sample_rate <= 0:
            sample_rate = 10.0

        timestamps = indices.astype(np.float64) / float(sample_rate)

        hours_of_data = iq_10hz.size / sample_rate / 3600.0
        logger.info(f"  ✅ Loaded {iq_10hz.size:,} samples @ {sample_rate:.2f} Hz ({hours_of_data:.1f} hours)")

        return timestamps, iq_10hz, float(sample_rate)

    except Exception as e:
        logger.error(f"Error reading Digital RF data: {e}", exc_info=True)
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
        
        # Convert spectrogram time axis to UTC datetime
        # t contains time offsets from start of data, timestamps[0] is the absolute start time
        plot_times = [datetime.fromtimestamp(timestamps[0] + offset, tz=timezone.utc) 
                     for offset in t]
        
        # Calculate actual data coverage for subtitle
        data_start = datetime.fromtimestamp(timestamps[0], tz=timezone.utc)
        data_end = datetime.fromtimestamp(timestamps[-1], tz=timezone.utc)
        hours_covered = (timestamps[-1] - timestamps[0]) / 3600
        coverage_str = f"Coverage: {data_start.strftime('%H:%M')} - {data_end.strftime('%H:%M')} UTC ({hours_covered:.1f} hrs)"
        
        # Parse date_str to get full 24-hour range for x-axis
        year = int(date_str.split('-')[0])
        month = int(date_str.split('-')[1])
        day = int(date_str.split('-')[2])
        day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        day_end = datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
        
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
        ax.set_title(f'{channel_name} - {date_str} - Carrier Spectrogram (10 Hz IQ)\n{coverage_str}', 
                    fontsize=14, fontweight='bold')
        
        # Force 24-hour x-axis range (00:00-23:59 UTC)
        ax.set_xlim(day_start, day_end)
        
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

    # Create centralized paths API instance
    paths = get_paths(args.data_root)
    
    # Setup output directory using paths API
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = paths.get_spectrograms_root()
    
    logger.info(f"Data root: {paths.data_root}")
    logger.info(f"Output dir: {output_dir}")

    # Discover channels that have Digital RF output using paths API
    channels = find_drf_channels(paths)

    if not channels:
        logger.warning(f"No Digital RF data found")
        return 1

    # Filter channels if specified
    if args.channels:
        filtered = [(c, p) for c, p in channels if c in args.channels]
        if not filtered:
            logger.error(f"None of the specified channels found: {args.channels}")
            return 1
        channels = filtered

    logger.info(f"Processing {len(channels)} channel(s)")

    success_count = 0
    for channel_name, drf_base in channels:
        logger.info(f"\n--- {channel_name} ---")

        # Read entire day
        safe_channel_name = channel_name.replace(' ', '_')
        result = read_drf_day(drf_base, date_str, safe_channel_name)

        if result:
            timestamps, iq_10hz, sample_rate = result

            # Generate spectrogram using paths API
            output_path = paths.get_spectrogram_path(channel_name, date_str, 'carrier')

            generate_spectrogram(
                timestamps=timestamps,
                iq_samples=iq_10hz,
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
