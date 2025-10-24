# Development Status and Roadmap

**Last Updated:** October 24, 2025  
**Current Version:** 0.1.0 (Initial Implementation)

---

## Current Status: Phase 1 Complete ✅

We have completed the **initial implementation** of the Signal Recorder system. All core functionality has been designed and coded, but **has not yet been tested with live ka9q-radio streams**.

### What's Been Completed

#### ✅ Core Architecture (100%)

All five core modules have been implemented:

1. **Stream Discovery Module** (`discovery.py` - 370 lines)
   - Avahi/mDNS service name resolution
   - Status metadata packet decoding (TLV format)
   - Automatic SSRC discovery and frequency mapping
   - StreamManager for coordinating multiple streams

2. **Stream Recorder Module** (`recorder.py` - 230 lines)
   - pcmrecord wrapper with process management
   - Multiple concurrent recorder support
   - Graceful start/stop with cleanup
   - RecorderManager for lifecycle management

3. **Storage Manager Module** (`storage.py` - 280 lines)
   - Hierarchical directory structure (HamSCI PSWS compatible)
   - JSON-based processing state tracking
   - File scanning and missing file detection
   - Retention policy support

4. **Signal Processor Module** (`processor.py` - 370 lines)
   - Plugin architecture base class
   - GRAPE processor implementation
   - Gap repair with silent file insertion
   - 24-hour concatenation and resampling (sox)
   - Digital RF conversion (wav2grape.py integration)

5. **Upload Manager Module** (`uploader.py` - 280 lines)
   - Queue-based upload with persistent state
   - Exponential backoff retry logic
   - SSH/rsync protocol implementation
   - Upload verification

#### ✅ Application Framework (100%)

- **Main Controller** (`app.py` - 280 lines): Daemon orchestration, processing loop
- **CLI Interface** (`cli.py` - 240 lines): discover, daemon, process, status, init commands
- **Configuration System**: TOML-based with example config
- **Package Structure**: setup.py, MANIFEST.in, proper Python package

#### ✅ Documentation (100%)

- **README.md**: Project overview and quick start
- **DEPLOYMENT_GUIDE.md**: Comprehensive 400+ line deployment guide
- **installation.md**: Step-by-step installation instructions
- **configuration.md**: Complete configuration reference
- **LICENSE**: MIT license

#### ✅ Distribution (100%)

- Source distribution package (signal-recorder-0.1.0.tar.gz)
- GitHub repository with all files

---

## What Needs to Be Done: Testing and Refinement

### Phase 2: Integration Testing (Current Priority)

The code is complete but **untested with real hardware**. We need to:

#### 1. Environment Setup Testing

**Prerequisites to verify:**
- [ ] ka9q-radio (radiod) is installed and running
- [ ] pcmrecord is in PATH and executable
- [ ] Avahi daemon is running
- [ ] sox, wavpack, wvunpack are installed
- [ ] Python dependencies install correctly

**Action items:**
```bash
# Test dependency installation
pip install -e .

# Verify external tools
which pcmrecord
which sox
which wavpack
systemctl status avahi-daemon
```

#### 2. Stream Discovery Testing

**Test the discovery module:**
```bash
# Should discover streams and show SSRCs
signal-recorder discover --radiod wwv-iq.local --verbose
```

**Expected issues to debug:**
- mDNS name resolution (may need to adjust service name)
- Status metadata decoding (TLV parsing edge cases)
- Multicast group membership (network configuration)
- SSRC to frequency mapping (tolerance values)

#### 3. Recording Testing

**Test basic recording:**
```bash
# Create minimal config
signal-recorder init --config /tmp/test-config.toml

# Edit to have just one frequency
# Run for 5 minutes
timeout 300 signal-recorder daemon --config /tmp/test-config.toml --verbose
```

**Expected issues to debug:**
- pcmrecord command line arguments
- File naming format (K1JT format)
- Directory permissions
- Wavpack compression settings
- File rotation timing

#### 4. Processing Testing

**Test GRAPE processing:**
```bash
# Manually process a date with recorded data
signal-recorder process --date 20241024 --config /tmp/test-config.toml --verbose
```

**Expected issues to debug:**
- Missing file detection logic
- Silent file creation
- sox command line (concatenation and resampling)
- wav2grape.py integration (may need to install Digital RF)
- Digital RF output format

#### 5. Upload Testing

**Test upload (to test server first):**
```bash
# Set up test SSH server or use actual PSWS server
# Process will automatically enqueue uploads
# Check upload queue
cat /var/lib/signal-recorder/upload_queue.json
```

**Expected issues to debug:**
- SSH key authentication
- rsync command line
- Remote path construction
- Retry logic timing
- Verification logic

---

## Phase 3: Bug Fixes and Refinements

Based on testing, we'll likely need to:

### High Priority Fixes

1. **Fix any critical bugs** that prevent basic operation
   - Discovery failures
   - Recording failures
   - Processing crashes

2. **Adjust configuration defaults**
   - Sample rates
   - File paths
   - Timeout values

3. **Improve error messages**
   - More helpful diagnostics
   - Better user guidance

### Medium Priority Enhancements

1. **Add missing dependencies**
   - Digital RF Python package
   - Any other missing tools

2. **Improve robustness**
   - Better error handling
   - More graceful degradation
   - Recovery from edge cases

3. **Add validation**
   - Config file validation
   - Dependency checking at startup
   - Better status reporting

---

## Phase 4: Production Hardening

Once basic functionality works:

### 1. Add Unit Tests

