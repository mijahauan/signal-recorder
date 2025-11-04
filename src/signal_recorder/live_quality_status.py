#!/usr/bin/env python3
"""
Live Quality Status Writer

Writes real-time quality metrics to JSON for web UI monitoring
"""

import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)


class LiveQualityStatus:
    """
    Maintains live quality status for web UI
    
    Updates a JSON file every N seconds with current recording quality
    """
    
    def __init__(self, status_file: Path, update_interval: int = 5):
        """
        Initialize live status writer
        
        Args:
            status_file: Path to JSON status file
            update_interval: Seconds between updates
        """
        self.status_file = Path(status_file)
        self.update_interval = update_interval
        self.last_update = 0
        
        # Per-channel status
        self.channels: Dict[str, dict] = {}
        
        # System-wide status
        self.system_status = {
            'start_time': time.time(),
            'last_update': 0,
            'channels_active': 0,
            'total_packets': 0,
            'total_gaps': 0
        }
        
        logger.info(f"Live quality status initialized: {status_file}")
    
    def update_channel(self, channel_name: str, metrics: dict):
        """
        Update metrics for a channel
        
        Args:
            channel_name: Channel name
            metrics: Dictionary with current metrics
        """
        now = time.time()
        
        # Initialize channel if new
        if channel_name not in self.channels:
            self.channels[channel_name] = {
                'name': channel_name,
                'frequency_hz': metrics.get('frequency_hz', 0),
                'first_seen': now,
                'last_update': now,
                'status': 'active',
                
                # Cumulative counters
                'total_packets': 0,
                'total_packets_dropped': 0,
                'total_samples': 0,
                'minutes_written': 0,
                'total_gaps': 0,
                
                # Current minute
                'current_minute_packets': 0,
                'current_minute_samples': 0,
                'current_minute_completeness': 100.0,
                
                # Recent history (last 60 data points)
                'history_completeness': deque(maxlen=60),
                'history_packet_loss': deque(maxlen=60),
                'history_timestamps': deque(maxlen=60),
                
                # WWV timing (if applicable)
                'wwv_enabled': False,
                'wwv_last_detection': None,
                'wwv_last_error_ms': None,
                'wwv_detections_today': 0
            }
        
        channel = self.channels[channel_name]
        
        # Update cumulative counters
        channel['total_packets'] = metrics.get('total_packets', channel['total_packets'])
        channel['total_packets_dropped'] = metrics.get('packets_dropped', channel['total_packets_dropped'])
        channel['total_samples'] = metrics.get('total_samples', channel['total_samples'])
        channel['minutes_written'] = metrics.get('minutes_written', channel['minutes_written'])
        
        # Update current minute
        channel['current_minute_packets'] = metrics.get('current_minute_packets', 0)
        channel['current_minute_samples'] = metrics.get('current_minute_samples', 0)
        
        # Use minute_progress if provided, otherwise calculate (but cap at 100%)
        if 'minute_progress_percent' in metrics:
            channel['minute_progress_percent'] = metrics['minute_progress_percent']
        else:
            expected_samples = metrics.get('expected_samples_per_minute', 480000)
            if expected_samples > 0:
                progress = (channel['current_minute_samples'] / expected_samples * 100)
                channel['minute_progress_percent'] = min(progress, 100.0)
            else:
                channel['minute_progress_percent'] = 0.0
        
        # Keep old completeness for history compatibility  
        channel['current_minute_completeness'] = channel['minute_progress_percent']
        
        # RTP status
        channel['last_rtp_sequence'] = metrics.get('last_rtp_sequence')
        channel['last_rtp_timestamp'] = metrics.get('last_rtp_timestamp')
        channel['rtp_timing_deviation_ms'] = metrics.get('rtp_timing_deviation_ms', 0.0)
        
        # Calculate packet loss percentage
        total_pkts = channel['total_packets'] + channel['total_packets_dropped']
        packet_loss_pct = (channel['total_packets_dropped'] / total_pkts * 100) if total_pkts > 0 else 0.0
        
        # Add to history
        channel['history_completeness'].append(channel['current_minute_completeness'])
        channel['history_packet_loss'].append(packet_loss_pct)
        channel['history_timestamps'].append(now)
        
        # WWV timing (if applicable)
        wwv_data = metrics.get('wwv')
        if wwv_data:
            channel['wwv_enabled'] = wwv_data.get('enabled', False)
            channel['wwv_last_detection'] = wwv_data.get('last_detection')
            channel['wwv_last_error_ms'] = wwv_data.get('last_error_ms')
            channel['wwv_detections_today'] = wwv_data.get('detections_today', 0)
        
        # Determine status
        if packet_loss_pct > 1.0:
            channel['status'] = 'error'
        elif packet_loss_pct > 0.1 or channel['current_minute_completeness'] < 99:
            channel['status'] = 'warning'
        else:
            channel['status'] = 'ok'
        
        channel['last_update'] = now
        
        # Update system totals
        self._update_system_status()
        
        # Write to file if interval elapsed
        if now - self.last_update >= self.update_interval:
            self.write_status()
    
    def _update_system_status(self):
        """Update system-wide status"""
        self.system_status['channels_active'] = len([
            c for c in self.channels.values() 
            if time.time() - c['last_update'] < 60
        ])
        self.system_status['total_packets'] = sum(
            c['total_packets'] for c in self.channels.values()
        )
        self.system_status['total_gaps'] = sum(
            c['total_gaps'] for c in self.channels.values()
        )
        self.system_status['last_update'] = time.time()
    
    def write_status(self):
        """Write current status to JSON file"""
        try:
            # Prepare serializable data
            data = {
                'system': {
                    'start_time': self.system_status['start_time'],
                    'last_update': self.system_status['last_update'],
                    'uptime_seconds': time.time() - self.system_status['start_time'],
                    'channels_active': self.system_status['channels_active'],
                    'channels_total': len(self.channels),
                    'total_packets': self.system_status['total_packets'],
                    'total_gaps': self.system_status['total_gaps']
                },
                'channels': {}
            }
            
            # Add channel data
            for name, channel in self.channels.items():
                # Calculate rates
                runtime = time.time() - channel['first_seen']
                packets_per_sec = channel['total_packets'] / runtime if runtime > 0 else 0
                
                total_pkts = channel['total_packets'] + channel['total_packets_dropped']
                packet_loss_pct = (channel['total_packets_dropped'] / total_pkts * 100) if total_pkts > 0 else 0.0
                
                data['channels'][name] = {
                    'name': name,
                    'frequency_hz': channel['frequency_hz'],
                    'frequency_mhz': channel['frequency_hz'] / 1e6,
                    'status': channel['status'],
                    'last_update': channel['last_update'],
                    'last_update_ago': time.time() - channel['last_update'],
                    
                    # Cumulative
                    'total_packets': channel['total_packets'],
                    'total_packets_dropped': channel['total_packets_dropped'],
                    'packet_loss_percent': round(packet_loss_pct, 3),
                    'total_samples': channel['total_samples'],
                    'minutes_written': channel['minutes_written'],
                    'packets_per_second': round(packets_per_sec, 1),
                    
                    # Current minute
                    'current_minute_samples': channel['current_minute_samples'],
                    'current_minute_completeness': round(channel['current_minute_completeness'], 2),
                    
                    # RTP status
                    'last_rtp_sequence': channel.get('last_rtp_sequence'),
                    'last_rtp_timestamp': channel.get('last_rtp_timestamp'),
                    'rtp_timing_deviation_ms': channel.get('rtp_timing_deviation_ms'),
                    
                    # History (for sparklines)
                    'history': {
                        'completeness': list(channel['history_completeness']),
                        'packet_loss': list(channel['history_packet_loss']),
                        'timestamps': list(channel['history_timestamps'])
                    },
                    
                    # WWV
                    'wwv': {
                        'enabled': channel['wwv_enabled'],
                        'last_detection': channel['wwv_last_detection'],
                        'last_error_ms': channel['wwv_last_error_ms'],
                        'detections_today': channel['wwv_detections_today']
                    } if channel['wwv_enabled'] else None
                }
            
            # Write atomically
            temp_file = self.status_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.rename(self.status_file)
            
            self.last_update = time.time()
            
        except Exception as e:
            logger.error(f"Failed to write live status: {e}")
    
    def mark_channel_inactive(self, channel_name: str):
        """Mark a channel as inactive"""
        if channel_name in self.channels:
            self.channels[channel_name]['status'] = 'inactive'
            self.write_status()


# Global instance (singleton pattern)
_live_status: Optional[LiveQualityStatus] = None


def get_live_status(status_file: Optional[Path] = None) -> LiveQualityStatus:
    """Get or create global live status instance"""
    global _live_status
    if _live_status is None:
        if status_file is None:
            raise ValueError("status_file required for first initialization")
        _live_status = LiveQualityStatus(status_file)
    return _live_status
