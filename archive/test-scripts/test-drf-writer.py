#!/usr/bin/env python3
"""
Test DRF Writer Service

Tests the standalone DRF writer with existing 10 Hz NPZ files.
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

# Import directly to avoid ka9q dependency
import importlib.util
spec = importlib.util.spec_from_file_location(
    "drf_writer_service",
    Path(__file__).parent / 'src' / 'signal_recorder' / 'drf_writer_service.py'
)
drf_writer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drf_writer_module)
DRFWriterService = drf_writer_module.DRFWriterService
DecimatedArchive = drf_writer_module.DecimatedArchive

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_drf_writer():
    """Test DRF writer with WWV 5 MHz data (shared frequency - good for later discrimination test)"""
    
    # Configuration
    channel_name = "WWV 5 MHz"
    frequency_hz = 5_000_000
    input_dir = Path("/tmp/grape-test/archives/WWV_5_MHz")
    output_dir = Path("/tmp/grape-test/drf_test_output")
    analytics_dir = Path("/tmp/grape-test/analytics/WWV_5_MHz")
    analytics_state_file = analytics_dir / "analytics_state.json"
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Station config
    station_config = {
        'callsign': 'TEST',
        'grid_square': 'EM00',
        'receiver_name': 'grape_test_receiver',
        'psws_station_id': 'test_wwv5',
        'psws_instrument_id': 'grape_v2_test'
    }
    
    logger.info(f"Testing DRF Writer for {channel_name}")
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Analytics state: {analytics_state_file}")
    
    # Check for 10 Hz NPZ files
    npz_files = sorted(input_dir.glob("*_iq_10hz.npz"))
    logger.info(f"Found {len(npz_files)} 10 Hz NPZ files")
    
    if not npz_files:
        logger.error("No 10 Hz NPZ files found! Run analytics service first to generate them.")
        return False
    
    # Show first few files
    logger.info("First 5 files:")
    for f in npz_files[:5]:
        size_mb = f.stat().st_size / (1024 * 1024)
        logger.info(f"  {f.name} ({size_mb:.2f} MB)")
    
    # Initialize DRF writer service
    logger.info("\nInitializing DRF Writer Service...")
    try:
        service = DRFWriterService(
            input_dir=input_dir,
            output_dir=output_dir,
            channel_name=channel_name,
            frequency_hz=frequency_hz,
            analytics_state_file=analytics_state_file,
            station_config=station_config
        )
        logger.info("✅ DRF Writer Service initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize DRF Writer: {e}", exc_info=True)
        return False
    
    # Process a small batch (5 files manually)
    logger.info("\nProcessing first 5 files...")
    processed = 0
    errors = 0
    
    for npz_file in npz_files[:5]:
        try:
            logger.info(f"\nProcessing: {npz_file.name}")
            
            # Load decimated archive
            archive = DecimatedArchive.load(npz_file)
            
            # Load time_snap
            time_snap = service._load_time_snap()
            if time_snap:
                logger.info(f"  Time_snap: {time_snap.station} @ {time_snap.utc_timestamp}")
            else:
                logger.info("  No time_snap available (will use file timestamp)")
            
            # Write to DRF
            service.write_to_drf(archive, time_snap)
            
            logger.info(f"✅ Success: Wrote {len(archive.iq_samples)} samples")
            processed += 1
                
        except Exception as e:
            logger.error(f"❌ Exception processing {npz_file.name}: {e}", exc_info=True)
            errors += 1
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("DRF WRITER TEST SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Files processed: {processed}/5")
    logger.info(f"Errors: {errors}")
    logger.info(f"Output directory: {output_dir}")
    
    # Check output
    if output_dir.exists():
        drf_files = list(output_dir.rglob("*.h5"))
        logger.info(f"Digital RF files created: {len(drf_files)}")
        if drf_files:
            logger.info("Sample DRF files:")
            for f in drf_files[:3]:
                size_kb = f.stat().st_size / 1024
                logger.info(f"  {f.relative_to(output_dir)} ({size_kb:.1f} KB)")
    
    return processed > 0 and errors == 0

if __name__ == '__main__':
    success = test_drf_writer()
    sys.exit(0 if success else 1)
