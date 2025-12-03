#!/bin/bash
# =============================================================================
# GRAPE Recorder Installation Script
# =============================================================================
# Usage: ./install.sh [--mode test|production] [--user <username>]
#
# This script:
#   1. Creates required directories
#   2. Sets up Python virtual environment
#   3. Installs systemd services (production mode)
#   4. Creates configuration from template
#   5. Validates prerequisites
# =============================================================================

set -euo pipefail

# Default values
MODE="test"
INSTALL_USER="${USER}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $*"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --user)
            INSTALL_USER="$2"
            shift 2
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "GRAPE Recorder Installation Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --mode test|production  Installation mode (default: test)"
            echo "  --user <username>       User to run services as (default: current user)"
            echo "  --verbose, -v           Verbose output"
            echo "  --help, -h              Show this help"
            echo ""
            echo "Test Mode:"
            echo "  - Data stored in /tmp/grape-test"
            echo "  - Manual startup via scripts/grape-all.sh"
            echo "  - Ideal for development and testing"
            echo ""
            echo "Production Mode:"
            echo "  - Data stored in /var/lib/grape-recorder"
            echo "  - Configuration in /etc/grape-recorder"
            echo "  - Systemd services for auto-start and recovery"
            echo "  - Daily upload timer enabled"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate mode
if [[ "$MODE" != "test" && "$MODE" != "production" ]]; then
    log_error "Invalid mode: $MODE (must be 'test' or 'production')"
    exit 1
fi

echo "=============================================="
echo "  GRAPE Recorder Installation"
echo "=============================================="
echo "  Mode:    $MODE"
echo "  User:    $INSTALL_USER"
echo "  Project: $PROJECT_DIR"
echo "=============================================="
echo ""

# =============================================================================
# Step 1: Check Prerequisites
# =============================================================================
log_step "Checking prerequisites..."

check_command() {
    if command -v "$1" &> /dev/null; then
        log_info "  ✅ $1 found"
        return 0
    else
        log_warn "  ❌ $1 not found"
        return 1
    fi
}

PREREQ_OK=true

check_command python3 || PREREQ_OK=false
check_command pip3 || PREREQ_OK=false
check_command node || log_warn "  ⚠️  node not found (Web UI will not work)"
check_command npm || log_warn "  ⚠️  npm not found (Web UI will not work)"

# Check Python version
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [[ "$(echo "$PYTHON_VERSION >= 3.10" | bc)" -eq 1 ]]; then
    log_info "  ✅ Python $PYTHON_VERSION (>= 3.10 required)"
else
    log_error "  ❌ Python $PYTHON_VERSION (>= 3.10 required)"
    PREREQ_OK=false
fi

if [[ "$PREREQ_OK" == "false" ]]; then
    log_error "Prerequisites not met. Please install missing packages."
    exit 1
fi

# =============================================================================
# Step 2: Set Paths Based on Mode
# =============================================================================
log_step "Setting up paths for $MODE mode..."

if [[ "$MODE" == "production" ]]; then
    DATA_ROOT="/var/lib/grape-recorder"
    CONFIG_DIR="/etc/grape-recorder"
    VENV_DIR="/opt/grape-recorder/venv"
    WEBUI_DIR="/opt/grape-recorder/web-ui"
    LOG_DIR="/var/log/grape-recorder"  # FHS standard: logs in /var/log/
else
    DATA_ROOT="/tmp/grape-test"
    CONFIG_DIR="$PROJECT_DIR/config"
    VENV_DIR="$PROJECT_DIR/venv"
    WEBUI_DIR="$PROJECT_DIR/web-ui"
    LOG_DIR="$DATA_ROOT/logs"  # Test mode: keep logs with data for simplicity
fi

log_info "  Data root: $DATA_ROOT"
log_info "  Config:    $CONFIG_DIR"
log_info "  Venv:      $VENV_DIR"
log_info "  Web UI:    $WEBUI_DIR"
log_info "  Logs:      $LOG_DIR"

# =============================================================================
# Step 3: Create Directories
# =============================================================================
log_step "Creating directories..."

