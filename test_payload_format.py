#!/usr/bin/env python3
"""
Test RTP Payload Format

Examines raw bytes to determine if KA9Q sends int16 or float32
"""

import socket
import struct
import numpy as np

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', 5004))

mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

print("Waiting for SSRC 5000000 packets...")
packet_count = 0

while packet_count < 5:
    data, addr = sock.recvfrom(8192)
    if len(data) < 12:
        continue
    
    ssrc = struct.unpack('>I', data[8:12])[0]
    if ssrc != 5000000:
        continue
    
    packet_count += 1
    payload = data[12:]
    
    print(f"\n=== Packet {packet_count} ===")
    print(f"Total RTP packet size: {len(data)} bytes")
    print(f"Payload size: {len(payload)} bytes")
    print(f"First 32 bytes (hex): {payload[:32].hex()}")
    
    # Try as int16 (big-endian)
    if len(payload) >= 8:
        int16_samples = np.frombuffer(payload[:8], dtype='>i2')
        print(f"\nAs int16 (big-endian): {int16_samples}")
        print(f"  Range: {int16_samples.min()} to {int16_samples.max()}")
        print(f"  Normalized to [-1,1]: {int16_samples.astype(float)/32768}")
    
    # Try as float32 (big-endian)
    if len(payload) >= 8:
        float32_samples = np.frombuffer(payload[:8], dtype='>f4')
        print(f"\nAs float32 (big-endian): {float32_samples}")
        print(f"  Range: {float32_samples.min():.6f} to {float32_samples.max():.6f}")
    
    # Try as float32 (little-endian)
    if len(payload) >= 8:
        float32_le_samples = np.frombuffer(payload[:8], dtype='<f4')
        print(f"\nAs float32 (little-endian): {float32_le_samples}")
        print(f"  Range: {float32_le_samples.min():.6f} to {float32_le_samples.max():.6f}")
    
    # Check if payload size makes sense
    print(f"\nPayload size analysis:")
    print(f"  {len(payload)} bytes / 4 = {len(payload)/4} (int16 I/Q pairs or float32 samples)")
    print(f"  {len(payload)} bytes / 8 = {len(payload)/8} (float32 I/Q pairs)")
    
sock.close()

print("\n\n=== CONCLUSIONS ===")
print("If int16 values are reasonable (-32768 to 32767 range), it's int16 format")
print("If float32 values are reasonable (-1.0 to 1.0 range), it's float32 format")
print("If values look like garbage/huge numbers, wrong format is being used")
