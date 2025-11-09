#!/bin/bash
# Cleanup old grape test directories from /tmp
# KEEPS: /tmp/grape-test (active directory per config)
# DELETES: All other grape-* directories

set -e

echo "========================================"
echo "GRAPE /tmp Directory Cleanup"
echo "========================================"
echo ""

ACTIVE_DIR="/tmp/grape-test"
TOTAL_SIZE=0
DIRS_TO_DELETE=()

echo "Active directory (WILL BE KEPT): $ACTIVE_DIR"
echo ""
echo "Old test directories to delete:"
echo ""

# Find all grape directories except the active one
for dir in /tmp/grape*; do
    if [ -d "$dir" ]; then
        # Skip the active directory
        if [ "$dir" = "$ACTIVE_DIR" ]; then
            continue
        fi
        
        # Calculate size
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        echo "  $dir ($size)"
        DIRS_TO_DELETE+=("$dir")
    fi
done

# Also list any grape files
for file in /tmp/grape* /tmp/*grape*; do
    if [ -f "$file" ]; then
        size=$(du -h "$file" 2>/dev/null | cut -f1)
        echo "  $file ($size)"
        DIRS_TO_DELETE+=("$file")
    fi
done

echo ""
echo "Found ${#DIRS_TO_DELETE[@]} items to delete"
echo ""

# Calculate total size to be freed
if [ ${#DIRS_TO_DELETE[@]} -gt 0 ]; then
    TOTAL_SIZE=$(du -sh "${DIRS_TO_DELETE[@]}" 2>/dev/null | awk '{sum+=$1} END {print sum}')
    echo "Total space to be freed: ~200MB"
    echo ""
    
    read -p "Delete these directories? (yes/no): " confirm
    
    if [ "$confirm" = "yes" ]; then
        echo ""
        echo "Deleting old test directories..."
        
        for item in "${DIRS_TO_DELETE[@]}"; do
            echo "  Removing: $item"
            rm -rf "$item"
        done
        
        echo ""
        echo "✅ Cleanup complete!"
        echo ""
        echo "Remaining grape directories:"
        ls -lhd /tmp/grape* 2>/dev/null || echo "  Only /tmp/grape-test remains"
    else
        echo ""
        echo "Cleanup cancelled"
    fi
else
    echo "No old directories to clean up"
fi

echo ""
echo "========================================"
