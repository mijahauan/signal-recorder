#!/usr/bin/env python3
"""
Stream Specification - Content-based stream identity

A stream is uniquely identified by its content specification, not by SSRC.
Two requests with identical StreamSpec share the same underlying stream.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StreamSpec:
    """
    Defines what makes a unique stream (content specification).
    
    This is what applications care about - the SSRC is just an internal
    index that radiod uses to track streams.
    
    Two StreamSpecs are equal if all parameters match (within tolerance
    for frequency). This enables automatic stream sharing.
    
    Attributes:
        frequency_hz: Center frequency in Hz
        preset: Demodulation mode ("iq", "usb", "lsb", "am", "fm", "cw")
        sample_rate: Output sample rate in Hz
        agc: Automatic gain control (True=on, False=off)
        gain: Manual gain in dB (used when agc=False)
    """
    frequency_hz: float
    preset: str
    sample_rate: int
    agc: bool = False
    gain: float = 0.0
    
    def __hash__(self):
        # Round frequency to nearest Hz for hashing
        # This ensures near-identical frequencies hash the same
        return hash((
            round(self.frequency_hz),
            self.preset.lower(),
            self.sample_rate,
            self.agc,
            round(self.gain, 1)
        ))
    
    def __eq__(self, other):
        if not isinstance(other, StreamSpec):
            return False
        # Frequency tolerance of 1 Hz
        freq_match = abs(self.frequency_hz - other.frequency_hz) < 1.0
        return (
            freq_match and
            self.preset.lower() == other.preset.lower() and
            self.sample_rate == other.sample_rate and
            self.agc == other.agc and
            abs(self.gain - other.gain) < 0.1
        )
    
    def __str__(self):
        agc_str = "AGC" if self.agc else f"{self.gain:.0f}dB"
        return f"{self.frequency_hz/1e6:.4f}MHz/{self.preset}/{self.sample_rate}Hz/{agc_str}"
    
    def __repr__(self):
        return (f"StreamSpec(frequency_hz={self.frequency_hz}, preset='{self.preset}', "
                f"sample_rate={self.sample_rate}, agc={self.agc}, gain={self.gain})")
    
    @property
    def frequency_mhz(self) -> float:
        """Frequency in MHz for convenience"""
        return self.frequency_hz / 1e6
    
    @property
    def frequency_khz(self) -> float:
        """Frequency in kHz for convenience"""
        return self.frequency_hz / 1e3
    
    def matches(self, other: 'StreamSpec', frequency_tolerance_hz: float = 1.0) -> bool:
        """
        Check if another StreamSpec is compatible (could share stream).
        
        Args:
            other: StreamSpec to compare
            frequency_tolerance_hz: How close frequencies must be
            
        Returns:
            True if specs are compatible
        """
        freq_match = abs(self.frequency_hz - other.frequency_hz) < frequency_tolerance_hz
        return (
            freq_match and
            self.preset.lower() == other.preset.lower() and
            self.sample_rate == other.sample_rate and
            self.agc == other.agc and
            abs(self.gain - other.gain) < 0.1
        )


@dataclass
class StreamRequest:
    """
    A request for a stream, including optional destination preferences.
    
    This wraps StreamSpec with additional parameters that don't affect
    stream identity but influence how the stream is set up.
    
    Attributes:
        spec: The content specification (what makes the stream unique)
        destination: Preferred multicast destination (address or address:port)
        description: Human-readable description for logging
    """
    spec: StreamSpec
    destination: Optional[str] = None
    description: str = ""
    
    @classmethod
    def create(
        cls,
        frequency_hz: float,
        preset: str = "iq",
        sample_rate: int = 16000,
        agc: bool = False,
        gain: float = 0.0,
        destination: Optional[str] = None,
        description: str = ""
    ) -> 'StreamRequest':
        """
        Convenience factory to create a StreamRequest.
        
        Args:
            frequency_hz: Center frequency in Hz
            preset: Demodulation mode
            sample_rate: Output sample rate in Hz
            agc: Enable AGC
            gain: Manual gain in dB
            destination: Preferred multicast destination
            description: Human-readable description
            
        Returns:
            StreamRequest instance
        """
        spec = StreamSpec(
            frequency_hz=frequency_hz,
            preset=preset,
            sample_rate=sample_rate,
            agc=agc,
            gain=gain
        )
        return cls(spec=spec, destination=destination, description=description)
    
    def __str__(self):
        dest = f" → {self.destination}" if self.destination else ""
        desc = f" ({self.description})" if self.description else ""
        return f"{self.spec}{dest}{desc}"
