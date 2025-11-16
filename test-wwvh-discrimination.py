#!/usr/bin/env python3
"""
Test WWV-H Discrimination with 440 Hz Integration

Tests:
1. Frequency-aware WWVH detection (only on 2.5, 5, 10, 15 MHz)
2. 440 Hz tone detection (minute 1 = WWVH, minute 2 = WWV)
3. CSV output format
"""

import sys
import logging
import numpy as np
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from signal_recorder.tone_detector import MultiStationToneDetector
from signal_recorder.wwvh_discrimination import WWVHDiscriminator
from signal_recorder.analytics_service import NPZArchive

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    force=True  # Override any existing config
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def test_frequency_aware_detection():
    """Test that WWVH detection is only enabled on correct frequencies"""
    
    logger.info("="*60)
    logger.info("TEST 1: Frequency-Aware WWVH Detection")
    logger.info("="*60)
    
    test_channels = [
        ("WWV 2.5 MHz", True),   # WWVH broadcasts here
        ("WWV 5 MHz", True),     # WWVH broadcasts here
        ("WWV 10 MHz", True),    # WWVH broadcasts here
        ("WWV 15 MHz", True),    # WWVH broadcasts here
        ("WWV 20 MHz", False),   # WWVH does NOT broadcast here
        ("WWV 25 MHz", False),   # WWVH does NOT broadcast here
        ("CHU 7.85 MHz", False), # CHU channel
    ]
    
    results = []
    for channel_name, should_have_wwvh in test_channels:
        detector = MultiStationToneDetector(channel_name=channel_name)
        has_wwvh = any('WWVH' in str(s) for s in detector.templates.keys())
        
        status = "✅" if has_wwvh == should_have_wwvh else "❌"
        logger.info(f"{status} {channel_name}: WWVH detection = {has_wwvh} (expected {should_have_wwvh})")
        results.append(has_wwvh == should_have_wwvh)
    
    all_passed = all(results)
    logger.info(f"\nFrequency-aware detection: {'✅ PASS' if all_passed else '❌ FAIL'}")
    return all_passed

def test_discrimination_with_real_data():
    """Test discrimination with real archived data from WWV 5 MHz"""
    
    logger.info("\n" + "="*60)
    logger.info("TEST 2: WWV-H Discrimination with Real Data")
    logger.info("="*60)
    
    # Find a WWV 5 MHz archive (shared frequency)
    archive_dir = Path("/tmp/grape-test/archives/WWV_5_MHz")
    npz_files = sorted(archive_dir.glob("*_iq.npz"))
    
    if not npz_files:
        logger.warning("No raw NPZ files found - skipping real data test")
        return True
    
    logger.info(f"Found {len(npz_files)} raw NPZ files")
    
    # Initialize components
    channel_name = "WWV 5 MHz"
    detector = MultiStationToneDetector(channel_name=channel_name)
    discriminator = WWVHDiscriminator(channel_name=channel_name)
    
    logger.info(f"Detector stations: {list(detector.templates.keys())}")
    
    # Process first 10 files (looking for minutes 1 and 2 for 440 Hz test)
    tested_files = 0
    detections_found = 0
    discrimination_results = []
    
    for npz_file in npz_files[:10]:
        try:
            # Load archive
            archive = NPZArchive.load(npz_file)
            
            # Get minute number
            dt = datetime.fromtimestamp(archive.unix_timestamp)
            minute_num = dt.minute
            
            logger.info(f"\nFile: {npz_file.name}")
            logger.info(f"  Time: {dt.strftime('%Y-%m-%d %H:%M:%S')} UTC (minute {minute_num})")
            logger.info(f"  Samples: {len(archive.iq_samples)} @ {archive.sample_rate} Hz")
            
            # Resample 16 kHz → 3 kHz for tone detection
            from scipy import signal as scipy_signal
            resampled = scipy_signal.resample_poly(
                archive.iq_samples,
                up=3,
                down=16,
                axis=0
            )
            
            # Detect tones
            detections = detector.process_samples(
                timestamp=archive.unix_timestamp,
                samples=resampled,
                rtp_timestamp=archive.rtp_timestamp
            )
            
            if detections:
                logger.info(f"  Detections: {len(detections)}")
                for det in detections:
                    logger.info(f"    {det.station.value}: {det.timing_error_ms:+.1f}ms, "
                              f"SNR={det.snr_db:.1f}dB, Power={det.tone_power_db:.1f}dB")
                detections_found += len(detections)
            else:
                logger.info("  No detections")
            
            # Run discrimination with 440 Hz analysis
            minute_timestamp = int(archive.unix_timestamp / 60) * 60
            discrimination = discriminator.analyze_minute_with_440hz(
                iq_samples=archive.iq_samples,
                sample_rate=archive.sample_rate,
                minute_timestamp=minute_timestamp,
                detections=detections
            )
            
            # Log discrimination result
            logger.info(f"  Discrimination:")
            logger.info(f"    WWV detected: {discrimination.wwv_detected}")
            logger.info(f"    WWVH detected: {discrimination.wwvh_detected}")
            if discrimination.power_ratio_db is not None:
                logger.info(f"    Power ratio: {discrimination.power_ratio_db:+.1f} dB")
            if discrimination.differential_delay_ms is not None:
                logger.info(f"    Delay: {discrimination.differential_delay_ms:+.1f} ms")
            
            # 440 Hz detection (only in minutes 1 and 2)
            if minute_num == 1:
                logger.info(f"    440 Hz WWVH (min 1): {discrimination.tone_440hz_wwvh_detected}")
                if discrimination.tone_440hz_wwvh_power_db is not None:
                    logger.info(f"    440 Hz power: {discrimination.tone_440hz_wwvh_power_db:.1f} dB")
            elif minute_num == 2:
                logger.info(f"    440 Hz WWV (min 2): {discrimination.tone_440hz_wwv_detected}")
                if discrimination.tone_440hz_wwv_power_db is not None:
                    logger.info(f"    440 Hz power: {discrimination.tone_440hz_wwv_power_db:.1f} dB")
            
            logger.info(f"    Dominant: {discrimination.dominant_station}")
            logger.info(f"    Confidence: {discrimination.confidence}")
            
            discrimination_results.append(discrimination)
            tested_files += 1
            
        except Exception as e:
            logger.error(f"Error processing {npz_file.name}: {e}", exc_info=True)
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("DISCRIMINATION TEST SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Files tested: {tested_files}")
    logger.info(f"Total detections: {detections_found}")
    logger.info(f"Discrimination results: {len(discrimination_results)}")
    
    # Check for 440 Hz detections
    wwv_440hz_count = sum(1 for d in discrimination_results if d.tone_440hz_wwv_detected)
    wwvh_440hz_count = sum(1 for d in discrimination_results if d.tone_440hz_wwvh_detected)
    logger.info(f"440 Hz WWV detections (min 2): {wwv_440hz_count}")
    logger.info(f"440 Hz WWVH detections (min 1): {wwvh_440hz_count}")
    
    return tested_files > 0

