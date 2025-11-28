#!/bin/bash
set -e

cd /home/mjh/git/signal-recorder
source venv/bin/activate

# Clean up previous test data
echo "🧹 Cleaning up previous test data..."
rm -rf /tmp/grape-test/analytics/WWV_10_MHz/decimated/*.npz 2>/dev/null || true
rm -rf /tmp/grape-test/analytics/WWV_10_MHz/digital_rf 2>/dev/null || true
rm -f /tmp/grape-test/state/analytics-WWV_10_MHz.json 2>/dev/null || true
rm -f /tmp/grape-test/analytics/WWV_10_MHz/drf_writer_state.json 2>/dev/null || true
# Ensure directories exist
mkdir -p /tmp/grape-test/analytics/WWV_10_MHz/decimated
mkdir -p /tmp/grape-test/state

# Create test 10Hz NPZ file
echo "📝 Creating test 10Hz NPZ file..."
python3 - << 'EOF'
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

output_dir = Path("/tmp/grape-test/analytics/WWV_10_MHz/decimated")
output_dir.mkdir(parents=True, exist_ok=True)

num_samples = 600
iq_samples = (np.random.randn(num_samples) + 1j * np.random.randn(num_samples)).astype(np.complex64)
iq_samples *= 0.1

# Use current time for both timestamp string and RTP calculation
now = datetime.now(timezone.utc)
timestamp = now.strftime("%Y%m%dT%H%M%SZ")
filename = f"{timestamp}_10000000_iq_10hz.npz"

# Calculate realistic RTP timestamp based on current time
# RTP timestamp = samples since epoch at 16kHz original sample rate
current_unix_time = now.timestamp()
rtp_timestamp = int(current_unix_time * 16000)  # 16kHz = original sample rate

np.savez_compressed(
    output_dir / filename,
    iq=iq_samples,
    rtp_timestamp=rtp_timestamp,
    sample_rate_original=16000,
    sample_rate_decimated=10,
    decimation_factor=1600,
    created_timestamp=current_unix_time,
    source_file=f"{timestamp}_10000000_iq.npz"
)

print(f"✅ Created: {output_dir / filename}")
EOF

# Run DRF writer (processes once then exits)
echo -e "\n🔄 Running DRF writer..."
echo "  (waiting 15 seconds for processing...)"
timeout 15 python -m signal_recorder.drf_writer_service \
  --input-dir /tmp/grape-test/analytics/WWV_10_MHz/decimated \
  --output-dir /tmp/grape-test/analytics/WWV_10_MHz \
  --channel-name "ch0" \
  --frequency-hz 10000000 \
  --analytics-state-file /tmp/grape-test/state/analytics-WWV_10_MHz.json \
  --callsign AC0G \
  --grid-square EM38ww \
  --receiver-name GRAPE \
  --psws-station-id S000171 \
  --psws-instrument-id 172 \
  --poll-interval 2 \
  --log-level INFO 2>&1 || echo "  DRF writer exited with code $?"

# Verify output
echo -e "\n✅ Verifying output..."
# Find the DRF top-level directory (parent of ch0)
DRF_PATH=$(find /tmp/grape-test/analytics/WWV_10_MHz/digital_rf -name "ch0" -type d | head -1)
if [ -n "$DRF_PATH" ]; then
    # Get parent directory (OBS2025-11-20T00-00)
    DRF_PARENT=$(dirname "$DRF_PATH")
    echo "Testing DRF directory: $DRF_PARENT"
    python test-drf-wsprdaemon-compat.py "$DRF_PARENT"
else
    echo "❌ No DRF output found"
fi