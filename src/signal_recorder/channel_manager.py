"""
Channel management for ka9q-radio

This module creates and configures channels dynamically using ka9q-radio's
command/status protocol. Channels are created on-demand based on configuration
rather than requiring manual radiod@.conf editing.
"""

import socket
import struct
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .control_discovery import discover_channels_via_control, ChannelInfo

logger = logging.getLogger(__name__)


@dataclass
class ChannelSpec:
    """Specification for a channel to create/configure"""
    ssrc: int
    frequency_hz: float
    preset: str = "iq"  # iq, usb, lsb, am, fm, etc.
    sample_rate: int = 16000
    description: str = ""


class ChannelManager:
    """Manages ka9q-radio channels via command/status protocol"""
    
    def __init__(self, status_address: str):
        """
        Initialize channel manager
        
        Args:
            status_address: Status multicast address (e.g., "bee1-hf-status.local")
        """
        self.status_address = status_address
        self.command_socket = None
        
    def ensure_channels(self, channel_specs: List[ChannelSpec]) -> Dict[int, ChannelInfo]:
        """
        Ensure all specified channels exist, creating them if necessary
        
        Args:
            channel_specs: List of channel specifications
            
        Returns:
            Dictionary mapping SSRC to ChannelInfo for all channels
        """
        logger.info(f"Ensuring {len(channel_specs)} channels exist")
        
        # Discover existing channels
        existing = discover_channels_via_control(self.status_address)
        existing_ssrcs = set(existing.keys())
        
        # Check which channels need to be created
        needed_ssrcs = {spec.ssrc for spec in channel_specs}
        missing_ssrcs = needed_ssrcs - existing_ssrcs
        
        if not missing_ssrcs:
            logger.info("All required channels already exist")
            return {ssrc: existing[ssrc] for ssrc in needed_ssrcs}
        
        logger.info(f"Need to create {len(missing_ssrcs)} channels: {sorted(missing_ssrcs)}")
        
        # Create missing channels
        for spec in channel_specs:
            if spec.ssrc in missing_ssrcs:
                self._create_channel(spec)
        
        # Wait a moment for channels to be created
        time.sleep(2)
        
        # Verify all channels now exist
        updated = discover_channels_via_control(self.status_address)
        result = {}
        
        for spec in channel_specs:
            if spec.ssrc in updated:
                result[spec.ssrc] = updated[spec.ssrc]
                logger.info(
                    f"Channel verified: SSRC={spec.ssrc}, "
                    f"freq={updated[spec.ssrc].frequency/1e6:.3f} MHz"
                )
            else:
                logger.error(f"Failed to create channel: SSRC={spec.ssrc}")
        
        return result
    
    def _create_channel(self, spec: ChannelSpec):
        """
        Create a new channel by sending commands to radiod
        
        This simulates what the 'control' utility does when you create a new SSRC.
        
        Args:
            spec: Channel specification
        """
        logger.info(
            f"Creating channel: SSRC={spec.ssrc}, "
            f"freq={spec.frequency_hz/1e6:.3f} MHz, "
            f"preset={spec.preset}"
        )
        
        try:
            # The control utility creates channels by:
            # 1. Sending a COMMAND packet with the new SSRC
            # 2. Setting frequency
            # 3. Setting preset/mode
            # 4. Setting sample rate (if needed)
            
            # For now, we'll use a simpler approach: invoke control utility
            # with scripted input to create the channel
            
            import subprocess
            
            # Script to create channel:
            # 1. Type the SSRC number (creates new channel)
            # 2. Set frequency (f command)
            # 3. Set preset (m command)
            # 4. Quit (q command)
            
            # Create command sequence with actual newlines
            commands = f"{spec.ssrc}\nf{spec.frequency_hz}\nm{spec.preset}\nq\n"
            
            # Run control with scripted input
            proc = subprocess.Popen(
                ['control', self.status_address],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = proc.communicate(input=commands, timeout=10)
            
            if proc.returncode != 0:
                logger.error(f"control utility failed: {stderr}")
            else:
                logger.debug(f"Channel creation output: {stdout}")
                
        except subprocess.TimeoutExpired:
            logger.error("Timeout creating channel")
            proc.kill()
        except FileNotFoundError:
            logger.error("control utility not found - is ka9q-radio installed?")
        except Exception as e:
            logger.error(f"Error creating channel: {e}")
    
    def delete_channel(self, ssrc: int):
        """
        Delete a channel
        
        Note: This may not be supported by all ka9q-radio versions.
        Channels typically persist until radiod is restarted.
        
        Args:
            ssrc: SSRC of channel to delete
        """
        logger.warning(f"Channel deletion not yet implemented for SSRC {ssrc}")
        # TODO: Implement if ka9q-radio supports channel deletion
    
    def configure_channel(self, ssrc: int, **params):
        """
        Configure parameters of an existing channel
        
        Args:
            ssrc: SSRC of channel to configure
            **params: Parameters to set (frequency, preset, sample_rate, etc.)
        """
        logger.info(f"Configuring channel SSRC={ssrc}: {params}")
        
        try:
            commands = [str(ssrc)]  # Select the channel
            
            if 'frequency' in params:
                commands.append(f"f{params['frequency']}")
            if 'preset' in params:
                commands.append(f"m{params['preset']}")
            if 'sample_rate' in params:
                commands.append(f"S{params['sample_rate']}")
            
            commands.append('q')  # Quit
            
            command_str = '\n'.join(commands) + '\n'
            
            proc = subprocess.Popen(
                ['control', self.status_address],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = proc.communicate(input=command_str, timeout=10)
            
            if proc.returncode != 0:
                logger.error(f"Configuration failed: {stderr}")
            else:
                logger.debug(f"Configuration output: {stdout}")
                
        except Exception as e:
            logger.error(f"Error configuring channel: {e}")


def channels_from_config(config: dict) -> List[ChannelSpec]:
    """
    Extract channel specifications from configuration
    
    Args:
        config: Configuration dictionary
        
    Returns:
        List of ChannelSpec objects
    """
    specs = []
    
    for channel_config in config.get('recorder', {}).get('channels', []):
        if not channel_config.get('enabled', True):
            continue
        
        spec = ChannelSpec(
            ssrc=channel_config['ssrc'],
            frequency_hz=channel_config['frequency_hz'],
            preset=channel_config.get('preset', 'iq'),
            sample_rate=channel_config.get('sample_rate', 16000),
            description=channel_config.get('description', '')
        )
        specs.append(spec)
    
    return specs

