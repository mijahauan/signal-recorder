#!/usr/bin/env python3
"""
Simple spectrogram generator for simplified grape-recorder architecture.
Reads 10 Hz decimated files from products/{CHANNEL}/decimated/, generates PNGs.

Usage:
    python generate_spectrograms_from_raw.py --data-root /var/lib/grape-recorder --date 20251210
    python generate_spectrograms_from_raw.py --data-root /var/lib/grape-recorder --date 20251210 --grid EM38ww
"""

import numpy as np
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import argparse
import logging
from scipy import signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Transmitter coordinates (lat, lon)
WWV_LOCATION = (40.67805, -105.04030)   # Fort Collins, Colorado
WWVH_LOCATION = (21.9886, -159.7642)    # Kekaha, Kauai, Hawaii
CHU_LOCATION = (45.2950, -75.7550)      # Ottawa, Canada


def grid_to_latlon(grid: str):
    """Convert Maidenhead grid square to latitude/longitude."""
    grid = grid.upper()
    if len(grid) < 4:
        return None, None
    
    lon = (ord(grid[0]) - ord('A')) * 20 - 180
    lat = (ord(grid[1]) - ord('A')) * 10 - 90
    lon += int(grid[2]) * 2
    lat += int(grid[3]) * 1
    
    if len(grid) >= 6:
        lon += (ord(grid[4]) - ord('A')) * (2/24)
        lat += (ord(grid[5]) - ord('A')) * (1/24)
        lon += 1/24
        lat += 1/48
    else:
        lon += 1
        lat += 0.5
    
    return lat, lon


