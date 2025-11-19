# Web UI Cleanup - Investigation Summary

**Date**: Nov 18, 2025  
**Status**: Analysis complete, ready for cleanup

---

## Current Production Configuration

### Active Server
- **Production**: `monitoring-server-v3.js` (57KB)
- **Started by**: `../start-dual-service.sh` (line 214)
- **Entry point**: `index.html` → redirects to `summary.html`

### Active HTML Pages (Confirmed)

| Page | Size | Purpose | Evidence |
|------|------|---------|----------|
| **summary.html** | 18KB | Main dashboard | ⭐ Referenced in startup messages |
| **carrier.html** | 17KB | Carrier analysis | ⭐ Referenced in startup messages |
| **discrimination.html** | 13KB | WWV/WWVH discrimination | Used by monitoring server |
| **timing-dashboard.html** | 39KB | Timing quality dashboard | Has API endpoints in server |
| **index.html** | 2KB | Entry/redirect | Redirects to summary.html |

### Legacy/Questionable Pages

| Page | Size | Status | Evidence |
|------|------|--------|----------|
| **simple-dashboard.html** | 33KB | ? Legacy | Server has compatibility aliases for it |
| **analysis.html** | 27KB | ? Used | Multiple pages link to it |
| **channels.html** | 49KB | ? Legacy config | Some pages link to it |
| **live-status.html** | 10KB | ? Obsolete | No apparent references |
| **timing-analysis.html** | 15KB | ? Obsolete | Likely superseded by timing-dashboard |
| **quality-dashboard-addon.html** | 10KB | ? Component | May be embedded |

---

## Key Findings

### 1. Script Discrepancy

**web-ui/start-monitoring.sh** (outdated):
```bash
nohup node monitoring-server.js > monitoring-server.log 2>&1 &
#          ^^^^^^^^^^^^^^^^^^ This file doesn't exist!
```

**Should be**:
```bash
nohup node monitoring-server-v3.js > monitoring-server.log 2>&1 &
#          ^^^^^^^^^^^^^^^^^^^^ Correct filename
```

**Production start script** (`../start-dual-service.sh`) is correct.

### 2. Compatibility Aliases

`monitoring-server-v3.js` includes backward-compatibility for `simple-dashboard.html`:
```javascript
// Line 920-922
services: processes,  // Alias for compatibility with simple-dashboard.html
radiod: processes.radiod,  // Top-level alias for simple-dashboard.html
disk: disk,  // Add disk info for simple-dashboard.html
```

**Question**: Is simple-dashboard still used, or can we remove it and these aliases?

### 3. Inter-Page Links

Several pages link to **analysis.html** and **channels.html**:
```html
<a href="/analysis.html">Analysis</a>
<a href="/channels.html">Channels</a>
```

**Question**: Are these navigation targets still valid?

### 4. Empty Data Files

```bash
$ ls -lh channels.json configurations.json
-rw-r--r-- 1 mjh mjh 3 Nov 18 18:13 channels.json
-rw-r--r-- 1 mjh mjh 3 Nov 18 18:13 configurations.json
```

Both are 3 bytes (empty JSON: `{}`). These appear to be from the old configuration UI (simple-server.js).

---

## Recommended Cleanup Actions

### Phase 1: Fix Scripts

**Update web-ui/start-monitoring.sh**:
```bash
#!/bin/bash
# Start GRAPE Monitoring Server

cd "$(dirname "$0")"

echo "🚀 Starting GRAPE Monitoring Server..."

# Stop any existing instance
pkill -f monitoring-server 2>/dev/null
sleep 1

# Start the correct server
nohup node monitoring-server-v3.js > monitoring-server.log 2>&1 &

sleep 2

# Check if it started
if pgrep -f monitoring-server-v3 > /dev/null; then
    echo "✅ Server started successfully!"
    echo ""
    echo "📊 Access the dashboards:"
    echo "   http://localhost:3000/           (redirects to summary)"
    echo "   http://localhost:3000/summary.html"
    echo "   http://localhost:3000/carrier.html"
    echo "   http://localhost:3000/discrimination.html"
    echo "   http://localhost:3000/timing-dashboard.html"
    echo ""
    echo "📝 View logs:"
    echo "   tail -f monitoring-server.log"
else
    echo "❌ Failed to start server"
    echo "Check monitoring-server.log for errors"
    exit 1
fi
```

### Phase 2: Archive Legacy Pages (After User Confirmation)

**Create archive directory**:
```bash
mkdir -p web-ui/archive/legacy-pages
```

