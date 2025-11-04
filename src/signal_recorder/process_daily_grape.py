#!/usr/bin/env python3
"""
Daily GRAPE Post-Processing

Process archived 8 kHz minute files:
1. Load all 1440 minutes for a day
2. High-quality decimation (8 kHz → 10 Hz)
3. Create Digital RF format (wsprdaemon-compatible)
4. Embed quality metadata
5. Queue for upload
"""

import argparse
import logging
import numpy as np
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple, Optional
import json

try:
    import digital_rf as drf
    HAS_DIGITAL_RF = True
except ImportError:
    HAS_DIGITAL_RF = False
    print("WARNING: digital_rf not available", file=sys.stderr)

from scipy import signal as scipy_signal

logger = logging.getLogger(__name__)


def load_day_minutes(archive_dir: Path, date_str: str, channel_name: str) -> List[Tuple[datetime, np.ndarray]]:
    """
    Load all 1-minute files for a given day and channel
    
    Returns:
        List of (timestamp, iq_data) tuples, sorted by time
    """
    # Find all minute files for this date/channel
    date_path = archive_dir / date_str
    if not date_path.exists():
        raise FileNotFoundError(f"No data directory for date {date_str}")
    
    # Find channel directory (pattern matching)
    channel_pattern = channel_name.replace(' ', '_')
    channel_dirs = list(date_path.rglob(channel_pattern))
    
    if not channel_dirs:
        raise FileNotFoundError(f"No channel directory found for {channel_name}")
    
    channel_dir = channel_dirs[0]
    logger.info(f"Loading minute files from {channel_dir}")
    
    # Load all .npz files
    minute_files = sorted(channel_dir.glob("*.npz"))
    logger.info(f"Found {len(minute_files)} minute files")
    
    minutes_data = []
    for file_path in minute_files:
        try:
            data = np.load(file_path)
            iq = data['iq']
            timestamp = data['timestamp']
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            minutes_data.append((dt, iq))
        except Exception as e:
            logger.error(f"Failed to load {file_path}: {e}")
            continue
    
    logger.info(f"Successfully loaded {len(minutes_data)} minute files")
    return minutes_data


def fill_missing_minutes(minutes_data: List[Tuple[datetime, np.ndarray]], 
                         sample_rate: int = 8000) -> np.ndarray:
    """
    Concatenate minutes and fill gaps with zeros
    
    Args:
        minutes_data: List of (timestamp, iq_data)
        sample_rate: Sample rate (8000 Hz)
    
    Returns:
        24-hour array with gaps filled
    """
    samples_per_minute = sample_rate * 60
    samples_per_day = sample_rate * 86400
    
    # Create full day array
    day_array = np.zeros(samples_per_day, dtype=np.complex64)
    
    # Sort by timestamp
    minutes_data.sort(key=lambda x: x[0])
    
    # Place each minute in correct position
    for dt, iq_data in minutes_data:
        # Calculate sample index for this minute
        seconds_since_midnight = (dt.hour * 3600) + (dt.minute * 60)
        start_idx = seconds_since_midnight * sample_rate
        end_idx = start_idx + len(iq_data)
        
        if end_idx <= samples_per_day:
            day_array[start_idx:end_idx] = iq_data
        else:
            # Clip if overflows
            available = samples_per_day - start_idx
            day_array[start_idx:] = iq_data[:available]
            logger.warning(f"Clipped minute at {dt} (overflow)")
    
    # Count gaps
    non_zero = np.count_nonzero(day_array)
    completeness = (non_zero / samples_per_day) * 100
    logger.info(f"Day completeness: {completeness:.2f}% ({non_zero}/{samples_per_day} samples)")
    
    return day_array


