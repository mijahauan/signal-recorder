#!/usr/bin/env python3
"""
Audio Streaming CLI

Streams live audio from a KA9Q radio multicast channel.
Outputs PCM audio to stdout for HTTP streaming.
"""

import sys
import os
import argparse
import logging

# Add parent directory to path for imports when run as script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from signal_recorder.audio_streamer import AudioStreamer

# Suppress logging to stderr since we're outputting audio to stdout
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Stream audio from KA9Q radio multicast channel')
    parser.add_argument('--multicast-address', required=True, help='Multicast IP address')
    parser.add_argument('--multicast-port', type=int, required=True, help='Multicast port')
    parser.add_argument('--mode', default='AM', choices=['AM', 'USB', 'LSB', 'FM'], 
                       help='Demodulation mode')
    parser.add_argument('--audio-rate', type=int, default=12000, 
                       help='Output audio sample rate (Hz)')
    
    args = parser.parse_args()
    
    multicast_address = args.multicast_address
    multicast_port = args.multicast_port
    
    logger.info(f"Starting audio stream: {multicast_address}:{multicast_port} "
               f"(mode={args.mode}, rate={args.audio_rate} Hz)")
    
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
            # Short timeout (50ms = 1 chunk duration) for smooth streaming
            chunk = streamer.get_audio_chunk(timeout=0.05)
            
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
