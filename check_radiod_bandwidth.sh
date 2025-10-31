#!/bin/bash
# Check radiod's actual bandwidth configuration for IQ channels

echo "=== Checking radiod configuration for SSRC 5000000 ==="
echo ""

# Method 1: Check via radctl if available
if command -v radctl &> /dev/null; then
    echo "Method 1: radctl dump"
    radctl 239.1.2.1:5006 dump 5000000 2>/dev/null || echo "radctl failed"
    echo ""
fi

# Method 2: Listen to status channel for bandwidth info
echo "Method 2: Capturing status packets for SSRC 5000000..."
python3 << 'EOF'
import socket
import struct
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', 5006))  # Status port

mreq = struct.pack('4sl', socket.inet_aton('239.1.2.1'), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
sock.settimeout(5)

print("Listening for status packets (5 second timeout)...")
target_ssrc = 5000000

try:
    for _ in range(100):  # Check up to 100 packets
        data, _ = sock.recvfrom(8192)
        if len(data) < 8:
            continue
        
        # Check if this is for our SSRC
        # Status packets may have SSRC at different offsets
        # Try to find 5000000 (0x004C4B40) in the packet
        if b'\x00\x4C\x4B\x40' in data:
            print(f"\nFound status packet mentioning SSRC {target_ssrc}")
            print(f"Packet size: {len(data)} bytes")
            print(f"First 128 bytes (hex):\n{data[:128].hex()}")
            
            # Look for common patterns
            if b'bandwidth' in data.lower():
                print("Contains 'bandwidth'")
            if b'low' in data.lower():
                print("Contains 'low'")
            if b'high' in data.lower():
                print("Contains 'high'")
            break
            
except socket.timeout:
    print("Timeout - no relevant status packets found")
    
sock.close()
EOF

echo ""
echo "=== Conclusion ==="
echo "Look for bandwidth, low, or high frequency parameters"
echo "If bandwidth < 200 Hz, the 100 Hz tone sidebands are being filtered out"
