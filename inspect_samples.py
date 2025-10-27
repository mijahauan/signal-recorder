#!/usr/bin/env python3
"""
Inspect live sample data from the daily buffers to validate data quality.
This reads from the daemon's running buffers to check sample continuity and quality.
"""

import sys
import json
import time
from pathlib import Path

def inspect_daemon_stats():
    """Read daemon stats and report on sample quality"""
    
    stats_file = Path('/tmp/signal-recorder-stats.json')
    
    if not stats_file.exists():
        print("❌ Daemon stats file not found. Is the daemon running?")
        return False
    
    # Read current stats
    with open(stats_file) as f:
        stats = json.load(f)
    
    if not stats.get('running', False):
        print("❌ Daemon not running")
        return False
    
    print("="*70)
    print("GRAPE Recorder Sample Quality Report")
    print("="*70)
    print(f"Recording Duration: {stats.get('recording_duration_sec', 0)} seconds")
    print(f"Total Packets: {stats.get('total_packets_received', 0):,}")
    print(f"Channels: {stats.get('channels', 0)}")
    print()
    
    all_good = True
    
    for ssrc, rec in stats.get('recorders', {}).items():
        channel = rec['channel_name']
        samples = rec['samples_received']
        expected = rec['expected_samples']
        completeness = rec['completeness_pct']
        rate = rec['samples_per_sec']
        packet_loss = rec['packet_loss_pct']
        
        # Determine status
        status_icon = "🟢"
        issues = []
        
        if completeness < 95:
            status_icon = "🔴"
            issues.append(f"Low completeness ({completeness:.1f}%)")
            all_good = False
        elif completeness < 99:
            status_icon = "🟡"
            issues.append(f"Moderate completeness ({completeness:.1f}%)")
        
        if packet_loss > 0.1:
            status_icon = "🔴"
            issues.append(f"Packet loss ({packet_loss:.2f}%)")
            all_good = False
        
        if abs(rate - 10.0) > 0.5:
            status_icon = "🔴"
            issues.append(f"Incorrect sample rate ({rate:.1f}/s, expected 10.0/s)")
            all_good = False
        
        print(f"{status_icon} {channel}")
        print(f"   Samples: {samples:,} / {expected:,} ({completeness:.1f}%)")
        print(f"   Rate: {rate:.1f} samples/sec (target: 10.0/s)")
        print(f"   Packet loss: {packet_loss:.2f}%")
        
        if issues:
            print(f"   ⚠️  Issues: {', '.join(issues)}")
        print()
    
    print("="*70)
    if all_good:
        print("✅ All channels operating normally!")
        print("   Data pipeline is working correctly.")
        print("   Digital RF files will be written at midnight UTC.")
    else:
        print("⚠️  Some channels have issues (see above)")
    print("="*70)
    
    return all_good

def watch_samples(interval_sec=10):
    """
    Watch sample accumulation over time to verify continuity
    """
    print("Watching sample accumulation (Ctrl-C to stop)...")
    print()
    
    previous = {}
    
    try:
        while True:
            stats_file = Path('/tmp/signal-recorder-stats.json')
            
            if not stats_file.exists():
                print("Daemon stats not available, waiting...")
                time.sleep(interval_sec)
                continue
            
            with open(stats_file) as f:
                stats = json.load(f)
            
            current_time = stats.get('recording_duration_sec', 0)
            
            print(f"\n--- {current_time}s ---")
            
            for ssrc, rec in stats.get('recorders', {}).items():
                channel = rec['channel_name']
                samples = rec['samples_received']
                
                if ssrc in previous:
                    delta = samples - previous[ssrc]
                    expected_delta = interval_sec * 10
                    pct = (delta / expected_delta * 100) if expected_delta > 0 else 0
                    
                    status = "✅" if abs(pct - 100) < 5 else "⚠️"
                    print(f"{status} {channel:20s}: +{delta:4d} samples "
                          f"(expected {expected_delta:4d}, {pct:5.1f}%)")
                else:
                    print(f"   {channel:20s}: {samples:5d} samples (baseline)")
                
                previous[ssrc] = samples
            
            time.sleep(interval_sec)
            
    except KeyboardInterrupt:
        print("\n\nStopped monitoring")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Inspect GRAPE recorder sample quality')
    parser.add_argument('--watch', action='store_true',
                       help='Continuously watch sample accumulation')
    parser.add_argument('--interval', type=int, default=10,
                       help='Watch interval in seconds (default: 10)')
    
    args = parser.parse_args()
    
    if args.watch:
        watch_samples(args.interval)
    else:
        inspect_daemon_stats()
