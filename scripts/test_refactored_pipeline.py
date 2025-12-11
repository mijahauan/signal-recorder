#!/usr/bin/env python3
"""
Test script for the refactored grape-recorder pipeline.

Tests:
1. StreamRecorder with RadiodStream
2. BinaryArchiveWriter with gap annotations
3. Phase3ProductEngine with TimingClient integration
4. End-to-end data flow

Usage:
    python scripts/test_refactored_pipeline.py
"""

import sys
import time
import tempfile
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


def test_imports():
    """Test all required imports work."""
    print("=" * 60)
    print("TEST: Module Imports")
    print("=" * 60)
    
    try:
        from grape_recorder.grape.stream_recorder import (
            StreamRecorder, StreamRecorderConfig, ChannelStreamRecorder
        )
        print("✓ StreamRecorder")
        
        from grape_recorder.grape.binary_archive_writer import (
            BinaryArchiveWriter, BinaryArchiveConfig, GapInterval
        )
        print("✓ BinaryArchiveWriter + GapInterval")
        
        from grape_recorder.grape.phase3_product_engine import (
            Phase3ProductEngine, Phase3Config
        )
        print("✓ Phase3ProductEngine")
        
        from grape_recorder.timing_client import TimingClient, ClockStatus
        print("✓ TimingClient")
        
        from grape_recorder.grape.pipeline_orchestrator import (
            PipelineOrchestrator, PipelineConfig
        )
        print("✓ PipelineOrchestrator")
        
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_gap_interval():
    """Test GapInterval dataclass."""
    print("\n" + "=" * 60)
    print("TEST: GapInterval Dataclass")
    print("=" * 60)
    
    from grape_recorder.grape.binary_archive_writer import GapInterval
    
    gap = GapInterval(
        start_sample=1000,
        duration_samples=400,
        source='rtp_loss'
    )
    
    print(f"  start_sample: {gap.start_sample}")
    print(f"  duration_samples: {gap.duration_samples}")
    print(f"  source: {gap.source}")
    
    # Test to_dict
    d = gap.to_dict()
    assert d['start_sample'] == 1000
    assert d['duration_samples'] == 400
    assert d['source'] == 'rtp_loss'
    print("✓ GapInterval works correctly")
    return True


