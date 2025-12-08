#!/usr/bin/env python3
"""
WWV/WWVH BCD Time Code Encoder

Generates the IRIG-H time code transmitted by WWV and WWVH at 100 Hz.
Both stations transmit the IDENTICAL BCD pattern encoding UTC time.

IRIG-H Format (used by WWV/WWVH):
- Frame: 60 seconds (one complete time code per minute)
- Each second: One pulse at start
- Pulse widths:
  * Binary 0: 200ms (20% of second)
  * Binary 1: 500ms (50% of second)
  * Position marker: 800ms (80% of second)
- Modulation: 100 Hz subcarrier, double-sideband AM

Time Code Fields (seconds within minute):
  0: Frame marker (800ms)
  1-8: Minute (BCD)
  9: Position marker
  10-17: Hour (BCD)
  19: Position marker
  20-29: Day of year (BCD)
  29: Position marker
  30-38: Year (last 2 digits, BCD)
  39: Position marker
  40-50: Unused/control bits
  49: Position marker
  51-58: Unused
  59: Position marker

Position markers at: 0, 9, 19, 29, 39, 49, 59

Reference: NIST Special Publication 432, "NIST Time and Frequency Services"
"""

import numpy as np
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class WWVBCDEncoder:
    """Encoder for WWV/WWVH IRIG-H time code"""
    
    # Position markers (800ms pulses)
    POSITION_MARKERS = [0, 9, 19, 29, 39, 49, 59]
    
    def __init__(self, sample_rate: int = 20000):
        """
        Initialize BCD encoder
        
        Args:
            sample_rate: Sample rate in Hz (20000 default, 16000 for legacy)
        """
        self.sample_rate = sample_rate
        self.samples_per_second = sample_rate
        
    def encode_minute(self, timestamp: float, envelope_only: bool = False) -> np.ndarray:
        """
        Generate 60-second BCD template for given UTC timestamp
        
        Args:
            timestamp: UTC timestamp at minute boundary
            envelope_only: If True, return just the envelope (for correlation with
                          demodulated signals). If False, return with 100 Hz carrier.
            
        Returns:
            60-second BCD waveform as numpy array
        """
        dt = datetime.utcfromtimestamp(timestamp)
        
        # Extract time components
        minute = dt.minute
        hour = dt.hour
        day_of_year = dt.timetuple().tm_yday
        year = dt.year % 100  # Last 2 digits
        
        # Generate BCD bit pattern for entire minute
        bcd_pattern = self._generate_bcd_pattern(minute, hour, day_of_year, year)
        
        # Convert to waveform with proper pulse widths
        waveform = self._pattern_to_waveform(bcd_pattern)
        
        if envelope_only:
            # Return envelope only (for correlation with demodulated signal)
            return waveform
        
        # Modulate onto 100 Hz subcarrier
        modulated = self._apply_100hz_modulation(waveform)
        
        return modulated
    
    def _generate_bcd_pattern(
        self,
        minute: int,
        hour: int,
        day_of_year: int,
        year: int
    ) -> list:
        """
        Generate 60-element BCD pattern (one element per second)
        
        Based on Phil Karn's wwvsim.c maketimecode() function.
        BCD encoding is LITTLE-ENDIAN (LSB first), unlike WWVB which uses big-endian.
        
        Returns:
            List of 60 elements, each 0 or 1 (position markers encoded separately)
        """
        code = [0] * 60
        
        # Helper function: encode BCD digit in little-endian format (lsb first)
        def encode_bcd_digit(value, start_index):
            for i in range(4):
                code[start_index + i] = value & 1
                value >>= 1
        
        # Second 2: DST status at 00:00 UTC (not implemented - set to 0)
        code[2] = 0
        
        # Second 3: Leap second pending
        code[3] = 0  # Would be set if leap second pending
        
        # Seconds 4-7, 51-54: Year (last 2 digits, BCD little-endian)
        encode_bcd_digit(year % 10, 4)       # Ones digit at seconds 4-7
        encode_bcd_digit((year // 10) % 10, 51)  # Tens digit at seconds 51-54
        
        # Seconds 10-14, 15-18: Minute (BCD little-endian)
        encode_bcd_digit(minute % 10, 10)    # Ones digit at seconds 10-13
        encode_bcd_digit(minute // 10, 15)   # Tens digit at seconds 15-17 (bit 18 unused)
        
        # Seconds 20-24, 25-28: Hour (BCD little-endian, 24-hour format)
        encode_bcd_digit(hour % 10, 20)      # Ones digit at seconds 20-23
        encode_bcd_digit(hour // 10, 25)     # Tens digit at seconds 25-26 (bits 27-28 unused)
        
        # Seconds 30-34, 35-38, 40-43: Day of year (BCD little-endian)
        # Need 9 bits for days 1-366 (actually 10 bits to encode in BCD)
        encode_bcd_digit(day_of_year % 10, 30)         # Ones digit
        encode_bcd_digit((day_of_year // 10) % 10, 35) # Tens digit
        encode_bcd_digit(day_of_year // 100, 40)       # Hundreds digit (bits 42-43 unused)
        
        # Second 50: UT1 sign (not implemented - set to 0 for positive)
        code[50] = 0
        
        # Second 55: DST status at 24:00 UTC (not implemented - set to 0)
        code[55] = 0
        
        # Seconds 56-59: UT1 magnitude (not implemented - set to 0)
        # Note: bits at 59 would be marker anyway
        
        # All other bits default to 0 (already initialized)
        
        return code
    
    def _to_bcd_8bit(self, value: int) -> list:
        """Convert value (0-99) to 8-bit BCD [MSB...LSB]"""
        tens = (value // 10) & 0x0F
        ones = value % 10
        
        bcd = []
        for i in range(4):
            bcd.append((tens >> (3-i)) & 1)
        for i in range(4):
            bcd.append((ones >> (3-i)) & 1)
        return bcd
    
    def _to_bcd_12bit(self, value: int) -> list:
        """Convert value (0-999) to 12-bit BCD [MSB...LSB]"""
        hundreds = (value // 100) & 0x0F
        tens = ((value % 100) // 10) & 0x0F
        ones = value % 10
        
        bcd = []
        for i in range(4):
            bcd.append((hundreds >> (3-i)) & 1)
        for i in range(4):
            bcd.append((tens >> (3-i)) & 1)
        for i in range(4):
            bcd.append((ones >> (3-i)) & 1)
        return bcd
    
    def _pattern_to_waveform(self, pattern: list) -> np.ndarray:
        """
        Convert BCD pattern to envelope waveform with proper pulse widths
        
        Based on Phil Karn's wwvsim.c makeminute() function.
        Each second has:
        - HIGH amplitude pulse (marker/one/zero duration)
        - LOW amplitude for remainder of second
        
        Position markers (seconds 0, 9, 19, 29, 39, 49, 59): 800ms HIGH
        
        Args:
            pattern: 60-element list of 0 or 1 bits
            
        Returns:
            60-second envelope waveform (before 100 Hz modulation)
        """
        # Amplitudes from wwvsim.c (NIST 250-67)
        marker_high_amp = 10.0 ** (-6.0 / 20.0)  # -6 dB
        marker_low_amp = marker_high_amp / 10     # -20 dB (observed, not -10.4 dB as spec says)
        
        # Position marker seconds
        position_markers = [0, 9, 19, 29, 39, 49, 59]
        
        waveform = np.zeros(60 * self.samples_per_second, dtype=np.float32)
        
        for second in range(1, 60):  # Skip second 0 (no BCD subcarrier during minute beep)
            start_idx = second * self.samples_per_second
            end_idx = (second + 1) * self.samples_per_second
            
            if second in position_markers:
                # 800ms HIGH, 200ms LOW
                high_length = int(0.8 * self.samples_per_second)
                waveform[start_idx:start_idx + high_length] = marker_high_amp
                waveform[start_idx + high_length:end_idx] = marker_low_amp
            elif pattern[second]:
                # Binary 1: 500ms HIGH, 500ms LOW
                high_length = int(0.5 * self.samples_per_second)
                waveform[start_idx:start_idx + high_length] = marker_high_amp
                waveform[start_idx + high_length:end_idx] = marker_low_amp
            else:
                # Binary 0: 200ms HIGH, 800ms LOW
                high_length = int(0.2 * self.samples_per_second)
                waveform[start_idx:start_idx + high_length] = marker_high_amp
                waveform[start_idx + high_length:end_idx] = marker_low_amp
        
        return waveform
    
    def _apply_100hz_modulation(self, envelope: np.ndarray) -> np.ndarray:
        """
        Apply 100 Hz subcarrier modulation
        
        Args:
            envelope: Pulse envelope waveform
            
        Returns:
            Modulated signal (envelope × 100 Hz sine wave)
        """
        t = np.arange(len(envelope)) / self.sample_rate
        carrier_100hz = np.sin(2 * np.pi * 100 * t)
        modulated = envelope * carrier_100hz
        
        return modulated


def test_encoder():
    """Test BCD encoder with a known timestamp"""
    encoder = WWVBCDEncoder(sample_rate=16000)
    
    # Test with a known time: 2025-11-19 14:30:00 UTC
    test_time = datetime(2025, 11, 19, 14, 30, 0).timestamp()
    
    template = encoder.encode_minute(test_time)
    
    print(f"Generated BCD template:")
    print(f"  Length: {len(template)} samples ({len(template)/16000:.1f} seconds)")
    print(f"  Min/Max: {template.min():.3f} / {template.max():.3f}")
    print(f"  RMS: {np.sqrt(np.mean(template**2)):.3f}")
    
    # Verify structure by checking position markers
    dt = datetime.utcfromtimestamp(test_time)
    print(f"\nEncoded time: {dt.isoformat()} UTC")
    print(f"  Minute: {dt.minute:02d}")
    print(f"  Hour: {dt.hour:02d}")
    print(f"  Day of year: {dt.timetuple().tm_yday:03d}")
    print(f"  Year: {dt.year % 100:02d}")


if __name__ == '__main__':
    test_encoder()
