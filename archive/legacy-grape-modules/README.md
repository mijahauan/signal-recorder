# Legacy GRAPE Modules (Archived 2025-12-04)

These modules have been superseded by the Three-Phase Pipeline architecture.

## Archived Files

| File | Reason | Replacement |
|------|--------|-------------|
| `core_npz_writer.py` | NPZ format replaced by Digital RF | `raw_archive_writer.py` |
| `grape_npz_writer.py` | Old segment writer for NPZ | `raw_archive_writer.py` |
| `grape_recorder.py` | Two-phase recorder design | `core_recorder.py` + three-phase pipeline |
| `corrected_product_generator.py` | Superseded | `phase3_product_engine.py` |
| `digital_rf_writer.py` | Superseded by batch writer | `drf_batch_writer.py` |
| `drf_writer_service.py` | Streaming mode, batch preferred | `phase3_product_engine.py` |
| `startup_tone_detector.py` | Merged into Phase 2 | `phase2_temporal_engine.py` |
| `test_grape_refactor.py` | Old refactor tests | N/A |

## Three-Phase Architecture

The new architecture separates concerns into three phases:

1. **Phase 1 (Core Recording)**: `raw_archive_writer.py`, `core_recorder.py`
   - Writes 20 kHz IQ to Digital RF format
   - System time only (no UTC corrections)
   - Immutable archive

2. **Phase 2 (Analytics)**: `analytics_service.py`, `phase2_temporal_engine.py`
   - Reads Phase 1, produces D_clock
   - Timing analysis, tone detection, discrimination
   - Output: CSV/JSON timing data

3. **Phase 3 (Products)**: `phase3_product_engine.py`, `spectrogram_generator.py`
   - Reads Phase 1 + Phase 2 D_clock
   - Decimates 20 kHz → 10 Hz
   - Produces PSWS-compatible DRF + spectrograms

## Recovery

If you need to restore these modules:

```bash
# Copy back a single file
cp archive/legacy-grape-modules/grape_recorder.py src/grape_recorder/grape/

# Or restore all
cp archive/legacy-grape-modules/*.py src/grape_recorder/grape/
```

Then update `src/grape_recorder/grape/__init__.py` to re-add the imports.
