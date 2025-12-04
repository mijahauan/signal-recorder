"""
GRAPE Application - Global Radio Amateur Propagation Experiment

This package provides GRAPE-specific components for recording and analyzing
WWV/WWVH/CHU time station signals for ionospheric propagation studies.

Architecture:
=============
Three-Phase Robust Time-Aligned Data Pipeline:

Phase 1: Immutable Raw Archive (20 kHz IQ DRF)
- Stores raw data with system time only (no UTC corrections)
- Fixed-duration file splitting (1 hour) - NOT event-based
- Lossless compression (Shuffle + ZSTD/gzip)
- NEVER modified based on subsequent analysis

Phase 2: Analytical Engine (Clock Offset Series)
- Reads from Phase 1 raw archive
- Produces D_clock = t_system - t_UTC
- Uses tone detection, discrimination, propagation modeling
- Output: Separate versionable CSV/JSON files

Phase 3: Corrected Telemetry Product (10 Hz DRF)
- Reads Phase 1 + applies D_clock from Phase 2
- Decimates 20 kHz → 10 Hz
- UTC(NIST) aligned timestamps
- Output: PROCESSED/ALIGNED DRF for upload

Key Components:
- RawArchiveWriter: Phase 1 immutable raw archive
- ClockOffsetEngine: Phase 2 analytical engine
- CorrectedProductGenerator: Phase 3 product generator
- PipelineOrchestrator: Coordinates all three phases
- TransmissionTimeSolver: UTC(NIST) back-calculation

Legacy Components (still supported):
- GrapeRecorder: Two-phase recorder (startup buffering → recording)
- GrapeNPZWriter: SegmentWriter for NPZ format with time_snap
- AnalyticsService: Discrimination, decimation, tone detection
- StartupToneDetector: WWV/CHU tone-based time_snap establishment

Example (New Pipeline):
    from grape_recorder.grape import create_pipeline
    
    orchestrator = create_pipeline(
        data_dir=Path('/data/grape'),
        channel_name='WWV_10MHz',
        frequency_hz=10e6,
        receiver_grid='EM38ww',
        station_config={'callsign': 'W3PM', 'grid_square': 'EM38ww'}
    )
    orchestrator.start()
    
    # Feed RTP data
    orchestrator.process_samples(iq_samples, rtp_timestamp)

Example (Legacy):
    from grape_recorder.grape import GrapeRecorder, GrapeConfig
    
    config = GrapeConfig(
        channel_name="WWV 10 MHz",
        frequency_hz=10.0e6,
        output_dir=Path("grape_output"),
    )
    recorder = GrapeRecorder(config, rtp_receiver)
    recorder.start()
"""

# Core GRAPE recorder
from .grape_recorder import GrapeRecorder, GrapeConfig, GrapeState
from .grape_npz_writer import GrapeNPZWriter

# Tone detection and timing
from .startup_tone_detector import StartupToneDetector
from .tone_detector import ToneDetector

# Analytics and discrimination
from .analytics_service import AnalyticsService
from .wwvh_discrimination import WWVHDiscriminator
from .wwv_test_signal import WWVTestSignalDetector
from .discrimination_csv_writers import DiscriminationCSVWriters

# Decimation
from .decimation import decimate_for_upload, get_decimator

# DRF output
from .digital_rf_writer import DigitalRFWriter
from .drf_batch_writer import DRFBatchWriter
from .drf_writer_service import DRFWriterService

# Supporting components
from .wwv_geographic_predictor import WWVGeographicPredictor
from .wwv_tone_schedule import schedule as wwv_tone_schedule
from .wwv_bcd_encoder import WWVBCDEncoder
from .quality_metrics import QualityMetricsTracker, MinuteQualityMetrics
from .timing_metrics_writer import TimingMetricsWriter
from .solar_zenith_calculator import calculate_solar_zenith_for_day
from .gap_backfill import find_gaps, backfill_gaps
from .core_npz_writer import CoreNPZWriter
from .core_recorder import CoreRecorder

# Cross-channel coordination (Station Lock)
from .global_station_voter import GlobalStationVoter, StationAnchor, AnchorQuality
from .station_lock_coordinator import StationLockCoordinator, GuidedDetection, MinuteProcessingResult

# Primary Time Standard (HF Time Transfer)
from .propagation_mode_solver import (
    PropagationModeSolver, 
    PropagationMode, 
    ModeCandidate,
    ModeIdentificationResult,
    EmissionTimeResult
)
from .primary_time_standard import (
    PrimaryTimeStandard,
    ChannelTimeResult,
    StationConsensus,
    MinuteTimeStandardResult
)
from .time_standard_csv_writer import TimeStandardCSVWriter, TimeStandardSummaryWriter

