#!/usr/bin/env python3
"""
Phase 3: Product Generation Engine - 10 Hz Decimated DRF with Timing Annotations

This module implements Phase 3 of the three-phase pipeline architecture:
1. Read 20 kHz raw IQ from Phase 1 (raw_archive/{CHANNEL}/)
2. Apply D_clock timing corrections from Phase 2 (phase2/{CHANNEL}/)
3. Decimate to 10 Hz with quality annotations
4. Write to products/{CHANNEL}/decimated/ for PSWS upload

Key Features:
=============
- **UTC(NIST) Corrected Timestamps**: Applies D_clock from Phase 2
- **Detailed Gap Analysis**: Documents data completeness per minute
- **Quality Annotations**: Embeds timing quality grades in metadata
- **PSWS Upload Compatible**: Matches wsprdaemon Digital RF format
- **Immutability Preserved**: Never modifies Phase 1 or Phase 2 data

Gap Analysis Metadata:
----------------------
For each minute of output, records:
- Gap count and total gap samples
- Data completeness percentage
- Largest single gap duration
- Gap locations (start sample, duration)
- Gap fill method (zeros, interpolated)

Output Structure:
-----------------
products/{CHANNEL}/
├── decimated/
│   └── {YYYYMMDD}/
│       └── {CALLSIGN}_{GRID}/
│           └── {RECEIVER}@{STATION_ID}_{INSTRUMENT_ID}/
│               └── OBS{YYYY-MM-DD}T{HH-MM}/
│                   └── ch0/
│                       ├── rf@{timestamp}.h5
│                       └── metadata/
│                           └── metadata.h5
├── gap_analysis/
│   └── {YYYYMMDD}_gaps.json
└── timing_annotations/
    └── {YYYYMMDD}_timing.csv

Usage:
------
    from grape_recorder.grape.phase3_product_engine import Phase3ProductEngine
    
    engine = Phase3ProductEngine(
        data_root='/tmp/grape-test',
        channel_name='WWV 10 MHz',
        station_config={
            'callsign': 'W3PM',
            'grid_square': 'EM38ww',
            'receiver_name': 'GRAPE',
            'psws_station_id': 'W3PM_1',
            'psws_instrument_id': '1'
        }
    )
    
    # Process a day's worth of data
    results = engine.process_day(date='2025-12-04')
    
    # Or process in real-time
    engine.process_minute(system_time=time.time())
"""

import numpy as np
import logging
import time
import uuid
import json
import csv
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Optional, Dict, List, Tuple, Any, NamedTuple
from dataclasses import dataclass, field
import threading

logger = logging.getLogger(__name__)

# Import TimingClient for D_clock from time-manager
try:
    from ..timing_client import TimingClient, ClockStatus
    TIMING_CLIENT_AVAILABLE = True
except ImportError:
    TIMING_CLIENT_AVAILABLE = False
    logger.warning("TimingClient not available - will use CSV fallback")

# Try to import Digital RF
try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    logger.warning("digital_rf not available - Phase 3 product generation disabled")


# =============================================================================
# Data Models for Phase 3
# =============================================================================

@dataclass
class GapInfo:
    """Information about a gap in the data stream."""
    start_sample: int           # Sample index where gap starts
    duration_samples: int       # Number of missing samples
    duration_ms: float          # Gap duration in milliseconds
    fill_method: str = 'zeros'  # How gap was filled: 'zeros', 'interpolated'
    
    def to_dict(self) -> Dict:
        return {
            'start_sample': self.start_sample,
            'duration_samples': self.duration_samples,
            'duration_ms': self.duration_ms,
            'fill_method': self.fill_method
        }


@dataclass
class GapAnalysis:
    """Complete gap analysis for a minute of data."""
    minute_boundary_utc: float
    total_samples: int
    valid_samples: int
    gap_samples: int
    gap_count: int
    gaps: List[GapInfo] = field(default_factory=list)
    
    # Derived metrics
    completeness_pct: float = 100.0
    largest_gap_ms: float = 0.0
    data_quality: str = 'complete'  # complete, minor_gaps, major_gaps, unusable
    
    def __post_init__(self):
        if self.total_samples > 0:
            self.completeness_pct = (self.valid_samples / self.total_samples) * 100.0
        
        if self.gaps:
            self.largest_gap_ms = max(g.duration_ms for g in self.gaps)
        
        # Classify data quality
        if self.completeness_pct >= 99.9:
            self.data_quality = 'complete'
        elif self.completeness_pct >= 95.0:
            self.data_quality = 'minor_gaps'
        elif self.completeness_pct >= 80.0:
            self.data_quality = 'major_gaps'
        else:
            self.data_quality = 'unusable'
    
    def to_dict(self) -> Dict:
        return {
            'minute_boundary_utc': self.minute_boundary_utc,
            'total_samples': self.total_samples,
            'valid_samples': self.valid_samples,
            'gap_samples': self.gap_samples,
            'gap_count': self.gap_count,
            'completeness_pct': self.completeness_pct,
            'largest_gap_ms': self.largest_gap_ms,
            'data_quality': self.data_quality,
            'gaps': [g.to_dict() for g in self.gaps]
        }


