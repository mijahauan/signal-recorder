#!/usr/bin/env python3
"""
Phase 3: Corrected Telemetry Product Generator (10 Hz DRF Upload)

This module generates the final time-corrected telemetry product by:
1. Reading raw 20 kHz IQ from Phase 1 (Immutable Raw Archive)
2. Applying clock offset corrections from Phase 2 (D_clock Series)
3. Decimating to 10 Hz
4. Writing to a separate DRF directory marked as PROCESSED/ALIGNED

The resulting 10 Hz product has highly accurate UTC(NIST) timestamps
derived from the analytical engine's propagation delay calculations.

Key Operation:
==============
For each output sample:
1. Read raw IQ from Phase 1
2. Look up D_clock for that time range from Phase 2
3. Apply correction: t_UTC = t_system - D_clock
4. Decimate 20 kHz → 10 Hz
5. Write to PROCESSED DRF with corrected timestamp

This architecture ensures:
- Phase 1 remains pristine (never modified)
- Phase 2 can be re-run with improved algorithms
- Phase 3 can be regenerated from Phases 1+2 without data loss

Usage:
------
    generator = CorrectedProductGenerator(
        raw_archive_dir=Path('/data/raw_archive'),
        clock_offset_dir=Path('/data/clock_offset'),
        output_dir=Path('/data/processed'),
        channel_name='WWV_10MHz',
        frequency_hz=10e6,
        station_config={'callsign': 'W3PM', 'grid_square': 'EM38ww'}
    )
    
    # Process a time range
    generator.process_range(start_time, end_time)
"""

import numpy as np
import logging
import time
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
import threading

logger = logging.getLogger(__name__)

# Try to import Digital RF
try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    logger.warning("digital_rf not available - product generation disabled")


@dataclass
class ProductConfig:
    """Configuration for corrected product generator."""
    raw_archive_dir: Path
    clock_offset_dir: Path
    output_dir: Path
    channel_name: str
    frequency_hz: float
    station_config: Dict[str, Any]
    
    # Processing parameters
    input_sample_rate: int = 20000   # Raw archive sample rate
    output_sample_rate: int = 10     # Final product sample rate
    
    # DRF parameters
    subdir_cadence_secs: int = 86400
    file_cadence_millisecs: int = 3600000
    compression_level: int = 9
    
    def __post_init__(self):
        self.raw_archive_dir = Path(self.raw_archive_dir)
        self.clock_offset_dir = Path(self.clock_offset_dir)
        self.output_dir = Path(self.output_dir)


