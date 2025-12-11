"""
GRAPE Recorder - Scientific data recorder for WWV/WWVH/CHU time signals

Records IQ data from ka9q-radio, applies timing corrections from time-manager,
and produces scientific-quality Digital RF packages for PSWS upload.

Architecture (Dec 2025 Refactor):
================================
Two-Application Split:
1. time-manager (separate repo) - Computes D_clock, feeds chronyd
2. grape-recorder (this package) - Records IQ data with timing annotations

Three-Phase Data Pipeline:
- Phase 1: Raw IQ recording via StreamRecorder (ka9q.RadiodStream)
- Phase 2: Timing from time-manager via TimingClient
- Phase 3: Decimated Digital RF with gap/timing annotations

Quick Start:
    from grape_recorder.grape import StreamRecorder, Phase3ProductEngine
    from grape_recorder.timing_client import get_time_manager_status
    
    # Check time-manager is running
    status = get_time_manager_status()
    print(f"time-manager: {status['status']}")

Copyright 2025
"""

__version__ = "3.0.0"  # Major refactor: RadiodStream + TimingClient
__author__ = "GRAPE Signal Recorder Project"

# =============================================================================
# GRAPE APPLICATION (primary interface)
# =============================================================================
from .grape import (
    # StreamRecorder (new RadiodStream-based intake)
    StreamRecorder,
    StreamRecorderConfig,
    ChannelStreamRecorder,
    # Phase 3 Product Engine
    Phase3ProductEngine,
    Phase3Config,
    GapInfo,
    GapAnalysis,
    TimingAnnotation,
    create_phase3_engine,
    # Pipeline
    PipelineOrchestrator,
    PipelineConfig,
    PipelineState,
    create_pipeline,
    # Decimation
    decimate_for_upload,
    get_decimator,
    StatefulDecimator,
)

# =============================================================================
# TIMING CLIENT (consumes timing from time-manager)
# =============================================================================
from .timing_client import (
    TimingClient,
    ClockStatus,
    ChannelTiming,
    TimingSnapshot,
    get_timing_client,
    get_d_clock,
    get_station,
    get_utc_time,
    get_time_manager_status,
)

# =============================================================================
# STREAM API (SSRC-free interface - still available)
# =============================================================================
from .stream import (
    StreamSpec, StreamRequest,
    StreamHandle, StreamInfo,
    StreamManager,
    subscribe_stream,
    subscribe_iq,
    subscribe_usb,
    subscribe_am,
    subscribe_batch,
    discover_streams,
    find_stream,
    get_manager,
    close_all,
)

# Channel management (lower-level)
from .channel_manager import ChannelManager
from ka9q import discover_channels, ChannelInfo, RadiodControl

# ka9q timing functions (GPS_TIME/RTP_TIMESNAP support)
from ka9q import rtp_to_wallclock, parse_rtp_header

# Re-export ka9q functions for backward compatibility
discover_channels_via_control = discover_channels  # Legacy alias

# Upload
from .uploader import UploadManager, SSHRsyncUpload

__all__ = [
    # === GRAPE Application (primary) ===
    "StreamRecorder",
    "StreamRecorderConfig",
    "ChannelStreamRecorder",
    "Phase3ProductEngine",
    "Phase3Config",
    "GapInfo",
    "GapAnalysis",
    "TimingAnnotation",
    "create_phase3_engine",
    "PipelineOrchestrator",
    "PipelineConfig",
    "PipelineState",
    "create_pipeline",
    "decimate_for_upload",
    "get_decimator",
    "StatefulDecimator",
    # === Timing Client ===
    "TimingClient",
    "ClockStatus",
    "ChannelTiming",
    "TimingSnapshot",
    "get_timing_client",
    "get_d_clock",
    "get_station",
    "get_utc_time",
    "get_time_manager_status",
    # === Stream API ===
    "subscribe_stream",
    "subscribe_iq",
    "subscribe_usb",
    "subscribe_am",
    "subscribe_batch",
    "discover_streams",
    "find_stream",
    "get_manager",
    "close_all",
    "StreamSpec",
    "StreamRequest",
    "StreamHandle",
    "StreamInfo",
    "StreamManager",
    # === Lower-level ===
    "ChannelManager",
    "discover_channels_via_control",
    "ChannelInfo",
    "RadiodControl",
    "rtp_to_wallclock",
    "parse_rtp_header",
    "UploadManager",
    "SSHRsyncUpload",
]

# =============================================================================
# Package structure (Dec 2025 Refactor):
#   grape_recorder/
#   ├── grape/      - GRAPE app: StreamRecorder, Phase3ProductEngine
#   ├── stream/     - Stream API: subscribe, discover, manage
#   ├── core/       - DEPRECATED (RTP handling now in ka9q.RadiodStream)
#   └── timing_client.py - Consumes timing from time-manager
# =============================================================================