@dataclass
class TimingAnnotation:
    """Timing quality annotation for output metadata."""
    system_time: float              # Original system time from Phase 1
    utc_time: float                 # Corrected UTC time (after D_clock)
    d_clock_ms: float               # Applied D_clock correction
    uncertainty_ms: float           # Timing uncertainty
    quality_grade: str              # 'A', 'B', 'C', 'D', 'X'
    station: str                    # Station used: 'WWV', 'WWVH', 'CHU'
    propagation_mode: str           # '1F', '2F', etc.
    anchor_confidence: float        # Confidence in timing anchor
    
    def to_dict(self) -> Dict:
        return {
            'system_time': self.system_time,
            'utc_time': self.utc_time,
            'd_clock_ms': self.d_clock_ms,
            'uncertainty_ms': self.uncertainty_ms,
            'quality_grade': self.quality_grade,
            'station': self.station,
            'propagation_mode': self.propagation_mode,
            'anchor_confidence': self.anchor_confidence
        }


@dataclass
class Phase3Config:
    """Configuration for Phase 3 product engine."""
    data_root: Path
    channel_name: str
    frequency_hz: float
    station_config: Dict[str, Any]
    
    # Processing parameters
    input_sample_rate: int = 20000   # Phase 1 raw archive rate
    output_sample_rate: int = 10     # Final product rate
    
    # DRF output parameters (wsprdaemon compatible)
    subdir_cadence_secs: int = 86400     # Daily subdirectories
    file_cadence_millisecs: int = 3600000  # Hourly files
    compression_level: int = 9
    
    # Gap handling
    max_gap_fill_ms: float = 1000.0  # Max gap to fill with zeros (1 sec)
    interpolate_small_gaps: bool = False  # Interpolate gaps < 10 samples
    
    def __post_init__(self):
        self.data_root = Path(self.data_root)


