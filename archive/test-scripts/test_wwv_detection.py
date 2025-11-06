#!/usr/bin/env python3
"""
Test WWV/CHU Tone Detection - Periodic capture at minute boundaries

Runs for 3.5 seconds starting at :59.5 of each minute to capture time signal tones.

Time signal characteristics:
- WWV (NIST): 1000 Hz tone for 0.8 seconds
- CHU (Canada): 1000 Hz tone for 0.5 seconds
Both start at :00.0 of each minute

Compares:
- System time (when tone detected)
- RTP timestamp 
- Expected time (:00.0)

This mimics how GRAPE should check for timing alignment.
"""

import sys
import time
import signal
import logging
from pathlib import Path
from datetime import datetime, timezone
import threading

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.grape_channel_recorder_v2 import GRAPEChannelRecorderV2
from signal_recorder.grape_rtp_recorder import RTPReceiver, RTPHeader
import toml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def calculate_time_to_next_boundary():
    """Calculate seconds until next minute boundary"""
    now = datetime.now(timezone.utc)
    seconds_in_minute = now.second + (now.microsecond / 1e6)
    
    # Time until :59.5 of current minute, or :59.5 of next minute
    if seconds_in_minute < 59.5:
        wait_time = 59.5 - seconds_in_minute
    else:
        wait_time = (60 - seconds_in_minute) + 59.5
    
    return wait_time, now


def main():
    config_file = Path('config/grape-S000171.toml')
    config = toml.load(config_file)
    
    # Find WWV 10 MHz channel
    wwv_10 = None
    for ch in config['recorder']['channels']:
        if ch.get('ssrc') == 10000000:
            wwv_10 = ch
            break
    
    if not wwv_10:
        logger.error("WWV 10 MHz channel not found in config")
        return 1
    
    # Setup directories
    test_dir = Path('/tmp/grape-wwv-test')
    test_dir.mkdir(exist_ok=True)
    archive_dir = test_dir / 'data'
    analytics_dir = test_dir / 'analytics'
    archive_dir.mkdir(exist_ok=True)
    analytics_dir.mkdir(exist_ok=True)
    
    logger.info("=" * 70)
    logger.info("WWV TONE DETECTION TEST")
    logger.info("=" * 70)
    logger.info(f"Testing: {wwv_10['description']} (SSRC {wwv_10['ssrc']})")
    logger.info(f"Output: {test_dir}")
    logger.info("")
    
    # Wait for next boundary
    wait_time, now = calculate_time_to_next_boundary()
    logger.info(f"Current time: {now.strftime('%H:%M:%S')}")
    logger.info(f"Waiting {wait_time:.1f} seconds for next minute boundary...")
    logger.info(f"WWV tone expected at: {now.strftime('%H:%M')}:00")
    logger.info("")
    
    time.sleep(wait_time)
    
    # Create recorder
    station_config = config['station']
    
    recorder = GRAPEChannelRecorderV2(
        ssrc=wwv_10['ssrc'],
        channel_name='WWV_10_MHz',
        frequency_hz=wwv_10['frequency_hz'],
        archive_dir=archive_dir,
        analytics_dir=analytics_dir,
        station_config=station_config,
        is_wwv_channel=True
    )
    
    logger.info("✅ WWV recorder created - starting RTP capture")
    logger.info("   Will check for tones during :59-:03 window each minute")
    logger.info("   Press Ctrl+C to stop")
    logger.info("")
    
    # Setup RTP receiver
    multicast_addr = config['ka9q']['status_address']
    receiver = RTPReceiver(multicast_addr, port=5004)
    
    packet_count = 0
    minutes_captured = 0
    detection_count = 0
    
    def packet_handler(header: RTPHeader, payload: bytes):
        nonlocal packet_count, minutes_captured, detection_count
        packet_count += 1
        
        try:
            recorder.process_rtp_packet(header, payload)
            
            # Check if we've written a new minute
            if recorder.file_writer.minutes_written > minutes_captured:
                minutes_captured = recorder.file_writer.minutes_written
                logger.info(f"✅ Minute {minutes_captured} completed")
                
                # Check for WWV detections
                if recorder.wwv_detections_today > detection_count:
                    detection_count = recorder.wwv_detections_today
                    logger.info(f"🎵 WWV TONE DETECTED! Total detections today: {detection_count}")
                    
                    # Get last minute quality
                    if recorder.quality_tracker.minute_metrics:
                        last = recorder.quality_tracker.minute_metrics[-1]
                        if last.wwv_timing_error_ms is not None:
                            logger.info(f"   Timing error: {last.wwv_timing_error_ms:+.2f} ms")
        
        except Exception as e:
            logger.error(f"Error processing packet: {e}", exc_info=True)
    
    receiver.register_callback(wwv_10['ssrc'], packet_handler)
    
    # Signal handler
    def signal_handler(sig, frame):
        logger.info("")
        logger.info("=" * 70)
        logger.info("STOPPING TEST")
        logger.info("=" * 70)
        logger.info(f"Total packets: {packet_count:,}")
        logger.info(f"Minutes captured: {minutes_captured}")
        logger.info(f"WWV detections: {detection_count}")
        logger.info("")
        
        receiver.stop()
        
        # Export quality data
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        csv_file = recorder.quality_tracker.export_minute_csv(date_str)
        if csv_file:
            logger.info(f"Quality CSV: {csv_file}")
        
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start receiver
    receiver.start()
    
    # Run 5 capture cycles (5 minute boundaries)
    logger.info("Will capture at 5 minute boundaries (3.5 seconds each)")
    logger.info("")
    
    cycles = 0
    max_cycles = 5
    
    while cycles < max_cycles:
        cycles += 1
        
        # Wait for next :59.5
        wait_time, now = calculate_time_to_next_boundary()
        next_boundary = now.strftime('%H:%M')
        logger.info(f"Cycle {cycles}/{max_cycles}: Sleeping {wait_time:.1f}s until {next_boundary}:59.5...")
        time.sleep(wait_time)
        
        # Capture for 3.5 seconds
        capture_start = time.time()
        logger.info(f"🎧 CAPTURING at {datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3]} (listening for WWV tone...)")
        
        # Just sleep - the packet_handler continues to process
        time.sleep(3.5)
        
        logger.info(f"   Capture complete ({3.5}s)")
        
        # Report status
        if recorder.wwv_detections_today > detection_count:
            detection_count = recorder.wwv_detections_today
            logger.info(f"   ✅ WWV TONE DETECTED! (Total: {detection_count})")
            
            if recorder.quality_tracker.minute_metrics:
                last = recorder.quality_tracker.minute_metrics[-1]
                if last.wwv_timing_error_ms is not None:
                    logger.info(f"   📊 Timing error: {last.wwv_timing_error_ms:+.2f} ms")
                    logger.info(f"   📊 System time vs RTP vs WWV alignment captured")
        else:
            logger.info(f"   ⚠️  No tone detected (signal may be weak)")
        
        logger.info("")
    
    signal_handler(None, None)


if __name__ == '__main__':
    sys.exit(main())
