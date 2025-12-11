#!/usr/bin/env python3
"""
Three-Phase Pipeline Orchestrator

Coordinates the robust time-aligned data pipeline:
- Phase 1: Immutable Raw Archive (20 kHz IQ DRF)
- Phase 2: Analytical Engine (Clock Offset Series D_clock)
- Phase 3: Corrected Telemetry Product (10 Hz DRF)

This orchestrator ensures the strict, non-circular hierarchy of time sources
to guarantee data integrity and the ability to reprocess results.

Architecture:
=============
┌─────────────────────────────────────────────────────────────────────────┐
│                         RTP Stream (radiod)                             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│            PHASE 1: Immutable Raw Archive (20 kHz IQ DRF)               │
│  • System time tagging ONLY (t_system)                                  │
│  • Fixed-duration file splitting (1 hour)                               │
│  • Lossless compression (Shuffle + ZSTD/gzip)                           │
│  • NEVER modified based on analysis                                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│            PHASE 2: Analytical Engine (D_clock Series)                  │
│  • Tone detection (WWV/WWVH/CHU)                                        │
│  • WWV/WWVH discrimination                                              │
│  • Propagation delay calculation                                        │
│  • D_clock = t_system - t_UTC                                           │
│  • Output: Separate versionable CSV/JSON                                │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│         PHASE 3: Corrected Telemetry Product (10 Hz DRF)                │
│  • Reads Phase 1 raw archive                                            │
│  • Applies D_clock from Phase 2                                         │
│  • Decimates 20 kHz → 10 Hz                                             │
│  • UTC(NIST) aligned timestamps                                         │
│  • Output: PROCESSED/ALIGNED DRF for upload                             │
└─────────────────────────────────────────────────────────────────────────┘

Usage:
------
    orchestrator = PipelineOrchestrator(
        data_dir=Path('/data/grape'),
        channel_name='WWV_10MHz',
        frequency_hz=10e6,
        receiver_grid='EM38ww',
        station_config={'callsign': 'W3PM', ...}
    )
    
    # Start real-time processing
    orchestrator.start()
    
    # Feed RTP data
    orchestrator.process_rtp_packet(rtp_timestamp, iq_samples)
    
    # Stop gracefully
    orchestrator.stop()
"""

import numpy as np
import logging
import time
import threading
import queue
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """Pipeline operational states."""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class PipelineConfig:
    """
    Configuration for the three-phase pipeline.
    """
    # Base directories
    data_dir: Path
    
    # Channel identification
    channel_name: str
    frequency_hz: float
    sample_rate: int = 20000  # Raw sample rate from radiod
    
    # Receiver location (required for propagation calculation)
    receiver_grid: str = ""
    
    # Station metadata
    station_config: Dict[str, Any] = field(default_factory=dict)
    
    # Phase 1 settings
    raw_archive_compression: str = 'gzip'
    raw_archive_file_duration_sec: int = 3600  # 1 hour files
    # Note: Storage quota is managed at top-level, not per-channel
    
    # Phase 2 settings
    analysis_latency_sec: int = 120  # Wait for complete minute
    enable_multi_station: bool = True
    
    # Phase 3 settings
    output_sample_rate: int = 10  # 10 Hz decimated output
    streaming_latency_minutes: int = 2
    
    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        
        # Derive subdirectories
        self.raw_archive_dir = self.data_dir / 'raw_archive'
        self.clock_offset_dir = self.data_dir / 'clock_offset'
        self.processed_dir = self.data_dir / 'processed'
        
        # Create directories
        for d in [self.raw_archive_dir, self.clock_offset_dir, self.processed_dir]:
            d.mkdir(parents=True, exist_ok=True)


