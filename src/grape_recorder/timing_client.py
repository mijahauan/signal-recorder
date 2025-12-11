"""
Timing Client - Consumes timing data from time-manager

This module provides the client interface for grape-recorder (and other
applications) to consume timing data from the time-manager daemon.

The time-manager publishes timing results to /dev/shm/grape_timing in JSON
format. This client reads that file and provides a clean API for accessing
D_clock, station identification, and other timing metadata.

Usage:
    from grape_recorder.timing_client import TimingClient
    
    client = TimingClient()
    
    # Get current D_clock
    d_clock = client.get_d_clock()
    if d_clock is not None:
        corrected_time = time.time() - (d_clock / 1000.0)
    
    # Get station for a channel
    station = client.get_station("WWV 10 MHz")  # Returns "WWV" or "WWVH"
    
    # Check if time-manager is running and locked
    if client.is_locked():
        print("High-precision timing available")

Fallback Behavior:
    If time-manager is not running, methods return None or default values.
    grape-recorder should gracefully degrade to NTP-based timing.

Version: 1.0.0
"""

import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ClockStatus(str, Enum):
    """Clock synchronization status from time-manager."""
    ACQUIRING = "ACQUIRING"   # Initial startup, collecting data
    LOCKED = "LOCKED"         # Stable, high-confidence timing
    HOLDOVER = "HOLDOVER"     # Lost lock, using last known state
    UNLOCKED = "UNLOCKED"     # No timing available
    UNAVAILABLE = "UNAVAILABLE"  # time-manager not running


@dataclass
class ChannelTiming:
    """Timing information for a single channel."""
    channel_name: str
    station: str              # "WWV", "WWVH", "CHU", "UNKNOWN"
    confidence: str           # "high", "medium", "low"
    d_clock_raw_ms: Optional[float] = None
    propagation_delay_ms: Optional[float] = None
    propagation_mode: str = "UNKNOWN"
    snr_db: Optional[float] = None
    uncertainty_ms: float = 10.0


@dataclass
class TimingSnapshot:
    """
    Snapshot of timing state from time-manager.
    
    This represents a point-in-time view of the timing state,
    suitable for logging or decision-making.
    """
    timestamp: float
    d_clock_ms: float
    d_clock_uncertainty_ms: float
    clock_status: ClockStatus
    channels_active: int
    channels_locked: int
    age_seconds: float        # Time since time-manager updated this
    
    def is_fresh(self, max_age: float = 120.0) -> bool:
        """Check if snapshot is recent enough to be trusted."""
        return self.age_seconds < max_age


