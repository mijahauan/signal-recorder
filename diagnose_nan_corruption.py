#!/usr/bin/env python3
"""
Diagnostic tool for NaN/Inf corruption in RTP packets from radiod

Usage:
    python diagnose_nan_corruption.py [duration_seconds]
"""

import socket
import struct
import numpy as np
import sys
from collections import defaultdict
from datetime import datetime

MULTICAST_GROUP = '239.0.0.1'
MULTICAST_PORT = 5004

# Default duration, can be overridden by sys.argv[1]
DURATION = 60

def parse_rtp_header(data):
    """Parse RTP header"""
    if len(data) < 12:
        return None, "Packet too short for base RTP header"
    
    # RTP header format (simplified)
    byte0 = data[0]
    version = (byte0 >> 6) & 0x03
    padding = (byte0 >> 5) & 0x01
    extension = (byte0 >> 4) & 0x01
    csrc_count = byte0 & 0x0F
    
    byte1 = data[1]
    marker = (byte1 >> 7) & 0x01
    payload_type = byte1 & 0x7F
    
    sequence = struct.unpack('>H', data[2:4])[0]
    timestamp = struct.unpack('>I', data[4:8])[0]
    ssrc = struct.unpack('>I', data[8:12])[0]
    
    header_len = 12 + (csrc_count * 4)
    
    # --- FIX: Account for extension header ---
    if extension == 1:
        if len(data) < header_len + 4:
            return None, "Packet too short for extension header"
        
        # Extension header: 2 bytes ID, 2 bytes length (in 32-bit words)
        ext_len_words = struct.unpack('>H', data[header_len + 2:header_len + 4])[0]
        ext_len_bytes = ext_len_words * 4
        
        # Total header length includes the 4-byte extension header itself
        # plus the extension payload
        header_len += 4 + ext_len_bytes
        
        if len(data) < header_len:
            return None, "Packet too short for extension header payload"
    # --- END FIX ---
            
    return {
        'version': version,
        'padding': padding, # Pass padding flag out
        'extension': extension,
        'sequence': sequence,
        'timestamp': timestamp,
        'ssrc': ssrc,
        'payload_type': payload_type,
        'header_len': header_len
    }, None

def main():
    global DURATION
    # --- FIX: Safe argument parsing ---
    try:
        DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    except ValueError:
        print(f"Error: Invalid duration '{sys.argv[1]}'. Must be an integer.")
        print(__doc__) # Print the docstring as a usage guide
        sys.exit(1)
    # --- END FIX ---

    print(f"Monitoring radiod RTP packets for {DURATION} seconds...")
    print(f"Joining {MULTICAST_GROUP}:{MULTICAST_PORT}")
    print(f"Looking for NaN/Inf corruption\n")
    
    # Statistics
    total_packets = 0
    corrupt_packets = 0
    parse_errors = defaultdict(int)
    by_ssrc = defaultdict(lambda: {'total': 0, 'corrupt': 0, 'nan_samples': 0, 'inf_samples': 0})
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Bind to the port
    try:
        sock.bind(('', MULTICAST_PORT))
    except OSError as e:
        print(f"Error: Could not bind to port {MULTICAST_PORT}. {e}")
        print("Check if another process is using the port.")
        sys.exit(1)
    
    # Join multicast group
    mreq = struct.pack('4sl', socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as e:
        print(f"Error: Could not join multicast group {MULTICAST_GROUP}. {e}")
        print("Check network configuration and firewall.")
        sys.exit(1)
    
    sock.settimeout(1.0)
    
    start_time = datetime.now()
    
    try:
        while (datetime.now() - start_time).total_seconds() < DURATION:
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                continue
            
            total_packets += 1
            
            # Parse RTP header
            rtp, error = parse_rtp_header(data)
            if rtp is None:
                parse_errors[error] += 1
                continue
            
            # Extract IQ payload (float32 interleaved I/Q)
            payload = data[rtp['header_len']:]
            if len(payload) % 8 != 0:
                continue
            
            # Parse as float32
            samples = np.frombuffer(payload, dtype=np.float32)
            
            # Check for NaN/Inf
            finite_mask = np.isfinite(samples)
            if not np.all(finite_mask):
                corrupt_packets += 1
                nan_count = np.sum(np.isnan(samples))
                inf_count = np.sum(np.isinf(samples))
                
                ssrc = rtp['ssrc']
                by_ssrc[ssrc]['total'] += 1
                by_ssrc[ssrc]['corrupt'] += 1
                by_ssrc[ssrc]['nan_samples'] += nan_count
                by_ssrc[ssrc]['inf_samples'] += inf_count
                
                # Dump first corrupt packet details
                if corrupt_packets == 1:
                    print(f"\n=== FIRST CORRUPT PACKET ===")
                    print(f"SSRC: {ssrc} (freq: {ssrc/1e6:.2f} MHz)")
                    print(f"Sequence: {rtp['sequence']}")
                    print(f"Timestamp: {rtp['timestamp']}")
                    print(f"Payload size: {len(payload)} bytes")
                    print(f"Total samples: {len(samples)}")
                    print(f"NaN values: {nan_count}")
                    print(f"Inf values: {inf_count}")
                    print(f"Sample range: [{np.nanmin(samples):.6f}, {np.nanmax(samples):.6f}]")
                    
                    # Show which positions are corrupt
                    corrupt_indices = np.where(~finite_mask)[0]
                    print(f"Corrupt positions (first 20): {corrupt_indices[:20].tolist()}")
                    print(f"Corrupt values (first 20): {samples[corrupt_indices[:20]].tolist()}")
                    print()
            else:
                ssrc = rtp['ssrc']
                by_ssrc[ssrc]['total'] += 1
            
            # Progress
            if total_packets % 1000 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = total_packets / elapsed if elapsed > 0 else 0
                print(f"Progress: {total_packets} packets, {corrupt_packets} corrupt ({100*corrupt_packets/total_packets:.3f}%), {rate:.0f} pkt/s", end='\r')
    
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    
    finally:
        sock.close()
    
    # Summary
    print("\n\n=== SUMMARY ===")
    print(f"Duration: {(datetime.now() - start_time).total_seconds():.1f} seconds")
    print(f"Total packets: {total_packets}")
    print(f"Corrupt packets: {corrupt_packets} ({100*corrupt_packets/total_packets:.3f}%)")
    
    if parse_errors:
        print("\n=== PARSE ERRORS ===")
        for error, count in sorted(parse_errors.items()):
            print(f"{error}: {count}")
    
    print("\n=== BY CHANNEL (SSRC) ===")
    for ssrc in sorted(by_ssrc.keys()):
        stats = by_ssrc[ssrc]
        freq_mhz = ssrc / 1e6
        corrupt_pct = 100 * stats['corrupt'] / stats['total'] if stats['total'] > 0 else 0
        print(f"SSRC {ssrc:>10} ({freq_mhz:>6.2f} MHz): "
              f"{stats['total']:>6} pkts, {stats['corrupt']:>4} corrupt ({corrupt_pct:>5.2f}%), "
              f"{stats['nan_samples']:>5} NaN, {stats['inf_samples']:>5} Inf")

if __name__ == '__main__':
    main()
