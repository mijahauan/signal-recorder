#!/usr/bin/env python3
"""
Regenerate Digital RF data from NPZ archives using current time_snap

This is a simple script to fix incorrectly-timestamped Digital RF data
by reading NPZ archives (which have correct RTP timestamps) and regenerating
the Digital RF files with proper timestamp conversion.

Usage:
    python3 scripts/regenerate_drf_from_npz.py --date 20251112 --channel "WWV 5 MHz"
"""

import argparse
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
import sys
import shutil

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

# CRITICAL: Use centralized paths API
from src.signal_recorder.paths import get_paths, GRAPEPaths

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_time_snap(state_file: Path):
    """Load time_snap from analytics state file"""
    if not state_file.exists():
        logger.error(f"State file not found: {state_file}")
        return None
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        
        if not state.get('time_snap'):
            logger.error("No time_snap in state file")
            return None
        
        ts = state['time_snap']
        logger.info(f"✅ Loaded time_snap:")
        logger.info(f"   Source: {ts['source']}")
        logger.info(f"   RTP: {ts['rtp_timestamp']}")
        logger.info(f"   UTC: {datetime.fromtimestamp(ts['utc_timestamp'], tz=timezone.utc)}")
        logger.info(f"   Confidence: {ts['confidence']:.2f}")
        
        return ts
    except Exception as e:
        logger.error(f"Failed to load time_snap: {e}")
        return None


def select_appropriate_time_snap(state_file: Path, date_str: str, paths: GRAPEPaths, channel_name: str):
    """Select appropriate time_snap from history for the target date.
    
    Handles RTP timestamp rollovers by finding a time_snap that produces
    a valid UTC timestamp for the first NPZ file of the target date.
    """
    if not state_file.exists():
        logger.error(f"State file not found: {state_file}")
        return None
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        
        # Find first NPZ file for the target date
        archives_dir = paths.get_archive_dir(channel_name)
        pattern = f"{date_str}T*Z_*_iq.npz"
        npz_files = sorted(archives_dir.glob(pattern))
        
        if not npz_files:
            logger.warning(f"No NPZ files found for {date_str}")
            # Fall back to current time_snap
            return state.get('time_snap')
        
        first_npz = np.load(npz_files[0])
        first_rtp = int(first_npz['rtp_timestamp'])
        logger.info(f"First NPZ: {npz_files[0].name} RTP={first_rtp}")
        
        # Try current time_snap first
        candidates = [state.get('time_snap')]
        # Add history if available
        if 'time_snap_history' in state:
            candidates.extend(state['time_snap_history'])
        
        # Parse target date and create a range (±12 hours to handle day boundaries)
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        target_date = datetime(year, month, day, tzinfo=timezone.utc)
        min_utc = target_date.timestamp() - 12 * 3600  # 12 hours before
        max_utc = target_date.timestamp() + 36 * 3600  # 36 hours after (to cover full day + margins)
        
        # Find time_snap that gives valid UTC for target date
        for ts in candidates:
            if not ts:
                continue
            rtp_diff = first_rtp - ts['rtp_timestamp']
            time_offset = rtp_diff / ts['sample_rate']
            utc = ts['utc_timestamp'] + time_offset
            dt = datetime.fromtimestamp(utc, tz=timezone.utc)
            
            # Check if UTC is within the valid range for target date
            if min_utc <= utc <= max_utc:
                logger.info(f"✅ Selected time_snap:")
                logger.info(f"   Source: {ts['source']}")
                logger.info(f"   RTP: {ts['rtp_timestamp']}")
                logger.info(f"   UTC: {datetime.fromtimestamp(ts['utc_timestamp'], tz=timezone.utc)}")
                logger.info(f"   First NPZ will map to: {dt}")
                return ts
        
        # If no valid time_snap found, log warning and use current
        logger.warning(f"Could not find time_snap that maps first NPZ to {date_str}")
        logger.warning(f"Using current time_snap (may produce incorrect timestamps)")
        return state.get('time_snap')
        
    except Exception as e:
        logger.error(f"Failed to select time_snap: {e}", exc_info=True)
        return None


