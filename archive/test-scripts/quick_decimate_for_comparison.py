#!/usr/bin/env python3
"""
Quick decimation of wide channel NPZ files to 10 Hz for spectrogram comparison
This is a simplified version for testing - the full analytics service does more.
"""

import numpy as np
from pathlib import Path
from scipy import signal as scipy_signal
import sys
from datetime import datetime

def decimate_channel(channel_name: str, date_str: str, data_root: Path):
    """Decimate a single channel's data for one date"""
    
    # Find source data: data/YYYYMMDD/STATION/DOY/CHANNEL/
    date_path = data_root / 'data' / date_str
    
    channel_dir = channel_name.replace(' ', '_')
    npz_files = []
    
    # Search for channel directory
    if date_path.exists():
        for station_dir in date_path.iterdir():
            if not station_dir.is_dir():
                continue
            for doy_dir in station_dir.iterdir():
                if not doy_dir.is_dir():
                    continue
                channel_path = doy_dir / channel_dir
                if channel_path.exists():
                    npz_files = sorted(channel_path.glob(f'{date_str}*_iq.npz'))
                    break
            if npz_files:
                break
    
    if not npz_files:
        print(f"  No data found for {channel_name}")
        return False
    
    print(f"  Found {len(npz_files)} NPZ files for {channel_name}")
    
    # Create output directory
    output_dir = data_root / 'analytics' / channel_dir / 'decimated'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Decimate each file: 16 kHz → 10 Hz (factor of 1600)
    for npz_file in npz_files:
        try:
            data = np.load(npz_file)
            iq_16k = data['iq']
            
            # Decimate in stages to avoid filter artifacts
            # 16000 Hz → 400 Hz (factor 40) → 10 Hz (factor 40)
            iq_400 = scipy_signal.decimate(iq_16k, 40, ftype='fir', zero_phase=True)
            iq_10 = scipy_signal.decimate(iq_400, 40, ftype='fir', zero_phase=True)
            
            # Save with _10hz suffix
            output_file = output_dir / npz_file.name.replace('_iq.npz', '_iq_10hz.npz')
            np.savez_compressed(output_file, iq=iq_10)
            
        except Exception as e:
            print(f"    Error processing {npz_file.name}: {e}")
            continue
    
    print(f"  ✅ Decimated {len(npz_files)} files for {channel_name}")
    return True


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y%m%d')
    data_root = Path('/tmp/grape-test')
    
    print(f"Quick decimation for date: {date_str}")
    print(f"Data root: {data_root}\n")
    
    # Decimate all wide channels (non-carrier)
    channels = [
        'WWV 2.5 MHz', 'WWV 5 MHz', 'WWV 10 MHz', 'WWV 15 MHz', 'WWV 20 MHz', 'WWV 25 MHz',
        'CHU 3.33 MHz', 'CHU 7.85 MHz', 'CHU 14.67 MHz'
    ]
    
    success_count = 0
    for channel in channels:
        if decimate_channel(channel, date_str, data_root):
            success_count += 1
    
    print(f"\n✅ Decimated {success_count}/{len(channels)} channels")
    print(f"Output: {data_root}/analytics/[channel]/decimated/")


if __name__ == '__main__':
    main()
