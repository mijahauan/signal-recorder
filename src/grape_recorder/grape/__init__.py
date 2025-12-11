"""GRAPE Application - Global Radio Amateur Propagation Experiment

This package provides GRAPE-specific components for recording and analyzing
WWV/WWVH/CHU time station signals for ionospheric propagation studies.

Architecture (Refactored Dec 2025):
===================================
Two-Application Split:

1. time-manager (separate repo) - Infrastructure daemon
   - Computes D_clock via tone detection + discrimination
   - Publishes to /dev/shm/grape_timing
   - Feeds chronyd for system clock discipline

2. grape-recorder (this package) - Science data recorder
   - Consumes timing from time-manager via TimingClient
   - Records IQ data with time and gap annotations
   - Decimates 20 kHz → 10 Hz
   - Packages Digital RF for PSWS upload

Three-Phase Data Pipeline:

Phase 1: Immutable Raw Archive (20 kHz IQ)
- Uses StreamRecorder with ka9q.RadiodStream
- Binary files with JSON metadata sidecars
- Gap detection via StreamQuality
- Key: StreamRecorder, BinaryArchiveWriter

Phase 2: Timing (EXTERNAL - time-manager)
- D_clock consumed via TimingClient
- Station discrimination handled by time-manager

Phase 3: Corrected Telemetry Product (10 Hz DRF)
- Reads Phase 1 + applies D_clock from time-manager
- Decimates 20 kHz → 10 Hz with StatefulDecimator
- UTC(NIST) aligned timestamps
- Gap annotations in HDF5 metadata + sidecar JSON
- Key: Phase3ProductEngine

Example:
    from grape_recorder.grape import create_pipeline
    from grape_recorder.timing_client import get_time_manager_status
    
    # Check time-manager is running
    status = get_time_manager_status()
    print(f"time-manager: {status['status']}")
    
    orchestrator = create_pipeline(
        data_dir=Path('/data/grape'),
        channel_name='WWV_10MHz',
        frequency_hz=10e6,
        receiver_grid='EM38ww',
        station_config={'callsign': 'W3PM', 'grid_square': 'EM38ww'}
    )
    orchestrator.start()
"""

# Tone detection (used by time-manager, kept for compatibility)
from .tone_detector import ToneDetector

# WWV/WWVH discrimination (used by time-manager, kept for compatibility)
from .wwvh_discrimination import WWVHDiscriminator
from .wwv_test_signal import WWVTestSignalDetector

# Decimation
from .decimation import decimate_for_upload, get_decimator, StatefulDecimator

# DRF output
from .drf_batch_writer import DRFBatchWriter

# Supporting components
from .wwv_geographic_predictor import WWVGeographicPredictor
from .wwv_tone_schedule import schedule as wwv_tone_schedule
from .wwv_bcd_encoder import WWVBCDEncoder
from .quality_metrics import QualityMetricsTracker, MinuteQualityMetrics
from .timing_metrics_writer import TimingMetricsWriter
from .solar_zenith_calculator import calculate_solar_zenith_for_day
from .gap_backfill import find_gaps, backfill_gaps

# Time Standard CSV Writer (for logging)
from .time_standard_csv_writer import TimeStandardCSVWriter, TimeStandardSummaryWriter

# New StreamRecorder (RadiodStream-based)
from .stream_recorder import (
    StreamRecorder,
    StreamRecorderConfig,
    ChannelStreamRecorder
)

# Binary Archive Writer (Phase 1)
from .binary_archive_writer import (
    BinaryArchiveWriter,
    BinaryArchiveConfig,
    BinaryArchiveReader,
    GapInterval
)

# Pipeline components
from .pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineConfig,
    PipelineState,
    BatchReprocessor,
    create_pipeline
)
from .raw_archive_writer import (
    RawArchiveWriter,
    RawArchiveReader,
    RawArchiveConfig,
    SystemTimeReference,
    create_raw_archive_writer
)

# Phase 3: Product Generation Engine (10 Hz Decimated DRF with Timing Annotations)
from .phase3_product_engine import (
    Phase3ProductEngine,
    Phase3Config,
    GapInfo,
    GapAnalysis,
    TimingAnnotation,
    create_phase3_engine,
    process_channel_day
)

# Decimated Binary Buffer (stores 10 Hz IQ with timing metadata)
from .decimated_buffer import (
    DecimatedBuffer,
    DayMetadata,
    MinuteMetadata,
    get_decimated_buffer
)

# Spectrogram Generation - CarrierSpectrogramGenerator is the CANONICAL implementation
from .carrier_spectrogram import (
    CarrierSpectrogramGenerator,
    SpectrogramConfig as CarrierSpectrogramConfig,
    generate_all_channel_spectrograms
)

# DEPRECATED: SpectrogramGenerator - use CarrierSpectrogramGenerator instead
from .spectrogram_generator import (
    SpectrogramGenerator,  # DEPRECATED
    SpectrogramConfig,     # DEPRECATED - use CarrierSpectrogramConfig
    generate_spectrograms_for_day  # DEPRECATED
)

# Daily DRF Packager (for PSWS upload)
from .daily_drf_packager import (
    DailyDRFPackager,
    StationConfig,
    package_for_upload
)

__all__ = [
    # Tone detection
    "ToneDetector",
    # Discrimination
    "WWVHDiscriminator",
    "WWVTestSignalDetector",
    # Decimation
    "decimate_for_upload",
    "get_decimator",
    "StatefulDecimator",
    # DRF
    "DRFBatchWriter",
    # Supporting
    "WWVGeographicPredictor",
    "wwv_tone_schedule",
    "WWVBCDEncoder",
    "QualityMetricsTracker",
    "MinuteQualityMetrics",
    "TimingMetricsWriter",
    "calculate_solar_zenith_for_day",
    "find_gaps",
    "backfill_gaps",
    # Time Standard CSV
    "TimeStandardCSVWriter",
    "TimeStandardSummaryWriter",
    # New StreamRecorder
    "StreamRecorder",
    "StreamRecorderConfig",
    "ChannelStreamRecorder",
    # Binary Archive
    "BinaryArchiveWriter",
    "BinaryArchiveConfig",
    "BinaryArchiveReader",
    "GapInterval",
    # Pipeline
    "PipelineOrchestrator",
    "PipelineConfig",
    "PipelineState",
    "BatchReprocessor",
    "create_pipeline",
    "RawArchiveWriter",
    "RawArchiveReader",
    "RawArchiveConfig",
    "SystemTimeReference",
    "create_raw_archive_writer",
    # Phase 3: Product Generation Engine
    "Phase3ProductEngine",
    "Phase3Config",
    "GapInfo",
    "GapAnalysis",
    "TimingAnnotation",
    "create_phase3_engine",
    "process_channel_day",
    # Decimated Binary Buffer
    "DecimatedBuffer",
    "DayMetadata",
    "MinuteMetadata",
    "get_decimated_buffer",
    # Carrier Spectrogram Generator
    "CarrierSpectrogramGenerator",
    "CarrierSpectrogramConfig",
    "generate_all_channel_spectrograms",
    # Daily DRF Packager
    "DailyDRFPackager",
    "StationConfig",
    "package_for_upload",
]
