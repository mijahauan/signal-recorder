#!/usr/bin/env python3
"""
Verify IQ Data Quality with Spectrogram

Captures live IQ data from a GRAPE channel and generates a spectrogram
to verify:
- Carrier is present and at correct frequency
- Frequency deviations (doppler) are visible
- Data quality is suitable for ionospheric studies
"""

import socket
import struct
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal as scipy_signal
import argparse
from datetime import datetime

def capture_iq_data(ssrc, duration_sec=60, multicast_addr='239.192.152.141', port=5004):
    """Capture IQ samples from RTP multicast"""
    print(f"Capturing {duration_sec}s of IQ data from SSRC {ssrc}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))
    
    mreq = struct.pack('4sl', socket.inet_aton(multicast_addr), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    # Expected: 80 complex IQ samples per packet @ 100 packets/sec = 8000 Hz complex rate
    # For 60 seconds: 60 * 8000 = 480,000 samples
    target_samples = int(duration_sec * 8000)
    all_samples = []
    packet_count = 0
    
    while len(all_samples) < target_samples:
        data, addr = sock.recvfrom(8192)
        if len(data) < 12:
            continue
        
        # Check SSRC
        pkt_ssrc = struct.unpack('>I', data[8:12])[0]
        if pkt_ssrc != ssrc:
            continue
        
        packet_count += 1
        payload = data[12:]
        
        # Parse IQ samples with CORRECT byte order (big-endian) and phase (Q+jI)
        if len(payload) % 4 == 0:
            samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
            samples = samples_int16.astype(np.float32) / 32768.0
            # CRITICAL: KA9Q sends Q,I pairs - use Q + jI for carrier at DC
            iq_samples = samples[:, 1] + 1j * samples[:, 0]  # Q + jI
            all_samples.extend(iq_samples)
        
        if packet_count % 100 == 0:
            print(f"  {len(all_samples)}/{target_samples} samples ({packet_count} packets)")
    
    sock.close()
    
    iq_data = np.array(all_samples[:target_samples])
    print(f"Captured {len(iq_data)} IQ samples from {packet_count} packets")
    print(f"  IQ magnitude range: {np.min(np.abs(iq_data)):.4f} to {np.max(np.abs(iq_data)):.4f}")
    print(f"  IQ mean: {np.mean(iq_data):.4f}")
    
    return iq_data

def generate_spectrogram(iq_data, sample_rate=8000, channel_name="Channel"):
    """Generate and save spectrogram"""
    print(f"\nGenerating spectrogram...")
    
    # Create figure
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    
    # Spectrogram (time vs frequency)
    # Use longer FFT for better frequency resolution
    nperseg = 512  # FFT size
    noverlap = nperseg - 32  # Overlap for smoothness
    
    f, t, Sxx = scipy_signal.spectrogram(
        iq_data,
        fs=sample_rate,
        nperseg=nperseg,
        noverlap=noverlap,
        scaling='density'
    )
    
    # Plot spectrogram
    im = ax1.pcolormesh(t, f, 10 * np.log10(Sxx + 1e-10), 
                        shading='gouraud', cmap='viridis',
                        vmin=-80, vmax=-20)
    ax1.set_ylabel('Frequency (Hz)')
    ax1.set_xlabel('Time (seconds)')
    ax1.set_title(f'{channel_name} - Spectrogram (IQ baseband, carrier at DC)')
    ax1.grid(True, alpha=0.3)
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax1, label='Power (dB)')
    
    # Power vs time (averaged across frequency)
    power_time = np.mean(Sxx, axis=0)
    ax2.plot(t, 10 * np.log10(power_time + 1e-10))
    ax2.set_ylabel('Average Power (dB)')
    ax2.set_xlabel('Time (seconds)')
    ax2.set_title(f'{channel_name} - Average Power vs Time')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save figure
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'/tmp/{channel_name.replace(" ", "_")}_spectrogram_{timestamp}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"Spectrogram saved to: {filename}")
    
    return filename

def main():
    parser = argparse.ArgumentParser(description='Verify IQ data quality with spectrogram')
    parser.add_argument('--ssrc', type=int, default=5000000, help='SSRC to capture')
    parser.add_argument('--duration', type=int, default=60, help='Capture duration (seconds)')
    parser.add_argument('--channel-name', default='WWV_5MHz', help='Channel name for plot')
    
    args = parser.parse_args()
    
    # Capture IQ data
    iq_data = capture_iq_data(args.ssrc, args.duration)
    
    # Generate spectrogram
    filename = generate_spectrogram(iq_data, channel_name=args.channel_name)
    
    print(f"\n✅ IQ data verification complete!")
    print(f"   Download and view: scp bee1:{filename} ~/Downloads/")
    print(f"\nWhat to look for:")
    print(f"  - Strong carrier peak at 0 Hz (DC) - baseband signal")
    print(f"  - Frequency deviations show doppler shifts")
    print(f"  - Clean signal with good SNR")
    print(f"  - No unusual artifacts or noise patterns")

if __name__ == '__main__':
    main()
