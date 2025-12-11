"""
Core Infrastructure - Application-agnostic recording components

NOTE (Dec 2025 Refactor):
========================
This package has been deprecated. All RTP handling has been moved to:
    grape_recorder.grape.stream_recorder

The following modules were REMOVED:
- RTPReceiver (replaced by ka9q.RadiodStream)
- PacketResequencer (handled by RadiodStream)
- RecordingSession (replaced by StreamRecorder)

For RTP reception, use:
    from grape_recorder.grape.stream_recorder import StreamRecorder
"""

__all__ = []
