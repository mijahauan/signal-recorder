#!/usr/bin/env python3
"""
Test V2 Recorder with Config Filtering

Only processes channels defined in GRAPE config (9 IQ channels)
"""

import sys
import signal
import logging
import argparse
import toml
from pathlib import Path
import time

# Configure logging BEFORE any other imports
# This ensures our logging configuration takes precedence
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG to see all WWV detection attempts
    format='%(levelname)s:%(name)s:%(message)s',
    force=True  # Force reconfiguration if logging was already set up
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.grape_channel_recorder_v2 import GRAPEChannelRecorderV2
from signal_recorder.grape_rtp_recorder import RTPReceiver, RTPHeader


def load_grape_channels(config_file: Path):
    """Load GRAPE channel definitions from config"""
    config = toml.load(config_file)
    
    grape_channels = []
    for ch in config.get('recorder', {}).get('channels', []):
        if ch.get('processor') == 'grape' and ch.get('enabled', False):
            grape_channels.append({
                'ssrc': ch['ssrc'],
                'frequency_hz': ch['frequency_hz'],
                'description': ch.get('description', 'Unknown'),
                'preset': ch.get('preset', 'iq')
            })
    
    return grape_channels


class GRAPETestRecorder:
    """Test harness for V2 recorder with config filtering"""
    
    def __init__(self, config_file: Path, multicast_addr: str, port: int, test_output_dir: Path = None):
        self.config_file = config_file
        
        # Load config
        full_config = toml.load(config_file)
        self.station_config = full_config.get('station', {})
        
        # Get data_root from config (or use provided test_output_dir)
        if test_output_dir:
            # Command-line override
            self.data_root = test_output_dir
            logger.info(f"Using command-line output directory: {test_output_dir}")
        else:
            # Read mode from config
            recorder_config = full_config.get('recorder', {})
            mode = recorder_config.get('mode', 'test')
            
            if mode == 'production':
                self.data_root = Path(recorder_config.get('production_data_root', '/var/lib/signal-recorder'))
                logger.info(f"🚀 PRODUCTION MODE: {self.data_root}")
            else:
                self.data_root = Path(recorder_config.get('test_data_root', '/tmp/grape-test'))
                logger.info(f"🧪 TEST MODE: {self.data_root}")
        
        self.data_root.mkdir(parents=True, exist_ok=True)
        
        # Create standard subdirs
        self.archive_dir = self.data_root / 'data'
        self.analytics_dir = self.data_root / 'analytics'
        self.archive_dir.mkdir(exist_ok=True)
        self.analytics_dir.mkdir(exist_ok=True)
        
        # Load GRAPE channels
        self.grape_channels = load_grape_channels(config_file)
        self.grape_ssrcs = {ch['ssrc'] for ch in self.grape_channels}
        
        logger.info(f"Loaded {len(self.grape_channels)} GRAPE channels from config:")
        for ch in self.grape_channels:
            logger.info(f"  SSRC {ch['ssrc']}: {ch['description']} ({ch['frequency_hz']/1e6:.2f} MHz)")
        
        # RTP receiver
        self.receiver = RTPReceiver(multicast_addr, port)
        self.recorders = {}
        
        self.running = False
        logger.info(f"Test recorder initialized, output: {test_output_dir}")
    
    def _make_ssrc_handler(self, ssrc: int, channel_info: dict):
        """Create a handler for a specific GRAPE SSRC"""
        def handler(header: RTPHeader, payload: bytes):
            try:
                if ssrc not in self.recorders:
                    # First packet from this SSRC - create recorder
                    channel_name = channel_info['description'].replace(' ', '_')
                    # Enable tone detection for both WWV and CHU (both use 1000 Hz tones)
                    is_wwv = 'WWV' in channel_info['description'] or 'CHU' in channel_info['description']
                    
                    logger.info(f"Creating recorder for {channel_info['description']} (SSRC {ssrc}), WWV detection={'enabled' if is_wwv else 'disabled'}")
                    
                    self.recorders[ssrc] = GRAPEChannelRecorderV2(
                        ssrc=ssrc,
                        channel_name=channel_name,
                        frequency_hz=channel_info['frequency_hz'],
                        archive_dir=self.archive_dir,
                        analytics_dir=self.analytics_dir,
                        station_config=self.station_config,
                        is_wwv_channel=is_wwv
                    )
                
                # Process packet
                self.recorders[ssrc].process_rtp_packet(header, payload)
            except Exception as e:
                logger.error(f"Error processing packet from SSRC {ssrc}: {e}", exc_info=True)
        
        return handler
    
    def run(self, duration_seconds: int = 300):
        """Run test for specified duration"""
        logger.info(f"Starting filtered test run for {duration_seconds} seconds...")
        logger.info(f"Filtering to {len(self.grape_ssrcs)} GRAPE channels only")
        self.running = True
        
        # Setup signal handler
        def signal_handler(sig, frame):
            logger.info("Caught interrupt, stopping...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Register handlers ONLY for configured GRAPE channels
        for ch in self.grape_channels:
            handler = self._make_ssrc_handler(ch['ssrc'], ch)
            self.receiver.register_callback(ch['ssrc'], handler)
        
        # Start receiver
        logger.info("Starting RTP receiver...")
        self.receiver.start()
        
        # Wait for duration or interrupt
        start_time = time.time()
        try:
            while self.running and (time.time() - start_time) < duration_seconds:
                time.sleep(1)
                
                # Print stats every 30 seconds
                elapsed = int(time.time() - start_time)
                if elapsed > 0 and elapsed % 30 == 0:
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
        logger.info(f"ACTIVE RECORDERS: {len(self.recorders)}/{len(self.grape_channels)}")
        for ssrc, recorder in self.recorders.items():
            stats = recorder.get_stats()
            ch_info = next((ch for ch in self.grape_channels if ch['ssrc'] == ssrc), None)
            desc = ch_info['description'] if ch_info else f"SSRC {ssrc}"
            
            logger.info(f"{desc}: {stats['total_packets']} packets, "
                       f"{stats['packets_dropped']} dropped ({stats['packet_loss_percent']:.3f}%), "
                       f"{stats['minutes_written']} minutes")
        logger.info("=" * 60)
    
    def print_final_stats(self):
        """Print final statistics and file locations"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("FILTERED TEST COMPLETE - FINAL STATISTICS")
        logger.info("=" * 60)
        
        logger.info(f"\nConfigured GRAPE channels: {len(self.grape_channels)}")
        logger.info(f"Active recorders: {len(self.recorders)}")
        
        if len(self.recorders) < len(self.grape_channels):
            missing = self.grape_ssrcs - set(self.recorders.keys())
            logger.warning(f"Missing {len(missing)} channels: {missing}")
            logger.warning("These channels may not be active on the multicast")
        
        for ssrc, recorder in sorted(self.recorders.items()):
            stats = recorder.get_stats()
            ch_info = next((ch for ch in self.grape_channels if ch['ssrc'] == ssrc), None)
            desc = ch_info['description'] if ch_info else f"SSRC {ssrc}"
            
            logger.info(f"\n{desc} (SSRC {ssrc}):")
            logger.info(f"  Runtime: {stats['runtime_seconds']:.1f} seconds")
            logger.info(f"  Total packets: {stats['total_packets']:,}")
            logger.info(f"  Dropped packets: {stats['packets_dropped']}")
            logger.info(f"  Packet loss: {stats['packet_loss_percent']:.3f}%")
            logger.info(f"  Total samples: {stats['total_samples']:,}")
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
            
            # Group by channel
            by_channel = {}
            for f in minute_files:
                channel = f.parent.name
                by_channel[channel] = by_channel.get(channel, 0) + 1
            
            for channel, count in sorted(by_channel.items()):
                logger.info(f"    {channel}: {count} files")
        
        # List quality files
        quality_dir = self.analytics_dir / "quality" / date_str
        if quality_dir.exists():
            quality_files = list(quality_dir.glob("*.csv")) + list(quality_dir.glob("*.json"))
            logger.info(f"  Quality files: {len(quality_files)}")
        
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Test V2 recorder with config filtering")
    parser.add_argument('--config', type=Path, required=True, help='GRAPE config file')
    parser.add_argument('--multicast', default='239.192.152.141', help='Multicast address')
    parser.add_argument('--port', type=int, default=5004, help='Port')
    parser.add_argument('--duration', type=int, default=300, help='Test duration (seconds)')
    parser.add_argument('--output-dir', type=Path, default=None,
                       help='Override output directory (default: read from config)')
    
    args = parser.parse_args()
    
    if not args.config.exists():
        logger.error(f"Config file not found: {args.config}")
        return 1
    
    logger.info(f"Starting GRAPE V2 recorder")
    logger.info(f"Config: {args.config}")
    logger.info(f"Multicast: {args.multicast}:{args.port}")
    logger.info(f"Duration: {args.duration} seconds")
    if args.output_dir:
        logger.info(f"Output: {args.output_dir} (override)")
    else:
        logger.info(f"Output: (from config)")
    logger.info("")
    logger.info("NOTE: Only configured GRAPE channels will be recorded")
    logger.info("      Other SSRCs on the multicast will be ignored")
    logger.info("")
    
    test = GRAPETestRecorder(args.config, args.multicast, args.port, args.output_dir)
    test.run(args.duration)
    
    logger.info("\n✅ Test complete. Check output files above.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