create_dir() {
    local dir="$1"
    local owner="${2:-$INSTALL_USER}"
    
    if [[ "$MODE" == "production" ]]; then
        sudo mkdir -p "$dir"
        sudo chown "$owner:$owner" "$dir"
    else
        mkdir -p "$dir"
    fi
    log_info "  Created: $dir"
}

# Data directories
create_dir "$DATA_ROOT"
create_dir "$DATA_ROOT/archives"
create_dir "$DATA_ROOT/analytics"
create_dir "$DATA_ROOT/spectrograms"
create_dir "$DATA_ROOT/upload"
create_dir "$DATA_ROOT/state"
create_dir "$DATA_ROOT/status"
create_dir "$LOG_DIR"

# Config directory (production only)
if [[ "$MODE" == "production" ]]; then
    create_dir "$CONFIG_DIR"
    create_dir "/opt/grape-recorder"
fi

# =============================================================================
# Step 4: Create Python Virtual Environment
# =============================================================================
log_step "Setting up Python virtual environment..."

if [[ "$MODE" == "production" ]]; then
    sudo mkdir -p "$(dirname "$VENV_DIR")"
    sudo python3 -m venv "$VENV_DIR"
    sudo chown -R "$INSTALL_USER:$INSTALL_USER" "$VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
fi

# Activate and install
source "$VENV_DIR/bin/activate"
pip install --upgrade pip

log_info "Installing grape-recorder package..."
pip install -e "$PROJECT_DIR"

# Verify installation
python -c "import grape_recorder; print(f'  ✅ grape_recorder installed')"
python -c "import digital_rf; print(f'  ✅ digital_rf installed')"

deactivate

# =============================================================================
# Step 5: Install Web UI Dependencies
# =============================================================================
log_step "Setting up Web UI..."

if command -v npm &> /dev/null; then
    if [[ "$MODE" == "production" ]]; then
        # Copy web-ui to /opt
        sudo mkdir -p "$WEBUI_DIR"
        sudo cp -r "$PROJECT_DIR/web-ui/"* "$WEBUI_DIR/"
        sudo chown -R "$INSTALL_USER:$INSTALL_USER" "$WEBUI_DIR"
        cd "$WEBUI_DIR"
    else
        cd "$PROJECT_DIR/web-ui"
    fi
    
    # npm install is non-fatal - Web UI is optional
    if npm install 2>&1; then
        log_info "  ✅ Web UI dependencies installed"
    else
        log_warn "  ⚠️  npm install had issues (Web UI may still work)"
    fi
    cd "$PROJECT_DIR"
else
    log_warn "  ⚠️  npm not found, skipping Web UI setup"
fi

# =============================================================================
# Step 6: Create Configuration Files
# =============================================================================
log_step "Creating configuration files..."

# Environment file
ENV_FILE="$CONFIG_DIR/environment"

if [[ "$MODE" == "production" ]]; then
    sudo tee "$ENV_FILE" > /dev/null << EOF
# GRAPE Recorder Environment Configuration
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)

GRAPE_MODE=production
GRAPE_DATA_ROOT=$DATA_ROOT
GRAPE_LOG_DIR=$LOG_DIR
GRAPE_CONFIG=$CONFIG_DIR/grape-config.toml
GRAPE_VENV=$VENV_DIR
GRAPE_WEBUI=$WEBUI_DIR
GRAPE_LOG_LEVEL=INFO

# These are read from config but can be overridden:
# GRAPE_CALLSIGN=
# GRAPE_GRID_SQUARE=
# GRAPE_STATION_ID=
EOF
    sudo chown "$INSTALL_USER:$INSTALL_USER" "$ENV_FILE"
else
    cat > "$ENV_FILE" << EOF
# GRAPE Recorder Environment Configuration
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)

GRAPE_MODE=test
GRAPE_DATA_ROOT=$DATA_ROOT
GRAPE_LOG_DIR=$LOG_DIR
GRAPE_CONFIG=$CONFIG_DIR/grape-config.toml
GRAPE_VENV=$VENV_DIR
GRAPE_WEBUI=$WEBUI_DIR
GRAPE_LOG_LEVEL=DEBUG
EOF
fi

