#!/usr/bin/env python3
"""
Reprocess Digital RF data with corrected timestamps after time_snap established

This script:
1. Reads NPZ archives that were processed before time_snap was established
2. Reads the current time_snap from analytics state
3. Regenerates Digital RF data with precise RTP-to-UTC conversion
4. Overwrites the incorrectly-timestamped Digital RF files

Usage:
    # Reprocess last N hours of data
    python3 scripts/reprocess_drf_timestamps.py --hours 24
    
    # Reprocess specific date
    python3 scripts/reprocess_drf_timestamps.py --date 20251112
    
    # Reprocess specific channel
    python3 scripts/reprocess_drf_timestamps.py --channel "WWV 5 MHz" --hours 6
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.signal_recorder.analytics_service import AnalyticsService, ProcessingState

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def reprocess_channel(
    analytics_service: AnalyticsService,
    archives_dir: Path,
    start_time: datetime,
    end_time: datetime
):
    """
    Reprocess Digital RF data for a channel within time range
    
    Args:
        analytics_service: Analytics service with time_snap
        archives_dir: Channel archives directory
        start_time: Start of time range (UTC)
        end_time: End of time range (UTC)
    """
    # Check if time_snap is established
    if not analytics_service.state.time_snap:
        logger.error(f"❌ Cannot reprocess: time_snap not established for {archives_dir.name}")
        logger.error("   Wait for WWV/CHU tone detection to establish time reference")
        return 0
    
    logger.info(f"✅ time_snap established: {analytics_service.state.time_snap.source}")
    logger.info(f"   Confidence: {analytics_service.state.time_snap.confidence:.2f}")
    logger.info(f"   UTC timestamp: {datetime.fromtimestamp(analytics_service.state.time_snap.utc_timestamp, tz=timezone.utc)}")
    
    # Find NPZ files in time range
    npz_files = []
    for npz_file in sorted(archives_dir.glob('*.npz')):
        # Parse timestamp from filename: WWV_5_MHz_YYYYMMDD_HHMMSS.npz
        try:
            parts = npz_file.stem.split('_')
            date_str = parts[-2]  # YYYYMMDD
            time_str = parts[-1]  # HHMMSS
            
            file_dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            file_dt = file_dt.replace(tzinfo=timezone.utc)
            
            if start_time <= file_dt < end_time:
                npz_files.append(npz_file)
        except (ValueError, IndexError):
            logger.warning(f"Could not parse timestamp from: {npz_file.name}")
            continue
    
    if not npz_files:
        logger.warning(f"No NPZ files found in time range for {archives_dir.name}")
        return 0
    
    logger.info(f"Found {len(npz_files)} NPZ files to reprocess")
    
    # Reprocess each file
    reprocessed = 0
    for npz_file in npz_files:
        try:
            logger.info(f"Reprocessing: {npz_file.name}")
            
            # Load archive
            archive = analytics_service.NPZArchive.load(npz_file)
            
            # Calculate corrected UTC timestamp using time_snap
            utc_timestamp = archive.calculate_utc_timestamp(analytics_service.state.time_snap)
            
            logger.info(f"  RTP timestamp: {archive.rtp_timestamp}")
            logger.info(f"  Corrected UTC: {datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)}")
            
            # Regenerate Digital RF data
            # The DRF writer will use the corrected timestamp
            if analytics_service.drf_writer:
                analytics_service.drf_writer.add_samples(utc_timestamp, archive.iq_samples)
                reprocessed += 1
                logger.info(f"  ✅ Reprocessed and wrote to Digital RF")
            else:
                logger.warning(f"  ⚠️  No DRF writer available")
                
        except Exception as e:
            logger.error(f"  ❌ Failed to reprocess {npz_file.name}: {e}")
            continue
    
    # Flush DRF writer
    if analytics_service.drf_writer:
        logger.info("Flushing Digital RF writer...")
        analytics_service.drf_writer.flush()
    
    logger.info(f"✅ Reprocessed {reprocessed}/{len(npz_files)} files")
    return reprocessed


def main():
    parser = argparse.ArgumentParser(
        description='Reprocess Digital RF data with corrected timestamps'
    )
    parser.add_argument('--hours', type=int, default=24,
                       help='Number of hours to reprocess (default: 24)')
    parser.add_argument('--date', type=str,
                       help='Specific date to reprocess (YYYYMMDD format)')
    parser.add_argument('--channel', type=str,
                       help='Specific channel to reprocess (e.g., "WWV 5 MHz")')
    parser.add_argument('--data-root', type=str, default='/tmp/grape-test',
                       help='Data root directory')
    
    args = parser.parse_args()
    
    # Determine time range
    if args.date:
        # Specific date
        year = int(args.date[:4])
        month = int(args.date[4:6])
        day = int(args.date[6:8])
        start_time = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(days=1)
        logger.info(f"Reprocessing date: {args.date}")
    else:
        # Last N hours
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=args.hours)
        logger.info(f"Reprocessing last {args.hours} hours")
    
    logger.info(f"Time range: {start_time} to {end_time}")
    
    # Setup paths
    data_root = Path(args.data_root)
    analytics_dir = data_root / 'analytics'
    
    if not analytics_dir.exists():
        logger.error(f"Analytics directory not found: {analytics_dir}")
        return 1
    
    # Find channels to reprocess
    if args.channel:
        channel_name = args.channel.replace(' ', '_')
        channel_dirs = [analytics_dir / channel_name]
    else:
        channel_dirs = [d for d in analytics_dir.iterdir() if d.is_dir()]
    
    logger.info(f"Found {len(channel_dirs)} channels to process")
    
    total_reprocessed = 0
    
    for channel_dir in channel_dirs:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing channel: {channel_dir.name}")
        logger.info(f"{'='*60}")
        
        archives_dir = channel_dir / 'archives'
        if not archives_dir.exists():
            logger.warning(f"No archives directory: {archives_dir}")
            continue
        
        # Load analytics service to get time_snap
        # This is a simplified approach - in production, load from state file
        try:
            # For now, load state from analytics service state file
            state_file = channel_dir / 'analytics_state.json'
            if not state_file.exists():
                logger.warning(f"No state file found: {state_file}")
                logger.warning("Cannot reprocess without time_snap reference")
                continue
            
            # Load state
            state = ProcessingState.load(state_file)
            
            if not state.time_snap:
                logger.warning(f"No time_snap in state for {channel_dir.name}")
                continue
            
            # Create minimal analytics service for reprocessing
            # TODO: This is simplified - proper implementation would load full config
            logger.info(f"✅ Loaded time_snap from state file")
            logger.info(f"   Source: {state.time_snap.source}")
            logger.info(f"   Confidence: {state.time_snap.confidence:.2f}")
            
            # For now, just log what would be done
            # Full implementation requires recreating analytics service
            logger.warning("⚠️  Reprocessing script needs full implementation")
            logger.warning("    Manual reprocessing required for now:")
            logger.warning(f"    1. Restart analytics service for {channel_dir.name}")
            logger.warning(f"    2. It will use existing time_snap for new data")
            logger.warning(f"    3. Old incorrectly-timestamped data remains in Digital RF")
            
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Summary: {total_reprocessed} files reprocessed")
    logger.info(f"{'='*60}")
    
    return 0


if __name__ == '__main__':
    exit(main())
