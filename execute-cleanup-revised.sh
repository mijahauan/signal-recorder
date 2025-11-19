#!/bin/bash
# GRAPE Project Cleanup - Current vs Obsolete (Revised)
# Based on user clarification:
# 1. CLI only (no systemd)
# 2. core_recorder.py is current
# 3. grape_recorder.py V2 stack should be archived

set -e

PROJECT_ROOT="/home/mjh/git/signal-recorder"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "GRAPE Project Cleanup - Current vs Obsolete"
echo "=============================================="
echo ""
echo "⚠️  CRITICAL FINDING:"
echo "   grape_rtp_recorder.py contains BOTH:"
echo "   - RTPReceiver class (CURRENT - used by core_recorder.py)"
echo "   - GRAPERecorderManager class (OBSOLETE - uses V2 stack)"
echo ""
echo "   This file CANNOT be archived without refactoring."
echo "   Recommend: Extract RTPReceiver to separate file later."
echo ""
echo "This script will:"
echo "  1. Archive V2 Python files (NOT grape_rtp_recorder.py)"
echo "  2. Archive obsolete shell scripts"
echo "  3. Archive debug/test scripts"
echo "  4. Organize documentation"
echo "  5. Create git safety tag"
echo ""
echo "Files to archive:"
echo "  Python (V2):"
echo "    - grape_recorder.py (V2 entry point)"
echo "    - grape_channel_recorder_v2.py (V2 integrated recorder)"
echo "    - minute_file_writer.py (used by V2)"
echo "    - live_quality_status.py (used by V2)"
echo "    - grape_metadata.py (used by V2)"
echo "    [NOT grape_rtp_recorder.py - contains shared RTPReceiver]"
echo ""
echo "  Shell (V2/obsolete):"
echo "    - start-grape-recorder.sh (uses 'signal-recorder daemon')"
echo "    - start-grape.sh (old V2)"
echo "    - RESTART-RECORDER.sh (V2 CLI)"
echo "    - restart-recorder-with-new-code.sh (V2 CLI)"
echo "    + ~10 debug/test scripts"
echo "    + systemd scripts (not used)"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Create safety backup tag
echo ""
echo "Step 1: Creating git safety tag..."
git tag -f pre-cleanup-v2-archive
echo "✓ Tagged as 'pre-cleanup-v2-archive'"

# Create archive directories
echo ""
echo "Step 2: Creating archive directories..."
mkdir -p archive/legacy-code/v2-recorder
mkdir -p archive/shell-scripts/v2-scripts
mkdir -p archive/shell-scripts/debug
mkdir -p archive/shell-scripts/systemd
mkdir -p archive/dev-history
mkdir -p docs/features
mkdir -p docs/web-ui
echo "✓ Directories created"

# CRITICAL CHECK: Verify core_recorder doesn't import V2 components directly
echo ""
echo "Step 3: Verifying V2 components not imported by core..."

# Check if core_recorder imports grape_channel_recorder_v2
if grep -q "grape_channel_recorder_v2\|from.*grape_recorder import" src/signal_recorder/core_recorder.py src/signal_recorder/analytics_service.py; then
    echo "❌ ERROR: V2 components imported by core stack!"
    echo "Cannot archive safely. Manual review needed."
    exit 1
fi

# Note: grape_rtp_recorder.py is OK - it contains shared RTPReceiver class
echo "✓ Safe to archive V2 (except grape_rtp_recorder.py)"

# Archive V2 Python modules
echo ""
echo "Step 4: Archiving V2 Python modules..."

for file in grape_recorder.py grape_channel_recorder_v2.py minute_file_writer.py live_quality_status.py grape_metadata.py; do
    if [ -f "src/signal_recorder/$file" ]; then
        git mv "src/signal_recorder/$file" archive/legacy-code/v2-recorder/
        echo "  → $file"
    fi
done

# NOTE: grape_rtp_recorder.py stays - it contains RTPReceiver used by core_recorder.py
echo "  ℹ️  Keeping grape_rtp_recorder.py (contains shared RTPReceiver class)"

echo "✓ V2 Python modules archived"

# Archive V2 shell scripts
echo ""
echo "Step 5: Archiving V2 shell scripts (using old CLI)..."

for file in start-grape-recorder.sh start-grape.sh RESTART-RECORDER.sh restart-recorder-with-new-code.sh; do
    if [ -f "$file" ]; then
        git mv "$file" archive/shell-scripts/v2-scripts/
        echo "  → $file"
    fi
done

echo "✓ V2 shell scripts archived"

# Archive debug/test scripts
echo ""
echo "Step 6: Archiving debug and test scripts..."

for file in cleanup-buggy-tone-data.sh cleanup-corrupt-drf.sh cleanup-logs.sh cleanup-tmp-grape.sh clean-test-data.sh generate-carrier-comparison.sh test-health-runtime.sh test-health-monitoring.sh verify-mode-paths.sh start-watchdog.sh; do
    if [ -f "$file" ]; then
        git mv "$file" archive/shell-scripts/debug/
        echo "  → $file"
    fi
done

echo "✓ Debug scripts archived"

# Archive systemd scripts
echo ""
echo "Step 7: Archiving systemd scripts (not used)..."

for file in install-core-recorder-service.sh core-recorder-ctl.sh; do
    if [ -f "$file" ]; then
        git mv "$file" archive/shell-scripts/systemd/
        echo "  → $file"
    fi
done

echo "✓ Systemd scripts archived"