def calculate_midpoint(lat1, lon1, lat2, lon2):
    """Calculate geographic midpoint between two points."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    
    x1 = math.cos(lat1_r) * math.cos(lon1_r)
    y1 = math.cos(lat1_r) * math.sin(lon1_r)
    z1 = math.sin(lat1_r)
    x2 = math.cos(lat2_r) * math.cos(lon2_r)
    y2 = math.cos(lat2_r) * math.sin(lon2_r)
    z2 = math.sin(lat2_r)
    
    x, y, z = (x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2
    lon = math.atan2(y, x)
    lat = math.atan2(z, math.sqrt(x*x + y*y))
    
    return math.degrees(lat), math.degrees(lon)


def solar_elevation(dt, lat, lon):
    """Calculate solar elevation angle for given time and location (NOAA algorithm)."""
    a = (14 - dt.month) // 12
    y = dt.year + 4800 - a
    m = dt.month + 12 * a - 3
    jd = dt.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    jd = jd + (dt.hour - 12) / 24 + dt.minute / 1440 + dt.second / 86400
    
    t = (jd - 2451545.0) / 36525.0
    L0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    M = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    M_rad = math.radians(M)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    
    C = (math.sin(M_rad) * (1.914602 - t * (0.004817 + 0.000014 * t)) +
         math.sin(2 * M_rad) * (0.019993 - 0.000101 * t) +
         math.sin(3 * M_rad) * 0.000289)
    
    sun_lon = L0 + C
    omega = 125.04 - 1934.136 * t
    apparent_lon = sun_lon - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    
    obliq_mean = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliq_corr = obliq_mean + 0.00256 * math.cos(math.radians(omega))
    obliq_corr_rad = math.radians(obliq_corr)
    
    sin_decl = math.sin(obliq_corr_rad) * math.sin(math.radians(apparent_lon))
    decl = math.degrees(math.asin(sin_decl))
    decl_rad = math.radians(decl)
    
    var_y = math.tan(obliq_corr_rad / 2) ** 2
    L0_rad = math.radians(L0)
    eq_time = 4 * math.degrees(
        var_y * math.sin(2 * L0_rad) - 2 * e * math.sin(M_rad) +
        4 * e * var_y * math.sin(M_rad) * math.cos(2 * L0_rad) -
        0.5 * var_y * var_y * math.sin(4 * L0_rad) - 1.25 * e * e * math.sin(2 * M_rad)
    )
    
    time_offset = eq_time + 4 * lon
    true_solar_time = (dt.hour * 60 + dt.minute + dt.second / 60 + time_offset) % 1440
    hour_angle = true_solar_time / 4 - 180 if true_solar_time >= 0 else true_solar_time / 4 + 180
    hour_angle_rad = math.radians(hour_angle)
    
    lat_rad = math.radians(lat)
    cos_zenith = (math.sin(lat_rad) * math.sin(decl_rad) +
                  math.cos(lat_rad) * math.cos(decl_rad) * math.cos(hour_angle_rad))
    cos_zenith = max(-1, min(1, cos_zenith))
    
    return 90 - math.degrees(math.acos(cos_zenith))


def get_solar_curve(date_str, rx_lat, rx_lon, tx_location):
    """Calculate solar elevation curve at path midpoint for entire day."""
    mid_lat, mid_lon = calculate_midpoint(rx_lat, rx_lon, tx_location[0], tx_location[1])
    
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    
    hours = []
    elevations = []
    
    # Calculate elevation every 10 minutes
    for minute in range(0, 1440, 10):
        dt = datetime(year, month, day, minute // 60, minute % 60, 0)
        elev = solar_elevation(dt, mid_lat, mid_lon)
        hours.append(minute / 60)
        elevations.append(elev)
    
    return np.array(hours), np.array(elevations)

# Sample rate for decimated files
SAMPLE_RATE = 10  # 10 Hz decimated
SAMPLES_PER_DAY = SAMPLE_RATE * 86400  # 864,000 samples/day

# Channel frequencies
CHANNELS = [
    ('WWV 2.5 MHz', 2500000),
    ('CHU 3.33 MHz', 3330000),
    ('WWV 5 MHz', 5000000),
    ('CHU 7.85 MHz', 7850000),
    ('WWV 10 MHz', 10000000),
    ('CHU 14.67 MHz', 14670000),
    ('WWV 15 MHz', 15000000),
    ('WWV 20 MHz', 20000000),
    ('WWV 25 MHz', 25000000),
]


def channel_name_to_dir(name: str) -> str:
    """Convert channel name to directory format."""
    return name.replace(' ', '_')


def load_decimated_file(data_root: Path, channel_name: str, date_str: str) -> tuple:
    """Load decimated 10 Hz file for a channel and date."""
    channel_dir = channel_name_to_dir(channel_name)
    
    # Path to decimated file
    decimated_path = data_root / 'products' / channel_dir / 'decimated' / f'{date_str}.bin'
    meta_path = data_root / 'products' / channel_dir / 'decimated' / f'{date_str}_meta.json'
    
    if not decimated_path.exists():
        logger.warning(f"Decimated file not found: {decimated_path}")
        return None, None
    
    # Load IQ data
    data = np.fromfile(decimated_path, dtype=np.complex64)
    logger.info(f"Loaded {len(data)} samples from {decimated_path}")
    
    # Load metadata if available
    meta = None
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
    
    return data, meta


def generate_spectrogram(data: np.ndarray, channel_name: str, date_str: str, 
                        output_path: Path, grid: str = '', lat: float = None, lon: float = None):
    """Generate spectrogram PNG from 10 Hz decimated data with solar overlay."""
    if data is None or len(data) == 0:
        logger.warning(f"No data for {channel_name}")
        return None
    
    # Calculate magnitude and power in dB
    mag = np.abs(data)
    nonzero_mag = mag[mag > 0]
    if len(nonzero_mag) == 0:
        logger.warning(f"No non-zero data for {channel_name}")
        return None
    
    # Use dBFS (dB relative to full scale = 1.0 for normalized float)
    # Replace zeros with NaN to avoid -inf in plots
    mag_safe = np.where(mag > 1e-10, mag, np.nan)
    power_db = 20 * np.log10(mag_safe)
    
    # Time axis in hours - determine actual data extent
    hours = np.arange(len(data)) / SAMPLE_RATE / 3600
    
    # Create figure with GridSpec: 2 rows, 2 columns (main plots + colorbar space)
    # This ensures both main axes have identical widths
    fig = plt.figure(figsize=(14, 8))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 3], width_ratios=[50, 1], 
                          hspace=0.05, wspace=0.02)
    
    # Main plot axes (left column) - SHARE X-AXIS
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
    
    # Colorbar axis (right column, bottom row only)
    cax = fig.add_subplot(gs[1, 1])
    
    # Power plot - smooth with rolling average
    window = min(600, len(power_db) // 10)
    if window > 1:
        power_smooth = np.convolve(power_db, np.ones(window)/window, mode='same')
    else:
        power_smooth = power_db
    
    ax1.plot(hours, power_smooth, 'b-', linewidth=0.5, alpha=0.8)
    ax1.set_ylabel('Power (dB)')
    
    # Y-axis: use tight range around the data (filter NaN and Inf)
    valid_power = power_smooth[np.isfinite(power_smooth)]
    if len(valid_power) > 0:
        p_min = np.percentile(valid_power, 1) - 3
        p_max = np.percentile(valid_power, 99) + 3
        ax1.set_ylim(p_min, p_max)
    
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f'{channel_name} - {date_str} (10 Hz decimated)')
    ax1.tick_params(labelbottom=False)  # Hide x labels on top plot
    
    # Spectrogram - use PSD with Blackman window for sharp carrier definition
    nperseg = min(600, len(data) // 20)  # 60 seconds = 0.017 Hz resolution
    if nperseg >= 10:
        # Blackman window: excellent sidelobe suppression (-58 dB) for carrier signals
        f, t, Sxx = signal.spectrogram(data, fs=SAMPLE_RATE, nperseg=nperseg, 
                                        noverlap=nperseg*7//8, mode='psd',
                                        window='blackman', return_onesided=False)
        t_hours = t / 3600
        
        # Sort frequencies for proper display (complex data gives negative freqs)
        freq_order = np.argsort(f)
        f_sorted = f[freq_order]
        Sxx_sorted = Sxx[freq_order, :]
        
        # Convert to dB (absolute power spectral density)
        Sxx_db = 10 * np.log10(Sxx_sorted + 1e-20)
        
        # Data-adaptive dynamic range: use percentiles for contrast
        flat_db = Sxx_db.flatten()
        valid_db = flat_db[np.isfinite(flat_db)]
        if len(valid_db) > 0:
            # 1st-99th percentile for good contrast
            vmin = np.percentile(valid_db, 1)
            vmax = np.percentile(valid_db, 99)
            # Ensure at least 40 dB range
            if vmax - vmin < 40:
                mid = (vmax + vmin) / 2
                vmin, vmax = mid - 20, mid + 20
        else:
            vmin, vmax = -200, -100
        
        im = ax2.pcolormesh(t_hours, f_sorted, Sxx_db, 
                           shading='auto', cmap='viridis', vmin=vmin, vmax=vmax)
        ax2.set_ylabel('Frequency Offset (Hz)')
        ax2.set_xlabel('Time (UTC hours)')
        ax2.set_ylim(-SAMPLE_RATE/2, SAMPLE_RATE/2)  # Full bandwidth: -5 to +5 Hz
        plt.colorbar(im, cax=cax, label='Power (dB/Hz)')
    else:
        ax2.text(0.5, 0.5, 'Insufficient data for spectrogram', 
                ha='center', va='center', transform=ax2.transAxes)
    
    # CRITICAL: Set identical x-limits on both axes AFTER all plotting
    ax1.set_xlim(0, 24)
    ax2.set_xlim(0, 24)
    
    # Add solar elevation curve overlay if coordinates provided
    if lat is not None and lon is not None:
        # Determine which transmitters to show based on channel
        # CHU-only: 3.33, 7.85, 14.67 MHz
        # WWV-only: 20, 25 MHz
        # Shared (WWV + WWVH): 2.5, 5, 10, 15 MHz
        
        transmitters = []
        if 'CHU' in channel_name:
            transmitters = [('CHU', CHU_LOCATION, 'lime')]
        elif '20 MHz' in channel_name or '25 MHz' in channel_name:
            transmitters = [('WWV', WWV_LOCATION, 'orange')]
        else:
            # Shared frequencies: 2.5, 5, 10, 15 MHz - show both WWV and WWVH
            transmitters = [
                ('WWV', WWV_LOCATION, 'orange'),
                ('WWVH', WWVH_LOCATION, 'cyan')
            ]
        
        # Create twin axis for solar elevation on power plot
        ax1_solar = ax1.twinx()
        ax1_solar.set_ylabel('Solar Elevation (°)', fontsize=9)
        ax1_solar.set_ylim(-90, 90)
        ax1_solar.axhline(y=0, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
        
        for tx_name, tx_loc, color in transmitters:
            hours, elevations = get_solar_curve(date_str, lat, lon, tx_loc)
            
            # Plot solar elevation curve on power plot (twin axis)
            ax1_solar.plot(hours, elevations, color=color, linestyle='-', linewidth=1.5,
                          alpha=0.7, label=f'{tx_name} Solar Elev')
            
            # Add sunrise/sunset markers where elevation crosses 0
            for i in range(1, len(elevations)):
                if elevations[i-1] < 0 and elevations[i] >= 0:
                    # Sunrise
                    ax1.axvline(x=hours[i], color=color, linestyle=':', linewidth=1, alpha=0.6)
                    ax2.axvline(x=hours[i], color=color, linestyle=':', linewidth=1, alpha=0.6)
                elif elevations[i-1] >= 0 and elevations[i] < 0:
                    # Sunset
                    ax1.axvline(x=hours[i], color=color, linestyle=':', linewidth=1, alpha=0.6)
                    ax2.axvline(x=hours[i], color=color, linestyle=':', linewidth=1, alpha=0.6)
            
            # Find max elevation
            max_elev = np.max(elevations)
            max_hour = hours[np.argmax(elevations)]
            logger.info(f"  {tx_name} path: max elev={max_elev:.1f}° at {max_hour:.1f}h UTC")
        
        # Add legend to solar axis
        if transmitters:
            ax1_solar.legend(loc='upper left', fontsize=7)
    
    # Save (no tight_layout - GridSpec handles spacing)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=100, bbox_inches='tight')
    plt.close()
    
    logger.info(f"✅ Generated {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Generate spectrograms from 10 Hz decimated files')
    parser.add_argument('--data-root', type=Path, default=Path('/var/lib/grape-recorder'),
                       help='Root data directory')
    parser.add_argument('--date', type=str, default=datetime.now(timezone.utc).strftime('%Y%m%d'),
                       help='Date to process (YYYYMMDD)')
    parser.add_argument('--channel', type=str, help='Single channel to process')
    parser.add_argument('--grid', type=str, default='', help='Grid square for solar overlay (e.g. EM38ww)')
    parser.add_argument('--output-dir', type=Path, help='Output directory (default: data_root/products)')
    
    args = parser.parse_args()
    
    output_base = args.output_dir or args.data_root / 'products'
    
    # Parse grid square to get receiver coordinates for solar overlay
    rx_lat, rx_lon = None, None
    if args.grid:
        rx_lat, rx_lon = grid_to_latlon(args.grid)
        if rx_lat is not None:
            logger.info(f"Solar overlay enabled: grid={args.grid} → lat={rx_lat:.4f}, lon={rx_lon:.4f}")
        else:
            logger.warning(f"Could not parse grid square: {args.grid}")
    
    channels_to_process = [(args.channel, 0)] if args.channel else CHANNELS
    
    logger.info(f"Generating spectrograms for {args.date}")
    logger.info(f"Data root: {args.data_root}")
    logger.info(f"Output: {output_base}")
    
    results = {}
    for channel_name, freq in channels_to_process:
        logger.info(f"Processing {channel_name}...")
        
        # Load decimated file
        data, meta = load_decimated_file(args.data_root, channel_name, args.date)
        if data is None:
            logger.warning(f"No decimated data found for {channel_name}")
            results[channel_name] = None
            continue
        
        # Generate spectrogram with solar overlay
        channel_dir = channel_name_to_dir(channel_name)
        output_path = output_base / channel_dir / 'spectrograms' / f'{args.date}_spectrogram.png'
        
        result = generate_spectrogram(data, channel_name, args.date, output_path, 
                                      grid=args.grid, lat=rx_lat, lon=rx_lon)
        results[channel_name] = result
    
    # Summary
    success = sum(1 for v in results.values() if v is not None)
    logger.info(f"\nGenerated {success}/{len(results)} spectrograms")


if __name__ == '__main__':
    main()