class PipelineOrchestrator:
    """
    Coordinates the three-phase robust time-aligned data pipeline.
    
    Ensures strict separation between:
    - Phase 1: Raw data (system time only)
    - Phase 2: Analysis (produces D_clock)
    - Phase 3: Products (applies D_clock)
    
    This design allows reprocessing at any phase without data loss.
    """
    
    def __init__(self, config: PipelineConfig):
        """
        Initialize the pipeline orchestrator.
        
        Args:
            config: PipelineConfig with all settings
        """
        self.config = config
        self._lock = threading.Lock()
        self.state = PipelineState.IDLE
        
        # Phase 1: Binary Archive Writer (simple, robust)
        # Uses raw binary files instead of HDF5/DRF for maximum reliability
        from .binary_archive_writer import BinaryArchiveWriter, BinaryArchiveConfig
        
        raw_config = BinaryArchiveConfig(
            output_dir=config.data_dir / 'raw_buffer',  # Separate from raw_archive
            channel_name=config.channel_name,
            frequency_hz=config.frequency_hz,
            sample_rate=config.sample_rate,
            station_config=config.station_config,
        )
        self.raw_archive_writer = BinaryArchiveWriter(raw_config)
        
        # Phase 2: Timing is now handled by time-manager
        # D_clock and station discrimination come from /dev/shm/grape_timing
        # via TimingClient in Phase 3. No local timing analysis needed.
        self.clock_offset_engine = None
        logger.info("Phase 2 timing disabled - using time-manager via TimingClient")
        
        # Phase 3: Product generation is now handled separately as batch processing
        # See phase3_product_engine.py and scripts/grape-phase3.sh
        # The streaming product generator is disabled - Phase 3 runs as batch job
        self.product_generator = None
        logger.info("Phase 3 streaming disabled - use batch processing via grape-phase3.sh")
        
        # Audio buffer for web UI playback (simple AM demod from IQ)
        from .audio_buffer import AudioBufferManager
        self.audio_buffer_manager = AudioBufferManager(
            data_root=str(config.data_dir),
            sample_rate=config.sample_rate
        )
        
        # Sample accumulation for minute-aligned processing
        self.samples_per_minute = config.sample_rate * 60
        self.current_minute_samples: List[np.ndarray] = []
        self.current_minute_start_time: Optional[float] = None
        self.current_minute_start_rtp: Optional[int] = None
        
        # Processing queue for Phase 2
        self.analysis_queue: queue.Queue = queue.Queue()
        self.analysis_thread: Optional[threading.Thread] = None
        
        # Statistics
        self.stats = {
            'packets_received': 0,
            'samples_archived': 0,
            'minutes_analyzed': 0,
            'products_generated': 0,
            'start_time': None
        }
        
        logger.info(f"PipelineOrchestrator initialized for {config.channel_name}")
        logger.info(f"  Data directory: {config.data_dir}")
        logger.info(f"  Sample rate: {config.sample_rate} Hz")
        logger.info(f"  Output rate: {config.output_sample_rate} Hz")
    
    def start(self):
        """Start the pipeline processing."""
        with self._lock:
            if self.state != PipelineState.IDLE:
                logger.warning(f"Cannot start pipeline in state {self.state}")
                return
            
            self.state = PipelineState.STARTING
        
        # Start analysis thread
        self.analysis_thread = threading.Thread(
            target=self._analysis_loop,
            name=f"Analysis-{self.config.channel_name}",
            daemon=True
        )
        self.analysis_thread.start()
        
        self.stats['start_time'] = time.time()
        
        with self._lock:
            self.state = PipelineState.RUNNING
        
        logger.info(f"Pipeline started for {self.config.channel_name}")
    
    def set_stream_health(self, metrics: Dict[str, Any]):
        """
        Set RTP stream health metrics for archival.
        
        Call this before stop() to include stream health in the session summary.
        
        Args:
            metrics: Dict with keys like packets_received, packets_dropped,
                    packets_out_of_order, sequence_errors, timestamp_jumps
        """
        self.stream_health_metrics = metrics
        self.raw_archive_writer.set_stream_health(metrics)
    
    def stop(self):
        """Stop the pipeline gracefully."""
        with self._lock:
            if self.state not in (PipelineState.RUNNING, PipelineState.STARTING):
                return
            
            self.state = PipelineState.STOPPING
        
        # Signal analysis thread to stop
        self.analysis_queue.put(None)
        
        # Wait for analysis thread
        if self.analysis_thread and self.analysis_thread.is_alive():
            self.analysis_thread.join(timeout=5.0)
        
        # Flush all writers
        self._flush_current_minute()
        self.raw_archive_writer.close()
        if self.clock_offset_engine:
            self.clock_offset_engine.save_series()
        if self.product_generator:
            self.product_generator.close()
        
        with self._lock:
            self.state = PipelineState.IDLE
        
        logger.info(f"Pipeline stopped for {self.config.channel_name}")
    
    def process_samples(
        self,
        samples: np.ndarray,
        rtp_timestamp: int,
        system_time: Optional[float] = None
    ):
        """
        Process incoming IQ samples through the pipeline.
        
        This is the main entry point for real-time data.
        
        Args:
            samples: Complex64 IQ samples
            rtp_timestamp: RTP timestamp of first sample
            system_time: System wall clock time (uses current if None)
        """
        with self._lock:
            if self.state != PipelineState.RUNNING:
                return
        
        if system_time is None:
            system_time = time.time()
        
        self.stats['packets_received'] += 1
        
        # Phase 1: Write to raw archive (system time only)
        # CRITICAL: This writes raw data WITHOUT any UTC correction
        samples_written = self.raw_archive_writer.write_samples(
            samples=samples,
            rtp_timestamp=rtp_timestamp,
            system_time=system_time
        )
        self.stats['samples_archived'] += samples_written
        
        # Write to audio buffer for web UI playback
        try:
            self.audio_buffer_manager.write_iq(self.config.channel_name, samples)
        except Exception as e:
            # Don't let audio buffer errors affect main pipeline
            pass
        
        # NOTE: Minute accumulation disabled for performance
        # Phase 2 reads directly from archive - no need to buffer in memory
        # self._accumulate_minute(samples, rtp_timestamp, system_time)
    
    def _accumulate_minute(
        self,
        samples: np.ndarray,
        rtp_timestamp: int,
        system_time: float
    ):
        """
        Accumulate samples until we have a complete minute.
        
        Phase 2 and 3 operate on minute-aligned data.
        """
        # Start new minute if needed
        if self.current_minute_start_time is None:
            # Align to minute boundary
            minute_boundary = (int(system_time) // 60) * 60
            self.current_minute_start_time = minute_boundary
            self.current_minute_start_rtp = rtp_timestamp
            self.current_minute_samples = []
        
        # Add samples
        self.current_minute_samples.append(samples)
        
        # Check if minute is complete
        total_samples = sum(len(s) for s in self.current_minute_samples)
        if total_samples >= self.samples_per_minute:
            self._complete_minute()
    
    def _complete_minute(self):
        """
        Complete the current minute and queue for Phase 2/3 processing.
        """
        if not self.current_minute_samples:
            return
        
        # Concatenate samples
        minute_samples = np.concatenate(self.current_minute_samples)
        
        # Trim to exact minute if needed
        if len(minute_samples) > self.samples_per_minute:
            minute_samples = minute_samples[:self.samples_per_minute]
        
        # Queue for analysis (Phase 2)
        self.analysis_queue.put((
            self.current_minute_start_time,
            self.current_minute_start_rtp,
            minute_samples
        ))
        
        # Reset for next minute
        # Keep any overflow samples for next minute
        overflow_samples = sum(len(s) for s in self.current_minute_samples) - self.samples_per_minute
        if overflow_samples > 0:
            # Calculate overflow
            all_samples = np.concatenate(self.current_minute_samples)
            self.current_minute_samples = [all_samples[self.samples_per_minute:]]
            self.current_minute_start_time += 60
            self.current_minute_start_rtp += self.samples_per_minute
        else:
            self.current_minute_samples = []
            self.current_minute_start_time = None
            self.current_minute_start_rtp = None
    
    def _flush_current_minute(self):
        """Flush any partial minute data."""
        if self.current_minute_samples:
            # Pad to full minute
            minute_samples = np.concatenate(self.current_minute_samples)
            if len(minute_samples) < self.samples_per_minute:
                padding = np.zeros(
                    self.samples_per_minute - len(minute_samples),
                    dtype=np.complex64
                )
                minute_samples = np.concatenate([minute_samples, padding])
            
            # Process partial minute
            self.analysis_queue.put((
                self.current_minute_start_time,
                self.current_minute_start_rtp,
                minute_samples
            ))
    
    def _analysis_loop(self):
        """
        Background thread for Phase 2 and Phase 3 processing.
        
        Processes complete minutes from the queue.
        """
        logger.info("Analysis thread started")
        
        while True:
            try:
                # Get next minute to process
                item = self.analysis_queue.get(timeout=1.0)
                
                if item is None:
                    # Shutdown signal
                    break
                
                system_time, rtp_timestamp, samples = item
                
                # Phase 2: Timing is handled by time-manager
                # No local D_clock computation - just count minutes processed
                if self.clock_offset_engine:
                    try:
                        measurement = self.clock_offset_engine.process_minute(
                            iq_samples=samples,
                            system_time=system_time,
                            rtp_timestamp=rtp_timestamp
                        )
                        
                        if measurement:
                            self.stats['minutes_analyzed'] += 1
                            logger.debug(
                                f"D_clock: {measurement.clock_offset_ms:+.2f}ms "
                                f"(conf={measurement.confidence:.2f})"
                            )
                    
                    except Exception as e:
                        logger.error(f"Phase 2 analysis error: {e}", exc_info=True)
                else:
                    # Timing comes from time-manager - just track that we processed this minute
                    self.stats['minutes_analyzed'] += 1
                
                # Phase 3: Generate corrected product (disabled in three-phase architecture)
                # Phase 3 now runs as batch processing via grape-phase3.sh
                if self.product_generator:
                    try:
                        # Add to streaming generator (will process when D_clock available)
                        self.product_generator.add_raw_minute(system_time, samples)
                        self.stats['products_generated'] += 1
                    
                    except Exception as e:
                        logger.error(f"Phase 3 product generation error: {e}", exc_info=True)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Analysis loop error: {e}", exc_info=True)
        
        logger.info("Analysis thread stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        with self._lock:
            uptime = time.time() - self.stats['start_time'] if self.stats['start_time'] else 0
            
            return {
                'state': self.state.value,
                'uptime_seconds': uptime,
                'packets_received': self.stats['packets_received'],
                'samples_archived': self.stats['samples_archived'],
                'minutes_analyzed': self.stats['minutes_analyzed'],
                'products_generated': self.stats['products_generated'],
                'queue_depth': self.analysis_queue.qsize(),
                'phase1_stats': self.raw_archive_writer.get_stats(),
                'phase2_stats': self.clock_offset_engine.get_stats() if self.clock_offset_engine else {'status': 'disabled (time-manager)'},
                'phase3_stats': self.product_generator.get_stats() if self.product_generator else {'status': 'disabled'}
            }
    
    def get_status(self) -> Dict[str, Any]:
        """Get detailed pipeline status for monitoring."""
        stats = self.get_stats()
        
        # Add health indicators
        stats['health'] = {
            'phase1_healthy': stats['samples_archived'] > 0,
            'phase2_healthy': stats['minutes_analyzed'] > 0,
            'phase3_healthy': stats['products_generated'] > 0,
            'queue_backlog': stats['queue_depth'] > 10
        }
        
        return stats


def create_pipeline(
    data_dir: Path,
    channel_name: str,
    frequency_hz: float,
    receiver_grid: str,
    station_config: Dict[str, Any],
    sample_rate: int = 20000
) -> PipelineOrchestrator:
    """
    Create a pipeline orchestrator with standard configuration.
    
    Args:
        data_dir: Base data directory
        channel_name: Channel identifier
        frequency_hz: Center frequency
        receiver_grid: Receiver grid square
        station_config: Station metadata
        sample_rate: Input sample rate
        
    Returns:
        Configured PipelineOrchestrator
    """
    config = PipelineConfig(
        data_dir=data_dir,
        channel_name=channel_name,
        frequency_hz=frequency_hz,
        receiver_grid=receiver_grid,
        station_config=station_config,
        sample_rate=sample_rate
    )
    
    return PipelineOrchestrator(config)


# Batch reprocessing support
class BatchReprocessor:
    """
    Reprocess historical data through Phase 2 and Phase 3.
    
    This allows re-running analysis with improved algorithms
    without re-recording Phase 1 data.
    """
    
    def __init__(
        self,
        data_dir: Path,
        channel_name: str,
        frequency_hz: float,
        receiver_grid: str,
        station_config: Dict[str, Any]
    ):
        """Initialize batch reprocessor."""
        self.data_dir = Path(data_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.receiver_grid = receiver_grid
        self.station_config = station_config
        
        # Directories
        self.raw_archive_dir = data_dir / 'raw_archive'
        self.clock_offset_dir = data_dir / 'clock_offset'
        self.processed_dir = data_dir / 'processed'
        
        logger.info(f"BatchReprocessor initialized for {channel_name}")
    
    def reprocess_phase2(
        self,
        start_time: float,
        end_time: float,
        output_version: str = "v2"
    ) -> Dict[str, Any]:
        """
        Reprocess Phase 1 data through Phase 2 analytical engine.
        
        Args:
            start_time: Start time (Unix timestamp)
            end_time: End time (Unix timestamp)
            output_version: Version string for output files
            
        Returns:
            Processing results summary
        """
        from .clock_offset_series import ClockOffsetEngine
        from .raw_archive_writer import RawArchiveReader
        
        # Create versioned output directory
        versioned_output = self.clock_offset_dir / output_version
        versioned_output.mkdir(parents=True, exist_ok=True)
        
        # Initialize engine with versioned output
        engine = ClockOffsetEngine(
            raw_archive_dir=self.raw_archive_dir,
            output_dir=versioned_output,
            channel_name=self.channel_name,
            frequency_hz=self.frequency_hz,
            receiver_grid=self.receiver_grid
        )
        
        # Initialize reader
        reader = RawArchiveReader(self.raw_archive_dir, self.channel_name)
        
        results = {
            'start_time': start_time,
            'end_time': end_time,
            'output_version': output_version,
            'minutes_processed': 0,
            'measurements': 0,
            'errors': []
        }
        
        # Process minute by minute
        current_time = start_time
        sample_rate = 20000
        samples_per_minute = sample_rate * 60
        
        while current_time < end_time:
            start_index = int(current_time * sample_rate)
            
            try:
                read_result = reader.read_samples(start_index, samples_per_minute)
                if read_result:
                    samples, _ = read_result
                    rtp_timestamp = start_index  # Approximate
                    
                    measurement = engine.process_minute(
                        iq_samples=samples,
                        system_time=current_time,
                        rtp_timestamp=rtp_timestamp
                    )
                    
                    results['minutes_processed'] += 1
                    if measurement:
                        results['measurements'] += 1
                        
            except Exception as e:
                results['errors'].append(f"{current_time}: {e}")
            
            current_time += 60
        
        # Save series
        engine.save_series()
        
        logger.info(
            f"Phase 2 reprocessing complete: "
            f"{results['minutes_processed']} minutes, "
            f"{results['measurements']} measurements"
        )
        
        return results
    
    def reprocess_phase3(
        self,
        start_time: float,
        end_time: float,
        clock_offset_version: str = "v2",
        output_version: str = "v2"
    ) -> Dict[str, Any]:
        """
        Reprocess Phase 1 data through Phase 3 with specific D_clock version.
        
        Note: This method has been deprecated. Use Phase3ProductEngine directly
        via the grape-phase3.sh script for batch processing.
        
        Args:
            start_time: Start time
            end_time: End time
            clock_offset_version: Which Phase 2 version to use
            output_version: Version string for output
            
        Returns:
            Processing results summary
        """
        # Phase 3 batch processing should use Phase3ProductEngine directly
        # See: scripts/grape-phase3.sh and src/grape_recorder/grape/phase3_product_engine.py
        raise NotImplementedError(
            "BatchReprocessor.reprocess_phase3() is deprecated. "
            "Use Phase3ProductEngine directly via grape-phase3.sh for batch processing."
        )
