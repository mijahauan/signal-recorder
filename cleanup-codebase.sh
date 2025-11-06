#!/bin/bash
#
# GRAPE Signal Recorder - Codebase Cleanup Script
# Archives development artifacts to preserve history while decluttering workspace
#
# Usage:
#   ./cleanup-codebase.sh --dry-run    # Preview what will be moved
#   ./cleanup-codebase.sh              # Execute the cleanup
#   ./cleanup-codebase.sh --help       # Show this help
#

# Don't exit on error - we want to continue even if some files don't exist
# set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

DRY_RUN=false
MOVED_COUNT=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "GRAPE Signal Recorder - Codebase Cleanup Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run    Preview changes without moving files"
            echo "  --help       Show this help message"
            echo ""
            echo "This script archives development artifacts to keep the workspace clean"
            echo "while preserving historical context."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}==== DRY RUN MODE ====${NC}"
    echo "No files will be moved. This is a preview only."
    echo ""
fi

# Function to move file with logging
move_file() {
    local src="$1"
    local dest_dir="$2"
    
    if [ ! -f "$src" ]; then
        # Silently skip if file doesn't exist (may have been already moved/deleted)
        return
    fi
    
    if [ "$DRY_RUN" = true ]; then
        echo -e "${BLUE}Would move:${NC} $src → $dest_dir/"
    else
        mkdir -p "$dest_dir"
        mv "$src" "$dest_dir/"
        echo -e "${GREEN}Moved:${NC} $src → $dest_dir/"
    fi
    
    ((MOVED_COUNT++))
}

