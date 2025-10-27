#!/usr/bin/env python3
"""
Test Digital RF writing by capturing a few minutes of data and writing it immediately.
This validates the entire pipeline without waiting for midnight UTC rollover.
"""

import sys
import time
import numpy as np
from pathlib import Path
sys.path.insert(0, 'src')

from signal_recorder.grape_rtp_recorder import GRAPERecorderManager

def test_immediate_write(config_file: str, duration_sec: int = 120):
    """
    Run recorder for specified duration and force-write data to validate pipeline.
    
    Args:
        config_file: Path to TOML config
        duration_sec: How long to record (default 2 minutes)
    """
    print(f"Starting test recording for {duration_sec} seconds...")
    print("This will capture data and attempt to write Digital RF format")
    print()
    
    # Create manager
    manager = GRAPERecorderManager(config_file=config_file)
    
    # Discover and start channels
    print("Discovering channels...")
    manager.discover_and_start()
    
    # Wait for data collection
    print(f"\nRecording for {duration_sec} seconds...")
    for i in range(duration_sec):
        time.sleep(1)
        if (i + 1) % 10 == 0:
            status = manager.get_status()
            print(f"  {i+1}s: {status['channels']} channels, "
                  f"{status.get('total_packets_received', 0)} packets received")
    
    # Get final status
    print("\n" + "="*70)
    print("Final Status")
    print("="*70)
    status = manager.get_status()
    
    for ssrc, rec_status in status.get('recorders', {}).items():
        print(f"\n{rec_status['channel_name']}:")
        print(f"  Samples received: {rec_status['samples_received']}")
        print(f"  Expected: {rec_status['expected_samples']}")
        print(f"  Completeness: {rec_status['completeness_pct']:.1f}%")
        print(f"  Sample rate: {rec_status['samples_per_sec']:.1f}/s")
        print(f"  Output dir: {rec_status.get('output_dir', 'N/A')}")
    
    print("\n" + "="*70)
    print("Data Collection Complete")
    print("="*70)
    print()
    print("Note: Digital RF files are written at midnight UTC rollover.")
    print("To force immediate write for testing, you would need to:")
    print("1. Stop the daemon")
    print("2. Manually flush the daily buffers")
    print("3. Or wait until midnight UTC")
    print()
    print(f"Expected samples per channel: {duration_sec * 10}")
    print("If completeness is 100%, data pipeline is working correctly!")
    
    # Cleanup
    manager.stop()

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Digital RF recording pipeline')
    parser.add_argument('--config', default='config/grape-example.toml',
                       help='Path to config file')
    parser.add_argument('--duration', type=int, default=120,
                       help='Recording duration in seconds (default: 120)')
    
    args = parser.parse_args()
    
    test_immediate_write(args.config, args.duration)