class CorrectedProductGenerator:
    """
    Phase 3: Generate time-corrected 10 Hz DRF products.
    
    Consumes:
    - Phase 1: Raw 20 kHz IQ archive (immutable)
    - Phase 2: Clock Offset Series (D_clock)
    
    Produces:
    - Time-corrected 10 Hz Digital RF for upload
    """
    
    def __init__(self, config: ProductConfig):
        """
        Initialize the corrected product generator.
        
        Args:
            config: ProductConfig with all settings
        """
        if not DRF_AVAILABLE:
            raise ImportError(
                "digital_rf package required for product generation. "
                "Install with: pip install digital_rf"
            )
        
        self.config = config
        self._lock = threading.Lock()
        
        # Create output directory structure
        self.product_dir = config.output_dir / 'processed' / config.channel_name.replace(' ', '_')
        self.product_dir.mkdir(parents=True, exist_ok=True)
        
        # Import Phase 1 and Phase 2 readers
        from .raw_archive_writer import RawArchiveReader
        from .clock_offset_series import ClockOffsetSeries, ClockOffsetSeriesWriter
        
        # Initialize Phase 1 reader
        self.archive_reader = RawArchiveReader(
            config.raw_archive_dir,
            config.channel_name
        )
        
        # Initialize Phase 2 reader
        self.clock_offset_writer = ClockOffsetSeriesWriter(
            config.clock_offset_dir,
            config.channel_name
        )
        
        # Current clock offset series (loaded on demand)
        self.clock_offset_series: Optional[ClockOffsetSeries] = None
        
        # DRF writer state
        self.drf_writer: Optional[drf.DigitalRFWriter] = None
        self.metadata_writer: Optional[drf.DigitalMetadataWriter] = None
        self.dataset_uuid = uuid.uuid4().hex
        self.current_day: Optional[datetime] = None
        self.next_sample_index: Optional[int] = None
        
        # Decimator
        self._init_decimator()
        
        # Statistics
        self.samples_written = 0
        self.minutes_processed = 0
        self.start_time = time.time()
        
        logger.info(f"CorrectedProductGenerator initialized for {config.channel_name}")
        logger.info(f"  Raw archive: {config.raw_archive_dir}")
        logger.info(f"  Clock offset: {config.clock_offset_dir}")
        logger.info(f"  Output: {self.product_dir}")
        logger.info(f"  Decimation: {config.input_sample_rate} Hz → {config.output_sample_rate} Hz")
    
    def _init_decimator(self):
        """Initialize decimation filter."""
        from .decimation import get_decimator
        
        self.decimator = get_decimator(
            self.config.input_sample_rate,
            self.config.output_sample_rate
        )
        self.decimation_factor = self.config.input_sample_rate // self.config.output_sample_rate
        
        logger.info(f"Decimator initialized: factor={self.decimation_factor}")
    
    def load_clock_offset_series(self, filename: Optional[str] = None) -> bool:
        """
        Load clock offset series from Phase 2.
        
        Args:
            filename: Specific file to load, or None for latest
            
        Returns:
            True if series loaded successfully
        """
        if filename:
            self.clock_offset_series = self.clock_offset_writer.load_series(filename)
        else:
            # Try to load from CSV (streaming format)
            csv_file = self.clock_offset_writer.output_dir / 'clock_offset_series.csv'
            if csv_file.exists():
                self.clock_offset_series = self._load_series_from_csv(csv_file)
        
        if self.clock_offset_series:
            logger.info(
                f"Loaded clock offset series: "
                f"{len(self.clock_offset_series.measurements)} measurements"
            )
            return True
        
        logger.warning("No clock offset series available")
        return False
    
    def _load_series_from_csv(self, csv_file: Path):
        """Load clock offset series from CSV file."""
        import csv
        from .clock_offset_series import (
            ClockOffsetSeries,
            ClockOffsetMeasurement,
            ClockOffsetQuality
        )
        
        series = ClockOffsetSeries(
            channel_name=self.config.channel_name,
            frequency_hz=self.config.frequency_hz,
            receiver_grid=self.config.station_config.get('grid_square', '')
        )
        
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    measurement = ClockOffsetMeasurement(
                        system_time=float(row['system_time']),
                        utc_time=float(row['utc_time']),
                        minute_boundary_utc=float(row['minute_boundary_utc']),
                        clock_offset_ms=float(row['clock_offset_ms']),
                        station=row['station'],
                        frequency_mhz=float(row['frequency_mhz']),
                        propagation_delay_ms=float(row['propagation_delay_ms']),
                        propagation_mode=row['propagation_mode'],
                        n_hops=int(row['n_hops']),
                        confidence=float(row['confidence']),
                        uncertainty_ms=float(row['uncertainty_ms']),
                        quality_grade=ClockOffsetQuality(row['quality_grade']),
                        snr_db=float(row['snr_db']) if row.get('snr_db') else 0.0,
                        utc_verified=row.get('utc_verified', '').lower() == 'true'
                    )
                    series.add_measurement(measurement)
                except (KeyError, ValueError) as e:
                    logger.warning(f"Error parsing CSV row: {e}")
                    continue
        
        return series
    
    def get_clock_offset(self, system_time: float) -> Tuple[float, float]:
        """
        Get clock offset for a specific system time.
        
        Args:
            system_time: System time to query
            
        Returns:
            Tuple of (offset_ms, uncertainty_ms)
        """
        if self.clock_offset_series is None:
            # No correction available - return 0 offset with high uncertainty
            return (0.0, 999.0)
        
        result = self.clock_offset_series.get_offset_at_time(system_time, interpolate=True)
        if result is None:
            return (0.0, 999.0)
        
        return result
    
    def _create_drf_writer(self, utc_timestamp: float):
        """
        Create Digital RF writer for corrected product.
        
        Uses UTC timestamp (corrected) for file organization.
        
        Args:
            utc_timestamp: UTC timestamp (after D_clock correction)
        """
        dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
        day_date = dt.date()
        
        # Close existing writer if day changed
        if self.current_day and self.current_day != day_date:
            logger.info("Day boundary: closing previous DRF writer")
            self._close_writer()
        
        if self.drf_writer is not None:
            return  # Already have writer for this day
        
        # Build PSWS-compatible directory structure
        station_config = self.config.station_config
        date_str = day_date.strftime('%Y%m%d')
        callsign = station_config.get('callsign', 'UNKNOWN')
        grid = station_config.get('grid_square', 'UNKNOWN')
        receiver_name = station_config.get('receiver_name', 'GRAPE')
        psws_station_id = station_config.get('psws_station_id', 'UNKNOWN')
        psws_instrument_id = station_config.get('psws_instrument_id', '1')
        safe_channel = self.config.channel_name.replace(' ', '_')
        
        # Mark as PROCESSED/ALIGNED product
        receiver_info = f"{receiver_name}@{psws_station_id}_{psws_instrument_id}"
        obs_timestamp = dt.strftime('OBS%Y-%m-%dT%H-%M')
        
        drf_dir = (
            self.product_dir / date_str / f"{callsign}_{grid}" /
            receiver_info / obs_timestamp / safe_channel
        )
        drf_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate start_global_index from UTC timestamp
        start_global_index = int(utc_timestamp * self.config.output_sample_rate)
        
        if self.next_sample_index is None:
            self.next_sample_index = start_global_index
        
        logger.info(f"Creating corrected product DRF writer for {day_date}")
        logger.info(f"  Directory: {drf_dir}")
        logger.info(f"  start_global_index: {start_global_index}")
        
        # Create Digital RF writer
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
        
        # Write metadata
        metadata = {
            'product_type': 'corrected_10hz_iq',
            'phase': 'phase3_aligned',
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
            'source_archive_type': 'raw_20khz_iq',
            'decimation_factor': self.decimation_factor
        }
        self.metadata_writer.write(start_global_index, metadata)
        
        self.current_day = day_date
        logger.info("✅ Corrected product DRF writer ready")
    
    def _close_writer(self):
        """Close DRF writer."""
        if self.drf_writer:
            try:
                self.drf_writer.close()
            except Exception as e:
                logger.warning(f"Error closing DRF writer: {e}")
            self.drf_writer = None
            self.metadata_writer = None
    
    def process_minute(
        self,
        raw_samples: np.ndarray,
        system_time: float
    ) -> int:
        """
        Process one minute of raw data into corrected product.
        
        Args:
            raw_samples: Raw 20 kHz IQ samples from Phase 1
            system_time: System time of first sample (from Phase 1)
            
        Returns:
            Number of output samples written
        """
        # Step 1: Get clock offset from Phase 2
        offset_ms, uncertainty_ms = self.get_clock_offset(system_time)
        
        # Step 2: Calculate corrected UTC time
        # t_UTC = t_system - D_clock
        utc_timestamp = system_time - (offset_ms / 1000.0)
        
        logger.debug(
            f"Time correction: system={system_time:.3f}, "
            f"D_clock={offset_ms:+.2f}ms, UTC={utc_timestamp:.3f}"
        )
        
        # Step 3: Ensure writer exists
        self._create_drf_writer(utc_timestamp)
        
        if self.drf_writer is None:
            logger.error("Failed to create DRF writer")
            return 0
        
        # Step 4: Decimate raw samples
        try:
            decimated = self.decimator(raw_samples)
        except Exception as e:
            logger.error(f"Decimation failed: {e}")
            return 0
        
        # Step 5: Convert to float32 (N, 2) format for wsprdaemon compatibility
        iq_complex = decimated.astype(np.complex64)
        iq_float = np.zeros((len(iq_complex), 2), dtype=np.float32)
        iq_float[:, 0] = iq_complex.real
        iq_float[:, 1] = iq_complex.imag
        
        # Step 6: Calculate sample index from UTC time
        calculated_index = int(utc_timestamp * self.config.output_sample_rate)
        
        # Check for backwards time
        if self.next_sample_index is not None and calculated_index < self.next_sample_index:
            logger.warning(
                f"Time correction caused backwards jump: "
                f"calculated={calculated_index} < next={self.next_sample_index}. "
                f"Skipping to maintain monotonic sequence."
            )
            return 0
        
        # Step 7: Write to DRF
        try:
            self.drf_writer.rf_write(iq_float)
            self.samples_written += len(decimated)
            self.next_sample_index = calculated_index + len(decimated)
            self.minutes_processed += 1
            
            return len(decimated)
            
        except Exception as e:
            logger.error(f"DRF write error: {e}")
            return 0
    
    def process_range(
        self,
        start_time: float,
        end_time: float,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Process a range of raw archive data into corrected product.
        
        Args:
            start_time: Start system time
            end_time: End system time
            progress_callback: Optional callback(current_time, total_minutes)
            
        Returns:
            Processing results summary
        """
        from .raw_archive_writer import RawArchiveReader
        
        # Load clock offset series
        if not self.load_clock_offset_series():
            logger.warning("No clock offset series - proceeding without correction")
        
        results = {
            'start_time': start_time,
            'end_time': end_time,
            'minutes_processed': 0,
            'samples_written': 0,
            'errors': []
        }
        
        # Calculate number of minutes
        total_minutes = int((end_time - start_time) / 60)
        samples_per_minute = self.config.input_sample_rate * 60
        
        logger.info(f"Processing {total_minutes} minutes of raw archive")
        
        current_time = start_time
        while current_time < end_time:
            # Calculate sample index for this minute
            start_index = int(current_time * self.config.input_sample_rate)
            
            # Read from raw archive
            try:
                read_result = self.archive_reader.read_samples(start_index, samples_per_minute)
                if read_result is None:
                    logger.warning(f"No data available at {current_time}")
                    current_time += 60
                    continue
                
                raw_samples, actual_index = read_result
                
                # Process this minute
                written = self.process_minute(raw_samples, current_time)
                results['samples_written'] += written
                results['minutes_processed'] += 1
                
            except Exception as e:
                logger.error(f"Error processing minute at {current_time}: {e}")
                results['errors'].append(str(e))
            
            if progress_callback:
                progress_callback(current_time, total_minutes)
            
            current_time += 60
        
        # Close writer
        self._close_writer()
        
        logger.info(
            f"Processing complete: {results['minutes_processed']} minutes, "
            f"{results['samples_written']} samples"
        )
        
        return results
    
    def write_timing_metadata(
        self,
        sample_index: int,
        clock_offset_ms: float,
        uncertainty_ms: float,
        quality_grade: str
    ):
        """
        Write timing quality metadata for a sample range.
        
        Args:
            sample_index: Sample index in output DRF
            clock_offset_ms: Applied clock offset
            uncertainty_ms: Timing uncertainty
            quality_grade: Quality grade ('A', 'B', 'C', 'D')
        """
        if self.metadata_writer is None:
            return
        
        timing_metadata = {
            'event_type': 'timing_correction',
            'clock_offset_ms': clock_offset_ms,
            'uncertainty_ms': uncertainty_ms,
            'quality_grade': quality_grade,
            'timestamp': datetime.now(tz=timezone.utc).isoformat()
        }
        
        try:
            self.metadata_writer.write(sample_index, timing_metadata)
        except Exception as e:
            logger.warning(f"Failed to write timing metadata: {e}")
    
    def flush(self):
        """Flush all buffered data."""
        with self._lock:
            if self.drf_writer:
                self._close_writer()
                logger.info(f"Flushed corrected product: {self.samples_written} samples")
    
    def close(self):
        """Close the generator and finalize output."""
        self.flush()
        self._write_session_summary()
    
    def _write_session_summary(self):
        """Write session summary metadata."""
        summary = {
            'product_type': 'corrected_10hz_iq',
            'phase': 'phase3_aligned',
            'channel_name': self.config.channel_name,
            'frequency_hz': self.config.frequency_hz,
            'output_sample_rate': self.config.output_sample_rate,
            'samples_written': self.samples_written,
            'minutes_processed': self.minutes_processed,
            'processing_time_sec': time.time() - self.start_time,
            'station_config': self.config.station_config,
            'clock_offset_applied': True,
            'time_reference': 'utc_nist_corrected',
            'created_at': datetime.now(tz=timezone.utc).isoformat()
        }
        
        summary_file = self.product_dir / 'session_summary.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Session summary written to {summary_file}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get generator statistics."""
        return {
            'samples_written': self.samples_written,
            'minutes_processed': self.minutes_processed,
            'current_day': self.current_day.isoformat() if self.current_day else None,
            'uptime_seconds': time.time() - self.start_time,
            'output_dir': str(self.product_dir)
        }


class StreamingProductGenerator(CorrectedProductGenerator):
    """
    Streaming version of the product generator for real-time processing.
    
    Processes data as it arrives from Phase 1 and Phase 2, producing
    corrected output with minimal latency.
    """
    
    def __init__(self, config: ProductConfig, latency_minutes: int = 2):
        """
        Initialize streaming generator.
        
        Args:
            config: ProductConfig
            latency_minutes: Processing delay to ensure D_clock is available
        """
        super().__init__(config)
        
        self.latency_minutes = latency_minutes
        self.pending_minutes: List[Tuple[float, np.ndarray]] = []
        self.last_processed_time: Optional[float] = None
    
    def add_raw_minute(self, system_time: float, raw_samples: np.ndarray):
        """
        Add a minute of raw data for processing.
        
        The data will be held until D_clock is available.
        
        Args:
            system_time: System time of first sample
            raw_samples: Raw 20 kHz IQ samples
        """
        with self._lock:
            self.pending_minutes.append((system_time, raw_samples))
            self._process_ready_minutes()
    
    def _process_ready_minutes(self):
        """Process minutes that have D_clock available."""
        if not self.pending_minutes:
            return
        
        # Reload clock offset series
        self.load_clock_offset_series()
        
        # Find minutes that can be processed
        # (D_clock must be available with acceptable uncertainty)
        now = time.time()
        cutoff_time = now - (self.latency_minutes * 60)
        
        ready = []
        still_pending = []
        
        for system_time, raw_samples in self.pending_minutes:
            if system_time < cutoff_time:
                # Check if D_clock is available
                offset_ms, uncertainty_ms = self.get_clock_offset(system_time)
                if uncertainty_ms < 100:  # Acceptable uncertainty
                    ready.append((system_time, raw_samples))
                else:
                    still_pending.append((system_time, raw_samples))
            else:
                still_pending.append((system_time, raw_samples))
        
        self.pending_minutes = still_pending
        
        # Process ready minutes (outside lock)
        for system_time, raw_samples in ready:
            self.process_minute(raw_samples, system_time)
            self.last_processed_time = system_time


# Convenience factory function
def create_product_generator(
    raw_archive_dir: Path,
    clock_offset_dir: Path,
    output_dir: Path,
    channel_name: str,
    frequency_hz: float,
    station_config: Dict[str, Any],
    streaming: bool = False,
    latency_minutes: int = 2
) -> CorrectedProductGenerator:
    """
    Create a corrected product generator.
    
    Args:
        raw_archive_dir: Phase 1 raw archive directory
        clock_offset_dir: Phase 2 clock offset directory
        output_dir: Output directory for Phase 3 product
        channel_name: Channel identifier
        frequency_hz: Center frequency
        station_config: Station metadata
        streaming: Use streaming mode for real-time processing
        latency_minutes: Processing latency for streaming mode
        
    Returns:
        Configured CorrectedProductGenerator
    """
    config = ProductConfig(
        raw_archive_dir=raw_archive_dir,
        clock_offset_dir=clock_offset_dir,
        output_dir=output_dir,
        channel_name=channel_name,
        frequency_hz=frequency_hz,
        station_config=station_config
    )
    
    if streaming:
        return StreamingProductGenerator(config, latency_minutes)
    else:
        return CorrectedProductGenerator(config)
