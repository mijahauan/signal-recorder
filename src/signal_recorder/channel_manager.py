"""
Channel management for ka9q-radio

This module creates and configures channels in radiod using the TLV control protocol.
"""

import logging
import time
from typing import List, Dict, Optional
from ka9q import discover_channels, ChannelInfo, RadiodControl

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Manages channel creation and configuration for ka9q-radio
    
    Uses the TLV control protocol to send commands directly to radiod.
    """
    
    def __init__(self, status_address: str):
        """
        Initialize channel manager
        
        Args:
            status_address: mDNS name or IP:port of radiod status stream
        """
        self.status_address = status_address
        self.control = RadiodControl(status_address)
    
    def discover_existing_channels(self) -> Dict[int, ChannelInfo]:
        """
        Discover all existing channels from radiod
        
        Returns:
            Dictionary mapping SSRC to ChannelInfo
        """
        logger.info(f"Discovering existing channels from {self.status_address}")
        channels = discover_channels(self.status_address)
        logger.info(f"Found {len(channels)} existing channels")
        return channels
    
    def create_channel(self, ssrc: int, frequency_hz: float, preset: str = "iq", 
                      sample_rate: Optional[int] = None, agc: int = 0, gain: float = 0.0,
                      description: str = "") -> bool:
        """
        Create a new channel in radiod
        
        Args:
            ssrc: SSRC for the new channel
            frequency_hz: Frequency in Hz
            preset: Preset/mode (default: "iq")
            sample_rate: Sample rate in Hz (optional, default: 16000)
            agc: AGC enable (0=auto AGC, 1=manual) (default: 0)
            gain: Manual gain in dB (default: 0.0)
            description: Human-readable description
        
        Returns:
            True if successful
        """
        logger.info(f"🔧 create_channel() called for SSRC {ssrc}")
        try:
            logger.info(
                f"Creating channel: SSRC={ssrc}, "
                f"freq={frequency_hz/1e6:.3f} MHz, "
                f"preset={preset}, rate={sample_rate}Hz, "
                f"agc={agc}, gain={gain}dB, "
                f"description='{description}'"
            )
            
            logger.info(f"About to call self.control.create_channel()...")
            
            # Use radiod_control to create and configure channel (new ka9q-python API)
            # create_channel() now takes all parameters in one call
            self.control.create_channel(
                ssrc=ssrc,
                frequency_hz=frequency_hz,
                preset=preset,
                sample_rate=sample_rate,
                agc_enable=agc,
                gain=gain
            )
            
            logger.info(f"Channel creation complete, waiting 0.5s...")
            
            # Wait for radiod to process
            time.sleep(0.5)
            
            logger.info(f"Verifying channel {ssrc}...")
            
            # Verify the channel was created
            if self.control.verify_channel(ssrc, frequency_hz):
                logger.info(f"✓ Channel {ssrc} created successfully")
                return True
            else:
                logger.warning(f"✗ Channel {ssrc} verification failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ EXCEPTION in create_channel({ssrc}): {e}", exc_info=True)
            return False
    
    def ensure_channels_exist(self, required_channels: List[Dict], update_existing: bool = False) -> bool:
        """
        Ensure all required channels exist, creating missing ones and optionally updating existing ones
        
        Args:
            required_channels: List of channel specifications, each with:
                - ssrc: int
                - frequency_hz: float
                - preset: str (optional, default "iq")
                - sample_rate: int (optional)
                - description: str (optional)
            update_existing: If True, update existing channels if parameters differ
        
        Returns:
            True if all channels exist or were created successfully
        """
        logger.info(f"📋 ensure_channels_exist() called with {len(required_channels)} channels")
        logger.info(f"Required SSRCs: {[ch['ssrc'] for ch in required_channels]}")
        
        # Discover existing channels
        logger.info("Discovering existing channels...")
        existing = self.discover_existing_channels()
        existing_ssrcs = set(existing.keys())
        logger.info(f"Found {len(existing_ssrcs)} existing: {sorted(existing_ssrcs)}")
        
        # Check which channels need to be created
        required_ssrcs = {ch['ssrc'] for ch in required_channels}
        missing_ssrcs = required_ssrcs - existing_ssrcs
        logger.info(f"Missing SSRCs: {sorted(missing_ssrcs)}")
        
        # Check which existing channels need updates
        channels_to_update = []
        if update_existing:
            for channel_spec in required_channels:
                ssrc = channel_spec['ssrc']
                if ssrc in existing_ssrcs:
                    existing_ch = existing[ssrc]
                    req_freq = channel_spec['frequency_hz']
                    req_preset = channel_spec.get('preset', 'iq')
                    
                    # Check if frequency or preset differs
                    freq_diff = abs(existing_ch.frequency - req_freq) > 1.0  # 1 Hz tolerance
                    preset_diff = existing_ch.preset != req_preset
                    
                    if freq_diff or preset_diff:
                        logger.info(f"Channel {ssrc} needs update: freq={existing_ch.frequency/1e6:.3f}->{req_freq/1e6:.3f} MHz, preset={existing_ch.preset}->{req_preset}")
                        channels_to_update.append(channel_spec)
        
        if not missing_ssrcs and not channels_to_update:
            logger.info("✓ All required channels already exist with correct parameters")
            return True
        
        if missing_ssrcs:
            logger.info(f"⚙️  Need to create {len(missing_ssrcs)} missing channels: {sorted(missing_ssrcs)}")
        if channels_to_update:
            logger.info(f"Need to update {len(channels_to_update)} existing channels")
        
        # Create missing channels
        logger.info(f"🔄 Starting channel creation loop for {len(required_channels)} required channels")
        create_success = 0
        for channel_spec in required_channels:
            ssrc = channel_spec['ssrc']
            logger.info(f"  Loop iteration: SSRC {ssrc}")
            
            if ssrc not in missing_ssrcs:
                logger.info(f"    ↪️ SSRC {ssrc} already exists, skipping")
                continue  # Already exists
            
            logger.info(f"    ▶️  Calling create_channel() for SSRC {ssrc}")
            if self.create_channel(
                ssrc=ssrc,
                frequency_hz=channel_spec['frequency_hz'],
                preset=channel_spec.get('preset', 'iq'),
                sample_rate=channel_spec.get('sample_rate', 16000),
                agc=channel_spec.get('agc', 0),
                gain=channel_spec.get('gain', 0.0),
                description=channel_spec.get('description', '')
            ):
                create_success += 1
        
        # Update existing channels
        update_success = 0
        for channel_spec in channels_to_update:
            ssrc = channel_spec['ssrc']
            logger.info(f"Updating channel {ssrc}")
            
            # Update channel using create_channel (new ka9q-python API)
            # Note: create_channel updates if channel already exists
            try:
                self.control.create_channel(
                    ssrc=ssrc,
                    frequency_hz=channel_spec['frequency_hz'],
                    preset=channel_spec.get('preset', 'iq'),
                    sample_rate=channel_spec.get('sample_rate', 16000),
                    agc_enable=channel_spec.get('agc', 0),
                    gain=channel_spec.get('gain', 0.0)
                )
                time.sleep(0.5)
                
                if self.control.verify_channel(ssrc, channel_spec['frequency_hz']):
                    logger.info(f"✓ Channel {ssrc} updated successfully")
                    update_success += 1
                else:
                    logger.warning(f"✗ Channel {ssrc} update verification failed")
            except Exception as e:
                logger.error(f"Failed to update channel {ssrc}: {e}")
        
        # Report results
        total_operations = len(missing_ssrcs) + len(channels_to_update)
        total_success = create_success + update_success
        
        if total_success == total_operations:
            logger.info(f"✓ All {total_operations} channel operations successful")
            return True
        else:
            logger.warning(
                f"⚠ Only {total_success}/{total_operations} channel operations successful"
            )
            return False
    
    def close(self):
        """Close the control connection"""
        if self.control:
            self.control.close()


if __name__ == '__main__':
    import argparse
    import toml
    
    parser = argparse.ArgumentParser(description='Manage radiod channels')
    parser.add_argument('--config', required=True, help='Path to configuration file')
    parser.add_argument('--create', action='store_true', help='Create missing channels from config')
    parser.add_argument('--status-address', help='Radiod status address (default: from config)')
    args = parser.parse_args()
    
    # Load config
    with open(args.config) as f:
        config = toml.load(f)
    
    # Get status address
    status_address = args.status_address or config.get('ka9q', {}).get('status_address', '239.192.152.141')
    
    # Create channel manager
    manager = ChannelManager(status_address)
    
    if args.create:
        # Get channels from config
        channels = config.get('recorder', {}).get('channels', [])
        enabled_channels = [ch for ch in channels if ch.get('enabled', True)]
        
        if not enabled_channels:
            print("No enabled channels found in configuration")
            exit(1)
        
        # Build channel specs
        channel_specs = []
        for ch in enabled_channels:
            channel_specs.append({
                'ssrc': ch['ssrc'],
                'frequency_hz': ch['frequency_hz'],
                'preset': ch.get('preset', 'iq'),
                'sample_rate': ch.get('sample_rate', 16000),
                'agc': ch.get('agc', 0),
                'gain': ch.get('gain', 0.0),
                'description': ch.get('description', '')
            })
        
        print(f"Creating {len(channel_specs)} channels...")
        success = manager.ensure_channels_exist(channel_specs, update_existing=False)
        
        if success:
            print("✓ All channels created successfully")
            exit(0)
        else:
            print("⚠ Some channels failed to create")
            exit(1)
    else:
        # Just discover channels
        channels = manager.discover_existing_channels()
        print(f"Found {len(channels)} existing channels:")
        for ssrc, info in channels.items():
            print(f"  {ssrc}: {info.frequency/1e6:.3f} MHz, {info.preset}, {info.sample_rate} Hz")
