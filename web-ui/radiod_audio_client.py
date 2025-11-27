#!/usr/bin/env python3
"""
Radiod Audio Client - AM Audio Channel Management for GRAPE

Creates AM audio channels with AGC for listening to WWV/CHU signals.
Audio channels use SSRC = IQ_SSRC + 999 (e.g., 5 MHz uses SSRC 5000999).

Usage:
    # Get or create audio channel for WWV 10 MHz
    python radiod_audio_client.py --radiod-host bee1-hf-status.local \
        get-or-create --frequency 10000000
    
    # Stop audio channel
    python radiod_audio_client.py --radiod-host bee1-hf-status.local \
        stop --frequency 10000000
"""

import sys
import json
import os
import argparse
import time
from typing import Dict, Optional

# CRITICAL: Force SWL-ka9q library - remove any cached ka9q modules first
# The venv may have an older/different ka9q that doesn't work properly
SWL_KA9Q_PATH = '/home/wsprdaemon/SWL-ka9q'

# Remove any pre-loaded ka9q modules
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith('ka9q'):
        del sys.modules[mod_name]

# Insert SWL-ka9q path at the very beginning
sys.path.insert(0, SWL_KA9Q_PATH)

try:
    from ka9q import RadiodControl
    from ka9q.discovery import discover_channels_native
    from ka9q.utils import resolve_multicast_address
except ImportError as e:
    print(json.dumps({
        'success': False,
        'error': f'ka9q library not available: {e}',
        'detail': 'Install ka9q-python or ensure SWL-ka9q venv is active'
    }))
    sys.exit(1)


# Audio SSRC offset - added to IQ SSRC to create audio channel SSRC
AUDIO_SSRC_OFFSET = 999


def get_audio_ssrc(frequency_hz: int) -> int:
    """
    Calculate audio SSRC from frequency.
    
    For WWV/CHU channels, the IQ SSRC equals the frequency in Hz.
    Audio SSRC = IQ_SSRC + 999
    
    Examples:
        5 MHz  -> IQ SSRC 5000000  -> Audio SSRC 5000999
        10 MHz -> IQ SSRC 10000000 -> Audio SSRC 10000999
    """
    iq_ssrc = int(frequency_hz)
    return iq_ssrc + AUDIO_SSRC_OFFSET


def get_or_create_audio_channel(
    radiod_host: str,
    frequency_hz: float,
    interface: Optional[str] = None,
    fallback_multicast: Optional[str] = None
) -> Dict:
    """
    Get or create an AM audio channel with AGC for the specified frequency.
    
    Args:
        radiod_host: Radiod hostname (e.g., 'bee1-hf-status.local')
        frequency_hz: Center frequency in Hz
        interface: Network interface IP for multicast
        fallback_multicast: Fallback multicast address for remote clients
    
    Returns:
        Dict with channel information including multicast address and port
    """
    ssrc = get_audio_ssrc(int(frequency_hz))
    
    try:
        control = RadiodControl(radiod_host)
        
        # Create AM channel with AGC enabled
        # Settings optimized for WWV/CHU voice/tone listening
        control.create_channel(
            ssrc=ssrc,
            frequency_hz=frequency_hz,
            preset='am',           # AM demodulation
            sample_rate=12000,     # 12 kHz audio (sufficient for AM broadcast)
            agc_enable=1,          # AGC ON for comfortable listening
            gain=30.0              # Initial gain (AGC will adjust)
        )
        
        # Wait for radiod to process and broadcast status
        time.sleep(0.5)
        
        # Try to discover the channel's multicast address
        # Strategy 1: Native multicast discovery with retry (local clients)
        for attempt in range(2):
            try:
                channels = discover_channels_native(
                    radiod_host, 
                    listen_duration=1.5,  # Longer listen for new channels
                    interface=interface
                )
                if ssrc in channels:
                    ch = channels[ssrc]
                    return {
                        'success': True,
                        'ssrc': ssrc,
                        'iq_ssrc': ssrc - AUDIO_SSRC_OFFSET,
                        'frequency_hz': ch.frequency,
                        'multicast_address': ch.multicast_address,
                        'port': ch.port,
                        'sample_rate': ch.sample_rate,
                        'preset': 'am',
                        'agc_enabled': True,
                        'mode': 'discovered'
                    }
                # Channel not found yet, wait and retry
                if attempt == 0:
                    time.sleep(0.5)
            except Exception:
                pass  # Multicast discovery failed, try next strategy
        
        # Strategy 2: Query via control socket (remote clients)
        try:
            from ka9q.discovery import discover_channels_via_control
            channels = discover_channels_via_control(radiod_host, listen_duration=1.0)
            if ssrc in channels:
                ch = channels[ssrc]
                return {
                    'success': True,
                    'ssrc': ssrc,
                    'iq_ssrc': ssrc - AUDIO_SSRC_OFFSET,
                    'frequency_hz': ch.frequency,
                    'multicast_address': ch.multicast_address,
                    'port': ch.port,
                    'sample_rate': ch.sample_rate,
                    'preset': 'am',
                    'agc_enabled': True,
                    'mode': 'queried'
                }
        except Exception:
            pass  # Query failed, use fallback
        
        # Strategy 3: Use fallback multicast address
        if fallback_multicast:
            return {
                'success': True,
                'ssrc': ssrc,
                'iq_ssrc': ssrc - AUDIO_SSRC_OFFSET,
                'frequency_hz': frequency_hz,
                'multicast_address': fallback_multicast,
                'port': 5004,
                'sample_rate': 12000,
                'preset': 'am',
                'agc_enabled': True,
                'mode': 'fallback'
            }
        
        # No fallback available
        raise Exception(
            f'Cannot discover multicast address for audio SSRC {ssrc}. '
            f'Set RADIOD_AUDIO_MULTICAST environment variable or pass --fallback-multicast.'
        )
        
    except Exception as e:
        import traceback
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'ssrc': ssrc,
            'frequency_hz': frequency_hz
        }


