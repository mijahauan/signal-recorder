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
            
            # Increased timeout to allow radiod to fully respond with all channel status messages
            channels = discover_channels_via_control(radiod_address, timeout=7.0)
            
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
    
    def create_channels(self):
        """Create all channels defined in the configuration"""
        print("Creating channels from configuration...")
        
        # Get configuration
        ka9q_config = self.config.get('ka9q', {})
        recorder_config = self.config.get('recorder', {})
        channels = recorder_config.get('channels', [])
        
        if not channels:
            print("No channels configured")
            return False
        
        # Get multicast address
        multicast_address = ka9q_config.get('status_address', '239.192.152.141')
        if ':' in multicast_address:
            multicast_address = multicast_address.split(':')[0]
        
        print(f"Using radiod at: {multicast_address}")
        print(f"Found {len(channels)} channels in configuration\n")
        
        # Import ChannelManager
        from .channel_manager import ChannelManager
        channel_manager = ChannelManager(multicast_address)
        
        # Build channel specifications
        required_channels = []
        for channel in channels:
            if not channel.get('enabled', True):
                continue
            
            required_channels.append({
                'ssrc': channel['ssrc'],
                'frequency_hz': channel['frequency_hz'],
                'preset': channel.get('preset', 'iq'),
                'sample_rate': channel.get('sample_rate', 16000),
                'agc': channel.get('agc', 0),
                'gain': channel.get('gain', 0),
                'description': channel.get('description', '')
            })
        
        print(f"Creating {len(required_channels)} enabled channels...")
        
        # Create the channels
        success = channel_manager.ensure_channels_exist(required_channels, update_existing=True)
        
        if success:
            print("\n✅ All channels created successfully!")
            print("\nVerify with: control -v", multicast_address)
            return True
        else:
            print("\n⚠️  Some channels failed to create. Check logs above.")
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
                    
                    # System-wide status header
                    print(f"\n{'='*80}")
                    print(f"📊 GRAPE Recorder Status - {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
                    print(f"{'='*80}")
                    
                    # Overall health summary
                    duration_min = status['recording_duration_sec'] // 60
                    duration_hrs = duration_min // 60
                    duration_min_rem = duration_min % 60
                    
                    print(f"Recording Duration: {duration_hrs}h {duration_min_rem}m")
                    print(f"Total Data Written: {status['total_data_mb']:.1f} MB")
                    print(f"Aggregate Packet Loss: {status['aggregate_packet_loss_pct']:.2f}%")
                    print(f"Channel Health: 🟢 {status['healthy_channels']} healthy  "
                          f"🟡 {status['warning_channels']} warning  "
                          f"🔴 {status['error_channels']} error")
                    print()
                    
                    # Per-channel details
                    for ssrc, rec in status['recorders'].items():
                        # Status indicator based on health
                        if rec['health_status'] == 'healthy':
                            indicator = '🟢'
                        elif rec['health_status'] == 'warning':
                            indicator = '🟡'
                        else:
                            indicator = '🔴'
                        
                        print(f"{indicator} {rec['channel_name']} ({rec['frequency_mhz']:.2f} MHz)")
                        print(f"   Status: {rec['health_message']}")
                        print(f"   Data: {rec['completeness_pct']:.1f}% complete | "
                              f"{rec['samples_received']:,} samples ({rec['samples_per_sec']:.1f}/s)")
                        print(f"   Packets: {rec['packets_received']:,} received | "
                              f"{rec['packets_dropped']} dropped ({rec['packet_loss_pct']:.2f}%)")
                        print(f"   Output: {rec['file_count']} files | "
                              f"{rec['total_size_mb']:.1f} MB | "
                              f"{rec['data_rate_kbps']:.1f} KB/s")
                        
                        # Warning for stale data
                        if rec['is_stale']:
                            print(f"   ⚠️  WARNING: No data received for {rec['data_freshness_sec']} seconds!")
                        
                        print()
                    
                    print(f"{'='*80}\n")
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