# Function to remove empty directory
remove_empty_dir() {
    local dir="$1"
    
    if [ ! -d "$dir" ]; then
        return
    fi
    
    if [ -z "$(ls -A "$dir")" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo -e "${BLUE}Would remove empty directory:${NC} $dir"
        else
            rmdir "$dir"
            echo -e "${GREEN}Removed empty directory:${NC} $dir"
        fi
    fi
}

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  GRAPE Signal Recorder - Codebase Cleanup${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Create archive structure
if [ "$DRY_RUN" = false ]; then
    mkdir -p archive/dev-history
    mkdir -p archive/test-scripts
    mkdir -p archive/shell-scripts
    mkdir -p archive/legacy-code
    echo -e "${GREEN}Created archive directory structure${NC}"
    echo ""
fi

# 1. Historical Bug Fix Documentation
echo -e "${YELLOW}[1/9] Archiving historical bug fix documentation...${NC}"
move_file "CRITICAL-BUG-FIX.md" "archive/dev-history"
move_file "CRITICAL-FIX-2025-10-31.md" "archive/dev-history"
move_file "AUDIO-FIX-SUMMARY.md" "archive/dev-history"
move_file "AUDIO-INVESTIGATION-SUMMARY.md" "archive/dev-history"
move_file "FINAL-AUDIO-FIX.md" "archive/dev-history"
move_file "TESTING-2025-10-30.md" "archive/dev-history"
move_file "WWV-TIMING-ANALYSIS.md" "archive/dev-history"
move_file "WWV-TONE-STATUS.md" "archive/dev-history"
echo ""

# 2. Completed Migration/Implementation Docs
echo -e "${YELLOW}[2/9] Archiving completed migration documentation...${NC}"
move_file "IMPLEMENTATION-COMPLETE.md" "archive/dev-history"
move_file "MIGRATION-COMPLETE.md" "archive/dev-history"
move_file "KA9Q-MIGRATION.md" "archive/dev-history"
move_file "KA9Q-PACKAGE-COMPLETE.md" "archive/dev-history"
move_file "REFACTORING-PLAN.md" "archive/dev-history"
move_file "SECURITY-FIXES-COMPLETE.md" "archive/dev-history"
move_file "SECURITY-FIXES-PLAN.md" "archive/dev-history"
move_file "SECURITY-FIXES-STATUS.md" "archive/dev-history"
move_file "SYSTEM-STATUS.md" "archive/dev-history"
echo ""

# 3. Audit/Planning Docs
echo -e "${YELLOW}[3/9] Archiving audit and planning documents...${NC}"
move_file "CODEBASE_AUDIT.md" "archive/dev-history"
move_file "DATA-STORAGE-AUDIT.md" "archive/dev-history"
move_file "DATA-STORAGE-CHANGES.md" "archive/dev-history"
move_file "PATHS_AND_DATA_FLOW.md" "archive/dev-history"
echo ""

# 4. Root Directory Test Scripts
echo -e "${YELLOW}[4/9] Archiving root directory test scripts...${NC}"
move_file "test-8khz-audio.py" "archive/test-scripts"
move_file "test-accumulator-bug.py" "archive/test-scripts"
move_file "test-actual-rate.py" "archive/test-scripts"
move_file "test-audio-direct.py" "archive/test-scripts"
move_file "test-chunked-processing.py" "archive/test-scripts"
move_file "test-continuous.py" "archive/test-scripts"
move_file "test-continuous-processing.py" "archive/test-scripts"
move_file "test-daemon.py" "archive/test-scripts"
move_file "test-discover.py" "archive/test-scripts"
move_file "test-exact-rate.py" "archive/test-scripts"
move_file "test-exact-same-data.py" "archive/test-scripts"
move_file "test-fixed-version.py" "archive/test-scripts"
move_file "test-iq-format.py" "archive/test-scripts"
move_file "test-large-buffer.py" "archive/test-scripts"
move_file "test-packet-timing.py" "archive/test-scripts"
move_file "test-raw-iq.py" "archive/test-scripts"
move_file "test-realtime-diagnostics.py" "archive/test-scripts"
move_file "test-rtp-continuity.py" "archive/test-scripts"
move_file "test-rtp-rate.py" "archive/test-scripts"
move_file "test-synchronous.py" "archive/test-scripts"
move_file "test-watchdog.py" "archive/test-scripts"
move_file "test-working-version.py" "archive/test-scripts"
echo ""

# 5. Debug/Diagnostic Scripts - Root
echo -e "${YELLOW}[5/9] Archiving debug and diagnostic scripts...${NC}"
move_file "debug-chunk-boundaries.py" "archive/test-scripts"
move_file "debug-queue-timing.py" "archive/test-scripts"
move_file "debug-signal-levels.py" "archive/test-scripts"
move_file "debug-synchronous.py" "archive/test-scripts"
move_file "diagnose_iq_spectrum.py" "archive/test-scripts"
move_file "diagnose_wwv_tone.py" "archive/test-scripts"
move_file "analyze-audio-quality.py" "archive/test-scripts"
move_file "capture-minute-tone.py" "archive/test-scripts"
move_file "inspect_samples.py" "archive/test-scripts"
move_file "plot_wwv_timing.py" "archive/test-scripts"
move_file "verify_iq_data.py" "archive/test-scripts"
echo ""

# 6. Debug/Diagnostic Scripts - scripts/
echo -e "${YELLOW}[6/9] Archiving scripts/ test files...${NC}"
move_file "scripts/debug_correlation.py" "archive/test-scripts"
move_file "scripts/debug_wwv_signal.py" "archive/test-scripts"
move_file "scripts/diagnose_signal.py" "archive/test-scripts"
move_file "scripts/test_phase1_modules.py" "archive/test-scripts"
move_file "scripts/test_v2_recorder.py" "archive/test-scripts"
move_file "scripts/test_v2_recorder_filtered.py" "archive/test-scripts"
move_file "scripts/test_wwv_detection.py" "archive/test-scripts"
move_file "scripts/test_wwv_live_detection.py" "archive/test-scripts"
echo ""

# 7. Development Shell Scripts
echo -e "${YELLOW}[7/9] Archiving development shell scripts...${NC}"
move_file "check_radiod_bandwidth.sh" "archive/shell-scripts"
move_file "cleanup_watchdogs.sh" "archive/shell-scripts"
move_file "compare-packets.sh" "archive/shell-scripts"
move_file "debug-radiod-packets.sh" "archive/shell-scripts"
move_file "kill_daemon.sh" "archive/shell-scripts"
move_file "setup-linux-dev.sh" "archive/shell-scripts"
move_file "setup.sh" "archive/shell-scripts"
move_file "test-channel-creation.sh" "archive/shell-scripts"
move_file "watch-tone-detection.sh" "archive/shell-scripts"
move_file "scripts/setup_and_run.sh" "archive/shell-scripts"
move_file "scripts/start_overnight_v2.sh" "archive/shell-scripts"
move_file "scripts/watch_drift_development.sh" "archive/shell-scripts"
echo ""

# 8. Legacy Code
echo -e "${YELLOW}[8/9] Archiving legacy code and artifacts...${NC}"
move_file "rx888.c" "archive/legacy-code"
move_file "rx888.h" "archive/legacy-code"
move_file "rtp.c" "archive/legacy-code"
move_file "rtp.h" "archive/legacy-code"
move_file "signal-recorder-complete.tar.gz" "archive/legacy-code"
echo ""

# 9. Docs Archive
echo -e "${YELLOW}[9/9] Moving docs to docs/archive...${NC}"
move_file "docs/SESSION_SUMMARY_2024-11-03.md" "docs/archive"
move_file "docs/PHASE1_RESEQUENCING_COMPLETE.md" "docs/archive"
move_file "docs/PHASE2_TIME_SNAP_COMPLETE.md" "docs/archive"
move_file "docs/10_SECOND_DETECTION_WINDOW.md" "docs/archive"
move_file "docs/WWV_BUFFERED_DETECTION_SUCCESS.md" "docs/archive"
move_file "docs/MATCHED_FILTER_DETECTION.md" "docs/archive"
echo ""

# Remove empty directories
echo -e "${YELLOW}Checking for empty directories...${NC}"
remove_empty_dir "home"
remove_empty_dir "test-data"
remove_empty_dir "node_modules"
echo ""

# Summary
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Cleanup Summary${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}DRY RUN: No files were actually moved${NC}"
    echo -e "Files that would be moved: ${BLUE}$MOVED_COUNT${NC}"
    echo ""
    echo "To execute the cleanup, run:"
    echo "  ./cleanup-codebase.sh"
else
    echo -e "Files moved to archive: ${GREEN}$MOVED_COUNT${NC}"
    echo ""
    echo -e "${GREEN}✓ Cleanup complete!${NC}"
    echo ""
    echo "Archive structure:"
    echo "  archive/dev-history/     - Historical documentation"
    echo "  archive/test-scripts/    - Development test scripts"
    echo "  archive/shell-scripts/   - Development shell scripts"
    echo "  archive/legacy-code/     - Old implementations"
    echo "  docs/archive/            - Development session notes"
    echo ""
    echo "These files are preserved for reference but removed from the active workspace."
fi
echo ""

exit 0
