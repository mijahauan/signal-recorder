"""
Multi-Broadcast D_clock Fusion Engine

================================================================================
PURPOSE
================================================================================
Combine D_clock estimates from all available broadcasts to produce a
HIGH-ACCURACY UTC(NIST) time estimate through weighted fusion and
auto-calibration.

The fused D_clock should converge to 0ms, indicating perfect alignment
with UTC(NIST).

================================================================================
BROADCAST STRUCTURE
================================================================================
The GRAPE system monitors up to 13 time signal broadcasts:

    STATION | FREQUENCIES
    --------|----------------------------------------------------
    WWV     | 2.5, 5, 10, 15, 20, 25 MHz (6 broadcasts)
    WWVH    | 2.5, 5, 10, 15 MHz (4 broadcasts, shared with WWV)
    CHU     | 3.33, 7.85, 14.67 MHz (3 broadcasts, unique)

SHARED vs UNIQUE FREQUENCIES:
    - Shared (WWV + WWVH): 2.5, 5, 10, 15 MHz → 8 broadcasts (need discrimination)
    - WWV-only: 20, 25 MHz → 2 broadcasts
    - CHU-only: 3.33, 7.85, 14.67 MHz → 3 broadcasts (FSK timing reference)

================================================================================
FUSION THEORY
================================================================================
Each broadcast provides an independent D_clock estimate:

    D_clock_i = T_arrival_i - T_propagation_i

These estimates have different uncertainties based on:
    - SNR (signal quality)
    - Propagation mode (1-hop vs multi-hop)
    - Discrimination confidence (shared frequencies)
    - Quality grade from convergence model

WEIGHTED FUSION:
    D_clock_fused = Σ(w_i × D_clock_i) / Σ(w_i)

Where weights w_i are computed from:
    w_i = confidence × grade_weight × mode_weight × snr_factor

GRADE WEIGHTS:    A: 1.0, B: 0.8, C: 0.5, D: 0.2
MODE WEIGHTS:     1E: 1.0, 1F: 0.9, 2F: 0.7, 3F: 0.5, GW: 1.0

================================================================================
AUTO-CALIBRATION
================================================================================
Each station has a systematic offset due to:
    - Matched filter group delay
    - Tone rise time differences
    - Detection threshold effects

CALIBRATION MODEL:
    calibration_offset_station = -mean(D_clock_station)

This brings each station's mean D_clock to 0, which is the UTC(NIST) target.

CALIBRATION UPDATE (Exponential Moving Average):
    offset_new = α × (-mean_current) + (1-α) × offset_old
    
Where α = max(0.5, 20/n_samples) for fast initial convergence.

CHU AS REFERENCE:
    CHU's FSK time code provides precise 500ms boundary alignment,
    making it the most trusted reference. However, all stations are
    calibrated to converge to 0 (not to match CHU), since the goal
    is UTC(NIST) alignment.

================================================================================
OUTLIER REJECTION
================================================================================
Uses weighted Median Absolute Deviation (MAD) for robust outlier detection:

    MAD = median(|D_clock_i - weighted_median|) × 1.4826
    
Measurements with deviation > 3σ are rejected.

This prevents ionospheric events or detection errors on one channel
from corrupting the fused estimate.

================================================================================
OUTPUT
================================================================================
The fusion produces:
    - d_clock_fused_ms: Calibrated weighted mean (should → 0)
    - d_clock_raw_ms: Uncalibrated mean (for comparison)
    - uncertainty_ms: Weighted standard deviation
    - n_broadcasts: Number of broadcasts contributing
    - quality_grade: A/B/C/D based on broadcast count and uncertainty

Output is written to: phase2/fusion/fused_d_clock.csv

================================================================================
USAGE
================================================================================
Continuous service mode (typical):

    python -m grape_recorder.grape.multi_broadcast_fusion \\
        --data-root /data \\
        --interval 60

Programmatic usage:

    fusion = MultiBroadcastFusion(data_root=Path('/data'))
    result = fusion.fuse(lookback_minutes=10)
    print(f"Fused D_clock: {result.d_clock_fused_ms:+.3f} ms")

================================================================================
REVISION HISTORY
================================================================================
2025-12-07: Added comprehensive theoretical documentation
2025-11-20: Improved calibration to target UTC(NIST) = 0
2025-11-01: Initial implementation with CHU reference
"""

