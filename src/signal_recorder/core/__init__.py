"""
Core Infrastructure - Application-agnostic recording components

This package provides the generic infrastructure for recording RTP streams:
- RTPReceiver: Multicast reception and SSRC demultiplexing
- RecordingSession: Packet resequencing, segmentation, gap detection
- PacketResequencer: Out-of-order packet handling

These components are used by application-specific recorders (GRAPE, WSPR, etc.)
but contain no application-specific logic.
"""

from .rtp_receiver import RTPReceiver, RTPHeader
from .recording_session import (
    RecordingSession,
    SessionConfig,
    SessionState,
    SegmentInfo,
    SessionMetrics,
    SegmentWriter,
)
from .packet_resequencer import PacketResequencer, RTPPacket, GapInfo

__all__ = [
    # RTP reception
    "RTPReceiver",
    "RTPHeader",
    # Recording session
    "RecordingSession",
    "SessionConfig",
    "SessionState",
    "SegmentInfo",
    "SessionMetrics",
    "SegmentWriter",
    # Packet handling
    "PacketResequencer",
    "RTPPacket",
    "GapInfo",
]
