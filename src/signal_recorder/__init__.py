"""
Signal Recorder - Automated recording and upload system for ka9q-radio streams

This package provides a modular system for:
- Discovering ka9q-radio streams via Avahi/mDNS
- Recording time-synchronized audio/IQ data
- Processing signals with pluggable processors (GRAPE, CODAR, etc.)
- Uploading to remote repositories (HamSCI PSWS, etc.)

Copyright 2025
"""

__version__ = "0.1.0"
__author__ = "Signal Recorder Project"

from .discovery import StreamDiscovery, StreamManager
from .recorder import StreamRecorder
from .storage import StorageManager
from .processor import SignalProcessor, GRAPEProcessor
from .uploader import UploadManager, SSHRsyncUpload

__all__ = [
    "StreamDiscovery",
    "StreamManager",
    "StreamRecorder",
    "StorageManager",
    "SignalProcessor",
    "GRAPEProcessor",
    "UploadManager",
    "SSHRsyncUpload",
]