**Archive these if confirmed obsolete**:
```bash
# Confirmed legacy from old config UI
mv web-ui/simple-server.js.ARCHIVED-config-ui web-ui/archive/legacy-pages/

# Potentially obsolete (USER TO CONFIRM):
mv web-ui/simple-dashboard.html web-ui/archive/legacy-pages/
mv web-ui/live-status.html web-ui/archive/legacy-pages/
mv web-ui/timing-analysis.html web-ui/archive/legacy-pages/
mv web-ui/quality-dashboard-addon.html web-ui/archive/legacy-pages/

# These may still be used - CHECK FIRST:
# analysis.html - Referenced in nav links
# channels.html - Referenced in nav links
```

### Phase 3: Clean Empty Data Files

```bash
# Only if confirmed unused (old config UI artifacts)
rm -f web-ui/channels.json web-ui/configurations.json
```

### Phase 4: Update Documentation

**web-ui/README.md** currently documents:
- Simple-server.js (obsolete config UI)
- JSON-based configuration (obsolete)

**Should document**:
- monitoring-server-v3.js (production server)
- Active dashboards: summary, carrier, discrimination, timing
- Real-time monitoring capabilities
- Path synchronization (grape-paths.js)

---

## Questions for User

Before proceeding with cleanup, please clarify:

1. **simple-dashboard.html**: Still used or superseded by summary.html?

2. **analysis.html**: Actively used for correlation analysis or obsolete?

3. **channels.html**: Still used for channel management or config-file only now?

4. **quality-dashboard-addon.html**: Standalone page or embedded component?

5. **live-status.html**: Used anywhere or replaced by summary.html?

6. **timing-analysis.html**: Used or superseded by timing-dashboard.html?

---

## Proposed Final Structure

```
web-ui/
├── README.md                         # ← UPDATE with current architecture
├── package.json
├── pnpm-lock.yaml
│
├── monitoring-server-v3.js           # Production server
├── grape-paths.js                    # Path synchronization
├── ka9q-radio-proxy.cjs              # Radiod proxy
├── gstream-audio-proxy.js            # Audio streaming
│
├── index.html                        # Entry (redirects to summary)
├── summary.html                      # ⭐ Main dashboard
├── carrier.html                      # ⭐ Carrier analysis
├── discrimination.html               # ⭐ WWV/WWVH discrimination
├── timing-dashboard.html             # ⭐ Timing quality
├── discrimination.js                 # Chart logic
│
├── [analysis.html]                   # ← Keep if actively used
├── [channels.html]                   # ← Keep if actively used
│
├── utils/                            # Utility modules
│   ├── audit.js
│   ├── auth.js
│   ├── config-sync.js
│   └── radiod.js
│
├── middleware/                       # Express middleware
│   └── validation.js
│
├── scripts/                          # Admin scripts
│   └── create-admin.js
│
├── data/                             # Runtime data
│   ├── users.json
│   ├── jwt-secret.txt
│   └── .gitignore
│
├── start-monitoring.sh               # ← UPDATE to use -v3.js
├── start-audio-proxy.sh
├── check-dashboard-status.sh
│
└── archive/                          # Legacy artifacts
    └── legacy-pages/
        ├── simple-server.js.ARCHIVED-config-ui
        ├── simple-dashboard.html     # ← If confirmed obsolete
        ├── live-status.html          # ← If confirmed obsolete
        ├── timing-analysis.html      # ← If confirmed obsolete
        └── quality-dashboard-addon.html  # ← If confirmed obsolete
```

---

## Benefits of Cleanup

1. **Clarity**: Clear which dashboards are production
2. **Correct scripts**: start-monitoring.sh will work
3. **Updated docs**: README reflects current architecture
4. **Less confusion**: Obsolete pages archived, not deleted
5. **Easier maintenance**: Focus on active dashboards

---

## Next Steps

1. **User clarifies** which HTML pages are actively used
2. **Update** start-monitoring.sh to use correct server name
3. **Archive** confirmed obsolete pages
4. **Update** web-ui/README.md with current architecture
5. **Test** that all production dashboards still work
6. **Commit** cleanup changes

---

## Files to Review with User

Please check if these are actively used:
- [ ] `web-ui/simple-dashboard.html`
- [ ] `web-ui/analysis.html`
- [ ] `web-ui/channels.html`
- [ ] `web-ui/quality-dashboard-addon.html`
- [ ] `web-ui/live-status.html`
- [ ] `web-ui/timing-analysis.html`

---

**Status**: Awaiting user input on page usage before proceeding with archival
