# grape_rtp_recorder.py - Archived

**Archived:** November 30, 2025  
**Reason:** Refactored for modularity and generic reuse

## What Was Extracted

The generic `RTPReceiver` and `RTPHeader` classes were extracted to:
- `src/signal_recorder/rtp_receiver.py`

These are now application-independent and can be reused for non-GRAPE projects.

## Contents of Archived File

| Component | Status | Notes |
|-----------|--------|-------|
| `DiscontinuityType` | Unused | Was never integrated |
| `TimingDiscontinuity` | Unused | Had GRAPE-specific fields |
| `DiscontinuityTracker` | Unused | Was never integrated |
| `MultiStationToneDetector` | Superseded | Replaced by `tone_detector.py` |
| `RTPHeader` | **Extracted** | Now in `rtp_receiver.py` |
| `RTPReceiver` | **Extracted** | Now in `rtp_receiver.py` |
| `Resampler` | Unused | V2 stack only |
| `DailyBuffer` | Unused | V2 stack only |
| `GRAPERecorderManager` | **OBSOLETE** | V2 stack - use `core_recorder.py` |

## Migration

If you have code importing from `grape_rtp_recorder`, update:

```python
# Old
from .grape_rtp_recorder import RTPReceiver

# New
from .rtp_receiver import RTPReceiver, RTPHeader
```

Or use the package export:

```python
from signal_recorder import RTPReceiver, RTPHeader
```
