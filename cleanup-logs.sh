#!/bin/bash
# Cleanup old log files
# KEEPS: Recently modified logs (last 24 hours), system logs
# DELETES: Old test logs, stale daemon logs

set -e

echo "========================================"
echo "Log File Cleanup Analysis"
echo "========================================"
echo ""

# Define what's "active" (modified in last 24 hours)
CUTOFF_TIME=$(date -d '24 hours ago' +%s)

# Arrays to track files
declare -a ACTIVE_LOGS
declare -a OLD_LOGS
TOTAL_OLD_SIZE=0

echo "🔍 Scanning for log files..."
echo ""

# Function to check if file is active
is_active() {
    local file="$1"
    local mtime=$(stat -c %Y "$file" 2>/dev/null || echo 0)
    
    if [ $mtime -gt $CUTOFF_TIME ]; then
        return 0  # Active
    else
        return 1  # Old
    fi
}

# Function to format size for display
format_size() {
    local file="$1"
    du -h "$file" 2>/dev/null | cut -f1
}

# Scan /tmp for log files
echo "📂 Scanning /tmp/*.log..."
for logfile in /tmp/*.log; do
    [ -f "$logfile" ] || continue
    
    if is_active "$logfile"; then
        ACTIVE_LOGS+=("$logfile")
    else
        OLD_LOGS+=("$logfile")
    fi
done

# Scan /tmp/grape-test/logs
echo "📂 Scanning /tmp/grape-test/logs/*.log..."
if [ -d /tmp/grape-test/logs ]; then
    for logfile in /tmp/grape-test/logs/*.log; do
        [ -f "$logfile" ] || continue
        
        if is_active "$logfile"; then
            ACTIVE_LOGS+=("$logfile")
        else
            OLD_LOGS+=("$logfile")
        fi
    done
fi

# Scan web-ui logs (keep only last 3 days)
WEBUI_CUTOFF=$(date -d '3 days ago' +%s)
echo "📂 Scanning web-ui logs (older than 3 days)..."
for logfile in /home/mjh/git/signal-recorder/web-ui/*.log; do
    [ -f "$logfile" ] || continue
    
    mtime=$(stat -c %Y "$logfile" 2>/dev/null || echo 0)
    if [ $mtime -lt $WEBUI_CUTOFF ]; then
        OLD_LOGS+=("$logfile")
    else
        ACTIVE_LOGS+=("$logfile")
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 ACTIVE LOG FILES (WILL BE KEPT)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ${#ACTIVE_LOGS[@]} -eq 0 ]; then
    echo "  (none - no recently modified logs)"
else
    for log in "${ACTIVE_LOGS[@]}"; do
        size=$(format_size "$log")
        mtime=$(stat -c %y "$log" | cut -d'.' -f1)
        echo "  ✓ $log"
        echo "     Size: $size, Modified: $mtime"
    done
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🗑️  OLD LOG FILES (WILL BE DELETED)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ${#OLD_LOGS[@]} -eq 0 ]; then
    echo "  (none - all logs are recent)"
    echo ""
    echo "✅ No cleanup needed!"
    exit 0
fi

# Calculate total size and show files
for log in "${OLD_LOGS[@]}"; do
    size=$(format_size "$log")
    mtime=$(stat -c %y "$log" | cut -d'.' -f1)
    echo "  ✗ $log"
    echo "     Size: $size, Modified: $mtime"
done

# Calculate total size to be freed
echo ""
TOTAL_SIZE=$(du -ch "${OLD_LOGS[@]}" 2>/dev/null | tail -1 | cut -f1)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Total files to delete: ${#OLD_LOGS[@]}"
echo "Total space to free: $TOTAL_SIZE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Show largest files
echo "📈 Largest old log files:"
for log in "${OLD_LOGS[@]}"; do
    du -h "$log" 2>/dev/null
done | sort -h | tail -5 | awk '{print "  " $2 " (" $1 ")"}'

echo ""
read -p "Delete these old log files? (yes/no): " confirm

if [ "$confirm" = "yes" ]; then
    echo ""
    echo "🗑️  Deleting old log files..."
    
    DELETED_COUNT=0
    SKIPPED_COUNT=0
    
    for log in "${OLD_LOGS[@]}"; do
        if rm -f "$log" 2>/dev/null; then
            echo "  ✓ Removed: $log"
            ((DELETED_COUNT++))
        else
            echo "  ⊘ Skipped (no permission): $log"
            ((SKIPPED_COUNT++))
        fi
    done
    
    echo ""
    echo "✅ Cleanup complete!"
    echo "   Deleted: $DELETED_COUNT files"
    if [ $SKIPPED_COUNT -gt 0 ]; then
        echo "   Skipped: $SKIPPED_COUNT files (permission denied)"
    fi
    echo "   Freed: ~$TOTAL_SIZE"
    echo ""
    echo "Remaining active logs:"
    echo "  /home/mjh/git/signal-recorder/logs/"
    ls -lh /home/mjh/git/signal-recorder/logs/*.log 2>/dev/null || echo "    (none)"
    echo ""
    echo "  /var/log/signal-recorder/"
    ls -lh /var/log/signal-recorder/*.log 2>/dev/null || echo "    (none)"
else
    echo ""
    echo "Cleanup cancelled"
fi

echo ""
echo "========================================"
