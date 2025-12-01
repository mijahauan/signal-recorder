"""
Data Management Commands

Commands for managing RTP data, analytics, and cleanup operations.
Provides safe deletion of stream data while preserving site configuration.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional
import sys

logger = logging.getLogger(__name__)


class DataManager:
    """
    Manager for data lifecycle operations
    """
    
    def __init__(self, path_resolver):
        """
        Initialize data manager
        
        Args:
            path_resolver: PathResolver instance
        """
        self.path_resolver = path_resolver
    
    def get_data_size(self, path: Path) -> tuple[int, int]:
        """
        Get total size and file count of a directory
        
        Returns:
            Tuple of (size in bytes, file count)
        """
        if not path.exists():
            return 0, 0
        
        total_size = 0
        file_count = 0
        
        try:
            for item in path.rglob('*'):
                if item.is_file():
                    total_size += item.stat().st_size
                    file_count += 1
        except Exception as e:
            logger.error(f"Error calculating size of {path}: {e}")
        
        return total_size, file_count
    
    def format_size(self, size_bytes: int) -> str:
        """Format size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    def print_data_summary(self):
        """Print summary of data storage usage"""
        print("\n" + "="*70)
        print("DATA STORAGE SUMMARY")
        print("="*70)
        
        # RTP data
        data_dir = self.path_resolver.get_data_dir()
        data_size, data_files = self.get_data_size(data_dir)
        print(f"\n📊 RTP Recordings (SAFE TO DELETE)")
        print(f"  Location: {data_dir}")
        print(f"  Size:     {self.format_size(data_size)}")
        print(f"  Files:    {data_files:,}")
        
        # Analytics
        analytics_dir = self.path_resolver.get_analytics_dir()
        analytics_size, analytics_files = self.get_data_size(analytics_dir)
        print(f"\n📈 Analytics (SAFE TO DELETE, regenerable)")
        print(f"  Location: {analytics_dir}")
        print(f"  Size:     {self.format_size(analytics_size)}")
        print(f"  Files:    {analytics_files:,}")
        
        # Upload state
        upload_dir = self.path_resolver.get_upload_state_dir()
        upload_size, upload_files = self.get_data_size(upload_dir)
        print(f"\n📤 Upload State (SAFE TO DELETE)")
        print(f"  Location: {upload_dir}")
        print(f"  Size:     {self.format_size(upload_size)}")
        print(f"  Files:    {upload_files:,}")
        
        # Runtime status
        status_dir = self.path_resolver.get_status_dir()
        status_size, status_files = self.get_data_size(status_dir)
        print(f"\n🔄 Runtime Status (SAFE TO DELETE)")
        print(f"  Location: {status_dir}")
        print(f"  Size:     {self.format_size(status_size)}")
        print(f"  Files:    {status_files:,}")
        
        # Total deletable
        total_deletable = data_size + analytics_size + upload_size + status_size
        print(f"\n💾 Total Deletable: {self.format_size(total_deletable)}")
        
        # Site management (DO NOT DELETE)
        print(f"\n🔐 Site Management (DO NOT DELETE)")
        web_ui_dir = self.path_resolver.get_web_ui_data_dir()
        cred_dir = self.path_resolver.get_credentials_dir()
        print(f"  Web UI:        {web_ui_dir}")
        print(f"  Credentials:   {cred_dir}")
        
        print("="*70 + "\n")
    
    def clean_data(self, dry_run: bool = True, confirm: bool = False):
        """
        Delete all RTP recording data
        
        Args:
            dry_run: If True, show what would be deleted without deleting
            confirm: If True, skip confirmation prompt
        """
        data_dir = self.path_resolver.get_data_dir()
        
        if not data_dir.exists():
            print(f"❌ Data directory does not exist: {data_dir}")
            return
        
        size, file_count = self.get_data_size(data_dir)
        
        print(f"\n⚠️  CLEAN RTP DATA")
        print(f"  Will delete: {data_dir}")
        print(f"  Size:        {self.format_size(size)}")
        print(f"  Files:       {file_count:,}")
        
        if dry_run:
            print("\n  [DRY RUN] No files will be deleted")
            return
        
        if not confirm:
            response = input("\n  Type 'DELETE' to confirm: ")
            if response != 'DELETE':
                print("  Cancelled")
                return
        
        try:
            shutil.rmtree(data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ Deleted {file_count:,} files ({self.format_size(size)})")
        except Exception as e:
            print(f"❌ Error deleting data: {e}")
            logger.error(f"Failed to delete data directory: {e}", exc_info=True)
    
    def clean_analytics(self, dry_run: bool = True, confirm: bool = False):
        """
        Delete analytics and derived data
        
        Args:
            dry_run: If True, show what would be deleted without deleting
            confirm: If True, skip confirmation prompt
        """
        analytics_dir = self.path_resolver.get_analytics_dir()
        
        if not analytics_dir.exists():
            print(f"❌ Analytics directory does not exist: {analytics_dir}")
            return
        
        size, file_count = self.get_data_size(analytics_dir)
        
        print(f"\n⚠️  CLEAN ANALYTICS")
        print(f"  Will delete: {analytics_dir}")
        print(f"  Size:        {self.format_size(size)}")
        print(f"  Files:       {file_count:,}")
        print(f"  Note:        Can be regenerated from raw data")
        
        if dry_run:
            print("\n  [DRY RUN] No files will be deleted")
            return
        
        if not confirm:
            response = input("\n  Type 'DELETE' to confirm: ")
            if response != 'DELETE':
                print("  Cancelled")
                return
        
        try:
            shutil.rmtree(analytics_dir)
            analytics_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ Deleted {file_count:,} files ({self.format_size(size)})")
        except Exception as e:
            print(f"❌ Error deleting analytics: {e}")
            logger.error(f"Failed to delete analytics directory: {e}", exc_info=True)
    
    def clean_uploads(self, dry_run: bool = True, confirm: bool = False):
        """
        Delete upload queue and state
        
        Args:
            dry_run: If True, show what would be deleted without deleting
            confirm: If True, skip confirmation prompt
        """
        upload_dir = self.path_resolver.get_upload_state_dir()
        
        if not upload_dir.exists():
            print(f"❌ Upload directory does not exist: {upload_dir}")
            return
        
        size, file_count = self.get_data_size(upload_dir)
        
        print(f"\n⚠️  CLEAN UPLOAD QUEUE")
        print(f"  Will delete: {upload_dir}")
        print(f"  Size:        {self.format_size(size)}")
        print(f"  Files:       {file_count:,}")
        print(f"  Warning:     Upload history will be lost")
        
        if dry_run:
            print("\n  [DRY RUN] No files will be deleted")
            return
        
        if not confirm:
            response = input("\n  Type 'DELETE' to confirm: ")
            if response != 'DELETE':
                print("  Cancelled")
                return
        
        try:
            shutil.rmtree(upload_dir)
            upload_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ Deleted {file_count:,} files ({self.format_size(size)})")
        except Exception as e:
            print(f"❌ Error deleting upload queue: {e}")
            logger.error(f"Failed to delete upload directory: {e}", exc_info=True)
    
    def clean_all(self, dry_run: bool = True, confirm: bool = False):
        """
        Delete all RTP data, analytics, and upload state
        
        Args:
            dry_run: If True, show what would be deleted without deleting
            confirm: If True, skip confirmation prompt
        """
        data_dir = self.path_resolver.get_data_dir()
        analytics_dir = self.path_resolver.get_analytics_dir()
        upload_dir = self.path_resolver.get_upload_state_dir()
        status_dir = self.path_resolver.get_status_dir()
        
        total_size = 0
        total_files = 0
        
        for directory in [data_dir, analytics_dir, upload_dir, status_dir]:
            if directory.exists():
                size, files = self.get_data_size(directory)
                total_size += size
                total_files += files
        
        print(f"\n⚠️  ⚠️  ⚠️   CLEAN ALL RTP DATA   ⚠️  ⚠️  ⚠️")
        print(f"\n  Will delete:")
        print(f"    • {data_dir}")
        print(f"    • {analytics_dir}")
        print(f"    • {upload_dir}")
        print(f"    • {status_dir}")
        print(f"\n  Total Size:  {self.format_size(total_size)}")
        print(f"  Total Files: {total_files:,}")
        print(f"\n  ✅ Will NOT delete:")
        print(f"    • Site configuration")
        print(f"    • User credentials")
        print(f"    • Web UI data")
        
        if dry_run:
            print("\n  [DRY RUN] No files will be deleted")
            return
        
        if not confirm:
            print("\n  ⚠️  This will delete ALL recording data and analytics!")
            response = input("  Type 'DELETE ALL' to confirm: ")
            if response != 'DELETE ALL':
                print("  Cancelled")
                return
        
        deleted_count = 0
        deleted_size = 0
        
        for directory in [data_dir, analytics_dir, upload_dir, status_dir]:
            if directory.exists():
                try:
                    size, files = self.get_data_size(directory)
                    shutil.rmtree(directory)
                    directory.mkdir(parents=True, exist_ok=True)
                    deleted_count += files
                    deleted_size += size
                    print(f"  ✅ Deleted {directory.name}/")
                except Exception as e:
                    print(f"  ❌ Failed to delete {directory.name}/: {e}")
                    logger.error(f"Failed to delete {directory}: {e}", exc_info=True)
        
        print(f"\n✅ Deleted {deleted_count:,} files ({self.format_size(deleted_size)})")


def main():
    """CLI entry point for data management"""
    import argparse
    import toml
    from .config_utils import PathResolver
    
    parser = argparse.ArgumentParser(
        description='Signal Recorder Data Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show data summary
  signal-recorder data summary
  
  # Delete all RTP recordings (with confirmation)
  signal-recorder data clean-data
  
  # Delete analytics only
  signal-recorder data clean-analytics
  
  # Delete everything (RTP data, analytics, uploads)
  signal-recorder data clean-all
  
  # Dry run (show what would be deleted)
  signal-recorder data clean-all --dry-run
"""
    )
    
    parser.add_argument('command', choices=['summary', 'clean-data', 'clean-analytics', 'clean-uploads', 'clean-all'],
                       help='Command to execute')
    parser.add_argument('--config', '-c', default='/etc/signal-recorder/config.toml',
                       help='Configuration file path')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be deleted without deleting')
    parser.add_argument('--yes', '-y', action='store_true',
                       help='Skip confirmation prompts')
    parser.add_argument('--dev', action='store_true',
                       help='Use development paths')
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        with open(args.config, 'r') as f:
            config = toml.load(f)
    except FileNotFoundError:
        print(f"❌ Configuration file not found: {args.config}")
        print(f"   Use --config to specify a different file")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        sys.exit(1)
    
    # Create path resolver
    path_resolver = PathResolver(config, development_mode=args.dev)
    
    # Create data manager
    manager = DataManager(path_resolver)
    
    # Execute command
    if args.command == 'summary':
        manager.print_data_summary()
    
    elif args.command == 'clean-data':
        manager.clean_data(dry_run=args.dry_run, confirm=args.yes)
    
    elif args.command == 'clean-analytics':
        manager.clean_analytics(dry_run=args.dry_run, confirm=args.yes)
    
    elif args.command == 'clean-uploads':
        manager.clean_uploads(dry_run=args.dry_run, confirm=args.yes)
    
    elif args.command == 'clean-all':
        manager.clean_all(dry_run=args.dry_run, confirm=args.yes)


if __name__ == '__main__':
    main()
