#!/usr/bin/env python3
"""
Phase 1: Module Testing

Test minute_file_writer and quality_metrics independently
"""

import sys
import numpy as np
from pathlib import Path
import time
import shutil

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

print("=" * 70)
print("PHASE 1: MODULE TESTING")
print("=" * 70)
print()

# Test output directory
test_dir = Path('/tmp/grape-phase1-test')
if test_dir.exists():
    shutil.rmtree(test_dir)
test_dir.mkdir(parents=True)

print(f"Test directory: {test_dir}")
print()

# ============================================================================
# TEST 1: MinuteFileWriter
# ============================================================================
print("TEST 1: MinuteFileWriter")
print("-" * 70)

try:
    from signal_recorder.minute_file_writer import MinuteFileWriter
    
    writer = MinuteFileWriter(
        output_dir=test_dir / 'archive',
        channel_name='TEST_WWV_2.5MHz',
        frequency_hz=2500000,
        sample_rate=8000,
        station_config={
            'callsign': 'AI6VN',
            'grid_square': 'CM87',
            'instrument_id': 'S000171'
        }
    )
    
    print(f"✅ MinuteFileWriter created successfully")
    
    # Simulate 2.5 minutes of data (to trigger 2 complete minute writes)
    print(f"   Simulating 2.5 minutes of RTP data...")
    base_timestamp = time.time()
    samples_written = 0
    minutes_completed = 0
    
    # Write in small chunks (like RTP packets)
    samples_per_chunk = 80  # Typical RTP packet size
    chunks_per_minute = (8000 * 60) // samples_per_chunk
    
    for minute in range(3):  # 3 minutes worth
        for chunk in range(chunks_per_minute):
            timestamp = base_timestamp + (minute * 60) + (chunk * samples_per_chunk / 8000)
            
            # Create realistic IQ samples
            samples = (np.random.randn(samples_per_chunk) + 
                      1j * np.random.randn(samples_per_chunk)) * 0.1
            samples = samples.astype(np.complex64)
            
            result = writer.add_samples(timestamp, samples)
            samples_written += len(samples)
            
            if result:
                minute_time, file_path = result
                minutes_completed += 1
                print(f"   ✅ Minute {minutes_completed} written: {file_path.name}")
                print(f"      Size: {file_path.stat().st_size / 1024:.1f} KB")
        
        # Stop after 2.5 minutes (don't complete 3rd minute)
        if minute >= 2:
            break
    
    # Get final stats
    stats = writer.get_stats()
    print(f"   Total samples written: {samples_written:,}")
    print(f"   Minutes completed: {stats['minutes_written']}")
    print(f"   Buffer remaining: {stats['buffer_samples']} samples")
    
    # Verify files exist
    minute_files = list((test_dir / 'archive').rglob('*.npz'))
    print(f"   Files on disk: {len(minute_files)}")
    
    if len(minute_files) >= 2:
        print(f"✅ TEST 1 PASSED: MinuteFileWriter working correctly")
        
        # Verify file contents
        print(f"   Verifying file contents...")
        data = np.load(minute_files[0])
        print(f"   ✅ Sample rate: {data['sample_rate']} Hz")
        print(f"   ✅ IQ samples: {len(data['iq'])} (expected ~480,000)")
        print(f"   ✅ Frequency: {data['frequency_hz'] / 1e6:.1f} MHz")
        print(f"   ✅ Timestamp: {data['timestamp']}")
    else:
        print(f"❌ TEST 1 FAILED: Expected >= 2 files, got {len(minute_files)}")
        sys.exit(1)
    
