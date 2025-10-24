#!/bin/bash
# Compare packets from signal-recorder vs control utility

set -e

echo "=========================================="
echo "Packet Comparison Test"
echo "=========================================="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

echo "This script will:"
echo "1. Capture packets from the 'control' utility"
echo "2. Capture packets from signal-recorder"
echo "3. Compare the packet structures"
echo ""

# Test 1: Capture control utility packets
echo "Step 1: Capturing control utility packets..."
echo "----------------------------------------"
tcpdump -i lo -n -w /tmp/control-packets.pcap 'dst host 239.251.200.193 and dst port 5006' &
TCPDUMP_PID=$!
sleep 1

# Send a poll command with control
timeout 2 control -v 239.251.200.193 > /dev/null 2>&1 || true

sleep 1
kill $TCPDUMP_PID 2>/dev/null || true
sleep 1

CONTROL_COUNT=$(tcpdump -r /tmp/control-packets.pcap 2>/dev/null | wc -l)
echo "Captured $CONTROL_COUNT packets from control utility"
echo ""

# Test 2: Capture signal-recorder packets
echo "Step 2: Capturing signal-recorder packets..."
echo "----------------------------------------"
tcpdump -i lo -n -w /tmp/signal-recorder-packets.pcap 'dst host 239.251.200.193 and dst port 5006' &
TCPDUMP_PID=$!
sleep 1

# Run signal-recorder
cd /home/mjh/git/signal-recorder
source docs/venv/bin/activate
timeout 2 signal-recorder create-channels --config config/test-new-channel.toml > /dev/null 2>&1 || true

sleep 1
kill $TCPDUMP_PID 2>/dev/null || true
sleep 1

SR_COUNT=$(tcpdump -r /tmp/signal-recorder-packets.pcap 2>/dev/null | wc -l)
echo "Captured $SR_COUNT packets from signal-recorder"
echo ""

# Compare
echo "Step 3: Analyzing packet structures..."
echo "----------------------------------------"
echo ""
echo "=== Control utility packets ===" 
tcpdump -r /tmp/control-packets.pcap -n -v -X 2>&1 | head -50
echo ""
echo "=== Signal-recorder packets ==="
tcpdump -r /tmp/signal-recorder-packets.pcap -n -v -X 2>&1 | head -100
echo ""

echo "=========================================="
echo "Analysis Complete"
echo "=========================================="

