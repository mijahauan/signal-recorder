"""
Upload manager module

Handles reliable upload of processed datasets to remote repositories.
"""

import subprocess
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json

logger = logging.getLogger(__name__)


@dataclass
class UploadTask:
    """Represents an upload task in the queue"""
    dataset_path: str
    remote_path: str
    metadata: Dict
    status: str = "pending"  # pending, uploading, completed, failed
    attempts: int = 0
    last_attempt: Optional[str] = None
    created_at: str = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UploadTask':
        """Create from dictionary"""
        return cls(**data)


class UploadProtocol(ABC):
    """Base class for upload protocols"""
    
    @abstractmethod
    def upload(self, local_path: Path, remote_path: str, metadata: Dict) -> bool:
        """
        Upload dataset
        
        Args:
            local_path: Local path to dataset
            remote_path: Remote path (protocol-specific)
            metadata: Additional metadata
            
        Returns:
            True if upload successful
        """
        pass
    
    @abstractmethod
    def verify(self, remote_path: str) -> bool:
        """
        Verify upload completed successfully
        
        Args:
            remote_path: Remote path to verify
            
        Returns:
            True if verified
        """
        pass


class SSHRsyncUpload(UploadProtocol):
    """Upload via SSH/rsync (for HamSCI PSWS)"""
    
    def __init__(self, config: Dict):
        """
        Initialize SSH/rsync uploader
        
        Args:
            config: Upload configuration
        """
        self.host = config['host']
        self.user = config['user']
        self.base_path = config.get('base_path', '/data/uploads')
        self.ssh_key = config.get('ssh', {}).get('key_file')
        self.bandwidth_limit = config.get('bandwidth_limit')  # KB/s
        self.timeout = config.get('timeout', 3600)  # seconds
    
    def upload(self, local_path: Path, remote_path: str, metadata: Dict) -> bool:
        """
        Upload using rsync over SSH
        
        Args:
            local_path: Local path to upload
            remote_path: Remote path relative to base_path
            metadata: Additional metadata
            
        Returns:
            True if successful
        """
        full_remote_path = f"{self.user}@{self.host}:{self.base_path}/{remote_path}"
        
        logger.info(f"Uploading {local_path} to {full_remote_path}")
        
        # Build rsync command
        cmd = ["rsync", "-avz", "--progress"]
        
        # Add SSH key if specified
        if self.ssh_key:
            cmd.extend(["-e", f"ssh -i {self.ssh_key}"])
        
        # Add bandwidth limit if specified
        if self.bandwidth_limit:
            cmd.extend(["--bwlimit", str(self.bandwidth_limit)])
        
        # Add timeout
        cmd.extend(["--timeout", str(self.timeout)])
        
        # Add source and destination
        # If directory, add trailing slash
        source = str(local_path)
        if local_path.is_dir():
            source += "/"
        
        cmd.extend([source, full_remote_path])
        
        logger.debug(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            logger.info(f"Upload successful: {local_path}")
            logger.debug(f"rsync output: {result.stdout}")
            return True
        
        except subprocess.CalledProcessError as e:
            logger.error(f"rsync failed: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"rsync timeout after {self.timeout} seconds")
            return False
        except Exception as e:
            logger.error(f"Upload error: {e}")
            return False
    
    def verify(self, remote_path: str) -> bool:
        """
        Verify upload by checking if remote path exists
        
        Args:
            remote_path: Remote path to verify
            
        Returns:
            True if exists
        """
        full_remote_path = f"{self.base_path}/{remote_path}"
        
        # Build SSH command to test if path exists
        cmd = ["ssh"]
        
        if self.ssh_key:
            cmd.extend(["-i", self.ssh_key])
        
        cmd.extend([
            f"{self.user}@{self.host}",
            "test", "-e", full_remote_path
        ])
        
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Verification error: {e}")
            return False


class UploadManager:
    """Manages upload queue and retry logic"""
    
    def __init__(self, config: Dict, storage_manager):
        """
        Initialize upload manager
        
        Args:
            config: Upload configuration
            storage_manager: StorageManager instance
        """
        self.config = config
        self.storage_manager = storage_manager
        self.protocol = self._create_protocol()
        self.max_retries = config.get('max_retries', 5)
        self.retry_backoff_base = config.get('retry_backoff_base', 2)
        self.queue_file = Path(config.get('queue_file', '/var/lib/signal-recorder/upload_queue.json'))
        self.queue: List[UploadTask] = []
        
        # Load queue from disk
        self._load_queue()
    
    def _create_protocol(self) -> UploadProtocol:
        """Create upload protocol instance"""
        protocol_type = self.config.get('protocol', 'ssh_rsync')
        
        if protocol_type == 'ssh_rsync':
            return SSHRsyncUpload(self.config)
        else:
            raise ValueError(f"Unknown upload protocol: {protocol_type}")
    
    def _load_queue(self):
        """Load upload queue from disk"""
        if self.queue_file.exists():
            try:
                with open(self.queue_file, 'r') as f:
                    data = json.load(f)
                self.queue = [UploadTask.from_dict(item) for item in data]
                logger.info(f"Loaded {len(self.queue)} tasks from queue")
            except Exception as e:
                logger.error(f"Error loading queue: {e}")
                self.queue = []
        else:
            self.queue = []
    
    def _save_queue(self):
        """Save upload queue to disk"""
        try:
            self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.queue_file, 'w') as f:
                data = [task.to_dict() for task in self.queue]
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving queue: {e}")
    
    def enqueue(self, dataset_path: Path, metadata: Dict):
        """
        Add dataset to upload queue
        
        Args:
            dataset_path: Path to dataset
            metadata: Metadata (date, band, station_id, etc.)
        """
        # Construct remote path
        # Format: {date}/{reporter_grid}/{receiver@psws_id}/
        date = metadata['date']
        reporter = f"{metadata['callsign']}_{metadata['grid_square']}"
        receiver = f"KA9Q_0@{metadata['station_id']}_{metadata['instrument_id']}"
        
        remote_path = f"{date}/{reporter}/{receiver}/{dataset_path.name}"
        
        # Create task
        task = UploadTask(
            dataset_path=str(dataset_path),
            remote_path=remote_path,
            metadata=metadata
        )
        
        # Check if already in queue
        for existing in self.queue:
            if existing.dataset_path == task.dataset_path:
                logger.warning(f"Dataset already in queue: {dataset_path}")
                return
        
        self.queue.append(task)
        self._save_queue()
        
        logger.info(f"Enqueued upload: {dataset_path} → {remote_path}")
    
    def process_queue(self):
        """Process upload queue with retry logic"""
        if not self.queue:
            logger.debug("Upload queue is empty")
            return
        
        logger.info(f"Processing upload queue ({len(self.queue)} tasks)")
        
        for task in self.queue[:]:  # Iterate over copy
            if task.status == "completed":
                continue
            
            # Check if we should retry
            if task.attempts >= self.max_retries:
                logger.error(f"Max retries exceeded for {task.dataset_path}")
                task.status = "failed"
                self._save_queue()
                continue
            
            # Exponential backoff
            if task.last_attempt:
                last_attempt_time = datetime.fromisoformat(task.last_attempt)
                wait_time = self.retry_backoff_base ** task.attempts * 60  # minutes
                elapsed = (datetime.now(timezone.utc) - last_attempt_time).total_seconds()
                
                if elapsed < wait_time:
                    logger.debug(f"Waiting {wait_time - elapsed:.0f}s before retry for {task.dataset_path}")
                    continue
            
            # Attempt upload
            self._attempt_upload(task)
            self._save_queue()
    
    def _attempt_upload(self, task: UploadTask):
        """
        Attempt to upload a task
        
        Args:
            task: UploadTask to upload
        """
        task.status = "uploading"
        task.attempts += 1
        task.last_attempt = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"Upload attempt {task.attempts}/{self.max_retries}: {task.dataset_path}")
        
        try:
            dataset_path = Path(task.dataset_path)
            
            if not dataset_path.exists():
                logger.error(f"Dataset not found: {dataset_path}")
                task.status = "failed"
                task.error_message = "Dataset not found"
                return
            
            # Perform upload
            success = self.protocol.upload(dataset_path, task.remote_path, task.metadata)
            
            if success:
                # Verify upload
                if self.protocol.verify(task.remote_path):
                    logger.info(f"Upload verified: {task.dataset_path}")
                    task.status = "completed"
                    task.completed_at = datetime.now(timezone.utc).isoformat()
                    
                    # Mark in storage manager
                    if 'date' in task.metadata and 'band' in task.metadata:
                        self.storage_manager.mark_upload_complete(
                            task.metadata['date'],
                            task.metadata['band']
                        )
                else:
                    logger.warning(f"Upload verification failed: {task.dataset_path}")
                    task.status = "pending"
                    task.error_message = "Verification failed"
            else:
                logger.error(f"Upload failed: {task.dataset_path}")
                task.status = "pending"
                task.error_message = "Upload failed"
            
            # Mark upload attempt in storage manager
            if 'date' in task.metadata and 'band' in task.metadata:
                self.storage_manager.mark_upload_attempted(
                    task.metadata['date'],
                    task.metadata['band']
                )
        
        except Exception as e:
            logger.error(f"Upload error: {e}", exc_info=True)
            task.status = "pending"
            task.error_message = str(e)
    
    def get_status(self) -> Dict:
        """Get upload queue status"""
        status = {
            'total': len(self.queue),
            'pending': 0,
            'uploading': 0,
            'completed': 0,
            'failed': 0
        }
        
        for task in self.queue:
            status[task.status] += 1
        
        return status
    
    def clear_completed(self):
        """Remove completed tasks from queue"""
        original_count = len(self.queue)
        self.queue = [task for task in self.queue if task.status != "completed"]
        removed = original_count - len(self.queue)
        
        if removed > 0:
            logger.info(f"Removed {removed} completed tasks from queue")
            self._save_queue()