def decimate_to_10hz(data_8khz: np.ndarray) -> np.ndarray:
    """
    High-quality decimation: 8000 Hz → 10 Hz
    
    Uses cascaded decimation for best anti-aliasing:
    - Stage 1: 8000 → 800 Hz (decimate by 10)
    - Stage 2: 800 → 80 Hz (decimate by 10)
    - Stage 3: 80 → 10 Hz (decimate by 8)
    
    Total: 800:1 ratio
    
    Args:
        data_8khz: Input at 8 kHz
    
    Returns:
        Output at 10 Hz
    """
    logger.info("Decimating 8 kHz → 10 Hz (3-stage FIR)")
    
    # Stage 1: 8000 → 800 Hz
    logger.info("  Stage 1: 8000 → 800 Hz")
    stage1 = scipy_signal.decimate(data_8khz, 10, ftype='fir', zero_phase=True)
    logger.info(f"  Stage 1 complete: {len(stage1)} samples")
    
    # Stage 2: 800 → 80 Hz
    logger.info("  Stage 2: 800 → 80 Hz")
    stage2 = scipy_signal.decimate(stage1, 10, ftype='fir', zero_phase=True)
    logger.info(f"  Stage 2 complete: {len(stage2)} samples")
    
    # Stage 3: 80 → 10 Hz
    logger.info("  Stage 3: 80 → 10 Hz")
    stage3 = scipy_signal.decimate(stage2, 8, ftype='fir', zero_phase=True)
    logger.info(f"  Stage 3 complete: {len(stage3)} samples @ 10 Hz")
    
    return stage3


def create_digital_rf(output_dir: Path, channel_name: str, frequency_hz: float,
                      data_10hz: np.ndarray, date_str: str, 
                      station_config: dict, quality_metadata: dict) -> str:
    """
    Create Digital RF dataset (wsprdaemon-compatible)
    
    Args:
        output_dir: Base output directory
        channel_name: Channel name
        frequency_hz: Center frequency
        data_10hz: Decimated 10 Hz data
        date_str: Date (YYYYMMDD)
        station_config: Station metadata
        quality_metadata: Quality metrics to embed
    
    Returns:
        UUID of created dataset
    """
    if not HAS_DIGITAL_RF:
        raise ImportError("digital_rf module required for Digital RF creation")
    
    import uuid
    
    # Parse date
    date_obj = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    start_time = date_obj.timestamp()
    start_global_index = int(start_time * 10)  # 10 Hz sample rate
    
    # Generate UUID
    dataset_uuid = uuid.uuid4().hex
    
    # Create directory structure
    drf_dir = output_dir / date_str / channel_name.replace(' ', '_')
    drf_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Creating Digital RF dataset:")
    logger.info(f"  Directory: {drf_dir}")
    logger.info(f"  Samples: {len(data_10hz)}")
    logger.info(f"  Start index: {start_global_index}")
    logger.info(f"  UUID: {dataset_uuid}")
    
    # Write RF data
    with drf.DigitalRFWriter(
        str(drf_dir),
        dtype=np.complex64,
        subdir_cadence_secs=3600,      # 1-hour subdirectories
        file_cadence_millisecs=1000,   # 1-second files
        start_global_index=start_global_index,
        sample_rate_numerator=10,
        sample_rate_denominator=1,
        uuid_str=dataset_uuid,
        compression_level=6,
        checksum=False,
        is_complex=True,
        num_subchannels=1,
        is_continuous=True,
        marching_periods=False
    ) as writer:
        writer.rf_write(data_10hz.astype(np.complex64))
    
    logger.info(f"Digital RF data written")
    
    # Write metadata (wsprdaemon-compatible + quality extensions)
    metadata_dir = drf_dir / 'metadata'
    metadata_dir.mkdir(parents=True, exist_ok=True)
    
    metadata = {
        # Standard wsprdaemon fields
        'callsign': station_config.get('callsign', 'UNKNOWN'),
        'grid_square': station_config.get('grid_square', 'UNKNOWN'),
        'receiver_name': station_config.get('instrument_id', 'UNKNOWN'),
        'center_frequencies': np.array([frequency_hz], dtype=np.float64),
        'uuid_str': dataset_uuid,
        'sample_rate': 10.0,
        'date': date_str,
        
        # NEW: Quality metadata (backward compatible)
        'quality_metadata': quality_metadata
    }
    
    with drf.DigitalMetadataWriter(
        str(metadata_dir),
        subdir_cadence_secs=3600,
        file_cadence_secs=3600,
        sample_rate_numerator=10,
        sample_rate_denominator=1,
        file_name='metadata'
    ) as metadata_writer:
        metadata_writer.write(start_global_index, metadata)
    
    logger.info(f"Digital RF metadata written (with quality extensions)")
    
    return dataset_uuid


