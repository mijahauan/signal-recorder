#!/bin/bash
# Debug script to capture and analyze radiod control packets

set -e

echo "=========================================="
echo "Radiod Control Packet Debug Tool"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

CAPTURE_FILE="/tmp/radiod-control-capture.pcap"
DECODED_FILE="/tmp/radiod-control-decoded.txt"

echo "Step 1: Start packet capture on loopback"
echo "----------------------------------------"
echo "Capturing packets to 239.251.200.193:5006..."
echo "Press Ctrl+C after running the channel creation command"
echo ""

# Start tcpdump
tcpdump -i lo -n -w "$CAPTURE_FILE" 'dst host 239.251.200.193 and dst port 5006' &
TCPDUMP_PID=$!

echo "tcpdump started (PID: $TCPDUMP_PID)"
echo ""
echo "Now run in another terminal:"
echo "  signal-recorder create-channels --config config/test-new-channel.toml"
echo ""
echo "Press Enter when done to stop capture..."
read

# Stop tcpdump
kill $TCPDUMP_PID 2>/dev/null || true
sleep 1

echo ""
echo "Step 2: Analyze captured packets"
echo "----------------------------------------"

# Check if we captured anything
PACKET_COUNT=$(tcpdump -r "$CAPTURE_FILE" 2>/dev/null | wc -l)
echo "Captured $PACKET_COUNT packets"
echo ""

if [ "$PACKET_COUNT" -eq 0 ]; then
    echo "ERROR: No packets captured!"
    echo "This means packets are not reaching the loopback interface."
    exit 1
fi

echo "Packet details:"
tcpdump -r "$CAPTURE_FILE" -n -v -X 2>&1 | tee "$DECODED_FILE"

echo ""
echo "=========================================="
echo "Analysis Complete"
echo "=========================================="
echo ""
echo "Files created:"
echo "  $CAPTURE_FILE - Raw packet capture"
echo "  $DECODED_FILE - Decoded packet dump"
echo ""
echo "To check radiod logs for errors:"
echo "  sudo journalctl -u radiod@ac0g-bee1-rx888 -f"
echo ""

