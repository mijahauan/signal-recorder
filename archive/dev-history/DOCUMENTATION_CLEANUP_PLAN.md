# Documentation Cleanup Plan

**Created**: Nov 18, 2025  
**Purpose**: Guide for archiving historical documentation now that we have distilled narratives

---

## New Core Documentation (KEEP)

These documents replace most of the historical archive:

1. **`OPERATIONAL_SUMMARY.md`** ← **NEW**
   - Current system configuration
   - 18 channels, 5 data products
   - Upload strategy and retention
   - **Purpose**: Quick operational overview

2. **`PROJECT_NARRATIVE.md`** ← **NEW**
   - Complete project history
   - All critical bugs and fixes
   - Architectural decisions
   - Lessons learned
   - **Replaces**: ~50 session summary files

3. **`TECHNICAL_REFERENCE.md`** ← **NEW**
   - Quick developer reference
   - Critical design principles
   - Common issues & debugging
   - **Replaces**: Various technical docs

4. **`CONTEXT.md`** (existing, keep)
   - System overview
   - Current architecture
   - API reference

5. **`ARCHITECTURE.md`** (existing, keep)
   - Detailed technical architecture
   - Module relationships

6. **`QUICK_START.md`** (existing, keep)
   - Getting started guide

7. **`README.md`** (existing, keep)
   - Project overview

8. **`DEPENDENCIES.md`** (existing, keep)
   - Installation requirements

9. **`INSTALLATION.md`** (existing, keep)
   - Setup instructions

---

## Files That Can Be Archived

### Session Summaries (Already Archived)

**Location**: `archive/dev-history/`

All session summaries are now **superseded by PROJECT_NARRATIVE.md**:

```
SESSION_2025-11-17_CARRIER_CHANNELS.md         → Ch. 5 of PROJECT_NARRATIVE
SESSION_2025-11-17_TONE_DETECTOR_FIX.md        → Ch. 5 of PROJECT_NARRATIVE
SESSION_2025-11-17_CARRIER_FIX_COMPLETE.md     → Ch. 5 of PROJECT_NARRATIVE
SESSION_SUMMARY_NOV13_2024.md                  → Ch. 2-4 of PROJECT_NARRATIVE
SESSION_SUMMARY_NOV9_2024.md                   → Ch. 3 of PROJECT_NARRATIVE
... (30+ more session files)
```

**Action**: ✅ Already in `archive/dev-history/` - Leave there

### Implementation Docs (Already Archived)

**Location**: `archive/dev-history/`

Now covered in PROJECT_NARRATIVE.md or CONTEXT.md:

```
CORE_RECORDER_IMPLEMENTATION.md                → Ch. 3 + CONTEXT.md
ANALYTICS_SERVICE_IMPLEMENTATION.md            → Ch. 3 + CONTEXT.md
TONE_DETECTOR_IMPLEMENTATION.md                → Ch. 4 + CONTEXT.md
WWVH_DISCRIMINATION_IMPLEMENTATION.md          → Ch. 4 + CONTEXT.md
HEALTH_MONITORING_IMPLEMENTATION.md            → CONTEXT.md
... (10+ more implementation files)
```

**Action**: ✅ Already in `archive/dev-history/` - Leave there

### Feature Docs (Already in docs/features/)

**Location**: `docs/features/`

Detailed feature documentation - **keep if still relevant**, **archive if superseded**:

#### Keep (Still Relevant)
- `AUTOMATIC_SPECTROGRAM_GENERATION.md` - Active feature
- `RADIOD_MONITORING_SYSTEM.md` - Active monitoring
- `WWVH_DISCRIMINATION_QUICKREF.md` - Quick reference

#### Can Archive (Covered in PROJECT_NARRATIVE/TECHNICAL_REFERENCE)
- `DIGITAL_RF_UPLOAD_TIMING.md` → Ch. 4 of PROJECT_NARRATIVE
- `CARRIER_TIME_BASIS_ANALYSIS.md` → Ch. 5 of PROJECT_NARRATIVE
- `DRF_TIMESTAMP_BUG_FIX.md` → Ch. 2 of PROJECT_NARRATIVE
- `PATHS_API_MIGRATION_AUDIT.md` → TECHNICAL_REFERENCE

**Action**: Review and selectively archive

---

## Root Directory Docs (Current State)

### Definitely Keep

1. **Core References** (System documentation)
   - `README.md`
   - `CONTEXT.md`
   - `ARCHITECTURE.md`
   - `PROJECT_NARRATIVE.md` ← **NEW**
   - `TECHNICAL_REFERENCE.md` ← **NEW**

2. **Getting Started**
   - `QUICK_START.md`
   - `INSTALLATION.md`
   - `DEPENDENCIES.md`
   - `STARTUP_GUIDE.md`

3. **Current Design**
   - `CORE_ANALYTICS_SPLIT_DESIGN.md` (foundational decision)

