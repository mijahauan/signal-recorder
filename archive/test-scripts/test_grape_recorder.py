#!/usr/bin/env python3
"""
Test script for GRAPE recorder

Tests the direct RTP→Digital RF pipeline with live data from ka9q-radio.
"""

import sys
import time
import signal
import logging
import toml
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from signal_recorder.grape_recorder import GRAPERecorderManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/grape_recorder_test.log')
    ]
)

logger = logging.getLogger(__name__)


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    logger.info("Received interrupt signal, stopping...")
    sys.exit(0)


def main():
    """Main test function"""
    logger.info("=" * 70)
    logger.info("GRAPE Recorder Test")
    logger.info("=" * 70)
    
    # Load configuration
    config_file = Path(__file__).parent / 'config' / 'grape-S000171.toml'
    
    if not config_file.exists():
        logger.error(f"Configuration file not found: {config_file}")
        return 1
    
    logger.info(f"Loading configuration from {config_file}")
    
    try:
        with open(config_file, 'r') as f:
            config = toml.load(f)
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        return 1
    
    # Display configuration summary
    logger.info(f"Station: {config['station']['callsign']} ({config['station']['grid_square']})")
    logger.info(f"Instrument: {config['station']['instrument_id']}")
    
    enabled_channels = [
        ch for ch in config['recorder']['channels']
        if ch.get('enabled', True) and ch.get('processor') == 'grape'
    ]
    
    logger.info(f"Enabled GRAPE channels: {len(enabled_channels)}")
    for ch in enabled_channels:
        logger.info(f"  - {ch['description']} @ {ch['frequency_hz'] / 1e6:.3f} MHz (SSRC 0x{ch['ssrc']:08x})")
    
    # Create recorder manager
    logger.info("\nInitializing GRAPE recorder manager...")
    
    try:
        manager = GRAPERecorderManager(config)
    except Exception as e:
        logger.error(f"Error creating recorder manager: {e}", exc_info=True)
        return 1
    
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start recording
    logger.info("\nStarting GRAPE recorders...")
    
    try:
        manager.start()
    except Exception as e:
        logger.error(f"Error starting recorders: {e}", exc_info=True)
        return 1
    
    logger.info("\nRecording started successfully!")
    logger.info("Press Ctrl+C to stop\n")
    
    # Monitor status
    try:
        status_interval = 30  # seconds
        last_status_time = time.time()
        
        while True:
            time.sleep(1)
            
            # Print status periodically
            current_time = time.time()
            if current_time - last_status_time >= status_interval:
                logger.info("\n" + "=" * 70)
                logger.info("Status Update")
                logger.info("=" * 70)
                
                status = manager.get_status()
                
                if status['running']:
                    logger.info(f"Recorder manager: RUNNING")
                    logger.info(f"Active channels: {len(status['channels'])}")
                    
                    for ssrc, channel_status in status['channels'].items():
                        logger.info(f"\n  {channel_status['description']}:")
                        logger.info(f"    Packets received: {channel_status['packets_received']:,}")
                        logger.info(f"    Packets dropped: {channel_status['packets_dropped']:,}")
                        logger.info(f"    Samples recorded: {channel_status['samples_recorded']:,}")
                        logger.info(f"    Data completeness: {channel_status['data_completeness']}")
                        logger.info(f"    Gaps: {channel_status['gaps']}")
                else:
                    logger.warning("Recorder manager: NOT RUNNING")
                
                logger.info("=" * 70 + "\n")
                last_status_time = current_time
    
    except KeyboardInterrupt:
        logger.info("\nReceived interrupt, stopping...")
    
    except Exception as e:
        logger.error(f"Error during recording: {e}", exc_info=True)
    
    finally:
        # Stop recording
        logger.info("\nStopping GRAPE recorders...")
        try:
            manager.stop()
            logger.info("Recorders stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping recorders: {e}", exc_info=True)
    
    logger.info("\nTest completed")
    return 0


if __name__ == '__main__':
    sys.exit(main())

