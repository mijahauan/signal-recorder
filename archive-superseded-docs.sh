#!/bin/bash
# Archive superseded documentation after creating PROJECT_NARRATIVE.md
# This moves historical/redundant docs while keeping core references

set -e

PROJECT_ROOT="/home/mjh/git/signal-recorder"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "  Archive Superseded Documentation"
echo "=============================================="
echo ""
echo "This will archive documentation now covered by:"
echo "  • PROJECT_NARRATIVE.md (complete history)"
echo "  • TECHNICAL_REFERENCE.md (developer quick ref)"
echo "  • CONTEXT.md (system reference)"
echo ""
echo "Superseded docs will move to archive/dev-history/"
echo "All changes tracked by git (reversible)"
echo ""

read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Ensure archive directory exists
mkdir -p archive/dev-history

echo ""
echo "Step 1: Archiving cleanup documentation (Nov 18 one-time cleanup)..."

for file in CLEANUP_*.md START_HERE_CLEANUP.md; do
    if [ -f "$file" ]; then
        git mv "$file" archive/dev-history/ 2>/dev/null && echo "  → $file" || true
    fi
done

echo "✓ Cleanup docs archived"

echo ""
echo "Step 2: Archiving session summaries (covered in PROJECT_NARRATIVE)..."

for file in SESSION_2025-11-17_WEB_UI_SYNC.md WEB_UI_V2_INTEGRATION_SESSION.md; do
    if [ -f "$file" ]; then
        git mv "$file" archive/dev-history/ 2>/dev/null && echo "  → $file" || true
    fi
done

echo "✓ Session docs archived"

echo ""
echo "Step 3: Archiving specific feature implementations..."

for file in \
    CARRIER_CHANNEL_ANALYTICS_IMPLEMENTATION.md \
    DISCRIMINATION_VISUALIZATION_IMPROVEMENTS.md \
    CORRELATION_ANALYSIS_COMPLETE.md \
    QUALITY_ANALYSIS_INTEGRATION.md \
    SPECTROGRAM_GENERATION_COMPLETE.md \
    TIMING_DASHBOARD_INTEGRATION.md \
    TONE_LOCKED_RENAME.md \
    QUALITY_DASHBOARD_QUICKSTART.md; do
    if [ -f "$file" ]; then
        git mv "$file" archive/dev-history/ 2>/dev/null && echo "  → $file" || true
    fi
done

echo "✓ Feature implementation docs archived"

echo ""
echo "Step 4: Archiving quick fixes and test results..."

for file in \
    QUICK_FIX_SPECTROGRAM_GENERATION.md \
    RESTART-FOR-DIGITAL-RF.md \
    REALTIME_DATA_VERIFICATION.md \
    SUMMARY_SCREEN_TEST_RESULTS.md; do
    if [ -f "$file" ]; then
        git mv "$file" archive/dev-history/ 2>/dev/null && echo "  → $file" || true
    fi
done

echo "✓ Quick fixes and test results archived"

echo ""
echo "Step 5: Archiving web UI protocol docs (covered in TECHNICAL_REFERENCE)..."

for file in \
    WEB_UI_ANALYTICS_SYNC_PROTOCOL.md \
    WEB_UI_API_PROPOSAL.md \
    WEB_UI_DUAL_SERVICE_INTEGRATION.md \
    WEB_UI_IMPROVEMENTS_NOV13_2024.md; do
    if [ -f "$file" ]; then
        git mv "$file" archive/dev-history/ 2>/dev/null && echo "  → $file" || true
    fi
done

echo "✓ Web UI protocol docs archived"

echo ""
echo "=============================================="
echo "  ✅ Documentation Cleanup Complete"
echo "=============================================="
echo ""
echo "Root directory now has:"
ls -1 *.md 2>/dev/null | wc -l
echo "markdown files"
echo ""
echo "Remaining docs:"
ls -1 *.md 2>/dev/null
echo ""
echo "Summary:"
git status --short | grep "^R" | wc -l
echo "files archived"
echo ""
echo "Next steps:"
echo "  1. Review: git status"
echo "  2. Verify core docs are still present:"
echo "     ls -1 PROJECT_NARRATIVE.md TECHNICAL_REFERENCE.md CONTEXT.md README.md"
echo "  3. If satisfied:"
echo "     git commit -m 'Archive superseded documentation"
echo ""
echo "     - Created PROJECT_NARRATIVE.md (complete history)"
echo "     - Created TECHNICAL_REFERENCE.md (developer reference)"
echo "     - Archived ~30 superseded docs to archive/dev-history/"
echo "     - Root directory now has 8-11 core docs (down from 60+)'"
echo "  4. If not satisfied:"
echo "     git reset --hard HEAD"
echo ""
