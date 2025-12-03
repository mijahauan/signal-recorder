#!/usr/bin/env python3
"""
Phase 2: Clock Offset Series (D_clock) - Analytical Engine

This module implements the Phase 2 analytical engine that reads the
immutable raw archive (Phase 1) and produces the Clock Offset Series.

The Clock Offset Series is:
$$D_{clock} = t_{system} - t_{UTC}$$

Where:
- t_system is the monotonic system time from Phase 1
- t_UTC is the true UTC time derived from WWV/WWVH/CHU radio signals

The D_clock product allows Phase 3 to apply time corrections and generate
UTC-aligned telemetry products.

Key Equations:
==============
1. Total Delay: $D_{total} = t_{RTP} - t_{UTC\_expected}$
2. Clock Offset: $D_{clock} = D_{total} - D_{prop}$

Where D_prop is the propagation delay from the TransmissionTimeSolver.

This module:
1. Reads raw 20 kHz IQ from Phase 1 archive
2. Detects synchronization tones (WWV, WWVH, CHU)
3. Performs WWV/WWVH discrimination
4. Calculates propagation delay using ionospheric modeling
5. Produces the Clock Offset Series as a separate, versionable file

Usage:
------
    engine = ClockOffsetEngine(
        raw_archive_dir=Path('/data/raw_archive'),
        output_dir=Path('/data/clock_offset'),
        channel_name='WWV_10MHz',
        receiver_grid='EM38ww'
    )
    
    # Process a time range
    results = engine.process_range(start_time, end_time)
    
    # Get D_clock for a specific time
    d_clock = engine.get_clock_offset(target_time)
"""

import numpy as np
import logging
import json
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any, NamedTuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class ClockOffsetQuality(Enum):
    """Quality grades for clock offset measurements."""
    EXCELLENT = "A"  # Sub-millisecond uncertainty, multi-station verified
    GOOD = "B"       # 1-2ms uncertainty, single station high confidence
    FAIR = "C"       # 2-5ms uncertainty, moderate confidence
    POOR = "D"       # >5ms uncertainty or low confidence
    INVALID = "X"    # No valid measurement


@dataclass
class ClockOffsetMeasurement:
    """
    A single clock offset measurement.
    
    This represents D_clock at a specific time, derived from tone detection
    and propagation delay calculation.
    """
    # Time reference
    system_time: float           # System time (t_system) from Phase 1
    utc_time: float              # Calculated UTC time (t_UTC)
    minute_boundary_utc: float   # UTC minute boundary this measurement relates to
    
    # The clock offset: D_clock = t_system - t_UTC
    clock_offset_ms: float       # Offset in milliseconds
    
    # Source identification
    station: str                 # 'WWV', 'WWVH', 'CHU', or 'COMBINED'
    frequency_mhz: float         # Carrier frequency
    
    # Propagation analysis
    propagation_delay_ms: float  # Calculated propagation delay
    propagation_mode: str        # '1F', '2F', 'GW', etc.
    n_hops: int                  # Number of ionospheric hops
    
    # Quality metrics
    confidence: float            # 0-1 confidence score
    uncertainty_ms: float        # Estimated uncertainty
    quality_grade: ClockOffsetQuality = ClockOffsetQuality.FAIR
    
    # Detection metrics (from tone detector)
    snr_db: float = 0.0
    delay_spread_ms: float = 0.0
    doppler_std_hz: float = 0.0
    fss_db: Optional[float] = None  # Frequency selectivity strength
    
    # Discrimination results
    wwv_power_db: Optional[float] = None
    wwvh_power_db: Optional[float] = None
    discrimination_confidence: str = 'low'
    
    # Verification
    utc_verified: bool = False   # True if emission offset < 2ms
    multi_station_verified: bool = False
    
    # Provenance
    archive_file: Optional[str] = None
    rtp_timestamp: Optional[int] = None
    processing_version: str = "1.0.0"
    processed_at: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d['quality_grade'] = self.quality_grade.value
        return d
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'ClockOffsetMeasurement':
        """Create from dictionary."""
        d = d.copy()
        if isinstance(d.get('quality_grade'), str):
            d['quality_grade'] = ClockOffsetQuality(d['quality_grade'])
        return cls(**d)