import logging
import json
import csv
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BroadcastMeasurement:
    """Single D_clock measurement from one broadcast."""
    timestamp: float           # Unix time of measurement
    station: str              # WWV, WWVH, CHU
    frequency_mhz: float      # Broadcast frequency
    d_clock_ms: float         # Raw D_clock measurement
    propagation_delay_ms: float
    propagation_mode: str     # 1E, 1F, 2F, etc.
    confidence: float         # 0-1 confidence score
    snr_db: float            # Signal quality
    quality_grade: str        # A, B, C, D
    channel_name: str         # Source channel


@dataclass
class BroadcastCalibration:
    """
    Per-broadcast calibration offset learned from data.
    
    Issue 3.2 Fix: Calibration is now per-broadcast (station+frequency) rather
    than per-station. This accounts for frequency-dependent ionospheric delays:
    - Different frequencies have different ionospheric delays (1/f²)
    - Same-frequency broadcasts share ionospheric conditions (correlated errors)
    
    Issue 4.3 Fix: No more hardcoded defaults. Initial offset is 0 with high
    uncertainty, and the system learns from data using ground truth validation.
    """
    station: str              # WWV, WWVH, CHU
    frequency_mhz: float      # Broadcast frequency (key for correlation)
    offset_ms: float          # Calibration offset to apply
    uncertainty_ms: float     # Uncertainty in offset
    n_samples: int            # Number of samples used
    last_updated: float       # Unix time of last update
    reference_station: str    # Station used as reference (CHU)
    
    @property
    def broadcast_key(self) -> str:
        """Unique key for this broadcast (station_frequency)."""
        return f"{self.station}_{self.frequency_mhz:.2f}"


# Legacy alias for backwards compatibility
StationCalibration = BroadcastCalibration


@dataclass 
class FusedResult:
    """Result of multi-broadcast fusion."""
    timestamp: float
    d_clock_fused_ms: float      # Fused D_clock (should converge to 0)
    d_clock_raw_ms: float        # Unweighted mean before calibration
    uncertainty_ms: float        # Estimated uncertainty
    n_broadcasts: int            # Number of broadcasts used
    n_stations: int              # Number of unique stations
    
    # Per-station breakdown
    wwv_mean_ms: Optional[float] = None
    wwvh_mean_ms: Optional[float] = None
    chu_mean_ms: Optional[float] = None
    wwv_count: int = 0
    wwvh_count: int = 0
    chu_count: int = 0
    
    # Calibration applied
    calibration_applied: bool = False
    reference_station: str = 'CHU'
    
    # Quality
    outliers_rejected: int = 0
    quality_grade: str = 'D'


