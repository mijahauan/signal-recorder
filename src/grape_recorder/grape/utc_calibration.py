"""
UTC Calibration from Tone Detection

This module provides precise RTP-to-UTC calibration using converged
tone detection from Phase 2 analytics.

Strategy:
    1. Phase 1 starts with NTP-calibrated RTP offset (~1-10ms accuracy)
    2. Phase 2 Kalman filter converges on tone timing (Grade A)
    3. This module computes precise RTP-to-UTC offset from tone detection
    4. Calibration stored in shared file for all services to use

The calibration corrects for:
    - Initial NTP offset error
    - Any system clock drift since startup

Usage:
    # Phase 2 (after Kalman convergence):
    calibrator = UTCCalibrator(data_root, receiver_grid)
    calibrator.apply_calibration(
        tone_rtp_timestamp=12345678,
        tone_utc_minute=1765300500,  # Unix timestamp of UTC minute
        station='WWV',
        confidence=0.95
    )
    
    # Phase 1 or any service:
    calibration = UTCCalibrator.load_calibration(data_root)
    if calibration and calibration['confidence'] > 0.9:
        precise_utc = rtp_timestamp / sample_rate + calibration['rtp_to_utc_offset']
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Propagation delays from transmitters (approximate, in seconds)
# These are calculated from great-circle distance at speed of light
STATION_COORDS = {
    'WWV': (40.6781, -105.0469),   # Fort Collins, CO
    'WWVH': (21.9886, -159.7642),  # Kauai, HI
    'CHU': (45.2950, -75.7500),    # Ottawa, Canada
}


def calculate_propagation_delay(receiver_grid: str, station: str) -> float:
    """
    Calculate propagation delay from station to receiver.
    
    Args:
        receiver_grid: Maidenhead grid square (e.g., 'DM79')
        station: Station name ('WWV', 'WWVH', 'CHU')
        
    Returns:
        Propagation delay in seconds
    """
    from .transmission_time_solver import grid_to_latlon
    
    if station not in STATION_COORDS:
        logger.warning(f"Unknown station {station}, assuming 10ms delay")
        return 0.010
    
    try:
        rx_lat, rx_lon = grid_to_latlon(receiver_grid)
        tx_lat, tx_lon = STATION_COORDS[station]
        
        # Haversine formula for great-circle distance
        import math
        R = 6371000  # Earth radius in meters
        
        lat1, lat2 = math.radians(rx_lat), math.radians(tx_lat)
        dlat = math.radians(tx_lat - rx_lat)
        dlon = math.radians(tx_lon - rx_lon)
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        # Speed of light
        c_light = 299792458  # m/s
        delay = distance / c_light
        
        logger.debug(f"Propagation delay to {station}: {delay*1000:.2f} ms ({distance/1000:.0f} km)")
        return delay
        
    except Exception as e:
        logger.warning(f"Could not calculate propagation delay: {e}")
        return 0.010  # Default 10ms


@dataclass
class UTCCalibration:
    """UTC calibration data."""
    rtp_to_utc_offset: float      # Seconds to add to (rtp_timestamp / sample_rate)
    ntp_offset_error: float       # Correction from initial NTP offset (seconds)
    station: str                  # Station used for calibration
    propagation_delay: float      # Propagation delay accounted for (seconds)
    confidence: float             # Confidence level (0-1)
    kalman_grade: str             # Grade at calibration time
    calibrated_at: str            # ISO timestamp
    tone_rtp_timestamp: int       # RTP timestamp of calibration tone
    tone_utc_minute: int          # UTC minute boundary (Unix timestamp)


class UTCCalibrator:
    """
    Manages UTC calibration from tone detection.
    """
    
    def __init__(self, data_root: Path, receiver_grid: str, sample_rate: int = 20000):
        self.data_root = Path(data_root)
        self.receiver_grid = receiver_grid
        self.sample_rate = sample_rate
        self.calibration_file = self.data_root / 'state' / 'utc_calibration.json'
        self.calibration_file.parent.mkdir(parents=True, exist_ok=True)
        
    def apply_calibration(
        self,
        tone_rtp_timestamp: int,
        tone_utc_minute: int,
        station: str,
        confidence: float,
        kalman_grade: str,
        current_ntp_offset: float
    ) -> Optional[UTCCalibration]:
        """
        Apply UTC calibration from a converged tone detection.
        
        Args:
            tone_rtp_timestamp: RTP timestamp when tone was detected
            tone_utc_minute: The UTC minute boundary (Unix timestamp) the tone represents
            station: Station that transmitted the tone ('WWV', 'WWVH')
            confidence: Confidence level from Kalman filter (0-1)
            kalman_grade: Quality grade ('A', 'B', 'C', 'D')
            current_ntp_offset: The current RTP-to-Unix offset from NTP calibration
            
        Returns:
            UTCCalibration object if successful
        """
        if confidence < 0.8:
            logger.warning(f"Confidence {confidence:.2f} too low for calibration (need >0.8)")
            return None
            
        if kalman_grade not in ['A', 'B']:
            logger.warning(f"Grade {kalman_grade} too low for calibration (need A or B)")
            return None
        
        # Calculate propagation delay
        prop_delay = calculate_propagation_delay(self.receiver_grid, station)
        
        # The tone was transmitted at tone_utc_minute and arrived prop_delay later
        tone_arrival_utc = tone_utc_minute + prop_delay
        
        # Calculate precise RTP-to-UTC offset
        rtp_to_utc_offset = tone_arrival_utc - (tone_rtp_timestamp / self.sample_rate)
        
        # Calculate how much the NTP offset was wrong
        ntp_offset_error = rtp_to_utc_offset - current_ntp_offset
        
        calibration = UTCCalibration(
            rtp_to_utc_offset=rtp_to_utc_offset,
            ntp_offset_error=ntp_offset_error,
            station=station,
            propagation_delay=prop_delay,
            confidence=confidence,
            kalman_grade=kalman_grade,
            calibrated_at=datetime.now(timezone.utc).isoformat(),
            tone_rtp_timestamp=tone_rtp_timestamp,
            tone_utc_minute=tone_utc_minute
        )
        
        # Save calibration
        self._save_calibration(calibration)
        
        logger.info(
            f"✅ UTC calibration applied: offset={rtp_to_utc_offset:.6f}s, "
            f"NTP error={ntp_offset_error*1000:.2f}ms, "
            f"station={station}, prop_delay={prop_delay*1000:.2f}ms"
        )
        
        return calibration
    
    def _save_calibration(self, calibration: UTCCalibration):
        """Save calibration to file."""
        data = {
            'rtp_to_utc_offset': calibration.rtp_to_utc_offset,
            'ntp_offset_error': calibration.ntp_offset_error,
            'station': calibration.station,
            'propagation_delay': calibration.propagation_delay,
            'confidence': calibration.confidence,
            'kalman_grade': calibration.kalman_grade,
            'calibrated_at': calibration.calibrated_at,
            'tone_rtp_timestamp': calibration.tone_rtp_timestamp,
            'tone_utc_minute': calibration.tone_utc_minute,
            'sample_rate': self.sample_rate,
            'receiver_grid': self.receiver_grid
        }
        
        with open(self.calibration_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load_calibration(cls, data_root: Path) -> Optional[Dict[str, Any]]:
        """
        Load calibration from file.
        
        Returns:
            Calibration dict or None if not available
        """
        calibration_file = Path(data_root) / 'state' / 'utc_calibration.json'
        
        if not calibration_file.exists():
            return None
            
        try:
            with open(calibration_file) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load calibration: {e}")
            return None
    
    @classmethod
    def get_precise_utc(
        cls, 
        rtp_timestamp: int, 
        sample_rate: int,
        data_root: Path,
        fallback_offset: float
    ) -> tuple[float, bool]:
        """
        Get precise UTC time from RTP timestamp.
        
        Args:
            rtp_timestamp: RTP timestamp
            sample_rate: Sample rate in Hz
            data_root: Data root directory
            fallback_offset: NTP-based offset to use if no calibration
            
        Returns:
            (utc_time, is_calibrated) tuple
        """
        calibration = cls.load_calibration(data_root)
        
        if calibration and calibration.get('confidence', 0) > 0.8:
            utc_time = rtp_timestamp / sample_rate + calibration['rtp_to_utc_offset']
            return utc_time, True
        else:
            utc_time = rtp_timestamp / sample_rate + fallback_offset
            return utc_time, False
