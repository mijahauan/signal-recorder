#!/bin/bash
# Commit Previous Sessions Work (Timing + Discrimination + Web-UI)
# Run this BEFORE committing today's critical fixes

echo "========================================="
echo "Committing Previous Sessions Changes"
echo "========================================="
echo ""

echo "Adding files from previous sessions..."
echo ""

# Add timing system (NEW)
echo "✓ Adding timing_metrics_writer.py (NEW)"
git add src/signal_recorder/timing_metrics_writer.py

# Add discrimination enhancements
echo "✓ Adding discrimination_csv_writers.py"
git add src/signal_recorder/discrimination_csv_writers.py

echo "✓ Adding wwvh_discrimination.py"
git add src/signal_recorder/wwvh_discrimination.py

# Add paths
echo "✓ Adding paths.py"
git add src/signal_recorder/paths.py

# Add web-UI improvements
echo "✓ Adding monitoring-server-v3.js"
git add web-ui/monitoring-server-v3.js

echo "✓ Adding summary.html"
git add web-ui/summary.html

echo "✓ Adding timing-dashboard.html"
git add web-ui/timing-dashboard.html

echo "✓ Adding discrimination.html"
git add web-ui/discrimination.html

echo "✓ Adding carrier.html"
git add web-ui/carrier.html

echo "✓ Adding grape-paths.js"
git add web-ui/grape-paths.js

echo ""
echo "========================================="
echo "Files staged for commit:"
echo "========================================="
git status --short | grep "^A"

echo ""
echo "========================================="
echo "Ready to commit!"
echo "========================================="
echo ""

# Commit with comprehensive message
git commit -m "feat: Add comprehensive timing metrics system and enhance discrimination

TIMING SYSTEM (NEW):
- Add TimingMetricsWriter for drift/jitter analysis  
- Implement minute-to-minute drift measurements
- Add tone-to-tone frequency drift (PPM)
- Calculate RMS jitter from drift history
- Quality classification (TONE_LOCKED, NTP_SYNCED, etc.)
- CSV and JSON output for web-UI visualization

DISCRIMINATION ENHANCEMENTS:
- Add test signal detection for minutes 8 and 44
- Implement chirp and multitone pattern matching
- Enhance WWVH vs WWV discrimination voting
- Add TestSignalRecord CSV writer
- Improve station identification accuracy

WEB-UI IMPROVEMENTS:
- Fix timing quality classification (use 5-minute threshold)
- Add timing metrics visualization endpoints
- Add test signal detection display  
- Improve discrimination dashboard
- Update summary page timing badges
- Add INTERPOLATED quality status display

INFRASTRUCTURE:
- Add timing metrics and test signal path methods
- Update grape-paths.js for path consistency
- Clean directory structure
- Ensure backward compatibility

FILES:
- New: timing_metrics_writer.py (628 lines)
- Modified: 9 files (discrimination, paths, web-UI)
- Total: +881 insertions, -118 deletions

IMPACT:
- Complete timing analysis for web-UI
- Better station discrimination accuracy
- Consistent timing quality display
- Enhanced user visibility into system health"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Commit successful!"
    echo ""
    echo "Next steps:"
    echo "1. Run: git push"
    echo "2. Then commit today's critical fixes separately"
    echo ""
else
    echo ""
    echo "❌ Commit failed - please review errors above"
    echo ""
    exit 1
fi