**Priority test areas:**
```python
# tests/test_discovery.py
- Test TLV metadata decoding
- Test frequency to SSRC mapping
- Test mDNS resolution (mocked)

# tests/test_storage.py
- Test directory structure creation
- Test state file read/write
- Test missing file detection

# tests/test_processor.py
- Test file validation
- Test gap repair logic
- Test processor plugin registration

# tests/test_uploader.py
- Test queue persistence
- Test retry backoff calculation
- Test upload task state transitions
```

**Implementation:**
```bash
# Add pytest to dev dependencies
pip install pytest pytest-cov

# Create tests directory structure
mkdir -p tests
touch tests/__init__.py
touch tests/test_discovery.py
# ... etc

# Run tests
pytest tests/ -v --cov=signal_recorder
```

### 2. Add Logging Improvements

- Structured logging with context
- Log rotation configuration
- Different log levels for different modules
- Performance metrics logging

### 3. Add Monitoring

- Health check endpoint
- Metrics export (Prometheus format)
- Status file for external monitoring
- Email/webhook alerts on failures

### 4. Add Systemd Integration

Create proper systemd service files:
```ini
# /etc/systemd/system/signal-recorder.service
[Unit]
Description=Signal Recorder Daemon
After=network-online.target radiod.service

[Service]
Type=simple
User=signal-recorder
Group=signal-recorder
ExecStart=/opt/signal-recorder/venv/bin/signal-recorder daemon --config /etc/signal-recorder/config.toml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 5. Add Installation Scripts

```bash
# install.sh
#!/bin/bash
# Automated installation script
# - Check dependencies
# - Create user/group
# - Install Python package
# - Create directories
# - Install systemd service
# - Generate config template
```

---

## Phase 5: Feature Enhancements

Once the system is stable in production:

### 1. Pure Python RTP Receiver (Optional)

Replace pcmrecord dependency with pure Python implementation:
- More control over recording
- Better error handling
- No external binary dependency
- Easier to debug

**Estimated effort:** 2-3 days

### 2. Additional Processors

Implement processors for other signal types:

**CODAR Processor:**
- Decode ocean radar chirps
- Extract current vectors
- Output NetCDF format

**HF Radar Processor:**
- Process ionospheric soundings
- Generate propagation maps
- Output HDF5 format

**Estimated effort per processor:** 1-2 days

### 3. Web Dashboard (Optional)

Real-time monitoring interface:
- Stream status display
- Recording statistics
- Upload queue status
- Processing progress
- Configuration management

**Technology:** Flask/FastAPI + Vue.js/React
**Estimated effort:** 1-2 weeks

### 4. Additional Upload Protocols

- HTTP/HTTPS POST
- AWS S3
- Google Cloud Storage
- FTP/SFTP

**Estimated effort per protocol:** 1-2 days

### 5. Control Protocol Integration

Use ka9q-radio's control protocol to:
- Dynamically create channels
- Adjust receiver parameters
- Query receiver status

**Estimated effort:** 3-5 days

---

## Immediate Next Steps (Recommended Order)

### Step 1: Environment Verification (You)

**What you need to do:**

1. **Verify ka9q-radio is running:**
   ```bash
   systemctl status radiod
   # or however you run radiod
   ```

2. **Check your radiod configuration:**
   ```bash
   cat /etc/radio/radiod@*.conf
   # Find the [WWV-IQ] or similar section
   # Note the "data = " line (e.g., "data = wwv-iq.local")
   ```

3. **Install system dependencies:**
   ```bash
   sudo apt-get install -y sox wavpack avahi-daemon avahi-utils rsync
   ```

4. **Install Python package:**
   ```bash
   cd /path/to/signal-recorder
   python3 -m venv venv
   source venv/bin/activate
   pip install -e .
   ```

5. **Try discovery:**
   ```bash
   signal-recorder discover --radiod wwv-iq.local --verbose
   ```

**Report back:**
- Does discovery work?
- What errors do you see?
- What streams are discovered?

### Step 2: First Recording Test (Together)

Once discovery works, we'll:

1. Create a minimal test configuration
2. Run the daemon for 5-10 minutes
3. Check that files are being created
4. Debug any issues

### Step 3: Processing Test (Together)

Once recording works:

1. Let it record for a full day (or use existing data)
2. Run manual processing
3. Check output format
4. Debug any issues

### Step 4: Upload Test (Together)

Once processing works:

1. Set up SSH keys for PSWS server
2. Test manual rsync
3. Run upload manager
4. Verify data arrives correctly

### Step 5: Production Deployment

Once everything works:

1. Create systemd service
2. Set up log rotation
3. Configure monitoring
4. Document operational procedures

---

## Summary

**Current State:**
- ✅ All code written (~2,050 lines)
- ✅ All documentation complete
- ✅ Package structure ready
- ❌ Not yet tested with real hardware

**Immediate Priority:**
1. **You:** Verify ka9q-radio setup and install dependencies
2. **You:** Run discovery test and report results
3. **Together:** Debug discovery issues if any
4. **Together:** Test recording for 5-10 minutes
5. **Together:** Iterate on fixes

**Estimated Timeline:**
- **Phase 2 (Testing):** 1-3 days (depending on issues found)
- **Phase 3 (Bug Fixes):** 1-2 days
- **Phase 4 (Hardening):** 1-2 weeks (optional, can deploy without)
- **Phase 5 (Enhancements):** Ongoing as needed

**Risk Assessment:**
- **Low risk:** Discovery and recording (well-tested patterns)
- **Medium risk:** Processing (depends on sox/wav2grape.py)
- **Low risk:** Upload (standard rsync)

**The code is ready. Now we need to test it with your actual ka9q-radio setup and iterate on any issues we find.**

What's your ka9q-radio setup like? Is radiod currently running and producing streams?