log_info "  Created: $ENV_FILE"

# Copy/update main config if not exists
MAIN_CONFIG="$CONFIG_DIR/grape-config.toml"
if [[ ! -f "$MAIN_CONFIG" ]]; then
    if [[ "$MODE" == "production" ]]; then
        sudo cp "$PROJECT_DIR/config/grape-config.toml" "$MAIN_CONFIG"
        # Update mode in config
        sudo sed -i 's/mode = "test"/mode = "production"/' "$MAIN_CONFIG"
        sudo sed -i "s|test_data_root = .*|test_data_root = \"/tmp/grape-test\"|" "$MAIN_CONFIG"
        sudo sed -i "s|production_data_root = .*|production_data_root = \"$DATA_ROOT\"|" "$MAIN_CONFIG"
        sudo chown "$INSTALL_USER:$INSTALL_USER" "$MAIN_CONFIG"
    else
        cp "$PROJECT_DIR/config/grape-config.toml" "$MAIN_CONFIG" 2>/dev/null || true
    fi
    log_info "  Created: $MAIN_CONFIG"
else
    log_info "  Config exists: $MAIN_CONFIG (not overwriting)"
fi

# =============================================================================
# Step 7: Install Systemd Services (Production Only)
# =============================================================================
if [[ "$MODE" == "production" ]]; then
    log_step "Installing systemd services..."
    
    # Create service files with correct paths
    SYSTEMD_DIR="/etc/systemd/system"
    
    # Core Recorder Service
    sudo tee "$SYSTEMD_DIR/grape-recorder.service" > /dev/null << EOF
[Unit]
Description=GRAPE Signal Recorder
Documentation=https://github.com/mijahauan/grape-recorder
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_USER
EnvironmentFile=$CONFIG_DIR/environment
WorkingDirectory=$DATA_ROOT

ExecStart=$VENV_DIR/bin/python -m grape_recorder.grape.core_recorder --config \${GRAPE_CONFIG}

Restart=always
RestartSec=30
StartLimitInterval=300
StartLimitBurst=5

# Resource limits
MemoryMax=2G
CPUQuota=80%

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=grape-recorder

[Install]
WantedBy=multi-user.target
EOF
    
    # Analytics Service (template for per-channel)
    sudo tee "$SYSTEMD_DIR/grape-analytics@.service" > /dev/null << EOF
[Unit]
Description=GRAPE Analytics Service - %i
Documentation=https://github.com/mijahauan/grape-recorder
After=grape-recorder.service
Wants=grape-recorder.service

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_USER
EnvironmentFile=$CONFIG_DIR/environment
WorkingDirectory=$DATA_ROOT

ExecStart=$VENV_DIR/bin/python -m grape_recorder.grape.analytics_service --config \${GRAPE_CONFIG} --channel "%i"

Restart=always
RestartSec=30
StartLimitInterval=300
StartLimitBurst=5

StandardOutput=journal
StandardError=journal
SyslogIdentifier=grape-analytics-%i

[Install]
WantedBy=multi-user.target
EOF
    
    # Analytics Service (all channels)
    sudo tee "$SYSTEMD_DIR/grape-analytics.service" > /dev/null << EOF
[Unit]
Description=GRAPE Analytics Service (All Channels)
Documentation=https://github.com/mijahauan/grape-recorder
After=grape-recorder.service
Wants=grape-recorder.service

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_USER
EnvironmentFile=$CONFIG_DIR/environment
WorkingDirectory=$DATA_ROOT

ExecStart=$VENV_DIR/bin/python -m grape_recorder.grape.analytics_service --config \${GRAPE_CONFIG}

Restart=always
RestartSec=30
StartLimitInterval=300
StartLimitBurst=5

StandardOutput=journal
StandardError=journal
SyslogIdentifier=grape-analytics

[Install]
WantedBy=multi-user.target
EOF

    # Web UI Service
    sudo tee "$SYSTEMD_DIR/grape-webui.service" > /dev/null << EOF
