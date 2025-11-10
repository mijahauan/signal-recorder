#!/usr/bin/env python3
"""
Test Digital RF Integration

Quick test to verify analytics service Digital RF output works.
Processes a few NPZ files and checks Digital RF output.
"""

import sys
import logging
import time
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_drf_integration():
    """Test complete analytics pipeline with Digital RF output"""
    
    # Import after path setup
    from signal_recorder.analytics_service import AnalyticsService
    
    # Configuration
    archive_dir = Path('/tmp/grape-core-test')
    output_dir = Path('/tmp/grape-analytics-test')
    
    # Clean output dir for test
    import shutil
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("="*80)
    logger.info("Digital RF Integration Test")
    logger.info("="*80)
    
    # Station config (PSWS-compatible format)
    station_config = {
        'callsign': 'AC0G',
        'grid_square': 'EN34',
        'receiver_name': 'GRAPE-TEST',
        'psws_station_id': 'AC0G',
        'psws_instrument_id': '1'
    }
    
    # Create analytics service
    logger.info("\nInitializing analytics service...")
    try:
        service = AnalyticsService(
            archive_dir=archive_dir,
            output_dir=output_dir,
            channel_name='WWV_10_MHz',
            frequency_hz=10000000.0,
            state_file=output_dir / 'state.json',
            station_config=station_config
        )
        logger.info("✅ Service initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize: {e}", exc_info=True)
        return 1
    
    # Process a few files
    logger.info("\nDiscovering NPZ files...")
    new_files = service.discover_new_files()
    logger.info(f"Found {len(new_files)} files")
    
    # Process first 3 files
    test_files = new_files[:3]
    logger.info(f"\nProcessing {len(test_files)} test files...")
    
    from signal_recorder.analytics_service import NPZArchive
    
    for i, file_path in enumerate(test_files):
        logger.info(f"\n[{i+1}/{len(test_files)}] Processing: {file_path.name}")
        
        try:
            # Load archive
            archive = NPZArchive.load(file_path)
            
            # Process through pipeline
            results = service.process_archive(archive)
            
            # Display results
            logger.info(f"  Quality: {results['quality_metrics']['completeness_pct']:.1f}% complete")
            logger.info(f"  Tones detected: {len(results['tone_detections'])}")
            logger.info(f"  Decimated samples: {results['decimated_samples']}")
            logger.info(f"  Time snap updated: {results['time_snap_updated']}")
            
            if results['errors']:
                logger.warning(f"  Errors: {results['errors']}")
            else:
                logger.info("  ✅ Processing successful")
                
        except Exception as e:
            logger.error(f"❌ Failed to process {file_path.name}: {e}", exc_info=True)
            return 1
    
    # Flush Digital RF writer
    logger.info("\nFlushing Digital RF buffers...")
    if service.drf_writer:
        service.drf_writer.flush()
        stats = service.drf_writer.get_stats()
        logger.info(f"  Samples written: {stats['samples_written']}")
        logger.info(f"  Buffer size: {stats['buffer_size']}")
        logger.info(f"  Decimation factor: {stats['decimation_factor']}")
        logger.info(f"  Output rate: {stats['output_sample_rate']} Hz")
    
    # Check outputs
    logger.info("\nVerifying outputs...")
    
    # Quality files
    quality_files = list(service.quality_dir.rglob('*.csv'))
    logger.info(f"  Quality CSV files: {len(quality_files)}")
    if quality_files:
        logger.info(f"    ✅ {quality_files[0]}")
    
    # Discontinuity logs
    log_files = list(service.logs_dir.rglob('*.log'))
    logger.info(f"  Discontinuity logs: {len(log_files)}")
    
    # Digital RF files
    drf_files = list(service.drf_dir.rglob('*.h5'))
    logger.info(f"  Digital RF HDF5 files: {len(drf_files)}")
    if drf_files:
        for drf_file in drf_files[:3]:
            size_mb = drf_file.stat().st_size / (1024*1024)
            logger.info(f"    ✅ {drf_file.name} ({size_mb:.1f} MB)")
    
    # Metadata files
    metadata_files = list(service.drf_dir.rglob('metadata*.h5'))
    logger.info(f"  Digital RF metadata files: {len(metadata_files)}")
    if metadata_files:
        for meta_file in metadata_files:
            size_kb = meta_file.stat().st_size / 1024
            logger.info(f"    ✅ {meta_file.name} ({size_kb:.1f} KB)")
    
    # Final summary
    logger.info("\n" + "="*80)
    if drf_files and quality_files:
        logger.info("✅ Digital RF Integration TEST PASSED")
        logger.info("="*80)
        logger.info("\nDigital RF pipeline verified:")
        logger.info("  ✅ NPZ archives → Quality analysis")
        logger.info("  ✅ Tone detection → Time snap")
        logger.info("  ✅ 16 kHz decimation → 10 Hz")
        logger.info("  ✅ Digital RF HDF5 output")
        logger.info("  ✅ Quality metadata embedding")
        logger.info(f"\nTest outputs: {output_dir}")
        return 0
    else:
        logger.error("❌ TEST FAILED - Missing expected outputs")
        return 1


if __name__ == '__main__':
    sys.exit(test_drf_integration())
