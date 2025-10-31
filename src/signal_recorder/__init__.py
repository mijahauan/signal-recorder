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

# Core GRAPE components
from .grape_rtp_recorder import GRAPERecorderManager, GRAPEChannelRecorder
from .grape_metadata import GRAPEMetadataGenerator
from .grape_recorder import GRAPERecorderManager as GRAPECLIManager

# Channel management
from .channel_manager import ChannelManager
from .control_discovery import discover_channels_via_control, ChannelInfo
from .radiod_control import RadiodControl
from .radiod_stream_manager import RadiodStreamManager, StreamInfo

# Upload (exists but not yet integrated into daemon)
from .uploader import UploadManager, SSHRsyncUpload

__all__ = [
    # Core GRAPE
    "GRAPERecorderManager",
    "GRAPEChannelRecorder", 
    "GRAPEMetadataGenerator",
    "GRAPECLIManager",
    # Channel management
    "ChannelManager",
    "discover_channels_via_control",
    "ChannelInfo",
    "RadiodControl",
    "RadiodStreamManager",
    "StreamInfo",
    # Upload
    "UploadManager",
    "SSHRsyncUpload",
]

# Legacy components moved to src/signal_recorder/legacy/
# (StreamDiscovery, StreamRecorder, StorageManager, SignalProcessor, etc.)

