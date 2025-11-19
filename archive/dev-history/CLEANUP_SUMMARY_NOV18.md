# Project Cleanup Summary - November 18, 2025

## Current Status: Analysis Complete, Ready for Cleanup

This document summarizes the cleanup analysis performed on November 18, 2025 to address project clutter.

---

## Quick Start

**To execute the cleanup:**
```bash
./execute-cleanup.sh
```

This will:
1. Create a git safety tag `pre-cleanup-backup`
2. Move ~70 markdown docs to organized locations
3. Move ~30 test scripts to archive
4. Clean up web-ui test files
5. NO FILES DELETED - all changes reversible

**To review the detailed analysis:**
- Read `CLEANUP_PROPOSAL.md` for full breakdown

---

## Critical Finding: Two Recording Systems

The analysis revealed that the codebase contains TWO complete recording implementations:

### 1. V2 Stack (Currently Running) ✅ ACTIVE
- Files: `grape_recorder.py` → `grape_rtp_recorder.py` → `grape_channel_recorder_v2.py`
- Status: Production system, used by systemd
- Action: **KEEP - DO NOT DELETE**

### 2. Core/Analytics Split (Future) ⚠️ PLANNED
- Files: `core_recorder.py` → `packet_resequencer.py` + `core_npz_writer.py`
- Status: Newer design (Nov 17-18), not yet deployed
- Purpose: Cleaner separation of concerns
- Action: **KEEP - Future replacement for V2**

**Recommendation:** Keep BOTH stacks. Once Core is deployed to production, THEN archive V2.

---

## Safe Cleanup Actions (Automated)

The `execute-cleanup.sh` script performs these SAFE operations:

### 1. Session Documentation → `archive/dev-history/`
**~50 files** including:
- `SESSION_*.md` - Development session notes
- `*_COMPLETE.md` - Completion summaries
- `*_IMPLEMENTATION.md` - Implementation notes
- `*_SUMMARY.md` - Summary documents
- `PHASE*.md` - Phase completion docs
- `OVERNIGHT_STATUS.md`, `NEXT_STEPS.md`, etc.

**Why safe:** These document completed work, valuable history but clutter workspace.

### 2. Feature Documentation → `docs/features/`
**~40 files** including:
- `TIMING_*.md` - Timing feature docs
- `CARRIER_*.md` - Carrier channel docs
- `QUALITY_*.md` - Quality metrics docs
- `WWV*.md` / `WWVH*.md` - Tone detection docs
- `DIGITAL_RF_*.md` / `DRF_*.md` - Digital RF docs
- `SPECTROGRAM_*.md` - Spectrogram docs
- `CONFIG_*.md` - Configuration docs
- etc.

**Why safe:** These are feature docs, not core docs. Better organized in `docs/features/`.

### 3. Test Scripts → `archive/test-scripts/`
**~30 scripts** including:
- `analyze_*.py` - One-time analysis scripts
- `compare_*.py` - Comparison scripts
- `measure_*.py` - Measurement scripts
- `test_*.sh` - Test scripts
- `validate-*.sh` - Validation scripts
- `regenerate_*.py`, `reprocess_*.py` - Data migration (completed)
- `generate_spectrograms_v2.py`, `generate_spectrograms_drf.py` - Old versions

**Why safe:** These were for one-time investigations or are superseded by production scripts.

### 4. Web-UI Cleanup
**Files moved:**
- `web-ui/*.md` (except README.md) → `docs/web-ui/`
- `web-ui/test-*.js`, `test-*.cjs`, `test-*.sh` → `archive/test-scripts/`
- `web-ui/monitoring-server.js` → `archive/legacy-code/` (deprecated, file has warning)

**Files deleted:** (build artifacts, not in git)
- `monitoring-server.log`
- `build-output.txt`
- `cookies.txt`

**Why safe:** Test files archived, deprecated server marked as such, build artifacts cleaned.

---

## Files Explicitly NOT Touched (Active Code)

