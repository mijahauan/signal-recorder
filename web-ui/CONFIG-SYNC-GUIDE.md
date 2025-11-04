# Configuration File Synchronization Guide

**Feature**: Automatic sync of TOML config with radiod channels

---

## What It Does

The **Sync Default Config** button reads your `grape-S000171.toml` file and ensures all defined channels are created and running in radiod.

### Process

1. **Reads** `config/grape-S000171.toml`
2. **Parses** all `[[recorder.channels]]` sections
3. **Checks** if each channel exists in radiod
4. **Creates** any missing channels
5. **Verifies** all channels are running
6. **Reports** status of each channel

---

## How to Use

### Quick Start

1. Navigate to http://localhost:3000/
2. Login
3. Click **🔄 Sync Default Config** button
4. Watch real-time sync status
5. See results for each channel

### Button Location

The button is in the **Recording Daemon** section at the top of the dashboard, next to Start/Stop Recording buttons.

---

## Status Indicators

After sync completes, you'll see status for each channel:

- ✅ **Verified** - Channel already existed in radiod
- 🆕 **Created** - Channel was created successfully
- ❌ **Failed** - Channel creation failed (see error)
- ⏭️ **Skipped** - Channel disabled in config (`enabled = false`)

### Example Output

```
✅ Sync complete: 6 verified, 3 created, 0 failed, 0 skipped

✅ WWV 2.5 MHz (2500000 Hz) - Channel already exists in radiod
✅ WWV 5 MHz (5000000 Hz) - Channel already exists in radiod
🆕 WWV 10 MHz (10000000 Hz) - Channel created and verified
🆕 WWV 15 MHz (15000000 Hz) - Channel created and verified
🆕 WWV 20 MHz (20000000 Hz) - Channel created and verified
✅ WWV 25 MHz (25000000 Hz) - Channel already exists in radiod
✅ CHU 3.33 MHz (3330000 Hz) - Channel already exists in radiod
✅ CHU 7.85 MHz (7850000 Hz) - Channel already exists in radiod
✅ CHU 14.67 MHz (14670000 Hz) - Channel already exists in radiod
```

---

## Config File Format

The system reads your TOML config file which looks like:

```toml
[station]
callsign = "S000171"
grid_square = "EM13"
id = "S000171"
instrument_id = "I000171"

[[recorder.channels]]
ssrc = 2500000
frequency_hz = 2500000
preset = "iq"
sample_rate = 16000
agc = 0
gain = 0
description = "WWV 2.5 MHz"
enabled = true
processor = "grape"

[[recorder.channels]]
ssrc = 5000000
frequency_hz = 5000000
preset = "iq"
sample_rate = 16000
agc = 0
gain = 0
description = "WWV 5 MHz"
enabled = true
processor = "grape"

# ... more channels ...
```

### Channel Properties

| Property | Required | Description |
|----------|----------|-------------|
| `ssrc` | Yes | Unique channel identifier |
| `frequency_hz` | Yes | Frequency in Hertz |
| `description` | Recommended | Human-readable name |
| `preset` | No | Default: "iq" |
| `sample_rate` | No | Default: 16000 |
| `enabled` | No | Default: true |
| `agc` | No | Automatic Gain Control |
| `gain` | No | Fixed gain |
| `processor` | No | Default: "grape" |

---

## API Endpoints

### POST `/api/config/sync`

Synchronize config file with radiod.

**Request**:
```json
{
  "configPath": null,  // null = use default grape-S000171.toml
  "createMissing": true
}
```

**Response**:
```json
{
  "success": true,
  "configPath": "/path/to/config/grape-S000171.toml",
  "timestamp": "2025-11-03T16:00:00.000Z",
  "station": {
    "callsign": "S000171",
    "grid_square": "EM13",
    "id": "S000171"
  },
  "channels": [
    {
      "ssrc": 2500000,
      "frequencyHz": 2500000,
      "description": "WWV 2.5 MHz",
      "status": "verified",
      "message": "Channel already exists in radiod"
    },
    {
      "ssrc": 10000000,
      "frequencyHz": 10000000,
      "description": "WWV 10 MHz",
      "status": "created",
      "message": "Channel created and verified"
    }
  ],
  "summary": {
    "total": 9,
    "verified": 6,
    "created": 3,
    "failed": 0,
    "skipped": 0
  }
}
```

### GET `/api/config/parse`

Parse config file without syncing.

**Query Parameters**:
- `path` - Config file path (optional, defaults to grape-S000171.toml)

**Response**:
```json
{
  "success": true,
  "configPath": "/path/to/config/grape-S000171.toml",
  "station": {...},
  "channels": [...],
  "channelCount": 9
}
```

### POST `/api/config/import-channels`

Import channels from config file into database.

**Request**:
```json
{
  "configPath": null,  // Optional
  "configId": "config-123"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Imported 9 channels",
  "channels": [...]
}
```

---

## Use Cases

### 1. Initial Setup

When setting up a new system:

1. Edit `config/grape-S000171.toml` with your channels
2. Click **Sync Default Config**
3. All channels created in radiod automatically
4. Start recording immediately

### 2. Adding New Channels

When you want to add new channels:

1. Edit `config/grape-S000171.toml`
2. Add new `[[recorder.channels]]` sections
3. Click **Sync Default Config**
4. Only new channels are created (existing ones stay)