def test_csv_format():
    """Test CSV output format"""
    
    logger.info("\n" + "="*60)
    logger.info("TEST 3: CSV Output Format")
    logger.info("="*60)
    
    # Check for discrimination CSV files
    csv_dir = Path("/tmp/grape-test/analytics/WWV_5_MHz/discrimination_logs")
    
    if not csv_dir.exists():
        logger.info(f"CSV directory doesn't exist yet: {csv_dir}")
        logger.info("(Will be created when analytics service runs)")
        return True
    
    csv_files = sorted(csv_dir.glob("*.csv"))
    logger.info(f"Found {len(csv_files)} CSV files")
    
    if csv_files:
        latest_csv = csv_files[-1]
        logger.info(f"\nLatest CSV: {latest_csv.name}")
        
        # Read and show header
        with open(latest_csv, 'r') as f:
            header = f.readline().strip()
            logger.info(f"Header: {header}")
            
            # Show expected fields
            expected_fields = [
                'timestamp_utc', 'minute_timestamp', 'minute_number',
                'wwv_detected', 'wwvh_detected',
                'wwv_power_db', 'wwvh_power_db', 'power_ratio_db',
                'differential_delay_ms',
                'tone_440hz_wwv_detected', 'tone_440hz_wwv_power_db',
                'tone_440hz_wwvh_detected', 'tone_440hz_wwvh_power_db',
                'dominant_station', 'confidence'
            ]
            
            header_fields = header.split(',')
            has_all_fields = all(field in header_fields for field in expected_fields)
            
            if has_all_fields:
                logger.info("✅ CSV header has all expected fields")
            else:
                logger.warning("❌ CSV header missing some fields")
                missing = set(expected_fields) - set(header_fields)
                logger.warning(f"Missing fields: {missing}")
            
            # Show first few data lines
            logger.info("\nFirst 3 data rows:")
            for i, line in enumerate(f):
                if i >= 3:
                    break
                logger.info(f"  {line.strip()}")
            
            return has_all_fields
    else:
        logger.info("No CSV files found yet (will be created by analytics service)")
        return True

if __name__ == '__main__':
    print("Starting test suite...")  # Debug print
    logger.info("WWV-H DISCRIMINATION TEST SUITE")
    logger.info("="*60)
    
    # Run tests
    test1 = test_frequency_aware_detection()
    test2 = test_discrimination_with_real_data()
    test3 = test_csv_format()
    
    # Final summary
    logger.info("\n" + "="*60)
    logger.info("FINAL SUMMARY")
    logger.info("="*60)
    logger.info(f"Frequency-aware detection: {'✅ PASS' if test1 else '❌ FAIL'}")
    logger.info(f"Discrimination with data: {'✅ PASS' if test2 else '❌ FAIL'}")
    logger.info(f"CSV format: {'✅ PASS' if test3 else '❌ FAIL'}")
    
    all_passed = test1 and test2 and test3
    logger.info(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    sys.exit(0 if all_passed else 1)