class Phase3ProductEngine:
    """
    Phase 3: Product Generation Engine
    
    Transforms Phase 1 raw archive + Phase 2 timing analysis into
    corrected 10 Hz Digital RF products for PSWS upload.
    """
    
    def __init__(self, config: Phase3Config):
        """
        Initialize Phase 3 Product Engine.
        
        Args:
            config: Phase3Config with all settings
        """
        if not DRF_AVAILABLE:
            raise ImportError(
                "digital_rf package required for Phase 3 product generation. "
                "Install with: pip install digital_rf"
            )
        
        self.config = config
        self._lock = threading.Lock()
        
        # Initialize path manager
        from ..paths import GRAPEPaths
        self.paths = GRAPEPaths(config.data_root)
        
        # Create output directories
        self.decimated_dir = self.paths.get_decimated_dir(config.channel_name)
        self.decimated_dir.mkdir(parents=True, exist_ok=True)
        
        # Gap analysis output
        gap_dir = self.paths.get_products_dir(config.channel_name) / 'gap_analysis'
        gap_dir.mkdir(parents=True, exist_ok=True)
        self.gap_analysis_dir = gap_dir
        
        # Timing annotations output
        timing_dir = self.paths.get_products_dir(config.channel_name) / 'timing_annotations'
        timing_dir.mkdir(parents=True, exist_ok=True)
        self.timing_dir = timing_dir
        
        # Initialize Phase 1 reader
        self._init_phase1_reader()
        
        # Initialize decimator
        self._init_decimator()
        
        # DRF writer state
        self.drf_writer: Optional[drf.DigitalRFWriter] = None
        self.metadata_writer: Optional[drf.DigitalMetadataWriter] = None
        self.dataset_uuid = uuid.uuid4().hex
        self.current_day: Optional[date] = None
        self.next_sample_index: Optional[int] = None
        
        # Processing state
        self.samples_written = 0
        self.minutes_processed = 0
        self.gaps_detected = 0
        self.start_time = time.time()
        
        # Collected gap analyses for batch writing
        self.gap_analyses: List[GapAnalysis] = []
        self.timing_annotations: List[TimingAnnotation] = []
        
        # Initialize TimingClient for real-time D_clock from time-manager
        self.timing_client: Optional[TimingClient] = None
        if TIMING_CLIENT_AVAILABLE:
            try:
                self.timing_client = TimingClient()
                if self.timing_client.available:
                    logger.info("  TimingClient: connected to time-manager")
                else:
                    logger.info("  TimingClient: time-manager not running (will use CSV fallback)")
            except Exception as e:
                logger.warning(f"  TimingClient init failed: {e}")
        
        logger.info(f"Phase3ProductEngine initialized for {config.channel_name}")
        logger.info(f"  Data root: {config.data_root}")
        logger.info(f"  Decimation: {config.input_sample_rate} Hz → {config.output_sample_rate} Hz")
        logger.info(f"  Output: {self.decimated_dir}")
    
    def _init_phase1_reader(self):
        """Initialize Phase 1 raw archive reader."""
        raw_archive_dir = self.paths.get_raw_archive_dir(self.config.channel_name)
        
        if not raw_archive_dir.exists():
            logger.warning(f"Phase 1 raw archive not found: {raw_archive_dir}")
            self.phase1_reader = None
            return
        
        try:
            # Use Digital RF reader for Phase 1 data
            self.phase1_reader = drf.DigitalRFReader(str(raw_archive_dir))
            bounds = self.phase1_reader.get_bounds()
            if bounds[0] is not None:
                logger.info(f"  Phase 1 archive: {bounds[1] - bounds[0]} samples available")
        except Exception as e:
            logger.warning(f"Could not open Phase 1 archive: {e}")
            self.phase1_reader = None
    
    def _init_decimator(self):
        """Initialize decimation filter."""
        from .decimation import get_decimator
        
        self.decimator = get_decimator(
            self.config.input_sample_rate,
            self.config.output_sample_rate
        )
        self.decimation_factor = self.config.input_sample_rate // self.config.output_sample_rate
        
        logger.info(f"  Decimation factor: {self.decimation_factor}")
    
    def load_phase2_result(self, system_time: float) -> Optional[Dict]:
        """
        Load timing result for a specific minute.
        
        Priority:
        1. TimingClient (real-time from time-manager SHM) - for current minute
        2. CSV files (historical data) - for reprocessing past data
        
        Args:
            system_time: System time of the minute to load
            
        Returns:
            Timing result dict or None if not available
        """
        # Try TimingClient first for recent data (within 2 minutes)
        if self.timing_client and self.timing_client.available:
            age = time.time() - system_time
            if age < 120:  # Within 2 minutes - use live timing
                result = self._load_from_timing_client()
                if result:
                    return result
        
        # Fall back to CSV for historical data
        # Calculate minute boundary
        minute_boundary = int(system_time / 60) * 60
        
        # Look for Phase 2 clock offset file
        clock_offset_dir = self.paths.get_clock_offset_dir(self.config.channel_name)
        
        # Try to load from CSV
        date_str = datetime.fromtimestamp(minute_boundary, tz=timezone.utc).strftime('%Y%m%d')
        csv_file = clock_offset_dir / f'{date_str}_clock_offset.csv'
        
        if csv_file.exists():
            return self._load_phase2_from_csv(csv_file, minute_boundary)
        
        # Also try legacy location
        csv_file = clock_offset_dir / 'clock_offset_series.csv'
        if csv_file.exists():
            return self._load_phase2_from_csv(csv_file, minute_boundary)
        
        return None
    
    def _load_from_timing_client(self) -> Optional[Dict]:
        """
        Load timing from time-manager via TimingClient.
        
        Returns:
            Timing result dict or None if not available
        """
        if not self.timing_client:
            return None
        
        try:
            # Get channel-specific timing if available
            channel_timing = self.timing_client.get_channel_timing(self.config.channel_name)
            
            if channel_timing:
                # Use channel-specific data
                d_clock, uncertainty = self.timing_client.get_d_clock_with_uncertainty()
                
                return {
                    'd_clock_ms': d_clock if d_clock is not None else 0.0,
                    'uncertainty_ms': uncertainty if uncertainty is not None else 999.0,
                    'quality_grade': self._status_to_grade(self.timing_client.get_clock_status()),
                    'station': channel_timing.station,
                    'propagation_mode': channel_timing.propagation_mode,
                    'confidence': 0.9 if channel_timing.confidence == 'high' else 0.5
                }
            else:
                # Use fused D_clock (global)
                d_clock, uncertainty = self.timing_client.get_d_clock_with_uncertainty()
                
                if d_clock is None:
                    return None
                
                return {
                    'd_clock_ms': d_clock,
                    'uncertainty_ms': uncertainty if uncertainty is not None else 999.0,
                    'quality_grade': self._status_to_grade(self.timing_client.get_clock_status()),
                    'station': 'FUSED',  # Multi-station fusion
                    'propagation_mode': 'FUSED',
                    'confidence': 0.8
                }
                
        except Exception as e:
            logger.warning(f"TimingClient error: {e}")
            return None
    
    def _status_to_grade(self, status) -> str:
        """Convert ClockStatus to quality grade."""
        if not TIMING_CLIENT_AVAILABLE:
            return 'X'
        
        grade_map = {
            ClockStatus.LOCKED: 'A',
            ClockStatus.HOLDOVER: 'B',
            ClockStatus.ACQUIRING: 'C',
            ClockStatus.UNLOCKED: 'D',
            ClockStatus.UNAVAILABLE: 'X',
        }
        return grade_map.get(status, 'X')
    
    def _load_phase2_from_csv(self, csv_file: Path, minute_boundary: float) -> Optional[Dict]:
        """Load specific minute's Phase 2 result from CSV (for historical data)."""
        try:
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_time = float(row.get('system_time', 0))
                    if abs(row_time - minute_boundary) < 30:  # Within 30 seconds
                        return {
                            'd_clock_ms': float(row.get('clock_offset_ms', 0)),
                            'uncertainty_ms': float(row.get('uncertainty_ms', 999)),
                            'quality_grade': row.get('quality_grade', 'X'),
                            'station': row.get('station', 'UNKNOWN'),
                            'propagation_mode': row.get('propagation_mode', 'UNKNOWN'),
                            'confidence': float(row.get('confidence', 0))
                        }
        except Exception as e:
            logger.warning(f"Error loading Phase 2 CSV: {e}")
        
        return None
    
    def read_phase1_minute(
        self, 
        system_time: float
    ) -> Tuple[Optional[np.ndarray], GapAnalysis]:
        """
        Read one minute of Phase 1 raw archive data.
        
        Args:
            system_time: System time of minute start
            
        Returns:
            Tuple of (samples, gap_analysis)
        """
        samples_per_minute = self.config.input_sample_rate * 60
        minute_boundary = int(system_time / 60) * 60
        
        # Calculate global sample index
        start_index = int(system_time * self.config.input_sample_rate)
        end_index = start_index + samples_per_minute
        
        if self.phase1_reader is None:
            # Return empty data with full gap
            gap_analysis = GapAnalysis(
                minute_boundary_utc=minute_boundary,
                total_samples=samples_per_minute,
                valid_samples=0,
                gap_samples=samples_per_minute,
                gap_count=1,
                gaps=[GapInfo(
                    start_sample=0,
                    duration_samples=samples_per_minute,
                    duration_ms=(samples_per_minute / self.config.input_sample_rate) * 1000,
                    fill_method='zeros'
                )]
            )
            return None, gap_analysis
        
        try:
            # Get channel name for DRF reader
            channels = self.phase1_reader.get_channels()
            if not channels:
                logger.warning("No channels in Phase 1 archive")
                return None, self._create_empty_gap_analysis(minute_boundary, samples_per_minute)
            
            channel = channels[0]
            
            # Read samples (DRF uses start_index, num_samples, channel)
            samples = self.phase1_reader.read_vector(
                start_index,
                samples_per_minute,
                channel
            )
            
            if samples is None or len(samples) == 0:
                return None, self._create_empty_gap_analysis(minute_boundary, samples_per_minute)
            
            # Analyze gaps in the data
            gap_analysis = self._analyze_gaps(
                samples=samples,
                minute_boundary_utc=minute_boundary,
                expected_samples=samples_per_minute
            )
            
            return samples.astype(np.complex64), gap_analysis
            
        except Exception as e:
            logger.warning(f"Error reading Phase 1 archive at {system_time}: {e}")
            return None, self._create_empty_gap_analysis(minute_boundary, samples_per_minute)
    
    def _create_empty_gap_analysis(
        self, 
        minute_boundary: float, 
        samples_per_minute: int
    ) -> GapAnalysis:
        """Create gap analysis for missing minute."""
        return GapAnalysis(
            minute_boundary_utc=minute_boundary,
            total_samples=samples_per_minute,
            valid_samples=0,
            gap_samples=samples_per_minute,
            gap_count=1,
            gaps=[GapInfo(
                start_sample=0,
                duration_samples=samples_per_minute,
                duration_ms=(samples_per_minute / self.config.input_sample_rate) * 1000,
                fill_method='zeros'
            )]
        )
    
    def _analyze_gaps(
        self,
        samples: np.ndarray,
        minute_boundary_utc: float,
        expected_samples: int
    ) -> GapAnalysis:
        """
        Analyze gaps in Phase 1 data.
        
        Gaps are detected as:
        - Zero-valued sequences (from gap fill in Phase 1)
        - Missing samples if array is shorter than expected
        """
        gaps = []
        gap_samples_total = 0
        
        # Check for zero sequences (gap fills from Phase 1)
        # A gap is defined as >= 10 consecutive zero samples
        min_gap_samples = 10
        
        zero_mask = (samples.real == 0) & (samples.imag == 0)
        in_gap = False
        gap_start = 0
        
        for i, is_zero in enumerate(zero_mask):
            if is_zero and not in_gap:
                gap_start = i
                in_gap = True
            elif not is_zero and in_gap:
                gap_length = i - gap_start
                if gap_length >= min_gap_samples:
                    gap_duration_ms = (gap_length / self.config.input_sample_rate) * 1000
                    gaps.append(GapInfo(
                        start_sample=gap_start,
                        duration_samples=gap_length,
                        duration_ms=gap_duration_ms,
                        fill_method='zeros'
                    ))
                    gap_samples_total += gap_length
                in_gap = False
        
        # Handle trailing gap
        if in_gap:
            gap_length = len(samples) - gap_start
            if gap_length >= min_gap_samples:
                gap_duration_ms = (gap_length / self.config.input_sample_rate) * 1000
                gaps.append(GapInfo(
                    start_sample=gap_start,
                    duration_samples=gap_length,
                    duration_ms=gap_duration_ms,
                    fill_method='zeros'
                ))
                gap_samples_total += gap_length
        
        # Check for missing samples at end
        if len(samples) < expected_samples:
            missing = expected_samples - len(samples)
            gaps.append(GapInfo(
                start_sample=len(samples),
                duration_samples=missing,
                duration_ms=(missing / self.config.input_sample_rate) * 1000,
                fill_method='zeros'
            ))
            gap_samples_total += missing
        
        return GapAnalysis(
            minute_boundary_utc=minute_boundary_utc,
            total_samples=expected_samples,
            valid_samples=expected_samples - gap_samples_total,
            gap_samples=gap_samples_total,
            gap_count=len(gaps),
            gaps=gaps
        )
    
    def _create_drf_writer(self, utc_timestamp: float):
        """Create Digital RF writer for output products."""
        dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
        day_date = dt.date()
        
        # Close existing writer if day changed
        if self.current_day and self.current_day != day_date:
            logger.info("Day boundary: closing previous DRF writer")
            self._close_writer()
        
        if self.drf_writer is not None:
            return
        
        # Build PSWS-compatible directory structure
        station = self.config.station_config
        date_str = day_date.strftime('%Y%m%d')
        
        callsign = station.get('callsign', 'UNKNOWN')
        grid = station.get('grid_square', 'UNKNOWN')
        receiver_name = station.get('receiver_name', 'GRAPE')
        psws_station_id = station.get('psws_station_id', 'UNKNOWN')
        psws_instrument_id = station.get('psws_instrument_id', '1')
        
        receiver_info = f"{receiver_name}@{psws_station_id}_{psws_instrument_id}"
        obs_timestamp = dt.strftime('OBS%Y-%m-%dT%H-%M')
        
        drf_dir = (
            self.decimated_dir / date_str / f"{callsign}_{grid}" /
            receiver_info / obs_timestamp / 'ch0'
        )
        drf_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate start_global_index from UTC timestamp
        start_global_index = int(utc_timestamp * self.config.output_sample_rate)
        
        if self.next_sample_index is None:
            self.next_sample_index = start_global_index
        
        logger.info(f"Creating Phase 3 DRF writer for {day_date}")
        logger.info(f"  Directory: {drf_dir}")
        logger.info(f"  start_global_index: {start_global_index}")
        
        # Create Digital RF writer (wsprdaemon compatible format)
        self.drf_writer = drf.DigitalRFWriter(
            str(drf_dir),
            dtype=np.float32,  # float32 (N, 2) for wsprdaemon compatibility
            subdir_cadence_secs=self.config.subdir_cadence_secs,
            file_cadence_millisecs=self.config.file_cadence_millisecs,
            start_global_index=start_global_index,
            sample_rate_numerator=self.config.output_sample_rate,
            sample_rate_denominator=1,
            uuid_str=self.dataset_uuid,
            compression_level=self.config.compression_level,
            checksum=False,
            is_complex=True,
            num_subchannels=1,
            is_continuous=True,
            marching_periods=False
        )
        
        # Create metadata writer
        metadata_dir = drf_dir / 'metadata'
        metadata_dir.mkdir(parents=True, exist_ok=True)
        
        self.metadata_writer = drf.DigitalMetadataWriter(
            str(metadata_dir),
            subdir_cadence_secs=self.config.subdir_cadence_secs,
            file_cadence_secs=86400,
            sample_rate_numerator=self.config.output_sample_rate,
            sample_rate_denominator=1,
            file_name='metadata'
        )
        
        # Write initial metadata (PSWS compatible)
        metadata = {
            'product_type': 'phase3_decimated_10hz',
            'time_reference': 'utc_nist_corrected',
            'clock_offset_applied': True,
            'callsign': callsign,
            'grid_square': grid,
            'receiver_name': receiver_name,
            'center_frequencies': np.array([self.config.frequency_hz], dtype=np.float64),
            'uuid_str': self.dataset_uuid,
            'sample_rate': float(self.config.output_sample_rate),
            'date': day_date.isoformat(),
            'created_at': datetime.now(tz=timezone.utc).isoformat(),
            'source_archive_type': 'phase1_raw_20khz',
            'decimation_factor': self.decimation_factor,
            'pipeline_version': '3.0.0'
        }
        self.metadata_writer.write(start_global_index, metadata)
        
        self.current_day = day_date
        logger.info("✅ Phase 3 DRF writer ready")
    
    def _close_writer(self):
        """Close DRF writer."""
        if self.drf_writer:
            try:
                self.drf_writer.close()
            except Exception as e:
                logger.warning(f"Error closing DRF writer: {e}")
            self.drf_writer = None
            self.metadata_writer = None
    
    def _write_minute_metadata(
        self,
        sample_index: int,
        gap_analysis: GapAnalysis,
        timing_annotation: TimingAnnotation,
        station: str,
        d_clock_ms: float,
        quality_grade: str
    ):
        """
        Write per-minute metadata to DRF metadata file.
        
        This embeds gap and timing information directly in the HDF5 metadata
        for PSWS upload compatibility.
        """
        if not self.metadata_writer:
            return
        
        try:
            # Build gap intervals as numpy arrays for HDF5 storage
            gap_starts = np.array([g.start_sample for g in gap_analysis.gaps], dtype=np.int64)
            gap_durations = np.array([g.duration_samples for g in gap_analysis.gaps], dtype=np.int64)
            
            minute_metadata = {
                # Timing annotations
                'd_clock_ms': np.float32(d_clock_ms),
                'd_clock_uncertainty_ms': np.float32(timing_annotation.uncertainty_ms),
                'quality_grade': quality_grade,
                'station': station,
                'propagation_mode': timing_annotation.propagation_mode,
                
                # Gap annotations
                'gap_count': np.int32(gap_analysis.gap_count),
                'gap_samples_total': np.int64(gap_analysis.gap_samples),
                'completeness_pct': np.float32(gap_analysis.completeness_pct),
                'data_quality': gap_analysis.data_quality,
                
                # Gap intervals (for sample-accurate gap locations)
                'gap_start_samples': gap_starts if len(gap_starts) > 0 else np.array([], dtype=np.int64),
                'gap_duration_samples': gap_durations if len(gap_durations) > 0 else np.array([], dtype=np.int64),
                
                # Source tracking
                'system_time': np.float64(timing_annotation.system_time),
                'utc_time': np.float64(timing_annotation.utc_time),
            }
            
            self.metadata_writer.write(sample_index, minute_metadata)
            
        except Exception as e:
            logger.warning(f"Failed to write minute metadata: {e}")
    
    def process_minute(
        self,
        system_time: float,
        raw_samples: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        Process one minute of data into Phase 3 product.
        
        Args:
            system_time: System time of minute start
            raw_samples: Optional raw samples (if None, reads from Phase 1)
            
        Returns:
            Processing result dict
        """
        result = {
            'system_time': system_time,
            'samples_written': 0,
            'success': False
        }
        
        # Step 1: Load Phase 2 timing analysis
        phase2_result = self.load_phase2_result(system_time)
        
        if phase2_result:
            d_clock_ms = phase2_result['d_clock_ms']
            uncertainty_ms = phase2_result['uncertainty_ms']
            quality_grade = phase2_result['quality_grade']
            station = phase2_result['station']
            propagation_mode = phase2_result['propagation_mode']
            confidence = phase2_result['confidence']
        else:
            # No Phase 2 data - use 0 correction with high uncertainty
            d_clock_ms = 0.0
            uncertainty_ms = 999.0
            quality_grade = 'X'
            station = 'UNKNOWN'
            propagation_mode = 'UNKNOWN'
            confidence = 0.0
        
        result['d_clock_ms'] = d_clock_ms
        result['quality_grade'] = quality_grade
        
        # Step 2: Calculate corrected UTC time
        utc_timestamp = system_time - (d_clock_ms / 1000.0)
        result['utc_time'] = utc_timestamp
        
        # Step 3: Read Phase 1 data (if not provided)
        if raw_samples is None:
            raw_samples, gap_analysis = self.read_phase1_minute(system_time)
        else:
            # Analyze provided samples
            samples_per_minute = self.config.input_sample_rate * 60
            minute_boundary = int(system_time / 60) * 60
            gap_analysis = self._analyze_gaps(raw_samples, minute_boundary, samples_per_minute)
        
        result['gap_analysis'] = gap_analysis.to_dict()
        self.gap_analyses.append(gap_analysis)
        self.gaps_detected += gap_analysis.gap_count
        
        if raw_samples is None or len(raw_samples) == 0:
            logger.warning(f"No Phase 1 data available at {system_time}")
            return result
        
        # Step 4: Create timing annotation
        annotation = TimingAnnotation(
            system_time=system_time,
            utc_time=utc_timestamp,
            d_clock_ms=d_clock_ms,
            uncertainty_ms=uncertainty_ms,
            quality_grade=quality_grade,
            station=station,
            propagation_mode=propagation_mode,
            anchor_confidence=confidence
        )
        self.timing_annotations.append(annotation)
        
        # Step 5: Ensure DRF writer exists
        self._create_drf_writer(utc_timestamp)
        
        if self.drf_writer is None:
            logger.error("Failed to create DRF writer")
            return result
        
        # Step 6: Decimate raw samples
        try:
            decimated = self.decimator(raw_samples)
        except Exception as e:
            logger.error(f"Decimation failed: {e}")
            return result
        
        if decimated is None or len(decimated) == 0:
            logger.warning("Decimation produced no output")
            return result
        
        # Step 7: Convert to float32 (N, 2) format for wsprdaemon compatibility
        iq_complex = decimated.astype(np.complex64)
        iq_float = np.zeros((len(iq_complex), 2), dtype=np.float32)
        iq_float[:, 0] = iq_complex.real
        iq_float[:, 1] = iq_complex.imag
        
        # Step 8: Calculate sample index and check monotonicity
        calculated_index = int(utc_timestamp * self.config.output_sample_rate)
        
        if self.next_sample_index is not None and calculated_index < self.next_sample_index:
            logger.warning(
                f"Time correction caused backwards jump: "
                f"calculated={calculated_index} < next={self.next_sample_index}. "
                f"Skipping to maintain monotonic sequence."
            )
            return result
        
        # Step 9: Write to DRF
        try:
            self.drf_writer.rf_write(iq_float)
            self.samples_written += len(decimated)
            self.next_sample_index = calculated_index + len(decimated)
            self.minutes_processed += 1
            
            result['samples_written'] = len(decimated)
            result['success'] = True
            
            # Step 10: Write per-minute metadata with gap and timing annotations
            if self.metadata_writer:
                self._write_minute_metadata(
                    sample_index=calculated_index,
                    gap_analysis=gap_analysis,
                    timing_annotation=annotation,
                    station=station,
                    d_clock_ms=d_clock_ms,
                    quality_grade=quality_grade
                )
            
            logger.debug(
                f"Phase 3: Wrote {len(decimated)} samples at UTC={utc_timestamp:.3f} "
                f"(D_clock={d_clock_ms:+.2f}ms, grade={quality_grade})"
            )
            
        except Exception as e:
            logger.error(f"DRF write error: {e}")
        
        return result
    
    def process_day(
        self,
        date_str: str,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Process a full day's data from Phase 1 to Phase 3.
        
        Args:
            date_str: Date in YYYYMMDD or YYYY-MM-DD format
            progress_callback: Optional callback(minute_num, total_minutes)
            
        Returns:
            Processing results summary
        """
        # Parse date
        if '-' in date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.strptime(date_str, '%Y%m%d').date()
        
        # Calculate time range (full day in UTC)
        start_dt = datetime(target_date.year, target_date.month, target_date.day, 
                           0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(target_date.year, target_date.month, target_date.day,
                         23, 59, 59, tzinfo=timezone.utc)
        
        start_time = start_dt.timestamp()
        end_time = end_dt.timestamp()
        
        results = {
            'date': target_date.isoformat(),
            'start_time': start_time,
            'end_time': end_time,
            'minutes_processed': 0,
            'samples_written': 0,
            'gaps_detected': 0,
            'quality_grades': {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'X': 0},
            'errors': []
        }
        
        total_minutes = 1440  # 24 * 60
        
        logger.info(f"Processing {target_date} for {self.config.channel_name}")
        logger.info(f"  Total minutes: {total_minutes}")
        
        current_time = start_time
        minute_num = 0
        
        while current_time < end_time:
            try:
                result = self.process_minute(current_time)
                
                results['samples_written'] += result.get('samples_written', 0)
                if result.get('success'):
                    results['minutes_processed'] += 1
                
                grade = result.get('quality_grade', 'X')
                results['quality_grades'][grade] = results['quality_grades'].get(grade, 0) + 1
                
            except Exception as e:
                logger.error(f"Error processing minute at {current_time}: {e}")
                results['errors'].append(str(e))
            
            minute_num += 1
            if progress_callback:
                progress_callback(minute_num, total_minutes)
            
            current_time += 60
        
        # Finalize
        self._close_writer()
        self._write_gap_analysis(target_date)
        self._write_timing_annotations(target_date)
        
        results['gaps_detected'] = self.gaps_detected
        
        logger.info(f"✅ Day processing complete: {results['minutes_processed']} minutes, "
                   f"{results['samples_written']} samples")
        
        return results
    
    def _write_gap_analysis(self, target_date: date):
        """Write gap analysis JSON for the day."""
        if not self.gap_analyses:
            return
        
        output_file = self.gap_analysis_dir / f'{target_date.strftime("%Y%m%d")}_gaps.json'
        
        analysis_data = {
            'date': target_date.isoformat(),
            'channel_name': self.config.channel_name,
            'total_minutes': len(self.gap_analyses),
            'complete_minutes': sum(1 for g in self.gap_analyses if g.data_quality == 'complete'),
            'minutes_with_gaps': sum(1 for g in self.gap_analyses if g.gap_count > 0),
            'total_gap_samples': sum(g.gap_samples for g in self.gap_analyses),
            'overall_completeness_pct': (
                sum(g.valid_samples for g in self.gap_analyses) /
                sum(g.total_samples for g in self.gap_analyses) * 100
                if self.gap_analyses else 0
            ),
            'minutes': [g.to_dict() for g in self.gap_analyses]
        }
        
        with open(output_file, 'w') as f:
            json.dump(analysis_data, f, indent=2)
        
        logger.info(f"Gap analysis written to {output_file}")
        self.gap_analyses.clear()
    
    def _write_timing_annotations(self, target_date: date):
        """Write timing annotations CSV for the day."""
        if not self.timing_annotations:
            return
        
        output_file = self.timing_dir / f'{target_date.strftime("%Y%m%d")}_timing.csv'
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'system_time', 'utc_time', 'd_clock_ms', 'uncertainty_ms',
                'quality_grade', 'station', 'propagation_mode', 'anchor_confidence'
            ])
            writer.writeheader()
            for ann in self.timing_annotations:
                writer.writerow(ann.to_dict())
        
        logger.info(f"Timing annotations written to {output_file}")
        self.timing_annotations.clear()
    
    def close(self):
        """Close engine and finalize outputs."""
        with self._lock:
            self._close_writer()
            
            # Write any remaining gap analyses
            if self.gap_analyses:
                today = date.today()
                self._write_gap_analysis(today)
            
            if self.timing_annotations:
                today = date.today()
                self._write_timing_annotations(today)
        
        self._write_session_summary()
    
    def _write_session_summary(self):
        """Write session summary."""
        summary = {
            'product_type': 'phase3_decimated_10hz',
            'channel_name': self.config.channel_name,
            'frequency_hz': self.config.frequency_hz,
            'output_sample_rate': self.config.output_sample_rate,
            'samples_written': self.samples_written,
            'minutes_processed': self.minutes_processed,
            'gaps_detected': self.gaps_detected,
            'processing_time_sec': time.time() - self.start_time,
            'created_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
        summary_file = self.paths.get_products_dir(self.config.channel_name) / 'phase3_session_summary.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Session summary written to {summary_file}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            'samples_written': self.samples_written,
            'minutes_processed': self.minutes_processed,
            'gaps_detected': self.gaps_detected,
            'current_day': self.current_day.isoformat() if self.current_day else None,
            'uptime_seconds': time.time() - self.start_time,
            'output_dir': str(self.decimated_dir)
        }


