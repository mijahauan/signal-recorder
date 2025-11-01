#!/usr/bin/env python3
"""Check RTP timestamps to determine actual sample rate"""
import socket, struct, time

def check_rtp_rate(ssrc=5000000, num_packets=100):
    """Check RTP timestamp increments to determine sample rate"""
    print(f"Checking RTP timestamps for SSRC {ssrc}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    timestamps = []
    samples_per_packet = []
    
    while len(timestamps) < num_packets:
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
            
        # Parse RTP header
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        rtp_timestamp = struct.unpack('>I', data[4:8])[0]
        timestamps.append(rtp_timestamp)
        
        # Count samples in this packet
        header_byte0 = data[0]
        csrc_count = header_byte0 & 0x0F
        has_extension = (header_byte0 & 0x10) != 0
        payload_offset = 12 + (csrc_count * 4)
        if has_extension and len(data) >= payload_offset + 4:
            ext_length_words = struct.unpack('>H', data[payload_offset+2:payload_offset+4])[0]
            payload_offset += 4 + (ext_length_words * 4)
        
        payload = data[payload_offset:]
        if len(payload) % 4 == 0:
            samples_per_packet.append(len(payload) // 4)
    
    sock.close()
    
    # Analyze timestamp increments
    if len(timestamps) > 1:
        diffs = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        # Handle uint32 wraparound
        diffs = [(d + 2**32) % 2**32 for d in diffs]
        diffs = [d if d < 2**31 else d - 2**32 for d in diffs]
        
        avg_diff = sum(diffs) / len(diffs)
        avg_samples = sum(samples_per_packet) / len(samples_per_packet)
        
        print(f"\n=== RTP TIMESTAMP ANALYSIS ===")
        print(f"Packets analyzed: {len(timestamps)}")
        print(f"Avg timestamp increment: {avg_diff:.1f}")
        print(f"Avg samples per packet: {avg_samples:.1f}")
        
        # RTP timestamp increment = number of samples in packet
        # So if increment is 320, that's 320 samples at the RTP sample rate
        print(f"\n=== SAMPLE RATE DETERMINATION ===")
        print(f"RTP timestamp units represent {avg_diff:.0f} samples")
        print(f"Actual IQ samples in packet: {avg_samples:.0f}")
        
        if abs(avg_diff - 320) < 10:
            print(f"\nTimestamp increment is ~320")
            print(f"This matches 320 samples/packet * 25 packets/sec = 8000 Hz")
            print(f"✓ Confirmed: 8 kHz complex IQ rate (16 kHz real sample_rate)")
        elif abs(avg_diff - 640) < 10:
            print(f"\nTimestamp increment is ~640")
            print(f"This would mean 16 kHz complex IQ rate")
            print(f"⚠ WARNING: Double the expected rate!")
        
        print(f"\nIf timestamps match actual samples: {avg_diff == avg_samples}")

if __name__ == '__main__':
    import sys
    ssrc = int(sys.argv[1]) if len(sys.argv) > 1 else 5000000
    check_rtp_rate(ssrc, num_packets=100)
