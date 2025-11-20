# PSWS Upload Service - Quick Start

**Status:** Ready to implement  
**Priority:** High (required for HamSCI network participation)

## TL;DR - What You Need to Know

### Upload Method: SFTP (Not Rsync!)

Wsprdaemon uses **SFTP with SSH autologin**, not rsync. Your system already has the credentials configured.

**One-liner test:**
```bash
echo "ls" | sftp S000171@pswsnetwork.eng.ua.edu
```

**Note:** PSWS allows SFTP only (no SSH shell access). Use your PSWS station ID (e.g., S000171), not your callsign.

### Key Command Pattern (from wsprdaemon)

```bash
# Create batch commands file
cat > /tmp/sftp_commands.txt <<EOF
put -r analytics/WWV_10_MHz/digital_rf/2025-11-20T00-00-00
mkdir cS000171_#1_#2025-11-21T00-05
EOF

# Execute upload
sftp -v -o StrictHostKeyChecking=no -o ConnectTimeout=20 \
     -l 100 \                              # 100 kbps bandwidth limit (wsprdaemon default)
     -b /tmp/sftp_commands.txt \           # Batch commands
     S000171@pswsnetwork.eng.ua.edu
```

**Critical:** The `mkdir` command creates a "trigger directory" that signals to PSWS that the upload is complete.

### Trigger Directory Naming Convention

Format: `c{STATION_ID}_#{INSTRUMENT_ID}_#{TIMESTAMP}`

Example: `cS000171_#1_#2025-11-21T00-05`

- `c` prefix = constant
- Station ID = your PSWS username (S000171, from config file)
- Instrument ID = your device number (confirm with HamSCI - typically 1)
- Timestamp = upload completion time (UTC, no colons)

### Upload Cadence

**Once daily at 00:05 UTC** (wsprdaemon pattern - proven reliable)

Benefits:
- Upload complete 24-hour dataset after UTC day ends
- Single large batch more efficient
- PSWS expects daily delivery pattern
- Matches wsprdaemon behavior

### Retention Policy After Upload

- **Digital RF:** 7 days (can regenerate from 16 kHz archives)
- **16 kHz NPZ:** 30 days (reprocessability)
- **Discrimination CSVs:** 90 days (small, valuable for analysis)

### Configuration Needed (config/grape-config.toml)

```toml
[uploader]
enabled = true
station_id = "S000171"                   # ← YOUR PSWS USERNAME (not callsign!)
instrument_id = "1"                      # ← CONFIRM THIS WITH HAMSCI
psws_server = "pswsnetwork.eng.ua.edu"
upload_time_utc = "00:05"                # Daily upload at 00:05 UTC
bandwidth_limit_kbps = 100               # wsprdaemon default
retention_days = 7
```

### Security Note (Important!)

Wsprdaemon sets `umask 022` before SFTP upload (line 239). This prevents group write permissions on PSWS home directory, which would break SSH autologin. Make sure your implementation does the same.

### Next Actions

**Before Implementation:**
1. ✅ Verify SFTP autologin works: `echo "ls" | sftp S000171@pswsnetwork.eng.ua.edu`
2. ❓ Confirm instrument ID with HamSCI coordinators
3. ✅ No staging server - careful production testing required
4. ✅ Verify DRF files are wsprdaemon-compatible (already done per SESSION_2025-11-20)
5. ✅ Review grape-utils.sh SSH key management (lines 344-378)

**Implementation Order:**
1. Create `src/signal_recorder/psws_upload_service.py`
2. Add SFTP upload function (use subprocess, not paramiko - simpler)
3. Implement state tracking (`state/upload_state.json`)
4. Add retry logic with exponential backoff
5. Create systemd service (`systemd/grape-upload-service.service`)
6. Add Web UI monitoring page (`web-ui/upload-status.html`)

**Estimated Time:** 4-5 days

### Testing Checklist

- [ ] SFTP autologin works (no SSH shell - SFTP only!)
- [ ] SFTP can list remote directory: `echo "ls" | sftp S000171@pswsnetwork.eng.ua.edu`
- [ ] Upload test DRF directory (small test first!)
- [ ] Trigger directory created successfully
- [ ] Cleanup removes old files after 7 days
- [ ] Retry logic works on network failure
- [ ] Web UI shows upload status
- [ ] Systemd service starts/stops correctly
- [ ] Daily upload runs at 00:05 UTC

### Files to Review

- `docs/PSWS_UPLOAD_SERVICE_DESIGN.md` - Full design document
- `wsprdaemon/grape-utils.sh` - Lines 200-284 (upload implementation)
- `wsprdaemon/upload-client-utils.sh` - Lines 527-579 (SFTP logic)
- `docs/DRF_WRITER_MODES.md` - Wsprdaemon compatibility

---

**Ready to start implementation?** Review `PSWS_UPLOAD_SERVICE_DESIGN.md` for complete details.
