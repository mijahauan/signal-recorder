# Web UI Cleanup Proposal

**Date**: Nov 18, 2025  
**Purpose**: Organize web UI files and archive development artifacts

---

## Current Web UI Status

**Production Server**: `monitoring-server-v3.js` (57KB)
- Serves monitoring dashboard
- Real-time data via WebSocket/polling
- Static file serving from web-ui directory

**Entry Points** (based on monitoring-server-v3.js startup messages):
- `http://localhost:3000/summary.html` - Summary dashboard
- `http://localhost:3000/carrier.html` - Carrier analysis

---

## File Inventory

### Active HTML Pages

| File | Size | Purpose | Status |
|------|------|---------|--------|
| `summary.html` | 18KB | Main summary dashboard | ✅ KEEP (production) |
| `carrier.html` | 17KB | Carrier analysis screen | ✅ KEEP (production) |
| `discrimination.html` | 13KB | WWV/WWVH discrimination | ✅ KEEP (production) |
| `timing-dashboard.html` | 39KB | Timing quality dashboard | ? Review usage |
| `index.html` | 2KB | Entry point/redirect | ✅ KEEP |

### Potentially Obsolete HTML

| File | Size | Purpose | Recommendation |
|------|------|---------|----------------|
| `simple-dashboard.html` | 33KB | Legacy dashboard? | Archive if superseded by summary.html |
| `quality-dashboard-addon.html` | 10KB | Add-on component | Merge or archive |
| `timing-analysis.html` | 15KB | Timing analysis | Archive if superseded by timing-dashboard |
| `live-status.html` | 10KB | Live status page | Archive if not used |
| `analysis.html` | 27KB | Analysis page | Clarify usage or archive |
| `channels.html` | 49KB | Channel management | Archive if config-only |

### JavaScript Files

| File | Size | Purpose | Status |
|------|------|---------|--------|
| `monitoring-server-v3.js` | 57KB | **Production server** | ✅ KEEP |
| `grape-paths.js` | 12KB | Path management (Python sync) | ✅ KEEP |
| `discrimination.js` | 14KB | Discrimination chart logic | ✅ KEEP |
| `simple-server.js.ARCHIVED-config-ui` | 91KB | **Already archived** | ✅ Verify archive |
| `ka9q-radio-proxy.cjs` | 6KB | Radiod proxy | ✅ KEEP |
| `gstream-audio-proxy.js` | 3KB | Audio streaming | ✅ KEEP |

### Support Files (Utils, Middleware)

| Directory | Files | Status |
|-----------|-------|--------|
| `utils/` | audit.js, auth.js, config-sync.js, radiod.js | ✅ KEEP |
| `middleware/` | validation.js | ✅ KEEP |
| `scripts/` | create-admin.js | ✅ KEEP |

### Shell Scripts

| File | Purpose | Status |
|------|---------|--------|
| `start-monitoring.sh` | Start monitoring server | ✅ KEEP |
| `start-audio-proxy.sh` | Start audio proxy | ✅ KEEP |
| `check-dashboard-status.sh` | Health check | ✅ KEEP |
| `start-summary-test.sh` | Testing script | ? Review |

### Build/Dev Files

| File/Dir | Purpose | Recommendation |
|----------|---------|----------------|
| `dist/` | Build output | Delete if generated |
| `client/` | Source files? | Check if used |
| `node_modules/` | Dependencies | ✅ KEEP (git ignored) |
| `build-output.txt` | Build log | Archive |

### Data Files

| File | Purpose | Status |
|------|---------|--------|
| `channels.json` | Channel config (empty: 3 bytes) | Delete if unused |
| `configurations.json` | Config storage (empty: 3 bytes) | Delete if unused |
| `users.json` | User auth | ✅ KEEP |
| `cookies.txt` | Session data | ✅ KEEP (runtime) |
| `monitoring-server.log` | Server log | ✅ KEEP (runtime) |

---

## Cleanup Actions

### Phase 1: Archive Obsolete HTML Pages

**Create**: `web-ui/archive/legacy-pages/`

**Move these if confirmed obsolete**:
```bash
mkdir -p web-ui/archive/legacy-pages

# Verify these are not actively used first
mv simple-dashboard.html archive/legacy-pages/
mv live-status.html archive/legacy-pages/
mv quality-dashboard-addon.html archive/legacy-pages/
mv timing-analysis.html archive/legacy-pages/  # if superseded by timing-dashboard
mv analysis.html archive/legacy-pages/  # if not used
mv channels.html archive/legacy-pages/  # if config-only
```

