"""
RadioD Stream Manager - Clean API for managing radiod RTP streams

This module provides a stable, high-level API for requesting and managing
RTP streams from radiod. It handles all the complexity of:
- Creating/configuring channels in radiod
- Discovering multicast addresses and ports
- Managing stream lifecycle

Usage:
    manager = RadiodStreamManager('bee1-hf-status.local')
    
    # Request a stream
    stream = manager.request_stream(
        ssrc=5000001,
        frequency=5000000,
        preset='am',
        sample_rate=12000,
        agc=1,
        gain=50
    )
    
    # Use the stream info
    print(f"Stream available at {stream.multicast_address}:{stream.multicast_port}")
    
    # Stop the stream when done
    manager.stop_stream(5000001)
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict
from .radiod_control import RadiodControl
from .control_discovery import discover_channels_via_control, ChannelInfo

logger = logging.getLogger(__name__)


@dataclass
class StreamInfo:
    """Information about an active RTP stream from radiod"""
    ssrc: int
    frequency: float
    preset: str
    sample_rate: int
    multicast_address: str
    multicast_port: int
    snr: float = 0.0
    
    def __str__(self):
        return (f"Stream(SSRC={self.ssrc}, freq={self.frequency/1e6:.3f}MHz, "
                f"preset={self.preset}, rate={self.sample_rate}Hz, "
                f"addr={self.multicast_address}:{self.multicast_port})")


class RadiodStreamManager:
    """
    High-level manager for radiod RTP streams
    
    This class provides a simple, stable API for requesting RTP streams
    from radiod with any combination of parameters.
    """
    
    def __init__(self, status_address: str):
        """
        Initialize the stream manager
        
        Args:
            status_address: mDNS name or IP of radiod status multicast
                          (e.g., 'bee1-hf-status.local' or '239.192.152.141')
        """
        self.status_address = status_address
        self.control = RadiodControl(status_address)
        self.active_streams: Dict[int, StreamInfo] = {}
        
        logger.info(f"RadiodStreamManager initialized for {status_address}")
    
    def request_stream(
        self,
        ssrc: int,
        frequency: float,
        preset: str = 'am',
        sample_rate: int = 12000,
        agc: int = 1,
        gain: float = 50.0,
        discovery_timeout: float = 5.0,
        discovery_retries: int = 3
    ) -> StreamInfo:
        """
        Request a new RTP stream from radiod
        
        This method:
        1. Sends a create/configure command to radiod
        2. Waits for the stream to appear
        3. Discovers its multicast address and port
        4. Returns StreamInfo ready for use
        
        Args:
            ssrc: Unique SSRC for this stream
            frequency: Center frequency in Hz (e.g., 5000000 for 5 MHz)
            preset: Demodulation mode ('am', 'fm', 'usb', 'lsb', 'iq', etc.)
            sample_rate: Audio sample rate in Hz (e.g., 12000)
            agc: AGC enable (1=on, 0=off)
            gain: Gain in dB (used when AGC is off)
            discovery_timeout: Seconds to wait for stream to appear
            discovery_retries: Number of times to retry discovery
            
        Returns:
            StreamInfo object with multicast address, port, and other details
            
        Raises:
            RuntimeError: If stream creation or discovery fails
        """
        logger.info(f"Requesting stream: SSRC={ssrc}, freq={frequency/1e6:.3f}MHz, "
                   f"preset={preset}, rate={sample_rate}Hz")
        
        # Check if stream already exists
        if ssrc in self.active_streams:
            logger.warning(f"Stream {ssrc} already exists, returning existing info")
            return self.active_streams[ssrc]
        
        # Create and configure the channel in radiod
        try:
            self.control.create_and_configure_channel(
                ssrc=ssrc,
                frequency_hz=frequency,
                preset=preset,
                sample_rate=sample_rate,
                agc_enable=agc,
                gain=gain
            )
            logger.info(f"Sent create/configure command for SSRC {ssrc}")
        except Exception as e:
            logger.error(f"Failed to create channel {ssrc}: {e}")
            raise RuntimeError(f"Failed to create channel: {e}")
        
        # Wait a moment for radiod to create the stream
        time.sleep(0.5)
        
        # Discover the stream's multicast address and port
        stream_info = None
        for attempt in range(discovery_retries):
            try:
                logger.debug(f"Discovery attempt {attempt + 1}/{discovery_retries} for SSRC {ssrc}")
                channel = self._discover_channel(ssrc, timeout=discovery_timeout)
                
                if channel:
                    stream_info = StreamInfo(
                        ssrc=channel.ssrc,
                        frequency=channel.frequency,
                        preset=channel.preset,
                        sample_rate=channel.sample_rate,
                        multicast_address=channel.multicast_address,
                        multicast_port=channel.port,
                        snr=channel.snr
                    )
                    break
                    
            except Exception as e:
                logger.warning(f"Discovery attempt {attempt + 1} failed: {e}")
                if attempt < discovery_retries - 1:
                    time.sleep(1.0)
        
        if not stream_info:
            raise RuntimeError(
                f"Failed to discover stream {ssrc} after {discovery_retries} attempts. "
                "Stream may not have been created by radiod."
            )
        
        # Cache the stream info
        self.active_streams[ssrc] = stream_info
        logger.info(f"Stream discovered: {stream_info}")
        
        return stream_info
    
    def get_stream(self, ssrc: int) -> Optional[StreamInfo]:
        """
        Get information about an active stream
        
        Args:
            ssrc: SSRC of the stream
            
        Returns:
            StreamInfo if stream exists, None otherwise
        """
        return self.active_streams.get(ssrc)
    
    def stop_stream(self, ssrc: int) -> bool:
        """
        Stop a stream (remove from radiod)
        
        Args:
            ssrc: SSRC of the stream to stop
            
        Returns:
            True if stream was stopped, False if it didn't exist
        """
        if ssrc not in self.active_streams:
            logger.warning(f"Cannot stop stream {ssrc}: not found")
            return False
        
        try:
            # Send command to radiod to remove the channel
            # (radiod automatically removes channels when they're not used)
            logger.info(f"Stopping stream {ssrc}")
            del self.active_streams[ssrc]
            return True
        except Exception as e:
            logger.error(f"Failed to stop stream {ssrc}: {e}")
            return False
    
    def list_streams(self) -> Dict[int, StreamInfo]:
        """
        List all active streams managed by this instance
        
        Returns:
            Dictionary mapping SSRC to StreamInfo
        """
        return self.active_streams.copy()
    
    def discover_all_streams(self) -> Dict[int, StreamInfo]:
        """
        Discover all active streams from radiod (not just managed ones)
        
        Returns:
            Dictionary mapping SSRC to StreamInfo for all streams
        """
        try:
            channels = discover_channels_via_control(self.status_address, timeout=5.0)
            
            streams = {}
            for ssrc, channel in channels.items():
                streams[ssrc] = StreamInfo(
                    ssrc=channel.ssrc,
                    frequency=channel.frequency,
                    preset=channel.preset,
                    sample_rate=channel.sample_rate,
                    multicast_address=channel.multicast_address,
                    multicast_port=channel.port,
                    snr=channel.snr
                )
            
            return streams
        except Exception as e:
            logger.error(f"Failed to discover streams: {e}")
            return {}
    
    def _discover_channel(self, ssrc: int, timeout: float = 5.0) -> Optional[ChannelInfo]:
        """
        Discover a specific channel by SSRC
        
        Args:
            ssrc: SSRC to look for
            timeout: Discovery timeout in seconds
            
        Returns:
            ChannelInfo if found, None otherwise
        """
        channels = discover_channels_via_control(self.status_address, timeout=timeout)
        return channels.get(ssrc)
    
    def close(self):
        """Clean up resources"""
        logger.info("RadiodStreamManager closing")
        self.active_streams.clear()
