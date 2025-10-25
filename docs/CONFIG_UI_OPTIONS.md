# Configuration UI Options for GRAPE Signal Recorder

## Overview

Currently, users must manually edit TOML configuration files, which can be error-prone and intimidating for non-technical users. This document explores options for creating a user-friendly graphical configuration interface.

## Requirements

### Essential Features
- **Read/write TOML files** - Load existing configs, save changes
- **Form validation** - Prevent invalid entries (frequencies, grid squares, etc.)
- **Helpful guidance** - Tooltips, descriptions, examples
- **Dropdown menus** - Pre-populated options for common fields
- **Smart defaults** - Sensible starting values
- **Real-time validation** - Immediate feedback on errors
- **Configuration preview** - Show resulting TOML before saving

### Nice-to-Have Features
- **Auto-discovery** - Detect ka9q-radio receivers on network
- **Grid square lookup** - Convert lat/lon to Maidenhead grid
- **Frequency presets** - WWV/CHU standard frequencies
- **Test connectivity** - Verify ka9q-radio and PSWS connections
- **Import/export** - Share configurations between stations
- **Configuration templates** - Pre-built configs for common setups

## Option 1: Web-Based Interface (Recommended)

### Technology Stack
- **Backend**: Python Flask or FastAPI
- **Frontend**: HTML/CSS/JavaScript with modern framework (React, Vue, or vanilla)
- **Styling**: Bootstrap or Tailwind CSS for professional appearance
- **Validation**: Client-side (JavaScript) + server-side (Python)

### Advantages
- ✓ **Cross-platform** - Works on any device with browser
- ✓ **No installation** - Users just navigate to http://localhost:5000
- ✓ **Modern UI** - Professional, responsive design
- ✓ **Easy updates** - Update UI without reinstalling
- ✓ **Remote access** - Can configure from another computer
- ✓ **Rich interactions** - Dynamic forms, AJAX validation
- ✓ **Familiar** - Everyone knows how to use web forms

### Disadvantages
- ✗ Requires running web server
- ✗ More complex than simple GUI
- ✗ Security considerations for remote access

### Implementation Effort
- **Time**: 2-3 days
- **Complexity**: Medium
- **Dependencies**: Flask/FastAPI, minimal JavaScript

### Example Architecture

```
┌─────────────────────────────────────────┐
│         Web Browser (any device)        │
│  ┌───────────────────────────────────┐  │
│  │   Configuration Form Interface    │  │
│  │  - Station Info                   │  │
│  │  - Receiver Settings              │  │
│  │  - Channel Configuration          │  │
│  │  - PSWS Credentials               │  │
│  └───────────────────────────────────┘  │
└─────────────────┬───────────────────────┘
                  │ HTTP/AJAX
┌─────────────────▼───────────────────────┐
│      Flask/FastAPI Backend Server       │
│  ┌───────────────────────────────────┐  │
│  │   Configuration API Endpoints     │  │
│  │  - GET /config (load current)     │  │
│  │  - POST /config (save changes)    │  │
│  │  - GET /validate (check values)   │  │
│  │  - GET /discover (find receivers) │  │
│  └───────────────────────────────────┘  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│      TOML Configuration Files           │
│  - grape-production.toml                │
│  - station-specific.toml                │
└─────────────────────────────────────────┘
```

## Option 2: Desktop GUI (PyQt/Tkinter)

### Technology Stack
- **Framework**: PyQt5/PyQt6 or Tkinter (built-in)
- **Styling**: Qt Designer for PyQt, ttk themes for Tkinter
- **Validation**: Python-based with immediate feedback

### Advantages
- ✓ **Native look** - Matches OS appearance
- ✓ **No web server** - Standalone application
- ✓ **Offline** - No network required
- ✓ **Rich widgets** - Built-in form controls
- ✓ **File dialogs** - Native file/directory pickers

### Disadvantages
- ✗ Platform-specific packaging
- ✗ Requires GUI libraries installation
- ✗ Less familiar for web-savvy users
- ✗ Harder to access remotely

### Implementation Effort
- **Time**: 3-4 days
- **Complexity**: Medium-High
- ✗ **Dependencies**: PyQt5 or Tkinter (built-in)

## Option 3: Terminal UI (TUI)

