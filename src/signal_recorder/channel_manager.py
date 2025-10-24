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
    
    def ensure_channels_exist(self, required_channels: List[Dict]) -> bool:
        """
        Ensure all required channels exist, creating missing ones
        
        Args:
            required_channels: List of channel specifications, each with:
                - ssrc: int
                - frequency_hz: float
                - preset: str (optional, default "iq")
                - sample_rate: int (optional)
                - description: str (optional)
        
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
        
        if not missing_ssrcs:
            logger.info("✓ All required channels already exist")
            return True
        
        logger.info(f"Need to create {len(missing_ssrcs)} missing channels: {sorted(missing_ssrcs)}")
        
        # Create missing channels
        success_count = 0
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
                success_count += 1
        
        if success_count == len(missing_ssrcs):
            logger.info(f"✓ All {success_count} missing channels created successfully")
            return True
        else:
            logger.warning(
                f"⚠ Only {success_count}/{len(missing_ssrcs)} channels created successfully"
            )
            return False
    
    def close(self):
        """Close the control connection"""
        if self.control:
            self.control.close()

