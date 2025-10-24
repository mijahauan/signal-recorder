"""
Command-line interface for Signal Recorder
"""

import sys
import argparse
import logging
from pathlib import Path
import toml

from .app import SignalRecorderApp
from .discovery import StreamDiscovery
from .control_discovery import discover_channels_via_control
from .channel_manager import ChannelManager


def setup_logging(verbose: bool = False):
    """Setup logging configuration"""
    level = logging.DEBUG if verbose else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def load_config(config_path: str) -> dict:
    """Load configuration from TOML file"""
    config_file = Path(config_path)
    
    if not config_file.exists():
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        with open(config_file, 'r') as f:
            config = toml.load(f)
        return config
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_discover(args):
    """Discover available streams"""
    setup_logging(args.verbose)
    
    # Use control utility if available (much simpler and more reliable)
    status_addr = args.status if hasattr(args, 'status') and args.status else args.radiod
    
    print(f"Discovering channels from {status_addr} using control utility...\n")
    
    try:
        channels = discover_channels_via_control(status_addr, timeout=args.timeout)
        
        if channels:
            print(f"Found {len(channels)} channels:\n")
            print(f"{'SSRC':<12} {'Frequency':<15} {'Rate':<10} {'Preset':<8} {'SNR':<8} {'Address':<25}")
            print("-" * 85)
            
            for ssrc, channel in sorted(channels.items(), key=lambda x: x[1].frequency):
                freq_mhz = channel.frequency / 1e6
                snr_str = f"{channel.snr:.1f}" if channel.snr != float('-inf') else "-inf"
                addr_str = f"{channel.multicast_address}:{channel.port}"
                
                print(f"{ssrc:<12} {freq_mhz:>8.3f} MHz   {channel.sample_rate:<10} {channel.preset:<8} {snr_str:<8} {addr_str:<25}")
        else:
            print("No channels found")
            print("\nNote: Make sure 'control' utility from ka9q-radio is installed and in PATH")
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)


def cmd_daemon(args):
    """Run as daemon"""
    setup_logging(args.verbose)
    
    config = load_config(args.config)
    
    app = SignalRecorderApp(config)
    app.run_daemon()


def cmd_process(args):
    """Process a specific date"""
    setup_logging(args.verbose)
    
    config = load_config(args.config)
    
    app = SignalRecorderApp(config)
    app.run_once(args.date)


def cmd_status(args):
    """Show status"""
    setup_logging(args.verbose)
    
    config = load_config(args.config)
    
    app = SignalRecorderApp(config)
    status = app.get_status()
    
    print("=== Signal Recorder Status ===\n")
    
    print("Recorders:")
    if status['recorders']:
        for ssrc, info in status['recorders'].items():
            print(f"  {info['band_name']}: {info['frequency']/1e6:.3f} MHz")
            print(f"    Running: {info['running']}")
            print(f"    Output: {info['output_dir']}")
    else:
        print("  No recorders running")
    
    print("\nUploads:")
    uploads = status['uploads']
    print(f"  Total: {uploads['total']}")
    print(f"  Pending: {uploads['pending']}")
    print(f"  Uploading: {uploads['uploading']}")
    print(f"  Completed: {uploads['completed']}")
    print(f"  Failed: {uploads['failed']}")


def cmd_create_channels(args):
    """Create channels from configuration"""
    setup_logging(args.verbose)
    
    config = load_config(args.config)
    
    # Get ka9q configuration
    ka9q_config = config.get('ka9q', {})
    status_address = ka9q_config.get('status_address')
    
    if not status_address:
        print("Error: status_address not found in [ka9q] section", file=sys.stderr)
        sys.exit(1)
    
    # Get channel specifications from config
    recorder_config = config.get('recorder', {})
    channels_config = recorder_config.get('channels', [])
    
    if not channels_config:
        print("No channels defined in [recorder.channels] section", file=sys.stderr)
        sys.exit(1)
    
    # Convert to required format
    required_channels = []
    for ch in channels_config:
        required_channels.append({
            'ssrc': ch.get('ssrc'),
            'frequency_hz': ch.get('frequency_hz'),
            'preset': ch.get('preset', 'iq'),
            'sample_rate': ch.get('sample_rate'),
            'description': ch.get('description', '')
        })
    
    print(f"Creating {len(required_channels)} channels...\n")
    
    # Create channel manager
    manager = ChannelManager(status_address)
    
    try:
        # Ensure all channels exist
        success = manager.ensure_channels_exist(required_channels)
        
        print(f"\n=== Channel Creation Summary ===")
        print(f"Requested: {len(required_channels)} channels\n")
        
        if success:
            print("✓ All channels successfully created/verified")
            
            # Discover and show all channels
            all_channels = manager.discover_existing_channels()
            required_ssrcs = {ch['ssrc'] for ch in required_channels}
            
            print("\nChannels:")
            for ssrc in sorted(required_ssrcs):
                if ssrc in all_channels:
                    info = all_channels[ssrc]
                    print(f"  SSRC {ssrc:>10}: {info.frequency/1e6:>7.3f} MHz ({info.preset}) @ {info.multicast_address}")
        else:
            print("✗ Some channels failed to create")
            sys.exit(1)
    finally:
        manager.close()


