#!/usr/bin/env python3
"""
Test upload using configuration from grape-S000171.toml

This script:
1. Loads config from grape-S000171.toml
2. Uses existing S000171/172 credentials
3. Tests upload with synthetic data
"""

import sys
import toml
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from signal_recorder.uploader import UploadManager, load_upload_config_from_toml


def main():
    print("🧪 Testing GRAPE Upload with grape-S000171.toml configuration\n")
    
    # Load TOML config
    config_file = Path(__file__).parent / 'config' / 'grape-S000171.toml'
    
    if not config_file.exists():
        print(f"❌ Config file not found: {config_file}")
        sys.exit(1)
    
    print(f"📖 Loading config from: {config_file}")
    with open(config_file, 'r') as f:
        toml_config = toml.load(f)
    
    # Extract upload configuration
    upload_config = load_upload_config_from_toml(toml_config)
    station_config = toml_config.get('station', {})
    
    print(f"\n📡 Station Configuration:")
    print(f"   Callsign: {station_config.get('callsign', 'N/A')}")
    print(f"   Grid: {station_config.get('grid_square', 'N/A')}")
    print(f"   Station ID: {station_config.get('id', 'N/A')}")
    print(f"   Instrument: {station_config.get('instrument_id', 'N/A')}")
    
    print(f"\n📤 Upload Configuration:")
    print(f"   Protocol: {upload_config['protocol']}")
    print(f"   Host: {upload_config['host']}")
    print(f"   User: {upload_config['user']}")
    print(f"   SSH Key: {upload_config['ssh']['key_file']}")
    print(f"   Bandwidth: {upload_config['bandwidth_limit_kbps']} KB/s")
    
    # Check for test dataset
    dataset_path = Path('/tmp/grape_test_upload')
    obs_dirs = list(dataset_path.glob('OBS*'))
    
    if not obs_dirs:
        print(f"\n❌ No test dataset found at {dataset_path}")
        print(f"\nCreate one with:")
        print(f"   python3 test_upload.py --verify")
        sys.exit(1)
    
    test_dataset = obs_dirs[0]
    print(f"\n📦 Test Dataset: {test_dataset}")
    
    # Prepare metadata
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    metadata = {
        'date': yesterday,
        'callsign': station_config.get('callsign', 'TEST'),
        'grid_square': station_config.get('grid_square', 'EM00'),
        'station_id': station_config.get('id', 'S000171'),
        'instrument_id': station_config.get('instrument_id', '172')
    }
    
    print(f"\n📋 Upload Metadata:")
    for key, value in metadata.items():
        print(f"   {key}: {value}")
    
    # Create dummy storage manager
    class DummyStorage:
        pass
    
    # Create uploader
    print(f"\n🚀 Initializing uploader...")
    uploader = UploadManager(upload_config, DummyStorage())
    
    # Enqueue dataset
    print(f"\n1️⃣  Enqueuing dataset...")
    uploader.enqueue(test_dataset, metadata)
    
    # Check queue status
    status = uploader.get_status()
    if status['total'] == 0:
        print(f"\n⚠️  Dataset not enqueued (check logs above for reason)")
        print(f"\nCommon reasons:")
        print(f"   - Date validation failed (must be yesterday or earlier)")
        print(f"   - Already uploaded (.upload_complete marker exists)")
        print(f"   - Digital RF validation failed")
        sys.exit(1)
    
    print(f"\n   ✅ Dataset enqueued successfully")
    
    # Process queue
    print(f"\n2️⃣  Processing upload queue...")
    uploader.process_queue()
    
    # Final status
    status = uploader.get_status()
    print(f"\n3️⃣  Upload Queue Status:")
    print(f"   Total: {status['total']}")
    print(f"   Completed: {status['completed']}")
    print(f"   Failed: {status['failed']}")
    print(f"   Pending: {status['pending']}")
    
    if status['completed'] > 0:
        print(f"\n✅ Upload test SUCCESSFUL!")
        print(f"\nNext steps:")
        print(f"   1. Check PSWS dashboard for uploaded data")
        print(f"   2. Verify trigger directory was created")
        print(f"   3. Look for .upload_complete marker:")
        print(f"      ls -la {test_dataset.parent}/.upload_complete")
    elif status['failed'] > 0:
        print(f"\n❌ Upload test FAILED")
        print(f"\nCheck logs for errors")
    else:
        print(f"\n⏳ Upload pending (may need retry)")
    
    print(f"\n" + "="*60)
    print(f"Test complete!")


if __name__ == "__main__":
    main()
