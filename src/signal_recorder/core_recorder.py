#!/usr/bin/env python3
"""
GRAPE Core Recorder - Battle-Tested Data Acquisition

Minimal, rock-solid recorder that ONLY writes NPZ archives.
NO analytics, NO tone detection, NO decimation, NO quality metrics.

Responsibilities:
1. Receive RTP packets from ka9q-radio multicast
2. Resequence packets (handle out-of-order delivery)
3. Detect gaps via RTP timestamp discontinuities
4. Fill gaps with zeros (maintain sample count integrity)
5. Write complete NPZ archives with RTP timestamps

That's it. Everything else is analytics (separate process).
"""

import numpy as np
import struct
import logging
import signal
import sys
import os
import time
import json
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from .grape_rtp_recorder import RTPReceiver  # Reuse existing RTP receiver
from .packet_resequencer import PacketResequencer, RTPPacket, GapInfo
from .core_npz_writer import CoreNPZWriter, GapRecord
from .channel_manager import ChannelManager
from .radiod_health import RadiodHealthChecker

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """Configuration for a single channel"""
    ssrc: int
    frequency_hz: float
    sample_rate: int
    description: str


class CoreRecorder:
    """
    Core recorder: RTP → NPZ archives
    
    Design principles:
    - Minimal code (~200 lines)
    - Conservative error handling (never crash)
    - No dependencies on analytics code
    - Optimized for reliability over features
    """
    
    def __init__(self, config: dict):
        """
        Initialize core recorder
        
        Args:
            config: Configuration dict with:
                - multicast_address: RTP multicast group
                - port: RTP port (default 5004)
                - output_dir: Base directory for archives
                - station: Station metadata (callsign, grid, instrument_id)
                - channels: List of channel configs
                - status_address: Radiod status address for channel management
        """
        self.config = config
        self.output_dir = Path(config['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Channel management for auto-recovery
        self.status_address = config.get('status_address', '239.192.152.141')
        self.channel_manager = ChannelManager(self.status_address)
        self.health_checker = RadiodHealthChecker(self.status_address)
        self.channel_configs = {}  # Store for recreation
        
        # RTP receiver (shared across channels)
        self.rtp_receiver = RTPReceiver(
            multicast_address=config['multicast_address'],
            port=config.get('port', 5004)
        )
        
        # Per-channel processors
        self.channels: Dict[int, 'ChannelProcessor'] = {}
        
        # Initialize channels
        station_config = config.get('station', {})
        for ch_cfg in config.get('channels', []):
            # Store config for recovery
            self.channel_configs[ch_cfg['ssrc']] = ch_cfg
            
            processor = ChannelProcessor(
                ssrc=ch_cfg['ssrc'],
                frequency_hz=ch_cfg['frequency_hz'],
                sample_rate=ch_cfg['sample_rate'],
                description=ch_cfg['description'],
                output_dir=self.output_dir,
                station_config=station_config
            )
            self.channels[ch_cfg['ssrc']] = processor
            
            # Register RTP callback
            self.rtp_receiver.register_callback(
                ssrc=ch_cfg['ssrc'],
                callback=processor.process_rtp_packet
            )
        
        logger.info(f"CoreRecorder initialized: {len(self.channels)} channels")
        
        # Status tracking
        self.start_time = time.time()
        self.status_file = self.output_dir / 'status' / 'core-recorder-status.json'
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Graceful shutdown
        self.running = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def run(self):
        """Main run loop"""
        logger.info("Starting GRAPE Core Recorder")
        logger.info("Responsibility: RTP → NPZ archives (no analytics)")
        
        # Ensure all channels exist in radiod before starting
        logger.info("Verifying radiod channels...")
        self._ensure_channels_exist()
        
        # Start RTP receiver
        self.rtp_receiver.start()
        self.running = True
        
        logger.info("Core recorder running. Press Ctrl+C to stop.")
        
        # Write initial status
        self._write_status()
        
        # Main loop (status updates and health monitoring)
        last_status_time = 0
        last_health_check = 0
        try:
            while self.running:
                time.sleep(1)
                now = time.time()
                
                # Periodic status update (every 10 seconds)
                if now - last_status_time >= 10:
                    self._write_status()
                    last_status_time = now
                
                # Periodic status logging (every 60 seconds)
                if int(now) % 60 == 0:
                    self._log_status()
                
                # Health monitoring (every 30 seconds)
                if now - last_health_check >= 30:
                    self._monitor_stream_health()
                    last_health_check = now
        
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        
        finally:
            self._shutdown()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def _write_status(self):
        """Write current status to JSON file for web-ui monitoring"""
        try:
            status = {
                'service': 'core_recorder',
                'version': '2.0',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'uptime_seconds': int(time.time() - self.start_time),
                'pid': os.getpid(),
                'channels': {},
                'overall': {
                    'channels_active': 0,
                    'channels_total': len(self.channels),
                    'total_npz_written': 0,
                    'total_packets_received': 0,
                    'total_gaps_detected': 0
                }
            }
            
            # Gather per-channel stats
            for ssrc, processor in self.channels.items():
                ch_stats = processor.get_status()
                status['channels'][hex(ssrc)] = ch_stats
                
                # Aggregate overall stats
                if ch_stats['packets_received'] > 0:
                    status['overall']['channels_active'] += 1
                status['overall']['total_npz_written'] += ch_stats['npz_files_written']
                status['overall']['total_packets_received'] += ch_stats['packets_received']
                status['overall']['total_gaps_detected'] += ch_stats['gaps_detected']
            
            # Write atomically (write to temp file, then rename)
            temp_file = self.status_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(status, f, indent=2)
            temp_file.replace(self.status_file)
            
        except Exception as e:
            logger.error(f"Failed to write status file: {e}")
    
    def _log_status(self):
        """Log periodic status"""
        for ssrc, processor in self.channels.items():
            stats = processor.get_stats()
            logger.info(
                f"{processor.description}: "
                f"{stats['minutes_written']} minutes, "
                f"{stats['packets_received']} packets, "
                f"{stats['gaps_detected']} gaps"
            )
    
    def _ensure_channels_exist(self):
        """
        Verify all configured channels exist in radiod, create if missing.
        Called at startup.
        """
        try:
            # Build channel specifications
            required_channels = []
            for ssrc, ch_cfg in self.channel_configs.items():
                required_channels.append({
                    'ssrc': ssrc,
                    'frequency_hz': ch_cfg['frequency_hz'],
                    'preset': ch_cfg.get('preset', 'iq'),
                    'sample_rate': ch_cfg.get('sample_rate', 16000),
                    'agc': ch_cfg.get('agc', 0),
                    'gain': ch_cfg.get('gain', 0),
                    'description': ch_cfg['description']
                })
            
            if not required_channels:
                logger.warning("No channels configured")
                return
            
            # Ensure channels exist (create missing ones)
            logger.info(f"Ensuring {len(required_channels)} channels exist in radiod...")
            success = self.channel_manager.ensure_channels_exist(
                required_channels, 
                update_existing=False
            )
            
            if success:
                logger.info("✓ All channels verified/created in radiod")
            else:
                logger.warning("⚠ Some channels may be missing - recording may fail")
                
        except Exception as e:
            logger.error(f"Channel verification failed: {e}", exc_info=True)
            logger.warning("Continuing anyway - some channels may work")
    
    def _monitor_stream_health(self):
        """
        Monitor stream health and recreate dead channels.
        Called periodically (every 30 seconds) in main loop.
        """
        try:
            # Check if radiod is alive
            if not self.health_checker.is_radiod_alive(timeout_sec=3.0):
                logger.warning("Radiod appears down - skipping health check")
                return
            
            # Check each channel for stale packets
            for ssrc, processor in self.channels.items():
                # Check if channel has gone silent
                if not processor.is_healthy():
                    logger.warning(
                        f"Channel {processor.description} (SSRC {ssrc:x}) appears dead - "
                        f"no packets in {processor.get_silence_duration():.0f}s"
                    )
                    
                    # Verify channel still exists in radiod
                    if not self.health_checker.verify_channel_exists(ssrc):
                        logger.error(
                            f"Channel {processor.description} missing from radiod - "
                            f"attempting recreation..."
                        )
                        self._recreate_channel(ssrc)
                    else:
                        logger.info(
                            f"Channel {processor.description} exists in radiod but no data - "
                            f"possible network/multicast issue"
                        )
                        
        except Exception as e:
            logger.error(f"Health monitoring error: {e}", exc_info=True)
    
    def _recreate_channel(self, ssrc: int):
        """
        Recreate a missing channel in radiod.
        
        Args:
            ssrc: SSRC of the channel to recreate
        """
        if ssrc not in self.channel_configs:
            logger.error(f"No config found for SSRC {ssrc:x} - cannot recreate")
            return
        
        ch_cfg = self.channel_configs[ssrc]
        
        try:
            logger.info(f"Recreating channel {ch_cfg['description']} (SSRC {ssrc:x})...")
            
            # Build channel spec
            channel_spec = {
                'ssrc': ssrc,
                'frequency_hz': ch_cfg['frequency_hz'],
                'preset': ch_cfg.get('preset', 'iq'),
                'sample_rate': ch_cfg.get('sample_rate', 16000),
                'agc': ch_cfg.get('agc', 0),
                'gain': ch_cfg.get('gain', 0),
                'description': ch_cfg['description']
            }
            
            # Create the channel
            success = self.channel_manager.create_channel(
                ssrc=channel_spec['ssrc'],
                frequency_hz=channel_spec['frequency_hz'],
                preset=channel_spec['preset'],
                sample_rate=channel_spec['sample_rate'],
                agc=channel_spec['agc'],
                gain=channel_spec['gain'],
                description=channel_spec['description']
            )
            
            if success:
                logger.info(f"✓ Successfully recreated channel {ch_cfg['description']}")
                # Reset processor packet timer to avoid immediate re-trigger
                if ssrc in self.channels:
                    self.channels[ssrc].reset_health()
            else:
                logger.error(f"✗ Failed to recreate channel {ch_cfg['description']}")
                
        except Exception as e:
            logger.error(f"Channel recreation exception for SSRC {ssrc:x}: {e}", exc_info=True)
    
    def _shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down core recorder...")
        
        # Stop RTP receiver
        self.rtp_receiver.stop()
        
        # Flush all channels
        for ssrc, processor in self.channels.items():
            try:
                processor.flush()
            except Exception as e:
                logger.error(f"Error flushing channel {ssrc}: {e}")
        
        logger.info("Core recorder stopped")


class ChannelProcessor:
    """
    Per-channel packet processing
    
    Handles:
    - RTP packet parsing
    - Packet resequencing
    - Gap detection and filling
    - NPZ archive writing
    """
    
    def __init__(self, ssrc: int, frequency_hz: float, sample_rate: int,
                 description: str, output_dir: Path, station_config: dict):
        """Initialize channel processor"""
        self.ssrc = ssrc
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.description = description
        
        # Components
        self.resequencer = PacketResequencer(
            buffer_size=64,
            samples_per_packet=320  # Standard for 16 kHz IQ
        )
        
        self.npz_writer = CoreNPZWriter(
            output_dir=output_dir,
            channel_name=description,
            frequency_hz=frequency_hz,
            sample_rate=sample_rate,
            ssrc=ssrc,
            station_config=station_config
        )
        
        # State
        self.packets_received = 0
        self.current_sample_index = 0
        self.last_packet_time = 0  # For health monitoring
        
        logger.info(f"ChannelProcessor initialized: {description} (SSRC {ssrc})")
    
    def process_rtp_packet(self, header, payload: bytes):
        """
        Process incoming RTP packet
        
        This is the callback registered with RTPReceiver.
        Never crashes - just logs errors and continues.
        
        Args:
            header: RTPHeader object from grape_rtp_recorder.py
            payload: RTP payload bytes (IQ samples)
        """
        try:
            self.packets_received += 1
            self.last_packet_time = time.time()  # Update health timestamp
            
            # Extract header fields
            sequence = header.sequence
            timestamp = header.timestamp
            ssrc = header.ssrc
            
            # Verify SSRC (should match due to callback registration, but check anyway)
            if ssrc != self.ssrc:
                logger.warning(f"{self.description}: SSRC mismatch {ssrc} != {self.ssrc}")
                return
            
            # Convert to complex IQ samples based on payload type
            # PT 120 = int16 IQ (interleaved I, Q, I, Q, ...) - ka9q-radio IQ format
            # PT 11 = float32 IQ (interleaved I, Q, I, Q, ...)
            payload_type = header.payload_type
            
            if payload_type == 120:
                # int16 format: 2 bytes per sample (I or Q)
                if len(payload) % 4 != 0:
                    logger.warning(f"{self.description}: Invalid payload length {len(payload)} for PT 120")
                    return
                
                # Parse as int16 and normalize to float range [-1.0, 1.0]
                samples_int16 = np.frombuffer(payload, dtype=np.int16)
                samples = samples_int16.astype(np.float32) / 32768.0
                
            elif payload_type == 11:
                # float32 format: 4 bytes per sample (I or Q)
                if len(payload) % 8 != 0:
                    logger.warning(f"{self.description}: Invalid payload length {len(payload)} for PT 11")
                    return
                
                samples = np.frombuffer(payload, dtype=np.float32)
                
            else:
                logger.warning(f"{self.description}: Unknown payload type {payload_type}, assuming float32")
                if len(payload) % 8 != 0:
                    logger.warning(f"{self.description}: Invalid payload length {len(payload)}")
                    return
                samples = np.frombuffer(payload, dtype=np.float32)
            
            i_samples = samples[0::2]
            q_samples = samples[1::2]
            iq_samples = (i_samples + 1j * q_samples).astype(np.complex64)
            
            # Create RTP packet object
            rtp_pkt = RTPPacket(
                sequence=sequence,
                timestamp=timestamp,
                ssrc=ssrc,
                samples=iq_samples
            )
            
            # Resequence (handles out-of-order, detects gaps)
            output_samples, gap_info = self.resequencer.process_packet(rtp_pkt)
            
            if output_samples is None:
                # Buffering - no output yet
                return
            
            # Create gap record if gap was detected
            gap_record = None
            if gap_info:
                gap_record = GapRecord(
                    rtp_timestamp=gap_info.expected_timestamp,
                    sample_index=self.current_sample_index,
                    samples_filled=gap_info.gap_samples,
                    packets_lost=gap_info.gap_packets
                )
            
            # Write to NPZ archive
            result = self.npz_writer.add_samples(
                rtp_timestamp=timestamp,
                samples=output_samples,
                gap_record=gap_record
            )
            
            # Update sample index
            self.current_sample_index += len(output_samples)
            
            if result:
                minute_ts, file_path = result
                logger.debug(f"{self.description}: Wrote {file_path.name}")
        
        except Exception as e:
            # NEVER crash - just log error and continue
            logger.error(f"{self.description}: Error processing packet: {e}", exc_info=True)
    
    def flush(self):
        """Flush remaining data (for shutdown)"""
        logger.info(f"{self.description}: Flushing remaining data...")
        
        # Flush resequencer
        buffered = self.resequencer.flush()
        for samples, gap_info in buffered:
            gap_record = None
            if gap_info:
                gap_record = GapRecord(
                    rtp_timestamp=gap_info.expected_timestamp,
                    sample_index=self.current_sample_index,
                    samples_filled=gap_info.gap_samples,
                    packets_lost=gap_info.gap_packets
                )
            
            self.npz_writer.add_samples(
                rtp_timestamp=self.resequencer.last_output_ts or 0,
                samples=samples,
                gap_record=gap_record
            )
            
            self.current_sample_index += len(samples)
        
        # Flush NPZ writer
        self.npz_writer.flush()
        
        logger.info(f"{self.description}: Flush complete")
    
    def get_stats(self) -> dict:
        """Get channel statistics (for logging)"""
        reseq_stats = self.resequencer.get_stats()
        return {
            'packets_received': self.packets_received,
            'minutes_written': self.npz_writer.minutes_written,
            'gaps_detected': reseq_stats['gaps_detected'],
            'samples_filled': reseq_stats['samples_filled']
        }
    
    def get_status(self) -> dict:
        """Get detailed channel status for web-ui"""
        reseq_stats = self.resequencer.get_stats()
        last_packet_time = datetime.fromtimestamp(self.last_packet_time, timezone.utc).isoformat() if self.last_packet_time > 0 else None
        
        return {
            'ssrc': hex(self.ssrc),
            'channel_name': self.description,
            'frequency_hz': self.frequency_hz,
            'sample_rate': self.sample_rate,
            'packets_received': self.packets_received,
            'npz_files_written': self.npz_writer.minutes_written,
            'last_npz_file': str(self.npz_writer.last_file_written) if hasattr(self.npz_writer, 'last_file_written') else None,
            'gaps_detected': reseq_stats['gaps_detected'],
            'total_gap_samples': reseq_stats['samples_filled'],
            'status': 'recording' if self.packets_received > 0 else 'idle',
            'last_packet_time': last_packet_time
        }
    
    def is_healthy(self, timeout_sec: float = 120.0) -> bool:
        """
        Check if channel is receiving packets.
        
        Args:
            timeout_sec: Maximum silence duration before considered unhealthy
            
        Returns:
            True if packets received within timeout, False if silent too long
        """
        if self.last_packet_time == 0:
            # Never received any packets - give it time to start
            return True
        
        silence_duration = time.time() - self.last_packet_time
        return silence_duration < timeout_sec
    
    def get_silence_duration(self) -> float:
        """Get seconds since last packet received"""
        if self.last_packet_time == 0:
            return 0.0
        return time.time() - self.last_packet_time
    
    def reset_health(self):
        """Reset health timestamp (after channel recreation)"""
        self.last_packet_time = time.time()
        logger.debug(f"{self.description}: Health timer reset")


def main():
    """Entry point for core recorder"""
    import toml
    import argparse
    
    parser = argparse.ArgumentParser(description='GRAPE Core Recorder')
    parser.add_argument('--config', required=True, help='Configuration file (TOML)')
    args = parser.parse_args()
    
    # Load TOML configuration
    toml_config = toml.load(args.config)
    
    # Setup logging
    log_level = toml_config.get('logging', {}).get('level', 'INFO')
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Transform TOML config to CoreRecorder format
    recorder_config = toml_config.get('recorder', {})
    mode = recorder_config.get('mode', 'test')
    
    # Determine output directory based on mode
    if mode == 'production':
        output_dir = recorder_config.get('production_data_root', '/var/lib/signal-recorder')
    else:
        output_dir = recorder_config.get('test_data_root', '/tmp/grape-test')
    
    # Get KA9Q multicast info
    ka9q_config = toml_config.get('ka9q', {})
    status_address = ka9q_config.get('status_address', 'bee1-hf-status.local')
    
    # Resolve status address to multicast group
    # For KA9Q, the default multicast group is 239.1.2.X where X depends on config
    # Default to standard group
    multicast_address = '239.1.2.55'  # Standard KA9Q multicast group
    
    # Build config dict for CoreRecorder
    config = {
        'output_dir': output_dir,
        'multicast_address': multicast_address,
        'port': 5004,
        'status_address': status_address,  # For channel management
        'station': toml_config.get('station', {}),
        'channels': recorder_config.get('channels', [])
    }
    
    logger.info(f"Starting in {mode.upper()} mode")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Multicast: {multicast_address}:5004")
    logger.info(f"Channels configured: {len(config['channels'])}")
    
    # Create and run recorder
    recorder = CoreRecorder(config)
    recorder.run()


if __name__ == '__main__':
    main()
