"""
Radiod Health Monitoring and Channel Recovery

Detects when radiod restarts or channels disappear and automatically
recreates missing channels to ensure continuous data collection.
"""

import logging
import time
from typing import Optional, Dict
from datetime import datetime
from ka9q import discover_channels

logger = logging.getLogger(__name__)


class RadiodHealthChecker:
    """
    Monitor radiod liveness and verify channel existence.
    
    Provides two levels of health checking:
    1. Is radiod process alive and broadcasting status?
    2. Does a specific channel (SSRC) exist in radiod?
    """
    
    def __init__(self, status_address: str, status_port: int = 5006):
        """
        Initialize health checker.
        
        Args:
            status_address: Multicast address for radiod status (e.g., "239.192.152.141")
            status_port: UDP port for radiod status packets (default 5006)
        """
        self.status_address = status_address
        self.status_port = status_port
        self.logger = logging.getLogger(f"{__name__}.{status_address}")
    
    def is_radiod_alive(self, timeout_sec: float = 5.0) -> bool:
        """
        Check if radiod is responsive by attempting to discover channels.
        
        Args:
            timeout_sec: How long to wait for discovery
            
        Returns:
            True if radiod is responding, False otherwise
        """
        try:
            # Use ka9q discover_channels - works with mDNS hostnames and multicast addresses
            channels = discover_channels(self.status_address)
            
            # If we got any response (even empty channel list), radiod is alive
            self.logger.debug(f"Radiod alive - discovered {len(channels)} channels")
            return True
            
        except Exception as e:
            self.logger.warning(f"Radiod discovery failed: {e}")
            return False
    
    def verify_channel_exists(self, ssrc: int, timeout_sec: float = 5.0) -> bool:
        """
        Verify a specific channel exists in radiod by discovering channels.
        
        Args:
            ssrc: RTP SSRC identifier for the channel
            timeout_sec: Timeout for discovery
            
        Returns:
            True if channel exists, False otherwise
        """
        try:
            # Use ka9q discover_channels to get all channels
            channels = discover_channels(self.status_address)
            
            # Check if our SSRC is in the discovered channels
            if ssrc in channels:
                self.logger.debug(f"Channel {ssrc:x} found in radiod")
                return True
            else:
                self.logger.warning(f"Channel {ssrc:x} not found in radiod (have {len(channels)} channels)")
                return False
            
        except Exception as e:
            self.logger.error(f"Channel verification failed: {e}")
            return False
    
    def get_status(self) -> Dict[str, any]:
        """
        Get comprehensive health status.
        
        Returns:
            Dictionary with radiod_alive, check_time, and error fields
        """
        check_time = time.time()
        radiod_alive = self.is_radiod_alive()
        
        return {
            'radiod_alive': radiod_alive,
            'status_address': self.status_address,
            'check_time': check_time,
            'check_time_str': datetime.fromtimestamp(check_time).isoformat(),
            'error': None if radiod_alive else 'No status packets received'
        }
