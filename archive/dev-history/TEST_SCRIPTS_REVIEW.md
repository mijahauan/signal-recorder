# Test Scripts Review - Nov 18, 2025

**Purpose**: Identify which test scripts are relevant to current architecture and archive the rest

---

## Current Architecture

**Production**: Core Recorder + Analytics Service split  
**Components in use**:
- `CoreRecorder` - RTP reception, NPZ writing
- `AnalyticsService` - Tone detection, decimation, quality metrics
- `MultiStationToneDetector` - WWV/CHU/WWVH detection
- Path management, Digital RF writing

**Archived**: V1/V2 monolithic recorders, `GRAPERecorderManager`, `GRAPEChannelRecorderV2`

---

## Test Scripts Analysis

### ✅ Keep - Current Architecture Tests

| File | Size | Purpose | Status |
|------|------|---------|--------|
| **test-core-recorder.py** | 5.9K | Tests CoreNPZWriter, PacketResequencer | ✅ KEEP - Core components |
| **test-analytics-service.py** | 6.6K | Tests analytics service NPZ reading | ✅ KEEP - Analytics tests |
| **test-wwvh-discrimination.py** | 11K | Tests MultiStationToneDetector, WWV/WWVH separation | ✅ KEEP - Current feature |
| **test-drf-integration.py** | 5.5K | Tests Digital RF integration | ✅ KEEP - Future upload |

### 🔍 Review - Possibly Useful

| File | Size | Purpose | Recommendation |
|------|------|---------|----------------|
| **test-drf-writer.py** | 4.7K | Tests DRF writer component | Review - May be superseded by test-drf-integration.py |
| **test-psws-format.py** | 3.3K | Tests PSWS upload format | Keep if PSWS upload planned, else archive |
| **test_upload.py** | 8.4K | Tests upload manager | Keep if upload active, else archive |
| **test_upload_from_config.py** | 4.5K | Tests upload config loading | Keep if upload active, else archive |

### 🗑️ Archive - Legacy/V1/V2 Components

| File | Size | Purpose | Reason to Archive |
|------|------|---------|-------------------|
| **test_grape_recorder.py** | 4.9K | Tests old grape_recorder module | Uses GRAPERecorderManager (V2) |
| **test_digital_rf_write.py** | 3.0K | Tests old DRF writing | Uses GRAPERecorderManager (V2) |
| **test_grape_components.py** | 9.5K | Tests old GRAPE components | Tests V2/V1 components |
| **test_resampler.py** | 2.6K | Tests old Resampler class | From grape_rtp_recorder (V2) |

### 🔬 Archive - Low-Level RTP Diagnostic Scripts

| File | Size | Purpose | Reason to Archive |
|------|------|---------|-------------------|
| **test_am_preset.py** | 4.2K | RTP capture and AM demod test | Diagnostic script, not automated test |
| **test_custom_header.py** | 4.1K | RTP header analysis | Diagnostic script |
| **test_payload_format.py** | 2.4K | RTP payload format test | Diagnostic script |
| **test_wwv_vs_wwvh.py** | 5.1K | WWV vs WWVH frequency test | Diagnostic script, superseded by discrimination |

---

## Categorization Summary

### Keep at Root (5-8 files)
```
Core Architecture Tests:
├── test-core-recorder.py          # CoreRecorder, NPZ writer
├── test-analytics-service.py      # Analytics service
└── test-wwvh-discrimination.py    # WWV/WWVH detection

Digital RF / Upload Tests (if active):
├── test-drf-integration.py        # DRF integration
├── test-drf-writer.py              # DRF writer (if not redundant)
├── test-psws-format.py             # PSWS format (if upload planned)
├── test_upload.py                  # Upload manager (if active)
└── test_upload_from_config.py      # Upload config (if active)
```

### Archive to archive/test-scripts/ (8 files)
```
Legacy Component Tests:
├── test_grape_recorder.py          # V2 GRAPERecorderManager
├── test_digital_rf_write.py        # V2 DRF writing
├── test_grape_components.py        # V2/V1 components
└── test_resampler.py               # V2 Resampler

Diagnostic Scripts:
├── test_am_preset.py               # RTP/AM diagnostic
├── test_custom_header.py           # RTP header diagnostic
├── test_payload_format.py          # RTP payload diagnostic
└── test_wwv_vs_wwvh.py             # Frequency discrimination diagnostic
```

---

## Recommended Actions

### Phase 1: Archive Legacy Tests

