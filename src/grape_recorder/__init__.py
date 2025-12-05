"""
Signal Recorder - Generic RTP stream recording with GRAPE specialization

A generic system for subscribing to and recording RTP streams from ka9q-radio,
with specialized support for GRAPE (WWV/CHU timing signals) and WSPR.

Key Features:
- SSRC-free API: Specify frequency, mode, sample rate - SSRC handled internally
- Automatic stream sharing: Same spec = same stream
- Protocol-based storage: Implement SegmentWriter for any output format
- Multi-app coordination: Discovery prevents SSRC collisions

Quick Start:
    from grape_recorder import subscribe_stream
    
    # Get a stream (no SSRC needed!)
    stream = subscribe_stream(
        radiod="radiod.local",
        frequency_hz=10.0e6,
        preset="iq",
        sample_rate=16000
    )
    
    print(f"Receiving on {stream.multicast_address}:{stream.port}")

See ARCHITECTURE.md for design details.

Copyright 2025
"""

__version__ = "2.0.0"  # Major version bump: package restructuring
__author__ = "GRAPE Signal Recorder Project"

# =============================================================================
# CORE INFRASTRUCTURE (application-agnostic)
# Moved to grape_recorder/core/ package (Dec 1, 2025)
# =============================================================================
from .core import (
    RTPReceiver, RTPHeader,
    RecordingSession, SessionConfig, SessionState,
    SegmentInfo, SessionMetrics, SegmentWriter,
    PacketResequencer, RTPPacket, GapInfo,
)

# =============================================================================
# STREAM API (SSRC-free interface)
# Moved to grape_recorder/stream/ package (Dec 1, 2025)
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

# =============================================================================
# GRAPE APPLICATION (WWV/WWVH/CHU time signals)
# Moved to grape_recorder/grape/ package (Dec 1, 2025)
# Now using three-phase pipeline architecture
# =============================================================================
from .grape import (
    PipelineRecorder, PipelineRecorderConfig, PipelineRecorderState,
    CoreRecorder,
)

# =============================================================================
# WSPR APPLICATION (Weak Signal Propagation Reporter)
# Moved to grape_recorder/wspr/ package (Dec 1, 2025)
# =============================================================================
from .wspr import (
    WsprRecorder, WsprConfig, WsprState,
    WsprWAVWriter,
    create_wspr_recorder,
)

# Channel management (lower-level)
from .channel_manager import ChannelManager
from ka9q import discover_channels, ChannelInfo, RadiodControl

# ka9q timing functions (GPS_TIME/RTP_TIMESNAP support)
from ka9q import rtp_to_wallclock, parse_rtp_header

# Re-export ka9q functions for backward compatibility
discover_channels_via_control = discover_channels  # Legacy alias

# Upload (exists but not yet integrated into daemon)
from .uploader import UploadManager, SSHRsyncUpload

__all__ = [
    # === Stream API (primary interface) ===
    "subscribe_stream",
    "subscribe_iq",
    "subscribe_usb",
    "subscribe_am",
    "subscribe_batch",
    "discover_streams",
    "find_stream",
    "get_manager",
    "close_all",
    # Stream types
    "StreamSpec",
    "StreamRequest",
    "StreamHandle",
    "StreamInfo",
    "StreamManager",
    # === Core infrastructure ===
    "RTPReceiver",
    "RTPHeader",
    "RecordingSession",
    "SessionConfig",
    "SessionState",
    "SegmentInfo",
    "SessionMetrics",
    "SegmentWriter",
    "PacketResequencer",
    "RTPPacket",
    "GapInfo",
    # === GRAPE application (three-phase pipeline) ===
    "PipelineRecorder",
    "PipelineRecorderConfig",
    "PipelineRecorderState",
    "CoreRecorder",
    # === WSPR application ===
    "WsprRecorder",
    "WsprConfig",
    "WsprState",
    "WsprWAVWriter",
    "create_wspr_recorder",
    # === Lower-level (advanced use) ===
    "ChannelManager",
    "discover_channels_via_control",
    "ChannelInfo",
    "RadiodControl",
    # Timing (from ka9q-python)
    "rtp_to_wallclock",
    "parse_rtp_header",
    # Upload
    "UploadManager",
    "SSHRsyncUpload",
]

# =============================================================================
# Package structure (Dec 1, 2025):
#   grape_recorder/
#   ├── core/       - Application-agnostic: RTP, resequencing, sessions
#   ├── stream/     - Stream API: subscribe, discover, manage
#   ├── grape/      - GRAPE app: WWV/WWVH/CHU recording & analysis
#   └── wspr/       - WSPR app: 2-minute WAV recording
# =============================================================================

