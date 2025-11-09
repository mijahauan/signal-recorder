# GRAPE Recorder - Next Steps

**Date:** November 6, 2025  
**Current Status:** ✅ Recording works, ⏭ Upload needs implementation

---

## What We Completed Today

✅ **Comprehensive codebase cleanup** (85 files archived)  
✅ **wsprdaemon analysis** - Understand PSWS upload format  
✅ **Real-time verification strategy** - Don't wait for daily processing  
✅ **Configuration audit** - Found critical issues before production  

---

## Documents Created

| Document | Purpose | Read This If... |
|----------|---------|----------------|
| **REVIEW_SUMMARY.md** | Overview of all findings | You want the big picture |
| **GRAPE_UPLOAD_IMPLEMENTATION.md** | Upload requirements & wsprdaemon comparison | You're implementing uploads |
| **REALTIME_DATA_VERIFICATION.md** | How to verify data NOW | You want continuous monitoring |
| **CONFIG_AUDIT_REPORT.md** | Detailed config review | You need to fix the config |
| **quick-verify.sh** | Instant data check script | You want to check data NOW |

---

## What to Do Right Now

### Step 1: Verify Current Data (5 minutes)

```bash
cd /home/mjh/git/signal-recorder
./quick-verify.sh
```

This will tell you:
- ✓ Is recorder running?
- ✓ Are Digital RF files being created?
- ✓ Are WWV tones being detected?
- ✓ Does data contain actual signal?

**Expected output:** All green checks, some channels with tone detections

---

### Step 2: Review Key Findings (15 minutes)

**Read these three sections:**

1. **REVIEW_SUMMARY.md** - Start here for overview
2. **CONFIG_AUDIT_REPORT.md** - Section on [uploader] issues (Critical!)
3. **GRAPE_UPLOAD_IMPLEMENTATION.md** - Section 3 (Required Changes)

**Key discoveries:**

| Issue | Impact | Priority |
|-------|--------|----------|
| Digital RF file cadence wrong | PSWS won't accept format | 🔴 Critical |
| Upload protocol is rsync not sftp | Upload will fail | 🔴 Critical |
| Duplicate CHU 14.67 channel | Wasted resources | 🟡 Medium |
| Missing trigger directory creation | PSWS won't process data | 🔴 Critical |

---

### Step 3: Decide on Timeline (Planning)

**Option A: Fix Critical Issues This Week** (Recommended)

Timeline: 4-6 hours spread over 2-3 days

1. **Day 1** (2 hours):
   - Apply config fixes
   - Update Digital RF parameters
   - Remove duplicate channel
   - Test recording still works

2. **Day 2** (2 hours):
   - Implement SFTP upload
   - Add trigger directory creation
   - Test with sample dataset

3. **Day 3** (1 hour):
   - Contact PSWS to verify account setup
   - Dry-run upload test
   - Enable production uploads

**Option B: Gradual Implementation** (Lower risk)

Timeline: 2-3 weeks

- **Week 1:** Fix config, verify recording
- **Week 2:** Implement upload, test locally
- **Week 3:** Contact PSWS, production uploads

---

## Critical Changes Needed Before Upload

### 1. Digital RF Parameters (CRITICAL!)

**File:** `src/signal_recorder/grape_rtp_recorder.py` line ~1220

**Change from:**
```python
subdir_cadence_secs=3600,        # 1 hour
file_cadence_millisecs=1000,     # 1 second
compression_level=1,             # Low
```

**To:**
```python
subdir_cadence_secs=86400,       # 24 hours (PSWS requires this!)
file_cadence_millisecs=3600000,  # 1 hour (PSWS requires this!)
compression_level=9,             # High (save upload bandwidth)
```

**Why:** PSWS expects wsprdaemon format. Wrong parameters = rejected uploads.

### 2. Upload Configuration (CRITICAL!)

**File:** `config/grape-config.toml` lines 158-178

**Current (WRONG):**
```toml
[uploader]
enabled = false
protocol = "rsync"  # ❌ WRONG!

[uploader.rsync]  # ❌ WRONG SECTION!
user = "your_username"  # ❌ WRONG!
ssh_key = "/home/wsprdaemon/.ssh/id_rsa_psws"  # ❌ WRONG PATH!
remote_base_path = "/data/S000171"  # ❌ WRONG PATH!
```

**Corrected:**
```toml
[uploader]
enabled = false  # Set to true when ready
protocol = "sftp"  # ✓ CORRECT

[uploader.sftp]  # ✓ CORRECT SECTION
user = "S000171"  # ✓ Your station ID
ssh_key = "/home/mjh/.ssh/id_ed25519"  # ✓ Your actual key
remote_base_path = "/"  # ✓ PSWS requires home dir
create_trigger_directory = true  # ✓ CRITICAL!
```

