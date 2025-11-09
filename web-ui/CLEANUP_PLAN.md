# Web-UI Cleanup and Modernization Plan

## Current State (Before Cleanup)

```
web-ui/
├── monitoring-server.js          ✅ KEEP - Main server (needs refactoring)
├── timing-dashboard.html         ✅ KEEP - Will update to new API
├── live-status.html              ⚠️  EVALUATE - Redundant with timing dashboard?
├── index.html                    ⚠️  EVALUATE - What does this serve?
│
├── monitoring.html.OLD           ❌ DELETE - Legacy backup
├── monitoring.html.backup        ❌ DELETE - Legacy backup
├── index.html.OLD                ❌ DELETE - Legacy backup
│
├── simple-server.js              ⚠️  EVALUATE - 90KB! Why so large?
├── simple-server.js.backup-*     ❌ DELETE - Backups
│
├── gstream-audio-proxy.js        ✅ KEEP - Audio streaming
├── ka9q-radio-proxy.cjs          ✅ KEEP - Radiod proxy
├── start-monitoring.sh           ✅ KEEP - Startup script
├── start-audio-proxy.sh          ✅ KEEP - Audio startup
│
└── Documentation (many .md files) ✅ KEEP - Historical context
```

## Files to Delete

### Immediate Deletion (Legacy Backups)
```bash
rm -f web-ui/monitoring.html.OLD
rm -f web-ui/monitoring.html.backup
rm -f web-ui/index.html.OLD
rm -f web-ui/simple-server.js.backup-20251103-094306
rm -f web-ui/simple-server.js.backup-20251104-070345
```

### Evaluate Before Deletion

1. **`simple-server.js`** (90KB)
   - Check if it's still used
   - If obsolete → DELETE
   - If used → Document purpose, consider refactoring

2. **`live-status.html`**
   - If it duplicates `timing-dashboard.html` → DELETE
   - If it serves unique purpose → UPDATE to new API

3. **`index.html`**
   - If it's just a redirect → Replace with server redirect
   - If it has content → Merge into main dashboard

---

## Proposed Clean Structure

```
web-ui/
├── server/                         # Backend (Node.js)
│   ├── api/                        # API route handlers
│   │   ├── v1/
│   │   │   ├── system.js          # System status endpoints
│   │   │   ├── quality.js         # Quality metrics endpoints
│   │   │   ├── timing.js          # Timing/WWV endpoints
│   │   │   ├── data.js            # Data analytics endpoints
│   │   │   └── upload.js          # Upload status endpoints
│   │   └── index.js               # API router
│   │
│   ├── services/                   # Business logic
│   │   ├── quality-analyzer.js    # Quality data processing
│   │   ├── spectrogram-generator.js # Spectrogram creation
│   │   ├── disk-monitor.js        # Disk usage tracking
│   │   └── error-collector.js     # Error log aggregation
│   │
│   ├── utils/                      # Utilities
│   │   ├── config-loader.js       # TOML config parsing
│   │   ├── csv-parser.js          # CSV data parsing
│   │   └── cache.js               # Response caching
│   │
│   ├── monitoring-server.js       # Main server entry point
│   └── package.json
│
├── public/                         # Frontend (Static files)
│   ├── dashboards/
│   │   ├── system-status.html     # Tier 1: System health
│   │   ├── timing.html            # Timing & WWV analysis
│   │   ├── quality.html           # Quality metrics
│   │   ├── spectrograms.html      # Spectrogram viewer
│   │   └── uploads.html           # Upload monitoring
│   │
│   ├── js/
│   │   ├── api-client.js          # API wrapper
│   │   ├── charts.js              # Chart.js configurations
│   │   ├── utils.js               # Utilities
│   │   └── components/
│   │       ├── channel-status.js  # Reusable components
│   │       ├── quality-badge.js
│   │       └── time-snap-indicator.js
│   │
│   ├── css/
│   │   ├── main.css               # Main styles
│   │   └── dashboard.css          # Dashboard-specific
│   │
│   └── index.html                 # Landing page / redirect
│
├── scripts/                        # Python data processing
│   ├── generate_spectrogram.py    # Spectrogram generation
│   ├── analyze_quality.py         # Quality analysis
│   └── compute_signal_power.py    # Signal power calculation
│
├── cache/                          # Generated assets
│   ├── spectrograms/              # PNG files
│   └── api-responses/             # Cached JSON
│
├── proxies/                        # External service proxies
│   ├── gstream-audio-proxy.js     # Audio streaming
│   └── ka9q-radio-proxy.cjs       # Radiod interface
│
├── docs/                           # Documentation
│   ├── API.md                     # API documentation
│   ├── ARCHITECTURE.md            # System architecture
│   └── CHANGELOG.md               # Version history
│
└── start-monitoring.sh            # Startup script
```

---

## Migration Steps

### Step 1: Create New Structure (Don't break existing!)