### 3. System Recovery

After radiod restart or crash:

1. Click **Sync Default Config**
2. All channels from config are recreated
3. System back to full operation

### 4. Configuration Validation

To verify config file without making changes:

1. Use API: `GET /api/config/parse`
2. Check response for parsing errors
3. Fix any issues in TOML file

---

## Troubleshooting

### "Config file not found"

**Problem**: Can't find `grape-S000171.toml`

**Solution**:
```bash
# Check file exists
ls -la /home/mjh/git/signal-recorder/config/grape-S000171.toml

# If missing, create from template
cp config/grape-example.toml config/grape-S000171.toml
```

### "Failed to parse config file"

**Problem**: TOML syntax error

**Solution**:
1. Check for missing quotes, brackets, or commas
2. Validate TOML online: https://www.toml-lint.com/
3. Compare with working example

### "Channel creation failed"

**Problem**: Radiod can't create channel

**Possible Causes**:
- Radiod not running
- Invalid frequency (out of range)
- SSRC already in use
- Network/multicast issues

**Solutions**:
```bash
# Check radiod status
ps aux | grep radiod

# Check radiod can be reached
control -v bee1-hf-status.local

# Check for existing channels
control -v bee1-hf-status.local | grep <SSRC>
```

### "Some channels skipped"

**Not an Error**: Channels with `enabled = false` are intentionally skipped.

To enable:
1. Edit config file
2. Change `enabled = false` to `enabled = true`
3. Re-sync

---

## Performance

### Sync Speed

- **Parse config**: <100ms
- **Check channel**: ~100-300ms each
- **Create channel**: ~1-3 seconds each
- **Total time**: Depends on channels (typically 5-30 seconds)

### Example Timing

```
9 channels total
├─ 6 already exist: ~1.8 seconds (6 × 300ms)
├─ 3 to create: ~6 seconds (3 × 2s)
└─ Total: ~8 seconds
```

---

## Technical Details

### Implementation

**Backend** (`utils/config-sync.js`):
- Uses `toml` npm package for parsing
- Spawns Python scripts via ka9q-python
- Validates each channel before creation
- Verifies channels after creation

**Frontend** (`index.html`):
- Real-time status updates
- Detailed per-channel reporting
- Color-coded status indicators
- Toast notifications for summary

### Security

✅ **Input Validation**:
- SSRC validated (0 - 0xFFFFFFFF)
- Frequency validated (0 - 30 MHz)
- Sample rate validated (positive integer)

✅ **Path Security**:
- Config path sanitized
- No directory traversal allowed
- File existence verified

✅ **Audit Logging**:
- All sync operations logged
- Success/failure tracked
- User attribution

---

## Integration with Workflow

### Typical Workflow

```
1. Edit grape-S000171.toml
   ├─ Add/modify channels
   ├─ Set frequencies
   └─ Configure parameters

2. Sync Default Config
   ├─ Reads TOML file
   ├─ Creates missing channels
   └─ Verifies all channels

3. Start Recording
   ├─ Channels already configured
   ├─ RTP streams active
   └─ Data being recorded

4. Monitor Operations
   ├─ Check channel status
   ├─ View timing data
   └─ Export configurations
```

### Best Practices

1. **Always sync after editing config**
   - Ensures radiod matches config file
   - Catches errors early

2. **Sync after radiod restart**
   - Recreates all channels
   - Faster than manual setup

3. **Keep config file as source of truth**
   - Edit TOML, not radiod directly
   - Version control your config
   - Document changes

4. **Test with parse first**
   - Validate syntax before syncing
   - Catch errors without creating channels

---

## Advanced Usage

### Custom Config Path

Use a different config file:

```javascript
await apiRequest('/config/sync', {
    method: 'POST',
    body: JSON.stringify({
        configPath: '/path/to/custom-config.toml',
        createMissing: true
    })
});
```

### Sync Without Creating

Check status without creating missing channels:

```javascript
await apiRequest('/config/sync', {
    method: 'POST',
    body: JSON.stringify({
        configPath: null,
        createMissing: false  // Only check, don't create
    })
});
```

### Automated Sync on Startup

Add to your startup script:

```bash
#!/bin/bash
# Start radiod
radiod -c /path/to/radiod.conf &

# Wait for radiod to initialize
sleep 5

# Sync channels from config
curl -X POST http://localhost:3000/api/config/sync \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"createMissing": true}'
```

---

## Future Enhancements

Planned features:

1. **Bi-directional sync**
   - Discover channels from radiod
   - Update config file with running channels

2. **Diff view**
   - Show what will change before syncing
   - Highlight additions/removals

3. **Scheduled sync**
   - Auto-sync every N minutes
   - Ensure channels stay configured

4. **Backup/restore**
   - Save channel state
   - Restore after crashes

5. **Multi-config support**
   - Switch between different configs
   - A/B testing setups

---

## Conclusion

The **Sync Default Config** feature provides:

✅ **Automatic channel setup** from TOML config  
✅ **Verification** of all channels  
✅ **Clear status reporting** for each channel  
✅ **Error handling** with helpful messages  
✅ **Audit trail** of all operations  

**Result**: Your `grape-S000171.toml` is now the single source of truth, and radiod automatically matches it! 🎉
