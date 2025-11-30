"""
GRAPE Signal Recorder - WWV/CHU timing signal recorder for HamSCI

Specialized system for recording time-standard radio signals from ka9q-radio
and uploading to the HamSCI PSWS repository.

Features:
- Direct RTP packet reception (no external tools)
- scipy-based decimation (16 kHz → 10 Hz IQ)
- Digital RF format with HamSCI metadata
- Real-time quality monitoring (completeness, timing drift, packet loss)
- Web-based configuration and monitoring

See ARCHITECTURE.md for design details.

Copyright 2025
"""

__version__ = "1.0.0"
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

# Channel management
from .channel_manager import ChannelManager
from ka9q import discover_channels, ChannelInfo, RadiodControl

# ka9q timing functions (GPS_TIME/RTP_TIMESNAP support)
from ka9q import rtp_to_wallclock, parse_rtp_header

# Re-export ka9q functions for backward compatibility
discover_channels_via_control = discover_channels  # Legacy alias

# Upload (exists but not yet integrated into daemon)
from .uploader import UploadManager, SSHRsyncUpload

__all__ = [
    # Generic RTP reception
    "RTPReceiver",
    "RTPHeader",
    # Generic recording session
    "RecordingSession",
    "SessionConfig",
    "SessionState",
    "SegmentInfo",
    "SessionMetrics",
    "SegmentWriter",
    # Channel management
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