### Can Archive (Superseded by Narratives)

Move to `archive/dev-history/`:

1. **Session-Specific Docs**
   - `SESSION_2025-11-17_WEB_UI_SYNC.md` → Ch. 6 of PROJECT_NARRATIVE
   - `WEB_UI_V2_INTEGRATION_SESSION.md` → Ch. 6 of PROJECT_NARRATIVE

2. **Specific Feature Implementations**
   - `CARRIER_CHANNEL_ANALYTICS_IMPLEMENTATION.md` → Ch. 5 of PROJECT_NARRATIVE
   - `DISCRIMINATION_VISUALIZATION_IMPROVEMENTS.md` → Ch. 6 of PROJECT_NARRATIVE
   - `CORRELATION_ANALYSIS_COMPLETE.md` → TECHNICAL_REFERENCE
   - `QUALITY_ANALYSIS_INTEGRATION.md` → CONTEXT.md
   - `SPECTROGRAM_GENERATION_COMPLETE.md` → Ch. 6 of PROJECT_NARRATIVE
   - `TIMING_DASHBOARD_INTEGRATION.md` → Ch. 6 of PROJECT_NARRATIVE
   - `TONE_LOCKED_RENAME.md` → Ch. 4 of PROJECT_NARRATIVE

3. **Quick Fixes** (Historical)
   - `QUICK_FIX_SPECTROGRAM_GENERATION.md` → Covered in narrative
   - `RESTART-FOR-DIGITAL-RF.md` → Historical artifact
   - `REALTIME_DATA_VERIFICATION.md` → Standard practice now

4. **Web UI Protocols**
   - `WEB_UI_ANALYTICS_SYNC_PROTOCOL.md` → TECHNICAL_REFERENCE
   - `WEB_UI_API_PROPOSAL.md` → Implemented, covered in CONTEXT
   - `WEB_UI_DUAL_SERVICE_INTEGRATION.md` → Ch. 6 of PROJECT_NARRATIVE
   - `WEB_UI_IMPROVEMENTS_NOV13_2024.md` → Historical

5. **Test Results**
   - `SUMMARY_SCREEN_TEST_RESULTS.md` → Feature working, can archive
   - `QUALITY_DASHBOARD_QUICKSTART.md` → Could keep as user guide or archive

6. **Cleanup Docs** (Now Historical)
   - `CLEANUP_EXECUTION_SUMMARY.md` → One-time cleanup, archive
   - `CLEANUP_PLAN_FINAL.md` → One-time cleanup, archive
   - `CLEANUP_PROPOSAL.md` → One-time cleanup, archive
   - `CLEANUP_QUICKSTART.md` → One-time cleanup, archive
   - `CLEANUP_REVISED.md` → One-time cleanup, archive
   - `CLEANUP_SUMMARY.md` → One-time cleanup, archive
   - `CLEANUP_SUMMARY_NOV18.md` → One-time cleanup, archive
   - `START_HERE_CLEANUP.md` → One-time cleanup, archive

### Borderline (Review Case-by-Case)

**Operational guides** - Keep if actively used:
- `ARCHITECTURE_OVERVIEW.md` - Redundant with ARCHITECTURE.md?
- `SYSTEMD_INSTALLATION.md` - Keep if systemd deployment planned
- `INSTALLATION-SYSTEMD.md` - Keep if systemd deployment planned

---

## Recommended Actions

### Phase 1: Archive Cleanup Docs (Immediate)

```bash
# Move cleanup docs to archive
git mv CLEANUP_*.md START_HERE_CLEANUP.md archive/dev-history/
```

These were one-time cleanup documentation (Nov 18, 2025) now superseded by clean structure.

### Phase 2: Archive Session/Implementation Docs (Immediate)

```bash
# Already done - these are in archive/dev-history/
# Nothing to do
```

### Phase 3: Archive Superseded Feature Docs (Review First)

```bash
# Move to archive/dev-history/ (review each):
git mv SESSION_2025-11-17_WEB_UI_SYNC.md archive/dev-history/
git mv CARRIER_CHANNEL_ANALYTICS_IMPLEMENTATION.md archive/dev-history/
git mv DISCRIMINATION_VISUALIZATION_IMPROVEMENTS.md archive/dev-history/
git mv CORRELATION_ANALYSIS_COMPLETE.md archive/dev-history/
git mv QUALITY_ANALYSIS_INTEGRATION.md archive/dev-history/
git mv SPECTROGRAM_GENERATION_COMPLETE.md archive/dev-history/
git mv TIMING_DASHBOARD_INTEGRATION.md archive/dev-history/
git mv TONE_LOCKED_RENAME.md archive/dev-history/
git mv QUICK_FIX_SPECTROGRAM_GENERATION.md archive/dev-history/
git mv RESTART-FOR-DIGITAL-RF.md archive/dev-history/
git mv REALTIME_DATA_VERIFICATION.md archive/dev-history/
git mv WEB_UI_*.md archive/dev-history/
git mv SUMMARY_SCREEN_TEST_RESULTS.md archive/dev-history/
```

