"""
GRAPE Application - Global Radio Amateur Propagation Experiment

This package provides GRAPE-specific components for recording and analyzing
WWV/WWVH/CHU time station signals for ionospheric propagation studies.

Key Components:
- GrapeRecorder: Two-phase recorder (startup buffering → recording)
- GrapeNPZWriter: SegmentWriter for NPZ format with time_snap
- AnalyticsService: Discrimination, decimation, tone detection
- StartupToneDetector: WWV/CHU tone-based time_snap establishment

Example:
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
]
