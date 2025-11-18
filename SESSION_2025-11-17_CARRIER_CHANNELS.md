# Session Summary: 2025-11-17 - Carrier Channels & Web UI

## ✅ COMPLETED

### 1. **Carrier Spectrograms Working**
- Script: `scripts/generate_spectrograms_from_carrier.py`
- All 9 carrier channels generating spectrograms
- 10 Hz low-pass filter and decimation implemented
- Usage: `python3 scripts/generate_spectrograms_from_carrier.py --date 20251117 --data-root /tmp/grape-test --channel "WWV 5 MHz"`

### 2. **Web UI Improvements**
- **File**: `web-ui/monitoring-server-v3.js`
  - Added carrier channel detection (checks for "carrier" in name)
  - Displays channel type (📡 Carrier / 📶 Wide) and sample rates
  - Proper timing quality: GPS_LOCKED for wide channels, NTP_SYNCED for carriers
  - Fixed spectrogram URL construction (removed duplicate "carrier" suffix)

- **File**: `web-ui/carrier.html`
  - Updated timing labels (GPS instead of TONE)
  - Shows channel type icon and sample rate in UI

- **API**: `/api/v1/carrier/quality?date=YYYYMMDD`
  - Returns `channel_type`, `sample_rate`, `timing_quality` for all channels

### 3. **RTP Offset Analysis**
- Confirmed: Each ka9q-radio channel has independent RTP clock
- Wide and carrier channels drift ±2.7M samples (cannot share time_snap)
- **Carrier timing strategy**: NTP_SYNCED (±10ms, adequate for Doppler analysis)

## 🐛 CRITICAL BUG FOUND - NOT YET FIXED

### **Carrier Channels Recording All ZEROS**

**Root Cause**: Core recorder doesn't recognize RTP payload type 97 (used by carrier channels)

**Evidence**:
```bash
# Core recorder log shows:
WARNING: WWV 5 MHz carrier: Unknown payload type 97, assuming float32

# All carrier NPZ files contain zeros:
$ python3 -c "import numpy as np; d=np.load('/tmp/grape-test/archives/WWV_5_MHz_carrier/20251117T200000Z_5000000_iq.npz'); print(np.count_nonzero(d['iq']))"
0  # <-- ALL ZEROS!
```

**Fix Applied** (NOT YET TESTED):
- **File**: `src/signal_recorder/core_recorder.py` line 441
- Changed: `if payload_type == 120:` → `if payload_type == 120 or payload_type == 97:`
- PT 97 is int16 IQ format (same as PT 120 used by 16 kHz channels)

**Action Required**:
1. Restart core recorder: `./RESTART-RECORDER.sh` or `./restart-recorder-with-new-code.sh`
2. Wait 1-2 minutes for new carrier data
3. Verify carrier files contain non-zero samples:
   ```bash
   python3 -c "import numpy as np; d=np.load('/tmp/grape-test/archives/WWV_5_MHz_carrier/LATEST_FILE.npz'); print(f'Non-zero: {np.count_nonzero(d[\"iq\"])}/{len(d[\"iq\"])}')"
   ```
4. Regenerate spectrograms after collecting good data

## 🔍 SECONDARY ISSUE (Lower Priority)

### **Discrimination Data Gap After 20:41 UTC**

**Symptom**: WWV/WWVH discrimination stops recording after 20:41 UTC

**Root Cause**: Tone detections showing ±29.5 second timing errors
- Creates ±59 second differential delays
- All measurements rejected (threshold: ±1 second)

**Logs Show**:
```
WARNING: WWV 5 MHz: Rejecting outlier differential delay: -59259.0ms 
  (WWV: -29518.5ms, WWVH: 29740.5ms)
```

**Investigation Needed**:
- The 30-second offset suggests buffer timing calculation issue
- File timestamps are correct (verified)
- Tone detector expects `buffer_middle_utc` (already correct)
- Need to trace `archive.calculate_utc_timestamp()` and buffer construction

## 📊 CURRENT SYSTEM STATUS

### Carrier Channels (9 total):
- **Sample rate**: Configured 200 Hz (radiod minimum)
- **Actual rate**: ~98 Hz effective (49% packet reception due to multicast loss)
- **Timing**: NTP_SYNCED (±10ms, adequate for <10 Hz Doppler analysis)
- **Data**: ⚠️ Currently all ZEROS (PT 97 bug) - FIX READY, needs restart

### Wide Channels:
- **Sample rate**: 16 kHz
- **Timing**: GPS_LOCKED via WWV tone detection (±1ms)
- **Status**: Working correctly

### Web UI:
- Carrier page working (showing proper channel types and timing)
- Spectrograms loading (but showing zeros until carrier bug fixed)

## 🔧 NEXT STEPS

1. **CRITICAL**: Restart core recorder to apply PT 97 fix
2. Verify carrier channels receiving real IQ data
3. Regenerate carrier spectrograms with real data
4. Compare carrier spectrograms (from radiod ~100 Hz) vs wide decimated (16 kHz→10 Hz)
5. Investigate 30-second tone timing offset (discrimination gap)

## 📁 FILES MODIFIED (Not Yet Committed)

- `src/signal_recorder/core_recorder.py` (PT 97 support)
- `web-ui/monitoring-server-v3.js` (carrier channel metadata)
- `web-ui/carrier.html` (UI display updates)

## 🎯 KEY INSIGHT

**The spectrograms looking identical makes sense**: They're BOTH using decimated data from the 16 kHz wide channel! The carrier channel files are all zeros, so the script must be falling back or the comparison wasn't actually using carrier data. Once PT 97 is fixed, we'll get real ~100 Hz data from radiod to compare against the decimated 16 kHz data.
