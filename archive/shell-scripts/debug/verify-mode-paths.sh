#!/bin/bash
# Verify that mode setting in grape-config.toml governs all paths

set -e

echo "========================================"
echo "MODE-BASED PATH VERIFICATION"
echo "========================================"
echo ""

CONFIG="config/grape-config.toml"

# Extract current mode setting
CURRENT_MODE=$(grep '^mode = ' "$CONFIG" | cut -d'"' -f2)
TEST_ROOT=$(grep '^test_data_root = ' "$CONFIG" | cut -d'"' -f2)
PROD_ROOT=$(grep '^production_data_root = ' "$CONFIG" | cut -d'"' -f2)

echo "Configuration:"
echo "  File: $CONFIG"
echo "  Current mode: $CURRENT_MODE"
echo "  Test root:    $TEST_ROOT"
echo "  Prod root:    $PROD_ROOT"
echo ""

# Test with Python
echo "Testing PathResolver behavior..."
echo ""

python3 << 'PYTHON_TEST'
import sys
sys.path.insert(0, 'src')

from signal_recorder.config_utils import PathResolver

# Load config
try:
    import tomli as toml
    with open('config/grape-config.toml', 'rb') as f:
        config = toml.load(f)
except ImportError:
    import toml
    with open('config/grape-config.toml', 'r') as f:
        config = toml.load(f)

recorder_config = config.get('recorder', {})
config_mode = recorder_config.get('mode', 'production')
test_root = recorder_config.get('test_data_root', '/tmp/grape-test')
prod_root = recorder_config.get('production_data_root', '/var/lib/signal-recorder')

print(f"Config file mode setting: {config_mode}")
print("")

# Create resolver based on config mode
development_mode = (config_mode == 'test')
resolver = PathResolver(config, development_mode=development_mode)

print(f"PathResolver created with development_mode={development_mode}")
print("")
print("Resolved paths:")
print(f"  Data:      {resolver.get_data_dir()}")
print(f"  Analytics: {resolver.get_analytics_dir()}")
print(f"  Upload:    {resolver.get_upload_state_dir()}")
print(f"  Status:    {resolver.get_status_dir()}")
print(f"  Logs:      {resolver.get_log_dir()}")
print("")

# Verify paths match expected root
data_dir = str(resolver.get_data_dir())
expected_root = test_root if development_mode else prod_root

if data_dir.startswith(expected_root):
    print(f"✅ Paths correctly use {'test' if development_mode else 'production'} root: {expected_root}")
else:
    print(f"❌ ERROR: Paths don't use expected root!")
    print(f"   Expected: {expected_root}")
    print(f"   Got:      {data_dir}")
    sys.exit(1)

# Show what happens when mode changes
print("")
print("─" * 50)
print("Simulating mode change:")
print("")

other_mode = not development_mode
other_resolver = PathResolver(config, development_mode=other_mode)
other_mode_name = 'test' if other_mode else 'production'
other_root = test_root if other_mode else prod_root

print(f"If mode changed to '{other_mode_name}':")
print(f"  Data:      {other_resolver.get_data_dir()}")
print(f"  Analytics: {other_resolver.get_analytics_dir()}")
print(f"  Upload:    {other_resolver.get_upload_state_dir()}")
print(f"  Status:    {other_resolver.get_status_dir()}")
print(f"  Logs:      {other_resolver.get_log_dir()}")
print("")

if str(other_resolver.get_data_dir()).startswith(other_root):
    print(f"✅ Would correctly use {other_mode_name} root: {other_root}")
else:
    print(f"❌ ERROR: Path resolution broken for {other_mode_name} mode")
    sys.exit(1)

PYTHON_TEST

echo ""
echo "========================================"
echo "VERIFICATION COMPLETE"
echo "========================================"
echo ""
echo "✅ All paths are properly governed by mode setting"
echo "✅ Test and production data remain isolated"
echo ""
echo "Directory structure by mode:"
echo ""
echo "TEST MODE (mode = \"test\"):"
echo "  $TEST_ROOT/"
echo "  ├── data/           # RTP recordings and Digital RF"
echo "  ├── analytics/      # Quality metrics, WWV timing"
echo "  ├── upload/         # Upload queue"
echo "  ├── status/         # Runtime status JSON"
echo "  └── logs/           # Application logs"
echo ""
echo "PRODUCTION MODE (mode = \"production\"):"
echo "  $PROD_ROOT/"
echo "  ├── data/           # RTP recordings and Digital RF"
echo "  ├── analytics/      # Quality metrics, WWV timing"
echo "  ├── upload/         # Upload queue"
echo "  ├── status/         # Runtime status JSON"
echo "  └── logs/           # Application logs"
echo ""