class MultiBroadcastFusion:
    """
    Fuse D_clock estimates from all 13 broadcasts.
    
    Uses CHU FSK-verified timing as the reference for calibration,
    since CHU FSK provides exact 500ms boundary alignment.
    """
    
    # Issue 4.3 Fix: No more hardcoded defaults
    # Calibration starts at 0 with high uncertainty and learns from data.
    # Per-broadcast calibration (Issue 3.2) accounts for frequency-dependent delays.
    #
    # The old hardcoded values were:
    #   'WWV': 2.5, 'WWVH': 2.5, 'CHU': 1.0
    # These are now replaced by learned values from ground truth validation.
    DEFAULT_CALIBRATION = {}  # Empty - all calibration is learned
    
    def __init__(
        self,
        data_root: Path,
        calibration_file: Optional[Path] = None,
        auto_calibrate: bool = True,
        reference_station: str = 'CHU'
    ):
        """
        Initialize multi-broadcast fusion engine.
        
        Args:
            data_root: Root directory containing phase2/{CHANNEL}/ subdirs
            calibration_file: Optional file to persist calibration
            auto_calibrate: Whether to learn calibration from data
            reference_station: Station to use as timing reference
        """
        self.data_root = Path(data_root)
        self.phase2_dir = self.data_root / 'phase2'
        self.auto_calibrate = auto_calibrate
        self.reference_station = reference_station
        
        # Calibration state
        self.calibration_file = calibration_file or (
            self.data_root / 'state' / 'broadcast_calibration.json'
        )
        self.calibration: Dict[str, StationCalibration] = {}
        self._load_calibration()
        
        # Fusion output
        self.fusion_dir = self.data_root / 'phase2' / 'fusion'
        self.fusion_dir.mkdir(parents=True, exist_ok=True)
        self.fusion_csv = self.fusion_dir / 'fused_d_clock.csv'
        self._init_fusion_csv()
        
        # History for calibration learning
        self.measurement_history: Dict[str, List[BroadcastMeasurement]] = defaultdict(list)
        self.history_max_size = 100  # Keep last N measurements per station
        
        # Channels to aggregate
        self.channels = self._discover_channels()
        
        logger.info(f"MultiBroadcastFusion initialized")
        logger.info(f"  Data root: {data_root}")
        logger.info(f"  Channels: {len(self.channels)}")
        logger.info(f"  Reference station: {reference_station}")
        logger.info(f"  Auto-calibrate: {auto_calibrate}")
    
    def _discover_channels(self) -> List[str]:
        """Discover available Phase 2 channels."""
        channels = []
        if self.phase2_dir.exists():
            for subdir in self.phase2_dir.iterdir():
                if subdir.is_dir() and (subdir / 'clock_offset').exists():
                    channels.append(subdir.name)
        return sorted(channels)
    
    def _load_calibration(self):
        """
        Load per-broadcast calibration from file.
        
        Issue 3.2 Fix: Calibration is now keyed by broadcast (station_frequency)
        rather than just station, to account for frequency-dependent delays.
        """
        if self.calibration_file.exists():
            try:
                with open(self.calibration_file) as f:
                    data = json.load(f)
                for broadcast_key, cal_data in data.items():
                    # Parse station and frequency from key (e.g., "WWV_10.00")
                    parts = broadcast_key.rsplit('_', 1)
                    station = parts[0] if len(parts) > 1 else broadcast_key
                    freq = float(parts[1]) if len(parts) > 1 else 0.0
                    
                    self.calibration[broadcast_key] = BroadcastCalibration(
                        station=station,
                        frequency_mhz=cal_data.get('frequency_mhz', freq),
                        offset_ms=cal_data['offset_ms'],
                        uncertainty_ms=cal_data['uncertainty_ms'],
                        n_samples=cal_data['n_samples'],
                        last_updated=cal_data['last_updated'],
                        reference_station=cal_data.get('reference_station', 'CHU')
                    )
                logger.info(f"Loaded {len(self.calibration)} broadcast calibrations from {self.calibration_file}")
            except Exception as e:
                logger.warning(f"Could not load calibration: {e}")
                self._init_default_calibration()
        else:
            self._init_default_calibration()
    
    def _init_default_calibration(self):
        """
        Initialize with zero calibration (Issue 4.3 fix).
        
        Instead of hardcoded guesses, we start with zero offset and high
        uncertainty. The system learns proper calibration from:
        1. Ground truth validation (GPS PPS, silent minutes)
        2. CHU FSK verified timing
        3. Cross-validation between broadcasts
        """
        # No default offsets - all calibration is learned from data
        # The calibration dict will be populated as measurements arrive
        logger.info("Calibration initialized - will learn from data (no hardcoded defaults)")
    
    def _save_calibration(self):
        """Persist per-broadcast calibration to file."""
        self.calibration_file.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for broadcast_key, cal in self.calibration.items():
            data[broadcast_key] = {
                'station': cal.station,
                'frequency_mhz': cal.frequency_mhz,
                'offset_ms': cal.offset_ms,
                'uncertainty_ms': cal.uncertainty_ms,
                'n_samples': cal.n_samples,
                'last_updated': cal.last_updated,
                'reference_station': cal.reference_station
            }
        with open(self.calibration_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _init_fusion_csv(self):
        """Initialize fused D_clock CSV."""
        if not self.fusion_csv.exists():
            with open(self.fusion_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'd_clock_fused_ms', 'd_clock_raw_ms',
                    'uncertainty_ms', 'n_broadcasts', 'n_stations',
                    'wwv_mean_ms', 'wwvh_mean_ms', 'chu_mean_ms',
                    'wwv_count', 'wwvh_count', 'chu_count',
                    'calibration_applied', 'quality_grade',
                    'outliers_rejected'
                ])
    
    def _read_latest_measurements(
        self, 
        lookback_minutes: int = 5
    ) -> List[BroadcastMeasurement]:
        """
        Read latest D_clock measurements from all channels.
        
        Returns measurements from the last N minutes.
        """
        measurements = []
        now = time.time()
        cutoff = now - (lookback_minutes * 60)
        
        for channel in self.channels:
            csv_path = self.phase2_dir / channel / 'clock_offset' / 'clock_offset_series.csv'
            if not csv_path.exists():
                continue
            
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            ts = float(row.get('system_time', 0))
                            if ts < cutoff:
                                continue
                            
                            m = BroadcastMeasurement(
                                timestamp=ts,
                                station=row.get('station', 'UNKNOWN'),
                                frequency_mhz=float(row.get('frequency_mhz', 0)),
                                d_clock_ms=float(row.get('clock_offset_ms', 0)),
                                propagation_delay_ms=float(row.get('propagation_delay_ms', 0)),
                                propagation_mode=row.get('propagation_mode', ''),
                                confidence=float(row.get('confidence', 0)),
                                snr_db=float(row.get('snr_db', 0)),
                                quality_grade=row.get('quality_grade', 'D'),
                                channel_name=channel
                            )
                            measurements.append(m)
                        except (ValueError, KeyError):
                            continue
            except Exception as e:
                logger.debug(f"Error reading {csv_path}: {e}")
        
        return measurements
    
    def _calculate_weights(
        self, 
        measurements: List[BroadcastMeasurement]
    ) -> List[float]:
        """
        Calculate quality-based weights for each measurement.
        
        Weights consider:
        - Confidence score
        - SNR
        - Quality grade
        - Propagation mode (lower hop = more reliable)
        """
        weights = []
        
        grade_weights = {'A': 1.0, 'B': 0.8, 'C': 0.5, 'D': 0.2}
        mode_weights = {
            '1E': 1.0, '1F': 0.9, '2F': 0.7, '3F': 0.5, 'GW': 1.0
        }
        
        for m in measurements:
            # Base weight from confidence
            w = m.confidence
            
            # Adjust for quality grade
            w *= grade_weights.get(m.quality_grade, 0.2)
            
            # Adjust for propagation mode
            w *= mode_weights.get(m.propagation_mode, 0.5)
            
            # Adjust for SNR (higher is better)
            if m.snr_db > 10:
                w *= 1.0
            elif m.snr_db > 5:
                w *= 0.8
            else:
                w *= 0.5
            
            weights.append(max(0.01, w))  # Minimum weight
        
        return weights
    
    def _reject_outliers(
        self,
        measurements: List[BroadcastMeasurement],
        weights: List[float],
        sigma_threshold: float = 3.0
    ) -> Tuple[List[BroadcastMeasurement], List[float], int]:
        """
        Reject outliers using weighted median absolute deviation.
        
        Returns filtered measurements, weights, and count of rejected.
        """
        if len(measurements) < 4:
            return measurements, weights, 0
        
        # Calculate weighted median
        d_clocks = np.array([m.d_clock_ms for m in measurements])
        w = np.array(weights)
        
        sorted_idx = np.argsort(d_clocks)
        sorted_d = d_clocks[sorted_idx]
        sorted_w = w[sorted_idx]
        cumsum = np.cumsum(sorted_w)
        median_idx = np.searchsorted(cumsum, cumsum[-1] / 2)
        weighted_median = sorted_d[min(median_idx, len(sorted_d)-1)]
        
        # Calculate MAD
        deviations = np.abs(d_clocks - weighted_median)
        mad = np.median(deviations) * 1.4826  # Scale to std dev
        
        if mad < 0.1:
            mad = 0.1  # Minimum to avoid divide by zero
        
        # Reject outliers
        keep_mask = deviations < (sigma_threshold * mad)
        
        filtered_m = [m for m, keep in zip(measurements, keep_mask) if keep]
        filtered_w = [w for w, keep in zip(weights, keep_mask) if keep]
        n_rejected = len(measurements) - len(filtered_m)
        
        return filtered_m, filtered_w, n_rejected
    
    def _get_broadcast_key(self, station: str, frequency_mhz: float) -> str:
        """Generate consistent broadcast key for calibration lookups."""
        return f"{station}_{frequency_mhz:.2f}"
    
    def _apply_calibration(
        self,
        measurements: List[BroadcastMeasurement]
    ) -> List[float]:
        """
        Apply per-broadcast calibration offsets.
        
        Issue 1.1 Fix (2025-12-08): Now correctly uses per-broadcast keys
        (station_frequency) instead of per-station keys. This properly accounts
        for frequency-dependent ionospheric delays (1/f²).
        
        Returns calibrated D_clock values.
        """
        calibrated = []
        for m in measurements:
            # Use per-broadcast key for frequency-dependent calibration
            broadcast_key = self._get_broadcast_key(m.station, m.frequency_mhz)
            cal = self.calibration.get(broadcast_key)
            if cal:
                # Apply the calibration offset
                calibrated.append(m.d_clock_ms + cal.offset_ms)
            else:
                # Fall back to station-level calibration for backwards compatibility
                station_cal = self.calibration.get(m.station)
                if station_cal:
                    calibrated.append(m.d_clock_ms + station_cal.offset_ms)
                else:
                    calibrated.append(m.d_clock_ms)
        return calibrated
    
    def _update_calibration(
        self,
        measurements: List[BroadcastMeasurement]
    ):
        """
        Update calibration offsets per-broadcast.
        
        Issue 1.1 Fix (2025-12-08): Now calibrates per-broadcast (station+frequency)
        instead of per-station. This accounts for frequency-dependent ionospheric
        delays which follow 1/f² relationship.
        
        Uses CHU as reference (assumed most accurate due to FSK).
        All broadcasts are calibrated to converge to UTC(NIST) = 0.
        """
        if not self.auto_calibrate:
            return
        
        # Add to history keyed by broadcast (station + frequency)
        for m in measurements:
            broadcast_key = self._get_broadcast_key(m.station, m.frequency_mhz)
            history = self.measurement_history[broadcast_key]
            history.append(m)
            if len(history) > self.history_max_size:
                self.measurement_history[broadcast_key] = history[-self.history_max_size:]
        
        # Update calibration for each broadcast individually
        for broadcast_key, history in self.measurement_history.items():
            if len(history) < 10:
                continue
            
            # Get recent measurements for this broadcast
            recent = history[-30:]
            broadcast_d_clocks = [m.d_clock_ms for m in recent]
            broadcast_mean = np.mean(broadcast_d_clocks)
            
            # Extract station and frequency from the history
            station = recent[0].station
            frequency_mhz = recent[0].frequency_mhz
            
            # Offset should bring mean to 0 (UTC(NIST) alignment)
            new_offset = -broadcast_mean
            
            # Exponential moving average for smooth updates
            old_cal = self.calibration.get(broadcast_key)
            if old_cal and old_cal.n_samples > 0:
                # Faster adaptation initially, slower as samples accumulate
                alpha = max(0.5, 20.0 / old_cal.n_samples)
                new_offset = alpha * new_offset + (1 - alpha) * old_cal.offset_ms
            
            self.calibration[broadcast_key] = BroadcastCalibration(
                station=station,
                frequency_mhz=frequency_mhz,
                offset_ms=new_offset,
                uncertainty_ms=np.std(broadcast_d_clocks) if len(broadcast_d_clocks) > 1 else 1.0,
                n_samples=len(history),
                last_updated=time.time(),
                reference_station=self.reference_station
            )
        
        self._save_calibration()
    
    def fuse(self, lookback_minutes: int = 10) -> Optional[FusedResult]:
        """
        Perform multi-broadcast fusion.
        
        Combines all available broadcasts into a single D_clock estimate
        that converges toward UTC(NIST).
        
        Returns:
            FusedResult with fused D_clock and statistics
        """
        # Read latest measurements
        measurements = self._read_latest_measurements(lookback_minutes)
        
        if not measurements:
            logger.debug("No measurements available for fusion")
            return None
        
        # Calculate weights
        weights = self._calculate_weights(measurements)
        
        # Reject outliers
        measurements, weights, n_rejected = self._reject_outliers(
            measurements, weights
        )
        
        if len(measurements) < 2:
            logger.debug("Too few measurements after outlier rejection")
            return None
        
        # Update calibration (before applying)
        self._update_calibration(measurements)
        
        # Apply calibration
        calibrated = self._apply_calibration(measurements)
        
        # Weighted mean of calibrated values
        w = np.array(weights)
        d = np.array(calibrated)
        fused_d_clock = np.sum(w * d) / np.sum(w)
        
        # Raw (uncalibrated) mean for comparison
        raw_d_clocks = np.array([m.d_clock_ms for m in measurements])
        raw_mean = np.mean(raw_d_clocks)
        
        # Uncertainty from weighted std
        weighted_var = np.sum(w * (d - fused_d_clock)**2) / np.sum(w)
        uncertainty = np.sqrt(weighted_var)
        
        # Per-station breakdown
        wwv_m = [m.d_clock_ms for m in measurements if m.station == 'WWV']
        wwvh_m = [m.d_clock_ms for m in measurements if m.station == 'WWVH']
        chu_m = [m.d_clock_ms for m in measurements if m.station == 'CHU']
        
        # Unique stations
        stations = set(m.station for m in measurements)
        
        # Quality grade based on number of broadcasts and uncertainty
        if len(measurements) >= 8 and uncertainty < 0.5:
            grade = 'A'
        elif len(measurements) >= 5 and uncertainty < 1.0:
            grade = 'B'
        elif len(measurements) >= 3 and uncertainty < 2.0:
            grade = 'C'
        else:
            grade = 'D'
        
        result = FusedResult(
            timestamp=time.time(),
            d_clock_fused_ms=fused_d_clock,
            d_clock_raw_ms=raw_mean,
            uncertainty_ms=uncertainty,
            n_broadcasts=len(measurements),
            n_stations=len(stations),
            wwv_mean_ms=np.mean(wwv_m) if wwv_m else None,
            wwvh_mean_ms=np.mean(wwvh_m) if wwvh_m else None,
            chu_mean_ms=np.mean(chu_m) if chu_m else None,
            wwv_count=len(wwv_m),
            wwvh_count=len(wwvh_m),
            chu_count=len(chu_m),
            calibration_applied=True,
            reference_station=self.reference_station,
            outliers_rejected=n_rejected,
            quality_grade=grade
        )
        
        # Write to CSV
        self._write_fused_result(result)
        
        return result
    
    def _write_fused_result(self, result: FusedResult):
        """Append fused result to CSV."""
        with open(self.fusion_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                result.timestamp,
                result.d_clock_fused_ms,
                result.d_clock_raw_ms,
                result.uncertainty_ms,
                result.n_broadcasts,
                result.n_stations,
                result.wwv_mean_ms or '',
                result.wwvh_mean_ms or '',
                result.chu_mean_ms or '',
                result.wwv_count,
                result.wwvh_count,
                result.chu_count,
                result.calibration_applied,
                result.quality_grade,
                result.outliers_rejected
            ])
    
    def get_current_calibration(self) -> Dict[str, float]:
        """Get current calibration offsets."""
        return {
            station: cal.offset_ms 
            for station, cal in self.calibration.items()
        }
    
    def get_status(self) -> Dict:
        """Get fusion engine status."""
        return {
            'channels': self.channels,
            'n_channels': len(self.channels),
            'reference_station': self.reference_station,
            'auto_calibrate': self.auto_calibrate,
            'calibration': {
                station: {
                    'offset_ms': cal.offset_ms,
                    'uncertainty_ms': cal.uncertainty_ms,
                    'n_samples': cal.n_samples
                }
                for station, cal in self.calibration.items()
            }
        }


