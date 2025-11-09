"""
Radiod Health Monitoring and Channel Recovery

Detects when radiod restarts or channels disappear and automatically
recreates missing channels to ensure continuous data collection.
"""

import socket
import subprocess
import logging
import time
from typing import Optional, Dict
from datetime import datetime

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
        Check if radiod is responsive by listening for status multicast packets.
        
        Args:
            timeout_sec: How long to wait for a status packet
            
        Returns:
            True if radiod is broadcasting status, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout_sec)
            
            # Bind to status port
            sock.bind(('', self.status_port))
            
            # Join multicast group
            mreq = socket.inet_aton(self.status_address) + socket.inet_aton('0.0.0.0')
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            # Try to receive one packet
            data, addr = sock.recv(1024)
            sock.close()
            
            self.logger.debug(f"Radiod alive - received status packet from {addr}")
            return True
            
        except socket.timeout:
            self.logger.warning(f"Radiod timeout - no status packets received in {timeout_sec}s")
            return False
        except Exception as e:
            self.logger.error(f"Radiod health check failed: {e}")
            return False
    
    def verify_channel_exists(self, ssrc: int, timeout_sec: float = 5.0) -> bool:
        """
        Verify a specific channel exists in radiod using the control utility.
        
        Args:
            ssrc: RTP SSRC identifier for the channel
            timeout_sec: Timeout for control command
            
        Returns:
            True if channel exists, False otherwise
        """
        try:
            result = subprocess.run(
                ['control', '-v', self.status_address],
                capture_output=True,
                text=True,
                timeout=timeout_sec
            )
            
            if result.returncode != 0:
                self.logger.error(f"Control command failed: {result.stderr}")
                return False
            
            # Parse output for SSRC
            # control -v output format: lines like "SSRC 2500000: WWV 2.5 MHz"
            ssrc_str = str(ssrc)
            for line in result.stdout.split('\n'):
                if ssrc_str in line:
                    self.logger.debug(f"Channel {ssrc} found in radiod")
                    return True
            
            self.logger.warning(f"Channel {ssrc} not found in radiod output")
            return False
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Control command timed out after {timeout_sec}s")
            return False
        except FileNotFoundError:
            self.logger.error("'control' utility not found - is ka9q-radio installed?")
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