**Move to archive/test-scripts/**:
```bash
git mv test_grape_recorder.py archive/test-scripts/
git mv test_digital_rf_write.py archive/test-scripts/
git mv test_grape_components.py archive/test-scripts/
git mv test_resampler.py archive/test-scripts/
```

**Reason**: Test V2/V1 components that have been archived

### Phase 2: Archive Diagnostic Scripts

**Move to archive/test-scripts/**:
```bash
git mv test_am_preset.py archive/test-scripts/
git mv test_custom_header.py archive/test-scripts/
git mv test_payload_format.py archive/test-scripts/
git mv test_wwv_vs_wwvh.py archive/test-scripts/
```

**Reason**: One-off diagnostic scripts, not automated tests. RTP bugs are fixed, WWV/WWVH discrimination is now in analytics service.

### Phase 3: Review Upload Tests (User Decision Needed)

**Question**: Is upload functionality actively used/planned?

**If YES** (upload active):
- Keep: `test_upload.py`, `test_upload_from_config.py`, `test-psws-format.py`

**If NO** (upload not yet implemented):
- Archive all three to `archive/test-scripts/`

**If UNSURE**:
- Keep `test-psws-format.py` (validates output format)
- Archive `test_upload.py`, `test_upload_from_config.py` (can restore when needed)

### Phase 4: Review DRF Writer

**Question**: Is `test-drf-writer.py` redundant with `test-drf-integration.py`?

**Recommendation**: 
- If `test-drf-integration.py` covers DRF writer functionality → Archive `test-drf-writer.py`
- Otherwise → Keep both

---

## Questions for User

Before proceeding with archival, please clarify:

1. **Upload Status**: 
   - Is upload functionality currently active?
   - Should we keep upload-related tests at root?

2. **DRF Writer**:
   - Is `test-drf-writer.py` still needed alongside `test-drf-integration.py`?

3. **PSWS Format**:
   - Is PSWS upload format validation still relevant?

---

## Expected Result

**Root directory** (after cleanup):
```
Current Test Scripts (5-8 files):
- test-core-recorder.py
- test-analytics-service.py
- test-wwvh-discrimination.py
- test-drf-integration.py
- [test-drf-writer.py] - if needed
- [test-psws-format.py] - if upload planned
- [test_upload.py] - if upload active
- [test_upload_from_config.py] - if upload active
```

**Archived** (8 files minimum):
- 4 legacy V2/V1 component tests
- 4 diagnostic RTP scripts

**Benefit**: 
- Clear which tests are for current architecture
- Legacy tests preserved in archive
- Can still run diagnostic scripts if needed

---

## Git Activity Analysis

Recent commits touching test files:
```
Nov 2024: test-wwvh-discrimination.py - WWV/WWVH discrimination
Nov 2024: test-core-recorder.py - Core/Analytics split
Nov 2024: test_wwv_vs_wwvh.py - Frequency diagnostic
Nov 2024: test_payload_format.py - RTP payload fix
Nov 2024: test_resampler.py - Resampler diagnostic
```

**Most active**:
- test-core-recorder.py (current architecture)
- test-analytics-service.py (current architecture)
- test-wwvh-discrimination.py (current feature)

**One-time diagnostics**:
- test_wwv_vs_wwvh.py (diagnostic, problem solved)
- test_payload_format.py (diagnostic, RTP bug fixed)
- test_resampler.py (diagnostic, resampler validated)

---

## Execution Plan

### Step 1: Archive Confirmed Legacy (No Questions)
```bash
# Create archive directory if needed
mkdir -p archive/test-scripts

# Archive V2/V1 component tests
git mv test_grape_recorder.py archive/test-scripts/
git mv test_digital_rf_write.py archive/test-scripts/
git mv test_grape_components.py archive/test-scripts/
git mv test_resampler.py archive/test-scripts/

# Archive diagnostic scripts
git mv test_am_preset.py archive/test-scripts/
git mv test_custom_header.py archive/test-scripts/
git mv test_payload_format.py archive/test-scripts/
git mv test_wwv_vs_wwvh.py archive/test-scripts/
```

**Result**: 8 files archived

### Step 2: User Decides on Upload Tests

Based on user input, either:
- Keep at root (if upload active)
- Archive to archive/test-scripts/ (if not yet used)

### Step 3: Commit

```bash
git commit -m "Archive legacy and diagnostic test scripts

Archived to archive/test-scripts/:
- Legacy V2/V1 tests: test_grape_recorder, test_digital_rf_write, 
  test_grape_components, test_resampler
- Diagnostic scripts: test_am_preset, test_custom_header, 
  test_payload_format, test_wwv_vs_wwvh

Kept at root (current architecture):
- test-core-recorder.py (CoreRecorder/NPZ)
- test-analytics-service.py (Analytics)
- test-wwvh-discrimination.py (WWV/WWVH detection)
- test-drf-integration.py (Digital RF)
[+ upload tests if decided to keep]

All tests preserved in archive for future reference."
```

---

## Status

**Analysis**: ✅ Complete  
**User Input Needed**: Upload functionality status  
**Ready to Execute**: Archive of 8 confirmed obsolete files

---

**Next Step**: Await user confirmation on upload test status, then execute archival.
