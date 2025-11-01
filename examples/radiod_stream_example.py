#!/usr/bin/env python3
"""
Example: Using RadiodStreamManager to request RTP streams

This demonstrates the clean API for requesting and managing radiod streams.
"""

from signal_recorder import RadiodStreamManager
import logging

# Enable logging to see what's happening
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def main():
    # Create the stream manager
    manager = RadiodStreamManager('bee1-hf-status.local')
    
    print("\n=== Example 1: Request a simple AM audio stream ===")
    # Request WWV 5 MHz audio stream
    stream = manager.request_stream(
        ssrc=5000001,
        frequency=5000000,      # 5 MHz
        preset='am',            # AM demodulation
        sample_rate=12000,      # 12 kHz audio
        agc=1,                  # AGC on
        gain=50                 # 50 dB gain
    )
    
    print(f"\nStream created!")
    print(f"  SSRC: {stream.ssrc}")
    print(f"  Frequency: {stream.frequency/1e6:.3f} MHz")
    print(f"  Preset: {stream.preset}")
    print(f"  Sample Rate: {stream.sample_rate} Hz")
    print(f"  Multicast: {stream.multicast_address}:{stream.multicast_port}")
    print(f"  SNR: {stream.snr:.1f} dB")
    
    print("\n=== Example 2: Request an IQ stream for recording ===")
    # Request WWV 10 MHz IQ stream
    iq_stream = manager.request_stream(
        ssrc=10000000,
        frequency=10000000,     # 10 MHz
        preset='iq',            # IQ (raw samples)
        sample_rate=16000,      # 16 kHz bandwidth
        agc=0,                  # AGC off for IQ
        gain=0                  # No gain
    )
    
    print(f"\nIQ Stream created!")
    print(f"  {iq_stream}")
    
    print("\n=== Example 3: List all active streams ===")
    streams = manager.list_streams()
    print(f"\nManaged streams: {len(streams)}")
    for ssrc, info in streams.items():
        print(f"  - {info}")
    
    print("\n=== Example 4: Discover all streams (including existing ones) ===")
    all_streams = manager.discover_all_streams()
    print(f"\nAll streams in radiod: {len(all_streams)}")
    for ssrc, info in all_streams.items():
        managed = "✓" if ssrc in streams else " "
        print(f"  [{managed}] SSRC {ssrc:>8}: {info.frequency/1e6:>7.3f} MHz, "
              f"{info.preset:>4}, {info.multicast_address}:{info.multicast_port}")
    
    print("\n=== Example 5: Get specific stream info ===")
    info = manager.get_stream(5000001)
    if info:
        print(f"\nStream 5000001: {info}")
    
    print("\n=== Example 6: Stop a stream ===")
    if manager.stop_stream(5000001):
        print("Stream 5000001 stopped")
    
    # Clean up
    manager.close()
    print("\nDone!")

if __name__ == '__main__':
    main()
