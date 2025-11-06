#!/usr/bin/env python3
"""Test RTP packet arrival timing to diagnose choppiness"""
import socket, struct, time
import numpy as np

def test_packet_timing(ssrc=5000000, duration=5):
    """Measure packet arrival timing"""
    print(f"Measuring packet timing for {duration} seconds...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    packet_times = []
    packet_sizes = []
    start = time.time()
    last_time = start
    
    while time.time() - start < duration:
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
            
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        now = time.time()
        packet_times.append(now)
        packet_sizes.append(len(data))
    
    sock.close()
    
    # Analyze timing
    packet_times = np.array(packet_times)
    intervals = np.diff(packet_times) * 1000  # Convert to ms
    
    print(f"\n=== PACKET TIMING ===")
    print(f"Total packets: {len(packet_times)}")
    print(f"Duration: {packet_times[-1] - packet_times[0]:.2f}s")
    print(f"Packet rate: {len(packet_times) / (packet_times[-1] - packet_times[0]):.1f} packets/sec")
    
    print(f"\n=== INTER-PACKET INTERVALS ===")
    print(f"Mean interval: {np.mean(intervals):.2f} ms")
    print(f"Std dev: {np.std(intervals):.2f} ms")
    print(f"Min: {np.min(intervals):.2f} ms")
    print(f"Max: {np.max(intervals):.2f} ms")
    
    # Check for jitter (irregular intervals)
    target_interval = 1000 / 25  # 25 packets/sec = 40ms
    jitter = np.abs(intervals - target_interval)
    
    print(f"\n=== JITTER (deviation from {target_interval:.1f}ms) ===")
    print(f"Mean jitter: {np.mean(jitter):.2f} ms")
    print(f"Max jitter: {np.max(jitter):.2f} ms")
    
    # Find large gaps
    large_gaps = intervals > 100  # >100ms is problematic
    if np.any(large_gaps):
        print(f"\n⚠️ LARGE GAPS (>100ms): {np.sum(large_gaps)}")
        gap_indices = np.where(large_gaps)[0]
        for i in gap_indices[:10]:
            print(f"  Gap {i}: {intervals[i]:.1f} ms")
    
    # Histogram of intervals
    bins = [0, 20, 30, 40, 50, 60, 100, 200, 1000]
    hist, _ = np.histogram(intervals, bins=bins)
    
    print(f"\n=== INTERVAL DISTRIBUTION ===")
    for i in range(len(bins)-1):
        pct = hist[i] / len(intervals) * 100
        print(f"  {bins[i]:3d}-{bins[i+1]:3d} ms: {hist[i]:4d} packets ({pct:5.1f}%)")
    
    print(f"\n=== DIAGNOSIS ===")
    if np.std(intervals) > 10:
        print(f"⚠️ HIGH JITTER: {np.std(intervals):.1f}ms std dev")
        print("   → Packets arriving irregularly (network or processing delay)")
    
    if np.any(large_gaps):
        print(f"⚠️ LARGE GAPS: {np.sum(large_gaps)} gaps >100ms")
        print("   → Packets being dropped or delayed")
    
    if np.mean(intervals) > 50:
        print(f"⚠️ SLOW RATE: {np.mean(intervals):.1f}ms intervals (should be ~40ms)")
        print("   → Not keeping up with real-time")
    
    # This is the KEY for choppiness
    regular_pct = np.sum((intervals > 35) & (intervals < 45)) / len(intervals) * 100
    print(f"\nPackets arriving regularly (35-45ms): {regular_pct:.1f}%")
    if regular_pct < 80:
        print("⚠️ CHOPPINESS LIKELY: Irregular packet arrival")
    else:
        print("✓ Packet timing looks good")

if __name__ == '__main__':
    import sys
    ssrc = int(sys.argv[1]) if len(sys.argv) > 1 else 5000000
    test_packet_timing(ssrc, duration=5)
