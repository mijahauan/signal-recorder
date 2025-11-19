#!/usr/bin/env python3
"""
Unit tests for GRAPE recorder components

Tests individual components without requiring live RTP streams.
"""

import sys
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
import struct

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from signal_recorder.grape_recorder import (
    RTPHeader, RTPPacket, Resampler, DailyBuffer
)
from signal_recorder.grape_metadata import (
    GRAPEMetadataGenerator, GapRecord, QualityMetrics
)

def test_rtp_header_parsing():
    """Test RTP header parsing"""
    print("Testing RTP header parsing...")
    
    # Create a sample RTP packet header
    # Version=2, Padding=0, Extension=0, CC=0, Marker=0, PT=123, Seq=1000, TS=48000, SSRC=0x12345678
    # First word: V(2) P(1) X(1) CC(4) M(1) PT(7) Seq(16)
    word0 = (2 << 30) | (0 << 29) | (0 << 28) | (0 << 24) | (0 << 23) | (123 << 16) | 1000
    header_bytes = struct.pack('!III', 
        word0,  # V=2, P=0, X=0, CC=0, M=0, PT=123, Seq=1000
        48000,  # Timestamp
        0x12345678  # SSRC
    )
    
    try:
        header, header_len = RTPHeader.parse(header_bytes)
        
        assert header.version == 2, f"Expected version 2, got {header.version}"
        assert header.payload_type == 123, f"Expected PT 123, got {header.payload_type}"
        assert header.sequence == 1000, f"Expected seq 1000, got {header.sequence}"
        assert header.timestamp == 48000, f"Expected TS 48000, got {header.timestamp}"
        assert header.ssrc == 0x12345678, f"Expected SSRC 0x12345678, got 0x{header.ssrc:08x}"
        assert header_len == 12, f"Expected header length 12, got {header_len}"
        
        print("  ✓ RTP header parsing works correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ RTP header parsing failed: {e}")
        return False


def test_iq_sample_extraction():
    """Test IQ sample extraction from RTP payload"""
    print("Testing IQ sample extraction...")
    
    try:
        # Create fake IQ data (interleaved float32: I, Q, I, Q, ...)
        num_samples = 120
        i_data = np.random.randn(num_samples).astype(np.float32)
        q_data = np.random.randn(num_samples).astype(np.float32)
        
        interleaved = np.empty(num_samples * 2, dtype=np.float32)
        interleaved[0::2] = i_data
        interleaved[1::2] = q_data
        
        payload = interleaved.tobytes()
        
        # Create fake RTP packet
        header = RTPHeader(
            version=2, padding=False, extension=False, csrc_count=0,
            marker=False, payload_type=123, sequence=1, timestamp=0, ssrc=0x12345678
        )
        
        packet = RTPPacket(header=header, payload=payload, arrival_time=0.0)
        
        # Extract IQ samples
        iq_samples = packet.get_iq_samples()
        
        assert len(iq_samples) == num_samples, f"Expected {num_samples} samples, got {len(iq_samples)}"
        
        # Verify I and Q components
        extracted_i = np.real(iq_samples)
        extracted_q = np.imag(iq_samples)
        
        assert np.allclose(extracted_i, i_data), "I component mismatch"
        assert np.allclose(extracted_q, q_data), "Q component mismatch"
        
        print("  ✓ IQ sample extraction works correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ IQ sample extraction failed: {e}")
        return False