def calculate_utc_from_rtp(rtp_timestamp, sample_rate, time_snap):
    """Calculate UTC timestamp from RTP using time_snap"""
    # time_snap maps: RTP timestamp -> UTC timestamp at that point
    # For any other RTP: UTC = time_snap_utc + (rtp - time_snap_rtp) / sample_rate
    
    rtp_diff = rtp_timestamp - time_snap['rtp_timestamp']
    time_offset = rtp_diff / sample_rate
    utc_timestamp = time_snap['utc_timestamp'] + time_offset
    
    return utc_timestamp


def regenerate_channel(paths: GRAPEPaths, channel_name: str, date_str: str, time_snap):
    """Regenerate Digital RF for a channel and date using paths API"""
    
    analytics_dir = paths.get_analytics_dir(channel_name)
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {channel_name}")
    logger.info(f"{'='*60}")
    
    # Log time_snap details for diagnostics
    logger.info(f"Time_snap for {channel_name}:")
    logger.info(f"  RTP: {time_snap['rtp_timestamp']}")
    logger.info(f"  UTC: {datetime.fromtimestamp(time_snap['utc_timestamp'], tz=timezone.utc)}")
    logger.info(f"  Source: {time_snap['source']}")
    logger.info(f"  Sample rate: {time_snap['sample_rate']}")
    
    # Find NPZ archives for the date using paths API
    archives_dir = paths.get_archive_dir(channel_name)
    if not archives_dir.exists():
        logger.error(f"Archives directory not found: {archives_dir}")
        return 0
    
    # Pattern: YYYYMMDDTHHMMSSZ_FREQUENCY_iq.npz
    pattern = f"{date_str}T*Z_*_iq.npz"
    npz_files = sorted(archives_dir.glob(pattern))
    
    if not npz_files:
        logger.warning(f"No NPZ files found for date {date_str}")
        return 0
    
    logger.info(f"Found {len(npz_files)} NPZ files")
    
    # Delete old incorrectly-timestamped Digital RF data for this date
    drf_dir = paths.get_digital_rf_dir(channel_name)
    date_dir = drf_dir / date_str
    if date_dir.exists():
        try:
            logger.info(f"Removing stale Digital RF data: {date_dir}")
            shutil.rmtree(date_dir)
        except Exception as e:
            logger.warning(f"  Could not remove {date_dir}: {e}")
    
    # Import Digital RF directly
    try:
        import digital_rf as drf
        from scipy import signal as scipy_signal
    except ImportError as e:
        logger.error(f"Cannot import Digital RF: {e}")
        return 0
    
    # Load station config
    config_file = paths.data_root.parent / 'config' / 'grape-config.toml'
    if config_file.exists():
        try:
            import toml
            with open(config_file, 'r') as f:
                config = toml.load(f)
            station_config = config.get('station', {})
        except Exception as e:
            logger.warning(f"Could not load config: {e}")
            station_config = {}
    else:
        station_config = {}
    
    # Parse channel name for frequency
    try:
        # e.g., "WWV_5_MHz" -> 5.0
        parts = channel_name.split('_')
        freq_str = parts[-2]  # "5"
        unit = parts[-1]  # "MHz"
        frequency_hz = float(freq_str) * 1e6 if unit == 'MHz' else float(freq_str) * 1e3
    except:
        logger.warning("Could not parse frequency from channel name, using 5 MHz")
        frequency_hz = 5e6
    
    # Create Digital RF output directory structure (PSWS format)
    # Format: {base}/YYYYMMDD/CALLSIGN_GRID/RECEIVER@STATION/OBS.../CHANNEL/
    date_display = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    callsign = station_config.get('callsign', 'UNKNOWN')
    grid = station_config.get('grid_square', 'UNKNOWN')
    receiver_name = station_config.get('receiver_name', 'GRAPE')
    psws_station_id = station_config.get('psws_station_id', 'UNKNOWN')
    psws_instrument_id = station_config.get('psws_instrument_id', '1')
    
    receiver_info = f"{receiver_name}@{psws_station_id}_{psws_instrument_id}"
    obs_timestamp = f"OBS{date_display}T00-00"
    
    # Use paths API to construct Digital RF directory
    drf_channel_dir = (
        paths.get_digital_rf_dir(channel_name) / date_str / f"{callsign}_{grid}" /
        receiver_info / obs_timestamp / channel_name
    )
    drf_channel_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Digital RF output: {drf_channel_dir}")
    
    # Create writer with proper settings
    try:
        # Calculate start index from first file using time_snap. We seed the
        # DRF index once from this UTC time and then advance by sample count
        # for each subsequent write to keep indices strictly monotonic even
        # if small timing adjustments occur.
        first_npz = np.load(npz_files[0])
        first_rtp = int(first_npz['rtp_timestamp'])
        first_sample_rate = int(first_npz['sample_rate'])
        first_utc = calculate_utc_from_rtp(first_rtp, first_sample_rate, time_snap)
        start_global_index = int(first_utc * 10)  # 10 Hz output rate
        
        # Log detailed index calculation for diagnostics
        logger.info(f"Index calculation for first NPZ ({npz_files[0].name}):")
        logger.info(f"  First RTP: {first_rtp}")
        logger.info(f"  First sample rate: {first_sample_rate}")
        logger.info(f"  First UTC: {datetime.fromtimestamp(first_utc, tz=timezone.utc)} ({first_utc})")
        logger.info(f"  Start global index: {start_global_index:,} (10 Hz)")
        logger.info(f"  Expected year: {datetime.fromtimestamp(first_utc, tz=timezone.utc).year}")
        
        # IMPORTANT: Pass start_global_index=0 to constructor. When you pass both
        # start_global_index to the constructor AND explicit indices to rf_write(),
        # DigitalRFWriter does unexpected calculations. Instead, pass 0 and rely
        # solely on the explicit index passed to rf_write().
        drf_writer = drf.DigitalRFWriter(
            str(drf_channel_dir),  # Channel directory (matches live writer layout)
            dtype=np.complex64,
            subdir_cadence_secs=86400,
            file_cadence_millisecs=3600000,
            start_global_index=0,
            sample_rate_numerator=10,
            sample_rate_denominator=1,
            compression_level=9,
            checksum=False,
            is_complex=True,
            num_subchannels=1,
            is_continuous=True,
            marching_periods=False
        )
        logger.info("✅ Created Digital RF writer")
    except Exception as e:
        logger.error(f"Failed to create Digital RF writer: {e}", exc_info=True)
        return 0

    # Monotonic index state for this channel/date. We intentionally advance
    # by len(decimated) for each write rather than recomputing from UTC for
    # every NPZ, which avoids occasional overlaps/backwards writes when
    # time_snap or RTP->UTC mapping shifts slightly.
    next_index = start_global_index
    
    # Process each NPZ file
    processed = 0
    for npz_file in npz_files:
        try:
            logger.info(f"Processing: {npz_file.name}")
            
            # Check for pre-decimated 10 Hz file (huge speedup!)
            # Format: 20251115T000000Z_10000000_iq_10hz.npz
            npz_10hz = npz_file.with_name(npz_file.name.replace('_iq.npz', '_iq_10hz.npz'))
            
            if npz_10hz.exists():
                # Use pre-decimated file (200x faster!)
                data = np.load(npz_10hz)
                decimated = data['iq_decimated'].astype(np.complex64)
                rtp_timestamp = int(data['rtp_timestamp'])
                sample_rate = int(data['sample_rate_original'])
                
                if processed == 0:
                    logger.info(f"  ✅ Using pre-decimated 10 Hz NPZ files (fast path)")
            else:
                # Fallback: Load 16 kHz and decimate
                data = np.load(npz_file)
                iq_samples = data['iq']
                rtp_timestamp = int(data['rtp_timestamp'])
                sample_rate = int(data['sample_rate'])
                
                if processed == 0:
                    logger.info(f"  ⚠️ No 10 Hz NPZ found, decimating live (slow path)")
                
                # Decimate from 16 kHz to 10 Hz
                decimation_factor = sample_rate // 10  # 16000 / 10 = 1600
                decimated = scipy_signal.decimate(iq_samples, decimation_factor, ftype='fir', zero_phase=True)
                decimated = decimated.astype(np.complex64)
                
                logger.info(f"  Decimated: {len(iq_samples)} -> {len(decimated)} samples")
            
            # Calculate corrected UTC timestamp for diagnostics
            utc_timestamp = calculate_utc_from_rtp(rtp_timestamp, sample_rate, time_snap)
            
            if processed < 3:  # Log first few for debugging
                logger.info(f"  RTP: {rtp_timestamp}")
                logger.info(f"  Corrected UTC: {datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)}")
                logger.info(f"  Decimated samples: {len(decimated):,}")
            
            # Write to Digital RF using monotonic index sequence.
            if processed < 3:  # Log first 3 writes for debugging
                logger.info(f"  Writing at index: {next_index:,}")
            drf_writer.rf_write(decimated, int(next_index))
            next_index += len(decimated)
            if processed < 3:
                logger.info(f"  Next index after write: {next_index:,}")
            
            processed += 1
            
        except Exception as e:
            logger.error(f"  ❌ Failed: {e}", exc_info=True)
            continue
    
    # Close writer (Digital RF auto-flushes, no explicit flush method)
    logger.info("Closing Digital RF writer...")
    drf_writer.close()
    
    logger.info(f"✅ Processed {processed}/{len(npz_files)} files")
    return processed


