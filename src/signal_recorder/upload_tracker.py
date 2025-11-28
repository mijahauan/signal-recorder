#!/usr/bin/env python3
"""
Upload Tracker - Track successful DRF uploads to PSWS

Maintains a JSON state file with upload history, enabling:
- Skip already-uploaded dates
- Retry failed uploads
- Audit trail of uploads
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class UploadRecord:
    """Record of a single upload attempt"""
    date: str                    # YYYY-MM-DD
    uploaded_at: str             # ISO timestamp
    status: str                  # 'success', 'failed', 'partial'
    channels: int                # Number of channels uploaded
    obs_dir: str                 # OBS directory name
    trigger_dir: str             # Trigger directory created on PSWS
    bytes_uploaded: int          # Total bytes uploaded
    duration_seconds: float      # Upload duration
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UploadRecord':
        return cls(**data)


class UploadTracker:
    """
    Tracks upload status in a JSON state file
    
    State file structure:
    {
        "version": 1,
        "station_id": "S000171",
        "last_successful_date": "2025-11-28",
        "uploads": [
            {
                "date": "2025-11-28",
                "uploaded_at": "2025-11-29T00:35:42Z",
                ...
            }
        ]
    }
    """
    
    VERSION = 1
    
    def __init__(self, state_file: Path, station_id: str):
        self.state_file = Path(state_file)
        self.station_id = station_id
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load state from file or create new"""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                logger.info(f"Loaded upload state: {len(state.get('uploads', []))} records")
                return state
            except Exception as e:
                logger.warning(f"Could not load state file: {e}")
        
        # Create new state
        return {
            'version': self.VERSION,
            'station_id': self.station_id,
            'last_successful_date': None,
            'uploads': []
        }
    
    def _save_state(self):
        """Save state to file"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.debug(f"Saved upload state to {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def is_date_uploaded(self, date_str: str) -> bool:
        """Check if a date has been successfully uploaded"""
        for record in self.state['uploads']:
            if record['date'] == date_str and record['status'] == 'success':
                return True
        return False
    
    def get_upload_record(self, date_str: str) -> Optional[UploadRecord]:
        """Get the most recent upload record for a date"""
        for record in reversed(self.state['uploads']):
            if record['date'] == date_str:
                return UploadRecord.from_dict(record)
        return None
    
    def get_last_successful_date(self) -> Optional[str]:
        """Get the most recent successfully uploaded date"""
        return self.state.get('last_successful_date')
    
    def get_pending_dates(self, start_date: str, end_date: str) -> List[str]:
        """Get dates in range that haven't been successfully uploaded"""
        from datetime import datetime, timedelta
        
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        pending = []
        current = start
        while current <= end:
            date_str = current.strftime('%Y-%m-%d')
            if not self.is_date_uploaded(date_str):
                pending.append(date_str)
            current += timedelta(days=1)
        
        return pending
    
    def record_upload(
        self,
        date_str: str,
        status: str,
        channels: int,
        obs_dir: str,
        trigger_dir: str,
        bytes_uploaded: int,
        duration_seconds: float,
        error_message: Optional[str] = None
    ):
        """Record an upload attempt"""
        record = UploadRecord(
            date=date_str,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            status=status,
            channels=channels,
            obs_dir=obs_dir,
            trigger_dir=trigger_dir,
            bytes_uploaded=bytes_uploaded,
            duration_seconds=duration_seconds,
            error_message=error_message
        )
        
        self.state['uploads'].append(record.to_dict())
        
        if status == 'success':
            # Update last successful date if this is newer
            if (self.state['last_successful_date'] is None or 
                date_str > self.state['last_successful_date']):
                self.state['last_successful_date'] = date_str
        
        self._save_state()
        
        logger.info(f"Recorded upload: {date_str} -> {status}")
        return record
    
    def get_statistics(self) -> Dict:
        """Get upload statistics"""
        uploads = self.state['uploads']
        
        successful = [u for u in uploads if u['status'] == 'success']
        failed = [u for u in uploads if u['status'] == 'failed']
        
        total_bytes = sum(u['bytes_uploaded'] for u in successful)
        total_duration = sum(u['duration_seconds'] for u in successful)
        
        return {
            'total_uploads': len(uploads),
            'successful': len(successful),
            'failed': len(failed),
            'total_bytes_uploaded': total_bytes,
            'total_duration_seconds': total_duration,
            'last_successful_date': self.state.get('last_successful_date'),
            'unique_dates': len(set(u['date'] for u in successful))
        }
    
    def cleanup_old_records(self, keep_days: int = 90):
        """Remove upload records older than keep_days"""
        from datetime import datetime, timedelta
        
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        
        original_count = len(self.state['uploads'])
        self.state['uploads'] = [
            u for u in self.state['uploads']
            if u['uploaded_at'] >= cutoff or u['status'] == 'success'
        ]
        
        removed = original_count - len(self.state['uploads'])
        if removed > 0:
            self._save_state()
            logger.info(f"Cleaned up {removed} old upload records")
        
        return removed


