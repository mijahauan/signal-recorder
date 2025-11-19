# Codebase Cleanup Summary

**Date:** November 6, 2025  
**Purpose:** Archive development artifacts to declutter the workspace

## Overview

This cleanup archives ~70 development files into an organized structure while preserving historical context. No files are deleted - everything is moved to `archive/` for future reference.

## Archive Structure Created

```
archive/
├── dev-history/           # Historical bug fixes, migrations, session notes
├── test-scripts/          # Development test and diagnostic scripts  
├── shell-scripts/         # Development shell scripts
└── legacy-code/           # Old C code, deprecated implementations

docs/archive/              # Development session documentation (already exists)
```

## Files Being Archived

### Development History (→ archive/dev-history/)
- **Bug fixes:** CRITICAL-BUG-FIX.md, AUDIO-FIX-SUMMARY.md, etc.
- **Migrations:** MIGRATION-COMPLETE.md, KA9Q-MIGRATION.md, etc.
- **Audits:** CODEBASE_AUDIT.md, DATA-STORAGE-AUDIT.md, etc.
- **Planning:** REFACTORING-PLAN.md, SECURITY-FIXES-PLAN.md, etc.

**Total:** 20 files documenting completed work

### Test Scripts (→ archive/test-scripts/)
- **Root test-*.py files:** 22 files
- **Debug scripts:** 11 files  
- **Scripts directory tests:** 8 files

**Total:** 41 development test/diagnostic scripts

### Shell Scripts (→ archive/shell-scripts/)
- **Development tools:** check_radiod_bandwidth.sh, debug-radiod-packets.sh, etc.
- **Old setup scripts:** setup.sh, setup-linux-dev.sh
- **Test runners:** test-channel-creation.sh, watch-tone-detection.sh

**Total:** 12 shell scripts

### Legacy Code (→ archive/legacy-code/)
- **C implementations:** rx888.c, rtp.c (reference code)
- **Headers:** rx888.h, rtp.h
- **Artifacts:** signal-recorder-complete.tar.gz

**Total:** 5 files

### Docs Archive (→ docs/archive/)
- **Session notes:** SESSION_SUMMARY_2024-11-03.md
- **Phase completion:** PHASE1_RESEQUENCING_COMPLETE.md, PHASE2_TIME_SNAP_COMPLETE.md
- **Development artifacts:** 10_SECOND_DETECTION_WINDOW.md, etc.

**Total:** 6 documentation files

## Files Remaining in Root

After cleanup, the root directory will contain only essential files:

**Documentation (13 files):**
- README.md
- ARCHITECTURE.md
- INSTALLATION.md
- INSTALLATION-SYSTEMD.md
- CONFIG_ARCHITECTURE.md
- DEPENDENCIES.md
- LICENSE
- MANIFEST.in
- package.json
- pnpm-lock.yaml
- requirements.txt
- requirements-dev.txt
- setup.py

**Operational Scripts (4 files):**
- start-grape.sh
- start-watchdog.sh
- install-linux.sh
- cleanup-codebase.sh (this cleanup script)

**Current Tests (8 files):**
- test_grape_recorder.py
- test_grape_components.py
- test_digital_rf_write.py
- test_resampler.py
- test_upload.py
- test_upload_from_config.py
- test_am_preset.py
- test_custom_header.py
- test_payload_format.py
- test_wwv_vs_wwvh.py

**Systemd Services (2 files):**
- signal-recorder-daemon.service
- signal-recorder-web.service

**Total:** ~30 essential files (down from ~80)

## Usage

### Preview Changes (Dry Run)
```bash
./cleanup-codebase.sh --dry-run
```

This shows exactly what will be moved without making any changes.

### Execute Cleanup
```bash
./cleanup-codebase.sh
```

Moves all files to the archive structure.

### Help
```bash
./cleanup-codebase.sh --help
```

## Impact

✅ **Cleaner workspace** - Root directory becomes scannable  
✅ **Preserved history** - All files archived, not deleted  
✅ **Organized structure** - Clear categorization by purpose  
✅ **Git intact** - All changes tracked in version control  
✅ **Reversible** - Files can be restored if needed  

## What to Do After Cleanup

1. **Review the archive** - Verify important files were moved correctly
2. **Update .gitignore** - Add build artifacts, venv/, etc.
3. **Clean up empty dirs** - The script removes some, check for others
4. **Commit changes** - Git commit with message like "Archive development artifacts"
5. **Optional:** Create README_ARCHIVE.md in root pointing to archive structure

## Rationale

These files document valuable development history but clutter the active workspace:
- Bug fixes that are now implemented
- Migration documentation for completed work
- One-off test scripts for specific investigations
- Development tools that served their purpose

Archiving (not deleting) preserves this context while keeping the active codebase focused on current/operational code.

## Questions?

See individual README.md files in each archive/ subdirectory for details on what's stored there.

---

**Created:** November 6, 2025  
**Script:** cleanup-codebase.sh
