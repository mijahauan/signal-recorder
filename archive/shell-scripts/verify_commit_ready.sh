#!/bin/bash
# Pre-Commit Verification Script
# Checks that code is ready for commit

echo "========================================="
echo "Pre-Commit Verification for Session 2025-11-26"
echo "========================================="
echo ""

# Track overall status
ERRORS=0

# Check Python syntax
echo "1. Checking Python syntax..."
python3 -m py_compile src/signal_recorder/core_recorder.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ core_recorder.py syntax OK"
else
    echo "   ❌ core_recorder.py has syntax errors"
    ERRORS=$((ERRORS + 1))
fi

python3 -m py_compile src/signal_recorder/core_npz_writer.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ core_npz_writer.py syntax OK"
else
    echo "   ❌ core_npz_writer.py has syntax errors"
    ERRORS=$((ERRORS + 1))
fi

python3 -m py_compile src/signal_recorder/analytics_service.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ analytics_service.py syntax OK"
else
    echo "   ❌ analytics_service.py has syntax errors"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# Check imports
echo "2. Checking critical imports..."
if grep -q "import threading" src/signal_recorder/core_recorder.py; then
    echo "   ✅ core_recorder.py has threading import"
else
    echo "   ❌ core_recorder.py missing threading import"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "import threading" src/signal_recorder/core_npz_writer.py; then
    echo "   ✅ core_npz_writer.py has threading import"
else
    echo "   ❌ core_npz_writer.py missing threading import"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# Check for key features
echo "3. Checking implementation features..."

# Thread safety locks
if grep -q "self._lock = threading.Lock()" src/signal_recorder/core_recorder.py; then
    echo "   ✅ ChannelProcessor has lock"
else
    echo "   ❌ ChannelProcessor missing lock"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "self._lock = threading.Lock()" src/signal_recorder/core_npz_writer.py; then
    echo "   ✅ CoreNPZWriter has lock"
else
    echo "   ❌ CoreNPZWriter missing lock"
    ERRORS=$((ERRORS + 1))
fi

# Centralized NTP
if grep -q "def get_ntp_status" src/signal_recorder/core_recorder.py; then
    echo "   ✅ Centralized get_ntp_status() exists"
else
    echo "   ❌ Missing get_ntp_status() method"
    ERRORS=$((ERRORS + 1))
fi

# Pending time_snap
if grep -q "pending_time_snap" src/signal_recorder/core_npz_writer.py; then
    echo "   ✅ Pending time_snap mechanism exists"
else
    echo "   ❌ Missing pending_time_snap"
    ERRORS=$((ERRORS + 1))
fi

# NTP fields in NPZ
if grep -q "ntp_wall_clock_time" src/signal_recorder/core_npz_writer.py; then
    echo "   ✅ NTP wall clock time field exists"
else
    echo "   ❌ Missing ntp_wall_clock_time field"
    ERRORS=$((ERRORS + 1))
fi

# Dead code removed
if grep -q "def _check_ntp_sync" src/signal_recorder/core_recorder.py; then
    echo "   ⚠️  WARNING: Old _check_ntp_sync still exists (should be removed)"
    ERRORS=$((ERRORS + 1))
else
    echo "   ✅ Dead code removed (_check_ntp_sync)"
fi

echo ""

# Check documentation
echo "4. Checking documentation files..."
DOCS=(
    "CRITICAL_FIXES_IMPLEMENTED.md"
    "NTP_CENTRALIZATION_COMPLETE.md"
    "FINAL_CLEANUP_COMPLETE.md"
    "API_FORMAT_ALIGNMENT.md"
    "COMMIT_PREPARATION.md"
    "CHANGELOG_SESSION_2025-11-26.md"
)

for doc in "${DOCS[@]}"; do
    if [ -f "$doc" ]; then
        echo "   ✅ $doc exists"
    else
        echo "   ❌ Missing $doc"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""

# Summary
echo "========================================="
if [ $ERRORS -eq 0 ]; then
    echo "✅ ALL CHECKS PASSED - READY FOR COMMIT"
    echo "========================================="
    echo ""
    echo "Next steps:"
    echo "1. Review COMMIT_PREPARATION.md"
    echo "2. Run: git add src/signal_recorder/core_recorder.py"
    echo "3. Run: git add src/signal_recorder/core_npz_writer.py"
    echo "4. Run: git add *.md"
    echo "5. Run: git commit -F COMMIT_PREPARATION.md (or use custom message)"
    echo "6. Run: git push"
    echo ""
    exit 0
else
    echo "❌ FOUND $ERRORS ISSUE(S) - PLEASE FIX BEFORE COMMIT"
    echo "========================================="
    echo ""
    exit 1
fi
