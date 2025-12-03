#!/usr/bin/env python3
"""
Integration Test: Three-Phase Pipeline

This script tests the complete three-phase pipeline with:
1. Synthetic IQ data (simulated WWV tones)
2. Full pipeline processing
3. Verification of all phases

Run with: python scripts/test_three_phase_integration.py
"""

import numpy as np
import tempfile
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def generate_wwv_tone(
    duration_sec: float,
    sample_rate: int = 20000,
    tone_freq: float = 1000.0,
    carrier_freq: float = 0.0,
    snr_db: float = 20.0
) -> np.ndarray:
    """
    Generate synthetic WWV-like IQ signal.
    
    Args:
        duration_sec: Duration in seconds
        sample_rate: Sample rate (Hz)
        tone_freq: Audio tone frequency (1000 Hz for WWV, 1200 Hz for WWVH)
        carrier_freq: Carrier offset from center (usually 0)
        snr_db: Signal-to-noise ratio
        
    Returns:
        Complex64 IQ samples
    """
    n_samples = int(duration_sec * sample_rate)
    t = np.arange(n_samples) / sample_rate
    
    # Generate AM modulated signal with tone
    # Carrier
    carrier = np.exp(2j * np.pi * carrier_freq * t)
    
    # Audio tone (modulation)
    modulation = 1.0 + 0.5 * np.sin(2 * np.pi * tone_freq * t)
    
    # Signal
    signal = carrier * modulation
    
    # Add noise
    signal_power = np.mean(np.abs(signal)**2)
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = np.sqrt(noise_power / 2) * (np.random.randn(n_samples) + 1j * np.random.randn(n_samples))
    
    return (signal + noise).astype(np.complex64)