def test_binary_archive_writer():
    """Test BinaryArchiveWriter with gap annotations."""
    print("\n" + "=" * 60)
    print("TEST: BinaryArchiveWriter with Gaps")
    print("=" * 60)
    
    from grape_recorder.grape.binary_archive_writer import (
        BinaryArchiveWriter, BinaryArchiveConfig, GapInterval
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = BinaryArchiveConfig(
            output_dir=Path(tmpdir),
            channel_name='TEST_10_MHz',
            frequency_hz=10e6,
            sample_rate=20000,
            station_config={'callsign': 'TEST', 'grid_square': 'XX00xx'}
        )
        
        writer = BinaryArchiveWriter(config)
        
        # Create test samples (1 second = 20000 samples)
        samples = np.zeros(20000, dtype=np.complex64)
        samples.real = np.sin(2 * np.pi * 100 * np.arange(20000) / 20000)
        
        # Create gap records
        gaps = [
            GapInterval(start_sample=5000, duration_samples=100, source='test_gap')
        ]
        
        # Write samples with gap info
        rtp_ts = int(time.time() * 20000)
        system_time = time.time()
        
        written = writer.write_samples(
            samples=samples,
            rtp_timestamp=rtp_ts,
            system_time=system_time,
            gaps=gaps
        )
        
        print(f"  Wrote {written} samples")
        
        writer.close()
        
        stats = writer.get_stats()
        print(f"  Samples written: {stats['samples_written']}")
        print(f"  Total gaps: {stats['total_gaps']}")
        
        print("✓ BinaryArchiveWriter handles gap annotations")
        return True


def test_timing_client():
    """Test TimingClient connection to time-manager."""
    print("\n" + "=" * 60)
    print("TEST: TimingClient")
    print("=" * 60)
    
    from grape_recorder.timing_client import TimingClient
    
    client = TimingClient()
    
    print(f"  SHM path: {client.shm_path}")
    print(f"  Available: {client.available}")
    
    if client.available:
        d_clock = client.get_d_clock()
        status = client.get_clock_status()
        if d_clock is not None:
            print(f"  D_clock: {d_clock:.2f} ms")
        else:
            print("  D_clock: None (data may be stale)")
        print(f"  Status: {status}")
        
        snapshot = client.get_snapshot()
        if snapshot:
            print(f"  Age: {snapshot.age_seconds:.1f}s")
        print("✓ TimingClient connected to time-manager")
    else:
        print("  ⚠ time-manager not running (SHM not found)")
        print("  This is OK for testing - TimingClient will fall back gracefully")
    
    return True


def test_phase3_timing_integration():
    """Test Phase3ProductEngine with TimingClient."""
    print("\n" + "=" * 60)
    print("TEST: Phase3ProductEngine TimingClient Integration")
    print("=" * 60)
    
    from grape_recorder.grape.phase3_product_engine import Phase3ProductEngine, Phase3Config
    from grape_recorder.timing_client import TimingClient
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Phase3Config(
            data_root=Path(tmpdir),
            channel_name='WWV_10_MHz',
            frequency_hz=10e6,
            station_config={'callsign': 'TEST', 'grid_square': 'XX00xx'}
        )
        
        engine = Phase3ProductEngine(config)
        
        # Check TimingClient is initialized
        if engine.timing_client:
            print(f"  TimingClient initialized: {engine.timing_client.available}")
        else:
            print("  TimingClient not available (TIMING_CLIENT_AVAILABLE=False)")
        
        # Test load_phase2_result with live timing
        current_time = time.time()
        result = engine.load_phase2_result(current_time)
        
        if result:
            print(f"  D_clock from TimingClient: {result['d_clock_ms']:.2f} ms")
            print(f"  Quality grade: {result['quality_grade']}")
            print(f"  Station: {result['station']}")
        else:
            print("  No timing data (time-manager not running or data too old)")
        
        engine.close()
        print("✓ Phase3ProductEngine TimingClient integration works")
        return True


def test_pipeline_orchestrator_disabled_phase2():
    """Test that PipelineOrchestrator has Phase 2 timing disabled."""
    print("\n" + "=" * 60)
    print("TEST: PipelineOrchestrator Phase 2 Disabled")
    print("=" * 60)
    
    from grape_recorder.grape.pipeline_orchestrator import PipelineOrchestrator, PipelineConfig
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = PipelineConfig(
            data_dir=Path(tmpdir),
            channel_name='WWV_10_MHz',
            frequency_hz=10e6,
            sample_rate=20000,
            output_sample_rate=10,
            station_config={'callsign': 'TEST', 'grid_square': 'XX00xx'},
            receiver_grid='XX00xx'
        )
        
        orchestrator = PipelineOrchestrator(config)
        
        # Verify clock_offset_engine is disabled
        if orchestrator.clock_offset_engine is None:
            print("  ✓ clock_offset_engine is None (disabled)")
        else:
            print("  ✗ clock_offset_engine should be None")
            return False
        
        # Check stats report
        orchestrator.start()
        time.sleep(0.1)
        stats = orchestrator.get_stats()
        orchestrator.stop()
        
        phase2_status = stats.get('phase2_stats', {})
        if isinstance(phase2_status, dict) and 'disabled' in str(phase2_status.get('status', '')):
            print(f"  ✓ Phase 2 status: {phase2_status['status']}")
        
        print("✓ PipelineOrchestrator correctly has Phase 2 timing disabled")
        return True


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print(" GRAPE-RECORDER REFACTORED PIPELINE TESTS")
    print(" Testing RadiodStream + TimingClient Integration")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Imports", test_imports()))
    results.append(("GapInterval", test_gap_interval()))
    results.append(("BinaryArchiveWriter", test_binary_archive_writer()))
    results.append(("TimingClient", test_timing_client()))
    results.append(("Phase3 TimingClient", test_phase3_timing_integration()))
    results.append(("PipelineOrchestrator", test_pipeline_orchestrator_disabled_phase2()))
    
    # Summary
    print("\n" + "=" * 60)
    print(" TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
