# 🧹 Project Cleanup - Start Here

## TL;DR

Your project is cluttered with:
- **Old V2 recorder** (grape_recorder.py, grape_channel_recorder_v2.py) - **OBSOLETE**
- **70+ docs at root** - Should be organized
- **30+ shell scripts** - Mix of current and obsolete
- **Dozens of debug scripts** - One-time use

**Current system:**
- `start-dual-service.sh` → `core_recorder.py` + `analytics_service.py`

---

## Execute Cleanup (Recommended)

```bash
./execute-cleanup-revised.sh
```

**Time:** ~30 seconds  
**Risk:** Very low (creates git tag, all reversible)

---

## What Gets Archived

### V2 Recorder Stack → `archive/legacy-code/v2-recorder/`
- grape_recorder.py
- grape_channel_recorder_v2.py  
- minute_file_writer.py
- live_quality_status.py
- grape_metadata.py

### Obsolete Scripts → `archive/shell-scripts/`
- V2 scripts (start-grape-recorder.sh, etc.)
- Debug scripts (cleanup-*.sh, test-*.sh)
- Systemd scripts (not used)

### Documentation → Organized
- ~50 session docs → `archive/dev-history/`
- ~40 feature docs → `docs/features/`
- ~30 test scripts → `archive/test-scripts/`

---

## What Stays (Protected)

### Current Python Code
```
✅ core_recorder.py         - Current recorder
✅ analytics_service.py     - Analytics
✅ All other modules        - Config, paths, etc.
⚠️  grape_rtp_recorder.py   - Has both current and obsolete code
```

### Current Scripts
```
✅ start-dual-service.sh            - PRIMARY
✅ start-core-recorder-direct.sh    
✅ restart-analytics.sh             
✅ restart-webui.sh                 
✅ stop-dual-service.sh             
```

### Core Docs
```
✅ README.md, CONTEXT.md, ARCHITECTURE.md, etc.
```

---

## After Cleanup

Root directory will have:
- **7 core docs** (vs 70+ before)
- **7 production scripts** (vs 30+ mixed before)
- **No V2 confusion** (archived)

---

## Critical Finding

**grape_rtp_recorder.py** contains BOTH:
- `RTPReceiver` class (CURRENT - used by core_recorder.py)
- `GRAPERecorderManager` class (OBSOLETE - uses V2 stack)

**Cannot archive** without extracting RTPReceiver first.  
File stays as-is for now.

---

## Verify After Cleanup

```bash
# Test it works
./start-dual-service.sh
# Ctrl+C after it starts

# Commit
git commit -m "Archive obsolete V2 recorder"

# Or undo everything
git reset --hard pre-cleanup-v2-archive
```

---

## Questions?

- **Full details:** `CLEANUP_PLAN_FINAL.md`
- **Script:** `./execute-cleanup-revised.sh`
- **Undo:** `git reset --hard pre-cleanup-v2-archive`
