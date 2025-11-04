#!/usr/bin/env python3
"""
Generate Quality Report for GRAPE Data

Creates visualizations and analysis of data quality metrics.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages


def load_quality_data(analytics_dir: Path, date_str: str, channel_name: str):
    """Load quality metrics for a channel/date"""
    
    channel_clean = channel_name.replace(' ', '_')
    base_path = analytics_dir / "quality" / date_str
    
    # Load minute metrics CSV
    minute_csv = base_path / f"{channel_clean}_minute_quality_{date_str}.csv"
    if not minute_csv.exists():
        print(f"ERROR: Minute metrics not found: {minute_csv}", file=sys.stderr)
        return None, None, None
    
    minutes_df = pd.read_csv(minute_csv)
    minutes_df['minute_start'] = pd.to_datetime(minutes_df['minute_start'])
    
    # Load discontinuities CSV
    disc_csv = base_path / f"{channel_clean}_discontinuities_{date_str}.csv"
    disc_df = None
    if disc_csv.exists():
        disc_df = pd.read_csv(disc_csv)
        disc_df['timestamp_utc'] = pd.to_datetime(disc_df['timestamp_utc'], unit='s')
    
    # Load daily summary JSON
    summary_json = base_path / f"{channel_clean}_daily_summary_{date_str}.json"
    summary = None
    if summary_json.exists():
        with open(summary_json, 'r') as f:
            summary = json.load(f)
    
    return minutes_df, disc_df, summary


def plot_completeness_timeline(ax, minutes_df):
    """Plot data completeness over time"""
    ax.plot(minutes_df['minute_start'], minutes_df['completeness_pct'], 
            linewidth=0.5, color='blue', alpha=0.7)
    ax.axhline(y=100, color='green', linestyle='--', alpha=0.5, label='100%')
    ax.axhline(y=99, color='orange', linestyle='--', alpha=0.5, label='99%')
    
    ax.set_xlabel('Time (UTC)')
    ax.set_ylabel('Completeness (%)')
    ax.set_title('Data Completeness Timeline')
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_ylim([98, 100.5])
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))


def plot_packet_loss(ax, minutes_df):
    """Plot packet loss over time"""
    # Only plot non-zero packet loss
    loss_data = minutes_df[minutes_df['packet_loss_pct'] > 0]
    
    if len(loss_data) > 0:
        ax.scatter(loss_data['minute_start'], loss_data['packet_loss_pct'],
                  s=10, color='red', alpha=0.6)
        ax.set_ylabel('Packet Loss (%)')
        ax.set_title('Packet Loss Events')
    else:
        ax.text(0.5, 0.5, 'No Packet Loss Detected\n(Perfect Recording!)',
               ha='center', va='center', transform=ax.transAxes,
               fontsize=14, color='green')
        ax.set_ylabel('Packet Loss (%)')
        ax.set_title('Packet Loss Events')
    
    ax.set_xlabel('Time (UTC)')
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))


def plot_wwv_timing(ax, minutes_df):
    """Plot WWV timing errors"""
    # Filter for WWV detections
    wwv_data = minutes_df[minutes_df['wwv_detected'] == True].copy()
    wwv_data['wwv_error_ms'] = pd.to_numeric(wwv_data['wwv_error_ms'], errors='coerce')
    wwv_data = wwv_data.dropna(subset=['wwv_error_ms'])
    
    if len(wwv_data) > 0:
        ax.scatter(wwv_data['minute_start'], wwv_data['wwv_error_ms'],
                  s=5, color='blue', alpha=0.5)
        ax.axhline(y=0, color='green', linestyle='-', alpha=0.7, label='Perfect')
        
        # Show ±5ms bounds
        ax.axhline(y=5, color='orange', linestyle='--', alpha=0.5)
        ax.axhline(y=-5, color='orange', linestyle='--', alpha=0.5)
        
        ax.set_ylabel('Timing Error (ms)')
        ax.set_title(f'WWV Timing Accuracy ({len(wwv_data)} detections)')
        ax.legend()
    else:
        ax.text(0.5, 0.5, 'No WWV Tone Detections\n(Not a WWV channel or detection disabled)',
               ha='center', va='center', transform=ax.transAxes,
               fontsize=12)
        ax.set_ylabel('Timing Error (ms)')
        ax.set_title('WWV Timing Accuracy')
    
    ax.set_xlabel('Time (UTC)')
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))


def plot_signal_power(ax, minutes_df):
    """Plot signal power over time"""
    power_data = minutes_df['signal_power_db'].astype(float)
    
    ax.plot(minutes_df['minute_start'], power_data,
           linewidth=0.5, color='purple', alpha=0.7)
    ax.set_xlabel('Time (UTC)')
    ax.set_ylabel('Signal Power (dB)')
    ax.set_title('Signal Power Timeline')
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))


def generate_summary_text(summary):
    """Generate text summary"""
    if not summary:
        return "No summary data available"
    
    text = f"""
DAILY QUALITY SUMMARY
=====================

