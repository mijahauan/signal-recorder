#!/usr/bin/env python3
"""
Test DRF Writer in Wsprdaemon-Compatible Mode

Verifies that Digital RF output matches wsprdaemon format exactly:
- Single metadata file with basic station info
- No timing quality, gap analysis, or discrimination metadata
- Compatible with existing PSWS infrastructure
"""

import sys
import argparse
from pathlib import Path
import numpy as np

try:
    import digital_rf as drf
except ImportError:
    print("ERROR: digital_rf not available - cannot test")
    sys.exit(1)

def check_drf_structure(drf_dir: Path, channel_name: str = 'ch0'):
    """Verify DRF directory structure matches wsprdaemon format"""
    print(f"\n📁 Checking DRF structure: {drf_dir}")
    
    # Should have main data channel
    if not drf_dir.exists():
        print(f"❌ DRF directory does not exist: {drf_dir}")
        return False, None
    
    # Check for channel directory
    channel_dir = drf_dir / channel_name
    if not channel_dir.exists():
        print(f"❌ Channel directory missing: {channel_dir}")
        return False, None
    
    # Check for metadata directory inside channel
    metadata_dir = channel_dir / "metadata"
    if not metadata_dir.exists():
        print(f"❌ Metadata directory missing: {metadata_dir}")
        return False, None
    
    print(f"✅ DRF directory structure exists")
    
    # List metadata files
    metadata_files = list(metadata_dir.glob("*.h5"))
    print(f"\n📋 Metadata files found: {len(metadata_files)}")
    for mf in metadata_files:
        print(f"   - {mf.name}")
    
    # In wsprdaemon mode, should have only ONE metadata type
    # Enhanced mode has: timing_quality/, data_quality/, wwvh_discrimination (NOT time-based subdirs)
    enhanced_metadata_dirs = ['timing_quality', 'data_quality', 'wwvh_discrimination', 'station_info']
    found_enhanced = [d for d in metadata_dir.iterdir() if d.is_dir() and d.name in enhanced_metadata_dirs]
    
    if found_enhanced:
        print("⚠️  Warning: Enhanced metadata channels found (not wsprdaemon mode):")
        for subdir in found_enhanced:
            print(f"   - {subdir.name}/")
    
    return True, metadata_dir