def stop_audio_channel(radiod_host: str, frequency_hz: float) -> Dict:
    """
    Stop/delete an audio channel by setting its frequency to 0.
    
    Args:
        radiod_host: Radiod hostname
        frequency_hz: Original frequency (used to calculate SSRC)
    
    Returns:
        Dict with success status
    """
    ssrc = get_audio_ssrc(int(frequency_hz))
    
    try:
        # Import low-level encoding functions to bypass validation
        from ka9q.control import encode_double, encode_int, encode_eol
        from ka9q.types import StatusType, CMD
        import random
        
        control = RadiodControl(radiod_host)
        
        # Construct command to set frequency to 0 (deletes channel)
        cmdbuffer = bytearray()
        cmdbuffer.append(CMD)
        encode_double(cmdbuffer, StatusType.RADIO_FREQUENCY, 0.0)
        encode_int(cmdbuffer, StatusType.OUTPUT_SSRC, ssrc)
        encode_int(cmdbuffer, StatusType.COMMAND_TAG, random.randint(1, 2**31))
        encode_eol(cmdbuffer)
        
        control.send_command(cmdbuffer)
        
        return {
            'success': True,
            'ssrc': ssrc,
            'frequency_hz': frequency_hz,
            'action': 'stopped'
        }
        
    except Exception as e:
        import traceback
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'ssrc': ssrc
        }


def list_audio_channels(radiod_host: str, interface: Optional[str] = None) -> Dict:
    """
    List all active audio channels (SSRCs ending in 999).
    
    Args:
        radiod_host: Radiod hostname
        interface: Network interface IP for multicast
    
    Returns:
        Dict with list of audio channels
    """
    try:
        channels = discover_channels_native(
            radiod_host, 
            listen_duration=2.0, 
            interface=interface
        )
        
        audio_channels = {}
        for ssrc, ch in channels.items():
            # Check if this is an audio channel (SSRC ends in 999)
            if ssrc % 1000 == AUDIO_SSRC_OFFSET:
                audio_channels[ssrc] = {
                    'ssrc': ssrc,
                    'iq_ssrc': ssrc - AUDIO_SSRC_OFFSET,
                    'frequency_hz': ch.frequency,
                    'frequency_mhz': ch.frequency / 1e6,
                    'multicast_address': ch.multicast_address,
                    'port': ch.port,
                    'sample_rate': ch.sample_rate,
                    'preset': ch.preset
                }
        
        return {
            'success': True,
            'count': len(audio_channels),
            'channels': audio_channels
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'channels': {}
        }


def main():
    parser = argparse.ArgumentParser(
        description='GRAPE Audio Channel Manager - Creates AM channels with AGC for WWV/CHU listening'
    )
    parser.add_argument('--radiod-host', required=True, 
                       help='Radiod hostname (e.g., bee1-hf-status.local)')
    parser.add_argument('--interface', 
                       help='Network interface IP for multicast')
    parser.add_argument('--fallback-multicast',
                       help='Fallback multicast address for remote clients')
    
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # get-or-create command
    create_parser = subparsers.add_parser('get-or-create',
        help='Get existing or create new AM audio channel')
    create_parser.add_argument('--frequency', type=float, required=True,
        help='Center frequency in Hz (e.g., 10000000 for 10 MHz)')
    
    # stop command
    stop_parser = subparsers.add_parser('stop',
        help='Stop/delete an audio channel')
    stop_parser.add_argument('--frequency', type=float, required=True,
        help='Center frequency in Hz')
    
    # list command
    list_parser = subparsers.add_parser('list',
        help='List active audio channels')
    
    # ssrc command (utility to calculate audio SSRC)
    ssrc_parser = subparsers.add_parser('ssrc',
        help='Calculate audio SSRC for a frequency')
    ssrc_parser.add_argument('--frequency', type=float, required=True,
        help='Center frequency in Hz')
    
    args = parser.parse_args()
    
    try:
        if args.command == 'get-or-create':
            fallback = args.fallback_multicast or os.environ.get('RADIOD_AUDIO_MULTICAST')
            result = get_or_create_audio_channel(
                args.radiod_host,
                args.frequency,
                args.interface,
                fallback
            )
        elif args.command == 'stop':
            result = stop_audio_channel(args.radiod_host, args.frequency)
        elif args.command == 'list':
            result = list_audio_channels(args.radiod_host, args.interface)
        elif args.command == 'ssrc':
            ssrc = get_audio_ssrc(int(args.frequency))
            result = {
                'success': True,
                'frequency_hz': args.frequency,
                'iq_ssrc': int(args.frequency),
                'audio_ssrc': ssrc
            }
        
        print(json.dumps(result))
        sys.stdout.flush()
        return 0 if result.get('success', False) else 1
        
    except Exception as e:
        import traceback
        error = {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }
        print(json.dumps(error), file=sys.stderr)
        sys.stderr.flush()
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.stdout.flush()
        return 1


if __name__ == '__main__':
    sys.exit(main())
