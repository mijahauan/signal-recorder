#!/usr/bin/env python3
"""
Test for ka9q-radio Custom Header

Captures raw RTP packets and analyzes the payload structure
to determine if there's a custom status header after the 12-byte RTP header.
"""

import socket
import struct
import numpy as np

def capture_and_analyze():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    print("Capturing SSRC 5000000 packets to analyze header structure...\n")
    
    for pkt_num in range(5):
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
        
        ssrc = struct.unpack('>I', data[8:12])[0]
        if ssrc != 5000000:
            continue
        
        print(f"=== Packet {pkt_num + 1} ===")
        print(f"Total packet size: {len(data)} bytes")
        print(f"RTP header (12 bytes): {data[:12].hex()}")
        
        # Show next 64 bytes after RTP header
        payload_start = data[12:76]
        print(f"\nBytes 12-75 (potential custom header + IQ data):")
        print(f"  Hex: {payload_start.hex()}")
        
        # Try different header sizes
        for header_size in [0, 16, 32, 64, 128]:
            if len(data) < 12 + header_size + 8:
                continue
            
            print(f"\n  Assuming {header_size}-byte custom header:")
            
            # Skip RTP header + custom header
            iq_start = 12 + header_size
            payload = data[iq_start:]
            
            if len(payload) < 8:
                print(f"    Payload too short")
                continue
            
            # Try parsing as int16 pairs
            try:
                samples = np.frombuffer(payload[:320], dtype='>i2').reshape(-1, 2)
                
                # Check if values look reasonable for IQ data
                i_vals = samples[:, 0]
                q_vals = samples[:, 1]
                
                i_range = (i_vals.min(), i_vals.max())
                q_range = (q_vals.min(), q_vals.max())
                i_mean = i_vals.mean()
                q_mean = q_vals.mean()
                
                # IQ data should have:
                # - Values in reasonable range (-10000 to +10000 typical)
                # - Small DC offset (means near 0)
                # - Similar variance in I and Q
                
                looks_good = (
                    abs(i_range[0]) < 20000 and abs(i_range[1]) < 20000 and
                    abs(q_range[0]) < 20000 and abs(q_range[1]) < 20000 and
                    abs(i_mean) < 5000 and abs(q_mean) < 5000
                )
                
                print(f"    I range: {i_range}, mean: {i_mean:.1f}")
                print(f"    Q range: {q_range}, mean: {q_mean:.1f}")
                print(f"    Looks valid: {'✓ YES' if looks_good else '✗ NO'}")
                
                # Also check payload size
                remaining = len(payload)
                if remaining % 4 == 0:
                    num_samples = remaining // 4
                    print(f"    Payload: {remaining} bytes = {num_samples} IQ pairs")
                    if num_samples in [80, 160, 320]:  # Common sizes
                        print(f"    ✓ Standard packet size!")
                
            except Exception as e:
                print(f"    Error: {e}")
        
        print("\n" + "="*60 + "\n")
    
    sock.close()
    
    print("\n=== CONCLUSION ===")
    print("Look for the header size where:")
    print("  1. I and Q values are reasonable (-10000 to +10000)")
    print("  2. Means are close to 0")
    print("  3. Payload size is 320, 640, or 1280 bytes (80, 160, or 320 IQ pairs)")
    print("\nIf header_size=0 looks good, there's no custom header.")
    print("Otherwise, the correct header_size is the one that gives valid IQ data.")

if __name__ == '__main__':
    capture_and_analyze()
