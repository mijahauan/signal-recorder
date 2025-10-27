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
    # Force level on root logger in case it was already configured
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Add handler if none exists
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
        root_logger.addHandler(handler)
    else:
        # Set level on existing handlers too
        for handler in root_logger.handlers:
            handler.setLevel(logging.INFO)
    
    # Test that INFO logging works
    logging.info("✓ Logging configured at INFO level")
    
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
