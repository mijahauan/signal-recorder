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
    from signal_recorder import subscribe_stream
    
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

__version__ = "1.1.0"
__author__ = "GRAPE Signal Recorder Project"

# Core components
# NOTE: V2 recorder stack archived to archive/legacy-code/v2-recorder/ (Nov 18, 2025)
# CURRENT stack: core_recorder.py + analytics_service.py
# Generic RTP receiver extracted to rtp_receiver.py (Nov 30, 2025)
# Generic recording session added (Nov 30, 2025)
from .rtp_receiver import RTPReceiver, RTPHeader
from .recording_session import (
    RecordingSession, SessionConfig, SessionState, 
    SegmentInfo, SessionMetrics, SegmentWriter
)

# GRAPE-specific components (refactored Nov 30, 2025)
from .grape_recorder import GrapeRecorder, GrapeConfig, GrapeState
from .grape_npz_writer import GrapeNPZWriter

# WSPR-specific components (added Nov 30, 2025)
from .wspr_recorder import WsprRecorder, WsprConfig, WsprState, create_wspr_recorder
from .wspr_wav_writer import WsprWAVWriter

# Stream API - SSRC-free interface (NEW Dec 2025)
from .stream_spec import StreamSpec, StreamRequest
from .stream_handle import StreamHandle, StreamInfo
from .stream_manager import StreamManager
from .stream_api import (
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
    # === Generic recording infrastructure ===
    "RTPReceiver",
    "RTPHeader",
    "RecordingSession",
    "SessionConfig",
    "SessionState",
    "SegmentInfo",
    "SessionMetrics",
    "SegmentWriter",
    # === Application-specific recorders ===
    # GRAPE
    "GrapeRecorder",
    "GrapeConfig",
    "GrapeState",
    "GrapeNPZWriter",
    # WSPR
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

# Legacy components moved to src/signal_recorder/legacy/
# (StreamDiscovery, StreamRecorder, StorageManager, SignalProcessor, etc.)

