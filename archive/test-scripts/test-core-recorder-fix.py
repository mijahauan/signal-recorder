#!/usr/bin/env python3
"""
Test Core Recorder Fix - Validate NPZ File Completeness

Checks that NPZ files contain exactly 960,000 samples (60 seconds @ 16 kHz)
and reports on timing quality indicators.

Usage:
    python3 test-core-recorder-fix.py --archive-dir /tmp/grape-test/archives/WWV_10_MHz
    python3 test-core-recorder-fix.py --archive-dir /tmp/grape-test/archives/WWV_10_MHz --latest 5
"""

import numpy as np
import argparse
from pathlib import Path
from datetime import datetime, timezone

def analyze_npz_file(file_path: Path) -> dict:
    """Analyze a single NPZ file for completeness"""
    try:
        archive = np.load(file_path)
        
        iq = archive['iq']
        rtp_timestamp = int(archive['rtp_timestamp'])
        sample_rate = int(archive['sample_rate'])
        gaps_filled = int(archive['gaps_filled'])
        gaps_count = int(archive['gaps_count'])
        packets_rx = int(archive['packets_received'])
        packets_exp = int(archive['packets_expected'])
        
        expected_samples = sample_rate * 60
        actual_samples = len(iq)
        duration_sec = actual_samples / sample_rate
        completeness_pct = 100.0 * (actual_samples - gaps_filled) / actual_samples if actual_samples > 0 else 0.0
        
        # File creation time
        created_time = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc)
        
        return {
            'file_name': file_path.name,
            'file_path': file_path,
            'samples': actual_samples,
            'expected_samples': expected_samples,
            'duration_sec': duration_sec,
            'sample_rate': sample_rate,
            'rtp_timestamp': rtp_timestamp,
            'gaps_filled': gaps_filled,
            'gaps_count': gaps_count,
            'packets_rx': packets_rx,
            'packets_exp': packets_exp,
            'completeness_pct': completeness_pct,
            'created_time': created_time,
            'complete': actual_samples == expected_samples,
            'file_size_mb': file_path.stat().st_size / (1024 * 1024)
        }
    except Exception as e:
        return {
            'file_name': file_path.name,
            'error': str(e)
        }

def main():
    parser = argparse.ArgumentParser(description='Validate Core Recorder NPZ Files')
    parser.add_argument('--archive-dir', type=Path, required=True,
                       help='Archive directory to scan')
    parser.add_argument('--latest', type=int, default=10,
                       help='Number of latest files to check (default: 10)')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed analysis for each file')
    args = parser.parse_args()
    
    if not args.archive_dir.exists():
        print(f"❌ Directory not found: {args.archive_dir}")
        return 1
    
    # Find all NPZ files
    npz_files = sorted(args.archive_dir.glob('*.npz'), key=lambda f: f.name)
    
    if not npz_files:
        print(f"❌ No NPZ files found in {args.archive_dir}")
        return 1
    
    print(f"📁 Archive Directory: {args.archive_dir}")
    print(f"📊 Total NPZ Files: {len(npz_files)}")
    print()
    
    # Analyze latest N files
    files_to_check = npz_files[-args.latest:] if args.latest else npz_files
    
    results = []
    for file_path in files_to_check:
        result = analyze_npz_file(file_path)
        results.append(result)
    
    # Summary statistics
    complete_files = [r for r in results if r.get('complete', False)]
    incomplete_files = [r for r in results if not r.get('complete', False) and 'error' not in r]
    error_files = [r for r in results if 'error' in r]
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Files Analyzed:        {len(results)}")
    print(f"✅ Complete (60s):     {len(complete_files)}")
    print(f"⚠️  Incomplete:         {len(incomplete_files)}")
    print(f"❌ Errors:             {len(error_files)}")
    print()
    
    if complete_files:
        avg_completeness = np.mean([r['completeness_pct'] for r in complete_files])
        avg_gaps = np.mean([r['gaps_count'] for r in complete_files])
        print(f"Average Data Quality:  {avg_completeness:.1f}%")
        print(f"Average Gaps/File:     {avg_gaps:.1f}")
        print()
    
    # Show incomplete files (the problem we're fixing)
    if incomplete_files:
        print("=" * 80)
        print("⚠️  INCOMPLETE FILES (BUG DETECTED)")
        print("=" * 80)
        for r in incomplete_files:
            print(f"File: {r['file_name']}")
            print(f"  Samples:   {r['samples']:,} / {r['expected_samples']:,} expected")
            print(f"  Duration:  {r['duration_sec']:.1f}s / 60.0s expected")
            print(f"  Created:   {r['created_time']}")
            print(f"  ⚠️  SHORT BY: {r['expected_samples'] - r['samples']:,} samples "
                  f"({60.0 - r['duration_sec']:.1f}s)")
            print()
    
    # Detailed analysis if requested
    if args.verbose:
        print("=" * 80)
        print("DETAILED ANALYSIS")
        print("=" * 80)
        for r in results:
            if 'error' in r:
                print(f"❌ {r['file_name']}: ERROR - {r['error']}")
                continue
            
            status = "✅" if r['complete'] else "⚠️"
            print(f"{status} {r['file_name']}")
            print(f"   Samples:      {r['samples']:,} ({r['duration_sec']:.1f}s)")
            print(f"   Completeness: {r['completeness_pct']:.1f}%")
            print(f"   Gaps:         {r['gaps_count']} ({r['gaps_filled']:,} samples)")
            print(f"   Packets:      {r['packets_rx']:,} / {r['packets_exp']:,}")
            print(f"   File Size:    {r['file_size_mb']:.2f} MB")
            print(f"   Created:      {r['created_time']}")
            print()
    
    # Test verdict
    print("=" * 80)
    if incomplete_files:
        print("❌ TEST FAILED: Found incomplete NPZ files")
        print()
        print("Expected: All files should contain 960,000 samples (60.0 seconds)")
        print("Action:   Core recorder bug still present - wall clock check not removed?")
        return 1
    elif complete_files:
        print("✅ TEST PASSED: All analyzed files are complete (960,000 samples)")
        print()
        print("Core recorder fix working correctly:")
        print("  - RTP timestamp is primary reference")
        print("  - Files written when sample count reaches 960,000")
        print("  - No premature writes on wall clock boundaries")
        return 0
    else:
        print("⚠️  NO VALID FILES: Unable to determine test result")
        return 1

if __name__ == '__main__':
    exit(main())