@dataclass
class ClockOffsetSeries:
    """
    The Clock Offset Series - a time-indexed collection of D_clock measurements.
    
    This is the primary output of Phase 2, providing the correction data
    needed by Phase 3 to generate UTC-aligned products.
    """
    channel_name: str
    frequency_hz: float
    receiver_grid: str
    
    # Series data
    measurements: List[ClockOffsetMeasurement] = field(default_factory=list)
    
    # Series metadata
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    version: str = "1.0.0"
    created_at: Optional[float] = None
    
    def add_measurement(self, measurement: ClockOffsetMeasurement):
        """Add a measurement to the series."""
        self.measurements.append(measurement)
        
        # Update bounds
        if self.start_time is None or measurement.system_time < self.start_time:
            self.start_time = measurement.system_time
        if self.end_time is None or measurement.system_time > self.end_time:
            self.end_time = measurement.system_time
    
    def get_offset_at_time(
        self,
        target_time: float,
        interpolate: bool = True
    ) -> Optional[Tuple[float, float]]:
        """
        Get the clock offset at a specific time.
        
        Args:
            target_time: System time to query
            interpolate: Whether to interpolate between measurements
            
        Returns:
            Tuple of (offset_ms, uncertainty_ms) or None if not available
        """
        if not self.measurements:
            return None
        
        # Sort by time
        sorted_meas = sorted(self.measurements, key=lambda m: m.system_time)
        
        # Find bracketing measurements
        before = None
        after = None
        
        for m in sorted_meas:
            if m.system_time <= target_time:
                before = m
            elif after is None:
                after = m
                break
        
        if before is None and after is None:
            return None
        
        if before is None:
            return (after.clock_offset_ms, after.uncertainty_ms)
        
        if after is None:
            return (before.clock_offset_ms, before.uncertainty_ms)
        
        if not interpolate:
            # Return nearest
            if abs(target_time - before.system_time) < abs(target_time - after.system_time):
                return (before.clock_offset_ms, before.uncertainty_ms)
            else:
                return (after.clock_offset_ms, after.uncertainty_ms)
        
        # Linear interpolation
        dt = after.system_time - before.system_time
        if dt <= 0:
            return (before.clock_offset_ms, before.uncertainty_ms)
        
        alpha = (target_time - before.system_time) / dt
        offset = before.clock_offset_ms + alpha * (after.clock_offset_ms - before.clock_offset_ms)
        uncertainty = max(before.uncertainty_ms, after.uncertainty_ms) * (1 + alpha * (1 - alpha))
        
        return (offset, uncertainty)
    
    def get_quality_summary(self) -> Dict[str, int]:
        """Get count of measurements by quality grade."""
        counts = {g.value: 0 for g in ClockOffsetQuality}
        for m in self.measurements:
            counts[m.quality_grade.value] += 1
        return counts
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'channel_name': self.channel_name,
            'frequency_hz': self.frequency_hz,
            'receiver_grid': self.receiver_grid,
            'measurements': [m.to_dict() for m in self.measurements],
            'start_time': self.start_time,
            'end_time': self.end_time,
            'version': self.version,
            'created_at': self.created_at,
            'quality_summary': self.get_quality_summary(),
            'measurement_count': len(self.measurements)
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'ClockOffsetSeries':
        """Create from dictionary."""
        series = cls(
            channel_name=d['channel_name'],
            frequency_hz=d['frequency_hz'],
            receiver_grid=d['receiver_grid'],
            start_time=d.get('start_time'),
            end_time=d.get('end_time'),
            version=d.get('version', '1.0.0'),
            created_at=d.get('created_at')
        )
        for m_dict in d.get('measurements', []):
            series.measurements.append(ClockOffsetMeasurement.from_dict(m_dict))
        return series