# =============================================================================
# Factory Functions
# =============================================================================

def create_phase3_engine(
    data_root: Path,
    channel_name: str,
    frequency_hz: float,
    station_config: Dict[str, Any]
) -> Phase3ProductEngine:
    """
    Create a Phase 3 Product Engine.
    
    Args:
        data_root: Root data directory
        channel_name: Channel name (e.g., 'WWV 10 MHz')
        frequency_hz: Center frequency in Hz
        station_config: Station metadata dict
        
    Returns:
        Configured Phase3ProductEngine
    """
    config = Phase3Config(
        data_root=data_root,
        channel_name=channel_name,
        frequency_hz=frequency_hz,
        station_config=station_config
    )
    
    return Phase3ProductEngine(config)


def process_channel_day(
    data_root: Path,
    channel_name: str,
    frequency_hz: float,
    station_config: Dict[str, Any],
    date_str: str
) -> Dict[str, Any]:
    """
    Process one day's data for a channel.
    
    Convenience function for batch processing.
    
    Args:
        data_root: Root data directory
        channel_name: Channel name
        frequency_hz: Center frequency
        station_config: Station metadata
        date_str: Date to process (YYYYMMDD or YYYY-MM-DD)
        
    Returns:
        Processing results
    """
    engine = create_phase3_engine(
        data_root=data_root,
        channel_name=channel_name,
        frequency_hz=frequency_hz,
        station_config=station_config
    )
    
    try:
        results = engine.process_day(date_str)
        return results
    finally:
        engine.close()
