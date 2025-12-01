#!/bin/bash
# Common settings for all grape-recorder scripts
# Source this at the top of every shell script:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Determine project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Set Python to use venv - MANDATORY
if [ -f "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/venv/bin/python"
    export VIRTUAL_ENV="$PROJECT_DIR/venv"
    export PATH="$PROJECT_DIR/venv/bin:$PATH"
else
    echo "❌ ERROR: venv not found at $PROJECT_DIR/venv"
    echo "   Run: cd $PROJECT_DIR && python3 -m venv venv && venv/bin/pip install -e ."
    exit 1
fi

# Default config location
DEFAULT_CONFIG="$PROJECT_DIR/config/grape-config.toml"

# Helper to get data root from config
get_data_root() {
    local config="${1:-$DEFAULT_CONFIG}"
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