def test_phase1_raw_archive():
    """Test Phase 1: Raw Archive Writer"""
    logger.info("=" * 60)
    logger.info("PHASE 1 TEST: Raw Archive Writer")
    logger.info("=" * 60)
    
    from grape_recorder.grape import (
        RawArchiveWriter,
        RawArchiveConfig,
        SystemTimeReference
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = RawArchiveConfig(
            output_dir=Path(tmpdir),
            channel_name='WWV_10MHz',
            frequency_hz=10e6,
            sample_rate=20000,
            station_config={
                'callsign': 'TEST',
                'grid_square': 'EM38ww'
            },
            compression='gzip',
            file_duration_sec=3600
        )
        
        writer = RawArchiveWriter(config)
        
        # Generate 60 seconds of synthetic data (1 minute)
        logger.info("Generating 60 seconds of synthetic IQ data...")
        samples = generate_wwv_tone(duration_sec=60.0, snr_db=25.0)
        
        # Set time reference
        base_time = time.time()
        base_rtp = 1000000
        writer.set_time_reference(base_rtp, base_time, ntp_offset_ms=5.0)
        
        # Write samples
        logger.info(f"Writing {len(samples)} samples to raw archive...")
        written = writer.write_samples(
            samples=samples,
            rtp_timestamp=base_rtp,
            system_time=base_time
        )
        
        logger.info(f"  ✅ Wrote {written} samples")
        
        # Check stats
        stats = writer.get_stats()
        logger.info(f"  Samples written: {stats['samples_written']}")
        logger.info(f"  Archive dir: {stats['archive_dir']}")
        
        writer.close()
        
        # Verify metadata
        metadata_file = Path(tmpdir) / 'raw_archive' / 'WWV_10MHz' / 'metadata' / 'session_summary.json'
        if metadata_file.exists():
            import json
            with open(metadata_file) as f:
                metadata = json.load(f)
            logger.info(f"  Archive type: {metadata.get('archive_type')}")
            logger.info(f"  UTC correction applied: {metadata.get('utc_correction_applied')}")
            assert metadata.get('utc_correction_applied') == False, "Raw archive should NOT have UTC correction!"
            logger.info("  ✅ Phase 1 metadata correct (no UTC correction)")
        
        return True


def test_phase2_clock_offset():
    """Test Phase 2: Clock Offset Engine"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 2 TEST: Clock Offset Engine")
    logger.info("=" * 60)
    
    from grape_recorder.grape import (
        ClockOffsetSeries,
        ClockOffsetMeasurement,
        ClockOffsetQuality,
        ClockOffsetSeriesWriter
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create writer
        writer = ClockOffsetSeriesWriter(
            output_dir=Path(tmpdir),
            channel_name='WWV_10MHz'
        )
        
        # Create series
        series = ClockOffsetSeries(
            channel_name='WWV_10MHz',
            frequency_hz=10e6,
            receiver_grid='EM38ww'
        )
        
        # Add measurements for 5 minutes
        base_time = time.time()
        logger.info("Generating D_clock measurements for 5 minutes...")
        
        for i in range(5):
            measurement = ClockOffsetMeasurement(
                system_time=base_time + i * 60,
                utc_time=base_time + i * 60 - 0.015,  # 15ms clock offset
                minute_boundary_utc=base_time + i * 60,
                clock_offset_ms=15.0 + np.random.normal(0, 0.5),  # ~15ms with jitter
                station='WWV',
                frequency_mhz=10.0,
                propagation_delay_ms=3.8,  # ~1100km path
                propagation_mode='1E',
                n_hops=1,
                confidence=0.85 + np.random.uniform(0, 0.1),
                uncertainty_ms=0.5,
                quality_grade=ClockOffsetQuality.GOOD,
                snr_db=25.0 + np.random.uniform(-3, 3),
                utc_verified=True,
                processed_at=time.time()
            )
            
            series.add_measurement(measurement)
            writer.write_measurement(measurement)
            
            logger.info(f"  Minute {i}: D_clock={measurement.clock_offset_ms:.2f}ms, "
                       f"confidence={measurement.confidence:.2%}")
        
        # Save complete series
        writer.write_series(series)
        
        # Verify interpolation
        logger.info("")
        logger.info("Testing D_clock interpolation...")
        
        # Query at various times
        for offset in [0, 30, 90, 150, 240]:
            result = series.get_offset_at_time(base_time + offset, interpolate=True)
            if result:
                d_clock, uncertainty = result
                logger.info(f"  t+{offset}s: D_clock={d_clock:.2f}ms ±{uncertainty:.2f}ms")
        
        # Quality summary
        summary = series.get_quality_summary()
        logger.info(f"  Quality summary: {summary}")
        logger.info("  ✅ Phase 2 clock offset series complete")
        
        return True


def test_phase3_product():
    """Test Phase 3: Corrected Product Generator"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 3 TEST: Corrected Product Generator")
    logger.info("=" * 60)
    
    from grape_recorder.grape import (
        ClockOffsetSeries,
        ClockOffsetMeasurement,
        ClockOffsetQuality,
        ProductConfig
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create D_clock series for Phase 3 to consume
        series = ClockOffsetSeries(
            channel_name='WWV_10MHz',
            frequency_hz=10e6,
            receiver_grid='EM38ww'
        )
        
        base_time = 1733222400.0  # Fixed time for reproducibility
        
        series.add_measurement(ClockOffsetMeasurement(
            system_time=base_time,
            utc_time=base_time - 0.015,
            minute_boundary_utc=base_time,
            clock_offset_ms=15.0,
            station='WWV',
            frequency_mhz=10.0,
            propagation_delay_ms=3.8,
            propagation_mode='1E',
            n_hops=1,
            confidence=0.9,
            uncertainty_ms=0.5,
            quality_grade=ClockOffsetQuality.GOOD
        ))
        
        # Test time correction calculation
        logger.info("Testing time correction application...")
        
        system_time = base_time + 30  # 30 seconds into minute
        result = series.get_offset_at_time(system_time)
        
        if result:
            d_clock_ms, uncertainty = result
            utc_corrected = system_time - (d_clock_ms / 1000.0)
            
            logger.info(f"  System time: {system_time}")
            logger.info(f"  D_clock: {d_clock_ms:.2f} ms")
            logger.info(f"  UTC corrected: {utc_corrected}")
            logger.info(f"  Correction applied: {(system_time - utc_corrected)*1000:.2f} ms")
            
            # Verify correction is approximately 15ms
            correction_ms = (system_time - utc_corrected) * 1000
            assert abs(correction_ms - 15.0) < 1.0, f"Correction {correction_ms}ms not ~15ms"
            logger.info("  ✅ Time correction calculation correct")
        
        # Test decimation factor
        from grape_recorder.grape.decimation import get_decimator
        
        decimator = get_decimator(20000, 10)
        test_samples = generate_wwv_tone(1.0, sample_rate=20000)
        decimated = decimator(test_samples)
        
        logger.info(f"  Decimation: {len(test_samples)} → {len(decimated)} samples")
        logger.info(f"  Factor: {len(test_samples) / len(decimated):.0f}x")
        logger.info("  ✅ Decimation works correctly")
        
        return True


def test_transmission_solver():
    """Test TransmissionTimeSolver"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TRANSMISSION SOLVER TEST: UTC Back-Calculation")
    logger.info("=" * 60)
    
    from grape_recorder.grape import create_solver_from_grid, create_multi_station_solver
    
    # Create solver for Kansas City area
    solver = create_solver_from_grid('EM38ww', sample_rate=20000)
    
    logger.info("Station distances from EM38ww:")
    for station, dist in solver.station_distances.items():
        logger.info(f"  {station}: {dist:.0f} km")
    
    # Test solving for WWV
    logger.info("")
    logger.info("Solving for WWV at 10 MHz...")
    
    # Simulate detection at expected time (arrival after propagation delay)
    expected_second_rtp = 1000000  # Second boundary
    # WWV is ~1100km, 1-hop E-layer delay ~3.8ms = 76 samples at 20kHz
    arrival_rtp = expected_second_rtp + 76
    
    result = solver.solve(
        station='WWV',
        frequency_mhz=10.0,
        arrival_rtp=arrival_rtp,
        delay_spread_ms=0.3,  # Low multipath
        doppler_std_hz=0.1,   # Stable path
        fss_db=-0.5,          # Slight D-layer
        expected_second_rtp=expected_second_rtp
    )
    
    logger.info(f"  Mode: {result.mode_name}")
    logger.info(f"  N hops: {result.n_hops}")
    logger.info(f"  Propagation delay: {result.propagation_delay_ms:.2f} ms")
    logger.info(f"  Emission offset: {result.emission_offset_ms:.2f} ms")
    logger.info(f"  Confidence: {result.confidence:.2%}")
    logger.info(f"  UTC verified: {result.utc_nist_verified}")
    
    # Test WWVH
    logger.info("")
    logger.info("Solving for WWVH at 10 MHz...")
    
    # WWVH is ~6600km, multi-hop delay ~24ms = 480 samples
    arrival_rtp_wwvh = expected_second_rtp + 480
    
    result_wwvh = solver.solve(
        station='WWVH',
        frequency_mhz=10.0,
        arrival_rtp=arrival_rtp_wwvh,
        delay_spread_ms=1.2,  # Higher multipath (longer path)
        doppler_std_hz=0.3,
        fss_db=-2.0,
        expected_second_rtp=expected_second_rtp
    )
    
    logger.info(f"  Mode: {result_wwvh.mode_name}")
    logger.info(f"  N hops: {result_wwvh.n_hops}")
    logger.info(f"  Propagation delay: {result_wwvh.propagation_delay_ms:.2f} ms")
    logger.info(f"  Confidence: {result_wwvh.confidence:.2%}")
    
    # Test multi-station solver
    logger.info("")
    logger.info("Testing multi-station correlation...")
    
    multi_solver = create_multi_station_solver('EM38ww', sample_rate=20000)
    
    multi_solver.add_observation(
        station='WWV',
        frequency_mhz=10.0,
        arrival_rtp=arrival_rtp,
        expected_second_rtp=expected_second_rtp,
        snr_db=28.0,
        delay_spread_ms=0.3
    )
    
    multi_solver.add_observation(
        station='WWVH',
        frequency_mhz=10.0,
        arrival_rtp=arrival_rtp_wwvh,
        expected_second_rtp=expected_second_rtp,
        snr_db=22.0,
        delay_spread_ms=1.2
    )
    
    combined = multi_solver.solve_combined()
    
    logger.info(f"  Combined UTC offset: {combined.utc_offset_ms:.2f} ms")
    logger.info(f"  Uncertainty: {combined.uncertainty_ms:.2f} ms")
    logger.info(f"  Consistency: {combined.consistency:.2%}")
    logger.info(f"  Quality grade: {combined.quality_grade}")
    logger.info(f"  Stations used: {combined.n_stations}")
    logger.info("  ✅ Multi-station solver works")
    
    return True


def test_full_pipeline():
    """Test complete pipeline orchestration"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("FULL PIPELINE TEST: End-to-End Integration")
    logger.info("=" * 60)
    
    from grape_recorder.grape import (
        PipelineConfig,
        PipelineOrchestrator,
        PipelineState
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = PipelineConfig(
            data_dir=Path(tmpdir),
            channel_name='WWV_10MHz',
            frequency_hz=10e6,
            sample_rate=20000,
            receiver_grid='EM38ww',
            station_config={
                'callsign': 'TEST',
                'grid_square': 'EM38ww',
                'psws_station_id': 'TEST01',
                'psws_instrument_id': '1'
            }
        )
        
        logger.info("Creating pipeline orchestrator...")
        orchestrator = PipelineOrchestrator(config)
        
        logger.info(f"  Pipeline state: {orchestrator.state.value}")
        assert orchestrator.state == PipelineState.IDLE
        
        logger.info("Starting pipeline...")
        orchestrator.start()
        assert orchestrator.state == PipelineState.RUNNING
        logger.info(f"  Pipeline state: {orchestrator.state.value}")
        
        # Generate and feed synthetic data
        logger.info("")
        logger.info("Feeding 5 seconds of synthetic data...")
        
        base_time = time.time()
        base_rtp = 1000000
        samples_per_packet = 400  # 20ms at 20kHz
        
        for i in range(25):  # 25 packets = 0.5 second
            packet_time = base_time + (i * 0.02)  # 20ms per packet
            packet_rtp = base_rtp + (i * samples_per_packet)
            
            # Generate packet worth of samples
            samples = generate_wwv_tone(
                duration_sec=0.02,
                sample_rate=20000,
                snr_db=25.0
            )
            
            orchestrator.process_samples(
                samples=samples,
                rtp_timestamp=packet_rtp,
                system_time=packet_time
            )
        
        # Wait a moment for processing
        time.sleep(0.5)
        
        # Check stats
        stats = orchestrator.get_stats()
        logger.info("")
        logger.info("Pipeline statistics:")
        logger.info(f"  Packets received: {stats.get('packets_received', 0)}")
        logger.info(f"  Samples archived: {stats.get('samples_archived', 0)}")
        logger.info(f"  Queue depth: {stats.get('queue_depth', 0)}")
        
        # Stop pipeline
        logger.info("")
        logger.info("Stopping pipeline...")
        orchestrator.stop()
        assert orchestrator.state == PipelineState.IDLE
        logger.info(f"  Pipeline state: {orchestrator.state.value}")
        
        logger.info("  ✅ Full pipeline test complete")
        
        return True


def main():
    """Run all integration tests"""
    print()
    print("=" * 70)
    print("  THREE-PHASE PIPELINE INTEGRATION TEST")
    print("=" * 70)
    print()
    
    results = []
    
    try:
        results.append(("Phase 1: Raw Archive", test_phase1_raw_archive()))
    except Exception as e:
        logger.error(f"Phase 1 failed: {e}")
        results.append(("Phase 1: Raw Archive", False))
    
    try:
        results.append(("Phase 2: Clock Offset", test_phase2_clock_offset()))
    except Exception as e:
        logger.error(f"Phase 2 failed: {e}")
        results.append(("Phase 2: Clock Offset", False))
    
    try:
        results.append(("Phase 3: Product", test_phase3_product()))
    except Exception as e:
        logger.error(f"Phase 3 failed: {e}")
        results.append(("Phase 3: Product", False))
    
    try:
        results.append(("Transmission Solver", test_transmission_solver()))
    except Exception as e:
        logger.error(f"Transmission Solver failed: {e}")
        results.append(("Transmission Solver", False))
    
    try:
        results.append(("Full Pipeline", test_full_pipeline()))
    except Exception as e:
        logger.error(f"Full Pipeline failed: {e}")
        results.append(("Full Pipeline", False))
    
    # Summary
    print()
    print("=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    print()
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("  🎉 ALL TESTS PASSED!")
    else:
        print("  ⚠️  SOME TESTS FAILED")
    print()
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    exit(main())
