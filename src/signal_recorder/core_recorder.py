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
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass

from .grape_rtp_recorder import RTPReceiver  # Reuse existing RTP receiver
from .packet_resequencer import PacketResequencer, RTPPacket, GapInfo
from .core_npz_writer import CoreNPZWriter, GapRecord

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
        """
        self.config = config
        self.output_dir = Path(config['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
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
        
        # Graceful shutdown
        self.running = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def run(self):
        """Main run loop"""
        logger.info("Starting GRAPE Core Recorder")
        logger.info("Responsibility: RTP → NPZ archives (no analytics)")
        
        # Start RTP receiver
        self.rtp_receiver.start()
        self.running = True
        
        logger.info("Core recorder running. Press Ctrl+C to stop.")
        
        # Main loop (just keep running, RTP receiver has its own thread)
        try:
            while self.running:
                import time
                time.sleep(1)
                
                # Periodic status logging (every 60 seconds)
                if int(time.time()) % 60 == 0:
                    self._log_status()
        
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        
        finally:
            self._shutdown()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
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
            
            # Extract header fields
            sequence = header.sequence
            timestamp = header.timestamp
            ssrc = header.ssrc
            
            # Verify SSRC (should match due to callback registration, but check anyway)
            if ssrc != self.ssrc:
                logger.warning(f"{self.description}: SSRC mismatch {ssrc} != {self.ssrc}")
                return
            
            # Convert to complex IQ samples
            # Format: interleaved float32 I, Q, I, Q, ...
            if len(payload) % 8 != 0:
                logger.warning(f"{self.description}: Invalid payload length {len(payload)}")
                return
            
            num_samples = len(payload) // 8
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
        """Get channel statistics"""
        reseq_stats = self.resequencer.get_stats()
        return {
            'packets_received': self.packets_received,
            'minutes_written': self.npz_writer.minutes_written,
            'gaps_detected': reseq_stats['gaps_detected'],
            'samples_filled': reseq_stats['samples_filled']
        }


def main():
    """Entry point for core recorder"""
    import toml
    import argparse
    
    parser = argparse.ArgumentParser(description='GRAPE Core Recorder')
    parser.add_argument('--config', required=True, help='Configuration file (TOML)')
    args = parser.parse_args()
    
    # Load configuration
    config = toml.load(args.config)
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run recorder
    recorder = CoreRecorder(config)
    recorder.run()


if __name__ == '__main__':
    main()