### Phase 4: Review Borderline Docs

**Decision needed**:
1. Keep `ARCHITECTURE_OVERVIEW.md` or merge into `ARCHITECTURE.md`?
2. Keep `SYSTEMD_INSTALLATION.md` for future deployment?
3. Keep `QUALITY_DASHBOARD_QUICKSTART.md` as user guide?

---

## Final Root Directory (Recommended)

### Core Documentation (9 files)
```
README.md                   # Project overview
OPERATIONAL_SUMMARY.md      # Current configuration (18 ch, 5 products) ← NEW
CONTEXT.md                  # System reference (existing)
ARCHITECTURE.md             # Technical details (existing)
PROJECT_NARRATIVE.md        # Complete history ← NEW
TECHNICAL_REFERENCE.md      # Developer quick ref ← NEW
QUICK_START.md              # Getting started (existing)
INSTALLATION.md             # Setup (existing)
DEPENDENCIES.md             # Requirements (existing)
```

**Optional** (if actively used):
```
CORE_ANALYTICS_SPLIT_DESIGN.md   # Foundational design doc
SYSTEMD_INSTALLATION.md          # If systemd deployment planned
STARTUP_GUIDE.md                 # If different from QUICK_START
```

**Total**: 9-12 markdown files at root (down from 60+)

---

## Benefits of This Cleanup

### Before (Nov 18, pre-narrative)
- 60+ markdown files at root
- Hard to find current architecture
- Session summaries mixed with references
- Redundant information across many docs

### After (Proposed)
- 9-12 core docs at root
- Clear hierarchy: Overview → Reference → Details
- Current state in OPERATIONAL_SUMMARY.md
- History in PROJECT_NARRATIVE.md
- Quick lookup in TECHNICAL_REFERENCE.md
- Historical details preserved in archive/

### For New Developers
- Start: `README.md`
- Setup: `QUICK_START.md` → `INSTALLATION.md`
- Overview: `OPERATIONAL_SUMMARY.md` (what does it do?)
- Understand: `PROJECT_NARRATIVE.md` (history + lessons)
- Reference: `TECHNICAL_REFERENCE.md` (how does it work?)
- Details: `CONTEXT.md` + `ARCHITECTURE.md`
- Historical: `archive/dev-history/` (if needed)

### For Maintenance
- Current architecture: `ARCHITECTURE.md` + `CONTEXT.md`
- Why decisions made: `PROJECT_NARRATIVE.md`
- Quick answers: `TECHNICAL_REFERENCE.md`
- Debugging: `TECHNICAL_REFERENCE.md` + logs

---

## Execution Script

```bash
#!/bin/bash
# archive-superseded-docs.sh

set -e

echo "Archiving superseded documentation..."

# Phase 1: Cleanup docs (one-time Nov 18 cleanup)
for file in CLEANUP_*.md START_HERE_CLEANUP.md; do
    [ -f "$file" ] && git mv "$file" archive/dev-history/ && echo "  → $file"
done

# Phase 2: Session and implementation docs
for file in SESSION_*.md *_COMPLETE.md *_IMPLEMENTATION.md CORRELATION_*.md; do
    [ -f "$file" ] && git mv "$file" archive/dev-history/ && echo "  → $file"
done

# Phase 3: Superseded feature docs
for file in QUICK_FIX_*.md RESTART-FOR-*.md REALTIME_*.md TONE_LOCKED_*.md; do
    [ -f "$file" ] && git mv "$file" archive/dev-history/ && echo "  → $file"
done

# Phase 4: Web UI docs (check if any left in root)
for file in WEB_UI_*.md; do
    [ -f "$file" ] && git mv "$file" archive/dev-history/ && echo "  → $file"
done

# Phase 5: Test results
for file in SUMMARY_SCREEN_TEST_RESULTS.md; do
    [ -f "$file" ] && git mv "$file" archive/dev-history/ && echo "  → $file"
done

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Root directory now has:"
ls -1 *.md | wc -l
echo "markdown files (target: 8-11)"
echo ""
echo "Review remaining files:"
ls -1 *.md
```

---

## Summary

**What PROJECT_NARRATIVE.md replaces**:
- All session summaries (~35 files)
- All implementation complete docs (~15 files)
- Bug fix documentation (~5 files)
- Architecture evolution docs (~10 files)

**What TECHNICAL_REFERENCE.md replaces**:
- Quick reference docs (~5 files)
- Common issues docs (~3 files)
- Debugging guides (~2 files)

**Total**: ~75 files of content distilled into 2 comprehensive documents + existing core docs.

**History preserved**: All archived in `archive/dev-history/` and `docs/features/`.

---

**Next Step**: Review this plan, then execute `archive-superseded-docs.sh` to complete cleanup.
