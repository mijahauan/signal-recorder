# GRAPE Recorder Review Summary

**Date:** November 6, 2025  
**Reviewer:** AI Analysis  
**Scope:** Upload compatibility, data verification, configuration audit

---

## Three Questions Answered

### 1. ✅ How does wsprdaemon prepare data for PSWS upload?

**See:** [`GRAPE_UPLOAD_IMPLEMENTATION.md`](GRAPE_UPLOAD_IMPLEMENTATION.md)

**Key Findings:**

wsprdaemon creates **24-hour Digital RF datasets** with specific parameters:
- **Directory structure:** `CALLSIGN_GRID/OBSYYYY-MM-DDTHH-MM/ch0/`
- **File cadence:** 3600000 ms (1-hour files)
- **Subdir cadence:** 86400 s (24-hour subdirectories)
- **Compression:** Level 9 (high)
- **Channel name:** `ch0` (hardcoded)
- **Upload protocol:** SFTP (not rsync!)
- **Trigger directory:** Creates `cOBS...` directory to signal PSWS processing

**Your GRAPE recorder differences:**
- ✅ Same sample rate (10 Hz)
- ✅ Same data format (Digital RF)
- ❌ Different file cadence (1s vs 1h) **← CRITICAL FIX NEEDED**
- ❌ Different directory structure **← NEEDS ADJUSTMENT**
- ❌ Upload not implemented yet

**Action Required:**
1. Change Digital RF parameters to match wsprdaemon (see implementation guide)
2. Implement SFTP upload with trigger directory creation
3. Test format compatibility before production uploads

---

### 2. ✅ How to verify data quality in real-time?

**See:** [`REALTIME_DATA_VERIFICATION.md`](REALTIME_DATA_VERIFICATION.md)

**Multi-Layer Approach:**

| Layer | Frequency | What It Checks | Alert Threshold |
|-------|-----------|----------------|-----------------|
| **Packet stats** | 60s | Completeness, gaps | <99% for 10 min |
| **Signal presence** | 5min | Spectral energy | No signal for 30 min |
| **WWV tone** | 1min | Tone detection | No tones for 6 hrs |
| **Spectrogram** | 1hr | Visual waterfall | Manual review |

**You Already Have:**
- ✅ Packet-level monitoring (RTP stats)
- ✅ WWV tone detection (PERFECT for verification!)
- ✅ Gap tracking
- ✅ Completeness metrics

**Need to Add:**
- ⏭ Signal presence check (simple spectral test)
- ⏭ Hourly spectrograms
- ⏭ Web dashboard showing all metrics
- ⏭ Automated alerts

**Quick verification script provided** - Run `quick-verify.sh` NOW to check current data!

---

### 3. ✅ Configuration audit results

**See:** [`CONFIG_AUDIT_REPORT.md`](CONFIG_AUDIT_REPORT.md)

**Overall Grade:** 🟡 **70% Correct** - Works for recording, needs fixes before upload

**Critical Issues:**

1. ❌ **Duplicate channel** - CHU 14.67 MHz defined twice (lines 35 & 135)
2. ❌ **Upload protocol wrong** - Says "rsync", should be "sftp"
3. ❌ **Upload credentials wrong** - user should be "S000171", SSH key path wrong
4. ❌ **Missing Digital RF parameters** - Need wsprdaemon-compatible settings
5. ⚠️ **Obsolete [processor.grape]** section - V2 recorder doesn't use it

**High-Priority Fixes:**
- Remove duplicate channel definition
- Fix [uploader] section completely
- Add Digital RF cadence parameters
- Update SSH key path to `/home/mjh/.ssh/id_ed25519`
- Enable monitoring (enable_metrics = true)

**Corrected config file:** `config/grape-config-CORRECTED.toml` (created below)

---

## Implementation Priority

### CRITICAL (Do Before Enabling Uploads)

1. **Fix Digital RF parameters** (1 hour)
   - Change file_cadence_millisecs to 3600000
   - Change subdir_cadence_secs to 86400
   - Set compression_level to 9
   
2. **Fix upload configuration** (30 minutes)
   - Change protocol to "sftp"
   - Fix user, ssh_key, remote_base_path
   - Add trigger directory creation
   
3. **Remove duplicate channel** (2 minutes)
   - Delete lines 135-143 in grape-config.toml

### HIGH (Operational Improvements)

4. **Implement real-time verification** (2-3 hours)
   - Add signal presence check script
   - Add hourly spectrogram generation
   - Update web dashboard

5. **Test upload compatibility** (1 hour)
   - Create test dataset with wsprdaemon parameters
   - Verify PSWS can read it
   - Dry-run SFTP upload

### MEDIUM (Nice to Have)

6. **Add timing and quality sections to config**
7. **Improve web UI monitoring**
8. **Set up automated alerts**

---

## Test Plan

### Phase 1: Verify Current Recording (NOW)

```bash
# Run quick verification
./quick-verify.sh

# Check WWV tone detection is working
tail -f /tmp/grape-test/analytics/timing/wwv_timing.csv

# Verify Digital RF files are being created
ls -lh /tmp/grape-test/data/$(date -u +%Y%m%d)/AC0G_EM38ww/*/
```

**Expected:** All channels recording, WWV tones detected on strong signals

### Phase 2: Apply Configuration Fixes (1-2 hours)

```bash
# Backup current config
cp config/grape-config.toml config/grape-config.toml.backup

# Apply corrected config
cp config/grape-config-CORRECTED.toml config/grape-config.toml

# Restart recorder
# (stop current instance, start with new config)
```

### Phase 3: Verify PSWS Compatibility (Before Production)

```bash
# Generate test dataset with wsprdaemon parameters
python3 scripts/create_test_dataset.py

# Compare with wsprdaemon output
diff -r /tmp/grape-test-data /tmp/wsprdaemon-test-data

# Test SFTP upload (dry-run)
sftp -n S000171@pswsnetwork.eng.ua.edu <<EOF
cd /
ls
quit
EOF
```

**Expected:** Formats match, SFTP login works

### Phase 4: Production Uploads (After Testing)

```bash
# Enable uploads in config
# Set [uploader] enabled = true

# Monitor first upload
tail -f /var/log/signal-recorder/upload.log
```

---

## Quick Reference

| Document | Purpose |
|----------|---------|
| **GRAPE_UPLOAD_IMPLEMENTATION.md** | wsprdaemon analysis & upload requirements |
| **REALTIME_DATA_VERIFICATION.md** | Real-time verification strategies |
| **CONFIG_AUDIT_REPORT.md** | Detailed config review |
| **REVIEW_SUMMARY.md** | This document - action items |
| **config/grape-config-CORRECTED.toml** | Corrected configuration |

---

## Immediate Action Items (This Week)

- [ ] Run `quick-verify.sh` to check current data
- [ ] Apply config fixes (remove duplicate, fix upload section)
- [ ] Update Digital RF parameters to match wsprdaemon
- [ ] Test signal presence check script
- [ ] Review WWV tone detection logs
- [ ] Contact PSWS to verify S000171 account is set up
- [ ] Add SSH public key to PSWS account

## Next Month

- [ ] Implement hourly spectrograms
- [ ] Add real-time health dashboard
- [ ] Set up automated alerts
- [ ] Enable production uploads
- [ ] Monitor first week of uploads

---

**Status:** Ready to proceed with fixes. Most critical: Digital RF parameter changes and upload configuration.

**Estimated Time to Production:** 1-2 days (if PSWS account is ready)
