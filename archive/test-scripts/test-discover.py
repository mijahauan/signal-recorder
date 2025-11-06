#!/Users/mjh/Sync/GitHub/signal-recorder/venv/bin/python
"""
Simple test discover script for signal-recorder web UI testing
Outputs format matching real ka9q-radio discovery
"""

import sys

def main():
    radiod_addr = sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1'

    print(f"Discovering channels from {radiod_addr}")
    print("SSRC      Frequency  Rate   Preset  SNR    Address")
    print("--------- ---------- ------ ------- ------ ------------------")

    # Real channel data from user's ka9q-radio system
    real_channels = [
        (2500000, 2.5, 12000, 'iq', 12.3),
        (3330000, 3.33, 12000, 'iq', 6.7),
        (5000000, 5.0, 12000, 'iq', 32.4),
        (7850000, 7.85, 12000, 'iq', 30.6),
        (10000000, 10.0, 12000, 'iq', 14.1),
        (14670000, 14.67, 12000, 'iq', -12.0),
        (15000000, 15.0, 12000, 'iq', -9.4),
        (20000000, 20.0, 12000, 'iq', -float('inf')),
        (25000000, 25.0, 12000, 'iq', -float('inf'))
    ]

    for ssrc, freq_mhz, rate, preset, snr in real_channels:
        # All channels use the same multicast address and port as per user's radio system
        address = '239.192.152.141:5004'

        # Format frequency display (handle both integer and decimal frequencies)
        if freq_mhz.is_integer():
            freq_display = f"{freq_mhz:8.0f}"
        else:
            freq_display = f"{freq_mhz:8.2f}"

        # Format SNR display
        if snr == -float('inf'):
            snr_display = " -inf"
        else:
            snr_display = f"{snr:5.1f}"

        # Print formatted line
        print(f"{ssrc:8} {freq_display}MHz {rate:5} {preset:6} {snr_display:5} {address}")

if __name__ == '__main__':
    main()