class TimingClient:
    """
    Client for consuming timing data from time-manager.
    
    This client reads timing data from the shared memory file published
    by time-manager. It provides a clean API for accessing D_clock,
    station identification, and other timing metadata.
    
    Thread Safety:
        This class is thread-safe. Multiple threads can read concurrently.
        File reads are atomic (JSON is loaded in one operation).
    
    Performance:
        Each method call reads the shared memory file. For high-frequency
        access, consider caching the result for a short period.
    """
    
    DEFAULT_SHM_PATH = "/dev/shm/grape_timing"
    
    def __init__(self, shm_path: Optional[str] = None):
        """
        Initialize timing client.
        
        Args:
            shm_path: Path to shared memory file (default: /dev/shm/grape_timing)
        """
        self.shm_path = Path(shm_path or self.DEFAULT_SHM_PATH)
        self._last_data: Optional[Dict] = None
        self._last_read_time: float = 0.0
        self._cache_ttl: float = 0.5  # Cache for 500ms to reduce I/O
        
        logger.debug(f"TimingClient initialized: {self.shm_path}")
    
    def _read_shm(self) -> Optional[Dict]:
        """
        Read and parse the shared memory file.
        
        Returns cached data if called within cache_ttl.
        """
        now = time.time()
        
        # Return cached data if fresh
        if self._last_data and (now - self._last_read_time) < self._cache_ttl:
            return self._last_data
        
        try:
            if not self.shm_path.exists():
                return None
            
            with open(self.shm_path, 'r') as f:
                data = json.load(f)
            
            self._last_data = data
            self._last_read_time = now
            return data
            
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in timing SHM: {e}")
            return None
        except Exception as e:
            logger.debug(f"Failed to read timing SHM: {e}")
            return None
    
    @property
    def available(self) -> bool:
        """Check if time-manager shared memory exists."""
        return self.shm_path.exists()
    
    def get_d_clock(self) -> Optional[float]:
        """
        Get the current D_clock value.
        
        D_clock is the system clock offset from UTC(NIST) in milliseconds:
            D_clock = T_system - T_UTC
        
        To get UTC from system time:
            utc = time.time() - (d_clock_ms / 1000.0)
        
        Returns:
            D_clock in milliseconds, or None if unavailable
        """
        data = self._read_shm()
        if data is None:
            return None
        
        status = data.get('clock_status', 'UNAVAILABLE')
        if status not in ('LOCKED', 'HOLDOVER'):
            return None
        
        return data.get('d_clock_ms')
    
    def get_d_clock_with_uncertainty(self) -> tuple[Optional[float], Optional[float]]:
        """
        Get D_clock with uncertainty bounds.
        
        Returns:
            Tuple of (d_clock_ms, uncertainty_ms), or (None, None) if unavailable
        """
        data = self._read_shm()
        if data is None:
            return None, None
        
        status = data.get('clock_status', 'UNAVAILABLE')
        if status not in ('LOCKED', 'HOLDOVER'):
            return None, None
        
        return (
            data.get('d_clock_ms'),
            data.get('d_clock_uncertainty_ms')
        )
    
    def get_clock_status(self) -> ClockStatus:
        """
        Get current clock synchronization status.
        
        Returns:
            ClockStatus enum value
        """
        data = self._read_shm()
        if data is None:
            return ClockStatus.UNAVAILABLE
        
        status_str = data.get('clock_status', 'UNAVAILABLE')
        try:
            return ClockStatus(status_str)
        except ValueError:
            return ClockStatus.UNAVAILABLE
    
    def is_locked(self) -> bool:
        """
        Check if time-manager has achieved lock.
        
        Returns:
            True if clock status is LOCKED
        """
        return self.get_clock_status() == ClockStatus.LOCKED
    
    def is_available(self) -> bool:
        """
        Check if timing data is available (locked or holdover).
        
        Returns:
            True if timing data can be used
        """
        status = self.get_clock_status()
        return status in (ClockStatus.LOCKED, ClockStatus.HOLDOVER)
    
    def get_station(self, channel_name: str) -> Optional[str]:
        """
        Get the identified station for a channel.
        
        For shared frequencies (2.5, 5, 10, 15 MHz), time-manager performs
        discrimination to determine whether WWV or WWVH is dominant.
        
        Args:
            channel_name: Channel name (e.g., "WWV 10 MHz")
            
        Returns:
            Station name ("WWV", "WWVH", "CHU") or None if not available
        """
        data = self._read_shm()
        if data is None:
            return None
        
        channels = data.get('channels', {})
        
        # Try exact match first
        if channel_name in channels:
            return channels[channel_name].get('station')
        
        # Try with underscores
        key = channel_name.replace(' ', '_')
        if key in channels:
            return channels[key].get('station')
        
        return None
    
    def get_channel_timing(self, channel_name: str) -> Optional[ChannelTiming]:
        """
        Get full timing information for a channel.
        
        Args:
            channel_name: Channel name
            
        Returns:
            ChannelTiming object or None if not available
        """
        data = self._read_shm()
        if data is None:
            return None
        
        channels = data.get('channels', {})
        
        # Try both formats
        ch_data = channels.get(channel_name) or channels.get(channel_name.replace(' ', '_'))
        if ch_data is None:
            return None
        
        return ChannelTiming(
            channel_name=ch_data.get('channel_name', channel_name),
            station=ch_data.get('station', 'UNKNOWN'),
            confidence=ch_data.get('confidence', 'low'),
            d_clock_raw_ms=ch_data.get('d_clock_raw_ms'),
            propagation_delay_ms=ch_data.get('propagation_delay_ms'),
            propagation_mode=ch_data.get('propagation_mode', 'UNKNOWN'),
            snr_db=ch_data.get('snr_db'),
            uncertainty_ms=ch_data.get('uncertainty_ms', 10.0)
        )
    
    def get_snapshot(self) -> TimingSnapshot:
        """
        Get a complete snapshot of timing state.
        
        Returns:
            TimingSnapshot with all timing information
        """
        data = self._read_shm()
        
        if data is None:
            return TimingSnapshot(
                timestamp=time.time(),
                d_clock_ms=0.0,
                d_clock_uncertainty_ms=999.0,
                clock_status=ClockStatus.UNAVAILABLE,
                channels_active=0,
                channels_locked=0,
                age_seconds=999.0
            )
        
        generated_at = data.get('generated_at', 0.0)
        age = time.time() - generated_at if generated_at > 0 else 999.0
        
        status_str = data.get('clock_status', 'UNAVAILABLE')
        try:
            status = ClockStatus(status_str)
        except ValueError:
            status = ClockStatus.UNAVAILABLE
        
        return TimingSnapshot(
            timestamp=data.get('timestamp', time.time()),
            d_clock_ms=data.get('d_clock_ms', 0.0),
            d_clock_uncertainty_ms=data.get('d_clock_uncertainty_ms', 999.0),
            clock_status=status,
            channels_active=data.get('channels_active', 0),
            channels_locked=data.get('channels_locked', 0),
            age_seconds=age
        )
    
    def get_utc_time(self) -> float:
        """
        Get current UTC time, corrected using D_clock if available.
        
        This is the recommended way to get UTC time. If time-manager
        is locked, the returned time has ~1ms accuracy. Otherwise,
        falls back to system time (NTP accuracy).
        
        Returns:
            UTC timestamp
        """
        d_clock = self.get_d_clock()
        now = time.time()
        
        if d_clock is not None:
            return now - (d_clock / 1000.0)
        
        # Fallback to system time
        return now
    
    def wait_for_lock(self, timeout: float = 300.0) -> bool:
        """
        Wait for time-manager to achieve lock.
        
        Useful at startup to ensure timing is available before proceeding.
        
        Args:
            timeout: Maximum seconds to wait
            
        Returns:
            True if lock achieved, False if timeout
        """
        start = time.time()
        
        while (time.time() - start) < timeout:
            if self.is_locked():
                return True
            time.sleep(1.0)
        
        return False


