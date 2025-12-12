#!/usr/bin/env python3
"""
Decimate 20 kHz raw binary archives to 10 Hz for spectrograms and PSWS upload.

Reads: raw_archive/{CHANNEL}/{YYYYMMDD}/{timestamp}.bin (20 kHz complex64)
Writes: products/{CHANNEL}/decimated/{YYYYMMDD}.bin (10 Hz complex64)

Usage:
    python decimate_raw_to_10hz.py --data-root /var/lib/grape-recorder --date 20251211
    python decimate_raw_to_10hz.py --data-root /var/lib/grape-recorder --channel "WWV 10 MHz" --date 20251211
"""

import numpy as np
from scipy import signal
from pathlib import Path
from datetime import datetime, timezone
import json
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
INPUT_RATE = 20000  # 20 kHz input
OUTPUT_RATE = 10    # 10 Hz output
DECIMATION_FACTOR = INPUT_RATE // OUTPUT_RATE  # 2000
SAMPLES_PER_MINUTE_IN = INPUT_RATE * 60   # 1,200,000
SAMPLES_PER_MINUTE_OUT = OUTPUT_RATE * 60  # 600

# Standard channels
CHANNELS = [
    'WWV_2.5_MHz', 'CHU_3.33_MHz', 'WWV_5_MHz', 'CHU_7.85_MHz',
    'WWV_10_MHz', 'CHU_14.67_MHz', 'WWV_15_MHz', 'WWV_20_MHz', 'WWV_25_MHz'
]


def decimate_minute(samples: np.ndarray) -> np.ndarray:
    """
    Decimate 20 kHz samples to 10 Hz using multi-stage approach.
    
    Stage 1: 20kHz -> 400Hz (factor 50) using scipy.signal.decimate
    Stage 2: 400Hz -> 10Hz (factor 40) using scipy.signal.decimate
    """
    if len(samples) == 0:
        return np.array([], dtype=np.complex64)
    
    # Stage 1: 20kHz -> 400Hz (decimate by 50)
    stage1 = signal.decimate(samples, 50, ftype='fir', zero_phase=True)
    
    # Stage 2: 400Hz -> 10Hz (decimate by 40)
    stage2 = signal.decimate(stage1, 40, ftype='fir', zero_phase=True)
    
    return stage2.astype(np.complex64)


def process_channel_day(data_root: Path, channel_dir: str, date_str: str) -> dict:
    """
    Process one channel for one day: read all minute files, decimate, write output.
    
    Returns dict with statistics.
    """
    raw_dir = data_root / 'raw_archive' / channel_dir / date_str
    output_dir = data_root / 'products' / channel_dir / 'decimated'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / f'{date_str}.bin'
    meta_file = output_dir / f'{date_str}_meta.json'
    
    if not raw_dir.exists():
        logger.warning(f"No raw data directory: {raw_dir}")
        return {'status': 'no_data', 'channel': channel_dir}
    
    # Find all minute files for this date
    bin_files = sorted(raw_dir.glob('*.bin'))
    if not bin_files:
        logger.warning(f"No binary files in {raw_dir}")
        return {'status': 'no_files', 'channel': channel_dir}
    
    # Parse date to get day boundaries
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    day_start = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
    day_start_ts = int(day_start.timestamp())
    
    # Initialize output array (864,000 samples = 10 Hz * 86400 seconds)
    output_samples = np.zeros(OUTPUT_RATE * 86400, dtype=np.complex64)
    
    minutes_processed = 0
    minutes_with_data = 0
    total_gaps = 0
    metadata = {
        'channel': channel_dir,
        'date': date_str,
        'sample_rate': OUTPUT_RATE,
        'samples_per_minute': SAMPLES_PER_MINUTE_OUT,
        'start_utc': float(day_start_ts),
        'minutes': {}
    }
    
    for bin_file in bin_files:
        try:
            # Parse minute boundary from filename
            minute_ts = int(bin_file.stem)
            
            # Check if this minute belongs to this date
            if minute_ts < day_start_ts or minute_ts >= day_start_ts + 86400:
                continue
            
            # Calculate minute index within the day
            minute_index = (minute_ts - day_start_ts) // 60
            
            # Load metadata if available
            json_file = bin_file.with_suffix('.json')
            minute_meta = {}
            if json_file.exists():
                with open(json_file) as f:
                    minute_meta = json.load(f)
            
            # Load and decimate samples
            samples = np.fromfile(bin_file, dtype=np.complex64)
            decimated = decimate_minute(samples)
            
            # Write to output array at correct position
            start_idx = minute_index * SAMPLES_PER_MINUTE_OUT
            end_idx = start_idx + len(decimated)
            
            if end_idx <= len(output_samples):
                output_samples[start_idx:end_idx] = decimated
                minutes_with_data += 1
                
                # Record metadata for this minute
                metadata['minutes'][str(minute_index)] = {
                    'minute_index': minute_index,
                    'utc_timestamp': float(minute_ts),
                    'samples_in': len(samples),
                    'samples_out': len(decimated),
                    'gap_count': minute_meta.get('gap_count', 0),
                    'gap_samples': minute_meta.get('gap_samples', 0),
                    'completeness_pct': minute_meta.get('completeness_pct', 100.0)
                }
                total_gaps += minute_meta.get('gap_count', 0)
            
            minutes_processed += 1
            
        except Exception as e:
            logger.error(f"Error processing {bin_file}: {e}")
            continue
    
    if minutes_with_data == 0:
        logger.warning(f"No valid data for {channel_dir} on {date_str}")
        return {'status': 'no_valid_data', 'channel': channel_dir}
    
    # Write output
    output_samples.tofile(output_file)
    
    # Update metadata summary
    metadata['minutes_processed'] = minutes_processed
    metadata['minutes_with_data'] = minutes_with_data
    metadata['total_gaps'] = total_gaps
    metadata['coverage_pct'] = 100.0 * minutes_with_data / 1440
    
    with open(meta_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"✅ {channel_dir}: {minutes_with_data}/1440 minutes ({metadata['coverage_pct']:.1f}% coverage)")
    logger.info(f"   Output: {output_file}")
    
    return {
        'status': 'success',
        'channel': channel_dir,
        'minutes_with_data': minutes_with_data,
        'coverage_pct': metadata['coverage_pct'],
        'output_file': str(output_file)
    }


def main():
    parser = argparse.ArgumentParser(description='Decimate 20 kHz raw to 10 Hz')
    parser.add_argument('--data-root', type=Path, default=Path('/var/lib/grape-recorder'),
                       help='Root data directory')
    parser.add_argument('--date', type=str, default=datetime.now(timezone.utc).strftime('%Y%m%d'),
                       help='Date to process (YYYYMMDD)')
    parser.add_argument('--channel', type=str, help='Single channel to process (e.g. WWV_10_MHz)')
    
    args = parser.parse_args()
    
    logger.info(f"Decimating raw 20 kHz to 10 Hz")
    logger.info(f"Data root: {args.data_root}")
    logger.info(f"Date: {args.date}")
    
    if args.channel:
        channels = [args.channel.replace(' ', '_')]
    else:
        channels = CHANNELS
    
    results = []
    for channel_dir in channels:
        logger.info(f"Processing {channel_dir}...")
        result = process_channel_day(args.data_root, channel_dir, args.date)
        results.append(result)
    
    # Summary
    success = sum(1 for r in results if r['status'] == 'success')
    logger.info(f"\nProcessed {success}/{len(channels)} channels")


if __name__ == '__main__':
    main()
