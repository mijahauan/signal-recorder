#!/usr/bin/env python3
"""
Diagnose BCD discrimination data availability
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

def main():
    data_root = Path(__file__).parent.parent / 'data'
    
    print("=" * 70)
    print("BCD DISCRIMINATION DATA DIAGNOSIS")
    print("=" * 70)
    print()
    
    # Check for archives
    archives_dir = data_root / 'archives'
    if not archives_dir.exists():
        print("❌ No archives directory found")
        return
    
    print("✅ Archives directory exists")
    
    # Count NPZ files
    npz_count = 0
    for channel_dir in archives_dir.iterdir():
        if channel_dir.is_dir():
            npz_files = list(channel_dir.glob('*.npz'))
            if npz_files:
                print(f"   📁 {channel_dir.name}: {len(npz_files)} NPZ files")
                npz_count += len(npz_files)
    
    if npz_count == 0:
        print("❌ No NPZ archive files found")
        return
    
    print(f"\n✅ Total NPZ files: {npz_count}")
    print()
    
    # Check for discrimination CSV files
    from grape_recorder.paths import GRAPEPaths
    paths = GRAPEPaths(data_root)
    analytics_dir = data_root / 'analytics'  # For existence check only
    if not analytics_dir.exists():
        print("❌ No analytics directory - CSV files haven't been generated")
        print()
        print("SOLUTION: Run the reprocessing script:")
        print("  cd /home/mjh/git/signal-recorder")
        print("  python3 scripts/reprocess_discrimination.py --date 20251119 --channel 'WWV 10 MHz'")
        return
    
    print("✅ Analytics directory exists")
    
    # Check for CSV files
    csv_count = 0
    csv_with_bcd = 0
    
    paths = GRAPEPaths(data_root)
    for channel_dir in analytics_dir.iterdir():
        if channel_dir.is_dir():
            discrimination_dir = paths.get_discrimination_dir(channel_dir.name)
            if discrimination_dir.exists():
                csv_files = list(discrimination_dir.glob('*.csv'))
                if csv_files:
                    print(f"   📄 {channel_dir.name}: {len(csv_files)} CSV files")
                    csv_count += len(csv_files)
                    
                    # Check if BCD columns exist
                    for csv_file in csv_files:
                        try:
                            with open(csv_file, 'r') as f:
                                header = f.readline()
                                if 'bcd_windows' in header:
                                    csv_with_bcd += 1
                                    # Check if there's actual BCD data
                                    sample_line = f.readline()
                                    if sample_line:
                                        fields = sample_line.split(',')
                                        if len(fields) > 18:  # Has BCD fields
                                            bcd_windows_field = fields[-1].strip().strip('"')
                                            if bcd_windows_field and bcd_windows_field != '':
                                                print(f"      ✅ {csv_file.name} has BCD data")
                                            else:
                                                print(f"      ⚠️  {csv_file.name} has BCD columns but no data")
                                        else:
                                            print(f"      ❌ {csv_file.name} missing BCD columns")
                        except Exception as e:
                            print(f"      ⚠️  Error reading {csv_file.name}: {e}")
    
    if csv_count == 0:
        print("\n❌ No discrimination CSV files found")
        print()
        print("SOLUTION: Run the reprocessing script:")
        print("  cd /home/mjh/git/signal-recorder")
        print("  python3 scripts/reprocess_discrimination.py --date 20251119 --channel 'WWV 10 MHz'")
    elif csv_with_bcd == 0:
        print(f"\n⚠️  Found {csv_count} CSV files but NONE have BCD columns")
        print()
        print("SOLUTION: Re-run reprocessing to add BCD columns:")
        print("  cd /home/mjh/git/signal-recorder")
        print("  python3 scripts/reprocess_discrimination.py --date 20251119 --channel 'WWV 10 MHz'")
    else:
        print(f"\n✅ Found {csv_with_bcd} CSV files with BCD columns")
        print()
        print("If web UI shows empty graphs:")
        print("1. Hard refresh browser (Ctrl+Shift+R)")
        print("2. Check browser console for JavaScript errors")
        print("3. Verify API is serving the CSV files")

if __name__ == '__main__':
    main()
