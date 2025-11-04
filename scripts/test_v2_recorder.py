#!/usr/bin/env python3
"""
Test V2 Recorder in Parallel with Production

This script runs the new V2 recorder WITHOUT touching the production daemon.
It listens to the same RTP stream and writes to a separate test directory.
"""

import sys
import signal
import logging
import argparse
from pathlib import Path
import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.grape_channel_recorder_v2 import GRAPEChannelRecorderV2
from signal_recorder.grape_rtp_recorder import RTPReceiver, RTPHeader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestRecorder:
    """Test harness for V2 recorder"""
    
    def __init__(self, multicast_addr: str, port: int, test_output_dir: Path):
        self.test_output_dir = test_output_dir
        self.test_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirs
        self.archive_dir = test_output_dir / 'data'
        self.analytics_dir = test_output_dir / 'analytics'
        self.archive_dir.mkdir(exist_ok=True)
        self.analytics_dir.mkdir(exist_ok=True)
        
        # Station config
        self.station_config = {
            'callsign': 'TEST',
            'grid_square': 'CM87',
            'instrument_id': 'TEST-V2'
        }
        
        # RTP receiver
        self.receiver = RTPReceiver(multicast_addr, port)
        self.recorders = {}
        self.ssrc_registry = {}  # Keep track of seen SSRCs
        
        self.running = False
        logger.info(f"Test recorder initialized, output: {test_output_dir}")
    
    def _make_ssrc_handler(self, ssrc: int):
        """Create a handler for a specific SSRC"""
        def handler(header: RTPHeader, payload: bytes):
            try:
                if ssrc not in self.recorders:
                    # First packet from this SSRC - create recorder
                    channel_name = f"TEST_CH_{ssrc}"
                    logger.info(f"Creating recorder for SSRC {ssrc}")
                    
                    self.recorders[ssrc] = GRAPEChannelRecorderV2(
                        ssrc=ssrc,
                        channel_name=channel_name,
                        frequency_hz=2500000.0,  # Placeholder
                        archive_dir=self.archive_dir,
                        analytics_dir=self.analytics_dir,
                        station_config=self.station_config,
                        is_wwv_channel=False  # Can enable if testing WWV
                    )
                
                # Process packet
                self.recorders[ssrc].process_rtp_packet(header, payload)
            except Exception as e:
                logger.error(f"Error processing packet from SSRC {ssrc}: {e}", exc_info=True)
        
        return handler
    
    def discover_ssrcs(self, duration: int = 5):
        """Listen for a few seconds to discover SSRCs"""
        logger.info(f"Discovering SSRCs (listening for {duration} seconds)...")
        
        discovered = set()
        
        # Create temporary socket to sniff packets
        import socket as sock_module
        import struct
        
        temp_sock = sock_module.socket(sock_module.AF_INET, sock_module.SOCK_DGRAM)
        temp_sock.setsockopt(sock_module.SOL_SOCKET, sock_module.SO_REUSEADDR, 1)
        temp_sock.bind(('', self.receiver.port))
        
        # Join multicast
        try:
            mreq = struct.pack("4s4s",
                              sock_module.inet_aton(self.receiver.multicast_address),
                              sock_module.inet_aton('127.0.0.1'))
            temp_sock.setsockopt(sock_module.IPPROTO_IP, sock_module.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            mreq = struct.pack("4sl",
                              sock_module.inet_aton(self.receiver.multicast_address),
                              sock_module.INADDR_ANY)
            temp_sock.setsockopt(sock_module.IPPROTO_IP, sock_module.IP_ADD_MEMBERSHIP, mreq)
        
        temp_sock.settimeout(1.0)
        
        start_time = time.time()
        packet_count = 0
        
        while time.time() - start_time < duration:
            try:
                data, addr = temp_sock.recvfrom(8192)
                packet_count += 1
                
                # Parse SSRC from RTP header
                if len(data) >= 12:
                    ssrc = struct.unpack('>I', data[8:12])[0]
                    if ssrc not in discovered:
                        discovered.add(ssrc)
                        logger.info(f"  Discovered SSRC: {ssrc}")
            except sock_module.timeout:
                continue
            except Exception as e:
                logger.warning(f"Error during discovery: {e}")
        
        temp_sock.close()
        
        logger.info(f"Discovery complete: {len(discovered)} SSRCs found from {packet_count} packets")
        return discovered
    
    def run(self, duration_seconds: int = 300):
        """Run test for specified duration"""
        logger.info(f"Starting test run for {duration_seconds} seconds...")
        self.running = True
        
        # Setup signal handler
        def signal_handler(sig, frame):
            logger.info("Caught interrupt, stopping...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Phase 1: Discover SSRCs
        ssrcs = self.discover_ssrcs(duration=5)
        
        if not ssrcs:
            logger.error("No SSRCs discovered! Is RTP multicast running?")
            return
        
        # Phase 2: Register handlers for each discovered SSRC
        for ssrc in ssrcs:
            handler = self._make_ssrc_handler(ssrc)
            self.receiver.register_callback(ssrc, handler)
            logger.info(f"Registered handler for SSRC {ssrc}")
        
        # Phase 3: Start receiver
        self.receiver.start()
        
        # Wait for duration or interrupt
        start_time = time.time()
        try:
            while self.running and (time.time() - start_time) < duration_seconds:
                time.sleep(1)
                
                # Print stats every 30 seconds
                if int(time.time() - start_time) % 30 == 0:
                    self.print_stats()
        
        finally:
            logger.info("Stopping receiver...")
            self.receiver.stop()
            
            # Finalize all recorders
            date_str = time.strftime("%Y%m%d", time.gmtime())
            for ssrc, recorder in self.recorders.items():
                logger.info(f"Finalizing recorder {ssrc}...")
                recorder.finalize_day(date_str)
            
            self.print_final_stats()
    
    def print_stats(self):
        """Print current statistics"""
        logger.info("=" * 60)
        for ssrc, recorder in self.recorders.items():
            stats = recorder.get_stats()
            logger.info(f"SSRC {ssrc}: {stats['total_packets']} packets, "
                       f"{stats['packets_dropped']} dropped ({stats['packet_loss_percent']:.3f}%), "
                       f"{stats['minutes_written']} minutes written")
        logger.info("=" * 60)
    
    def print_final_stats(self):
        """Print final statistics and file locations"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST COMPLETE - FINAL STATISTICS")
        logger.info("=" * 60)
        
        for ssrc, recorder in self.recorders.items():
            stats = recorder.get_stats()
            logger.info(f"\nSSRC {ssrc} ({stats['channel_name']}):")
            logger.info(f"  Runtime: {stats['runtime_seconds']:.1f} seconds")
            logger.info(f"  Total packets: {stats['total_packets']}")
            logger.info(f"  Dropped packets: {stats['packets_dropped']}")
            logger.info(f"  Packet loss: {stats['packet_loss_percent']:.3f}%")
            logger.info(f"  Total samples: {stats['total_samples']}")
            logger.info(f"  Minutes written: {stats['minutes_written']}")
        
        logger.info(f"\n📁 Output files:")
        logger.info(f"  Archive: {self.archive_dir}")
        logger.info(f"  Analytics: {self.analytics_dir}")
        
        # List minute files
        date_str = time.strftime("%Y%m%d", time.gmtime())
        date_dir = self.archive_dir / date_str
        if date_dir.exists():
            minute_files = list(date_dir.rglob("*.npz"))
            logger.info(f"  Minute files: {len(minute_files)}")
            if minute_files:
                logger.info(f"  Example: {minute_files[0]}")
        
        # List quality files
        quality_dir = self.analytics_dir / "quality" / date_str
        if quality_dir.exists():
            quality_files = list(quality_dir.glob("*.csv")) + list(quality_dir.glob("*.json"))
            logger.info(f"  Quality files: {len(quality_files)}")
            for qf in quality_files:
                logger.info(f"    - {qf.name}")
        
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Test V2 recorder in parallel")
    parser.add_argument('--multicast', default='239.192.152.141', help='Multicast address')
    parser.add_argument('--port', type=int, default=5004, help='Port')
    parser.add_argument('--duration', type=int, default=300, help='Test duration (seconds)')
    parser.add_argument('--output-dir', type=Path, default=Path('/tmp/grape-v2-test'),
                       help='Test output directory')
    
    args = parser.parse_args()
    
    logger.info(f"Starting V2 recorder test")
    logger.info(f"Multicast: {args.multicast}:{args.port}")
    logger.info(f"Duration: {args.duration} seconds")
    logger.info(f"Output: {args.output_dir}")
    logger.info("")
    logger.info("NOTE: This test runs INDEPENDENTLY of production daemon")
    logger.info("      It will not interfere with existing recordings")
    logger.info("")
    
    test = TestRecorder(args.multicast, args.port, args.output_dir)
    test.run(args.duration)
    
    logger.info("\n✅ Test complete. Check output files above.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