def process_channel_day(archive_dir: Path, output_dir: Path, analytics_dir: Path,
                        date_str: str, channel_name: str, frequency_hz: float,
                        station_config: dict) -> bool:
    """
    Process one channel for one day
    
    Returns:
        True if successful
    """
    logger.info(f"=" * 60)
    logger.info(f"Processing {channel_name} for {date_str}")
    logger.info(f"=" * 60)
    
    try:
        # Load minute files
        minutes_data = load_day_minutes(archive_dir, date_str, channel_name)
        
        if len(minutes_data) == 0:
            logger.error(f"No data found for {channel_name} on {date_str}")
            return False
        
        # Concatenate and fill gaps
        day_8khz = fill_missing_minutes(minutes_data, sample_rate=8000)
        
        # Decimate to 10 Hz
        day_10hz = decimate_to_10hz(day_8khz)
        
        # Load quality metadata
        quality_json = (analytics_dir / "quality" / date_str / 
                       f"{channel_name.replace(' ', '_')}_daily_summary_{date_str}.json")
        
        quality_metadata = {}
        if quality_json.exists():
            with open(quality_json, 'r') as f:
                quality_metadata = json.load(f)
            logger.info(f"Loaded quality metadata: {quality_metadata.get('data_completeness_percent', 0):.1f}% complete")
        else:
            logger.warning(f"No quality metadata found at {quality_json}")
        
        # Add processing metadata
        quality_metadata['processing'] = {
            'recorder_version': 'signal-recorder-0.2.0',
            'decimation_method': 'scipy.decimate-3stage-FIR',
            'decimation_stages': ['8000→800 (q=10)', '800→80 (q=10)', '80→10 (q=8)'],
            'filter_type': 'FIR',
            'zero_phase': True,
            'archive_format': 'npz-compressed',
            'processed_timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Create Digital RF
        uuid_str = create_digital_rf(
            output_dir=output_dir,
            channel_name=channel_name,
            frequency_hz=frequency_hz,
            data_10hz=day_10hz,
            date_str=date_str,
            station_config=station_config,
            quality_metadata=quality_metadata
        )
        
        logger.info(f"✅ Successfully processed {channel_name} for {date_str}")
        logger.info(f"   UUID: {uuid_str}")
        logger.info(f"   Output: {output_dir / date_str / channel_name.replace(' ', '_')}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to process {channel_name}: {e}", exc_info=True)
        return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Process daily GRAPE data")
    parser.add_argument('--date', required=True, help='Date to process (YYYYMMDD)')
    parser.add_argument('--channel', help='Specific channel (optional, processes all if not specified)')
    parser.add_argument('--archive-dir', type=Path, required=True, help='Archive directory')
    parser.add_argument('--output-dir', type=Path, required=True, help='Digital RF output directory')
    parser.add_argument('--analytics-dir', type=Path, required=True, help='Analytics directory')
    parser.add_argument('--config', type=Path, help='Config file for station metadata')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load station config
    station_config = {
        'callsign': 'UNKNOWN',
        'grid_square': 'UNKNOWN',
        'instrument_id': 'UNKNOWN'
    }
    
    if args.config and args.config.exists():
        import toml
        config = toml.load(args.config)
        if 'station' in config:
            station_config = config['station']
    
    # Determine channels to process
    if args.channel:
        channels = [(args.channel, 0.0)]  # Frequency will be loaded from files
    else:
        # Auto-discover channels
        date_path = args.archive_dir / args.date
        if not date_path.exists():
            logger.error(f"No data for date {args.date}")
            return 1
        
        # Find all channel directories
        channel_dirs = [d for d in date_path.rglob("*") if d.is_dir() and d.name not in ['metadata']]
        channels = [(d.name.replace('_', ' '), 0.0) for d in channel_dirs]
        logger.info(f"Auto-discovered {len(channels)} channels: {[c[0] for c in channels]}")
    
    # Process each channel
    success_count = 0
    for channel_name, frequency_hz in channels:
        if process_channel_day(
            archive_dir=args.archive_dir,
            output_dir=args.output_dir,
            analytics_dir=args.analytics_dir,
            date_str=args.date,
            channel_name=channel_name,
            frequency_hz=frequency_hz,
            station_config=station_config
        ):
            success_count += 1
    
    logger.info(f"")
    logger.info(f"=" * 60)
    logger.info(f"Processing complete: {success_count}/{len(channels)} channels successful")
    logger.info(f"=" * 60)
    
    return 0 if success_count == len(channels) else 1


if __name__ == '__main__':
    sys.exit(main())
