#!/usr/bin/env python3
"""
Plot WWV timing variations over time to visualize ionospheric propagation effects.

Shows 24-hour patterns and differences between frequencies.
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path

def plot_wwv_timing():
    """Plot WWV timing data from CSV"""
    
    # Load data
    csv_path = Path(__file__).parent / 'logs' / 'wwv_timing.csv'
    
    if not csv_path.exists():
        print(f"No timing data found at {csv_path}")
        print("Waiting for WWV tone detections...")
        return
    
    df = pd.read_csv(csv_path)
    
    if len(df) == 0:
        print("No timing data yet. Waiting for WWV tone detections...")
        return
    
    # Convert timestamp to datetime
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    
    # Create figure with subplots
    fig, axes = plt.subplots(2, 1, figsize=(15, 10))
    
    # Plot 1: Timing error vs time for each frequency
    ax1 = axes[0]
    for freq in sorted(df['frequency_mhz'].unique()):
        freq_data = df[df['frequency_mhz'] == freq]
        ax1.plot(freq_data['datetime'], freq_data['timing_error_ms'], 
                marker='o', markersize=3, label=f'{freq} MHz', alpha=0.7)
    
    ax1.set_xlabel('Time (UTC)')
    ax1.set_ylabel('Timing Error (ms)')
    ax1.set_title('WWV Tone Timing Variations by Frequency')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
    
    # Plot 2: Distribution of timing errors
    ax2 = axes[1]
    for freq in sorted(df['frequency_mhz'].unique()):
        freq_data = df[df['frequency_mhz'] == freq]
        ax2.hist(freq_data['timing_error_ms'], bins=30, alpha=0.5, label=f'{freq} MHz')
    
    ax2.set_xlabel('Timing Error (ms)')
    ax2.set_ylabel('Count')
    ax2.set_title('Distribution of Timing Errors')
    ax2.legend(loc='best')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save plot
    output_path = Path(__file__).parent / 'logs' / 'wwv_timing_plot.png'
    plt.savefig(output_path, dpi=150)
    print(f"✅ Plot saved to {output_path}")
    
    # Print statistics
    print("\n=== WWV Timing Statistics ===")
    print(f"Total detections: {len(df)}")
    print(f"Time range: {df['datetime'].min()} to {df['datetime'].max()}")
    print("\nBy Frequency:")
    for freq in sorted(df['frequency_mhz'].unique()):
        freq_data = df[df['frequency_mhz'] == freq]
        print(f"  {freq:5.1f} MHz: {len(freq_data):4d} detections, "
              f"error = {freq_data['timing_error_ms'].mean():+6.2f} ± {freq_data['timing_error_ms'].std():5.2f} ms")
    
    # Show plot
    plt.show()

if __name__ == '__main__':
    plot_wwv_timing()
