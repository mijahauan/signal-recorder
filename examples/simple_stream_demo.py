#!/usr/bin/env python3
"""
Simple Stream Demo - SSRC-Free API

Demonstrates the new stream API where you specify what you want
(frequency, mode, sample rate) and the system handles SSRC allocation.

Usage:
    python examples/simple_stream_demo.py
    python examples/simple_stream_demo.py --radiod bee1-hf-status.local
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder import (
    subscribe_stream,
    subscribe_iq,
    subscribe_usb,
    subscribe_batch,
    discover_streams,
    StreamManager,
)


def demo_basic_usage(radiod: str):
    """Show the simplest possible usage"""
    print("\n" + "="*60)
    print("Demo 1: Basic Stream Subscription")
    print("="*60)
    
    # Just say what you want - no SSRC needed!
    stream = subscribe_stream(
        radiod=radiod,
        frequency_hz=10.0e6,      # 10 MHz
        preset="iq",              # IQ mode
        sample_rate=16000         # 16 kHz
    )
    
    print(f"\n✓ Got stream: {stream}")
    print(f"  Frequency: {stream.frequency_mhz:.4f} MHz")
    print(f"  Preset: {stream.preset}")
    print(f"  Sample rate: {stream.sample_rate} Hz")
    print(f"  Receive on: {stream.multicast_address}:{stream.port}")
    print(f"  (Internal SSRC: {stream.ssrc} - you don't need to know this)")
    
    stream.release()
    print("  Released.")


def demo_convenience_functions(radiod: str):
    """Show preset-specific convenience functions"""
    print("\n" + "="*60)
    print("Demo 2: Convenience Functions")
    print("="*60)
    
    # IQ stream (default for recording)
    print("\nsubscribe_iq():")
    iq = subscribe_iq(radiod, frequency_hz=5.0e6, sample_rate=16000)
    print(f"  {iq}")
    
    # USB stream (for SSB/WSPR)
    print("\nsubscribe_usb():")
    usb = subscribe_usb(radiod, frequency_hz=14.0956e6, sample_rate=12000)
    print(f"  {usb}")
    
    # Release both
    iq.release()
    usb.release()
    print("\n  Both released.")


def demo_same_frequency_different_modes(radiod: str):
    """Show two streams at same frequency, different modes"""
    print("\n" + "="*60)
    print("Demo 3: Same Frequency, Different Modes")
    print("="*60)
    
    # Both at 10 MHz, but different purposes
    print("\nCreating IQ stream at 10 MHz...")
    iq_stream = subscribe_stream(
        radiod=radiod,
        frequency_hz=10.0e6,
        preset="iq",
        sample_rate=16000,
        description="GRAPE IQ recording"
    )
    print(f"  IQ: {iq_stream}")
    
    print("\nCreating AM stream at 10 MHz...")
    am_stream = subscribe_stream(
        radiod=radiod,
        frequency_hz=10.0e6,
        preset="am",
        sample_rate=12000,
        agc=True,
        description="Audio monitor"
    )
    print(f"  AM: {am_stream}")
    
    print("\n✓ Two different streams at same frequency:")
    print(f"  IQ: {iq_stream.multicast_address}:{iq_stream.port}")
    print(f"  AM: {am_stream.multicast_address}:{am_stream.port}")
    
    iq_stream.release()
    am_stream.release()
    print("\n  Both released.")


def demo_stream_sharing(radiod: str):
    """Show automatic stream sharing"""
    print("\n" + "="*60)
    print("Demo 4: Automatic Stream Sharing")
    print("="*60)
    
    print("\nFirst subscription to 10 MHz IQ @ 16kHz...")
    stream1 = subscribe_stream(
        radiod=radiod,
        frequency_hz=10.0e6,
        preset="iq",
        sample_rate=16000
    )
    print(f"  Stream 1: {stream1.multicast_address}:{stream1.port}")
    
    print("\nSecond subscription with IDENTICAL parameters...")
    stream2 = subscribe_stream(
        radiod=radiod,
        frequency_hz=10.0e6,
        preset="iq",
        sample_rate=16000
    )
    print(f"  Stream 2: {stream2.multicast_address}:{stream2.port}")
    
    # They should be the same stream!
    same = (stream1.multicast_address == stream2.multicast_address and
            stream1.port == stream2.port)
    print(f"\n✓ Same underlying stream? {same}")
    print("  (Automatic sharing - no duplicate radiod channels)")
    
    stream1.release()
    stream2.release()


def demo_batch_creation(radiod: str):
    """Show batch creation for apps like GRAPE"""
    print("\n" + "="*60)
    print("Demo 5: Batch Stream Creation (GRAPE-style)")
    print("="*60)
    
    # Create multiple streams with same parameters
    wwv_frequencies = [2.5e6, 5.0e6, 10.0e6, 15.0e6]
    
    print(f"\nCreating {len(wwv_frequencies)} IQ streams at once...")
    streams = subscribe_batch(
        radiod=radiod,
        frequencies=wwv_frequencies,
        preset="iq",
        sample_rate=16000
    )
    
    print("\n✓ Created streams:")
    for stream in streams:
        print(f"  {stream.frequency_mhz:.1f} MHz → {stream.multicast_address}:{stream.port}")
    
    # Release all
    for stream in streams:
        stream.release()
    print("\n  All released.")


def demo_discovery(radiod: str):
    """Show stream discovery"""
    print("\n" + "="*60)
    print("Demo 6: Stream Discovery")
    print("="*60)
    
    print(f"\nDiscovering streams on {radiod}...")
    streams = discover_streams(radiod)
    
    if streams:
        print(f"\n✓ Found {len(streams)} streams:")
        for s in streams:
            print(f"  {s.spec.frequency_hz/1e6:.4f} MHz, {s.spec.preset}, "
                  f"{s.spec.sample_rate} Hz → {s.multicast_address}:{s.port}")
    else:
        print("\n  No streams found (radiod may not be running)")


def demo_context_manager(radiod: str):
    """Show context manager usage"""
    print("\n" + "="*60)
    print("Demo 7: Context Manager (automatic cleanup)")
    print("="*60)
    
    print("\nUsing context manager for automatic release...")
    
    with subscribe_stream(
        radiod=radiod,
        frequency_hz=15.0e6,
        preset="iq",
        sample_rate=16000
    ) as stream:
        print(f"  Inside context: {stream}")
        # Use stream...
    
    print("  Outside context: automatically released")


def main():
    parser = argparse.ArgumentParser(
        description='Demonstrate SSRC-free Stream API'
    )
    parser.add_argument(
        '--radiod', '-r',
        default='bee1-hf-status.local',
        help='radiod address (default: bee1-hf-status.local)'
    )
    parser.add_argument(
        '--demo',
        choices=['basic', 'convenience', 'modes', 'sharing', 'batch', 'discovery', 'context', 'all'],
        default='all',
        help='Which demo to run (default: all)'
    )
    args = parser.parse_args()
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║              Stream API Demo - SSRC-Free Interface               ║
║                                                                  ║
║  Specify WHAT you want (frequency, mode, rate)                   ║
║  System handles HOW (SSRC allocation, sharing, lifecycle)        ║
╚══════════════════════════════════════════════════════════════════╝

radiod: {args.radiod}
""")
    
    demos = {
        'basic': demo_basic_usage,
        'convenience': demo_convenience_functions,
        'modes': demo_same_frequency_different_modes,
        'sharing': demo_stream_sharing,
        'batch': demo_batch_creation,
        'discovery': demo_discovery,
        'context': demo_context_manager,
    }
    
    try:
        if args.demo == 'all':
            for demo in demos.values():
                demo(args.radiod)
        else:
            demos[args.demo](args.radiod)
        
        print("\n" + "="*60)
        print("All demos complete!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure radiod is running and accessible.")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
