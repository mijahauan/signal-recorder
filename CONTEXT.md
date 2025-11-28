# GRAPE Signal Recorder - AI Context Document

**Last Updated:** 2025-11-28  
**Next Session Goal:** Test and confirm Digital RF preparation and upload to PSWS data repository

---

## 🎯 IMMEDIATE TASK: DRF Upload Testing

### What Needs Testing
1. **DRF Writer** - Converts 10 Hz NPZ files to Digital RF format for PSWS
2. **SFTP Upload** - Uploads DRF files to `pswsnetwork.eng.ua.edu`
3. **Trigger Directory** - Creates completion marker for PSWS ingestion

### Quick Test Commands
```bash
# 1. Verify SFTP autologin works
echo "ls" | sftp S000171@pswsnetwork.eng.ua.edu

# 2. Check if DRF files exist
ls -la /tmp/grape-test/analytics/WWV_10_MHz/digital_rf/

# 3. Run DRF writer manually (if needed)
python -m signal_recorder.drf_writer_service \
  --input-dir /tmp/grape-test/analytics/WWV_10_MHz/decimated \
  --output-dir /tmp/grape-test/analytics/WWV_10_MHz \
  --channel-name "ch0" \
  --frequency-hz 10000000 \
  --callsign AC0G \
  --grid-square EM38ww \
  --receiver-name GRAPE

# 4. Verify DRF compatibility with wsprdaemon format
python test-drf-wsprdaemon-compat.py /tmp/grape-test/analytics/WWV_10_MHz/digital_rf/
```

### PSWS Upload Pattern (from wsprdaemon)
```bash
# Create SFTP batch commands
cat > /tmp/sftp_commands.txt <<EOF
put -r digital_rf/2025-11-28T00-00-00
mkdir cS000171_#1_#2025-11-28T00-05
EOF

# Execute upload (100 kbps limit, batch mode)
sftp -o StrictHostKeyChecking=no -o ConnectTimeout=20 \
     -l 100 -b /tmp/sftp_commands.txt \
     S000171@pswsnetwork.eng.ua.edu
```

**Critical:** The `mkdir cS000171_#1_#TIMESTAMP` creates a "trigger directory" signaling upload completion.

---

## 1. 📡 Project Overview

**GRAPE Signal Recorder** captures WWV/WWVH/CHU time station signals via ka9q-radio SDR and:
1. Records 16 kHz IQ archives (NPZ format, 1-minute files)
2. Analyzes for WWV/WWVH discrimination (8 voting methods)
3. Decimates to 10 Hz for Digital RF format
4. Uploads to PSWS (HamSCI Personal Space Weather Station network)

### Data Pipeline
```
ka9q-radio RTP → Core Recorder (16kHz NPZ) → Analytics Service
                                                    ↓
                                           Discrimination CSVs
                                                    ↓
                                           10 Hz Decimation (NPZ)
                                                    ↓
                                           DRF Writer Service
                                                    ↓
                                           Digital RF (HDF5)
                                                    ↓
                                           SFTP Upload to PSWS
```

---

## 2. 🗂️ Key Files for DRF/Upload

| File | Purpose |
|------|---------|
| `src/signal_recorder/drf_writer_service.py` | Converts 10Hz NPZ → Digital RF HDF5 |
| `src/signal_recorder/uploader.py` | SFTP upload with retry/queue management |
| `wsprdaemon/grape-utils.sh` | Reference SFTP upload implementation |
| `wsprdaemon/upload-client-utils.sh` | SFTP/trigger directory patterns |
| `test-drf-wsprdaemon-compat.py` | Verify DRF format matches wsprdaemon |

### DRF Writer Details
- **Input:** `*_iq_10hz.npz` files (10 Hz decimated)
- **Output:** Digital RF HDF5 with wsprdaemon-compatible metadata
- **Format:** float32 (N, 2) for I/Q, is_complex=True
- **Metadata:** `callsign`, `grid_square`, `receiver_name`, `center_frequencies`, `uuid_str`

### Upload Configuration (`config/grape-config.toml`)
```toml
[uploader]
enabled = true
station_id = "S000171"              # PSWS username
instrument_id = "1"                 # Confirm with HamSCI
psws_server = "pswsnetwork.eng.ua.edu"
upload_time_utc = "00:05"           # Daily at 00:05 UTC
bandwidth_limit_kbps = 100
retention_days = 7
```

---

## 3. 🌐 Station Configuration

| Parameter | Value |
|-----------|-------|
| **Callsign** | AC0G |
| **Grid Square** | EM38ww |
| **PSWS Station ID** | S000171 |
| **Instrument ID** | 1 (verify with HamSCI) |
| **Location** | Kansas, USA |

### Channels (sorted by frequency)
- WWV 2.5 MHz, CHU 3.33 MHz, WWV 5 MHz, CHU 7.85 MHz
- WWV 10 MHz, CHU 14.67 MHz, WWV 15 MHz, WWV 20 MHz, WWV 25 MHz

---

## 4. 🔧 Quick Reference Commands

```bash
# Activate environment
cd /home/wsprdaemon/signal-recorder && source venv/bin/activate

# Start web UI (port 3000)
cd web-ui && node monitoring-server-v3.js

# Check services
systemctl status grape-core-recorder grape-radiod-monitor

# Data locations
ls /tmp/grape-test/archives/WWV_10_MHz/          # Raw 16kHz NPZ
ls /tmp/grape-test/analytics/WWV_10_MHz/decimated/  # 10Hz NPZ
ls /tmp/grape-test/analytics/WWV_10_MHz/digital_rf/ # DRF output
```

---

## 5. 📋 Recent Completions (Nov 27)

- **Gap Analysis Page:** Functional with batch NPZ processing, scatter timeline
- **Channel Sorting:** All pages sort by frequency (WWV 2.5 → WWV 25)
- **Quota Manager:** Disk cleanup integrated (spectrograms → NPZ → CSV → DRF)
- **Discrimination UI:** Plotly charts with left-aligned titles, proper loading
- **DRF Writer:** Wsprdaemon-compatible format verified (SESSION_2025-11-20)

---

## 6. 📚 Documentation References

| Document | Content |
|----------|---------|
| `PSWS_UPLOAD_QUICKSTART.md` | SFTP upload pattern, trigger directories |
| `DRF_WRITER_WSPRDAEMON_SUCCESS.md` | DRF format verification results |
| `docs/DRF_WRITER_MODES.md` | Wsprdaemon vs enhanced mode |
| `docs/PSWS_UPLOAD_SERVICE_DESIGN.md` | Full upload service design |
| `SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md` | DRF implementation session |
| `SESSION_2025-11-27_GAP_ANALYSIS_CHANNEL_SORTING.md` | Latest session notes |
