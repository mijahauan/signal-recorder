#!/usr/bin/env python3
"""
Create synthetic Digital RF data for testing upload functionality.

This creates a minimal but valid Digital RF dataset that can be used
to test the upload process without waiting 24 hours for real data.
"""

import numpy as np
import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import digital_rf as drf
except ImportError:
    print("Error: digital_rf not installed")
    print("Install with: pip install digital_rf")
    sys.exit(1)


def create_test_digital_rf(output_dir: Path, date: datetime.date, 
                           duration_minutes: int = 1, channel_name: str = "WWV_2_5"):
    """
    Create a minimal but valid Digital RF dataset for testing.
    
    Args:
        output_dir: Base output directory
        date: Date to simulate
        duration_minutes: How many minutes of data to generate (default: 1)
        channel_name: Channel name (e.g., WWV_2_5)
    
    Returns:
        Path to created dataset
    """
    # Calculate midnight UTC for the specified date
    day_start = datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc)
    start_time = day_start.timestamp()
    start_global_index = int(start_time * 10)  # 10 Hz sample rate
    
    # Calculate number of samples (10 Hz × 60 seconds/min)
    num_samples = duration_minutes * 600
    
    print(f"Creating test Digital RF dataset:")
    print(f"  Date: {date}")
    print(f"  Channel: {channel_name}")
    print(f"  Duration: {duration_minutes} minute(s)")
    print(f"  Samples: {num_samples}")
    print(f"  Start time: {day_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Start global index: {start_global_index}")
    
    # Generate random complex I/Q samples
    # In reality, these would be actual radio signals
    i_samples = np.random.randn(num_samples).astype(np.float32) * 0.1
    q_samples = np.random.randn(num_samples).astype(np.float32) * 0.1
    samples = (i_samples + 1j * q_samples).astype(np.complex64)
    
    # Create channel directory
    channel_dir = output_dir / channel_name
    channel_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nWriting Digital RF to {channel_dir}...")
    
    # Generate UUID for this dataset
    import uuid
    dataset_uuid = uuid.uuid4().hex
    
    # Write Digital RF data (wsprdaemon-compatible format)
    with drf.DigitalRFWriter(
        str(channel_dir),
        dtype=np.complex64,
        subdir_cadence_secs=3600,          # 1 hour subdirectories
        file_cadence_millisecs=1000,        # 1 second files
        start_global_index=start_global_index,
        sample_rate_numerator=10,
        sample_rate_denominator=1,
        uuid_str=dataset_uuid,
        compression_level=6,
        checksum=False,
        is_complex=True,
        num_subchannels=1,
        is_continuous=True,                 # No gaps
        marching_periods=False
    ) as writer:
        writer.rf_write(samples)
    
    print("  ✅ Digital RF data written")
    
    # Write metadata (wsprdaemon-compatible format)
    metadata_dir = channel_dir / 'metadata'
    metadata_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract frequency from channel name (e.g., WWV_2_5 → 2.5 MHz)
    try:
        freq_str = channel_name.split('_')[-1].replace('_', '.')
        frequency_mhz = float(freq_str)
        frequency_hz = frequency_mhz * 1e6
    except:
        frequency_hz = 2500000.0  # Default to 2.5 MHz
    
    metadata = {
        'callsign': 'TEST',
        'grid_square': 'EM00',
        'receiver_name': 'test_receiver',
        'center_frequencies': np.array([frequency_hz], dtype=np.float64),
        'uuid_str': dataset_uuid,
        'sample_rate': 10.0,
        'date': date.isoformat()
    }
    
    print(f"Writing metadata...")
    
    with drf.DigitalMetadataWriter(
        str(metadata_dir),
        subdir_cadence_secs=3600,
        file_cadence_secs=3600,
        sample_rate_numerator=10,
        sample_rate_denominator=1,
        file_name='metadata'
    ) as metadata_writer:
        metadata_writer.write(start_global_index, metadata)
    
    print("  ✅ Metadata written")
    
    # Create OBS directory structure (wsprdaemon format)
    obs_name = day_start.strftime('OBS%Y-%m-%dT%H-%M')
    obs_dir = output_dir / obs_name
    obs_dir.mkdir(parents=True, exist_ok=True)
    
    # Symlink or move channel into OBS directory
    obs_channel_dir = obs_dir / channel_name
    if not obs_channel_dir.exists():
        obs_channel_dir.symlink_to(channel_dir.absolute())
    
    print(f"\n✅ Test dataset created successfully!")
    print(f"\nDataset structure:")
    print(f"  {obs_dir}/")
    print(f"    └── {channel_name}/")
    print(f"        ├── YYYY-MM-DD-HH-MM-SS/  (hourly subdirs)")
    print(f"        └── metadata/")
    
    return obs_dir


def verify_dataset(dataset_path: Path):
    """
    Verify Digital RF dataset can be read.
    
    Args:
        dataset_path: Path to dataset directory
    """
    print(f"\n🔍 Verifying dataset at {dataset_path}...")
    
    # Find channels
    channels = [d for d in dataset_path.iterdir() if d.is_dir() and not d.name.startswith('.')]
    
    if not channels:
        print("  ❌ No channels found")
        return False
    
    print(f"  Found {len(channels)} channel(s): {', '.join(c.name for c in channels)}")
    
    for channel_dir in channels:
        try:
            reader = drf.DigitalRFReader(str(channel_dir))
            bounds = reader.get_bounds()
            
            if bounds[0] is None or bounds[1] is None:
                print(f"  ❌ {channel_dir.name}: No data found")
                continue
            
            # Read a sample to verify
            start_sample = bounds[0]
            data = reader.read_vector(start_sample, 10)  # Read 10 samples
            
            print(f"  ✅ {channel_dir.name}:")
            print(f"     Samples: {bounds[0]} to {bounds[1]}")
            print(f"     Count: {bounds[1] - bounds[0]}")
            print(f"     Data type: {data.dtype}")
            print(f"     Sample: {data[0]:.6f}")
            
        except Exception as e:
            print(f"  ❌ {channel_dir.name}: Error reading - {e}")
            return False
    
    print("\n✅ Dataset verification successful!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Create synthetic Digital RF data for upload testing"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("/tmp/grape_test_upload"),
        help="Output directory (default: /tmp/grape_test_upload)"
    )
    parser.add_argument(
        "-d", "--date",
        type=str,
        help="Date to simulate (YYYY-MM-DD, default: yesterday)"
    )
    parser.add_argument(
        "-m", "--minutes",
        type=int,
        default=1,
        help="Duration in minutes (default: 1, full day: 1440)"
    )
    parser.add_argument(
        "-c", "--channel",
        type=str,
        default="WWV_2_5",
        help="Channel name (default: WWV_2_5)"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify dataset after creation"
    )
    
    args = parser.parse_args()
    
    # Parse or default date
    if args.date:
        try:
            date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        # Default to yesterday
        date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    
    # Create test data
    try:
        dataset_path = create_test_digital_rf(
            args.output,
            date,
            args.minutes,
            args.channel
        )
        
        # Verify if requested
        if args.verify:
            if not verify_dataset(dataset_path):
                sys.exit(1)
        
        print(f"\n📤 Ready for upload testing:")
        print(f"   Dataset: {dataset_path}")
        print(f"   Date: {date}")
        print(f"\nNext steps:")
        print(f"  1. Configure upload credentials in config")
        print(f"  2. Test SFTP connection to PSWS")
        print(f"  3. Run upload: signal-recorder upload {dataset_path}")
        
    except Exception as e:
        print(f"\n❌ Error creating test data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
