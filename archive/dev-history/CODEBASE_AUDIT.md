# Codebase Audit - GRAPE Signal Recorder

## Active GRAPE Implementation

### Core Components (src/signal_recorder/)

**Main Daemon**:
- ✅ `grape_rtp_recorder.py` - RTP reception → scipy decimation → Digital RF output
  - `RTPReceiver` - UDP packet capture, RTP parsing
  - `CircularBuffer` - 2-second jitter buffer
  - `Resampler` - scipy decimation (16kHz → 10Hz) with timing validation
  - `GRAPEChannelRecorder` - Per-channel Digital RF writer
  - `GRAPERecorderManager` - Multi-channel coordinator

**Support Modules**:
- ✅ `grape_metadata.py` - HamSCI-compliant metadata generation
- ✅ `grape_recorder.py` - CLI wrapper for daemon control
- ✅ `cli.py` - Entry point (`signal-recorder` command)

**Channel Management**:
- ✅ `control_discovery.py` - Discover channels via `control` utility
- ✅ `radiod_control.py` - Create channels via `control` utility
- ✅ `channel_manager.py` - High-level channel operations

**Upload** (Partially Implemented):
- ⚠️ `uploader.py` - rsync/SFTP upload to PSWS
  - **Status**: Code exists but NOT integrated into `grape_rtp_recorder.py`
  - **TODO**: Add upload functionality to GRAPE daemon

### Web Interface (web-ui/)

**Server**:
- ✅ `simple-server.js` - Express.js API server
  - Configuration management (CRUD)
  - Monitoring API endpoints
  - Channel discovery/creation
  - Daemon control (start/stop/status)

**Frontend**:
- ✅ `index.html` - Configuration UI
- ✅ `monitoring.html` - Real-time dashboard
- ✅ `shared.js` - Common utilities

**Data**:
- ✅ `data/*.json` - JSON database (configs, users, session)

### Configuration

**Examples**:
- ✅ `config/grape-S000171.toml` - Working GRAPE station config
- ✅ `config/TEST_CONFIGS_README.md` - Config documentation

### Test/Development Scripts

**Active Tests**:
- ✅ `test_grape_recorder.py` - Integration test
- ✅ `test_grape_components.py` - Component unit tests
- ✅ `test-daemon.py` - Daemon startup test
- ✅ `test-watchdog.py` - Watchdog process test
- ✅ `test_digital_rf_write.py` - Digital RF I/O test
- ✅ `test_resampler.py` - Decimation accuracy test

**Legacy Tests**:
- ❌ `test_upload.py` - Tests old uploader (not integrated)
- ❌ `test_upload_from_config.py` - Tests old config-based upload

---

## Legacy Components (NOT USED)

### Generic Implementation (Pre-GRAPE)

These files implement a generic "signal recorder" concept that was superseded by the GRAPE-specific implementation:

**Generic Core**:
- ❌ `app.py` - Old `SignalRecorderApp` coordinator
  - Uses pcmrecord-based recording (not RTP direct)
  - Generic processor/storage/upload architecture
  - **Not used** by GRAPE flow

- ❌ `recorder.py` - Old `StreamRecorder` (pcmrecord-based)
  - Spawns external `pcmrecord` processes
  - Writes WAV/PCM files (not Digital RF)
  - **Replaced** by `grape_rtp_recorder.py` RTP receiver

- ❌ `processor.py` - Old generic `SignalProcessor`
  - Plugin architecture for post-processing
  - Separate from recording (not real-time)
  - **Not used** - GRAPE does scipy decimation inline

- ❌ `storage.py` - Old `StorageManager`
  - Generic file management
  - **Not needed** - Digital RF handles time-indexing

**Generic Discovery**:
- ❌ `discovery.py` - Old Avahi/mDNS-based discovery
  - **Replaced** by `control_discovery.py` which queries radiod directly
  - Avahi discovery was unreliable/complex

**Init Exports**:
- ⚠️ `__init__.py` - Exports legacy classes
  - Imports `discovery`, `recorder`, `storage`, `processor`
  - **Should be updated** to only export GRAPE components

---

## Dependency Graph

### Active GRAPE Flow

```
cli.py (entry point)
  ↓
grape_recorder.py (CLI wrapper)
  ↓
grape_rtp_recorder.py (main daemon)
  ├─→ channel_manager.py
  │     ├─→ control_discovery.py
  │     └─→ radiod_control.py
  └─→ grape_metadata.py

Web UI:
simple-server.js
  ├─→ Calls `signal-recorder` CLI
  ├─→ Reads /tmp/signal-recorder-stats.json
  └─→ Uses control_discovery.py via subprocess
```

### Legacy (Unused) Flow

```
app.py (not used)
  ├─→ recorder.py (pcmrecord, not used)
  ├─→ processor.py (not used)
  ├─→ storage.py (not used)
  └─→ uploader.py (not integrated)

discovery.py (Avahi, not used)
```

---

## Recommended Actions

### 1. Move to `legacy/` Directory