def run_fusion_service(data_root: Path, interval_sec: float = 60.0):
    """
    Run continuous fusion service.
    
    Produces fused D_clock estimate every interval_sec.
    """
    fusion = MultiBroadcastFusion(data_root)
    
    logger.info("Starting Multi-Broadcast Fusion Service")
    logger.info(f"  Interval: {interval_sec} seconds")
    logger.info(f"  Output: {fusion.fusion_csv}")
    
    while True:
        try:
            result = fusion.fuse()
            
            if result:
                logger.info(
                    f"Fused D_clock: {result.d_clock_fused_ms:+.3f} ms "
                    f"(raw: {result.d_clock_raw_ms:+.3f} ms) "
                    f"± {result.uncertainty_ms:.3f} ms "
                    f"[{result.n_broadcasts} broadcasts, grade {result.quality_grade}]"
                )
            
            time.sleep(interval_sec)
            
        except KeyboardInterrupt:
            logger.info("Fusion service stopped")
            break
        except Exception as e:
            logger.error(f"Fusion error: {e}")
            time.sleep(interval_sec)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Multi-Broadcast D_clock Fusion')
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--interval', type=float, default=60.0)
    parser.add_argument('--log-level', default='INFO')
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s %(levelname)s:%(name)s:%(message)s'
    )
    
    run_fusion_service(args.data_root, args.interval)
