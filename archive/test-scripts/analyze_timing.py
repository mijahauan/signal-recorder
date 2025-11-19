#!/usr/bin/env python3
"""
Analyze timing quality and gap statistics from NPZ archives.

Usage:
    python3 scripts/analyze_timing.py --date 20251115 --data-root /tmp/grape-test
    python3 scripts/analyze_timing.py --date 20251115 --channel "WWV 10 MHz" --data-root /tmp/grape-test
    python3 scripts/analyze_timing.py --date 20251115 --export gaps.json --data-root /tmp/grape-test
"""

import argparse
import json
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import sys

# CRITICAL: Use centralized path API
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.signal_recorder.paths import get_paths, GRAPEPaths

def load_time_snap_history(state_file: Path):
    """Load time_snap history from state file."""
    if not state_file.exists():
        return None
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        return {
            'current': state.get('time_snap'),
            'history': state.get('time_snap_history', [])
        }
    except Exception as e:
        print(f"Warning: Failed to load {state_file}: {e}")
        return None


def analyze_npz_file(npz_path: Path):
    """Extract timing and gap info from a single NPZ file."""
    try:
        data = np.load(npz_path)
        
        # Extract metadata
        info = {
            'filename': npz_path.name,
            'rtp_timestamp': int(data['rtp_timestamp']),
            'sample_rate': int(data['sample_rate']),
            'samples': len(data['iq']),
            'gaps_count': int(data.get('gaps_count', 0)),
            'gaps_filled': int(data.get('gaps_filled', 0)),
            'packets_received': int(data.get('packets_received', 0)),
            'packets_expected': int(data.get('packets_expected', 0)),
            'unix_timestamp': float(data.get('unix_timestamp', 0)),
        }
        
        # Calculate completeness
        if info['packets_expected'] > 0:
            info['completeness'] = info['packets_received'] / info['packets_expected']
        else:
            info['completeness'] = 1.0 if info['gaps_count'] == 0 else 0.0
        
        return info
    except Exception as e:
        print(f"Warning: Failed to analyze {npz_path.name}: {e}")
        return None


