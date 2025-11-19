#!/usr/bin/env python3
"""
Test resampler to verify 12 kHz → 10 Hz decimation produces correct output
"""

import numpy as np
import sys
sys.path.insert(0, 'src')

from signal_recorder.grape_rtp_recorder import Resampler

def test_resampler():
    """Test that resampler produces exactly 1 output for every 1200 inputs"""
    
    resampler = Resampler(input_rate=12000, output_rate=10)
    
    # Simulate RTP packets: typically 240 samples each at 12 kHz
    # 5 packets = 1200 samples = should produce 1 output sample
    
    total_input_samples = 0
    total_output_samples = 0
    
    # Simulate 10 seconds of reception
    # 10 sec * 12000 Hz = 120,000 input samples
    # Should produce 10 sec * 10 Hz = 100 output samples
    
    packet_size = 240
    num_packets = 120000 // packet_size  # 500 packets
    
    print(f"Testing resampler with {num_packets} packets of {packet_size} samples each")
    print(f"Expected input: {num_packets * packet_size} samples")
    print(f"Expected output: {(num_packets * packet_size) / 1200} samples")
    print()
    
    for i in range(num_packets):
        # Create test signal (doesn't matter what it is, just needs to be complex)
        samples = np.random.randn(packet_size) + 1j * np.random.randn(packet_size)
        samples = samples.astype(np.complex64)
        
        # Resample
        output = resampler.resample(samples)
        
        total_input_samples += len(samples)
        total_output_samples += len(output)
        
        if (i + 1) % 50 == 0:
            expected_outputs = total_input_samples / 1200
            print(f"After {i+1} packets:")
            print(f"  Input samples: {total_input_samples}")
            print(f"  Output samples: {total_output_samples}")
            print(f"  Expected outputs: {expected_outputs}")
            print(f"  Ratio: {total_output_samples / expected_outputs * 100:.1f}%")
            print()
    
    expected_outputs = total_input_samples / 1200
    actual_ratio = total_output_samples / expected_outputs * 100
    
    print(f"\nFinal results:")
    print(f"Total input samples: {total_input_samples}")
    print(f"Total output samples: {total_output_samples}")
    print(f"Expected output samples: {expected_outputs}")
    print(f"Actual/Expected ratio: {actual_ratio:.1f}%")
    print()
    
    if abs(actual_ratio - 100.0) < 1.0:
        print("✅ PASS: Resampler produces correct number of outputs")
        return True
    else:
        print(f"❌ FAIL: Resampler produces {actual_ratio:.1f}% of expected outputs")
        return False

if __name__ == '__main__':
    success = test_resampler()
    sys.exit(0 if success else 1)
