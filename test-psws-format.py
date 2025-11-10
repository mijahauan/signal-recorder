#!/usr/bin/env python3
"""
Test PSWS-compatible Directory Format

Verifies that Digital RF writer creates wsprdaemon-compatible directory structure.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

# Setup path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_directory_structure():
    """Test PSWS directory structure matches wsprdaemon format"""
    
    logger.info("="*80)
    logger.info("PSWS Directory Structure Test")
    logger.info("="*80)
    
    # Expected wsprdaemon format:
    # YYYYMMDD/CALLSIGN_GRID/RECEIVER@STATION_ID_INSTRUMENT_ID/OBS{timestamp}/CHANNEL/
    
    # Our implementation
    output_dir = Path('/tmp/psws-test')
    timestamp = datetime(2024, 11, 9, 19, 30, 0, tzinfo=timezone.utc).timestamp()
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    
    station_config = {
        'callsign': 'AC0G',
        'grid_square': 'EN34',
        'receiver_name': 'GRAPE',
        'psws_station_id': 'AC0G',
        'psws_instrument_id': '1'
    }
    
    channel_name = 'WWV_10_MHz'
    
    # Build directory structure
    date_str = dt.date().strftime('%Y%m%d')
    callsign = station_config['callsign']
    grid = station_config['grid_square']
    receiver_name = station_config['receiver_name']
    psws_station_id = station_config['psws_station_id']
    psws_instrument_id = station_config['psws_instrument_id']
    safe_channel_name = channel_name.replace(' ', '_')
    
    # Build receiver_info: RECEIVER@STATION_ID_INSTRUMENT_ID
    receiver_info = f"{receiver_name}@{psws_station_id}_{psws_instrument_id}"
    
    # Build OBS timestamp subdirectory
    obs_timestamp = dt.strftime('OBS%Y-%m-%dT%H-%M')
    
    # Full path
    drf_dir = (output_dir / date_str / f"{callsign}_{grid}" / 
               receiver_info / obs_timestamp / safe_channel_name)
    
    logger.info("\nExpected wsprdaemon format:")
    logger.info("  YYYYMMDD/CALLSIGN_GRID/RECEIVER@STATION_ID_INSTRUMENT_ID/OBS{timestamp}/CHANNEL/")
    
    logger.info("\nGenerated path:")
    logger.info(f"  {drf_dir.relative_to(output_dir)}")
    
    logger.info("\nPath components:")
    logger.info(f"  Date:          {date_str}")
    logger.info(f"  Station:       {callsign}_{grid}")
    logger.info(f"  Receiver Info: {receiver_info}")
    logger.info(f"  OBS timestamp: {obs_timestamp}")
    logger.info(f"  Channel:       {safe_channel_name}")
    
    # Check format matches
    expected_pattern = f"{date_str}/{callsign}_{grid}/{receiver_name}@{psws_station_id}_{psws_instrument_id}/OBS{dt.strftime('%Y-%m-%dT%H-%M')}/{safe_channel_name}"
    actual_path = str(drf_dir.relative_to(output_dir))
    
    if actual_path == expected_pattern:
        logger.info("\n✅ Directory structure matches wsprdaemon format!")
        logger.info(f"\nFull example path:")
        logger.info(f"  {drf_dir}")
        return 0
    else:
        logger.error("\n❌ Directory structure MISMATCH")
        logger.error(f"  Expected: {expected_pattern}")
        logger.error(f"  Got:      {actual_path}")
        return 1


if __name__ == '__main__':
    sys.exit(test_directory_structure())
