#!/usr/bin/env python3
"""
GRAPE Recorder Manager

Manages recording from ka9q-radio streams and saves to Digital RF format.
"""

import sys
import time
import logging
import toml
from pathlib import Path

class GRAPERecorderManager:
    """Main class for managing GRAPE recording operations"""
    
    def __init__(self, config_file=None):
        """Initialize the recorder manager"""
        self.config_file = config_file or 'config/grape-S000171.toml'
        self.config = None
        self.running = False
        
        # Load configuration
        self._load_config()
        
    def _load_config(self):
        """Load configuration from TOML file"""
        try:
            with open(self.config_file, 'r') as f:
                self.config = toml.load(f)
            print(f"Loaded configuration from {self.config_file}")
        except Exception as e:
            print(f"Failed to load config {self.config_file}: {e}")
            self.config = {}
            
    def discover_channels(self, radiod_address=None):
        """Discover available channels from radiod or use config"""
        if not radiod_address:
            radiod_address = self.config.get('ka9q', {}).get('status_address', '127.0.0.1')

        print(f"Discovering channels from {radiod_address}")

        # Try to discover channels using control utility
        try:
            from .control_discovery import discover_channels_via_control
            
            channels = discover_channels_via_control(radiod_address, timeout=5.0)
            
            if channels:
                print("SSRC      Frequency  Rate   Preset  SNR    Address")
                print("--------- ---------- ------ ------- ------ ------------------")
                
                for ssrc, info in sorted(channels.items()):
                    freq_mhz = info.frequency / 1000000
                    snr_str = f"{info.snr:>4.1f}" if info.snr != float('-inf') else "-inf"
                    address = f"{info.multicast_address}:{info.port}"
                    
                    print(f"{ssrc:>8} {freq_mhz:>8.2f}MHz {info.sample_rate:>5} {info.preset:>6} {snr_str:>5} {address}")
                
                return True
            else:
                # No channels discovered, fall back to config
                print("No channels discovered via control utility, using config")
                
        except Exception as e:
            print(f"Control utility discovery failed: {e}, using config fallback")
        
        # Fallback: use channels from config
        try:
            if self.config and 'recorder' in self.config and 'channels' in self.config['recorder']:
                print("SSRC      Frequency  Rate   Preset  SNR    Address")
                print("--------- ---------- ------ ------- ------ ------------------")

                for channel in self.config['recorder']['channels']:
                    ssrc = channel.get('ssrc', 'N/A')
                    freq = channel.get('frequency_hz', 0) / 1000000
                    rate = channel.get('sample_rate', 12000)
                    preset = channel.get('preset', 'iq')
                    snr = 'N/A (test)'
                    address = radiod_address

                    print(f"{ssrc:>8} {freq:>8.2f}MHz {rate:>5} {preset:>6} {snr:>5} {address}")

                return True
            else:
                print("No channels configured")
                return False
        except Exception as e:
            print(f"Error discovering channels: {e}")
            return False
        
    def run(self):
        """Run the recorder daemon"""
        print(f"Starting GRAPE recorder daemon with config: {self.config_file}")
        print("Press Ctrl+C to stop...")

        self.running = True
        
        try:
            from .grape_rtp_recorder import GRAPERecorderManager as RTPRecorderManager
            
            # Initialize RTP recorder manager
            rtp_recorder = RTPRecorderManager(self.config)
            
            print(f"Archive directory: {self.config.get('recorder', {}).get('archive_dir', 'not configured')}")

            if self.config and 'recorder' in self.config and 'channels' in self.config['recorder']:
                enabled_channels = [c for c in self.config['recorder']['channels'] if c.get('enabled', True)]
                print(f"Starting RTP→Digital RF recorder for {len(enabled_channels)} channels...")
                
                for channel in enabled_channels:
                    print(f"  • {channel.get('description', 'Unknown')} ({channel.get('frequency_hz', 0)/1e6:.2f} MHz, SSRC {channel['ssrc']})")
            
            # Start RTP recording
            rtp_recorder.start()
            print("\n🎙️  Recording via direct RTP reception with scipy decimation")
            print("📊 Output: Digital RF format (10 Hz IQ, compressed HDF5)")
            print("\nPress Ctrl+C to stop...\n")
            
            # Main daemon loop with status updates
            status_interval = 30  # seconds
            last_status = time.time()
            
            while self.running:
                time.sleep(5)
                
                # Periodic status update
                if time.time() - last_status >= status_interval:
                    status = rtp_recorder.get_status()
                    print(f"\n{'='*70}")
                    print(f"Status Update - {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
                    print(f"{'='*70}")
                    print(f"Recorder: {'RUNNING' if status['running'] else 'STOPPED'}")
                    print(f"Active channels: {status['channels']}")
                    
                    for ssrc, rec_status in status['recorders'].items():
                        print(f"\n  {rec_status['channel_name']}:")
                        print(f"    Frequency: {rec_status['frequency_hz']/1e6:.2f} MHz")
                        print(f"    Packets received: {rec_status['packets_received']:,}")
                    
                    print(f"{'='*70}\n")
                    last_status = time.time()

        except KeyboardInterrupt:
            print("\n\nStopping daemon...")
            self.running = False
        except Exception as e:
            print(f"Error in daemon: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Clean shutdown
            try:
                if 'rtp_recorder' in locals():
                    print("Stopping RTP recorder...")
                    rtp_recorder.stop()
            except Exception as e:
                print(f"Error during shutdown: {e}")
            print("Daemon stopped")
            
    def stop(self):
        """Stop the recorder daemon"""
        self.running = False
        print("Daemon stopped")
