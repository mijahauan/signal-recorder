# System Status - Oct 31, 2025 @ 09:00

## ✅ All Services Running

### 1. Signal Recorder Daemon
- **PID**: 3645236
- **Config**: config/grape-S000171.toml
- **Log**: /tmp/signal-recorder-daemon.log
- **Status**: Running, receiving RTP packets
- **Channels**: 9 active (WWV 2.5, 5, 10, 15, 20, 25 MHz + CHU 3.33, 7.85, 14.67 MHz)

### 2. Watchdog
- **PID**: 3656528, 3656599
- **Log**: /tmp/watchdog.log
- **Status File**: data/daemon-status.json
- **Status**: Monitoring daemon

### 3. Web UI
- **URL**: http://localhost:3000/
- **Monitoring**: http://localhost:3000/monitoring
- **Status**: Running
- **Log**: Background process

---

## 🔧 Critical Fixes Applied

### Sample Rate Fix (CRITICAL)
- **Issue**: Was assuming 8 kHz complex IQ, actual is 16 kHz
- **Fixed**:
  - audio_streamer.py: Now processes 16 kHz IQ
  - grape_rtp_recorder.py: Tone detector resamples from 16k → 3k
  - simple-server.js: WAV header now 16 kHz
  - Chunk sizes updated: 800 samples @ 16kHz = 50ms

### WWV Timing Fix
- **Issue**: Was passing wrong timestamp (end of buffer instead of start)
- **Fixed**: Now tracks first sample timestamp in tone_accumulator

---

## 🧪 Current Testing Status

### Audio Quality
✅ Confirmed 16 kHz rate: `aplay /tmp/wwv-correct-rate.wav`
- Should sound clear and normal (not muffled)

### WWV Tone Detection
⚠️ Still seeing rejections in logs:
```
WWV detector: REJECTED duration=0.004s to 0.041s (need 0.5-1.2s)
```
- Envelope levels very low (max_env 0.01-0.04)
- Possible causes:
  1. Weak signal at this time
  2. Tone not present at minute boundary
  3. Need to adjust threshold further

### Web Audio Streaming
🔄 Ready to test - refresh browser and click 🔈 button
- Should hear clear 16 kHz audio (not choppy/muffled)

---

## 📊 Next Steps

1. **Test Web Audio**: Open http://localhost:3000/monitoring and test audio streaming
2. **Monitor WWV Detection**: Watch logs at next minute boundary (:00 seconds)
3. **Capture Minute Tone**: Run `python3 capture-minute-tone.py 5000000` to analyze actual tone presence
4. **Check Signal Strength**: May need to try different frequency if 5 MHz propagation poor

---

## 🐛 Known Issues

1. **WWV Tone Detection**: Not detecting yet (0% rate)
   - May need threshold adjustment OR
   - Tone may not be present in signal OR
   - Need to verify signal quality

2. **Two Watchdog Instances**: Harmless but should investigate

---

## 📝 Quick Commands

```bash
# Check daemon logs
tail -f /tmp/signal-recorder-daemon.log | grep -E "WWV tone|REJECTED"

# Test audio direct capture
cd /home/mjh/git/signal-recorder
python3 test-exact-rate.py 5000000
aplay /tmp/wwv-correct-rate.wav

# Capture minute boundary
python3 capture-minute-tone.py 5000000

# Restart daemon only
pkill -f "signal-recorder daemon"
venv/bin/signal-recorder daemon --config config/grape-S000171.toml &

# Check all processes
ps aux | grep -E "signal-recorder|watchdog|simple-server" | grep -v grep
```

---

*Status as of: 2025-10-31 09:00 EDT*