Create `src/signal_recorder/legacy/` and move:
```bash
mkdir -p src/signal_recorder/legacy
mv src/signal_recorder/app.py src/signal_recorder/legacy/
mv src/signal_recorder/recorder.py src/signal_recorder/legacy/
mv src/signal_recorder/processor.py src/signal_recorder/legacy/
mv src/signal_recorder/storage.py src/signal_recorder/legacy/
mv src/signal_recorder/discovery.py src/signal_recorder/legacy/
```

Keep for reference but don't import in active code.

### 2. Update `__init__.py`

Change from:
```python
from .discovery import StreamDiscovery, StreamManager
from .recorder import StreamRecorder
from .storage import StorageManager
from .processor import SignalProcessor, GRAPEProcessor
from .uploader import UploadManager, SSHRsyncUpload
```

To:
```python
from .grape_rtp_recorder import GRAPERecorderManager, GRAPEChannelRecorder
from .grape_metadata import GRAPEMetadataGenerator
from .channel_manager import ChannelManager
from .control_discovery import discover_channels_via_control
from .radiod_control import RadiodControl
# uploader.py exists but not yet integrated - TODO
```

### 3. Integrate Uploader

Add upload functionality to `grape_rtp_recorder.py`:
```python
from .uploader import UploadManager, SSHRsyncUpload

class GRAPERecorderManager:
    def __init__(self, config):
        # ... existing code ...
        if config.get('uploader', {}).get('enabled'):
            self.uploader = UploadManager(config['uploader'], None)
```

### 4. Consolidate Documentation

**Keep**:
- `ARCHITECTURE.md` (new, comprehensive)
- `INSTALLATION.md` (new, step-by-step)
- `README.md` (update to GRAPE focus)
- `docs/configuration.md`
- `docs/GRAPE_DIGITAL_RF_RECORDER.md`
- `docs/PSWS_SETUP_GUIDE.md`
- `web-ui/README.md`

**Archive or merge**:
- `IMPLEMENTATION_SUMMARY.md` → merge into ARCHITECTURE.md
- `GRAPE_IMPLEMENTATION_SUMMARY.md` → merge into ARCHITECTURE.md
- `DEVELOPMENT_STATUS.md` → update with current status
- `Proposal_...md` → move to `docs/archive/`
- Multiple `GRAPE_*.md` files → consolidate

### 5. Update README.md

Replace current README with `README_NEW.md` (created above) which:
- Focuses on GRAPE project
- Explains ka9q-radio dependency
- Documents scipy-based processing
- Clarifies Digital RF output format
- Highlights web UI management

### 6. Clean Up Test Files

**Keep**:
- `test_grape_recorder.py`
- `test_grape_components.py`
- `test_digital_rf_write.py`
- `test_resampler.py`

**Move to `tests/legacy/`**:
- `test_upload.py` (until uploader integrated)
- `test_upload_from_config.py`

### 7. Verify No Broken Imports

After moves, test:
```bash
python3 -c "from signal_recorder import GRAPERecorderManager"
python3 -c "from signal_recorder.cli import main"
signal-recorder --help
```

---

## Import Verification

### Files That Import Nothing Internal
(Safe, no dependencies on legacy):
- `control_discovery.py` ✅
- `grape_metadata.py` ✅

### Files With Internal Imports

**grape_rtp_recorder.py**:
```python
from .channel_manager import ChannelManager  # ✅ active
from .grape_metadata import GRAPEMetadataGenerator  # ✅ active
```

**channel_manager.py**:
```python
from .control_discovery import discover_channels_via_control  # ✅ active
from .radiod_control import RadiodControl  # ✅ active
```

**radiod_control.py**:
```python
from .control_discovery import discover_channels_via_control  # ✅ active
```

**grape_recorder.py**:
```python
from .control_discovery import discover_channels_via_control  # ✅ active
from .channel_manager import ChannelManager  # ✅ active
from .grape_rtp_recorder import GRAPERecorderManager  # ✅ active
```

**cli.py**:
```python
from .grape_recorder import GRAPERecorderManager  # ✅ active
```

**✅ No imports of legacy code in active GRAPE implementation!**

---

## Status Summary

| Component | Status | Action |
|-----------|--------|--------|
| GRAPE RTP Recorder | ✅ Active | Keep, document |
| Channel Management | ✅ Active | Keep |
| Web UI | ✅ Active | Keep, document |
| Upload | ⚠️ Exists but not integrated | Integrate into daemon |
| Legacy recorder/processor/storage | ❌ Unused | Move to `legacy/` |
| Legacy discovery (Avahi) | ❌ Unused | Move to `legacy/` |
| Documentation | ⚠️ Scattered | Consolidate |

---

## Next Steps

1. ✅ Created `ARCHITECTURE.md` - comprehensive design doc
2. ✅ Created `INSTALLATION.md` - step-by-step setup
3. ✅ Created `README_NEW.md` - GRAPE-focused overview
4. ⏭️ Move legacy files to `legacy/` directory
5. ⏭️ Update `__init__.py` exports
6. ⏭️ Replace old README with new one
7. ⏭️ Consolidate scattered GRAPE docs
8. ⏭️ Integrate uploader into daemon
9. ⏭️ Test everything still works
10. ⏭️ Update contributing/development docs

---

*Last Updated: 2025-10-28*
