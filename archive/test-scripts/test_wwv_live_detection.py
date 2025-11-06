#!/usr/bin/env python3
"""
Test WWV Live Detection with Full Logging

Captures 3 minutes and shows real-time WWV tone detections
"""

import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.grape_channel_recorder_v2 import GRAPEChannelRecorderV2
from signal_recorder.grape_rtp_recorder import RTPReceiver
import toml

# Enable INFO logging to see tone detections
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    # Load config
    config = toml.load('config/grape-S000171.toml')
    
    # Find WWV 10 MHz
    wwv_10 = None
    for ch in config['recorder']['channels']:
        if ch.get('ssrc') == 10000000:
            wwv_10 = ch
            break
    
    if not wwv_10:
        logger.error("WWV 10 MHz not found in config")
        return 1
    
    # Setup directories
    test_dir = Path('/tmp/grape-wwv-live-test')
    test_dir.mkdir(exist_ok=True)
    archive_dir = test_dir / 'data'
    analytics_dir = test_dir / 'analytics'
    archive_dir.mkdir(exist_ok=True)
    analytics_dir.mkdir(exist_ok=True)
    
    logger.info("="*80)
    logger.info("WWV LIVE TONE DETECTION TEST")
    logger.info("="*80)
    logger.info(f"Channel: {wwv_10['description']} (SSRC {wwv_10['ssrc']})")
    logger.info(f"Output: {test_dir}")
    
    # Wait for next minute boundary
    now = datetime.now(timezone.utc)
    sec = now.second
    if sec < 55:
        wait = 55 - sec
    else:
        wait = (60 - sec) + 55
    
    logger.info(f"Current: {now.strftime('%H:%M:%S')}")
    logger.info(f"Waiting {wait}s for minute boundary...")
    time.sleep(wait)
    
    logger.info("🎬 STARTING CAPTURE - Watch for 'WWV tone detected!' messages")
    logger.info("")
    
    # Create recorder with WWV detection enabled
    recorder = GRAPEChannelRecorderV2(
        ssrc=wwv_10['ssrc'],
        channel_name='WWV_10_MHz',
        frequency_hz=wwv_10['frequency_hz'],
        archive_dir=archive_dir,
        analytics_dir=analytics_dir,
        station_config=config['station'],
        is_wwv_channel=True  # Enable tone detection!
    )
    
    # Setup RTP receiver
    receiver = RTPReceiver(config['ka9q']['status_address'], port=5004)
    
    packet_count = 0
    detection_count = 0
    
    def packet_handler(header, payload):
        nonlocal packet_count, detection_count
        packet_count += 1
        
        try:
            recorder.process_rtp_packet(header, payload)
            
            # Check for new detections
            if recorder.wwv_detections_today > detection_count:
                detection_count = recorder.wwv_detections_today
                logger.info(f"")
                logger.info(f"{'*'*80}")
                logger.info(f"🎵 WWV TONE #{detection_count} DETECTED!")
                logger.info(f"{'*'*80}")
                logger.info(f"")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
    
    receiver.register_callback(wwv_10['ssrc'], packet_handler)
    receiver.start()
    
    # Run for 3 minutes (should see 3 detections)
    logger.info("Running for 3 minutes...")
    logger.info("Expected: 3 tone detections at :00 of each minute")
    logger.info("")
    
    start = time.time()
    while time.time() - start < 180:
        time.sleep(1)
    
    receiver.stop()
    
    logger.info("")
    logger.info("="*80)
    logger.info("TEST COMPLETE")
    logger.info("="*80)
    logger.info(f"Packets processed: {packet_count:,}")
    logger.info(f"WWV tones detected: {detection_count}")
    logger.info(f"Minutes written: {recorder.file_writer.minutes_written}")
    
    # Export quality data
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    csv_file = recorder.quality_tracker.export_minute_csv(date_str)
    if csv_file:
        logger.info(f"Quality CSV: {csv_file}")
        
        # Show tone detections from CSV
        import csv as csv_module
        with open(csv_file) as f:
            reader = csv_module.DictReader(f)
            logger.info("")
            logger.info("Detections from CSV:")
            for row in reader:
                if row['wwv_detected']:
                    logger.info(f"  {row['minute_start']}: error={row['wwv_error_ms']}ms")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