# Convenience functions for shell script integration
def check_uploaded(state_file: str, station_id: str, date: str) -> bool:
    """Check if a date has been uploaded (for shell scripts)"""
    tracker = UploadTracker(Path(state_file), station_id)
    return tracker.is_date_uploaded(date)


def record_success(
    state_file: str,
    station_id: str,
    date: str,
    channels: int,
    obs_dir: str,
    trigger_dir: str,
    bytes_uploaded: int,
    duration_seconds: float
):
    """Record a successful upload (for shell scripts)"""
    tracker = UploadTracker(Path(state_file), station_id)
    tracker.record_upload(
        date_str=date,
        status='success',
        channels=channels,
        obs_dir=obs_dir,
        trigger_dir=trigger_dir,
        bytes_uploaded=bytes_uploaded,
        duration_seconds=duration_seconds
    )


def record_failure(
    state_file: str,
    station_id: str,
    date: str,
    error_message: str
):
    """Record a failed upload (for shell scripts)"""
    tracker = UploadTracker(Path(state_file), station_id)
    tracker.record_upload(
        date_str=date,
        status='failed',
        channels=0,
        obs_dir='',
        trigger_dir='',
        bytes_uploaded=0,
        duration_seconds=0,
        error_message=error_message
    )


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Upload Tracker CLI')
    parser.add_argument('--state-file', required=True, type=Path)
    parser.add_argument('--station-id', required=True)
    
    subparsers = parser.add_subparsers(dest='command')
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check if date is uploaded')
    check_parser.add_argument('--date', required=True)
    
    # Record command
    record_parser = subparsers.add_parser('record', help='Record upload')
    record_parser.add_argument('--date', required=True)
    record_parser.add_argument('--status', required=True, choices=['success', 'failed'])
    record_parser.add_argument('--channels', type=int, default=0)
    record_parser.add_argument('--obs-dir', default='')
    record_parser.add_argument('--trigger-dir', default='')
    record_parser.add_argument('--bytes', type=int, default=0)
    record_parser.add_argument('--duration', type=float, default=0)
    record_parser.add_argument('--error', default=None)
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show statistics')
    
    # Pending command
    pending_parser = subparsers.add_parser('pending', help='List pending dates')
    pending_parser.add_argument('--start', required=True)
    pending_parser.add_argument('--end', required=True)
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    tracker = UploadTracker(args.state_file, args.station_id)
    
    if args.command == 'check':
        uploaded = tracker.is_date_uploaded(args.date)
        print('true' if uploaded else 'false')
        exit(0 if uploaded else 1)
    
    elif args.command == 'record':
        tracker.record_upload(
            date_str=args.date,
            status=args.status,
            channels=args.channels,
            obs_dir=args.obs_dir,
            trigger_dir=args.trigger_dir,
            bytes_uploaded=args.bytes,
            duration_seconds=args.duration,
            error_message=args.error
        )
        print(f"Recorded: {args.date} -> {args.status}")
    
    elif args.command == 'stats':
        stats = tracker.get_statistics()
        print(json.dumps(stats, indent=2))
    
    elif args.command == 'pending':
        pending = tracker.get_pending_dates(args.start, args.end)
        for date in pending:
            print(date)
