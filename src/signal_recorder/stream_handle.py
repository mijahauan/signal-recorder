#!/usr/bin/env python3
"""
Stream Handle - Opaque handle to a radiod stream

Applications receive a StreamHandle when they subscribe to a stream.
The handle provides access to the stream without exposing internal
details like SSRC.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone

from .stream_spec import StreamSpec

if TYPE_CHECKING:
    from .stream_manager import StreamManager

logger = logging.getLogger(__name__)


@dataclass
class StreamHandle:
    """
    Opaque handle to a radiod stream.
    
    This is what applications receive when they subscribe to a stream.
    It provides everything needed to receive and process the stream
    without exposing implementation details like SSRC.
    
    Attributes:
        spec: The stream specification (what you asked for)
        multicast_address: Where to receive RTP packets
        port: RTP port number
        created_at: When this handle was created
        
    The SSRC is available via _ssrc if absolutely needed (e.g., for
    debugging), but applications should not depend on it.
    """
    spec: StreamSpec
    multicast_address: str
    port: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Internal - hidden from normal use
    _ssrc: int = field(default=0, repr=False)
    _manager: Optional['StreamManager'] = field(default=None, repr=False)
    _ref_count: int = field(default=1, repr=False)
    
    # === Public Properties (what apps care about) ===
    
    @property
    def frequency_hz(self) -> float:
        """Stream frequency in Hz"""
        return self.spec.frequency_hz
    
    @property
    def frequency_mhz(self) -> float:
        """Stream frequency in MHz"""
        return self.spec.frequency_hz / 1e6
    
    @property
    def preset(self) -> str:
        """Demodulation preset (iq, usb, am, etc.)"""
        return self.spec.preset
    
    @property
    def sample_rate(self) -> int:
        """Output sample rate in Hz"""
        return self.spec.sample_rate
    
    @property
    def agc(self) -> bool:
        """Whether AGC is enabled"""
        return self.spec.agc
    
    @property
    def gain(self) -> float:
        """Manual gain in dB"""
        return self.spec.gain
    
    @property
    def rtp_address(self) -> str:
        """Full RTP address as 'host:port'"""
        return f"{self.multicast_address}:{self.port}"
    
    # === Stream Information ===
    
    def __str__(self):
        return (f"Stream({self.spec.frequency_hz/1e6:.4f}MHz, {self.spec.preset}, "
                f"{self.spec.sample_rate}Hz) → {self.multicast_address}:{self.port}")
    
    def __repr__(self):
        return (f"StreamHandle(spec={self.spec!r}, "
                f"multicast_address='{self.multicast_address}', port={self.port})")
    
    def info(self) -> dict:
        """
        Get stream information as a dictionary.
        
        Returns:
            Dictionary with stream details (excludes internal fields)
        """
        return {
            'frequency_hz': self.spec.frequency_hz,
            'frequency_mhz': self.spec.frequency_hz / 1e6,
            'preset': self.spec.preset,
            'sample_rate': self.spec.sample_rate,
            'agc': self.spec.agc,
            'gain': self.spec.gain,
            'multicast_address': self.multicast_address,
            'port': self.port,
            'created_at': self.created_at.isoformat(),
        }
    
    # === Lifecycle ===
    
    def release(self):
        """
        Release this handle to the stream.
        
        When all handles to a stream are released, the stream may be
        removed from radiod (depending on manager policy).
        """
        if self._manager:
            self._manager._release_handle(self)
        else:
            logger.warning(f"StreamHandle.release() called but no manager: {self}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - releases the handle"""
        self.release()
        return False
    
    # === Internal (for advanced use / debugging) ===
    
    @property
    def ssrc(self) -> int:
        """
        Internal SSRC (for debugging only).
        
        Applications should not depend on this value.
        """
        return self._ssrc


@dataclass
class StreamInfo:
    """
    Information about an existing stream (from discovery).
    
    Similar to StreamHandle but read-only and doesn't imply ownership.
    """
    spec: StreamSpec
    multicast_address: str
    port: int
    snr: float = 0.0
    
    @classmethod
    def from_channel_info(cls, channel_info) -> 'StreamInfo':
        """
        Create StreamInfo from ka9q ChannelInfo.
        
        Args:
            channel_info: ka9q.ChannelInfo instance
            
        Returns:
            StreamInfo instance
        """
        spec = StreamSpec(
            frequency_hz=channel_info.frequency,
            preset=channel_info.preset,
            sample_rate=channel_info.sample_rate,
            agc=False,  # Not available from discovery
            gain=0.0    # Not available from discovery
        )
        return cls(
            spec=spec,
            multicast_address=channel_info.multicast_address,
            port=channel_info.port,
            snr=channel_info.snr
        )
    
    def __str__(self):
        return (f"{self.spec.frequency_hz/1e6:.4f}MHz/{self.spec.preset}/"
                f"{self.spec.sample_rate}Hz → {self.multicast_address}:{self.port}")
