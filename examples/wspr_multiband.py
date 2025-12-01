#!/usr/bin/env python3
"""
Multi-Band WSPR Recorder

Records multiple WSPR bands simultaneously from ka9q-radio.
Demonstrates parallel recording using multiple WsprRecorder instances
sharing a single RTPReceiver.

Usage:
    # Record 30m and 20m WSPR
    python3 wspr_multiband.py --bands 30m 20m --duration 300

    # Record all HF bands for 10 minutes
    python3 wspr_multiband.py --all-bands --duration 600

Output:
    WAV files organized by band: wspr_output/<band>/YYMMDD_HHMM_freq_usb.wav
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.rtp_receiver import RTPReceiver
from signal_recorder.wspr_recorder import WsprRecorder, WsprConfig

# WSPR dial frequencies and their corresponding SSRCs (freq in kHz)
WSPR_BANDS = {
    '160m': {'freq_hz': 1836600, 'ssrc': 1837},
    '80m':  {'freq_hz': 3568600, 'ssrc': 3569},
    '60m':  {'freq_hz': 5287200, 'ssrc': 5287},
    '40m':  {'freq_hz': 7038600, 'ssrc': 7039},
    '30m':  {'freq_hz': 10138700, 'ssrc': 10139},
    '20m':  {'freq_hz': 14095600, 'ssrc': 14096},
    '17m':  {'freq_hz': 18104600, 'ssrc': 18105},
    '15m':  {'freq_hz': 21094600, 'ssrc': 21095},
    '12m':  {'freq_hz': 24924600, 'ssrc': 24925},
    '10m':  {'freq_hz': 28124600, 'ssrc': 28125},
    '6m':   {'freq_hz': 50293000, 'ssrc': 50293},
}

# Common HF bands (excluding 160m, 6m which may not be available)
HF_BANDS = ['80m', '40m', '30m', '20m', '17m', '15m', '12m', '10m']


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def on_wav_complete(band: str, path: Path):
    """Callback when a WAV file is written"""
    print(f"  ✓ [{band}] {path.name} ({path.stat().st_size / 1024:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(
        description='Multi-Band WSPR Recorder',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available bands: {', '.join(WSPR_BANDS.keys())}

Examples:
  %(prog)s --bands 30m 20m --duration 300       # Record 30m and 20m for 5 min
  %(prog)s --all-bands --duration 600           # All bands for 10 min
  %(prog)s --hf-bands --duration 300            # HF bands (80m-10m)
"""
    )
    
    band_group = parser.add_mutually_exclusive_group(required=True)
    band_group.add_argument(
        '--bands', '-b',
        nargs='+',
        choices=list(WSPR_BANDS.keys()),
        help='WSPR bands to record'
    )
    band_group.add_argument(
        '--all-bands',
        action='store_true',
        help='Record all available bands'
    )
    band_group.add_argument(
        '--hf-bands',
        action='store_true',
        help='Record common HF bands (80m-10m)'
    )
    
    parser.add_argument(
        '--multicast', '-m',
        default='239.113.49.249',
        help='Multicast address (default: 239.113.49.249)'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=5004,
        help='RTP port (default: 5004)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=Path('./wspr_multiband'),
        help='Output directory (default: ./wspr_multiband)'
    )
    parser.add_argument(
        '--duration', '-d',
        type=int,
        default=130,
        help='Recording duration in seconds (default: 130)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger('wspr_multiband')
    
    # Determine bands to record
    if args.all_bands:
        bands = list(WSPR_BANDS.keys())
    elif args.hf_bands:
        bands = HF_BANDS
    else:
        bands = args.bands
    
    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)
    
    print(f"""
╔════════════════════════════════════════════════════════════════╗
║              Multi-Band WSPR Recorder                          ║
╠════════════════════════════════════════════════════════════════╣
║  Bands:      {', '.join(bands):<48} ║
║  Multicast:  {args.multicast}:{args.port:<5}                          ║
║  Output:     {str(args.output):<48} ║
║  Duration:   {args.duration:>10} seconds                            ║
╚════════════════════════════════════════════════════════════════╝
""")
    
    # Setup signal handler
    shutdown_requested = False
    
    def signal_handler(signum, frame):
        nonlocal shutdown_requested
        print("\n\nShutdown requested...")
        shutdown_requested = True
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create shared RTP receiver
    logger.info(f"Creating RTP receiver for {args.multicast}:{args.port}")
    rtp_receiver = RTPReceiver(args.multicast, args.port)
    
    # Create recorders for each band
    recorders: Dict[str, WsprRecorder] = {}
    
    for band in bands:
        band_info = WSPR_BANDS[band]
        band_dir = args.output / band
        band_dir.mkdir(parents=True, exist_ok=True)
        
        config = WsprConfig(
            ssrc=band_info['ssrc'],
            frequency_hz=band_info['freq_hz'],
            output_dir=band_dir,
            sample_rate=12000,
            segment_duration=120.0,
            description=f"WSPR {band}",
        )
        
        # Create callback with band closure
        def make_callback(b):
            return lambda path: on_wav_complete(b, path)
        
        recorder = WsprRecorder(
            config=config,
            rtp_receiver=rtp_receiver,
            on_file_complete=make_callback(band),
        )
        recorders[band] = recorder
        logger.info(f"Created recorder for {band}: SSRC={band_info['ssrc']}, freq={band_info['freq_hz']/1e6:.4f} MHz")
    
    try:
        # Start RTP receiver
        logger.info("Starting RTP receiver...")
        rtp_receiver.start()
        
        # Start all recorders
        logger.info(f"Starting {len(recorders)} WSPR recorders...")
        for band, recorder in recorders.items():
            recorder.start()
        
        print(f"Recording {len(bands)} bands... (Ctrl+C to stop)\n")
        print("WAV files will appear as 2-minute segments complete:\n")
        
        # Wait for duration or shutdown
        start_time = time.time()
        last_stats_time = start_time
        
        while not shutdown_requested and (time.time() - start_time) < args.duration:
            time.sleep(1)
            
            # Print status every 30 seconds
            elapsed = time.time() - start_time
            if time.time() - last_stats_time >= 30:
                total_packets = sum(r.get_stats().get('packets_received', 0) for r in recorders.values())
                total_segments = sum(r.get_stats().get('segments_written', 0) for r in recorders.values())
                remaining = args.duration - elapsed
                print(f"\n  [{elapsed:.0f}s] Packets: {total_packets}, Segments: {total_segments}, Remaining: {remaining:.0f}s\n")
                last_stats_time = time.time()
        
        print(f"\nRecording complete.")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1
        
    finally:
        # Stop all recorders
        logger.info("Stopping recorders...")
        for band, recorder in recorders.items():
            recorder.stop()
        
        # Stop RTP receiver
        logger.info("Stopping RTP receiver...")
        rtp_receiver.stop()
        
        # Print summary
        print(f"""
╔════════════════════════════════════════════════════════════════╗
║                      Recording Summary                         ║
╠════════════════════════════════════════════════════════════════╣""")
        
        total_segments = 0
        total_samples = 0
        for band, recorder in recorders.items():
            stats = recorder.get_stats()
            segments = stats.get('segments_written', 0)
            samples = stats.get('total_samples_written', 0)
            packets = stats.get('packets_received', 0)
            total_segments += segments
            total_samples += samples
            print(f"║  {band:>4}: {segments:>3} segments, {packets:>6} packets, {samples:>8} samples   ║")
        
        print(f"""╠════════════════════════════════════════════════════════════════╣
║  TOTAL: {total_segments:>3} segments, {total_samples:>10} samples                   ║
╚════════════════════════════════════════════════════════════════╝

WAV files are in: {args.output}/
""")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
