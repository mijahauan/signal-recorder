#!/usr/bin/env python3
"""Test actual sample rate from RTP stream"""
import socket, struct, numpy as np, time

def measure_actual_rate(ssrc=5000000, duration=5):
    """Measure actual IQ sample rate"""
    print(f"Measuring sample rate for SSRC {ssrc} over {duration} seconds...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 5004))
    mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    sample_count = 0
    packet_count = 0
    start = time.time()
    
    while time.time() - start < duration:
        data, _ = sock.recvfrom(8192)
        if len(data) < 12:
            continue
            
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        packet_count += 1
        
        # Parse payload
        header_byte0 = data[0]
        csrc_count = header_byte0 & 0x0F
        has_extension = (header_byte0 & 0x10) != 0
        payload_offset = 12 + (csrc_count * 4)
        if has_extension and len(data) >= payload_offset + 4:
            ext_length_words = struct.unpack('>H', data[payload_offset+2:payload_offset+4])[0]
            payload_offset += 4 + (ext_length_words * 4)
        
        payload = data[payload_offset:]
        if len(payload) % 4 != 0:
            continue
        
        # Each IQ sample = 4 bytes (2x int16)
        num_iq_samples = len(payload) // 4
        sample_count += num_iq_samples
    
    sock.close()
    elapsed = time.time() - start
    
    print(f"\n=== RESULTS ===")
    print(f"Duration: {elapsed:.2f} seconds")
    print(f"Packets: {packet_count}")
    print(f"Total IQ samples: {sample_count}")
    print(f"IQ samples per second: {sample_count / elapsed:.1f} Hz")
    print(f"Samples per packet: {sample_count / packet_count:.1f}")
    
    print(f"\n=== INTERPRETATION ===")
    rate = sample_count / elapsed
    if 7500 < rate < 8500:
        print("✓ Rate is ~8 kHz complex IQ (as expected for sample_rate=16000 real)")
    elif 15000 < rate < 17000:
        print("⚠ Rate is ~16 kHz - this is DOUBLE what we expected!")
        print("  This means ka9q is sending 16k complex IQ, not 8k")
    else:
        print(f"? Rate is {rate:.0f} Hz - unexpected value")

if __name__ == '__main__':
    import sys
    ssrc = int(sys.argv[1]) if len(sys.argv) > 1 else 5000000
    measure_actual_rate(ssrc, duration=5)