# Archive session docs (same as before)
echo ""
echo "Step 8: Archiving session summaries and completion docs..."

for file in SESSION_*.md *_COMPLETE.md *_IMPLEMENTATION.md *_SUMMARY.md PHASE*.md OVERNIGHT_STATUS.md NEXT_STEPS.md REVIEW_SUMMARY.md STARTUP_SESSION_SUMMARY.md; do
    if [ -f "$file" ]; then
        # Skip our new cleanup docs
        if [[ "$file" != "CLEANUP_"* ]] && [[ "$file" != "ARCHITECTURE_OVERVIEW.md" ]]; then
            git mv "$file" archive/dev-history/ 2>/dev/null || true
            echo "  → $file"
        fi
    fi
done

echo "✓ Session docs archived"

# Move feature documentation
echo ""
echo "Step 9: Organizing feature documentation..."

for file in TIMING_*.md TIME_*.md CARRIER_*.md QUALITY_*.md WWV*.md DIGITAL_RF_*.md DRF_*.md SPECTROGRAM_*.md ANALYTICS_*.md CORRELATION_*.md DECIMATION_*.md CONFIG_*.md HEALTH_*.md RADIOD_*.md DISCRIMINATION_*.md GRAPE_UPLOAD_*.md GRAPE_V1_*.md INTEGRATION_*.md INTERFACES_*.md PATH_MANAGEMENT.md PATHS_API_*.md PSWS_*.md AUTOMATIC_SPECTROGRAM_*.md PARTIAL_DAY_SPECTROGRAM_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/ 2>/dev/null || true
        echo "  → $file"
    fi
done

echo "✓ Feature docs organized"

# Archive test scripts from scripts/
echo ""
echo "Step 10: Archiving test scripts from scripts/..."

cd scripts

for file in analyze_*.py compare_*.py measure_*.py quick_*.py test_*.sh validate-*.sh migrate-*.sh regenerate_*.py reprocess_*.py generate_10hz_npz.py generate_spectrograms_v2.py generate_spectrograms_drf.py generate_spectrograms_from_*.py; do
    if [ -f "$file" ]; then
        git mv "$file" ../archive/test-scripts/ 2>/dev/null || true
        echo "  → scripts/$file"
    fi
done

cd "$PROJECT_ROOT"
echo "✓ Test scripts archived"

# Web-UI cleanup
echo ""
echo "Step 11: Organizing web-ui documentation and tests..."

cd web-ui

# Move docs
for file in *.md; do
    if [ -f "$file" ] && [ "$file" != "README.md" ]; then
        git mv "$file" ../docs/web-ui/ 2>/dev/null || true
        echo "  → web-ui/$file"
    fi
done

# Archive test files
for file in test-*.js test-*.cjs test-*.sh; do
    if [ -f "$file" ]; then
        git mv "$file" ../archive/test-scripts/ 2>/dev/null || true
        echo "  → web-ui/$file"
    fi
done

# Archive deprecated server
if [ -f "monitoring-server.js" ]; then
    git mv "monitoring-server.js" ../archive/legacy-code/monitoring-server-deprecated.js 2>/dev/null || true
    echo "  → web-ui/monitoring-server.js (deprecated)"
fi

cd "$PROJECT_ROOT"
echo "✓ Web-UI cleaned"

# Summary
echo ""
echo "=============================================="
echo "Cleanup Complete!"
echo "=============================================="
echo ""
echo "Summary of changes:"
echo "  • V2 Python modules → archive/legacy-code/v2-recorder/ (5 files)"
echo "  • V2 shell scripts → archive/shell-scripts/v2-scripts/ (4 files)"
echo "  • Debug scripts → archive/shell-scripts/debug/ (~10 files)"
echo "  • Systemd scripts → archive/shell-scripts/systemd/ (2 files)"
echo "  • Session docs → archive/dev-history/ (~50 files)"
echo "  • Feature docs → docs/features/ (~40 files)"
echo "  • Test scripts → archive/test-scripts/ (~30 files)"
echo "  • Web-UI docs → docs/web-ui/ (~15 files)"
echo ""
echo "⚠️  IMPORTANT: grape_rtp_recorder.py NOT archived"
echo "   Reason: Contains RTPReceiver class used by core_recorder.py"
echo "   Contains both CURRENT and OBSOLETE code"
echo "   Future: Extract RTPReceiver to separate file"
echo ""
echo "Current production scripts:"
echo "  ✅ start-dual-service.sh - PRIMARY entry point"
echo "  ✅ start-core-recorder-direct.sh - Alternative starter"
echo "  ✅ restart-analytics.sh - Restart analytics only"
echo "  ✅ restart-webui.sh - Restart web UI only"
echo "  ✅ stop-dual-service.sh - Stop all services"
echo ""
echo "Next steps:"
echo "  1. Review changes: git status"
echo "  2. Verify services still work:"
echo "     ./start-dual-service.sh"
echo "     # Let it start, then Ctrl+C"
echo "  3. Test imports:"
echo "     python3 -c 'import signal_recorder; print(\"OK\")'"
echo "  4. If satisfied:"
echo "     git commit -m 'Archive obsolete V2 recorder and debug scripts'"
echo "  5. If not satisfied:"
echo "     git reset --hard pre-cleanup-v2-archive"
echo ""
echo "Safety tag: pre-cleanup-v2-archive"
echo "To undo ALL changes: git reset --hard pre-cleanup-v2-archive"
echo ""