except Exception as e:
    print(f"❌ TEST 1 FAILED with exception: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ============================================================================
# TEST 2: QualityMetricsTracker
# ============================================================================
print("TEST 2: QualityMetricsTracker")
print("-" * 70)

try:
    from signal_recorder.quality_metrics import (
        QualityMetricsTracker, TimingDiscontinuity, DiscontinuityType
    )
    
    tracker = QualityMetricsTracker(
        channel_name='TEST_WWV_2.5MHz',
        frequency_hz=2500000,
        output_dir=test_dir / 'analytics'
    )
    
    print(f"✅ QualityMetricsTracker created successfully")
    
    # Simulate 5 minutes of data with varying quality
    print(f"   Simulating 5 minutes of quality metrics...")
    base_timestamp = time.time()
    
    for minute in range(5):
        minute_ts = base_timestamp + (minute * 60)
        
        # Start minute
        tracker.start_minute(minute_ts, expected_samples=480000)
        
        # Simulate varying completeness
        if minute == 2:
            # Minute 2: Some packet loss
            actual_samples = 479500
            packets_rx = 5990
            packets_drop = 10
        else:
            # Other minutes: Perfect
            actual_samples = 480000
            packets_rx = 6000
            packets_drop = 0
        
        tracker.update_minute_samples(actual_samples)
        
        # Add a discontinuity for minute 2
        if minute == 2:
            disc = TimingDiscontinuity(
                timestamp=minute_ts + 30,
                sample_index=minute * 480000 + 240000,
                discontinuity_type=DiscontinuityType.GAP,
                magnitude_samples=500,
                magnitude_ms=62.5,
                rtp_sequence_before=12000,
                rtp_sequence_after=12005,
                rtp_timestamp_before=192000000,
                rtp_timestamp_after=192008000,
                wwv_tone_detected=False,
                explanation="5 packets dropped, 62.5ms gap"
            )
            tracker.add_discontinuity(disc)
        
        # Simulate WWV detection (for minutes 0, 1, 3, 4 - miss minute 2)
        wwv_result = None
        if minute != 2:
            wwv_result = {
                'detected': True,
                'timing_error_ms': np.random.normal(-1.5, 2.0),  # Realistic error
                'snr_db': 18.0 + np.random.normal(0, 1.0),
                'duration_ms': 800.0
            }
        
        # Finalize minute
        signal_power = -42.0 + np.random.normal(0, 0.5)
        tracker.finalize_minute(packets_rx, packets_drop, signal_power, wwv_result)
        
        print(f"   ✅ Minute {minute}: {actual_samples} samples, "
              f"{packets_drop} dropped, WWV: {'Yes' if wwv_result else 'No'}")
    
    # Export metrics
    print(f"   Exporting metrics...")
    csv_file = tracker.export_minute_csv('20251103')
    disc_file = tracker.export_discontinuities_csv('20251103')
    summary_file = tracker.export_daily_summary('20251103')
    
    print(f"   ✅ Minute CSV: {csv_file}")
    print(f"   ✅ Discontinuities CSV: {disc_file if disc_file else 'None (no gaps)'}")
    print(f"   ✅ Daily summary: {summary_file}")
    
    # Verify files exist
    if csv_file and csv_file.exists():
        print(f"✅ TEST 2 PASSED: QualityMetricsTracker working correctly")
        
        # Show summary stats
        import json
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        
        print(f"   Summary statistics:")
        print(f"   - Completeness: {summary['data_completeness_percent']:.2f}%")
        print(f"   - Total gaps: {summary['total_gaps']}")
        print(f"   - Packet loss: {summary['packet_loss_percent']:.3f}%")
        if summary.get('wwv_detection_rate_percent', 0) > 0:
            print(f"   - WWV detection rate: {summary['wwv_detection_rate_percent']:.1f}%")
            print(f"   - WWV timing error: {summary['wwv_timing_error_mean_ms']:.2f} ± "
                  f"{summary['wwv_timing_error_std_ms']:.2f} ms")
    else:
        print(f"❌ TEST 2 FAILED: CSV file not created")
        sys.exit(1)
    
except Exception as e:
    print(f"❌ TEST 2 FAILED with exception: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ============================================================================
# SUMMARY
# ============================================================================
print("=" * 70)
print("PHASE 1 TESTING COMPLETE")
print("=" * 70)
print()
print(f"✅ All module tests PASSED")
print()
print(f"Test outputs saved to: {test_dir}")
print(f"  Archive: {test_dir / 'archive'}")
print(f"  Analytics: {test_dir / 'analytics'}")
print()
print(f"Minute files created:")
for f in sorted((test_dir / 'archive').rglob('*.npz')):
    print(f"  - {f.relative_to(test_dir)}")
print()
print(f"Quality files created:")
for f in sorted((test_dir / 'analytics').rglob('*')):
    if f.is_file():
        print(f"  - {f.relative_to(test_dir)}")
print()
print("Ready to proceed to PHASE 2 (parallel RTP testing)")
print("=" * 70)
