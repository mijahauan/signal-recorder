"""
Channel management for ka9q-radio

This module creates and configures channels in radiod using the TLV control protocol.
"""

import logging
import time
from typing import List, Dict, Optional
from .control_discovery import discover_channels_via_control, ChannelInfo
from .radiod_control import RadiodControl

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
        channels = discover_channels_via_control(self.status_address)
        logger.info(f"Found {len(channels)} existing channels")
        return channels
    
    def create_channel(self, ssrc: int, frequency_hz: float, preset: str = "iq", 
                      sample_rate: Optional[int] = None, description: str = "") -> bool:
        """
        Create a new channel in radiod
        
        Args:
            ssrc: SSRC for the new channel
            frequency_hz: Frequency in Hz
            preset: Preset/mode (default: "iq")
            sample_rate: Sample rate in Hz (optional)
            description: Human-readable description
        
        Returns:
            True if successful
        """
        try:
            logger.info(
                f"Creating channel: SSRC={ssrc}, "
                f"freq={frequency_hz/1e6:.3f} MHz, "
                f"preset={preset}, "
                f"description='{description}'"
            )
            
            # Use radiod_control to create and configure
            self.control.create_and_configure_channel(
                ssrc=ssrc,
                frequency_hz=frequency_hz,
                preset=preset,
                sample_rate=sample_rate
            )
            
            # Wait for radiod to process
            time.sleep(0.5)
            
            # Verify the channel was created
            if self.control.verify_channel(ssrc, frequency_hz):
                logger.info(f"✓ Channel {ssrc} created successfully")
                return True
            else:
                logger.warning(f"✗ Channel {ssrc} verification failed")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create channel {ssrc}: {e}")
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
        logger.info(f"Ensuring {len(required_channels)} channels exist")
        
        # Discover existing channels
        existing = self.discover_existing_channels()
        existing_ssrcs = set(existing.keys())
        
        # Check which channels need to be created
        required_ssrcs = {ch['ssrc'] for ch in required_channels}
        missing_ssrcs = required_ssrcs - existing_ssrcs
        
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
                    freq_diff = abs(existing_ch.frequency_hz - req_freq) > 1.0  # 1 Hz tolerance
                    preset_diff = existing_ch.preset != req_preset
                    
                    if freq_diff or preset_diff:
                        logger.info(f"Channel {ssrc} needs update: freq={existing_ch.frequency_hz/1e6:.3f}->{req_freq/1e6:.3f} MHz, preset={existing_ch.preset}->{req_preset}")
                        channels_to_update.append(channel_spec)
        
        if not missing_ssrcs and not channels_to_update:
            logger.info("✓ All required channels already exist with correct parameters")
            return True
        
        if missing_ssrcs:
            logger.info(f"Need to create {len(missing_ssrcs)} missing channels: {sorted(missing_ssrcs)}")
        if channels_to_update:
            logger.info(f"Need to update {len(channels_to_update)} existing channels")
        
        # Create missing channels
        create_success = 0
        for channel_spec in required_channels:
            ssrc = channel_spec['ssrc']
            
            if ssrc not in missing_ssrcs:
                continue  # Already exists
            
            if self.create_channel(
                ssrc=ssrc,
                frequency_hz=channel_spec['frequency_hz'],
                preset=channel_spec.get('preset', 'iq'),
                sample_rate=channel_spec.get('sample_rate'),
                description=channel_spec.get('description', '')
            ):
                create_success += 1
        
        # Update existing channels
        update_success = 0
        for channel_spec in channels_to_update:
            ssrc = channel_spec['ssrc']
            logger.info(f"Updating channel {ssrc}")
            
            # Send update commands (same as create, but channel already exists)
            try:
                self.control.create_and_configure_channel(
                    ssrc=ssrc,
                    frequency_hz=channel_spec['frequency_hz'],
                    preset=channel_spec.get('preset', 'iq'),
                    sample_rate=channel_spec.get('sample_rate')
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

