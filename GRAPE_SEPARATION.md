# GRAPE Application Separation Guide

**Date**: 2025-12-14  
**Status**: Files identified, ready for separation

This document lists the files that should be moved to a separate GRAPE application.
These files handle decimation to 10 Hz, spectrograms, power graphs, and PSWS upload.

---

## Files to Move to GRAPE App

### Python Modules (src/hf_timestd/core/)

**Phase 3 Products (decimation, spectrograms, upload):**
- `decimation.py` - 20 kHz → 10 Hz decimation filters
- `decimated_buffer.py` - 10 Hz binary buffer storage
- `spectrogram_generator.py` - Legacy spectrogram generator (DEPRECATED)
- `carrier_spectrogram.py` - Carrier spectrogram generator (CANONICAL)
- `phase3_product_engine.py` - Phase 3 product generation
- `phase3_products_service.py` - Phase 3 real-time service
- `daily_drf_packager.py` - PSWS DRF packaging
- `drf_batch_writer.py` - DRF batch writing

**Upload functionality:**
- `uploader.py` (in src/hf_timestd/) - SFTP upload manager
- `upload_tracker.py` (in src/hf_timestd/) - Upload state tracking

### Scripts (scripts/)

These scripts were NOT renamed to timestd-* and should move to grape app:
- `grape-spectrogram.sh` - (deleted, needs recreation in grape app)
- `grape-daily-upload.sh` - (deleted, needs recreation in grape app)
- `grape-products.sh` - (deleted, needs recreation in grape app)
- `grape-phase3.sh` - (deleted, needs recreation in grape app)

Supporting scripts that may need copies:
- `daily-drf-upload.sh` - Daily DRF upload script
- `run_phase3_processor.py` - Phase 3 batch processor
- `generate_daily_spectrograms.sh` - Daily spectrogram generation
- `auto-generate-spectrograms.sh` - Auto spectrogram generation

### Systemd Services (systemd/)

These services were NOT renamed and should move to grape app:
- `grape-spectrograms.service` - (deleted, needs recreation)
- `grape-spectrograms.timer` - (deleted, needs recreation)
- `grape-daily-upload.service` - (deleted, needs recreation)
- `grape-daily-upload.timer` - (deleted, needs recreation)

---

## Files Staying in hf_timestd

### Core Timing Analysis
- `tone_detector.py` - WWV/WWVH/CHU tone detection
- `phase2_temporal_engine.py` - Phase 2 timing analysis
- `phase2_analytics_service.py` - Phase 2 real-time service
- `transmission_time_solver.py` - D_clock calculation
- `wwvh_discrimination.py` - WWV/WWVH discrimination
- `clock_convergence.py` - Kalman filter convergence
- `multi_broadcast_fusion.py` - 13-broadcast fusion
- `chrony_shm.py` - Chrony SHM integration

### Recording Infrastructure
- `core_recorder.py` - Core recorder
- `core_recorder_v2.py` - V2 core recorder
- `raw_archive_writer.py` - Phase 1 DRF writer
- `binary_archive_writer.py` - Binary archive writer

### Supporting
- `wwv_constants.py` - WWV/WWVH/CHU constants
- `ionospheric_model.py` - Propagation modeling
- `gpsdo_monitor.py` - GPSDO state machine
- `quality_metrics.py` - Quality tracking

---

## Separation Strategy

1. **Create new grape-app repository**
2. **Copy identified files** to new repo
3. **Update imports** in grape-app to use `hf_timestd` as dependency
4. **Remove copied files** from hf_timestd (optional - can keep for reference)
5. **Update grape-app scripts** to use new paths

### Dependency Direction
```
grape-app (decimation, spectrograms, upload)
    ↓ depends on
hf_timestd (recording, timing analysis, D_clock)
```

The grape-app will import from hf_timestd:
```python
from hf_timestd.core import Phase2TemporalEngine, ClockOffsetSeries
from hf_timestd.paths import GRAPEPaths
```

---

## Notes

- The `decimation.py` contains `StatefulDecimator` which is also used by Phase 2 analytics
  for sliding window monitoring. May need to keep a copy or refactor.
- The `carrier_spectrogram.py` is the canonical spectrogram implementation.
- Upload functionality requires SSH keys and PSWS credentials.