```bash
cd web-ui

# Create new directories
mkdir -p server/api/v1
mkdir -p server/services
mkdir -p server/utils
mkdir -p public/dashboards
mkdir -p public/js/components
mkdir -p public/css
mkdir -p scripts
mkdir -p cache/spectrograms
mkdir -p proxies
mkdir -p docs
```

### Step 2: Refactor API (Incremental)

**Create `server/api/v1/system.js`:**
```javascript
// System status endpoints
export const getStatus = async (req, res) => {
  // Move logic from monitoring-server.js
  const status = {
    timestamp: new Date().toISOString(),
    recorder: await getRecorderStatus(),
    radiod: await getRadiodStatus(),
    channels: await getChannelStatus(),
    // ... etc
  };
  res.json(status);
};

export const getHealth = async (req, res) => {
  res.json({ status: 'healthy', checks: { ... } });
};

export const getErrors = async (req, res) => {
  const { since, severity } = req.query;
  const errors = await errorCollector.getErrors(since, severity);
  res.json({ errors });
};
```

**Create `server/api/v1/quality.js`:**
```javascript
// Quality metrics endpoints
export const getSummary = async (req, res) => {
  const { date, hour } = req.query;
  const summary = await qualityAnalyzer.getSummary(date, hour);
  res.json(summary);
};

export const getTimeline = async (req, res) => {
  // ... etc
};
```

### Step 3: Update Main Server

**Refactor `monitoring-server.js`:**
```javascript
import express from 'express';
import apiRouter from './api/index.js';

const app = express();

// Middleware
app.use(express.json());
app.use(express.static('public'));

// API routes (versioned)
app.use('/api/v1', apiRouter);

// Legacy redirects (for backwards compatibility)
app.get('/api/monitoring/station-info', (req, res) => {
  res.redirect(301, '/api/v1/system/status');
});
app.get('/api/monitoring/timing-quality', (req, res) => {
  res.redirect(301, '/api/v1/quality/summary');
});

// Serve main dashboard
app.get('/', (req, res) => {
  res.sendFile('public/dashboards/system-status.html');
});

app.listen(3000);
```

### Step 4: Build New Dashboards

**Create `public/dashboards/system-status.html`:**
- Use new `/api/v1/system/status` endpoint
- Clean, modern design
- Real-time updates (SSE or polling)

**Update `timing-dashboard.html`:**
- Migrate to `/api/v1/timing/*` and `/api/v1/quality/*`
- Add WWV/WWVH discrimination charts
- Keep existing functionality

### Step 5: Add New Features

1. **Spectrograms** - New dashboard + API endpoint
2. **Upload monitoring** - New dashboard showing Function 6 status
3. **Detection timeline** - Visual timeline for all channels
4. **Signal power plots** - Power vs time charts

### Step 6: Clean Up

```bash
# After testing new structure works:
rm -f monitoring.html.OLD monitoring.html.backup index.html.OLD
rm -f simple-server.js.backup-*

# Move proxies
mv gstream-audio-proxy.js proxies/
mv ka9q-radio-proxy.cjs proxies/

# Archive old server if not needed
mv simple-server.js simple-server.js.archived
```

---

## Backward Compatibility

During migration, maintain compatibility:

1. **Keep old endpoints** with 301 redirects to new ones
2. **Preserve response formats** where possible
3. **Add deprecation warnings** in API responses
4. **Document migration** in CHANGELOG.md

---

## Testing Checklist

- [ ] All existing endpoints still work (redirects)
- [ ] New API endpoints return correct data
- [ ] System status dashboard loads
- [ ] Timing dashboard works with new API
- [ ] Spectrograms generate correctly
- [ ] Error handling works (404, 500, etc.)
- [ ] Performance acceptable (response times)
- [ ] Auto-refresh works without memory leaks
- [ ] Works on mobile/tablet screens

---

## Deployment

### Development
```bash
cd web-ui
npm install
node server/monitoring-server.js
```

### Production
```bash
# Use PM2 or systemd
pm2 start server/monitoring-server.js --name grape-monitoring

# Or update systemd service
# (already exists in systemd/signal-recorder.service)
```

---

## Timeline

- **Week 1**: Structure setup, API refactoring
- **Week 2**: System status dashboard, quality API
- **Week 3**: Spectrograms, signal power
- **Week 4**: Upload monitoring, cleanup
- **Week 5**: Testing, documentation, deployment

---

## Questions to Answer

1. **Is `simple-server.js` still needed?**
   - If yes, what does it do?
   - If no, can we delete it?

2. **What should `index.html` be?**
   - Redirect to main dashboard?
   - Landing page with links?
   - Login page (if auth added later)?

3. **Keep audio streaming separate?**
   - Current: `gstream-audio-proxy.js`
   - Integrate into main server or keep separate?

4. **Spectrogram generation**:
   - Real-time or batch (hourly cron)?
   - Cache strategy?
   - Image format (PNG, JPEG, WebP)?

5. **Mobile support priority?**
   - Desktop-only OK?
   - Or responsive design required?