### Technology Stack
- **Framework**: Python `curses`, `textual`, or `rich`
- **Forms**: Text-based form library
- **Styling**: ANSI colors and box-drawing characters

### Advantages
- ✓ **SSH-friendly** - Works over SSH connections
- ✓ **Lightweight** - No GUI dependencies
- ✓ **Fast** - Minimal resource usage
- ✓ **Scriptable** - Can be automated

### Disadvantages
- ✗ Less intuitive for non-technical users
- ✗ Limited styling options
- ✗ Terminal compatibility issues
- ✗ Not as visually appealing

### Implementation Effort
- **Time**: 2-3 days
- **Complexity**: Medium
- **Dependencies**: textual or rich library

## Option 4: Configuration Wizard (CLI)

### Technology Stack
- **Framework**: Python with `click` or `argparse`
- **Prompts**: Interactive command-line prompts
- **Validation**: Inline validation with helpful messages

### Advantages
- ✓ **Simple** - Easy to implement
- ✓ **Guided** - Step-by-step process
- ✓ **No dependencies** - Pure Python
- ✓ **Scriptable** - Can be automated with input files

### Disadvantages
- ✗ Linear flow - Can't easily jump between sections
- ✗ No visual preview
- ✗ Limited editing of existing configs
- ✗ Less user-friendly than GUI

### Implementation Effort
- **Time**: 1 day
- **Complexity**: Low
- **Dependencies**: None (or click for enhanced prompts)

## Option 5: Hybrid Approach (Recommended Implementation)

### Combination Strategy
1. **Web UI** (primary) - For full-featured configuration
2. **CLI Wizard** (fallback) - For initial setup or headless systems
3. **Direct TOML editing** (advanced) - For power users

### Benefits
- ✓ Covers all use cases
- ✓ Graceful degradation (web → CLI → manual)
- ✓ Flexibility for different user skill levels
- ✓ Remote and local configuration options

## Detailed Design: Web-Based Configuration UI

### Page Structure

#### 1. **Dashboard/Overview**
- Current configuration status
- Quick links to common tasks
- System health indicators (ka9q-radio connection, PSWS auth status)
- Recent activity log

#### 2. **Station Configuration**
- **Callsign** (text input with validation)
- **Grid Square** (text input with Maidenhead validation, or lat/lon converter)
- **Station ID** (text input, PSWS SITE_ID format)
- **Instrument ID** (dropdown or text input)
- **Description** (text area)

#### 3. **Receiver Configuration**
- **Auto-discover receivers** (button to scan network)
- **Receiver list** (table with add/remove)
  - Name
  - Type (dropdown: RX888, KiwiSDR, etc.)
  - Status address (IP:port)
  - Auto-create channels (checkbox)

#### 4. **Channel Configuration**
- **Preset templates** (dropdown: "WWV All Bands", "CHU All Bands", "Custom")
- **Channel table** (add/remove/edit rows)
  - Enabled (checkbox)
  - Description (text)
  - Frequency (number input with MHz/Hz selector)
  - SSRC (auto-calculated or manual)
  - Sample rate (dropdown: 12000, 48000, etc.)
  - Processor (dropdown: grape, wspr, ft8)

#### 5. **PSWS Configuration**
- **Enable PSWS uploads** (checkbox)
- **Server** (text input with default)
- **Site ID** (text input with S000NNN format validation)
- **Instrument ID** (text input)
- **Test authentication** (button to verify ssh-copy-id setup)
- **Upload schedule** (time picker for daily upload)

#### 6. **Advanced Settings**
- **Data directories** (file picker)
- **Archive directory** (file picker)
- **Recording interval** (number input)
- **Continuous recording** (checkbox)
- **Log level** (dropdown: DEBUG, INFO, WARNING, ERROR)

#### 7. **Preview & Save**
- **TOML preview** (syntax-highlighted text area)
- **Validation results** (error/warning list)
- **Save** (button to write config file)
- **Test configuration** (button to dry-run)

### UI Mockup (Text-Based)

