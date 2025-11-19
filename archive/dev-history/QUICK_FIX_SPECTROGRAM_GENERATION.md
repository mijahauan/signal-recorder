# Quick Fix: Spectrogram Generation Error

## Error
```
❌ Failed to start spectrogram generation: JSON.parse: unexpected character at line 1 column 1 of the JSON data
```

## Root Cause
The monitoring server needs to be **restarted** to pick up the new API endpoints that were just added.

## Fix (Choose One Method)

### Method 1: Using PM2 (if running as service)
```bash
cd /home/mjh/git/signal-recorder/web-ui
pm2 restart grape-monitoring
# OR: pm2 restart all
```

### Method 2: Manual Restart
```bash
# 1. Stop the current server (Ctrl+C if running in terminal)
# OR find and kill the process:
ps aux | grep monitoring-server
kill <PID>

# 2. Start it again:
cd /home/mjh/git/signal-recorder/web-ui
node monitoring-server.js
# OR with pm2:
pm2 start monitoring-server.js --name grape-monitoring
```

### Method 3: Check if server is running at all
```bash
# See if monitoring server is running:
ps aux | grep monitoring-server

# Check if port 3000 is in use:
lsof -i :3000
# OR: netstat -tlnp | grep 3000

# If nothing is running:
cd /home/mjh/git/signal-recorder/web-ui
node monitoring-server.js
```

## Verification

After restarting, check the server logs for:
```
📊 GRAPE Monitoring Server
📁 Config file: /home/mjh/git/signal-recorder/config/grape-config.toml
🧪 Mode: TEST
📁 Data root: /tmp/grape-test
📡 Station: <callsign> <grid>
🌐 Server running on http://localhost:3000
```

Then try the spectrogram generation again in the browser.

## Still Getting Errors?

If you still see the error after restart, check:

### 1. Verify the endpoint exists
```bash
# The POST endpoint should be in the server file:
grep -n "app.post.*spectrograms/generate" web-ui/monitoring-server.js
# Should show line ~954
```

### 2. Test the endpoint directly
```bash
# Try calling it with curl:
curl -X POST http://localhost:3000/api/v1/spectrograms/generate \
  -H "Content-Type: application/json" \
  -d '{"date":"20251112","type":"carrier"}'

# Should return JSON like:
# {"jobId":"carrier_20251112_...","status":"started","message":"..."}
```

### 3. Check for JavaScript syntax errors
```bash
# Validate the JavaScript file:
node -c web-ui/monitoring-server.js
# Should print nothing (no errors)
```

### 4. Check server logs
```bash
# If using PM2:
pm2 logs grape-monitoring

# If running manually, look at the terminal output for errors
```

## Common Issues

### Issue: "Cannot find module 'spawn'"
**Fix**: `spawn` is part of `child_process`, check line 18:
```javascript
import { exec, spawn } from 'child_process';
```

### Issue: "spectrogramJobs is not defined"
**Fix**: Check line 24 for:
```javascript
const spectrogramJobs = new Map();
```

### Issue: Port 3000 already in use
**Fix**: Kill the old process:
```bash
lsof -i :3000
kill -9 <PID>
```

## Prevention

Set up proper service management:

```bash
# Install PM2 globally (if not already):
npm install -g pm2

# Start with PM2:
cd /home/mjh/git/signal-recorder/web-ui
pm2 start monitoring-server.js --name grape-monitoring

# Save PM2 config:
pm2 save

# Enable autostart on boot:
pm2 startup
```

Then future restarts are just:
```bash
pm2 restart grape-monitoring
```