Date: {summary.get('date_utc', 'N/A')}
Channel: {summary.get('channel_name', 'N/A')}
Frequency: {summary.get('frequency_hz', 0)/1e6:.2f} MHz

DATA COMPLETENESS
-----------------
Minutes Expected: {summary.get('minutes_expected', 1440)}
Minutes Recorded: {summary.get('minutes_recorded', 0)}
Minutes Missing: {summary.get('minutes_missing', 0)}
Completeness: {summary.get('data_completeness_percent', 0):.2f}%

GAP STATISTICS
--------------
Total Gaps: {summary.get('total_gaps', 0)}
Total Gap Duration: {summary.get('total_gap_duration_sec', 0):.1f} seconds
Longest Gap: {summary.get('longest_gap_sec', 0):.1f} seconds
  at: {summary.get('longest_gap_timestamp', 'N/A')}

RTP QUALITY
-----------
Packets Received: {summary.get('total_packets_received', 0):,}
Packets Dropped: {summary.get('total_packets_dropped', 0):,}
Packet Loss: {summary.get('packet_loss_percent', 0):.4f}%
RTP Resets: {summary.get('rtp_resets', 0)}

SIGNAL QUALITY
--------------
Mean Power: {summary.get('signal_power_mean_db', 0):.1f} dB
Power Std Dev: {summary.get('signal_power_std_db', 0):.1f} dB
"""
    
    # Add WWV timing if available
    if summary.get('wwv_detection_rate_percent', 0) > 0:
        text += f"""
WWV TIMING
----------
Detections Expected: {summary.get('wwv_detections_expected', 1440)}
Detections Successful: {summary.get('wwv_detections_successful', 0)}
Detection Rate: {summary.get('wwv_detection_rate_percent', 0):.1f}%
Mean Timing Error: {summary.get('wwv_timing_error_mean_ms', 0):+.2f} ms
Timing Std Dev: {summary.get('wwv_timing_error_std_ms', 0):.2f} ms
Max Timing Error: {summary.get('wwv_timing_error_max_ms', 0):+.2f} ms
"""
    
    return text


def generate_report(analytics_dir: Path, date_str: str, channel_name: str, output_pdf: Path):
    """Generate complete quality report PDF"""
    
    print(f"Generating quality report for {channel_name} on {date_str}...")
    
    # Load data
    minutes_df, disc_df, summary = load_quality_data(analytics_dir, date_str, channel_name)
    
    if minutes_df is None:
        print("ERROR: Could not load quality data", file=sys.stderr)
        return False
    
    # Create PDF
    with PdfPages(output_pdf) as pdf:
        # Page 1: Summary text
        fig = plt.figure(figsize=(8.5, 11))
        ax = fig.add_subplot(111)
        ax.axis('off')
        
        summary_text = generate_summary_text(summary)
        ax.text(0.1, 0.9, summary_text, transform=ax.transAxes,
               fontfamily='monospace', fontsize=10, verticalalignment='top')
        
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()
        
        # Page 2: Plots
        fig, axes = plt.subplots(4, 1, figsize=(11, 14))
        fig.suptitle(f'Quality Report: {channel_name} - {date_str}', fontsize=16, y=0.995)
        
        plot_completeness_timeline(axes[0], minutes_df)
        plot_packet_loss(axes[1], minutes_df)
        plot_wwv_timing(axes[2], minutes_df)
        plot_signal_power(axes[3], minutes_df)
        
        plt.tight_layout()
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()
        
        # Page 3: Discontinuities (if any)
        if disc_df is not None and len(disc_df) > 0:
            fig = plt.figure(figsize=(8.5, 11))
            ax = fig.add_subplot(111)
            ax.axis('off')
            
            disc_text = f"DISCONTINUITIES LOG\n{'='*50}\n\n"
            disc_text += f"Total Events: {len(disc_df)}\n\n"
            
            for idx, row in disc_df.head(20).iterrows():
                disc_text += f"{row['timestamp_utc']}: {row['type']}\n"
                disc_text += f"  Magnitude: {row['magnitude_samples']} samples ({row['magnitude_ms']} ms)\n"
                disc_text += f"  {row['explanation']}\n\n"
            
            if len(disc_df) > 20:
                disc_text += f"\n... and {len(disc_df) - 20} more events (see CSV for details)"
            
            ax.text(0.1, 0.9, disc_text, transform=ax.transAxes,
                   fontfamily='monospace', fontsize=9, verticalalignment='top')
            
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()
    
    print(f"✅ Report generated: {output_pdf}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate GRAPE quality report")
    parser.add_argument('--analytics-dir', type=Path, required=True, help='Analytics directory')
    parser.add_argument('--date', required=True, help='Date (YYYYMMDD)')
    parser.add_argument('--channel', required=True, help='Channel name')
    parser.add_argument('--output', type=Path, required=True, help='Output PDF file')
    
    args = parser.parse_args()
    
    success = generate_report(args.analytics_dir, args.date, args.channel, args.output)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
