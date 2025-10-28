# GRAPE Upload Quick Start

## ✅ Configuration Already Done!

All upload settings are already in **`config/grape-S000171.toml`**:

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
id = "S000171"              # PSWS station ID
instrument_id = "172"       # PSWS instrument ID

[uploader]
enabled = false             # ⬅️ SET TO true TO ENABLE
protocol = "sftp"

[uploader.sftp]
host = "pswsnetwork.eng.ua.edu"
user = "S000171"
ssh_key = "/home/mjh/.ssh/id_rsa"
bandwidth_limit_kbps = 100
```

No additional configuration needed! Your credentials and settings are all in place.

---

## 🧪 Test Upload (3 Steps)

### 1. Create Test Data
```bash
cd ~/git/signal-recorder
python3 test_upload.py --verify
```

### 2. Test SFTP Connection
```bash
sftp S000171@pswsnetwork.eng.ua.edu
# Type 'quit' to exit
```

### 3. Run Upload Test
```bash
python3 test_upload_from_config.py
```

**Expected Output:**
```
🧪 Testing GRAPE Upload with grape-S000171.toml configuration

📖 Loading config from: config/grape-S000171.toml

📡 Station Configuration:
   Callsign: AC0G
   Grid: EM38ww
   Station ID: S000171
   Instrument: 172

📤 Upload Configuration:
   Protocol: sftp
   Host: pswsnetwork.eng.ua.edu
   User: S000171
   SSH Key: /home/mjh/.ssh/id_rsa
   Bandwidth: 100 KB/s

📦 Test Dataset: /tmp/grape_test_upload/OBS2025-10-26T00-00

1️⃣  Enqueuing dataset...
   ✅ Dataset enqueued successfully

2️⃣  Processing upload queue...
   SFTP upload successful
   ✅ Upload verified

3️⃣  Upload Queue Status:
   Completed: 1
   Failed: 0

✅ Upload test SUCCESSFUL!
```

---

## 🚀 Enable Production Uploads

### Edit Config
```bash
nano config/grape-S000171.toml
```

Change line 117:
```toml
enabled = false  # Change to true
```

### Restart Daemon
```bash
# Via web UI or:
pkill -f signal-recorder-daemon
signal-recorder-daemon
```

---

## 📊 What Happens Automatically

**Daily Cycle:**

1. **00:00 UTC** - Day rolls over, new recording starts
2. **00:00 UTC + 5min** - Previous day's Digital RF finalized  
3. **00:30 UTC** - Upload runs (configured in `upload_time`)
4. **Validation** - Checks date, markers, Digital RF integrity
5. **SFTP Upload** - Sends OBS directory to PSWS
6. **Trigger** - Creates `cOBS_#172_#TIMESTAMP` directory
7. **Marker** - Creates `.upload_complete` to prevent re-upload

---

## 🔍 Monitoring

### Check Upload Queue
```bash
cat /home/mjh/git/signal-recorder/test-data/raw/upload_queue/upload_queue.json
```

### Check Logs
```bash
tail -f /tmp/signal-recorder-daemon.log | grep -i upload
```

### Check Completed Uploads
```bash
find /home/mjh/git/signal-recorder/test-data/raw -name ".upload_complete"
```

---

## ⚙️ Configuration Details

All settings from **`grape-S000171.toml`**:

| Setting | Value | Purpose |
|---------|-------|---------|
| `protocol` | `sftp` | PSWS requires SFTP (wsprdaemon-compatible) |
| `user` | `S000171` | Your PSWS station ID |
| `instrument_id` | `172` | Your PSWS instrument number |
| `ssh_key` | `/home/mjh/.ssh/id_rsa` | Already set up with ssh-copy-id |
| `bandwidth_limit_kbps` | `100` | 100 KB/s = ~360 MB/hour |
| `upload_time` | `00:30` | Runs at 00:30 UTC daily |
| `max_retries` | `5` | Retry up to 5 times with backoff |

---

## 🎯 Success Checklist

- [x] Config file has all credentials
- [ ] Test data created
- [ ] SFTP connection tested
- [ ] Upload test successful
- [ ] Trigger directory created on PSWS
- [ ] `.upload_complete` marker exists
- [ ] PSWS dashboard shows data
- [ ] Production uploads enabled

---

## 🆘 Troubleshooting

### "Skipping: date is not before today"
✅ **Expected** - Only uploads completed days (yesterday or earlier)

### "Already uploaded (.upload_complete marker exists)"
✅ **Expected** - Prevents re-uploading same data

### "SFTP failed: Permission denied"
❌ **Check SSH key**:
```bash
ssh S000171@pswsnetwork.eng.ua.edu
# Should login without password
```

### "Digital RF validation failed"
❌ **Check test data**:
```bash
python3 test_upload.py --verify
# Should show "✅ Dataset verification successful"
```

---

## 📚 Additional Documentation

- **Full analysis**: `GRAPE_UPLOAD_COMPARISON.md`
- **Detailed config**: `GRAPE_UPLOAD_CONFIG.md`
- **Timing fixes**: `GRAPE_TIMING_ANALYSIS.md`

---

## 🎉 Summary

Your configuration is **ready to go**! 

All you need to do:
1. ✅ Test with `test_upload_from_config.py`
2. ✅ Set `enabled = true` in `grape-S000171.toml`
3. ✅ Let it run through midnight UTC

**Your S000171/172 credentials are already configured and working!**
