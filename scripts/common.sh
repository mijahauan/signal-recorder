#!/bin/bash
# Common settings for all grape-recorder scripts
# Source this at the top of every shell script:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Determine project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Source environment file if exists (production mode)
# Order: /etc/grape-recorder/environment -> PROJECT_DIR/config/environment
if [ -f "/etc/grape-recorder/environment" ]; then
    source "/etc/grape-recorder/environment"
elif [ -f "$PROJECT_DIR/config/environment" ]; then
    source "$PROJECT_DIR/config/environment"
fi

# Determine venv location (from env or default)
VENV_PATH="${GRAPE_VENV:-$PROJECT_DIR/venv}"

# Set Python to use venv - MANDATORY
if [ -f "$VENV_PATH/bin/python" ]; then
    PYTHON="$VENV_PATH/bin/python"
    export VIRTUAL_ENV="$VENV_PATH"
    export PATH="$VENV_PATH/bin:$PATH"
else
    echo "❌ ERROR: venv not found at $VENV_PATH"
    echo "   Run: cd $PROJECT_DIR && python3 -m venv venv && venv/bin/pip install -e ."
    exit 1
fi

# Default config location (from env or default)
DEFAULT_CONFIG="${GRAPE_CONFIG:-$PROJECT_DIR/config/grape-config.toml}"

# Helper to get data root from config or environment
get_data_root() {
    local config="${1:-$DEFAULT_CONFIG}"
    
    # First check environment variable (set by install.sh or systemd)
    if [ -n "${GRAPE_DATA_ROOT:-}" ]; then
        echo "$GRAPE_DATA_ROOT"
        return
    fi
    
    # Fall back to parsing config file
    if [ -f "$config" ]; then
        local mode=$(grep '^mode' "$config" | cut -d'"' -f2)
        if [ "$mode" = "production" ]; then
            grep '^production_data_root' "$config" | cut -d'"' -f2
        else
            grep '^test_data_root' "$config" | cut -d'"' -f2
        fi
    else
        echo "/tmp/grape-test"
    fi
}

# Helper to get current mode
get_mode() {
    if [ -n "${GRAPE_MODE:-}" ]; then
        echo "$GRAPE_MODE"
    elif [ -f "$DEFAULT_CONFIG" ]; then
        grep '^mode' "$DEFAULT_CONFIG" | cut -d'"' -f2
    else
        echo "test"
    fi
}

# Helper to get log directory (FHS: /var/log/grape-recorder for production)
get_log_dir() {
    if [ -n "${GRAPE_LOG_DIR:-}" ]; then
        echo "$GRAPE_LOG_DIR"
    elif [ "$(get_mode)" = "production" ]; then
        echo "/var/log/grape-recorder"
    else
        echo "$(get_data_root)/logs"
    fi
}
