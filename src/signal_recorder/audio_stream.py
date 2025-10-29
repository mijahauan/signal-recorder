#!/usr/bin/env python3
"""
Audio Streaming CLI

Streams live audio from a KA9Q radio multicast channel.
Outputs PCM audio to stdout for HTTP streaming.
"""

import sys
import argparse
import logging
from .audio_streamer import AudioStreamer

# Suppress logging to stderr since we're outputting audio to stdout
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Stream audio from KA9Q radio multicast channel')
    parser.add_argument('--ssrc', required=True, help='Channel SSRC/frequency (Hz)')
    parser.add_argument('--multicast-base', default='239.1.2', help='Multicast base address')
    parser.add_argument('--mode', default='AM', choices=['AM', 'USB', 'LSB', 'FM'], 
                       help='Demodulation mode')
    parser.add_argument('--audio-rate', type=int, default=12000, 
                       help='Output audio sample rate (Hz)')
    
    args = parser.parse_args()
    
    # Convert SSRC to multicast address (same logic as grape_rtp_recorder.py)
    # Format: 239.1.2.X where X is derived from SSRC
    ssrc = int(args.ssrc)
    last_octet = (ssrc % 254) + 1  # Ensure 1-254 range
    multicast_address = f"{args.multicast_base}.{last_octet}"
    multicast_port = 5004  # Default RTP port
    
    logger.info(f"Starting audio stream: {multicast_address}:{multicast_port} "
               f"(SSRC={ssrc}, mode={args.mode}, rate={args.audio_rate} Hz)")
    
    # Create and start streamer
    streamer = AudioStreamer(
        multicast_address=multicast_address,
        multicast_port=multicast_port,
        mode=args.mode,
        audio_rate=args.audio_rate
    )
    
    try:
        streamer.start()
        
        # Stream audio chunks to stdout
        while True:
            chunk = streamer.get_audio_chunk(timeout=1.0)
            
            # Write raw PCM to stdout
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
    
    except KeyboardInterrupt:
        logger.info("Audio stream interrupted")
    except Exception as e:
        logger.error(f"Audio stream error: {e}", exc_info=True)
    finally:
        streamer.stop()
        logger.info("Audio stream stopped")


if __name__ == '__main__':
    main()
