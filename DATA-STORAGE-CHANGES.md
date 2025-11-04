# Data Storage Reorganization - Implementation Complete

**Status:** ✅ IMPLEMENTED  
**Date:** 2025-11-03  
**Breaking Changes:** Minimal (backward compatible)

---

## What Changed

The signal-recorder application has been updated with a standardized, FHS-compliant directory structure that clearly separates RTP stream data from site management data.

### Benefits

✅ **Easy Data Deletion** - Single command to delete all RTP data  
✅ **Secure Credentials** - Separated from deletable data with restrictive permissions  
✅ **System Standard** - Follows Linux Filesystem Hierarchy Standard  
✅ **Systemd Ready** - Prepared for production deployment as a service  
✅ **Backward Compatible** - Old configurations still work with fallbacks  

---

## New Directory Structure

```
/var/lib/signal-recorder/          # Base directory for all RTP data
├── data/                          # Raw Digital RF recordings (SAFE TO DELETE)
│   ├── WWV-2.5/
│   ├── WWV-5.0/
│   └── ...
├── analytics/                     # Derived analytics (SAFE TO DELETE)
│   ├── quality/                   # Quality metrics per channel
│   ├── timing/                    # WWV timing validation
│   └── reports/                   # Daily reports
├── upload/                        # Upload queue (SAFE TO DELETE)
│   └── queue.json
└── status/                        # Runtime status (SAFE TO DELETE)
    └── recording-stats.json

/etc/signal-recorder/              # System configuration (DO NOT DELETE)
├── config.toml                   # Main configuration
└── credentials/                   # Sensitive files (mode 0700)
    ├── psws_ssh_key              # SSH key for uploads
    └── jwt_secret.txt            # Web UI JWT secret

/var/lib/signal-recorder-web/     # Web UI data (DO NOT DELETE)
├── users.json                    # Login credentials
├── configurations.json           # Saved configurations
└── channels.json                 # Channel definitions

/var/log/signal-recorder/         # Application logs
├── signal-recorder.log
├── upload.log
└── web-ui.log
```

---

## How to Use

### For New Installations

Follow the new installation guide:
```bash
# See INSTALLATION-SYSTEMD.md for complete instructions
./scripts/install-systemd.sh
```

### For Existing Installations

#### Option 1: Automatic Migration (Recommended)

```bash
# Dry run to see what would be migrated
./scripts/migrate-data-storage.sh --dry-run

# Perform actual migration
sudo ./scripts/migrate-data-storage.sh
```

#### Option 2: Manual Migration

1. Copy your data to new locations manually
2. Update your configuration file to use the new path structure
3. Restart services

#### Option 3: Continue with Old Paths

The application still supports old path configurations through backward compatibility. However, you won't get the benefits of the new structure.

---

## Configuration Changes

### New Configuration Format (config/grape-production-v2.toml)

```toml
[paths]
# Standardized directory structure
base_dir = "/var/lib/signal-recorder"
data_dir = "/var/lib/signal-recorder/data"
analytics_dir = "/var/lib/signal-recorder/analytics"
upload_state_dir = "/var/lib/signal-recorder/upload"
status_dir = "/var/lib/signal-recorder/status"
credentials_dir = "/etc/signal-recorder/credentials"
log_dir = "/var/log/signal-recorder"

[recorder]
# Template variables supported
wwv_timing_csv = "${paths.analytics_dir}/timing/wwv_timing.csv"
quality_metrics_dir = "${paths.analytics_dir}/quality"

[uploader]
# Queue file uses path_resolver
# queue_file automatically resolves to ${paths.upload_state_dir}/queue.json

[uploader.rsync]
# Credentials separated
ssh_key = "${paths.credentials_dir}/psws_ssh_key"
```

### Old Configuration Still Works

```toml
[recorder]
archive_dir = "/home/mjh/grape-data/archive"  # Still supported

[uploader]
queue_dir = "/home/mjh/grape-data/upload_queue"  # Still supported
```

---

## Data Management Commands

### New CLI Commands

```bash
# Show storage summary
signal-recorder data summary

# Delete all RTP recordings (with confirmation)
signal-recorder data clean-data

# Delete analytics only (can be regenerated)
signal-recorder data clean-analytics

# Delete upload queue
signal-recorder data clean-uploads

# Delete everything except site config
signal-recorder data clean-all

# Dry run (preview what would be deleted)
signal-recorder data clean-all --dry-run

# Skip confirmation prompts
signal-recorder data clean-all --yes
```

### What Gets Deleted

**`clean-data`** - Deletes:
- `/var/lib/signal-recorder/data/` (all Digital RF files)

**`clean-analytics`** - Deletes:
- `/var/lib/signal-recorder/analytics/` (quality metrics, WWV logs, reports)

**`clean-uploads`** - Deletes:
- `/var/lib/signal-recorder/upload/` (upload queue and history)

**`clean-all`** - Deletes:
- All of the above
- `/var/lib/signal-recorder/status/` (runtime stats)

**NEVER Deletes:**
- `/etc/signal-recorder/` (configuration and credentials)
- `/var/lib/signal-recorder-web/` (user accounts, saved configs)
- `/var/log/signal-recorder/` (logs, unless you explicitly delete them)

---

## Code Changes

### Updated Files