def test_resampler():
    """Test resampler (12 kHz → 10 Hz)"""
    print("Testing resampler...")
    
    try:
        resampler = Resampler(input_rate=12000, output_rate=10)
        
        # Generate 1 second of test signal (12000 samples)
        t = np.linspace(0, 1, 12000, endpoint=False)
        # 1 Hz sine wave
        signal = np.exp(2j * np.pi * 1.0 * t).astype(np.complex64)
        
        # Resample
        resampled = resampler.resample(signal)
        
        # Should get 10 samples out (1 second at 10 Hz)
        expected_samples = 10
        assert len(resampled) == expected_samples, \
            f"Expected {expected_samples} samples, got {len(resampled)}"
        
        print(f"  ✓ Resampler works correctly (12000 → {len(resampled)} samples)")
        return True
        
    except Exception as e:
        print(f"  ✗ Resampler failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_daily_buffer():
    """Test daily buffer with UTC alignment"""
    print("Testing daily buffer...")
    
    try:
        buffer = DailyBuffer(output_rate=10)
        
        # Create test samples for midnight UTC
        test_date = datetime(2024, 10, 24, 0, 0, 0, tzinfo=timezone.utc)
        
        # Add samples at different times
        for hour in range(24):
            timestamp = test_date + timedelta(hours=hour)
            samples = np.random.randn(10) + 1j * np.random.randn(10)  # 1 second of data
            
            result, date = buffer.add_samples(samples, timestamp)
            
            # Should not trigger rollover until we cross midnight
            if hour < 23:
                assert result is None, f"Unexpected rollover at hour {hour}"
        
        # Add samples for next day (should trigger rollover)
        next_day = test_date + timedelta(days=1)
        samples = np.random.randn(10) + 1j * np.random.randn(10)
        result, date = buffer.add_samples(samples, next_day)
        
        assert result is not None, "Expected rollover on day boundary"
        assert date == test_date, f"Expected date {test_date}, got {date}"
        assert len(result) == 864000, f"Expected 864000 samples, got {len(result)}"
        
        print("  ✓ Daily buffer works correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Daily buffer failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_metadata_generator():
    """Test metadata generation"""
    print("Testing metadata generator...")
    
    try:
        generator = GRAPEMetadataGenerator(
            channel_name="WWV_2_5",
            frequency_hz=2.5e6,
            ssrc=0x12345678
        )
        
        # Simulate packet reception
        base_time = datetime(2024, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
        
        for i in range(100):
            timestamp = base_time + timedelta(seconds=i * 0.01)
            generator.record_packet(
                timestamp=timestamp,
                sequence=i,
                sample_count=120,
                is_dropped=False,
                is_duplicate=False
            )
        
        # Simulate a gap
        for i in range(100, 110):
            timestamp = base_time + timedelta(seconds=i * 0.01)
            generator.record_packet(
                timestamp=timestamp,
                sequence=i,
                sample_count=0,
                is_dropped=True,
                is_duplicate=False
            )
        
        # Continue normal packets
        for i in range(110, 200):
            timestamp = base_time + timedelta(seconds=i * 0.01)
            generator.record_packet(
                timestamp=timestamp,
                sequence=i,
                sample_count=120,
                is_dropped=False,
                is_duplicate=False
            )
        
        # Generate metrics
        metrics = generator.generate_quality_metrics(
            recording_date=datetime(2024, 10, 24, 0, 0, 0, tzinfo=timezone.utc)
        )
        
        assert metrics.total_packets_received == 190, \
            f"Expected 190 packets, got {metrics.total_packets_received}"
        assert metrics.total_packets_dropped == 10, \
            f"Expected 10 dropped packets, got {metrics.total_packets_dropped}"
        assert len(generator.gaps) == 1, \
            f"Expected 1 gap, got {len(generator.gaps)}"
        
        print(f"  ✓ Metadata generator works correctly")
        print(f"    - Packets received: {metrics.total_packets_received}")
        print(f"    - Packets dropped: {metrics.total_packets_dropped}")
        print(f"    - Gaps recorded: {len(generator.gaps)}")
        print(f"    - Data completeness: {metrics.data_completeness_percent:.2f}%")
        return True
        
    except Exception as e:
        print(f"  ✗ Metadata generator failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("=" * 70)
    print("GRAPE Recorder Component Tests")
    print("=" * 70)
    print()
    
    tests = [
        ("RTP Header Parsing", test_rtp_header_parsing),
        ("IQ Sample Extraction", test_iq_sample_extraction),
        ("Resampler", test_resampler),
        ("Daily Buffer", test_daily_buffer),
        ("Metadata Generator", test_metadata_generator),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        print("-" * 70)
        result = test_func()
        results.append((test_name, result))
        print()
    
    # Summary
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())

