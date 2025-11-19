# Cleanup Quick Start

## TL;DR

Your project has **70+ markdown docs** cluttering the root and **30+ test scripts** mixed with production code. This cleanup moves them to organized locations **without deleting anything**.

---

## Execute Cleanup (Recommended)

```bash
cd /home/mjh/git/signal-recorder
./execute-cleanup.sh
```

**What it does:**
- ✅ Moves ~50 session docs to `archive/dev-history/`
- ✅ Moves ~40 feature docs to `docs/features/`
- ✅ Moves ~30 test scripts to `archive/test-scripts/`
- ✅ Organizes web-ui docs to `docs/web-ui/`
- ✅ Creates git safety tag `pre-cleanup-backup`
- ✅ **NO CODE CHANGES** - only documentation organization
- ✅ **NO DELETIONS** - everything preserved in archive
- ✅ **100% REVERSIBLE** - git tag to restore

**Time:** ~30 seconds

---

## Undo If Needed

```bash
git reset --hard pre-cleanup-backup
```

This restores everything exactly as it was.

---

## What Gets Moved

### Session Docs → `archive/dev-history/`
```
SESSION_*.md
*_COMPLETE.md
*_IMPLEMENTATION.md
*_SUMMARY.md
OVERNIGHT_STATUS.md, NEXT_STEPS.md, etc.
```

### Feature Docs → `docs/features/`
```
TIMING_*.md, CARRIER_*.md, QUALITY_*.md
WWV*.md, DIGITAL_RF_*.md, DRF_*.md
SPECTROGRAM_*.md, CONFIG_*.md, etc.
```

### Test Scripts → `archive/test-scripts/`
```
analyze_*.py, compare_*.py, measure_*.py
test_*.sh, validate-*.sh
regenerate_*.py, reprocess_*.py
generate_spectrograms_v2.py (old version)
```

### Web-UI → `docs/web-ui/` + archive
```
web-ui/*.md → docs/web-ui/
web-ui/test-*.* → archive/test-scripts/
web-ui/monitoring-server.js → archive/legacy-code/ (deprecated)
```

---

## What Does NOT Get Moved (Active Code)

- ✅ **ALL source code** in `src/signal_recorder/`
- ✅ **ALL production scripts** (generate_spectrograms.py, etc.)
- ✅ **Core docs** (README.md, CONTEXT.md, ARCHITECTURE.md, etc.)
- ✅ **Systemd services**
- ✅ **Config files**
- ✅ **Web UI production files** (monitoring-server-v3.js, HTML pages, etc.)

**Result:** Your systems continue working exactly as before.

---

## Critical Finding

Your codebase has **TWO complete recording systems:**

1. **V2 Stack** (currently running)
   - `grape_recorder.py` → `grape_channel_recorder_v2.py`
   - Used by systemd
   - ✅ **KEEP - ACTIVE**

2. **Core Stack** (newer design, Nov 17-18)
   - `core_recorder.py` → `packet_resequencer.py`
   - Cleaner architecture
   - Not yet deployed
   - ⚠️ **KEEP - FUTURE**

**Don't delete either!** Core is meant to replace V2 eventually.

---

## After Cleanup

### Verify Everything Works
```bash
# 1. Check changes
git status

# 2. Test core recorder
systemctl status grape-core-recorder

# 3. Test web UI
cd web-ui && node monitoring-server-v3.js
# Press Ctrl+C after it starts

# 4. Test imports
python3 -c "import signal_recorder; print('OK')"
```

### Commit Changes
```bash
git commit -m "Cleanup: archive obsolete docs and test scripts"
```

### Or Undo
```bash
git reset --hard pre-cleanup-backup
```

---

## Questions?

- **Full details:** Read `CLEANUP_PROPOSAL.md`
- **Summary:** Read `CLEANUP_SUMMARY_NOV18.md`
- **Help:** `./execute-cleanup.sh --help` (if we add it)

---

**Time to execute:** 30 seconds  
**Risk level:** Very low (reversible)  
**Benefit:** Clean, organized workspace