```
╔══════════════════════════════════════════════════════════════════════╗
║  GRAPE Signal Recorder - Configuration                              ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  [Dashboard] [Station] [Receivers] [Channels] [PSWS] [Advanced]     ║
║                                                                      ║
║  ┌─ Station Configuration ────────────────────────────────────────┐ ║
║  │                                                                 │ ║
║  │  Callsign: [AC0G        ] ⓘ Your amateur radio callsign       │ ║
║  │                                                                 │ ║
║  │  Grid Square: [EM38ww     ] ⓘ Maidenhead grid locator         │ ║
║  │               [Convert from Lat/Lon...]                        │ ║
║  │                                                                 │ ║
║  │  Station ID: [S000987    ] ⓘ PSWS SITE_ID (format: S000NNN)   │ ║
║  │                                                                 │ ║
║  │  Instrument: [RX888 ▼    ] ⓘ Receiver type                    │ ║
║  │                                                                 │ ║
║  │  Instrument ID: [0        ] ⓘ PSWS INSTRUMENT_ID              │ ║
║  │                                                                 │ ║
║  │  Description: ┌─────────────────────────────────────────────┐ │ ║
║  │               │ GRAPE station with RX888 MkII and          │ │ ║
║  │               │ ka9q-radio for ionospheric research        │ │ ║
║  │               └─────────────────────────────────────────────┘ │ ║
║  │                                                                 │ ║
║  └─────────────────────────────────────────────────────────────────┘ ║
║                                                                      ║
║  [Previous]                                    [Next: Receivers >]  ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Form Validation Examples

#### Grid Square Validation
```javascript
function validateGridSquare(grid) {
    const pattern = /^[A-R]{2}[0-9]{2}[a-x]{2}$/i;
    if (!pattern.test(grid)) {
        return {
            valid: false,
            message: "Invalid grid square format. Expected: AA00aa (e.g., EM38ww)"
        };
    }
    return { valid: true };
}
```

#### Frequency Validation
```javascript
function validateFrequency(freq, unit) {
    const freqHz = unit === 'MHz' ? freq * 1e6 : freq;
    
    if (freqHz < 0 || freqHz > 30e6) {
        return {
            valid: false,
            message: "Frequency must be between 0 and 30 MHz for HF"
        };
    }
    
    // Check if it's a standard WWV/CHU frequency
    const standardFreqs = [2.5e6, 5e6, 10e6, 15e6, 20e6, 25e6, // WWV
                          3.33e6, 7.85e6, 14.67e6];            // CHU
    
    if (standardFreqs.includes(freqHz)) {
        return {
            valid: true,
            message: "✓ Standard WWV/CHU frequency"
        };
    }
    
    return { valid: true };
}
```

#### SITE_ID Validation
```javascript
function validateSiteID(siteId) {
    const pattern = /^S\d{6}$/;
    if (!pattern.test(siteId)) {
        return {
            valid: false,
            message: "Invalid SITE_ID format. Expected: S000NNN (e.g., S000987)"
        };
    }
    return { valid: true };
}
```

### Preset Templates

#### WWV All Bands Template
```javascript
const WWV_TEMPLATE = {
    channels: [
        { freq: 2.5e6, desc: "WWV 2.5 MHz", enabled: true },
        { freq: 5e6, desc: "WWV 5 MHz", enabled: true },
        { freq: 10e6, desc: "WWV 10 MHz", enabled: true },
        { freq: 15e6, desc: "WWV 15 MHz", enabled: true },
        { freq: 20e6, desc: "WWV 20 MHz", enabled: true },
        { freq: 25e6, desc: "WWV 25 MHz", enabled: false }
    ],
    sample_rate: 12000,
    processor: "grape"
};
```

#### CHU All Bands Template
```javascript
const CHU_TEMPLATE = {
    channels: [
        { freq: 3.33e6, desc: "CHU 3.33 MHz", enabled: true },
        { freq: 7.85e6, desc: "CHU 7.85 MHz", enabled: true },
        { freq: 14.67e6, desc: "CHU 14.67 MHz", enabled: true }
    ],
    sample_rate: 12000,
    processor: "grape"
};
```

## Implementation Plan

### Phase 1: Basic Web UI (Week 1)
- [ ] Flask/FastAPI backend with TOML read/write
- [ ] Simple HTML forms for all configuration sections
- [ ] Basic validation (client + server side)
- [ ] Save/load functionality

### Phase 2: Enhanced Features (Week 2)
- [ ] Auto-discovery of ka9q-radio receivers
- [ ] Preset templates for WWV/CHU
- [ ] Grid square converter (lat/lon ↔ Maidenhead)
- [ ] TOML preview with syntax highlighting
- [ ] Real-time validation feedback

### Phase 3: Advanced Features (Week 3)
- [ ] Test connectivity buttons (ka9q-radio, PSWS)
- [ ] Configuration import/export
- [ ] Multi-configuration management
- [ ] Backup/restore functionality
- [ ] Activity logging and status dashboard

### Phase 4: Polish & Documentation (Week 4)
- [ ] Responsive design for mobile/tablet
- [ ] Comprehensive help tooltips
- [ ] User guide and screenshots
- [ ] Video tutorial
- [ ] Deployment guide (systemd service)

## Technology Recommendations

### Backend: FastAPI
**Why FastAPI over Flask:**
- Automatic API documentation (Swagger UI)
- Built-in validation with Pydantic
- Modern async support
- Type hints for better code quality
- WebSocket support for real-time updates

### Frontend: Vanilla JavaScript + Alpine.js
**Why Alpine.js:**
- Lightweight (~15KB)
- Vue-like syntax but simpler
- No build step required
- Perfect for progressive enhancement
- Easy to learn

### Styling: Tailwind CSS
**Why Tailwind:**
- Utility-first approach
- Rapid development
- Consistent design system
- Small production bundle
- Excellent documentation

### Alternative: Bootstrap
**Why Bootstrap:**
- More traditional approach
- Pre-built components
- Familiar to many developers
- Extensive ecosystem
- Good accessibility

## Security Considerations

### Authentication
- **Local only**: Bind to 127.0.0.1 by default
- **Optional auth**: Add simple password protection for remote access
- **HTTPS**: Use self-signed cert for remote access

### File Access
- **Restricted paths**: Only allow access to config directory
- **Validation**: Sanitize all file paths
- **Permissions**: Check file permissions before write

### Input Validation
- **Server-side**: Never trust client validation alone
- **Sanitization**: Escape special characters in TOML
- **Type checking**: Use Pydantic models for validation

## User Experience Enhancements

### Contextual Help
- **Tooltips**: Hover over ⓘ icon for field descriptions
- **Examples**: Show example values in placeholders
- **Links**: Direct links to documentation for complex topics

### Error Handling
- **Inline errors**: Show errors next to relevant fields
- **Summary**: Error summary at top of form
- **Suggestions**: Offer corrections for common mistakes

### Progress Indication
- **Save feedback**: Show success/error messages
- **Loading states**: Indicate when operations are in progress
- **Auto-save**: Optional auto-save draft changes

### Accessibility
- **Keyboard navigation**: Full keyboard support
- **Screen readers**: Proper ARIA labels
- **Color contrast**: WCAG AA compliance
- **Focus indicators**: Clear focus states

## Comparison Matrix

| Feature | Web UI | Desktop GUI | TUI | CLI Wizard |
|---------|--------|-------------|-----|------------|
| **Ease of Use** | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★☆☆☆ |
| **Remote Access** | ★★★★★ | ★☆☆☆☆ | ★★★★★ | ★★★★★ |
| **Visual Appeal** | ★★★★★ | ★★★★☆ | ★★☆☆☆ | ★☆☆☆☆ |
| **Implementation** | ★★★☆☆ | ★★☆☆☆ | ★★★☆☆ | ★★★★★ |
| **Dependencies** | ★★★☆☆ | ★★☆☆☆ | ★★★★☆ | ★★★★★ |
| **Cross-Platform** | ★★★★★ | ★★★☆☆ | ★★★★☆ | ★★★★★ |
| **Maintenance** | ★★★★☆ | ★★★☆☆ | ★★★★☆ | ★★★★★ |

## Recommendation

**Primary**: **Web-based UI with FastAPI + Alpine.js + Tailwind CSS**

**Rationale**:
1. Best user experience for non-technical users
2. Works on any device (desktop, tablet, phone)
3. Easy to access remotely (common for headless servers)
4. Modern, professional appearance
5. Easy to update and maintain
6. No platform-specific packaging needed
7. Can be accessed via SSH tunnel for security

**Fallback**: **CLI Wizard** for initial setup or when web UI unavailable

This hybrid approach provides the best of both worlds: a powerful, user-friendly web interface for regular use, with a simple CLI wizard as a fallback for edge cases.