def main():
    parser = argparse.ArgumentParser(
        description='Regenerate Digital RF from NPZ archives with corrected timestamps'
    )
    parser.add_argument('--date', required=True,
                       help='Date to regenerate (YYYYMMDD format)')
    parser.add_argument('--channel', type=str,
                       help='Specific channel (e.g., "WWV 5 MHz"), or all if not specified')
    parser.add_argument('--data-root', default='/tmp/grape-test',
                       help='Data root directory')
    
    args = parser.parse_args()
    
    # Create centralized paths API instance
    paths = get_paths(args.data_root)
    
    logger.info(f"Regenerating Digital RF for date: {args.date}")
    logger.info(f"Data root: {paths.data_root}")
    
    # Find channels to process using paths API
    if args.channel:
        # Single channel specified
        channels_to_process = [args.channel]
        # Verify it exists
        archive_dir = paths.get_archive_dir(args.channel)
        if not archive_dir.exists():
            logger.error(f"Channel not found: {args.channel}")
            return 1
    else:
        # Discover all channels
        channels_to_process = paths.discover_channels()
    
    logger.info(f"Processing {len(channels_to_process)} channel(s)")
    
    total_processed = 0
    
    for channel_name in channels_to_process:
        # Use paths API to get state file (handles all channel naming conversions)
        state_file = paths.get_analytics_state_file(channel_name)
        
        time_snap = select_appropriate_time_snap(state_file, args.date, paths, channel_name)
        
        if not time_snap:
            logger.warning(f"Skipping {channel_name} - no time_snap")
            continue
        
        # Regenerate Digital RF using paths API
        processed = regenerate_channel(paths, channel_name, args.date, time_snap)
        total_processed += processed
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Complete: Regenerated {total_processed} files")
    logger.info(f"{'='*60}")
    logger.info(f"\nNow try generating spectrograms:")
    logger.info(f"  python3 scripts/generate_spectrograms_drf.py --date {args.date}")
    
    return 0


if __name__ == '__main__':
    exit(main())
