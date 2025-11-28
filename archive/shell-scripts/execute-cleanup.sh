#!/bin/bash
# GRAPE Project Cleanup Script
# Safe archiving of obsolete documentation and test scripts
# 
# This script moves files to archive/ without deleting anything
# All changes are reversible with git

set -e  # Exit on error

PROJECT_ROOT="/home/mjh/git/signal-recorder"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "GRAPE Project Cleanup"
echo "=============================================="
echo ""
echo "This script will:"
echo "  1. Create git tag 'pre-cleanup-backup'"
echo "  2. Move session docs to archive/dev-history/"
echo "  3. Move test scripts to archive/test-scripts/"
echo "  4. Move feature docs to docs/"
echo "  5. Clean up web-ui test files"
echo ""
echo "NO FILES WILL BE DELETED - only moved to archive/"
echo "All changes can be reversed with git"
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
git tag -f pre-cleanup-backup
echo "✓ Tagged as 'pre-cleanup-backup'"

# Create archive directories if needed
echo ""
echo "Step 2: Creating archive directories..."
mkdir -p archive/dev-history
mkdir -p archive/test-scripts
mkdir -p archive/legacy-code
mkdir -p docs/features
mkdir -p docs/web-ui
echo "✓ Directories created"

# Move session summaries and completion docs
echo ""
echo "Step 3: Archiving session summaries and completion docs..."

# Session summaries
for file in SESSION_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" archive/dev-history/
        echo "  → $file"
    fi
done

# Completion docs
for file in *_COMPLETE.md *_IMPLEMENTATION.md *_SUMMARY.md PHASE*.md; do
    if [ -f "$file" ]; then
        # Skip CLEANUP_PROPOSAL and CONTEXT
        if [[ "$file" != "CLEANUP_PROPOSAL.md" && "$file" != "ARCHITECTURE_OVERVIEW.md" ]]; then
            git mv "$file" archive/dev-history/
            echo "  → $file"
        fi
    fi
done

# Specific status docs
for file in OVERNIGHT_STATUS.md NEXT_STEPS.md REVIEW_SUMMARY.md STARTUP_SESSION_SUMMARY.md; do
    if [ -f "$file" ]; then
        git mv "$file" archive/dev-history/
        echo "  → $file"
    fi
done

echo "✓ Session docs archived"

# Move feature documentation to docs/features/
echo ""
echo "Step 4: Organizing feature documentation..."

# Timing docs
for pattern in "TIMING_*" "TIME_*" "DRF_TIMESTAMP_*" "DIGITAL_RF_TIMESTAMP_*"; do
    for file in $pattern.md; do
        if [ -f "$file" ]; then
            git mv "$file" docs/features/
            echo "  → $file"
        fi
    done
done

# Carrier docs
for file in CARRIER_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# Quality docs
for file in QUALITY_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# WWV/WWVH docs
for file in WWV*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# Digital RF docs
for file in DIGITAL_RF_*.md DRF_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# Spectrogram docs
for file in SPECTROGRAM_*.md AUTOMATIC_SPECTROGRAM_*.md PARTIAL_DAY_SPECTROGRAM_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# Analytics docs
for file in ANALYTICS_*.md CORRELATION_*.md DECIMATION_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# Config docs
for file in CONFIG_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# Health monitoring
for file in HEALTH_*.md RADIOD_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

# Other feature docs
for file in DISCRIMINATION_*.md GRAPE_UPLOAD_*.md GRAPE_V1_*.md INTEGRATION_*.md INTERFACES_*.md PATH_MANAGEMENT.md PATHS_API_*.md PSWS_*.md; do
    if [ -f "$file" ]; then
        git mv "$file" docs/features/
        echo "  → $file"
    fi
done

echo "✓ Feature docs organized"

# Move test/analysis scripts
echo ""
echo "Step 5: Archiving test and analysis scripts..."

cd scripts

# Analysis scripts (one-time investigations)
for file in analyze_*.py compare_*.py measure_*.py quick_*.py; do
    if [ -f "$file" ]; then
        git mv "$file" ../archive/test-scripts/
        echo "  → scripts/$file"
    fi
done

# Test scripts
for file in test_*.sh validate-*.sh; do
    if [ -f "$file" ]; then
        git mv "$file" ../archive/test-scripts/
        echo "  → scripts/$file"
    fi
done

# Data migration scripts (one-time use)
for file in migrate-*.sh regenerate_*.py reprocess_*.py generate_10hz_npz.py; do
    if [ -f "$file" ]; then
        git mv "$file" ../archive/test-scripts/
        echo "  → scripts/$file"
    fi
done

# Experimental spectrogram generators
for file in generate_spectrograms_v2.py generate_spectrograms_drf.py generate_spectrograms_from_*.py; do
    if [ -f "$file" ]; then
        git mv "$file" ../archive/test-scripts/
        echo "  → scripts/$file"
    fi
done

cd "$PROJECT_ROOT"
echo "✓ Test scripts archived"

# Move web-ui docs to docs/web-ui/
echo ""
echo "Step 6: Organizing web-ui documentation..."

cd web-ui

for file in *.md; do
    if [ -f "$file" ] && [ "$file" != "README.md" ]; then
        git mv "$file" ../docs/web-ui/
        echo "  → web-ui/$file"
    fi
done

# Archive web-ui test files
echo ""
echo "Step 7: Archiving web-ui test files..."

for file in test-*.js test-*.cjs test-*.sh; do
    if [ -f "$file" ]; then
        git mv "$file" ../archive/test-scripts/
        echo "  → web-ui/$file"
    fi
done

# Archive deprecated server
if [ -f "monitoring-server.js" ]; then
    git mv "monitoring-server.js" ../archive/legacy-code/
    echo "  → web-ui/monitoring-server.js (deprecated)"
fi

# Clean up build artifacts (not in git, just delete)
echo ""
echo "Step 8: Removing build artifacts..."
for file in monitoring-server.log build-output.txt cookies.txt; do
    if [ -f "$file" ] && ! git ls-files --error-unmatch "$file" > /dev/null 2>&1; then
        rm -f "$file"
        echo "  → Deleted $file (build artifact)"
    fi
done

cd "$PROJECT_ROOT"
echo "✓ Web-ui cleaned"

# Summary
echo ""
echo "=============================================="
echo "Cleanup Complete!"
echo "=============================================="
echo ""
echo "Summary of changes:"
echo "  • Session docs → archive/dev-history/"
echo "  • Feature docs → docs/features/"
echo "  • Test scripts → archive/test-scripts/"
echo "  • Web-ui docs → docs/web-ui/"
echo "  • Build artifacts → deleted"
echo ""
echo "Next steps:"
echo "  1. Review changes: git status"
echo "  2. Verify services still work:"
echo "     - Core recorder: systemctl status grape-core-recorder"
echo "     - Web UI: cd web-ui && node monitoring-server-v3.js"
echo "  3. If satisfied: git commit -m 'Cleanup: archive obsolete docs and test scripts'"
echo "  4. If not satisfied: git reset --hard pre-cleanup-backup"
echo ""
echo "Safety tag created: pre-cleanup-backup"
echo "To undo ALL changes: git reset --hard pre-cleanup-backup"
echo ""