# Three-Phase Pipeline (New Architecture)
from .pipeline_recorder import (
    PipelineRecorder,
    PipelineRecorderConfig,
    PipelineRecorderState,
    create_pipeline_recorder
)
from .raw_archive_writer import (
    RawArchiveWriter,
    RawArchiveReader,
    RawArchiveConfig,
    SystemTimeReference,
    create_raw_archive_writer
)
from .clock_offset_series import (
    ClockOffsetEngine,
    ClockOffsetSeries,
    ClockOffsetMeasurement,
    ClockOffsetQuality,
    ClockOffsetSeriesWriter,
    create_clock_offset_engine
)
from .corrected_product_generator import (
    CorrectedProductGenerator,
    StreamingProductGenerator,
    ProductConfig,
    create_product_generator
)
from .pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineConfig,
    PipelineState,
    BatchReprocessor,
    create_pipeline
)

# Transmission Time Solver (UTC back-calculation)
from .transmission_time_solver import (
    TransmissionTimeSolver,
    MultiStationSolver,
    SolverResult,
    CombinedUTCResult,
    PropagationMode,
    ModeCandidate as TransmissionModeCandidate,
    create_solver_from_grid,
    create_multi_station_solver,
    grid_to_latlon
)

# Phase 2: Temporal Analysis Engine (Refined temporal analysis order)
from .phase2_temporal_engine import (
    Phase2TemporalEngine,
    Phase2Result,
    TimeSnapResult,
    ChannelCharacterization,
    TransmissionTimeSolution,
    create_phase2_engine
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

# GPSDO Monitoring
from .gpsdo_monitor import (
    GPSDOMonitor,
    AnchorState,
    GPSDOMonitorState
)

# Sliding Window Monitor (10-second real-time quality tracking)
from .sliding_window_monitor import (
    SlidingWindowMonitor,
    WindowMetrics,
    MinuteSummary,
    SignalQuality
)

# Spectrogram Generation (from Phase 3 decimated data)
from .spectrogram_generator import (
    SpectrogramGenerator,
    SpectrogramConfig,
    generate_spectrograms_for_day
)

__all__ = [
    # Core recorder
    "GrapeRecorder",
    "GrapeConfig",
    "GrapeState",
    "GrapeNPZWriter",
    "CoreRecorder",
    "CoreNPZWriter",
    # Tone detection
    "StartupToneDetector",
    "ToneDetector",
    # Analytics
    "AnalyticsService",
    "WWVHDiscriminator",
    "WWVTestSignalDetector",
    "DiscriminationCSVWriters",
    # Decimation
    "decimate_for_upload",
    "get_decimator",
    # DRF
    "DigitalRFWriter",
    "DRFBatchWriter",
    "DRFWriterService",
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
    # Cross-channel coordination
    "GlobalStationVoter",
    "StationAnchor",
    "AnchorQuality",
    "StationLockCoordinator",
    "GuidedDetection",
    "MinuteProcessingResult",
    # Primary Time Standard
    "PropagationModeSolver",
    "PropagationMode",
    "ModeCandidate",
    "ModeIdentificationResult",
    "EmissionTimeResult",
    "PrimaryTimeStandard",
    "ChannelTimeResult",
    "StationConsensus",
    "MinuteTimeStandardResult",
    "TimeStandardCSVWriter",
    "TimeStandardSummaryWriter",
    # Three-Phase Pipeline (New Architecture)
    "PipelineRecorder",
    "PipelineRecorderConfig",
    "PipelineRecorderState",
    "create_pipeline_recorder",
    "RawArchiveWriter",
    "RawArchiveReader",
    "RawArchiveConfig",
    "SystemTimeReference",
    "create_raw_archive_writer",
    "ClockOffsetEngine",
    "ClockOffsetSeries",
    "ClockOffsetMeasurement",
    "ClockOffsetQuality",
    "ClockOffsetSeriesWriter",
    "create_clock_offset_engine",
    "CorrectedProductGenerator",
    "StreamingProductGenerator",
    "ProductConfig",
    "create_product_generator",
    "PipelineOrchestrator",
    "PipelineConfig",
    "PipelineState",
    "BatchReprocessor",
    "create_pipeline",
    # Transmission Time Solver
    "TransmissionTimeSolver",
    "MultiStationSolver",
    "SolverResult",
    "CombinedUTCResult",
    "TransmissionModeCandidate",
    "create_solver_from_grid",
    "create_multi_station_solver",
    "grid_to_latlon",
    # Phase 2: Temporal Analysis Engine
    "Phase2TemporalEngine",
    "Phase2Result",
    "TimeSnapResult",
    "ChannelCharacterization",
    "TransmissionTimeSolution",
    "create_phase2_engine",
    # Phase 3: Product Generation Engine
    "Phase3ProductEngine",
    "Phase3Config",
    "GapInfo",
    "GapAnalysis",
    "TimingAnnotation",
    "create_phase3_engine",
    "process_channel_day",
    # GPSDO Monitoring
    "GPSDOMonitor",
    "AnchorState",
    "GPSDOMonitorState",
    # Sliding Window Monitor
    "SlidingWindowMonitor",
    "WindowMetrics",
    "MinuteSummary",
    "SignalQuality",
]