### Source Code - ALL KEPT
- **V2 Stack:** 8 files (grape_recorder, grape_rtp_recorder, grape_channel_recorder_v2, etc.)
- **Core Stack:** 3 files (core_recorder, packet_resequencer, core_npz_writer)
- **Analytics:** 7 files (analytics_service, tone_detector, decimation, etc.)
- **Shared:** 12 files (config_utils, paths, channel_manager, etc.)
- **Interfaces:** Entire directory
- **Legacy:** Entire directory (may have imports)

### Production Scripts - ALL KEPT
- `generate_spectrograms.py` - Used by systemd timer
- `monitor_radiod_health.py` - Used by systemd service
- `auto-generate-spectrograms.sh` - Production automation
- `show_quality_summary.py` - Admin tool
- `check_wwv_detections.sh` - Admin tool
- `backfill-now.sh` - Admin tool
- etc.

### Core Documentation - ALL KEPT
- `README.md`
- `CONTEXT.md`
- `ARCHITECTURE.md`
- `QUICK_START.md`
- `DEPENDENCIES.md`
- `INSTALLATION.md`
- `SYSTEMD_INSTALLATION.md`

### New Documentation - CREATED
- `CLEANUP_PROPOSAL.md` - Full analysis
- `CLEANUP_SUMMARY_NOV18.md` - This document
- `execute-cleanup.sh` - Automated cleanup script

---

## Before vs After

### Root Directory Markdown Files
- **Before:** 70+ markdown files
- **After:** ~7 core docs + CLEANUP_PROPOSAL.md

### Scripts Directory
- **Before:** ~30 scripts (mix of production/test)
- **After:** ~10 production/admin scripts

### Web-UI Directory
- **Before:** 18 markdown files
- **After:** README.md only (others moved to docs/)

---

## Safety Features

### Git Safety Tag
Before ANY changes, script creates: `git tag pre-cleanup-backup`

**To undo everything:**
```bash
git reset --hard pre-cleanup-backup
```

### All Changes Tracked
Every move is done with `git mv`, so:
- Full history preserved
- Changes visible in `git status`
- Can review before committing

### No Deletions
Script only MOVES files to archive, never deletes (except build artifacts not in git).

---

## Verification Steps (After Cleanup)

```bash
# 1. Check git status
git status

# 2. Verify core recorder works
systemctl status grape-core-recorder

# 3. Verify web UI works
cd web-ui && node monitoring-server-v3.js
# Press Ctrl+C after verifying it starts

# 4. Check imports work
python3 -c "import signal_recorder; print('OK')"

# 5. If everything looks good
git commit -m "Cleanup: archive obsolete docs and test scripts

- Moved ~50 session docs to archive/dev-history/
- Moved ~40 feature docs to docs/features/
- Moved ~30 test scripts to archive/test-scripts/
- Organized web-ui docs to docs/web-ui/
- All source code preserved
- All production scripts preserved
- No functionality changed"

# 6. If something broke
git reset --hard pre-cleanup-backup
```

---

## Remaining Work (Manual Decision Required)

### Question 1: Core Recorder Deployment
- **Current:** V2 stack in production
- **Future:** Core stack (cleaner design)
- **Decision needed:** When to switch? How to migrate?

### Question 2: Legacy Directory
- **Status:** Contains old app.py with imports
- **Decision needed:** Can it be fully archived?

### Question 3: Build System
- **Files:** setup.py, requirements.txt, package.json
- **Decision needed:** Are all three build systems needed?

---

## Files Created by This Analysis

1. **CLEANUP_PROPOSAL.md** (17KB) - Comprehensive analysis
   - Source code dependency analysis
   - Scripts categorization
   - Documentation organization plan
   - Risk assessment
   - Full implementation plan

2. **execute-cleanup.sh** (7KB) - Automated cleanup script
   - Safe archiving automation
   - Git safety tag creation
   - Progress reporting
   - Verification instructions

3. **CLEANUP_SUMMARY_NOV18.md** (this file) - Executive summary

---

## Contact / Questions

If you encounter issues:
1. Check `git status` for what changed
2. Review `CLEANUP_PROPOSAL.md` for rationale
3. Use `git reset --hard pre-cleanup-backup` to undo
4. Review individual archived files if needed

---

**Created:** November 18, 2025  
**Author:** Cascade AI Analysis  
**Status:** Ready for execution  
**Safety:** All changes reversible via git tag
