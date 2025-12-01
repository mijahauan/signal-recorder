#!/usr/bin/env python3
"""
WSPR Recorder Demo

Demonstrates the WSPR recorder using the generic recording infrastructure.
Records WSPR audio from a ka9q-radio stream and outputs WAV files compatible
with the wsprd decoder.

Prerequisites:
    - radiod running with WSPR channels configured
    - ka9q-python installed

Usage:
    # Record 20m WSPR for 5 minutes
    python3 wspr_demo.py --frequency 14095600 --duration 300
    
    # Record from specific multicast address
    python3 wspr_demo.py --frequency 7038600 --multicast 239.192.152.141 --duration 600
    
    # Quick test (one 2-minute segment)
    python3 wspr_demo.py --frequency 10138700 --duration 130

Output:
    WAV files in ./wspr_output/ with wsprd-compatible naming:
    YYMMDD_HHMM_<freq>_usb.wav (e.g., 251130_1200_14095600_usb.wav)
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

# Add parent directory to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from signal_recorder.rtp_receiver import RTPReceiver
from signal_recorder.wspr_recorder import WsprRecorder, WsprConfig

# Common WSPR dial frequencies (Hz)
WSPR_FREQUENCIES = {
    '160m': 1836600,
    '80m': 3568600,
    '60m': 5287200,
    '40m': 7038600,
    '30m': 10138700,
    '20m': 14095600,
    '17m': 18104600,
    '15m': 21094600,
    '12m': 24924600,
    '10m': 28124600,
    '6m': 50293000,
}


def setup_logging(verbose: bool = False):
    """Configure logging"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    # Reduce noise from libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def on_wav_complete(path: Path):
    """Callback when a WAV file is written"""
    print(f"\n✓ WAV file complete: {path}")
    print(f"  Size: {path.stat().st_size / 1024:.1f} KB")
    print(f"  Ready for wsprd decoding")


def main():
    parser = argparse.ArgumentParser(
        description='WSPR Recorder Demo - Record WSPR audio from ka9q-radio',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --frequency 14095600 --duration 300    # Record 20m WSPR for 5 min
  %(prog)s --band 30m --duration 600              # Record 30m WSPR for 10 min
  %(prog)s --frequency 7038600 --output /tmp/wspr # Custom output directory
  
Common WSPR frequencies:
  160m: 1836600 Hz    80m: 3568600 Hz    60m: 5287200 Hz
  40m:  7038600 Hz    30m: 10138700 Hz   20m: 14095600 Hz
  17m:  18104600 Hz   15m: 21094600 Hz   12m: 24924600 Hz
  10m:  28124600 Hz   6m:  50293000 Hz
"""
    )
    
    # Frequency specification (either --frequency or --band)
    freq_group = parser.add_mutually_exclusive_group(required=True)
    freq_group.add_argument(
        '--frequency', '-f',
        type=int,
        help='WSPR dial frequency in Hz (e.g., 14095600)'
    )
    freq_group.add_argument(
        '--band', '-b',
        choices=list(WSPR_FREQUENCIES.keys()),
        help='WSPR band name (e.g., 20m, 30m)'
    )
    
    # Network parameters
    parser.add_argument(
        '--multicast', '-m',
        default='239.192.152.141',
        help='Multicast address for RTP stream (default: 239.192.152.141)'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=5004,
        help='RTP port (default: 5004)'
    )
    parser.add_argument(
        '--ssrc', '-s',
        type=int,
        help='RTP SSRC identifier (default: frequency in Hz)'
    )
    
    # Output parameters
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=Path('./wspr_output'),
        help='Output directory for WAV files (default: ./wspr_output)'
    )
    
    # Recording parameters
    parser.add_argument(
        '--duration', '-d',
        type=int,
        default=130,
        help='Recording duration in seconds (default: 130 = one 2-min segment + buffer)'
    )
    
    # Debugging
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger('wspr_demo')
    
    # Determine frequency
    if args.band:
        frequency_hz = WSPR_FREQUENCIES[args.band]
        logger.info(f"Using {args.band} WSPR frequency: {frequency_hz} Hz")
    else:
        frequency_hz = args.frequency
    
    # Determine SSRC
    ssrc = args.ssrc if args.ssrc else frequency_hz
    
    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)
    
    print(f"""
╔════════════════════════════════════════════════════════════════╗
║                    WSPR Recorder Demo                          ║
╠════════════════════════════════════════════════════════════════╣
║  Frequency:  {frequency_hz:>10} Hz ({frequency_hz/1e6:.4f} MHz)              ║
║  SSRC:       {ssrc:>10}                                    ║
║  Multicast:  {args.multicast}:{args.port:<5}                          ║
║  Output:     {str(args.output):<44} ║
║  Duration:   {args.duration:>10} seconds                            ║
╚════════════════════════════════════════════════════════════════╝
""")
    
    # Setup signal handler for graceful shutdown
    shutdown_requested = False
    
    def signal_handler(signum, frame):
        nonlocal shutdown_requested
        print("\n\nShutdown requested, finishing current segment...")
        shutdown_requested = True
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create RTP receiver
    logger.info(f"Creating RTP receiver for {args.multicast}:{args.port}")
    rtp_receiver = RTPReceiver(args.multicast, args.port)
    
    # Create WSPR recorder
    config = WsprConfig(
        ssrc=ssrc,
        frequency_hz=frequency_hz,
        output_dir=args.output,
        sample_rate=12000,
        segment_duration=120.0,
    )
    
    recorder = WsprRecorder(
        config=config,
        rtp_receiver=rtp_receiver,
        on_file_complete=on_wav_complete,
    )
    
    try:
        # Start RTP receiver
        logger.info("Starting RTP receiver...")
        rtp_receiver.start()
        
        # Start WSPR recorder
        logger.info("Starting WSPR recorder...")
        recorder.start()
        
        print(f"Recording... (press Ctrl+C to stop early)")
        print(f"WSPR 2-minute segments will be written as they complete.\n")
        
        # Wait for duration or shutdown signal
        start_time = time.time()
        last_stats_time = start_time
        
        while not shutdown_requested and (time.time() - start_time) < args.duration:
            time.sleep(1)
            
            # Print periodic status every 30 seconds
            elapsed = time.time() - start_time
            if time.time() - last_stats_time >= 30:
                stats = recorder.get_stats()
                remaining = args.duration - elapsed
                print(f"  [{elapsed:.0f}s] Segments: {stats.get('segments_completed', 0)}, "
                      f"Packets: {stats.get('packets_received', 0)}, "
                      f"Remaining: {remaining:.0f}s")
                last_stats_time = time.time()
        
        print(f"\nRecording complete.")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1
        
    finally:
        # Graceful shutdown
        logger.info("Stopping recorder...")
        recorder.stop()
        
        logger.info("Stopping RTP receiver...")
        rtp_receiver.stop()
        
        # Print final stats
        stats = recorder.get_stats()
        print(f"""
╔════════════════════════════════════════════════════════════════╗
║                      Recording Summary                         ║
╠════════════════════════════════════════════════════════════════╣
║  Segments written:  {stats.get('segments_written', 0):>6}                                  ║
║  Total samples:     {stats.get('total_samples_written', 0):>10}                              ║
║  Packets received:  {stats.get('packets_received', 0):>10}                              ║
║  Total gaps:        {stats.get('total_gaps', 0):>6}                                  ║
╚════════════════════════════════════════════════════════════════╝

WAV files are in: {args.output}

To decode with wsprd:
  cd {args.output}
  wsprd -f {frequency_hz/1e6:.4f} *.wav
""")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