# Singleton instance for convenience
_default_client: Optional[TimingClient] = None


def get_timing_client() -> TimingClient:
    """Get the default TimingClient instance."""
    global _default_client
    if _default_client is None:
        _default_client = TimingClient()
    return _default_client


def get_d_clock() -> Optional[float]:
    """Convenience function to get D_clock from default client."""
    return get_timing_client().get_d_clock()


def get_station(channel_name: str) -> Optional[str]:
    """Convenience function to get station from default client."""
    return get_timing_client().get_station(channel_name)


def get_utc_time() -> float:
    """Convenience function to get corrected UTC time."""
    return get_timing_client().get_utc_time()


def get_time_manager_status() -> Dict[str, Any]:
    """
    Get comprehensive time-manager status for monitoring.
    
    Returns a dict suitable for status endpoints and logging:
    - running: bool - whether time-manager SHM exists
    - healthy: bool - whether data is fresh and usable
    - status: str - clock status
    - d_clock_ms: float or None
    - age_seconds: float - how old the data is
    - channels_active: int
    """
    client = get_timing_client()
    
    result = {
        'running': client.available,
        'healthy': False,
        'status': 'UNAVAILABLE',
        'd_clock_ms': None,
        'uncertainty_ms': None,
        'age_seconds': None,
        'channels_active': 0,
        'channels_locked': 0,
    }
    
    if not client.available:
        return result
    
    snapshot = client.get_snapshot()
    if snapshot is None:
        return result
    
    result['status'] = snapshot.clock_status.value
    result['d_clock_ms'] = snapshot.d_clock_ms
    result['uncertainty_ms'] = snapshot.d_clock_uncertainty_ms
    result['age_seconds'] = snapshot.age_seconds
    result['channels_active'] = snapshot.channels_active
    result['channels_locked'] = snapshot.channels_locked
    
    # Consider healthy if data is fresh (< 2 minutes) and status is good
    result['healthy'] = (
        snapshot.age_seconds < 120.0 and
        snapshot.clock_status in (ClockStatus.LOCKED, ClockStatus.HOLDOVER, ClockStatus.ACQUIRING)
    )
    
    return result
