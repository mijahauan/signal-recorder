"""
Session Boundary Tracking

Detects and logs when the recorder daemon was offline, creating
RECORDER_OFFLINE discontinuities for complete data provenance.
"""

import os
import json
import glob
import logging
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List
from .interfaces.data_models import Discontinuity, DiscontinuityType

logger = logging.getLogger(__name__)


class SessionBoundaryTracker:
    """
    Track recorder session boundaries to detect offline periods.
    
    When the recorder starts, checks for gaps since the last session ended.
    Logs session boundaries to a persistent file for cross-session analysis.
    """
    
    def __init__(self, archive_dir: Path, channel_name: str, sample_rate: int):
        """
        Initialize session tracker.
        
        Args:
            archive_dir: Base directory for archived data
            channel_name: Channel identifier (e.g., "WWV 5.0 MHz")
            sample_rate: Sample rate in Hz (for gap magnitude calculation)
        """
        self.archive_dir = Path(archive_dir)
        self.channel_name = channel_name
        self.sample_rate = sample_rate
        self.session_log_file = self.archive_dir / 'session_boundaries.jsonl'
        self.logger = logging.getLogger(f"{__name__}.{channel_name}")
        
        # Ensure archive directory exists
        self.archive_dir.mkdir(parents=True, exist_ok=True)
    
    def check_for_offline_gap(self, current_start_time: float) -> Optional[Discontinuity]:
        """
        Check if there's a gap from the last session.
        
        Args:
            current_start_time: UTC timestamp when current session started
            
        Returns:
            Discontinuity object if offline gap detected, None otherwise
        """
        try:
            last_session_end = self._get_last_session_end_time()
            
            if last_session_end is None:
                self.logger.info("No previous session found - first run for this channel")
                return None
            
            # Calculate gap
            gap_duration = current_start_time - last_session_end
            
            # Only consider it an offline gap if >2 minutes
            # Shorter gaps might be normal restarts
            if gap_duration < 120:
                self.logger.debug(f"Short gap ({gap_duration:.1f}s) from last session - ignoring")
                return None
            
            self.logger.warning(
                f"Detected recorder offline gap: {gap_duration/3600:.2f} hours "
                f"(last session ended {datetime.fromtimestamp(last_session_end).isoformat()})"
            )
            
            # Create RECORDER_OFFLINE discontinuity
            discontinuity = Discontinuity(
                timestamp=last_session_end,
                sample_index=0,  # New session, starting from 0
                discontinuity_type=DiscontinuityType.RECORDER_OFFLINE,
                magnitude_samples=int(gap_duration * self.sample_rate),
                magnitude_ms=gap_duration * 1000,
                rtp_sequence_before=None,  # Not applicable - daemon was off
                rtp_sequence_after=None,
                rtp_timestamp_before=None,
                rtp_timestamp_after=None,
                wwv_related=False,
                explanation=(
                    f"Recorder was offline for {gap_duration/3600:.2f} hours. "
                    f"Previous session ended {datetime.fromtimestamp(last_session_end).isoformat()}, "
                    f"current session started {datetime.fromtimestamp(current_start_time).isoformat()}. "
                    f"Possible causes: daemon stopped, power outage, system maintenance, development testing."
                )
            )
            
            # Log to persistent session boundary file
            self._log_session_boundary(last_session_end, current_start_time, discontinuity)
            
            return discontinuity
            
        except Exception as e:
            self.logger.error(f"Error checking for offline gap: {e}")
            return None
    
    def _get_last_session_end_time(self) -> Optional[float]:
        """
        Find the end time of the most recent previous session.
        
        Looks for the latest archive file and extracts its end timestamp.
        
        Returns:
            UTC timestamp of last session end, or None if no previous session
        """
        # Channel directory name (spaces replaced with underscores)
        channel_dir = self.archive_dir / self.channel_name.replace(' ', '_')
        
        if not channel_dir.exists():
            return None
        
        # Find all NPZ files
        npz_files = sorted(glob.glob(str(channel_dir / '*.npz')))
        
        if not npz_files:
            return None
        
        # Load most recent file
        last_file = npz_files[-1]
        
        try:
            data = np.load(last_file, allow_pickle=True)
            
            # Get timestamp and calculate end time
            start_timestamp = float(data['timestamp'])
            num_samples = len(data['samples'])
            end_timestamp = start_timestamp + (num_samples / self.sample_rate)
            
            self.logger.debug(
                f"Last session file: {os.path.basename(last_file)}, "
                f"ended at {datetime.fromtimestamp(end_timestamp).isoformat()}"
            )
            
            return end_timestamp
            
        except Exception as e:
            self.logger.error(f"Error reading last session file {last_file}: {e}")
            return None
    
    def _log_session_boundary(
        self,
        last_end: float,
        current_start: float,
        discontinuity: Discontinuity
    ):
        """
        Log session boundary to persistent file.
        
        Uses JSON Lines format for easy append and analysis.
        
        Args:
            last_end: Timestamp when last session ended
            current_start: Timestamp when current session started
            discontinuity: The RECORDER_OFFLINE discontinuity object
        """
        try:
            record = {
                'channel': self.channel_name,
                'gap_type': 'RECORDER_OFFLINE',
                'previous_session_end': last_end,
                'previous_session_end_str': datetime.fromtimestamp(last_end).isoformat(),
                'current_session_start': current_start,
                'current_session_start_str': datetime.fromtimestamp(current_start).isoformat(),
                'gap_duration_sec': discontinuity.magnitude_ms / 1000,
                'gap_duration_hours': discontinuity.magnitude_ms / 3600000,
                'explanation': discontinuity.explanation,
                'detected_at': datetime.now().isoformat()
            }
            
            with open(self.session_log_file, 'a') as f:
                f.write(json.dumps(record) + '\n')
            
            self.logger.info(f"Logged session boundary to {self.session_log_file}")
            
        except Exception as e:
            self.logger.error(f"Error logging session boundary: {e}")
    
    def get_session_history(self, days: int = 7) -> List[Dict]:
        """
        Read session boundary history from log file.
        
        Args:
            days: How many days of history to retrieve
            
        Returns:
            List of session boundary records (most recent first)
        """
        if not self.session_log_file.exists():
            return []
        
        try:
            records = []
            cutoff_time = datetime.now().timestamp() - (days * 86400)
            
            with open(self.session_log_file, 'r') as f:
                for line in f:
                    record = json.loads(line)
                    
                    # Filter by channel and time
                    if (record.get('channel') == self.channel_name and
                        record.get('current_session_start', 0) >= cutoff_time):
                        records.append(record)
            
            # Sort by session start time (most recent first)
            records.sort(key=lambda r: r.get('current_session_start', 0), reverse=True)
            
            return records
            
        except Exception as e:
            self.logger.error(f"Error reading session history: {e}")
            return []