def format_timestamp(ts):
    """Format Unix timestamp as ISO string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def print_time_snap_info(channel_name: str, time_snap_data: dict):
    """Print time_snap current and history."""
    print("\n" + "="*70)
    print(f"TIME_SNAP HISTORY - {channel_name}")
    print("="*70)
    
    if not time_snap_data:
        print("❌ No time_snap data available")
        return
    
    current = time_snap_data.get('current')
    if current:
        print(f"\n📍 CURRENT:")
        print(f"   RTP:    {current['rtp_timestamp']:,}")
        print(f"   UTC:    {format_timestamp(current['utc_timestamp'])}")
        print(f"   Source: {current['source']}")
        print(f"   Rate:   {current['sample_rate']:,} Hz")
    
    history = time_snap_data.get('history', [])
    if history:
        print(f"\n📜 HISTORY ({len(history)} entries):")
        for i, snap in enumerate(reversed(history[-5:])):  # Show last 5
            print(f"   {i+1}. {format_timestamp(snap['utc_timestamp'])} "
                  f"(RTP: {snap['rtp_timestamp']:,}, {snap['source']})")


def print_gap_analysis(channel_name: str, npz_files: list):
    """Analyze and print gap statistics."""
    print("\n" + "="*70)
    print(f"GAP ANALYSIS - {channel_name}")
    print("="*70)
    
    total_files = len(npz_files)
    total_gaps = 0
    total_samples_filled = 0
    total_packets_rx = 0
    total_packets_expected = 0
    files_with_gaps = 0
    
    # Hourly breakdown
    hourly_gaps = defaultdict(lambda: {'count': 0, 'samples': 0, 'files': 0})
    
    for info in npz_files:
        if not info:
            continue
        
        total_gaps += info['gaps_count']
        total_samples_filled += info['gaps_filled']
        total_packets_rx += info['packets_received']
        total_packets_expected += info['packets_expected']
        
        if info['gaps_count'] > 0:
            files_with_gaps += 1
        
        # Extract hour from filename: 20251115T023400Z
        try:
            hour = int(info['filename'][9:11])
            hourly_gaps[hour]['count'] += info['gaps_count']
            hourly_gaps[hour]['samples'] += info['gaps_filled']
            hourly_gaps[hour]['files'] += 1
        except:
            pass
    
    # Overall stats
    completeness = 100.0 if total_packets_expected == 0 else \
                   (total_packets_rx / total_packets_expected * 100)
    
    print(f"\n📊 OVERALL STATISTICS:")
    print(f"   Total files:      {total_files:,}")
    print(f"   Files with gaps:  {files_with_gaps:,} ({files_with_gaps/total_files*100:.1f}%)")
    print(f"   Total gaps:       {total_gaps:,}")
    print(f"   Samples filled:   {total_samples_filled:,}")
    print(f"   Completeness:     {completeness:.2f}%")
    print(f"   Packets RX:       {total_packets_rx:,}/{total_packets_expected:,}")
    
    # Quality grade
    if completeness >= 99.9:
        grade = "A+"
    elif completeness >= 99.5:
        grade = "A"
    elif completeness >= 99.0:
        grade = "B"
    elif completeness >= 95.0:
        grade = "C"
    else:
        grade = "F"
    
    print(f"   Quality Grade:    {grade}")
    
    # Hourly breakdown
    if hourly_gaps:
        print(f"\n⏰ HOURLY BREAKDOWN:")
        print(f"   Hour │ Gaps │ Samples │ Files")
        print(f"   ─────┼──────┼─────────┼──────")
        
        for hour in range(24):
            if hour in hourly_gaps:
                h = hourly_gaps[hour]
                bar = "█" * min(int(h['count'] / 5), 20)
                print(f"   {hour:02d}:xx│ {h['count']:4d} │ {h['samples']:7d} │ {h['files']:4d} {bar}")


def print_timeline_chart(channel_name: str, npz_files: list):
    """Print a simple timeline chart of data quality."""
    print("\n" + "="*70)
    print(f"COMPLETENESS TIMELINE - {channel_name}")
    print("="*70)
    
    # Group by hour
    hourly_quality = defaultdict(list)
    
    for info in npz_files:
        if not info:
            continue
        try:
            hour = int(info['filename'][9:11])
            hourly_quality[hour].append(info['completeness'])
        except:
            pass
    
    print("\n   Hour │ Quality")
    print("   ─────┼────────────────────────────────────────────")
    
    for hour in range(24):
        if hour in hourly_quality:
            avg_completeness = np.mean(hourly_quality[hour]) * 100
            bar_len = int(avg_completeness / 2.5)  # Scale to ~40 chars
            
            if avg_completeness >= 99.9:
                bar = "▓" * bar_len
            elif avg_completeness >= 99.0:
                bar = "▒" * bar_len
            else:
                bar = "░" * bar_len
            
            print(f"   {hour:02d}:xx│ {bar} {avg_completeness:.1f}%")
        else:
            print(f"   {hour:02d}:xx│ (no data)")
    
    print("\n   ▓ >99.9%   ▒ 99.0-99.9%   ░ <99.0%")


def analyze_channel(paths: GRAPEPaths, channel_name: str, date_str: str, export_path: Path = None):
    """Analyze a single channel using centralized paths API."""
    # Use paths API to get archive directory
    npz_dir = paths.get_archive_dir(channel_name)
    
    if not npz_dir.exists():
        print(f"❌ Channel directory not found: {npz_dir}")
        return None
    
    pattern = f"{date_str}T*Z_*_iq.npz"
    npz_files = sorted(npz_dir.glob(pattern))
    
    if not npz_files:
        print(f"❌ No NPZ files found for {date_str}")
        return None
    
    print(f"\n🔍 Analyzing {len(npz_files)} files for {channel_name}...")
    
    # Analyze all files
    file_info = [analyze_npz_file(f) for f in npz_files]
    file_info = [f for f in file_info if f is not None]
    
    # Use paths API to get state file
    state_file = paths.get_analytics_state_file(channel_name)
    time_snap_data = load_time_snap_history(state_file)
    
    # Print analyses
    print_time_snap_info(channel_name, time_snap_data)
    print_gap_analysis(channel_name, file_info)
    print_timeline_chart(channel_name, file_info)
    
    # Export if requested
    if export_path:
        export_data = {
            'channel': channel_name,
            'date': date_str,
            'time_snap': time_snap_data,
            'files': file_info
        }
        with open(export_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        print(f"\n💾 Exported to: {export_path}")
    
    return file_info


def main():
    parser = argparse.ArgumentParser(description='Analyze timing and gap statistics')
    parser.add_argument('--date', type=str, required=True,
                        help='Date to analyze (YYYYMMDD)')
    parser.add_argument('--data-root', type=Path, required=True,
                        help='Data root directory')
    parser.add_argument('--channel', type=str,
                        help='Channel name (e.g., "WWV 10 MHz"). If omitted, analyzes all.')
    parser.add_argument('--export', type=Path,
                        help='Export results to JSON file')
    
    args = parser.parse_args()
    
    # Create centralized paths API instance
    paths = get_paths(args.data_root)
    
    # Verify archives exist
    archives_root = paths.data_root / 'archives'
    if not archives_root.exists():
        print(f"❌ Archives directory not found: {archives_root}")
        sys.exit(1)
    
    print("="*70)
    print("GRAPE TIMING & GAP ANALYSIS")
    print("="*70)
    print(f"Date: {args.date}")
    print(f"Data root: {paths.data_root}")
    
    if args.channel:
        # Analyze single channel
        analyze_channel(paths, args.channel, args.date, args.export)
    else:
        # Analyze all channels using paths API discovery
        channels = paths.discover_channels()
        print(f"\nFound {len(channels)} channels")
        
        for channel_name in channels:
            analyze_channel(paths, channel_name, args.date)
            print("\n")
    
    print("\n" + "="*70)
    print("✅ Analysis complete")
    print("="*70)


if __name__ == '__main__':
    main()
