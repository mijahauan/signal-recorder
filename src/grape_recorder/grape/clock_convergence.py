#!/usr/bin/env python3
"""
Clock Convergence Model - "Set, Monitor, Intervention" Architecture

================================================================================
PURPOSE
================================================================================
Implement a convergence-to-lock model for D_clock estimation that:
    1. Converges to a stable clock offset estimate
    2. Monitors for ionospheric propagation events (scientific data!)
    3. Re-acquires only when persistent anomalies indicate actual change

This is designed for GPSDO-disciplined receivers where the local clock is
a secondary standard with sub-ppm stability.

================================================================================
PHILOSOPHY: "SET, MONITOR, INTERVENTION"
================================================================================
Traditional approach: Constantly recalculate D_clock each minute
    Problem: Propagation variations appear as "noise" in the clock estimate

Our approach: Once clock is characterized, variations ARE the science
    1. SET: Converge to locked D_clock estimate (first 30 minutes)
    2. MONITOR: Track residuals as ionospheric propagation data
    3. INTERVENTION: Re-acquire only if physics violated

KEY INSIGHT:
    With a GPSDO (10⁻⁹ stability), the clock doesn't drift measurably in hours.
    Minute-to-minute D_clock variations are therefore NOT clock error—they
    are IONOSPHERIC PROPAGATION EFFECTS that we want to measure!

================================================================================
STATE MACHINE
================================================================================
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                                                                         │
    │   ┌──────────────┐                                                      │
    │   │  ACQUIRING   │ ──────────────────────────┐                          │
    │   │   N < 10     │                           │                          │
    │   └──────┬───────┘                           │                          │
    │          │ N ≥ 10                            │                          │
    │          ▼                                   │                          │
    │   ┌──────────────┐                           │                          │
    │   │  CONVERGING  │ ◄─────────────────────────┘                          │
    │   │  σ/√N > th   │                                                      │
    │   └──────┬───────┘                                                      │
    │          │ σ/√N < th AND N ≥ 30                                         │
    │          ▼                                                              │
    │   ┌──────────────┐      5 consecutive       ┌──────────────┐            │
    │   │    LOCKED    │ ──── anomalies ─────────►│  REACQUIRE   │            │
    │   │  monitoring  │                          │   reset      │            │
    │   └──────────────┘                          └──────┬───────┘            │
    │          ▲                                         │                    │
    │          │                                         │                    │
    │          └─────────────────────────────────────────┘                    │
    │                         start over                                      │
    └─────────────────────────────────────────────────────────────────────────┘

STATE DESCRIPTIONS:
    ACQUIRING  - First 10 measurements, building initial statistics
    CONVERGING - Uncertainty shrinking toward lock threshold
    LOCKED     - High confidence, now treating variations as propagation data
    HOLDOVER   - (Future) Lock lost but using last good estimate
    REACQUIRE  - Persistent anomalies, resetting statistics

================================================================================
STATISTICAL MODEL
================================================================================
WELFORD'S ONLINE ALGORITHM for numerically stable running statistics:

    count += 1
    delta = x - mean
    mean += delta / count
    delta2 = x - mean
    M2 += delta * delta2
    
    variance = M2 / count
    std_dev = √variance
    uncertainty = std_dev / √count  (standard error of the mean)

LOCK CRITERION:
    uncertainty < lock_threshold_ms (default: 1.0 ms)
    AND
    count ≥ min_samples (default: 30)

ANOMALY DETECTION:
    residual = measurement - reference
    anomaly_sigma = |residual| / std_dev
    is_anomaly = anomaly_sigma > k_sigma (default: 3.0)

================================================================================
OUTPUT: CONVERGENCE RESULT
================================================================================
Each measurement produces:
    - d_clock_ms: Best estimate (locked or running mean)
    - uncertainty_ms: Current uncertainty
    - residual_ms: Deviation from estimate (THE PROPAGATION SCIENCE!)
    - is_locked: True when locked
    - is_anomaly: True if residual exceeds threshold
    - convergence_progress: 0.0 to 1.0

WHEN LOCKED:
    residual_ms contains the ionospheric delay variation from mean.
    These residuals are the PRIMARY SCIENTIFIC OUTPUT for space weather!

================================================================================
USAGE
================================================================================
    model = ClockConvergenceModel(
        lock_uncertainty_ms=1.0,    # Lock when uncertainty < 1ms
        min_samples_for_lock=30,    # Need 30 minutes of data
        anomaly_sigma=3.0,          # 3σ for anomaly detection
        state_file=Path('/data/state/convergence.json')
    )
    
    # Process each minute's measurement
    result = model.process_measurement(
        station='WWV',
        frequency_mhz=10.0,
        d_clock_ms=15.234,
        timestamp=time.time()
    )
    
    if result.is_locked:
        # Use residual for space weather science!
        ionospheric_variation_ms = result.residual_ms
    else:
        # Still converging, use d_clock_ms for timing
        print(f"Converging: {result.convergence_progress:.0%}")

================================================================================
REVISION HISTORY
================================================================================
2025-12-07: Added comprehensive documentation
2025-12-01: Added state persistence
2025-11-15: Initial "Set, Monitor, Intervention" implementation
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
import json
import math
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ConvergenceState(Enum):
    """State of the clock convergence model."""
    ACQUIRING = "acquiring"      # Building initial estimate
    CONVERGING = "converging"    # Uncertainty shrinking
    LOCKED = "locked"            # High confidence, monitoring mode
    HOLDOVER = "holdover"        # Using last good estimate
    REACQUIRE = "reacquire"      # Rebuilding after anomaly


@dataclass
class StationAccumulator:
    """Running statistics for a single station's clock offset measurements."""
    station: str
    frequency_mhz: float
    
    # Running statistics (Welford's online algorithm)
    count: int = 0
    mean_ms: float = 0.0
    m2: float = 0.0  # Sum of squared differences from mean
    
    # Lock state
    state: ConvergenceState = field(default=ConvergenceState.ACQUIRING)
    locked_mean_ms: Optional[float] = None
    locked_uncertainty_ms: Optional[float] = None
    lock_timestamp: Optional[float] = None
    
    # History for anomaly detection
    last_measurements: List[float] = field(default_factory=list)
    max_history: int = 60  # Keep last hour of measurements
    
    # Anomaly tracking
    consecutive_anomalies: int = 0
    total_anomalies: int = 0
    
    @property
    def variance(self) -> float:
        """Population variance of measurements."""
        if self.count < 2:
            return float('inf')
        return self.m2 / self.count
    
    @property
    def std_dev(self) -> float:
        """Standard deviation of measurements."""
        return math.sqrt(self.variance) if self.variance != float('inf') else float('inf')
    
    @property
    def uncertainty_ms(self) -> float:
        """Standard error of the mean: σ/√N."""
        if self.count < 2:
            return float('inf')
        return self.std_dev / math.sqrt(self.count)
    
    def update(self, measurement_ms: float) -> None:
        """Add a new measurement using Welford's online algorithm."""
        self.count += 1
        delta = measurement_ms - self.mean_ms
        self.mean_ms += delta / self.count
        delta2 = measurement_ms - self.mean_ms
        self.m2 += delta * delta2
        
        # Track recent history
        self.last_measurements.append(measurement_ms)
        if len(self.last_measurements) > self.max_history:
            self.last_measurements.pop(0)
    
    def to_dict(self) -> dict:
        """Serialize state to dictionary."""
        return {
            'station': self.station,
            'frequency_mhz': self.frequency_mhz,
            'count': self.count,
            'mean_ms': self.mean_ms,
            'm2': self.m2,
            'state': self.state.value,
            'locked_mean_ms': self.locked_mean_ms,
            'locked_uncertainty_ms': self.locked_uncertainty_ms,
            'lock_timestamp': self.lock_timestamp,
            'last_measurements': self.last_measurements[-10:],  # Save last 10
            'consecutive_anomalies': self.consecutive_anomalies,
            'total_anomalies': self.total_anomalies
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'StationAccumulator':
        """Deserialize from dictionary."""
        acc = cls(
            station=data['station'],
            frequency_mhz=data['frequency_mhz'],
            count=data.get('count', 0),
            mean_ms=data.get('mean_ms', 0.0),
            m2=data.get('m2', 0.0),
            locked_mean_ms=data.get('locked_mean_ms'),
            locked_uncertainty_ms=data.get('locked_uncertainty_ms'),
            lock_timestamp=data.get('lock_timestamp'),
            consecutive_anomalies=data.get('consecutive_anomalies', 0),
            total_anomalies=data.get('total_anomalies', 0)
        )
        acc.state = ConvergenceState(data.get('state', 'acquiring'))
        acc.last_measurements = data.get('last_measurements', [])
        return acc


@dataclass
class ConvergenceResult:
    """Result of processing a measurement through the convergence model."""
    station: str
    frequency_mhz: float
    
    # Current state
    state: ConvergenceState
    d_clock_ms: float           # Best estimate of clock offset
    uncertainty_ms: float       # Current uncertainty
    
    # Measurement info
    measurement_ms: float       # Raw measurement this minute
    residual_ms: float          # Deviation from converged estimate (propagation effect!)
    
    # Statistics
    sample_count: int
    convergence_progress: float  # 0.0 to 1.0
    
    # Flags
    is_locked: bool
    is_anomaly: bool
    anomaly_sigma: Optional[float] = None


class ClockConvergenceModel:
    """
    Convergence-to-lock model for clock offset estimation.
    
    Implements the "Set, Monitor, Intervention" philosophy:
    1. SET: Converge to a locked clock offset estimate
    2. MONITOR: Track residuals for ionospheric effects
    3. INTERVENTION: Re-acquire only if anomaly detected
    
    Parameters:
    -----------
    lock_uncertainty_ms : float
        Uncertainty threshold for declaring lock (default: 1.0 ms)
    min_samples_for_lock : int
        Minimum samples before lock can be declared (default: 30)
    anomaly_sigma : float
        Number of standard deviations for anomaly detection (default: 3.0)
    max_consecutive_anomalies : int
        Anomalies before forcing re-acquire (default: 5)
    """
    
    def __init__(
        self,
        lock_uncertainty_ms: float = 1.0,
        min_samples_for_lock: int = 30,
        anomaly_sigma: float = 3.0,
        max_consecutive_anomalies: int = 5,
        state_file: Optional[Path] = None
    ):
        self.lock_uncertainty_ms = lock_uncertainty_ms
        self.min_samples_for_lock = min_samples_for_lock
        self.anomaly_sigma = anomaly_sigma
        self.max_consecutive_anomalies = max_consecutive_anomalies
        self.state_file = state_file
        
        # Per-station accumulators: key = "STATION_FREQ" e.g., "WWV_10.0"
        self.accumulators: Dict[str, StationAccumulator] = {}
        
        # Global state
        self.best_d_clock_ms: Optional[float] = None
        self.best_uncertainty_ms: Optional[float] = None
        self.best_source: Optional[str] = None
        
        # Load persisted state if available
        if state_file and state_file.exists():
            self._load_state()
    
    def _get_key(self, station: str, frequency_mhz: float) -> str:
        """Generate accumulator key."""
        return f"{station}_{frequency_mhz}"
    
    def _get_or_create_accumulator(self, station: str, frequency_mhz: float) -> StationAccumulator:
        """Get existing accumulator or create new one."""
        key = self._get_key(station, frequency_mhz)
        if key not in self.accumulators:
            self.accumulators[key] = StationAccumulator(
                station=station,
                frequency_mhz=frequency_mhz
            )
        return self.accumulators[key]
    
    def process_measurement(
        self,
        station: str,
        frequency_mhz: float,
        d_clock_ms: float,
        timestamp: float,
        snr_db: Optional[float] = None,
        quality_grade: Optional[str] = None
    ) -> ConvergenceResult:
        """
        Process a new clock offset measurement.
        
        Parameters:
        -----------
        station : str
            Station identifier (WWV, WWVH, CHU)
        frequency_mhz : float
            Frequency in MHz
        d_clock_ms : float
            Measured clock offset in milliseconds
        timestamp : float
            Unix timestamp of measurement
        snr_db : float, optional
            Signal-to-noise ratio
        quality_grade : str, optional
            Quality grade (A-D, X)
        
        Returns:
        --------
        ConvergenceResult with updated state and estimates
        """
        acc = self._get_or_create_accumulator(station, frequency_mhz)
        
        # Add measurement
        acc.update(d_clock_ms)
        
        # Calculate residual from current estimate
        if acc.state == ConvergenceState.LOCKED and acc.locked_mean_ms is not None:
            reference = acc.locked_mean_ms
        else:
            reference = acc.mean_ms
        
        residual_ms = d_clock_ms - reference
        
        # Anomaly detection (only meaningful after some data)
        is_anomaly = False
        anomaly_sigma = None
        if acc.count > 10 and acc.std_dev > 0:
            anomaly_sigma = abs(residual_ms) / acc.std_dev
            is_anomaly = anomaly_sigma > self.anomaly_sigma
        
        # Update anomaly tracking
        if is_anomaly:
            acc.consecutive_anomalies += 1
            acc.total_anomalies += 1
        else:
            acc.consecutive_anomalies = 0
        
        # State machine
        prev_state = acc.state
        
        if acc.state == ConvergenceState.ACQUIRING:
            # Need minimum samples to assess convergence
            if acc.count >= 10:
                acc.state = ConvergenceState.CONVERGING
        
        elif acc.state == ConvergenceState.CONVERGING:
            # Check lock criterion
            if (acc.count >= self.min_samples_for_lock and 
                acc.uncertainty_ms < self.lock_uncertainty_ms):
                acc.state = ConvergenceState.LOCKED
                acc.locked_mean_ms = acc.mean_ms
                acc.locked_uncertainty_ms = acc.uncertainty_ms
                acc.lock_timestamp = timestamp
                logger.info(
                    f"🔒 LOCKED: {station} @ {frequency_mhz} MHz - "
                    f"D_clock = {acc.locked_mean_ms:.3f} ± {acc.locked_uncertainty_ms:.3f} ms "
                    f"after {acc.count} samples"
                )
        
        elif acc.state == ConvergenceState.LOCKED:
            # Monitor for anomalies
            if acc.consecutive_anomalies >= self.max_consecutive_anomalies:
                acc.state = ConvergenceState.REACQUIRE
                logger.warning(
                    f"⚠️ REACQUIRE: {station} @ {frequency_mhz} MHz - "
                    f"{acc.consecutive_anomalies} consecutive anomalies"
                )
        
        elif acc.state == ConvergenceState.REACQUIRE:
            # Reset and start over
            acc.count = 1
            acc.mean_ms = d_clock_ms
            acc.m2 = 0.0
            acc.consecutive_anomalies = 0
            acc.locked_mean_ms = None
            acc.locked_uncertainty_ms = None
            acc.state = ConvergenceState.ACQUIRING
        
        # Log state transitions
        if acc.state != prev_state:
            logger.info(f"State transition: {station} @ {frequency_mhz} MHz: {prev_state.value} → {acc.state.value}")
        
        # Calculate convergence progress (0 to 1)
        if acc.count < 10:
            progress = acc.count / 10 * 0.2  # 0-20% during acquiring
        elif acc.state == ConvergenceState.CONVERGING:
            # Progress based on uncertainty approaching lock threshold
            if acc.uncertainty_ms > self.lock_uncertainty_ms * 10:
                progress = 0.3
            else:
                progress = 0.3 + 0.6 * (1 - acc.uncertainty_ms / (self.lock_uncertainty_ms * 10))
        elif acc.state == ConvergenceState.LOCKED:
            progress = 1.0
        else:
            progress = 0.5
        
        # Persist state periodically
        if self.state_file and acc.count % 10 == 0:
            self._save_state()
        
        return ConvergenceResult(
            station=station,
            frequency_mhz=frequency_mhz,
            state=acc.state,
            d_clock_ms=acc.locked_mean_ms if acc.state == ConvergenceState.LOCKED else acc.mean_ms,
            uncertainty_ms=acc.locked_uncertainty_ms if acc.state == ConvergenceState.LOCKED else acc.uncertainty_ms,
            measurement_ms=d_clock_ms,
            residual_ms=residual_ms,
            sample_count=acc.count,
            convergence_progress=progress,
            is_locked=acc.state == ConvergenceState.LOCKED,
            is_anomaly=is_anomaly,
            anomaly_sigma=anomaly_sigma
        )
    
    def get_best_estimate(self) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        """
        Get the best current D_clock estimate across all stations.
        
        Returns:
        --------
        (d_clock_ms, uncertainty_ms, source) or (None, None, None)
        """
        best = None
        
        for key, acc in self.accumulators.items():
            if acc.count < 5:
                continue
            
            # Prefer locked estimates
            if acc.state == ConvergenceState.LOCKED:
                if best is None or acc.locked_uncertainty_ms < best[1]:
                    best = (acc.locked_mean_ms, acc.locked_uncertainty_ms, key)
            elif best is None or acc.uncertainty_ms < best[1]:
                if acc.uncertainty_ms != float('inf'):
                    best = (acc.mean_ms, acc.uncertainty_ms, key)
        
        if best:
            self.best_d_clock_ms, self.best_uncertainty_ms, self.best_source = best
            return best
        return (None, None, None)
    
    def get_status(self) -> dict:
        """Get full status of convergence model."""
        d_clock, uncertainty, source = self.get_best_estimate()
        
        locked_count = sum(1 for a in self.accumulators.values() 
                          if a.state == ConvergenceState.LOCKED)
        converging_count = sum(1 for a in self.accumulators.values() 
                              if a.state == ConvergenceState.CONVERGING)
        
        return {
            'best_d_clock_ms': d_clock,
            'best_uncertainty_ms': uncertainty,
            'best_source': source,
            'locked_stations': locked_count,
            'converging_stations': converging_count,
            'total_stations': len(self.accumulators),
            'stations': {
                key: {
                    'state': acc.state.value,
                    'count': acc.count,
                    'mean_ms': acc.mean_ms,
                    'uncertainty_ms': acc.uncertainty_ms if acc.uncertainty_ms != float('inf') else None,
                    'locked_mean_ms': acc.locked_mean_ms,
                    'locked_uncertainty_ms': acc.locked_uncertainty_ms,
                    'convergence_progress': acc.count / self.min_samples_for_lock if acc.count < self.min_samples_for_lock else 1.0
                }
                for key, acc in self.accumulators.items()
            }
        }
    
    def _save_state(self) -> None:
        """Persist state to file."""
        if not self.state_file:
            return
        
        state = {
            'version': 1,
            'timestamp': datetime.now().isoformat(),
            'accumulators': {
                key: acc.to_dict() 
                for key, acc in self.accumulators.items()
            }
        }
        
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save convergence state: {e}")
    
    def _load_state(self) -> None:
        """Load state from file."""
        if not self.state_file or not self.state_file.exists():
            return
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            for key, data in state.get('accumulators', {}).items():
                self.accumulators[key] = StationAccumulator.from_dict(data)
            
            logger.info(f"Loaded convergence state: {len(self.accumulators)} stations")
        except Exception as e:
            logger.warning(f"Failed to load convergence state: {e}")