### 3. Remove Duplicate Channel

**File:** `config/grape-config.toml` lines 135-143

**Delete these lines:**
```toml
[[recorder.channels]]
ssrc = 14670000
frequency_hz = 14670000
# ... (entire duplicate section)
```

Channel already defined at lines 35-44.

---

## Implementation Checklist

### Before Starting
- [ ] Backup current config: `cp config/grape-config.toml config/grape-config.toml.backup`
- [ ] Backup current code: `git commit -am "Before upload implementation"`
- [ ] Run `./quick-verify.sh` to establish baseline

### Phase 1: Configuration Fixes (30 minutes)
- [ ] Remove duplicate CHU 14.67 channel (lines 135-143)
- [ ] Fix [uploader] section (change rsync → sftp, fix all paths)
- [ ] Enable monitoring (enable_metrics = true)
- [ ] Test config loads without errors

### Phase 2: Code Changes (1-2 hours)
- [ ] Update Digital RF parameters in `grape_rtp_recorder.py`
- [ ] Add SFTP upload module (adapt from existing rsync code)
- [ ] Implement trigger directory creation
- [ ] Add wsprdaemon-compatible directory structure

### Phase 3: Testing (1 hour)
- [ ] Generate test dataset with new parameters
- [ ] Verify format matches wsprdaemon output
- [ ] Test SFTP connection to PSWS
- [ ] Dry-run upload (don't create trigger yet)

### Phase 4: PSWS Coordination (External dependency)
- [ ] Contact PSWS to verify S000171 account exists
- [ ] Send SSH public key: `cat ~/.ssh/id_ed25519.pub`
- [ ] Test autologin: `sftp S000171@pswsnetwork.eng.ua.edu`
- [ ] Confirm trigger directory format

### Phase 5: Production (After testing)
- [ ] Set `[uploader] enabled = true`
- [ ] Monitor first upload closely
- [ ] Verify PSWS processes data
- [ ] Set up automated monitoring

---

## Questions to Answer

Before enabling uploads, clarify with PSWS:

1. **Is S000171 account active?**
   - Do they have your SSH public key?
   - Can you SFTP login now?

2. **Directory structure confirmation:**
   - Do they expect `AC0G_EM38ww/OBS.../ch0/` format?
   - Is trigger directory format correct: `cOBS{timestamp}_#172_#{upload_time}`?

3. **Data validation:**
   - Will they test with a sample dataset before production?
   - What's the preferred upload schedule? (currently 00:30 UTC)

---

## Real-Time Monitoring (Parallel Task)

While implementing uploads, also improve monitoring:

**Quick wins** (1-2 hours each):

1. **Add signal presence check**
   - Script provided in `REALTIME_DATA_VERIFICATION.md`
   - Run every 5 minutes via cron
   - Alerts if no signal for 30 minutes

2. **Generate hourly spectrograms**
   - Script provided in verification doc
   - Visual confirmation signal is present
   - Store in `/tmp/spectrograms/`

3. **Update web dashboard**
   - Show WWV tone detection status
   - Display signal presence indicators
   - Add "Last verified" timestamps

---

## Success Criteria

**You'll know it's working when:**

✅ `./quick-verify.sh` shows all green checks  
✅ WWV tones detected every minute on strong channels  
✅ Digital RF files have wsprdaemon-compatible parameters  
✅ SFTP upload test succeeds  
✅ PSWS processes your test upload  
✅ Continuous uploads run automatically  

---

## Help & Resources

**If stuck:**
1. Check the detailed implementation guides
2. Review wsprdaemon source code (`/home/mjh/git/wsprdaemon/wav2grape.py`)
3. Test each component individually before integration
4. Use dry-runs and test datasets before production

**Documentation:**
- `/home/mjh/git/wsprdaemon/` - Reference implementation
- `docs/WWV_DETECTION.md` - Tone detection details
- `docs/TIMING_ARCHITECTURE_V2.md` - time_snap mechanism

---

## Quick Command Reference

```bash
# Verify current data
./quick-verify.sh

# Check WWV tone detections
tail -f /tmp/grape-test/analytics/timing/wwv_timing.csv

# Monitor recorder
tail -f /var/log/signal-recorder/signal-recorder.log

# Test SFTP connection
sftp -o ConnectTimeout=10 S000171@pswsnetwork.eng.ua.edu

# Validate config
python3 -c "import toml; print(toml.load('config/grape-config.toml'))"
```

---

**Next Action:** Run `./quick-verify.sh` to check current data, then review REVIEW_SUMMARY.md for detailed findings.
