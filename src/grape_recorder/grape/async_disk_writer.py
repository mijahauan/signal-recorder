"""
Async Disk Writer - Non-blocking I/O for RTP Pipeline

Decouples disk writes from the receive loop using a dedicated writer thread.
This prevents disk latency from causing UDP packet loss.

Design:
    - Receive thread queues write requests (fast, non-blocking)
    - Writer thread processes queue (slow disk I/O in background)
    - Memory-mapped buffers minimize copy overhead
"""

import threading
import queue
import logging
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WriteRequest:
    """A request to write data to disk."""
    bin_path: Path
    json_path: Path
    samples: np.ndarray  # Will be copied to prevent mutation
    metadata: dict
    priority: int = 0  # Lower = higher priority


class AsyncDiskWriter:
    """
    Asynchronous disk writer with dedicated I/O thread.
    
    Usage:
        writer = AsyncDiskWriter()
        writer.start()
        
        # Non-blocking write (returns immediately)
        writer.queue_write(bin_path, json_path, samples, metadata)
        
        # Graceful shutdown
        writer.stop()
    """
    
    def __init__(self, max_queue_size: int = 100, num_workers: int = 1):
        """
        Initialize async writer.
        
        Args:
            max_queue_size: Maximum pending writes (prevents memory bloat)
            num_workers: Number of writer threads (1 is usually optimal for HDD)
        """
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        
        # Priority queue for write requests
        self.write_queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_queue_size)
        
        # Worker threads
        self.workers: list[threading.Thread] = []
        self.running = False
        
        # Statistics
        self.writes_queued = 0
        self.writes_completed = 0
        self.writes_failed = 0
        self.queue_full_drops = 0
        self.total_bytes_written = 0
        self._stats_lock = threading.Lock()
        
    def start(self):
        """Start writer threads."""
        if self.running:
            return
            
        self.running = True
        for i in range(self.num_workers):
            t = threading.Thread(target=self._writer_loop, name=f"DiskWriter-{i}", daemon=True)
            t.start()
            self.workers.append(t)
            
        logger.info(f"AsyncDiskWriter started with {self.num_workers} worker(s)")
        
    def stop(self, timeout: float = 10.0):
        """
        Stop writer threads gracefully.
        
        Args:
            timeout: Maximum time to wait for pending writes
        """
        self.running = False
        
        # Signal workers to stop
        for _ in self.workers:
            try:
                self.write_queue.put_nowait((999, None))  # Sentinel
            except queue.Full:
                pass
        
        # Wait for workers
        for t in self.workers:
            t.join(timeout=timeout / len(self.workers))
            
        pending = self.write_queue.qsize()
        if pending > 0:
            logger.warning(f"AsyncDiskWriter stopped with {pending} pending writes")
        else:
            logger.info(f"AsyncDiskWriter stopped cleanly. Completed {self.writes_completed} writes")
            
    def queue_write(
        self, 
        bin_path: Path, 
        json_path: Path, 
        samples: np.ndarray, 
        metadata: dict,
        priority: int = 0
    ) -> bool:
        """
        Queue a write request (non-blocking).
        
        Args:
            bin_path: Path for binary data file
            json_path: Path for JSON metadata file
            samples: NumPy array to write (will be copied)
            metadata: Metadata dict for JSON sidecar
            priority: Lower = higher priority (default 0)
            
        Returns:
            True if queued, False if queue full (data dropped)
        """
        if not self.running:
            logger.warning("AsyncDiskWriter not running, write dropped")
            return False
            
        # Copy samples to prevent mutation while queued
        samples_copy = samples.copy()
        
        request = WriteRequest(
            bin_path=bin_path,
            json_path=json_path,
            samples=samples_copy,
            metadata=metadata,
            priority=priority
        )
        
        try:
            self.write_queue.put_nowait((priority, request))
            with self._stats_lock:
                self.writes_queued += 1
            return True
        except queue.Full:
            with self._stats_lock:
                self.queue_full_drops += 1
            logger.error(f"Write queue full! Dropped write to {bin_path}")
            return False
            
    def _writer_loop(self):
        """Worker thread main loop."""
        while self.running or not self.write_queue.empty():
            try:
                priority, request = self.write_queue.get(timeout=0.5)
                
                if request is None:  # Sentinel
                    break
                    
                self._execute_write(request)
                self.write_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Writer thread error: {e}")
                
    def _execute_write(self, request: WriteRequest):
        """Execute a single write request."""
        try:
            # Ensure directory exists
            request.bin_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write binary data
            request.samples.tofile(request.bin_path)
            
            # Write metadata
            with open(request.json_path, 'w') as f:
                json.dump(request.metadata, f, indent=2)
                
            with self._stats_lock:
                self.writes_completed += 1
                self.total_bytes_written += request.samples.nbytes
                
        except Exception as e:
            with self._stats_lock:
                self.writes_failed += 1
            logger.error(f"Write failed for {request.bin_path}: {e}")
            
    def get_stats(self) -> dict:
        """Get writer statistics."""
        with self._stats_lock:
            return {
                'writes_queued': self.writes_queued,
                'writes_completed': self.writes_completed,
                'writes_failed': self.writes_failed,
                'writes_pending': self.write_queue.qsize(),
                'queue_full_drops': self.queue_full_drops,
                'total_bytes_written': self.total_bytes_written,
                'running': self.running
            }
            
    @property
    def queue_depth(self) -> int:
        """Current queue depth."""
        return self.write_queue.qsize()


# Global singleton for shared use
_global_writer: Optional[AsyncDiskWriter] = None
_global_lock = threading.Lock()


def get_async_writer() -> AsyncDiskWriter:
    """Get or create the global async disk writer."""
    global _global_writer
    with _global_lock:
        if _global_writer is None:
            _global_writer = AsyncDiskWriter()
            _global_writer.start()
        return _global_writer


def shutdown_async_writer():
    """Shutdown the global async disk writer."""
    global _global_writer
    with _global_lock:
        if _global_writer is not None:
            _global_writer.stop()
            _global_writer = None
