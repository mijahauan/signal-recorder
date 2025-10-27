#!/usr/bin/env python3
"""
Command Line Interface for Signal Recorder
"""

import sys
import logging
import argparse
from .grape_recorder import GRAPERecorderManager

def main():
    """Main entry point for signal-recorder command"""
    # Configure logging to show INFO level and above
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s:%(name)s:%(message)s'
    )
    
    parser = argparse.ArgumentParser(description='Signal Recorder for GRAPE')
    parser.add_argument('command', choices=['daemon', 'discover'], help='Command to run')
    parser.add_argument('--config', '-c', help='Configuration file path')
    parser.add_argument('--radiod', '-r', help='RadioD address for discovery')
    
    args = parser.parse_args()
    
    if args.command == 'daemon':
        # Start daemon mode
        manager = GRAPERecorderManager(config_file=args.config)
        manager.run()
    elif args.command == 'discover':
        # Discovery mode
        manager = GRAPERecorderManager(config_file=args.config)
        manager.discover_channels(radiod_address=args.radiod)

if __name__ == '__main__':
    main()