### Phase 2: Clean Build Artifacts

```bash
# Delete generated files
rm -f build-output.txt

# Clean dist/ if it's generated
rm -rf dist/  # Only if confirmed generated

# Check client/ directory
# If it's empty or legacy, archive it
```

### Phase 3: Archive Empty/Unused Data Files

```bash
# If these are truly unused (3 bytes = empty JSON)
rm -f channels.json
rm -f configurations.json
```

### Phase 4: Documentation Update

Update `web-ui/README.md` to reflect current architecture:
- Remove references to simple-server.js
- Document monitoring-server-v3.js as production
- Document active pages: summary, carrier, discrimination, timing-dashboard
- Remove legacy configuration UI documentation

---

## Investigation Needed

Before archiving, verify usage:

### 1. Check HTML References in Server

```bash
cd /home/mjh/git/signal-recorder/web-ui
grep -n "simple-dashboard\|live-status\|quality-dashboard-addon\|timing-analysis\|analysis\.html\|channels\.html" monitoring-server-v3.js
```

### 2. Check HTML Cross-References

```bash
# See if HTML pages link to each other
grep -r "href.*\.html" *.html | grep -v "summary\|carrier\|discrimination\|timing-dashboard\|index"
```

### 3. Check Startup Scripts

```bash
# What does start-monitoring.sh actually start?
cat start-monitoring.sh

# What about start-summary-test.sh?
cat start-summary-test.sh
```

### 4. Check for iframe Embeds

```bash
# Do active pages embed the "addon" pages?
grep -n "iframe\|embed" summary.html carrier.html discrimination.html timing-dashboard.html
```

---

## Questions for User

1. **simple-dashboard.html vs summary.html**: Are both used, or is simple-dashboard legacy?

2. **timing-analysis.html vs timing-dashboard.html**: Which is current?

3. **analysis.html**: Is this actively used for any correlation analysis?

4. **channels.html**: Still used for channel management, or config-file only?

5. **quality-dashboard-addon.html**: Standalone page or component embedded elsewhere?

6. **live-status.html**: Replaced by summary.html?

---

## Proposed Final Web UI Structure

```
web-ui/
├── README.md                      # Updated documentation
├── package.json                   # Dependencies
├── pnpm-lock.yaml                 # Lock file
│
├── monitoring-server-v3.js        # Production server
├── grape-paths.js                 # Path sync
├── ka9q-radio-proxy.cjs           # Radiod proxy
├── gstream-audio-proxy.js         # Audio proxy
│
├── index.html                     # Entry point
├── summary.html                   # Main dashboard ⭐
├── carrier.html                   # Carrier analysis ⭐
├── discrimination.html            # WWV/WWVH ⭐
├── timing-dashboard.html          # Timing quality ⭐
├── discrimination.js              # Chart logic
│
├── utils/                         # Utilities
│   ├── audit.js
│   ├── auth.js
│   ├── config-sync.js
│   └── radiod.js
│
├── middleware/                    # Middleware
│   └── validation.js
│
├── scripts/                       # Admin scripts
│   └── create-admin.js
│
├── data/                          # Runtime data
│   ├── users.json
│   └── jwt-secret.txt
│
├── start-monitoring.sh            # Startup scripts
├── start-audio-proxy.sh
├── check-dashboard-status.sh
│
└── archive/                       # Historical
    └── legacy-pages/
        ├── simple-dashboard.html
        ├── live-status.html
        ├── analysis.html
        ├── channels.html
        ├── timing-analysis.html
        ├── quality-dashboard-addon.html
        └── simple-server.js (already has .ARCHIVED suffix)
```

**Result**: ~12-15 core files (down from ~25+)

---

## Benefits

1. **Clarity**: Clear which pages are production vs legacy
2. **Maintenance**: Easier to update active pages
3. **Onboarding**: New developers see current architecture
4. **History Preserved**: Legacy pages archived, not deleted

---

## Next Steps

1. **User confirms** which HTML pages are actively used
2. **Archive** obsolete pages to `web-ui/archive/legacy-pages/`
3. **Update** `web-ui/README.md` with current architecture
4. **Test** that production pages still work
5. **Commit** cleanup

---

**Status**: Awaiting user clarification on active pages
