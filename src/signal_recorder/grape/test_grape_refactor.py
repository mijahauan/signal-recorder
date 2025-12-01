#!/usr/bin/env python3
"""
Test script for refactored GRAPE recorder

Tests the new GrapeRecorder → RecordingSession → GrapeNPZWriter pipeline
with live data from ka9q-radio.

Run with: python3 -m signal_recorder.test_grape_refactor
"""

import sys
import time
import signal
import logging
import tempfile
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

from ..core.rtp_receiver import RTPReceiver
from .grape_recorder import GrapeRecorder, GrapeConfig, GrapeState

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger(__name__)


class RefactoredGrapeTest:
    """Test the refactored GRAPE recorder with live radiod"""
    
    def __init__(self):
        self.rtp_receiver = None
        self.recorder = None
        self.output_dir = None
        self.running = False
        
    def setup(self):
        """Initialize test components"""
        # Create temp output directory
        self.output_dir = Path(tempfile.mkdtemp(prefix='grape_test_'))
        logger.info(f"Output directory: {self.output_dir}")
        
        # Create RTP receiver (standard ka9q-radio multicast)
        self.rtp_receiver = RTPReceiver(
            multicast_address='239.1.2.55',  # Standard ka9q multicast
            port=5004
        )
        
        # Create GRAPE recorder config for 10 MHz WWV
        # SSRC is frequency in Hz (discovered from radiod)
        config = GrapeConfig(
            ssrc=10000000,  # 10 MHz WWV - SSRC = frequency in Hz
            frequency_hz=10e6,
            sample_rate=16000,
            description="WWV 10 MHz (test)",
            output_dir=self.output_dir,
            station_config={
                'callsign': 'TEST',
                'grid_square': 'EM38',
                'instrument_id': 'TEST-001',
            },
            startup_buffer_duration=30.0,  # Shorter for testing (30s instead of 120s)
            tone_check_interval=60.0,      # Check every minute for testing
        )
        
        # Mock NTP status
        def get_ntp_status():
            return {
                'offset_ms': 0.1,
                'synced': True,
                'last_update': time.time(),
            }
        
        # Create recorder
        self.recorder = GrapeRecorder(
            config=config,
            rtp_receiver=self.rtp_receiver,
            get_ntp_status=get_ntp_status,
        )
        
        logger.info("Test components initialized")
    
    def run(self, duration_sec: float = 180.0):
        """
        Run test for specified duration.
        
        Args:
            duration_sec: How long to run (default 3 minutes for 1+ NPZ files)
        """
        logger.info(f"Starting test (duration: {duration_sec}s)")
        
        # Start RTP receiver
        self.rtp_receiver.start()
        
        # Start recorder
        self.recorder.start()
        
        self.running = True
        start_time = time.time()
        last_status_time = 0
        
        try:
            while self.running and (time.time() - start_time) < duration_sec:
                time.sleep(1)
                
                # Log status every 10 seconds
                if time.time() - last_status_time >= 10:
                    status = self.recorder.get_status()
                    logger.info(
                        f"State: {status['state']}, "
                        f"Packets: {status.get('packets_received', 0)}, "
                        f"NPZ files: {status.get('npz_files_written', 0)}"
                    )
                    last_status_time = time.time()
                    
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            
        finally:
            self.stop()
    
    def stop(self):
        """Stop test and cleanup"""
        self.running = False
        
        logger.info("Stopping recorder...")
        if self.recorder:
            self.recorder.stop()
        
        logger.info("Stopping RTP receiver...")
        if self.rtp_receiver:
            self.rtp_receiver.stop()
        
        logger.info("Test stopped")
    
    def verify_output(self):
        """Verify NPZ files were created correctly"""
        logger.info("\n" + "=" * 60)
        logger.info("VERIFICATION")
        logger.info("=" * 60)
        
        # Find NPZ files
        archives_dir = self.output_dir / 'archives'
        if not archives_dir.exists():
            logger.error("No archives directory created!")
            return False
        
        npz_files = list(archives_dir.rglob('*.npz'))
        logger.info(f"Found {len(npz_files)} NPZ file(s)")
        
        if len(npz_files) == 0:
            logger.warning("No NPZ files created - may need longer run time")
            return False
        
        # Verify each file
        all_valid = True
        for npz_path in npz_files:
            logger.info(f"\nFile: {npz_path.name}")
            
            try:
                with np.load(npz_path) as data:
                    # Check required fields
                    required = ['iq', 'rtp_timestamp', 'sample_rate', 'time_snap_rtp', 'time_snap_utc']
                    missing = [f for f in required if f not in data.files]
                    
                    if missing:
                        logger.error(f"  Missing fields: {missing}")
                        all_valid = False
                        continue
                    
                    # Check IQ data
                    iq = data['iq']
                    logger.info(f"  IQ samples: {len(iq)}")
                    logger.info(f"  IQ dtype: {iq.dtype}")
                    logger.info(f"  Sample rate: {data['sample_rate']}")
                    
                    # Check time_snap
                    logger.info(f"  time_snap source: {data['time_snap_source']}")
                    logger.info(f"  time_snap confidence: {data['time_snap_confidence']:.2f}")
                    
                    # Check gaps
                    gaps = int(data['gaps_count'])
                    gap_samples = int(data['gaps_filled'])
                    completeness = 100.0 * (len(iq) - gap_samples) / len(iq) if len(iq) > 0 else 0
                    logger.info(f"  Gaps: {gaps}, {gap_samples} samples filled")
                    logger.info(f"  Completeness: {completeness:.1f}%")
                    
                    # Verify segment info
                    if 'segment_id' in data.files:
                        logger.info(f"  Segment ID: {data['segment_id']}")
                    
                    logger.info("  ✅ Valid NPZ file")
                    
            except Exception as e:
                logger.error(f"  ✗ Error reading file: {e}")
                all_valid = False
        
        return all_valid


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("GRAPE Refactored Recorder Test")
    logger.info("=" * 60)
    logger.info("")
    logger.info("This test verifies the refactored recording pipeline:")
    logger.info("  GrapeRecorder → RecordingSession → GrapeNPZWriter")
    logger.info("")
    
    # Parse args
    duration = 180.0  # 3 minutes default
    if len(sys.argv) > 1:
        try:
            duration = float(sys.argv[1])
        except ValueError:
            pass
    
    logger.info(f"Test duration: {duration}s")
    logger.info("")
    
    # Create test
    test = RefactoredGrapeTest()
    
    # Setup signal handler
    def handler(signum, frame):
        logger.info("Signal received, stopping...")
        test.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    
    try:
        # Setup
        test.setup()
        
        # Run
        test.run(duration_sec=duration)
        
        # Verify
        success = test.verify_output()
        
        if success:
            logger.info("\n✅ Test PASSED")
            return 0
        else:
            logger.warning("\n⚠️ Test completed with warnings")
            return 1
            
    except Exception as e:
        logger.error(f"Test FAILED: {e}", exc_info=True)
        return 2


if __name__ == '__main__':
    sys.exit(main())