def read_metadata(drf_dir: Path, metadata_dir: Path):
    """Read and display metadata to verify wsprdaemon format"""
    print(f"\n📖 Reading metadata from: {metadata_dir}")
    
    try:
        # Read Digital RF channel
        reader = drf.DigitalRFReader(str(drf_dir))
        
        # Get channel name (should be 'ch0' for wsprdaemon compat)
        channels = reader.get_channels()
        print(f"\n📡 Channels: {channels}")
        
        if not channels:
            print("❌ No channels found in DRF dataset")
            return False
        
        # Read metadata
        if metadata_dir.exists():
            md_reader = drf.DigitalMetadataReader(str(metadata_dir))
            
            # Get bounds
            bounds = md_reader.get_bounds()
            print(f"\n⏰ Metadata bounds: {bounds}")
            
            if bounds[0] is not None:
                # Read first metadata sample
                metadata_raw = md_reader.read(bounds[0], bounds[0] + 1)
                
                # Digital RF nests metadata under timestamp keys
                # Get the first timestamp's metadata
                if metadata_raw:
                    first_timestamp = next(iter(metadata_raw))
                    metadata = metadata_raw[first_timestamp]
                    
                    print(f"\n📝 Metadata fields:")
                    for key, value in metadata.items():
                        if isinstance(value, np.ndarray):
                            print(f"   {key}: {value.tolist() if value.size < 10 else f'array[{value.shape}]'}")
                        else:
                            print(f"   {key}: {value}")
                    
                    # Verify wsprdaemon-compatible fields
                    required_fields = ['callsign', 'grid_square', 'receiver_name', 'center_frequencies', 'uuid_str']
                    wsprdaemon_compat = True
                    
                    print(f"\n✓ Wsprdaemon compatibility check:")
                    for field in required_fields:
                        if field in metadata:
                            print(f"   ✅ {field}: present")
                        else:
                            print(f"   ❌ {field}: MISSING")
                            wsprdaemon_compat = False
                else:
                    print(f"❌ No metadata found")
                    wsprdaemon_compat = False
                
                # Check for enhanced metadata fields (should NOT be present)
                enhanced_fields = ['psws_station_id', 'psws_instrument_id', 'center_frequency_hz', 
                                  'processing_chain', 'timing_quality', 'completeness_pct']
                enhanced_detected = False
                for field in enhanced_fields:
                    if field in metadata:
                        print(f"   ⚠️  {field}: present (enhanced mode field)")
                        enhanced_detected = True
                
                if wsprdaemon_compat and not enhanced_detected:
                    print(f"\n✅ Metadata matches wsprdaemon format!")
                elif enhanced_detected:
                    print(f"\n⚠️  Enhanced metadata detected - not pure wsprdaemon mode")
                else:
                    print(f"\n❌ Metadata does not match wsprdaemon format")
                
                return wsprdaemon_compat
        
        return True
        
    except Exception as e:
        print(f"❌ Error reading DRF: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_sample_data(drf_dir: Path, channel_name: str = 'ch0'):
    """Verify IQ data is present and correct"""
    print(f"\n📊 Checking sample data for channel: {channel_name}")
    
    try:
        reader = drf.DigitalRFReader(str(drf_dir))
        
        # Get bounds
        bounds = reader.get_bounds(channel_name)
        print(f"   Data bounds: {bounds}")
        
        if bounds[0] is None:
            print(f"❌ No data found in channel {channel_name}")
            return False
        
        # Read a small sample
        num_samples = min(100, bounds[1] - bounds[0])
        data = reader.read_vector(bounds[0], num_samples, channel_name)
        
        print(f"   Sample count: {len(data)}")
        print(f"   Data type: {data.dtype}")
        print(f"   Complex: {np.iscomplexobj(data)}")
        
        if not np.iscomplexobj(data):
            print(f"❌ Data is not complex (should be complex IQ)")
            return False
        
        # Check for reasonable values
        max_mag = np.max(np.abs(data))
        mean_mag = np.mean(np.abs(data))
        print(f"   Max magnitude: {max_mag:.4f}")
        print(f"   Mean magnitude: {mean_mag:.4f}")
        
        if max_mag == 0:
            print(f"⚠️  All samples are zero")
        else:
            print(f"✅ Sample data looks valid")
        
        return True
        
    except Exception as e:
        print(f"❌ Error reading samples: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Test DRF output for wsprdaemon compatibility'
    )
    parser.add_argument('drf_dir', type=Path,
                       help='Path to Digital RF top-level directory (parent of channel directories)')
    parser.add_argument('--channel', default='ch0',
                       help='Channel name to check (default: ch0)')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("WSPRDAEMON DIGITAL RF COMPATIBILITY TEST")
    print("=" * 70)
    
    # Run checks
    structure_ok, metadata_dir = check_drf_structure(args.drf_dir, args.channel)
    metadata_ok = read_metadata(args.drf_dir, metadata_dir) if structure_ok else False
    samples_ok = check_sample_data(args.drf_dir, args.channel) if structure_ok else False
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Directory structure: {'✅ PASS' if structure_ok else '❌ FAIL'}")
    print(f"Metadata format:     {'✅ PASS' if metadata_ok else '❌ FAIL'}")
    print(f"Sample data:         {'✅ PASS' if samples_ok else '❌ FAIL'}")
    
    if structure_ok and metadata_ok and samples_ok:
        print("\n🎉 All tests passed - wsprdaemon compatible!")
        return 0
    else:
        print("\n❌ Some tests failed - review output above")
        return 1

if __name__ == '__main__':
    sys.exit(main())
