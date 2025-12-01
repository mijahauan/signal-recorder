#!/usr/bin/env python3
"""
Show Quality Summary for GRAPE Recordings
Displays KA9Q timing architecture metrics
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
import csv

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from grape_recorder.quality_metrics import format_quality_summary, MinuteQualityMetrics


def load_minute_metrics_from_csv(csv_path: Path):
    """Load minute metrics from CSV file"""
    metrics = []
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse the row into a MinuteQualityMetrics object
            # This is simplified - in production you'd parse all fields
            metrics.append(row)
    
    return metrics


def show_hourly_summary(csv_files: list):
    """Show hourly summary across all channels"""
    print("\n" + "="*80)
    print("HOURLY QUALITY SUMMARY (KA9Q Timing Architecture)")
    print("="*80)
    
    all_grades = []
    all_drift = []
    total_resequenced = 0
    total_gaps = 0
    
    for csv_file in csv_files:
        channel_name = csv_file.stem.split('_minute_quality_')[0]
        
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            if not rows:
                continue
            
            # Calculate hourly stats
            grades = [r['quality_grade'] for r in rows if r.get('quality_grade')]
            grade_counts = {g: grades.count(g) for g in set(grades)}
            
            resequenced = sum(int(r.get('resequenced', 0)) for r in rows)
            gaps = sum(int(r.get('gaps', 0)) for r in rows)
            
            # WWV metrics
            wwv_detected_count = sum(1 for r in rows if r.get('wwv_detected') == 'True')
            drifts = [float(r['drift_ms']) for r in rows if r.get('drift_ms') and r['drift_ms']]
            
            print(f"\n📡 {channel_name}:")
            print(f"   Minutes: {len(rows)}")
            print(f"   Quality: {' '.join(f'{g}:{grade_counts.get(g, 0)}' for g in ['A', 'B', 'C', 'D', 'F'])}")
            
            if resequenced > 0:
                print(f"   Resequenced: {resequenced} packets")
            if gaps > 0:
                print(f"   Gaps: {gaps} events")
            
            if wwv_detected_count > 0:
                print(f"   WWV: {wwv_detected_count} detections")
                if drifts:
                    avg_drift = sum(drifts) / len(drifts)
                    print(f"   Avg drift: {avg_drift:+.1f} ms")
            
            all_grades.extend(grades)
            all_drift.extend(drifts)
            total_resequenced += resequenced
            total_gaps += gaps
    
    # Overall summary
    print(f"\n{'='*80}")
    print("OVERALL:")
    if all_grades:
        grade_pct = {g: (all_grades.count(g) / len(all_grades) * 100) for g in set(all_grades)}
        print(f"   Quality distribution:")
        for grade in ['A', 'B', 'C', 'D', 'F']:
            if grade in grade_pct:
                print(f"      {grade}: {grade_pct[grade]:.1f}%")
    
    print(f"   Total resequencing: {total_resequenced} packets")
    print(f"   Total gaps: {total_gaps} events")
    
    if all_drift:
        print(f"   Time_snap drift: {min(all_drift):+.1f} to {max(all_drift):+.1f} ms (avg: {sum(all_drift)/len(all_drift):+.1f})")
    
    print("="*80)


def main():
    parser = argparse.ArgumentParser(description='Show quality summary for GRAPE recordings')
    parser.add_argument('quality_dir', type=Path, help='Directory containing quality CSV files')
    parser.add_argument('--channel', help='Show specific channel only')
    parser.add_argument('--last', type=int, help='Show last N minutes')
    
    args = parser.parse_args()
    
    if not args.quality_dir.exists():
        print(f"Error: Directory not found: {args.quality_dir}")
        return 1
    
    # Find all minute quality CSV files
    csv_files = list(args.quality_dir.glob('*_minute_quality_*.csv'))
    
    if not csv_files:
        print(f"No quality CSV files found in {args.quality_dir}")
        return 1
    
    if args.channel:
        csv_files = [f for f in csv_files if args.channel in f.name]
    
    print(f"\nFound {len(csv_files)} quality files")
    
    # Show hourly summary
    show_hourly_summary(csv_files)
    
    # Show recent minutes if requested
    if args.last:
        print(f"\n\nLAST {args.last} MINUTES:")
        print("="*80)
        
        for csv_file in csv_files:
            channel_name = csv_file.stem.split('_minute_quality_')[0]
            
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)[-args.last:]
                
                for row in rows:
                    grade_emoji = {"A": "✅", "B": "✓", "C": "⚠️", "D": "❌", "F": "🔴"}.get(row.get('quality_grade', '?'), '?')
                    
                    print(f"\n{channel_name} @ {row['minute_start']}:")
                    print(f"   Quality: {grade_emoji} {row.get('quality_grade', '?')} ({row.get('quality_score', '?')})")
                    print(f"   Samples: {row.get('samples', '?')}/{row.get('completeness_pct', '?')}%")
                    print(f"   Loss: {row.get('packet_loss_pct', '0')}%")
                    
                    if row.get('drift_ms'):
                        print(f"   Drift: {row['drift_ms']} ms")
                    
                    if row.get('alerts'):
                        print(f"   ⚠️  {row['alerts']}")


if __name__ == '__main__':
    sys.exit(main())
