#!/usr/bin/env python3
"""
Measure RTP offset stability between paired channels

Tests whether carrier and wide channels tuned to the same frequency
share a stable RTP clock offset, enabling GPS-quality timing inheritance.

Usage:
    python3 scripts/measure_rtp_offset.py \
        --wide-channel "WWV 5 MHz" \
        --carrier-channel "WWV 5 MHz carrier" \
        --data-root /tmp/grape-test \
        --duration 3600
"""

import argparse
import logging
import sys
import time
import csv
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple, List
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def find_simultaneous_files(
    wide_dir: Path,
    carrier_dir: Path,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None
) -> List[Tuple[Path, Path]]:
    """
    Find pairs of NPZ files from same minute
    
    Returns:
        List of (wide_file, carrier_file) tuples
    """
    pairs = []
    
    # Get all wide channel files
    wide_files = sorted(wide_dir.glob('*_iq.npz'))
    carrier_files = sorted(carrier_dir.glob('*_iq.npz'))
    
    logger.info(f"Found {len(wide_files)} wide files, {len(carrier_files)} carrier files")
    
    # Create lookup by timestamp
    carrier_lookup = {}
    for cf in carrier_files:
        # Extract timestamp from filename: YYYYMMDDTHHmmssZ_...
        ts_str = cf.name.split('_')[0]
        carrier_lookup[ts_str] = cf
    
    # Match wide files to carrier files
    for wf in wide_files:
        ts_str = wf.name.split('_')[0]
        
        # Check time range filter
        if start_time or end_time:
            try:
                dt = datetime.strptime(ts_str, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                file_time = dt.timestamp()
                
                if start_time and file_time < start_time:
                    continue
                if end_time and file_time > end_time:
                    continue
            except ValueError:
                continue
        
        if ts_str in carrier_lookup:
            pairs.append((wf, carrier_lookup[ts_str]))
    
    logger.info(f"Found {len(pairs)} simultaneous file pairs")
    return pairs


def measure_offset(wide_file: Path, carrier_file: Path) -> Optional[Tuple[float, int, int, int]]:
    """
    Measure RTP offset between paired files
    
    Returns:
        (unix_timestamp, rtp_wide, rtp_carrier, offset) or None if error
    """
    try:
        wide_data = np.load(wide_file)
        carrier_data = np.load(carrier_file)
        
        unix_ts = float(wide_data['unix_timestamp'])
        rtp_wide = int(wide_data['rtp_timestamp'])
        rtp_carrier = int(carrier_data['rtp_timestamp'])
        
        # Calculate offset
        offset = rtp_carrier - rtp_wide
        
        return (unix_ts, rtp_wide, rtp_carrier, offset)
        
    except Exception as e:
        logger.warning(f"Failed to measure offset for {wide_file.name}: {e}")
        return None


def analyze_offset_stability(measurements: List[Tuple[float, int]]) -> dict:
    """
    Analyze offset stability statistics
    
    Args:
        measurements: List of (timestamp, offset) tuples
        
    Returns:
        Statistics dictionary
    """
    if not measurements:
        return {}
    
    offsets = np.array([o for _, o in measurements])
    timestamps = np.array([t for t, _ in measurements])
    
    # Basic statistics
    mean = np.mean(offsets)
    std = np.std(offsets)
    min_offset = np.min(offsets)
    max_offset = np.max(offsets)
    range_offset = max_offset - min_offset
    
    # Drift analysis (linear fit)
    if len(measurements) > 2:
        duration_hours = (timestamps[-1] - timestamps[0]) / 3600
        drift_per_hour = (offsets[-1] - offsets[0]) / duration_hours if duration_hours > 0 else 0
    else:
        duration_hours = 0
        drift_per_hour = 0
    
    # Jump detection (change > 1000 samples)
    jumps = 0
    if len(offsets) > 1:
        diffs = np.diff(offsets)
        jumps = np.sum(np.abs(diffs) > 1000)
    
    return {
        'count': len(measurements),
        'mean': mean,
        'std': std,
        'min': min_offset,
        'max': max_offset,
        'range': range_offset,
        'duration_hours': duration_hours,
        'drift_per_hour': drift_per_hour,
        'jumps': jumps
    }


def main():
    parser = argparse.ArgumentParser(description='Measure RTP offset between paired channels')
    parser.add_argument('--wide-channel', required=True, help='Wide channel name (e.g., "WWV 5 MHz")')
    parser.add_argument('--carrier-channel', required=True, help='Carrier channel name (e.g., "WWV 5 MHz carrier")')
    parser.add_argument('--data-root', default='/tmp/grape-test', help='Data root directory')
    parser.add_argument('--duration', type=int, help='Monitor duration in seconds (for live monitoring)')
    parser.add_argument('--output', help='Output CSV file for measurements')
    parser.add_argument('--live', action='store_true', help='Live monitoring mode (poll for new files)')
    
    args = parser.parse_args()
    
    # Convert channel names to directory names
    wide_dir_name = args.wide_channel.replace(' ', '_')
    carrier_dir_name = args.carrier_channel.replace(' ', '_')
    
    data_root = Path(args.data_root)
    wide_dir = data_root / 'archives' / wide_dir_name
    carrier_dir = data_root / 'archives' / carrier_dir_name
    
    if not wide_dir.exists():
        logger.error(f"Wide channel directory not found: {wide_dir}")
        return 1
    
    if not carrier_dir.exists():
        logger.error(f"Carrier channel directory not found: {carrier_dir}")
        return 1
    
    logger.info(f"Measuring RTP offset: {args.wide_channel} <-> {args.carrier_channel}")
    logger.info(f"Wide dir: {wide_dir}")
    logger.info(f"Carrier dir: {carrier_dir}")
    
    # Prepare output CSV
    output_file = None
    csv_writer = None
    if args.output:
        output_file = open(args.output, 'w', newline='')
        csv_writer = csv.writer(output_file)
        csv_writer.writerow(['timestamp', 'datetime_utc', 'rtp_wide', 'rtp_carrier', 'offset'])
    
    measurements = []
    start_time = time.time()
    
    try:
        if args.live:
            # Live monitoring mode
            logger.info(f"Live monitoring for {args.duration} seconds..." if args.duration else "Live monitoring (Ctrl+C to stop)...")
            
            processed_files = set()
            
            while True:
                # Check duration limit
                if args.duration and (time.time() - start_time) > args.duration:
                    logger.info("Duration limit reached")
                    break
                
                # Find new file pairs
                pairs = find_simultaneous_files(wide_dir, carrier_dir)
                
                for wide_file, carrier_file in pairs:
                    pair_id = (wide_file.name, carrier_file.name)
                    if pair_id in processed_files:
                        continue
                    
                    result = measure_offset(wide_file, carrier_file)
                    if result:
                        unix_ts, rtp_wide, rtp_carrier, offset = result
                        measurements.append((unix_ts, offset))
                        processed_files.add(pair_id)
                        
                        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
                        logger.info(f"Offset: {offset:+d} samples (RTP_wide={rtp_wide}, RTP_carrier={rtp_carrier})")
                        
                        if csv_writer:
                            csv_writer.writerow([unix_ts, dt.isoformat(), rtp_wide, rtp_carrier, offset])
                            output_file.flush()
                
                # Wait before next poll
                time.sleep(10)
        
        else:
            # Batch mode - process all existing files
            pairs = find_simultaneous_files(wide_dir, carrier_dir)
            
            for i, (wide_file, carrier_file) in enumerate(pairs):
                result = measure_offset(wide_file, carrier_file)
                if result:
                    unix_ts, rtp_wide, rtp_carrier, offset = result
                    measurements.append((unix_ts, offset))
                    
                    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
                    
                    if (i + 1) % 10 == 0:
                        logger.info(f"Processed {i + 1}/{len(pairs)} pairs...")
                    
                    if csv_writer:
                        csv_writer.writerow([unix_ts, dt.isoformat(), rtp_wide, rtp_carrier, offset])
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    finally:
        if output_file:
            output_file.close()
            logger.info(f"Measurements saved to: {args.output}")
    
    # Analyze results
    if measurements:
        logger.info(f"\n{'='*60}")
        logger.info("RTP Offset Stability Analysis")
        logger.info(f"{'='*60}")
        
        stats = analyze_offset_stability(measurements)
        
        logger.info(f"Measurements: {stats['count']}")
        logger.info(f"Duration: {stats['duration_hours']:.2f} hours")
        logger.info(f"Mean offset: {stats['mean']:.1f} samples")
        logger.info(f"Std deviation: {stats['std']:.3f} samples")
        logger.info(f"Range: {stats['min']} to {stats['max']} ({stats['range']} samples)")
        logger.info(f"Drift: {stats['drift_per_hour']:.3f} samples/hour")
        logger.info(f"Large jumps (>1000 samples): {stats['jumps']}")
        logger.info("")
        
        # Stability assessment
        if stats['std'] < 10:
            logger.info("✅ STABLE: Offset suitable for GPS-quality timing inheritance")
            logger.info("   Standard deviation < 10 samples (0.625ms @ 16 kHz)")
        elif stats['std'] < 100:
            logger.info("⚠️  MARGINAL: Offset may be usable but needs monitoring")
            logger.info("   Standard deviation 10-100 samples (0.6-6.25ms)")
        else:
            logger.info("❌ UNSTABLE: Offset not suitable for timing inheritance")
            logger.info("   Standard deviation > 100 samples (>6.25ms)")
            logger.info("   Continue using NTP_SYNCED for carrier channels")
        
        if stats['jumps'] > 0:
            logger.warning(f"⚠️  Detected {stats['jumps']} RTP clock resets/jumps")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
