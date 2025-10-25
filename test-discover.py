#!/Users/mjh/Sync/GitHub/signal-recorder/venv/bin/python
"""
Simple test discover script for signal-recorder web UI testing
"""

import sys
import toml
from pathlib import Path

def main():
    radiod_addr = sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1'
    
    print(f"Discovering channels from {radiod_addr}")
    print("SSRC      Frequency  Rate   Preset  SNR    Address")
    print("--------- ---------- ------ ------- ------ ------------------")
    
    # Try to load config and show channels
    config_file = '../config/grape-S000171.toml'
    try:
        with open(config_file, 'r') as f:
            config = toml.load(f)
        
        if config and 'recorder' in config and 'channels' in config['recorder']:
            for channel in config['recorder']['channels']:
                ssrc = channel.get('ssrc', 'N/A')
                freq = channel.get('frequency_hz', 0) / 1000000
                rate = channel.get('sample_rate', 12000)
                preset = channel.get('preset', 'iq')
                snr = '-inf'
                address = radiod_addr
                
                print(f"{ssrc">8"} {freq">8.2f"}MHz {rate">5"} {preset">6"} {snr">5"} {address}")
    except Exception as e:
        print(f"Error loading config: {e}")
        # Fallback: show some test channels
        test_channels = [
            (2500000, 2.5, 12000, 'iq'),
            (5000000, 5.0, 12000, 'iq'),
            (10000000, 10.0, 12000, 'iq')
        ]
        
        for ssrc, freq, rate, preset in test_channels:
            print(f"{ssrc">8"} {freq">8.2f"}MHz {rate">5"} {preset">6"} -inf   {radiod_addr}")

if __name__ == '__main__':
    main()
