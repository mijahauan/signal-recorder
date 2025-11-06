#!/usr/bin/env python3
"""Check if RTP stream has gaps or discontinuities"""
import socket, struct, time, numpy as np

ssrc = 5000000
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', 5004))
mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

print("Checking RTP stream continuity...")

last_seq = None
last_ts = None
seq_gaps = []
ts_gaps = []
packet_count = 0
start = time.time()

while packet_count < 500:  # Check 500 packets (~10 seconds)
    data, _ = sock.recvfrom(8192)
    if len(data) < 12:
        continue
        
    pkt_ssrc = struct.unpack('>I', data[8:12])[0]
    if pkt_ssrc != ssrc:
        continue
    
    # Parse RTP header
    seq = struct.unpack('>H', data[2:4])[0]
    ts = struct.unpack('>I', data[4:8])[0]
    
    if last_seq is not None:
        expected_seq = (last_seq + 1) & 0xFFFF
        if seq != expected_seq:
            gap = (seq - expected_seq) & 0xFFFF
            seq_gaps.append((packet_count, gap))
            print(f"Packet {packet_count}: Sequence gap! Expected {expected_seq}, got {seq} (gap={gap})")
    
    if last_ts is not None:
        ts_delta = (ts - last_ts) & 0xFFFFFFFF
        if ts_delta != 320:  # Should be 320 samples per packet
            ts_gaps.append((packet_count, ts_delta))
            if len(ts_gaps) <= 10:  # Only print first 10
                print(f"Packet {packet_count}: Timestamp gap! Delta={ts_delta} (expected 320)")
    
    last_seq = seq
    last_ts = ts
    packet_count += 1

sock.close()

print(f"\n=== RESULTS ({packet_count} packets, {time.time()-start:.1f}s) ===")
print(f"Sequence gaps: {len(seq_gaps)}")
print(f"Timestamp gaps (not 320): {len(ts_gaps)}")

if len(seq_gaps) == 0 and len(ts_gaps) == 0:
    print("\n✓ RTP stream is perfectly continuous - no gaps!")
    print("  Problem must be in audio processing, not RTP reception")
else:
    print("\n⚠️  RTP stream has discontinuities")
    if len(ts_gaps) > 0:
        print(f"  Timestamp deltas: {[g[1] for g in ts_gaps[:10]]}")