1. **`src/signal_recorder/config_utils.py`** (NEW)
   - PathResolver class for standardized path management
   - Environment variable expansion
   - Template variable substitution
   - Backward compatibility with old configs

2. **`src/signal_recorder/grape_rtp_recorder.py`**
   - Updated to accept `path_resolver` parameter
   - Stats file location now configurable
   - WWV timing CSV path uses path_resolver

3. **`src/signal_recorder/uploader.py`**
   - Updated `load_upload_config_from_toml()` to accept path_resolver
   - Queue file path now standardized
   - SSH key path resolution

4. **`src/signal_recorder/data_management.py`** (NEW)
   - DataManager class for cleanup operations
   - CLI commands for data management
   - Safe deletion with confirmations

5. **`config/grape-production-v2.toml`** (NEW)
   - Template configuration with new path structure
   - Detailed comments and examples
   - Security best practices

### Integration

To use the new path structure in your code:

```python
from signal_recorder.config_utils import load_config_with_paths, PathResolver

# Load configuration with path resolver
config, path_resolver = load_config_with_paths(config_file)

# Get standardized paths
data_dir = path_resolver.get_data_dir()
analytics_dir = path_resolver.get_analytics_dir()
status_file = path_resolver.get_status_file()

# Pass to recorder
recorder = GRAPERecorderManager(config, path_resolver=path_resolver)
```

---

## Migration Checklist

- [ ] Review new directory structure
- [ ] Backup existing data
- [ ] Run migration script (dry-run first)
- [ ] Verify data migrated correctly
- [ ] Update configuration file
- [ ] Update systemd service files (if using)
- [ ] Test recording functionality
- [ ] Test web UI access
- [ ] Test data cleanup commands
- [ ] Remove old data directories (after verification)

---

## Systemd Deployment

New systemd service files included:
- `systemd/signal-recorder.service` - Main recorder daemon
- `systemd/signal-recorder-web.service` - Web UI server

Features:
- Automatic restart on failure
- Resource limits (memory, CPU)
- Security hardening
- Proper logging to journald

See [INSTALLATION-SYSTEMD.md](INSTALLATION-SYSTEMD.md) for complete setup.

---

## Testing

### Verify Path Resolution

```bash
# Show resolved paths
python3 -c "
from signal_recorder.config_utils import load_config_with_paths
config, resolver = load_config_with_paths('config/grape-production-v2.toml')
resolver.print_summary()
"
```

### Test Data Management

```bash
# Preview data summary
signal-recorder data summary

# Test dry-run cleanup
signal-recorder data clean-all --dry-run
```

### Test Recording

```bash
# Start recorder with new config
signal-recorder record --config config/grape-production-v2.toml

# Verify data is written to correct location
ls -lh /var/lib/signal-recorder/data/

# Check stats file location
cat /var/lib/signal-recorder/status/recording-stats.json
```

---

## Backward Compatibility

### What Still Works

✅ Old `archive_dir` configuration  
✅ Old `queue_dir` configuration  
✅ Paths in source tree (development mode)  
✅ `/tmp/signal-recorder-stats.json` (with warning)  
✅ Existing TOML files without `[paths]` section  

### Deprecation Warnings

The application will log warnings if you're using deprecated paths:
```
WARNING: Using deprecated path /tmp/signal-recorder-stats.json
         Consider migrating to: /var/lib/signal-recorder/status/
```

---

## Troubleshooting

### Migration Issues

**Problem:** "Permission denied" during migration  
**Solution:** Run with sudo: `sudo ./scripts/migrate-data-storage.sh`

**Problem:** Old data still in source tree  
**Solution:** Verify migration completed, then manually remove old directories

### Path Resolution Issues

**Problem:** Application can't find data directory  
**Solution:** Check config file, ensure `paths.data_dir` is set or `recorder.archive_dir` exists

**Problem:** Stats file in wrong location  
**Solution:** Verify `monitoring.status_file` in config or use PathResolver

### Permission Issues

**Problem:** "Permission denied" writing to /etc/signal-recorder  
**Solution:** Check ownership: `sudo chown signal-recorder:signal-recorder /etc/signal-recorder/credentials/*`

---

## FAQ

**Q: Do I have to migrate to the new structure?**  
A: No, old configurations still work. But you won't get the benefits like easy data cleanup.

**Q: Will this delete my existing data?**  
A: No, migration copies data (doesn't move). Old data is preserved until you manually delete it.

**Q: Can I use a custom data directory?**  
A: Yes, set `paths.data_dir` in your config to any location.

**Q: What if I'm not using systemd?**  
A: The new path structure works with any deployment method. Systemd is just one option.

**Q: How do I roll back?**  
A: Keep your old configuration file and old data directories. Just use the old config file.

---

## Documentation

- [DATA-STORAGE-AUDIT.md](DATA-STORAGE-AUDIT.md) - Detailed analysis of old vs new structure
- [INSTALLATION-SYSTEMD.md](INSTALLATION-SYSTEMD.md) - Complete systemd installation guide
- [config/grape-production-v2.toml](config/grape-production-v2.toml) - Example configuration

---

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review logs: `sudo journalctl -u signal-recorder -n 100`
3. File an issue with details about your environment

---

**Implementation Status:** ✅ Complete and Ready for Use