[Unit]
Description=GRAPE Web UI
Documentation=https://github.com/mijahauan/grape-recorder
After=network-online.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_USER
EnvironmentFile=$CONFIG_DIR/environment
WorkingDirectory=$WEBUI_DIR

ExecStart=/usr/bin/node monitoring-server-v3.js

Restart=always
RestartSec=10

StandardOutput=journal
StandardError=journal
SyslogIdentifier=grape-webui

[Install]
WantedBy=multi-user.target
EOF

    # Daily Upload Service
    sudo tee "$SYSTEMD_DIR/grape-upload.service" > /dev/null << EOF
[Unit]
Description=GRAPE Daily DRF Upload to PSWS
Documentation=https://github.com/mijahauan/grape-recorder
After=network-online.target

[Service]
Type=oneshot
User=$INSTALL_USER
Group=$INSTALL_USER
EnvironmentFile=$CONFIG_DIR/environment

ExecStart=$PROJECT_DIR/scripts/daily-drf-upload.sh

TimeoutStartSec=3600
StandardOutput=journal
StandardError=journal
SyslogIdentifier=grape-upload

[Install]
WantedBy=multi-user.target
EOF

    # Daily Upload Timer
    sudo tee "$SYSTEMD_DIR/grape-upload.timer" > /dev/null << EOF
[Unit]
Description=GRAPE Daily Upload Timer
Documentation=https://github.com/mijahauan/grape-recorder

[Timer]
OnCalendar=*-*-* 00:30:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF

    # Reload systemd
    sudo systemctl daemon-reload
    
    log_info "  Installed systemd services:"
    log_info "    - grape-recorder.service"
    log_info "    - grape-analytics.service"
    log_info "    - grape-analytics@.service (template)"
    log_info "    - grape-webui.service"
    log_info "    - grape-upload.service"
    log_info "    - grape-upload.timer"
    
    # Enable services
    log_step "Enabling services for auto-start..."
    sudo systemctl enable grape-recorder.service
    sudo systemctl enable grape-analytics.service
    sudo systemctl enable grape-webui.service
    sudo systemctl enable grape-upload.timer
    
    log_info "  Services enabled (will start on boot)"

    # Create logrotate config
    sudo tee "/etc/logrotate.d/grape-recorder" > /dev/null << EOF
$LOG_DIR/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 $INSTALL_USER $INSTALL_USER
}
EOF
    log_info "  Created logrotate configuration"
fi

# =============================================================================
# Step 8: Summary
# =============================================================================
echo ""
echo "=============================================="
echo "  Installation Complete!"
echo "=============================================="
echo ""

if [[ "$MODE" == "production" ]]; then
    echo "Production mode installed. Next steps:"
    echo ""
    echo "1. Edit configuration:"
    echo "   sudo nano $CONFIG_DIR/grape-config.toml"
    echo ""
    echo "2. Set your station info (callsign, grid_square, etc.)"
    echo ""
    echo "3. Start services:"
    echo "   sudo systemctl start grape-recorder"
    echo "   sudo systemctl start grape-analytics"
    echo "   sudo systemctl start grape-webui"
    echo ""
    echo "4. Enable daily uploads (after SSH key setup):"
    echo "   sudo systemctl start grape-upload.timer"
    echo ""
    echo "5. Check status:"
    echo "   sudo systemctl status grape-recorder"
    echo "   journalctl -u grape-recorder -f"
    echo ""
    echo "Web UI: http://localhost:3000"
else
    echo "Test mode installed. Next steps:"
    echo ""
    echo "1. Edit configuration:"
    echo "   nano $CONFIG_DIR/grape-config.toml"
    echo ""
    echo "2. Start all services:"
    echo "   $PROJECT_DIR/scripts/grape-all.sh -start"
    echo ""
    echo "3. Check status:"
    echo "   $PROJECT_DIR/scripts/grape-all.sh -status"
    echo ""
    echo "4. Stop services:"
    echo "   $PROJECT_DIR/scripts/grape-all.sh -stop"
    echo ""
    echo "Web UI: http://localhost:3000"
fi

echo ""
echo "Data location: $DATA_ROOT"
echo "=============================================="