def cmd_init(args):
    """Initialize configuration"""
    config_file = Path(args.config)
    
    if config_file.exists() and not args.force:
        print(f"Error: Configuration file already exists: {config_file}", file=sys.stderr)
        print("Use --force to overwrite", file=sys.stderr)
        sys.exit(1)
    
    # Create example configuration
    example_config = {
        'station': {
            'id': 'PSWS001',
            'instrument_id': '1',
            'callsign': 'CALL',
            'grid_square': 'AA00',
            'latitude': 0.0,
            'longitude': 0.0,
        },
        'recorder': {
            'archive_dir': '/var/lib/signal-recorder/archive',
            'file_length': 60,
            'compress': True,
            'compression_format': 'wavpack',
            'pcmrecord_path': 'pcmrecord',
            'streams': [
                {
                    'stream_name': 'WWV-IQ',
                    'frequencies': [
                        2500000,
                        5000000,
                        10000000,
                        15000000,
                        20000000,
                        25000000,
                        3330000,
                        7850000,
                        14670000,
                    ],
                    'processor': 'grape',
                    'band_mapping': {
                        2500000: 'WWV_2_5',
                        5000000: 'WWV_5',
                        10000000: 'WWV_10',
                        15000000: 'WWV_15',
                        20000000: 'WWV_20',
                        25000000: 'WWV_25',
                        3330000: 'CHU_3',
                        7850000: 'CHU_7',
                        14670000: 'CHU_14',
                    }
                }
            ]
        },
        'processors': {
            'grape': {
                'enabled': True,
                'target_sample_rate': 10,
                'output_format': 'digital_rf',
            }
        },
        'upload': {
            'protocol': 'ssh_rsync',
            'host': 'pswsnetwork.eng.ua.edu',
            'user': 'grape',
            'base_path': '/data/uploads',
            'max_retries': 5,
            'retry_backoff_base': 2,
            'timeout': 3600,
            'queue_file': '/var/lib/signal-recorder/upload_queue.json',
            'ssh': {
                'key_file': '/home/user/.ssh/id_rsa',
            }
        }
    }
    
    # Create directory
    config_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write configuration
    with open(config_file, 'w') as f:
        toml.dump(example_config, f)
    
    print(f"Created configuration file: {config_file}")
    print("\nPlease edit the configuration file to match your setup:")
    print(f"  - Station information (callsign, grid square, etc.)")
    print(f"  - Stream names from your radiod configuration")
    print(f"  - Upload credentials and paths")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Signal Recorder - Automated recording and upload for ka9q-radio',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover available streams
  signal-recorder discover --radiod wwv-iq.local
  
  # Initialize configuration
  signal-recorder init --config /etc/signal-recorder/config.toml
  
  # Run as daemon
  signal-recorder daemon --config /etc/signal-recorder/config.toml
  
  # Process a specific date
  signal-recorder process --date 20241022 --config /etc/signal-recorder/config.toml
  
  # Show status
  signal-recorder status --config /etc/signal-recorder/config.toml
"""
    )
    
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Enable verbose logging')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Discover command
    discover_parser = subparsers.add_parser('discover',
                                           help='Discover available streams from radiod')
    discover_parser.add_argument('--radiod', required=True,
                                help='Radiod data stream name (e.g., wwv-iq.local)')
    discover_parser.add_argument('--status',
                                help='Status stream name if different from data (e.g., hf-status.local)')
    discover_parser.add_argument('--status-port', type=int,
                                help='Explicit status port (default: use resolved port or 5006)')
    discover_parser.add_argument('--timeout', type=float, default=5.0,
                                help='Discovery timeout in seconds (default: 5.0)')
    discover_parser.set_defaults(func=cmd_discover)
    
    # Create channels command
    create_parser = subparsers.add_parser('create-channels',
                                         help='Create channels from configuration')
    create_parser.add_argument('--config', required=True,
                              help='Configuration file path')
    create_parser.set_defaults(func=cmd_create_channels)
    
    # Init command
    init_parser = subparsers.add_parser('init',
                                       help='Initialize configuration file')
    init_parser.add_argument('--config', default='/etc/signal-recorder/config.toml',
                            help='Configuration file path')
    init_parser.add_argument('--force', action='store_true',
                            help='Overwrite existing configuration')
    init_parser.set_defaults(func=cmd_init)
    
    # Daemon command
    daemon_parser = subparsers.add_parser('daemon',
                                         help='Run as background daemon')
    daemon_parser.add_argument('--config', required=True,
                              help='Configuration file path')
    daemon_parser.set_defaults(func=cmd_daemon)
    
    # Process command
    process_parser = subparsers.add_parser('process',
                                          help='Process a specific date')
    process_parser.add_argument('--date', required=True,
                               help='Date to process (YYYYMMDD)')
    process_parser.add_argument('--config', required=True,
                               help='Configuration file path')
    process_parser.set_defaults(func=cmd_process)
    
    # Status command
    status_parser = subparsers.add_parser('status',
                                         help='Show status')
    status_parser.add_argument('--config', required=True,
                              help='Configuration file path')
    status_parser.set_defaults(func=cmd_status)
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Execute command
    args.func(args)


if __name__ == '__main__':
    main()