class ClockOffsetSeriesWriter:
    """
    Write Clock Offset Series to files.
    
    Supports multiple output formats:
    - JSON: Full structured data with all metadata
    - CSV: Tabular format for analysis tools
    - DRF metadata: Integration with Digital RF
    """
    
    def __init__(self, output_dir: Path, channel_name: str):
        """
        Initialize writer.
        
        Args:
            output_dir: Base output directory
            channel_name: Channel identifier
        """
        self.output_dir = Path(output_dir) / 'clock_offset' / channel_name.replace(' ', '_')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.channel_name = channel_name
        
        # CSV file for continuous logging
        self.csv_file = self.output_dir / 'clock_offset_series.csv'
        self._init_csv()
        
        logger.info(f"ClockOffsetSeriesWriter initialized: {self.output_dir}")
    
    def _init_csv(self):
        """Initialize CSV file with headers if needed."""
        if not self.csv_file.exists():
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'system_time', 'utc_time', 'minute_boundary_utc',
                    'clock_offset_ms', 'station', 'frequency_mhz',
                    'propagation_delay_ms', 'propagation_mode', 'n_hops',
                    'confidence', 'uncertainty_ms', 'quality_grade',
                    'snr_db', 'delay_spread_ms', 'doppler_std_hz', 'fss_db',
                    'wwv_power_db', 'wwvh_power_db', 'discrimination_confidence',
                    'utc_verified', 'multi_station_verified',
                    'rtp_timestamp', 'processed_at'
                ])
    
    def write_measurement(self, measurement: ClockOffsetMeasurement):
        """
        Write a single measurement to CSV.
        
        Args:
            measurement: ClockOffsetMeasurement to write
        """
        with open(self.csv_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                measurement.system_time,
                measurement.utc_time,
                measurement.minute_boundary_utc,
                measurement.clock_offset_ms,
                measurement.station,
                measurement.frequency_mhz,
                measurement.propagation_delay_ms,
                measurement.propagation_mode,
                measurement.n_hops,
                measurement.confidence,
                measurement.uncertainty_ms,
                measurement.quality_grade.value,
                measurement.snr_db,
                measurement.delay_spread_ms,
                measurement.doppler_std_hz,
                measurement.fss_db,
                measurement.wwv_power_db,
                measurement.wwvh_power_db,
                measurement.discrimination_confidence,
                measurement.utc_verified,
                measurement.multi_station_verified,
                measurement.rtp_timestamp,
                measurement.processed_at
            ])
    
    def write_series(self, series: ClockOffsetSeries, filename: Optional[str] = None):
        """
        Write complete series to JSON file.
        
        Args:
            series: ClockOffsetSeries to write
            filename: Optional filename (default: auto-generated)
        """
        if filename is None:
            # Generate filename from time range
            start_dt = datetime.fromtimestamp(series.start_time or 0, tz=timezone.utc)
            filename = f"clock_offset_{start_dt.strftime('%Y%m%d_%H%M%S')}.json"
        
        output_file = self.output_dir / filename
        with open(output_file, 'w') as f:
            json.dump(series.to_dict(), f, indent=2)
        
        logger.info(f"Clock offset series written: {output_file}")
    
    def load_series(self, filename: str) -> Optional[ClockOffsetSeries]:
        """
        Load a series from JSON file.
        
        Args:
            filename: Filename to load
            
        Returns:
            ClockOffsetSeries or None if not found
        """
        input_file = self.output_dir / filename
        if not input_file.exists():
            return None
        
        with open(input_file, 'r') as f:
            data = json.load(f)
        
        return ClockOffsetSeries.from_dict(data)


