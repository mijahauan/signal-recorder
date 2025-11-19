#!/bin/bash
#
# Data Storage Migration Script
# Migrates existing signal-recorder installation to new standardized paths
#
# Usage: sudo ./migrate-data-storage.sh [--dry-run]
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ] && [ "$1" != "--dry-run" ]; then 
   echo -e "${RED}Please run as root for production migration${NC}"
   echo "For dry-run: ./migrate-data-storage.sh --dry-run"
   exit 1
fi

DRY_RUN=false
if [ "$1" == "--dry-run" ]; then
    DRY_RUN=true
    echo -e "${BLUE}=== DRY RUN MODE ===${NC}"
    echo "No files will be moved or modified"
    echo ""
fi

# Source and destination paths
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Signal Recorder Data Storage Migration${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Detect old installation paths
OLD_PATHS=(
    "/tmp/signal-recorder-stats.json"
    "$HOME/grape-data"
    "$HOME/git/signal-recorder/logs/wwv_timing.csv"
    "$HOME/git/signal-recorder/web-ui/data"
)

NEW_BASE="/var/lib/signal-recorder"
NEW_WEB_UI="/var/lib/signal-recorder-web"
NEW_CONFIG="/etc/signal-recorder"
NEW_CREDENTIALS="$NEW_CONFIG/credentials"
NEW_LOGS="/var/log/signal-recorder"

echo -e "${YELLOW}Step 1: Checking existing installation${NC}"
echo ""

# Find old data directory
OLD_DATA_DIR=""
for path in "${OLD_PATHS[@]}"; do
    if [ -d "$path/archive" ] || [ -d "$path/raw" ]; then
        OLD_DATA_DIR="$path"
        echo -e "  ${GREEN}✓${NC} Found old data directory: $OLD_DATA_DIR"
        break
    fi
done

if [ -z "$OLD_DATA_DIR" ]; then
    echo -e "  ${YELLOW}⚠${NC}  No old data directory found"
    echo "  This may be a fresh installation"
fi

# Check for old stats file
if [ -f "/tmp/signal-recorder-stats.json" ]; then
    echo -e "  ${GREEN}✓${NC} Found stats file: /tmp/signal-recorder-stats.json"
    OLD_STATS_FILE="/tmp/signal-recorder-stats.json"
fi

# Check for WWV timing log
OLD_WWV_LOG=""
if [ -f "$HOME/git/signal-recorder/logs/wwv_timing.csv" ]; then
    OLD_WWV_LOG="$HOME/git/signal-recorder/logs/wwv_timing.csv"
    echo -e "  ${GREEN}✓${NC} Found WWV timing log: $OLD_WWV_LOG"
fi

# Check for web UI data
OLD_WEB_UI_DATA=""
if [ -d "$HOME/git/signal-recorder/web-ui/data" ]; then
    OLD_WEB_UI_DATA="$HOME/git/signal-recorder/web-ui/data"
    echo -e "  ${GREEN}✓${NC} Found web UI data: $OLD_WEB_UI_DATA"
fi

echo ""
echo -e "${YELLOW}Step 2: Creating new directory structure${NC}"
echo ""

create_dir() {
    local dir=$1
    local perms=$2
    
    if [ "$DRY_RUN" = true ]; then
        echo -e "  ${BLUE}[DRY RUN]${NC} Would create: $dir (mode $perms)"
    else
        mkdir -p "$dir"
        chmod "$perms" "$dir"
        echo -e "  ${GREEN}✓${NC} Created: $dir"
    fi
}

# Create new directory structure
create_dir "$NEW_BASE/data" "0755"
create_dir "$NEW_BASE/analytics/quality" "0755"
create_dir "$NEW_BASE/analytics/timing" "0755"
create_dir "$NEW_BASE/analytics/reports" "0755"
create_dir "$NEW_BASE/upload" "0755"
create_dir "$NEW_BASE/status" "0755"
create_dir "$NEW_WEB_UI" "0755"
create_dir "$NEW_CONFIG" "0755"
create_dir "$NEW_CREDENTIALS" "0700"
create_dir "$NEW_LOGS" "0755"

echo ""
echo -e "${YELLOW}Step 3: Migrating data${NC}"
echo ""

migrate_data() {
    local src=$1
    local dest=$2
    local description=$3
    
    if [ ! -e "$src" ]; then
        return
    fi
    
    if [ "$DRY_RUN" = true ]; then
        if [ -d "$src" ]; then
            file_count=$(find "$src" -type f 2>/dev/null | wc -l)
            echo -e "  ${BLUE}[DRY RUN]${NC} Would move $description: $src → $dest ($file_count files)"
        else
            echo -e "  ${BLUE}[DRY RUN]${NC} Would move $description: $src → $dest"
        fi
    else
        if [ -d "$src" ]; then
            cp -a "$src"/* "$dest/" 2>/dev/null || true
            file_count=$(find "$dest" -type f 2>/dev/null | wc -l)
            echo -e "  ${GREEN}✓${NC} Moved $description ($file_count files)"
        else
            cp -a "$src" "$dest/"
            echo -e "  ${GREEN}✓${NC} Moved $description"
        fi
    fi
}

# Migrate RTP data
if [ -n "$OLD_DATA_DIR" ]; then
    if [ -d "$OLD_DATA_DIR/archive" ]; then
        migrate_data "$OLD_DATA_DIR/archive" "$NEW_BASE/data" "RTP recordings"
    elif [ -d "$OLD_DATA_DIR/raw" ]; then
        migrate_data "$OLD_DATA_DIR/raw" "$NEW_BASE/data" "RTP recordings"
    fi
    
    # Check for upload queue
    if [ -d "$OLD_DATA_DIR/raw/upload_queue" ]; then
        migrate_data "$OLD_DATA_DIR/raw/upload_queue" "$NEW_BASE/upload" "upload queue"
    fi
fi

# Migrate stats file
if [ -n "$OLD_STATS_FILE" ]; then
    migrate_data "$OLD_STATS_FILE" "$NEW_BASE/status" "stats file"
fi

# Migrate WWV timing log
if [ -n "$OLD_WWV_LOG" ]; then
    migrate_data "$OLD_WWV_LOG" "$NEW_BASE/analytics/timing" "WWV timing log"
fi

# Migrate web UI data
if [ -n "$OLD_WEB_UI_DATA" ]; then
    # Separate credentials from web UI data
    if [ -f "$OLD_WEB_UI_DATA/jwt-secret.txt" ]; then
        migrate_data "$OLD_WEB_UI_DATA/jwt-secret.txt" "$NEW_CREDENTIALS" "JWT secret"
        if [ "$DRY_RUN" = false ]; then
            chmod 600 "$NEW_CREDENTIALS/jwt-secret.txt"
        fi
    fi
    
    # Move user data and configs
    for file in users.json configurations.json channels.json; do
        if [ -f "$OLD_WEB_UI_DATA/$file" ]; then
            migrate_data "$OLD_WEB_UI_DATA/$file" "$NEW_WEB_UI" "web UI $file"
        fi
    done
fi

echo ""
echo -e "${YELLOW}Step 4: Setting permissions${NC}"
echo ""

set_permissions() {
    local path=$1
    local perms=$2
    local description=$3
    
    if [ "$DRY_RUN" = true ]; then
        echo -e "  ${BLUE}[DRY RUN]${NC} Would set $description permissions: $perms"
    else
        if [ -e "$path" ]; then
            chmod -R "$perms" "$path"
            echo -e "  ${GREEN}✓${NC} Set $description permissions: $perms"
        fi
    fi
}

# Set restrictive permissions on credentials
set_permissions "$NEW_CREDENTIALS" "0700" "credentials directory"
if [ -f "$NEW_CREDENTIALS/jwt-secret.txt" ]; then
    if [ "$DRY_RUN" = false ]; then
        chmod 600 "$NEW_CREDENTIALS/jwt-secret.txt"
    fi
    echo -e "  ${GREEN}✓${NC} Set JWT secret permissions: 0600"
fi

# Set ownership (if running as root)
if [ "$EUID" -eq 0 ] && [ "$DRY_RUN" = false ]; then
    echo ""
    echo -e "${YELLOW}Step 5: Setting ownership${NC}"
    echo ""
    
    # Check if signal-recorder user exists
    if id "signal-recorder" &>/dev/null; then
        chown -R signal-recorder:signal-recorder "$NEW_BASE"
        chown -R signal-recorder:signal-recorder "$NEW_WEB_UI"
        chown -R signal-recorder:signal-recorder "$NEW_CONFIG"
        chown -R signal-recorder:signal-recorder "$NEW_LOGS"
        echo -e "  ${GREEN}✓${NC} Set ownership to signal-recorder user"
    else
        echo -e "  ${YELLOW}⚠${NC}  signal-recorder user not found, skipping ownership change"
        echo "     Create user with: sudo useradd -r -s /bin/false signal-recorder"
    fi
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Migration Summary${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo "New directory structure:"
echo "  RTP Data:       $NEW_BASE/data/"
echo "  Analytics:      $NEW_BASE/analytics/"
echo "  Upload State:   $NEW_BASE/upload/"
echo "  Runtime Status: $NEW_BASE/status/"
echo "  Web UI Data:    $NEW_WEB_UI/"
echo "  Configuration:  $NEW_CONFIG/"
echo "  Credentials:    $NEW_CREDENTIALS/ (mode 0700)"
echo "  Logs:           $NEW_LOGS/"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}This was a DRY RUN - no files were moved${NC}"
    echo "Run without --dry-run to perform the actual migration"
else
    echo -e "${GREEN}✓ Migration complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Update your configuration file to use new paths"
    echo "  2. Copy to: sudo cp config/grape-production-v2.toml /etc/signal-recorder/config.toml"
    echo "  3. Update systemd service file (if using systemd)"
    echo "  4. Restart signal-recorder service"
    echo ""
    echo "Old data locations have been preserved for safety"
    echo "After verifying the migration, you can remove:"
    if [ -n "$OLD_DATA_DIR" ]; then
        echo "  - $OLD_DATA_DIR"
    fi
    echo "  - /tmp/signal-recorder-stats.json"
fi

echo ""