class ClockOffsetEngine:
    """
    Phase 2 Analytical Engine - Generate Clock Offset Series from Raw Archive.
    
    This engine:
    1. Reads raw 20 kHz IQ from Phase 1 archive
    2. Detects synchronization tones (WWV, WWVH, CHU)
    3. Performs WWV/WWVH discrimination for correct propagation calculation
    4. Uses TransmissionTimeSolver to back-calculate UTC(NIST)
    5. Produces the Clock Offset Series (D_clock)
    """
    
    def __init__(
        self,
        raw_archive_dir: Path,
        output_dir: Path,
        channel_name: str,
        frequency_hz: float,
        receiver_grid: str,
        sample_rate: int = 20000
    ):
        """
        Initialize the clock offset engine.
        
        Args:
            raw_archive_dir: Directory containing Phase 1 raw archive
            output_dir: Output directory for D_clock series
            channel_name: Channel identifier
            frequency_hz: Center frequency
            receiver_grid: Receiver grid square (for propagation calculation)
            sample_rate: Sample rate (default 20000)
        """
        self.raw_archive_dir = Path(raw_archive_dir)
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.receiver_grid = receiver_grid
        self.sample_rate = sample_rate
        
        # Initialize output writer
        self.writer = ClockOffsetSeriesWriter(output_dir, channel_name)
        
        # Current series
        self.current_series = ClockOffsetSeries(
            channel_name=channel_name,
            frequency_hz=frequency_hz,
            receiver_grid=receiver_grid,
            created_at=datetime.now(tz=timezone.utc).timestamp()
        )
        
        # Import required modules (lazy import to avoid circular deps)
        self._init_analyzers()
        
        # Processing state
        self._lock = threading.Lock()
        self.measurements_processed = 0
        
        logger.info(f"ClockOffsetEngine initialized for {channel_name}")
        logger.info(f"  Raw archive: {raw_archive_dir}")
        logger.info(f"  Output: {output_dir}")
        logger.info(f"  Receiver: {receiver_grid}")
    
    def _init_analyzers(self):
        """Initialize analysis components."""
        try:
            from .tone_detector import MultiStationToneDetector
            from .wwvh_discrimination import WWVHDiscriminator
            from .transmission_time_solver import (
                TransmissionTimeSolver,
                MultiStationSolver,
                create_solver_from_grid,
                create_multi_station_solver
            )
            from .raw_archive_writer import RawArchiveReader
            
            # Tone detector
            self.tone_detector = MultiStationToneDetector(
                channel_name=self.channel_name,
                sample_rate=3000  # Internal processing rate after decimation
            )
            
            # WWV/H discriminator
            self.discriminator = WWVHDiscriminator(
                channel_name=self.channel_name,
                receiver_grid=self.receiver_grid,
                sample_rate=self.sample_rate
            )
            
            # Transmission time solver for UTC back-calculation
            self.solver = create_solver_from_grid(self.receiver_grid, self.sample_rate)
            
            # Multi-station solver for combining WWV/WWVH/CHU
            self.multi_station_solver = create_multi_station_solver(
                self.receiver_grid,
                self.sample_rate
            )
            
            # Raw archive reader
            self.archive_reader = RawArchiveReader(
                self.raw_archive_dir,
                self.channel_name
            )
            
            logger.info("✅ All analyzers initialized")
            
        except ImportError as e:
            logger.error(f"Failed to initialize analyzers: {e}")
            raise
    
    def process_minute(
        self,
        iq_samples: np.ndarray,
        system_time: float,
        rtp_timestamp: int
    ) -> Optional[ClockOffsetMeasurement]:
        """
        Process one minute of IQ data to produce a clock offset measurement.
        
        This is the core analysis function that:
        1. Detects WWV/WWVH tones
        2. Discriminates between stations
        3. Calculates propagation delay
        4. Produces D_clock
        
        Args:
            iq_samples: Complex64 IQ samples (60 seconds at sample_rate)
            system_time: System time of first sample
            rtp_timestamp: RTP timestamp of first sample
            
        Returns:
            ClockOffsetMeasurement or None if no valid detection
        """
        from ..interfaces.data_models import StationType
        
        # Calculate expected minute boundary
        minute_boundary = (int(system_time) // 60) * 60
        
        # Step 1: Resample to 3 kHz for tone detection
        # (existing tone detector expects 3 kHz)
        decimation_factor = self.sample_rate // 3000
        iq_3k = iq_samples[::decimation_factor]
        
        # Step 2: Run tone detection
        try:
            detections = self.tone_detector.process_samples(
                timestamp=system_time,
                samples=iq_3k
            )
        except Exception as e:
            logger.warning(f"Tone detection failed: {e}")
            return None
        
        if not detections:
            logger.debug("No tones detected")
            return None
        
        # Step 3: Run discrimination to identify dominant station
        discrimination = self.discriminator.compute_discrimination(
            detections=detections,
            minute_timestamp=system_time
        )
        
        # Step 4: Get channel metrics from discrimination
        delay_spread_ms = getattr(discrimination, 'test_signal_delay_spread_ms', 0.5) or 0.5
        doppler_std_hz = getattr(discrimination, 'doppler_wwv_std_hz', 0.1) or 0.1
        fss_db = getattr(discrimination, 'test_signal_frequency_selectivity_db', None)
        
        # Step 5: Solve for transmission time using TransmissionTimeSolver
        # This is the "Holy Grail" - back-calculating UTC(NIST)
        best_detection = None
        best_confidence = 0
        
        for det in detections:
            if det.confidence > best_confidence:
                best_detection = det
                best_confidence = det.confidence
        
        if best_detection is None:
            return None
        
        # Determine station
        station = discrimination.dominant_station or 'UNKNOWN'
        if station == 'BALANCED':
            # Use detection's station
            station = best_detection.station.value if best_detection.station else 'WWV'
        
        # Map station name for solver
        solver_station = 'WWV' if station in ('WWV', 'UNKNOWN') else station
        if solver_station == 'WWVH':
            solver_station = 'WWVH'
        elif solver_station not in ('WWV', 'WWVH', 'CHU'):
            solver_station = 'WWV'
        
        # Calculate expected second boundary RTP
        # (tone should arrive shortly after the second boundary)
        expected_second_rtp = rtp_timestamp  # First sample of minute
        
        # Get arrival RTP from detection
        # timing_error_ms is offset from expected arrival
        arrival_offset_samples = int((best_detection.timing_error_ms or 0) * self.sample_rate / 1000)
        arrival_rtp = rtp_timestamp + arrival_offset_samples
        
        try:
            solver_result = self.solver.solve(
                station=solver_station,
                frequency_mhz=self.frequency_hz / 1e6,
                arrival_rtp=arrival_rtp,
                delay_spread_ms=delay_spread_ms,
                doppler_std_hz=doppler_std_hz,
                fss_db=fss_db,
                expected_second_rtp=expected_second_rtp
            )
        except Exception as e:
            logger.warning(f"TransmissionTimeSolver failed: {e}")
            return None
        
        # Step 6: Calculate D_clock
        # D_clock = t_system - t_UTC
        # emission_offset_ms is the offset from the second boundary
        # If emission_offset_ms ≈ 0, our clock is accurate
        # If positive, our clock is fast; if negative, our clock is slow
        
        # The solver gives us utc_nist_offset_ms which is the clock error
        clock_offset_ms = solver_result.utc_nist_offset_ms or solver_result.emission_offset_ms
        
        # Calculate actual UTC time
        utc_time = system_time - (clock_offset_ms / 1000.0)
        
        # Determine quality grade
        if solver_result.confidence > 0.8 and abs(clock_offset_ms) < 2:
            quality = ClockOffsetQuality.EXCELLENT
            uncertainty_ms = 0.5
        elif solver_result.confidence > 0.6 and abs(clock_offset_ms) < 5:
            quality = ClockOffsetQuality.GOOD
            uncertainty_ms = 1.5
        elif solver_result.confidence > 0.3:
            quality = ClockOffsetQuality.FAIR
            uncertainty_ms = 3.0
        else:
            quality = ClockOffsetQuality.POOR
            uncertainty_ms = 5.0
        
        # Create measurement
        measurement = ClockOffsetMeasurement(
            system_time=system_time,
            utc_time=utc_time,
            minute_boundary_utc=minute_boundary,
            clock_offset_ms=clock_offset_ms,
            station=station,
            frequency_mhz=self.frequency_hz / 1e6,
            propagation_delay_ms=solver_result.propagation_delay_ms,
            propagation_mode=solver_result.mode.value,
            n_hops=solver_result.n_hops,
            confidence=solver_result.confidence,
            uncertainty_ms=uncertainty_ms,
            quality_grade=quality,
            snr_db=best_detection.snr_db or 0.0,
            delay_spread_ms=delay_spread_ms,
            doppler_std_hz=doppler_std_hz,
            fss_db=fss_db,
            wwv_power_db=discrimination.wwv_power_db,
            wwvh_power_db=discrimination.wwvh_power_db,
            discrimination_confidence=discrimination.confidence,
            utc_verified=solver_result.utc_nist_verified,
            multi_station_verified=False,  # Set later if multi-station solving used
            rtp_timestamp=rtp_timestamp,
            processed_at=datetime.now(tz=timezone.utc).timestamp(),
            processing_version="2.0.0"
        )
        
        # Add to series and write to CSV
        with self._lock:
            self.current_series.add_measurement(measurement)
            self.writer.write_measurement(measurement)
            self.measurements_processed += 1
        
        logger.info(
            f"D_clock: {clock_offset_ms:+.2f}ms (station={station}, "
            f"mode={solver_result.mode.value}, confidence={solver_result.confidence:.2f})"
        )
        
        return measurement
    
    def process_archive_file(self, file_path: Path) -> List[ClockOffsetMeasurement]:
        """
        Process a raw archive file to extract clock offset measurements.
        
        Args:
            file_path: Path to raw archive file
            
        Returns:
            List of ClockOffsetMeasurement objects
        """
        # This would read from DRF files and process minute by minute
        # For now, this is a placeholder for the full implementation
        raise NotImplementedError("Archive file processing not yet implemented")
    
    def get_current_series(self) -> ClockOffsetSeries:
        """Get the current clock offset series."""
        with self._lock:
            return self.current_series
    
    def save_series(self):
        """Save the current series to disk."""
        with self._lock:
            self.writer.write_series(self.current_series)
            logger.info(f"Saved series with {len(self.current_series.measurements)} measurements")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        with self._lock:
            quality_summary = self.current_series.get_quality_summary()
            return {
                'measurements_processed': self.measurements_processed,
                'measurements_in_series': len(self.current_series.measurements),
                'quality_summary': quality_summary,
                'start_time': self.current_series.start_time,
                'end_time': self.current_series.end_time
            }


# Convenience function
def create_clock_offset_engine(
    raw_archive_dir: Path,
    output_dir: Path,
    channel_name: str,
    frequency_hz: float,
    receiver_grid: str,
    sample_rate: int = 20000
) -> ClockOffsetEngine:
    """
    Create a clock offset engine with standard configuration.
    
    Args:
        raw_archive_dir: Directory containing Phase 1 raw archive
        output_dir: Output directory for D_clock series
        channel_name: Channel identifier
        frequency_hz: Center frequency
        receiver_grid: Receiver grid square
        sample_rate: Sample rate
        
    Returns:
        Configured ClockOffsetEngine
    """
    return ClockOffsetEngine(
        raw_archive_dir=raw_archive_dir,
        output_dir=output_dir,
        channel_name=channel_name,
        frequency_hz=frequency_hz,
        receiver_grid=receiver_grid,
        sample_rate=sample_rate
    )
