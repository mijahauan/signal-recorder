# GRAPE Signal Recorder - System Architecture

**Last Updated:** November 28, 2025  
**Status:** CANONICAL - Single source of truth for system design  
**Version:** V2 (Three-Service Architecture)

---

## 📖 Document Purpose

This document explains **WHY** the GRAPE system is designed the way it is. For **WHERE** data goes, see `DIRECTORY_STRUCTURE.md`. For **WHAT** functions exist, see `docs/API_REFERENCE.md`.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Design Philosophy](#design-philosophy)
3. [Three-Service Architecture](#three-service-architecture)
4. [Key Design Decisions](#key-design-decisions)
5. [Data Flow](#data-flow)
6. [Timing Architecture](#timing-architecture)
7. [WWV/WWVH Discrimination](#wwvwwvh-discrimination)
8. [Directory Structure](#directory-structure)
9. [Service Management](#service-management)
10. [Performance & Reliability](#performance--reliability)
11. [Failure Recovery](#failure-recovery)

---

## Executive Summary

The GRAPE Signal Recorder is a specialized system for recording, processing, and analyzing WWV/CHU time-standard radio signals for ionospheric propagation studies. It uses a **three-service architecture** where data flows through specialized processing stages, with **10 Hz decimated NPZ files** serving as the central pivot point for multiple downstream consumers.

### What Makes GRAPE Different?

**Not a General SDR Recorder:**
- Purpose-built for GRAPE (Global Radio Amateur Propagation Experiment)
- Specialized for WWV/CHU time signals (not WSPR, FT8, etc.)
- Focus on timing precision (±1ms) and continuous data capture

**Not wsprdaemon:**
- No external tools (sox, pcmrecord) - native Python processing
- Continuous data flow (not 2-minute WSPR cycles)
- IQ data preservation (full complex samples, not audio)
- Sub-10 Hz decimation for Doppler analysis

**Core Mission:**
Record WWV/WWVH/CHU time signals to study ionospheric disturbances through:
1. **Timing variations** (±1ms precision via tone detection)
2. **WWV/WWVH discrimination** on the 4 shared frequencies (2.5, 5, 10, 15 MHz)
3. **Propagation delays** (differential delay between WWV Fort Collins and WWVH Kauai)
4. **Carrier Doppler shifts** (±5 Hz window for ionospheric dynamics)

**Channel Configuration (9 frequencies):**
- **Shared frequencies (4):** 2.5, 5, 10, 15 MHz - WWV and WWVH both transmit, requiring discrimination
- **WWV-only (2):** 20, 25 MHz - WWV exclusive
- **CHU (3):** 3.33, 7.85, 14.67 MHz - Canadian time standard

---

## Design Philosophy

### 1. Separation of Concerns

```
Core Recorder (Stable)  →  Analytics (Evolving)  →  Consumers (Flexible)
    Archives                 Processes                Multiple outputs
  Changes <5/year         Can restart freely        Format conversions
```

**Why?**
- **Scientific Integrity:** Core recorder never drops data during analytics updates
- **Reprocessability:** Improve algorithms without re-recording
- **Independent Testing:** Test analytics on archived data
- **Flexible Deployment:** Run services on same or different machines

### 2. RTP Timestamp as Primary Reference

**Decision:** Wall clock time is **DERIVED** from RTP timestamps, not vice versa.

**Why?**
- **Sample Count Integrity:** Gaps are unambiguous (RTP timestamp jumps)
- **Precise Reconstruction:** `utc = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate`
- **No Time Stretching:** Never adjust sample count to fit wall clock
- **KA9Q Compatibility:** Follows Phil Karn's timing architecture

### 3. NPZ Archives Enable Reprocessability

**Decision:** Archive raw 16 kHz IQ in NPZ format before any analytics.

**Why?**
- **Algorithm Evolution:** Improve tone detection without re-recording
- **Validation:** Replay specific minutes for debugging
- **Multiple Analyses:** Run discrimination, Doppler, quality metrics independently
- **Scientific Record:** Complete data with RTP timestamps preserved

### 4. 10 Hz Decimated NPZ as Pivot

**Decision:** Decimate once to 10 Hz, store in NPZ, consume by multiple services.

**Why?**
- **Efficient Size:** 1600x smaller than 16 kHz (60 samples/min vs 960,000)
- **Scientific Goal:** ±5 Hz Doppler window requires 10 Hz sampling
- **Single Decimation:** Avoid repeated processing
- **Embedded Metadata:** Timing quality travels with IQ data
- **Python Native:** No external library dependencies

### 5. Independent Discrimination Methods

**Decision:** Eight voting methods + nine cross-validation checks for WWV/WWVH discrimination on shared frequencies, each with dedicated CSV output.

**Why?**
- **Independent Reprocessing:** Update one method without rerunning others
- **Testability:** Validate each method independently
- **Provenance:** Clear data lineage for each result
- **Weighted Voting:** Combine methods with confidence levels
- **Scientific Rigor:** Document how each conclusion was reached
- **Mutual Reinforcement:** Cross-validation checks validate voting results

**Voting Methods (8):**
1. Test Signal Detection (minutes :08, :44) - weight=15
2. 440 Hz Station ID (minutes 1, 2) - weight=10
3. BCD Amplitude Ratio (100 Hz subcarrier) - weight=2-10
4. 1000/1200 Hz Timing Tone Power Ratio - weight=1-10
5. Tick SNR Average (59-tick coherent integration) - weight=5
6. 500/600 Hz Ground Truth (12 exclusive min/hour) - weight=10-15
7. Doppler Stability (std ratio, independent of power) - weight=2
8. Timing Coherence (Test + BCD ToA agreement) - weight=3

**Cross-Validation Checks (9):**
1. Power vs Timing agreement
2. Per-tick voting consistency
3. Geographic delay validation
4. 440 Hz ground truth validation
5. BCD correlation quality
6. 500/600 Hz ground truth validation
7. Doppler-Power agreement (Δf_D vs power ratio)
8. Coherence quality confidence adjustment
9. Harmonic signature validation (500→1000, 600→1200 Hz)

---

## Three-Service Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CORE RECORDER SERVICE                        │
│                   (Rock-Solid Archiving)                        │
│                                                                 │
│  Input:  ka9q-radio RTP multicast (16 kHz IQ)                 │
│  Process: Resequencing + Gap Detection + Gap Fill              │
│  Output:  {timestamp}_iq.npz (16 kHz, complete scientific      │
│           record with RTP timestamps)                           │
│  Location: archives/{channel}/                                  │
│                                                                 │
│  Responsibilities:                                              │
│  ✅ Complete data capture (no analytics)                        │
│  ✅ Sample count integrity                                      │
│  ✅ RTP timestamp preservation                                  │
│  ✅ Gap filling with zeros (maintains timing)                   │
│                                                                 │
│  Changes: <5 times per year                                    │
│  Dependencies: Minimal (numpy only)                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   ANALYTICS SERVICE (Per Channel)               │
│         (Tone Detection + Quality + Discrimination + Decimate)  │
│                                                                 │
│  Input:  16 kHz NPZ files from Core Recorder                   │
│  Process:                                                       │
│    1. Tone Detection (WWV/WWVH/CHU @ 1000/1200 Hz)            │
│    2. Time_snap Management (GPS-quality timestamp anchors)     │
│    3. Quality Metrics (completeness, packet loss, gaps)        │
│    4. WWV-H Discrimination (5 independent methods):            │
│       • Timing tones (1000/1200 Hz power, delay)               │
│       • Tick windows (5ms tick coherent/incoherent SNR)        │
│       • Station ID (440 Hz tones minute 1=WWVH, 2=WWV)         │
│       • BCD discrimination (100 Hz subcarrier analysis)        │
│       • Weighted voting (final determination)                   │
│    5. Decimation (16 kHz → 10 Hz with embedded metadata)      │
│                                                                 │
│  Outputs:                                                       │
│  • 10 Hz NPZ: analytics/{channel}/decimated/*_iq_10hz.npz     │
│  • Tones CSV: analytics/{channel}/tone_detections/*.csv       │
│  • Ticks CSV: analytics/{channel}/tick_windows/*.csv          │
│  • 440Hz CSV: analytics/{channel}/station_id_440hz/*.csv      │
│  • BCD CSV: analytics/{channel}/bcd_discrimination/*.csv      │
│  • Final CSV: analytics/{channel}/discrimination/*.csv        │
│  • Quality CSV: analytics/{channel}/quality/*.csv             │
│  • State: state/analytics-{channel}.json (time_snap)          │
│                                                                 │
│  Responsibilities:                                              │
│  ✅ All derived products                                        │
│  ✅ Can restart/update independently                            │
│  ✅ Processes backlog automatically                             │
│  ✅ Aggressive retry (systemd restarts safe)                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
              ┌───────────────┴──────────────┐
              ↓                              ↓
┌──────────────────────────┐  ┌────────────────────────────────┐
│   DRF WRITER SERVICE     │  │   SPECTROGRAM GENERATOR        │
│   (Format Conversion)    │  │   (Carrier Visualization)      │
│                          │  │                                │
│ Input:  10Hz NPZ files   │  │ Input:  10Hz NPZ files         │
│ Process: Format          │  │ Process: FFT spectrogram       │
│          conversion only │  │          (Doppler analysis)    │
│ Output:  Digital RF HDF5 │  │ Output:  PNG files             │
│ Location: analytics/     │  │ Location: spectrograms/        │
│           {channel}/     │  │           {YYYYMMDD}/          │
│           digital_rf/    │  │                                │
│                          │  │ Shows: ±5 Hz carrier variation │
│ Next: rsync to PSWS      │  │        (ionospheric Doppler)   │
│                          │  │                                │
│ Responsibilities:        │  │ Responsibilities:              │
│ ✅ Format conversion      │  │ ✅ Daily PNG generation        │
│ ✅ Independent operation  │  │ ✅ On-demand processing        │
│ ✅ Reprocessable          │  │ ✅ Web UI visualization        │
└──────────────────────────┘  └────────────────────────────────┘
```

---

## Key Design Decisions

### Decision 1: Why 10 Hz Decimation?

**Requirements:**
- Detect ionospheric Doppler shifts (±5 Hz window)
- 0.1 Hz frequency resolution needed
- Nyquist: 10 Hz minimum sampling rate

**Benefits:**
- **Size:** 1600x smaller than 16 kHz
  - 16 kHz: 960,000 samples/min = ~1.8 MB NPZ
  - 10 Hz: 600 samples/min = ~1.2 KB NPZ
- **Speed:** FFT processing 1600x faster
- **Storage:** Enables long-term Doppler analysis
- **HamSCI:** Matches PSWS Digital RF format

### Decision 2: Why NPZ (not immediate Digital RF)?

**NPZ Advantages:**
- **Single Decimation:** Performed once, consumed multiple times
- **Embedded Metadata:** Timing/quality/tone data travels with IQ
- **Reprocessable:** Regenerate Digital RF with updated metadata
- **Python Native:** `np.load()` - no external dependencies
- **Fast:** Compressed, optimized for NumPy arrays

**Digital RF Disadvantages:**
- **Heavy Dependency:** Requires gr-drf library
- **Write Once:** Changing metadata requires full rewrite
- **Not Universal:** Specialized HamSCI format
- **Overkill:** Time-indexing not needed for minute-boundary files

### Decision 3: Why Separate Services?

**Core Recorder Isolation:**
- ✅ **Stability:** Minimal code changes (rock-solid)
- ✅ **No Data Loss:** Analytics can crash, core keeps recording
- ✅ **Simple:** ~300 lines, minimal dependencies
- ✅ **Scientific Integrity:** Complete record always preserved

**Analytics Independence:**
- ✅ **Evolution:** Update algorithms without downtime
- ✅ **Testing:** Replay archived data for validation
- ✅ **Reprocessing:** Improve historical analysis
- ✅ **Restart Safe:** Processes backlog automatically

**Consumer Flexibility:**
- ✅ **Multiple Outputs:** DRF, spectrograms, CSVs from same 10Hz NPZ
- ✅ **Distributed:** Can run on different machines
- ✅ **On-Demand:** Generate spectrograms as needed

### Decision 4: Why 5 Independent Discrimination Methods?

**Problem:** Single method can fail due to propagation conditions.

**Solution:** Multiple independent analyses with weighted voting.

**Benefits:**
1. **Robustness:** If one method fails, others still work
2. **Confidence:** Multiple confirmations increase reliability
3. **Provenance:** Clear data lineage for each result
4. **Scientific Rigor:** Document how conclusions reached
5. **Reprocessability:** Update one method without rerunning all

**Example Failure Scenarios:**
- **Weak Signal:** Timing tones may not detect, but BCD still works
- **Propagation Fade:** 440 Hz may be absent, but ticks still present
- **Interference:** One frequency polluted, others clean

### Decision 5: Why Canonical Contracts? (Nov 2025)

**Problem:** Inconsistent paths, APIs, and naming caused debugging loops.

**Solution:** Three canonical contracts established 2025-11-20:
1. `CANONICAL_CONTRACTS.md` - Overview and quick reference
2. `DIRECTORY_STRUCTURE.md` - WHERE data goes, HOW to name files
3. `docs/API_REFERENCE.md` - WHAT functions exist, HOW to call them

**Benefits:**
- ✅ **Single Source of Truth:** No conflicting documentation
- ✅ **Automated Enforcement:** `validate_api_compliance.py`
- ✅ **Clear Guidelines:** New developers know what to do
- ✅ **Reduced Debugging:** Path mismatches caught early

**Key Rules:**
- ALL paths via `GRAPEPaths` API
- ALL functions documented in API_REFERENCE.md
- NO time-range suffixes on daily files
- Consistent naming: `{CHANNEL}_{METHOD}_YYYYMMDD.csv`

---

## Data Flow

### Flow 1: Real-Time Recording

```
ka9q-radio RTP
     ↓
Core Recorder
     ↓ (16 kHz NPZ)
archives/{channel}/{timestamp}_iq.npz
     ↓
Analytics Service (polls every 10s)
     ↓ (processes)
├─→ tone_detections/{channel}_tones_{date}.csv
├─→ tick_windows/{channel}_ticks_{date}.csv
├─→ station_id_440hz/{channel}_440hz_{date}.csv
├─→ bcd_discrimination/{channel}_bcd_{date}.csv
├─→ discrimination/{channel}_discrimination_{date}.csv
└─→ decimated/{timestamp}_iq_10hz.npz (with metadata)
     ↓
├─→ DRF Writer → digital_rf/rf@*.h5 → rsync to PSWS
└─→ Spectrogram Generator → spectrograms/{date}/*.png
```

### Flow 2: Batch Reprocessing

```
archives/{channel}/*.npz (existing)
     ↓
Reprocessing Script (e.g., reprocess_discrimination_separated.py)
     ↓ (re-analyzes with improved algorithms)
├─→ tone_detections/{channel}_tones_{date}.csv (overwrite)
├─→ tick_windows/{channel}_ticks_{date}.csv (overwrite)
├─→ station_id_440hz/{channel}_440hz_{date}.csv (overwrite)
├─→ bcd_discrimination/{channel}_bcd_{date}.csv (overwrite)
└─→ discrimination/{channel}_discrimination_{date}.csv (overwrite)
```

**Note:** 10 Hz NPZ regeneration optional - only if decimation algorithm changes.

### Flow 3: Web UI Visualization

```
Web Browser
     ↓
Node.js Monitoring Server
     ↓ (reads CSVs + spectrograms)
├─→ discrimination/{channel}_discrimination_{date}.csv
├─→ quality/{channel}_quality_{date}.csv
├─→ spectrograms/{date}/*.png
└─→ state/analytics-{channel}.json
     ↓
JSON Response → Chart.js plots
```

---

## Timing Architecture

### Time Reference Hierarchy

**KA9Q Principle:** RTP timestamp is PRIMARY, wall clock is DERIVED.

```
┌──────────────────────────────────────────────────────────────┐
│ 1. RTP TIMESTAMP (Primary Reference)                        │
│    • From ka9q-radio packets                                │
│    • 16 kHz sample rate                                     │
│    • Gaps = dropped packets (fill with zeros)               │
│    • Sample count integrity paramount                        │
└──────────────────────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. TIME_SNAP (GPS-Quality Anchor)                           │
│    • WWV/CHU tone rising edge at :00.000                    │
│    • Maps RTP to UTC: utc = time_snap_utc +                 │
│      (rtp_ts - time_snap_rtp) / sample_rate                 │
│    • Precision: ±1ms                                        │
│    • Stored in state/analytics-{channel}.json               │
└──────────────────────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. TIMING QUALITY (Data Annotation)                         │
│    • TONE_LOCKED (±1ms): Recent time_snap (<5 min)         │
│    • NTP_SYNCED (±10ms): System NTP synchronized           │
│    • INTERPOLATED: Aged time_snap (5-60 min)               │
│    • WALL_CLOCK (±seconds): Fallback (mark for reprocess)  │
└──────────────────────────────────────────────────────────────┘
```

### Why This Matters

**Scientific Requirement:** ±1ms timestamp precision for propagation studies.

**RTP Timestamp Approach:**
- ✅ Unambiguous gap detection
- ✅ Precise reconstruction
- ✅ No time stretching
- ✅ Sample count integrity

**Alternative Approaches (Rejected):**
- ❌ System clock only: ±seconds, NTP jitter
- ❌ RTP correlation: Proven unstable (1.2B sample std dev)
- ❌ Interpolation only: Drift accumulates

---

## WWV/WWVH Discrimination

### The Discrimination Challenge

**Problem:** On 4 shared frequencies (2.5, 5, 10, 15 MHz), WWV (Fort Collins, CO) and WWVH (Kauai, HI) transmit simultaneously. Their signals mix in the ionosphere, arriving at different times and strengths depending on propagation conditions. Separating these signals is essential for ionospheric research.

**Solution:** Multiple independent analysis methods, each exploiting different signal characteristics, combined via weighted voting.

### Discrimination Methods

#### Method 1: BCD Correlation (🚀 PRIMARY)

**What:** Cross-correlate 100 Hz BCD time code to find two peaks representing the two stations.

**When:** 3-second sliding windows throughout each minute (15+ measurements/minute).

**Outputs:**
- WWV/WWVH amplitudes from dual-peak detection
- Differential delay (ms) - propagation path difference
- Geographic peak assignment using receiver location
- Correlation quality (0-1)

**Why Primary:** Highest temporal resolution, measures both amplitude AND timing simultaneously.

#### Method 2: Timing Tones (1000/1200 Hz)

**What:** Power ratio of WWV's 1000 Hz vs WWVH's 1200 Hz marker tones.

**When:** First 0.8 seconds of each minute.

**Outputs:**
- 1000 Hz power (dB) - WWV indicator
- 1200 Hz power (dB) - WWVH indicator
- Power ratio (dB)

**Use:** Reliable baseline, works even with weak signals.

#### Method 3: Tick Windows (5ms coherent analysis)

**What:** Analyze 5ms tick marks using adaptive coherent/incoherent integration.

**When:** 6 windows per minute (at seconds 0, 10, 20, 30, 40, 50).

**Outputs:**
- Coherent/incoherent SNR for WWV/WWVH
- Phase coherence quality (0-1)
- Integration method selected (coherent when phase stable)

**Use:** Sub-minute dynamics, tracks rapid propagation changes.

#### Method 4: 440/500/600 Hz Tone Detection

**What:** Detect station-identifying tones from the WWV/WWVH broadcast schedule.

**440 Hz Station ID:**
- Minute 1: WWVH broadcasts 440 Hz (WWV broadcasts 600 Hz)
- Minute 2: WWV broadcasts 440 Hz (WWVH broadcasts 600 Hz)

**500/600 Hz Ground Truth (14 minutes/hour):**
- WWV-only: Minutes 1, 16, 17, 19 (WWVH silent or different tone)
- WWVH-only: Minutes 2, 43-51 (WWV silent or different tone)

**Outputs:**
- Station detected (WWV/WWVH)
- Tone frequency and power (dB)
- Harmonic analysis: 500→1000 Hz (WWV), 600→1200 Hz (WWVH)

**Use:** Ground truth calibration - 100% certain identification when present.

#### Method 5: Test Signal Detection

**What:** Detect WWV/WWVH test signals at minutes :08 and :44.

**When:** Minutes 8 and 44 of each hour.

**Outputs:**
- Detection confidence
- Time-of-arrival offset (ms) - ionospheric channel characterization
- Station identified from schedule

**Use:** High-precision ToA measurement for path delay analysis.

#### Method 6: Weighted Voting (Final Determination)

**What:** Combine all 8 voting methods with minute-specific weighting.

**Voting Weights:**
| Vote | Method | Max Weight | When Applied |
|------|--------|------------|---------------|
| 0 | Test Signal | 15 | Minutes :08, :44 only |
| 1 | 440 Hz Station ID | 10 | Minutes 1, 2 only |
| 2 | BCD Amplitude Ratio | 10 | Higher in BCD-dominant minutes |
| 3 | 1000/1200 Hz Power | 10 | Reduced when ground truth available |
| 4 | Tick SNR Average | 5 | All minutes |
| 5 | 500/600 Hz Ground Truth | **15** | M16-19, M43-51 (exclusive); 10 for M1-2 |
| 6 | Doppler Stability | 2 | When quality > 0.3, std ratio > 3 dB |
| 7 | Timing Coherence | 3 | Minutes :08, :44 with test + BCD |

**Cross-Validation (Phase 6):**
After voting, 9 inter-method checks adjust confidence:
- **Agreements** boost confidence (≥2 with 0 disagreements → HIGH)
- **Disagreements** reduce confidence (≥2 → MEDIUM)
- Low coherence (<0.3) forces LOW confidence
- High coherence (>0.85) contributes to agreement count

**Outputs:**
- Dominant station (WWV/WWVH/BALANCED/UNKNOWN)
- Confidence level (high/medium/low)
- All individual method results
- Inter-method agreements/disagreements list

**Use:** Final determination for visualization and scientific analysis.

### Additional Analytics

- **Doppler Estimation:** Per-tick frequency shift measurement for ionospheric dynamics
- **Timing Metrics:** Time_snap quality, NTP drift, timing accuracy tracking

### CSV Output Structure

**Separated by Method:**
```
analytics/{channel}/
├── tone_detections/          # 1000/1200 Hz timing tones
├── tick_windows/             # 5ms tick coherent analysis
├── station_id_440hz/         # 440 Hz station ID (minutes 1,2)
├── bcd_discrimination/       # 100 Hz BCD dual-peak (PRIMARY)
├── test_signals/             # Minutes :08/:44 detection
├── doppler/                  # Per-tick Doppler estimates
├── timing_metrics/           # Time_snap quality tracking
└── discrimination/           # Final weighted voting results
```

**Benefits:**
- Independent reprocessing per method
- Clear data provenance
- Testable in isolation
- Web UI can visualize each method separately

---

## Directory Structure

See `DIRECTORY_STRUCTURE.md` for complete specification.

**Key Principles:**
- ✅ Use `GRAPEPaths` API for all path operations
- ✅ Consistent naming: `{CHANNEL}_{METHOD}_YYYYMMDD.csv`
- ✅ NO time-range suffixes on daily files
- ✅ Mode-aware (test vs production)

**Summary:**
```
{data_root}/
├── archives/{channel}/          # Core Recorder (16 kHz NPZ)
├── analytics/{channel}/
│   ├── decimated/               # 10 Hz NPZ (pivot point)
│   ├── digital_rf/              # DRF Writer output
│   ├── tone_detections/         # Method 1 CSVs
│   ├── tick_windows/            # Method 2 CSVs
│   ├── station_id_440hz/        # Method 3 CSVs
│   ├── bcd_discrimination/      # Method 4 CSVs
│   ├── discrimination/          # Method 5 CSVs (final)
│   └── quality/                 # Quality metrics CSVs
├── spectrograms/{YYYYMMDD}/     # Daily PNG files
└── state/                       # Service state files
```

---

## Service Management

### Start Order

**Required (Immediate):**
1. Core Recorder - Archive data immediately
2. Analytics Service (per channel) - Process archives with 10s polling

**Optional (Can start later):**
3. DRF Writer Service - Convert 10Hz NPZ to Digital RF
4. Spectrogram Generator - Create daily PNG files
5. Web UI Monitoring Server - Dashboard access

**Note:** All services are independent. Analytics processes backlog if started late.

### Service Dependencies

```
Core Recorder
  Requires: ka9q-radio RTP stream
  Provides: 16 kHz NPZ archives
  
Analytics Service
  Requires: 16 kHz NPZ archives
  Provides: 10 Hz NPZ + CSVs
  
DRF Writer
  Requires: 10 Hz NPZ
  Provides: Digital RF HDF5
  
Spectrogram Generator
  Requires: 10 Hz NPZ
  Provides: PNG files
  
Web UI
  Requires: CSVs + PNGs + state files
  Provides: Dashboard
```

### Systemd Integration

**Core Recorder:**
- `signal-recorder@{channel}.service`
- Restart: Always
- Stop: Graceful (finish current minute)

**Analytics Service:**
- `analytics-service@{channel}.service`
- Restart: On-failure
- Stop: Graceful (finish current file)

**DRF Writer:**
- `drf-writer@{channel}.service`
- Restart: On-failure
- Type: Simple

---

## Performance & Reliability

### Performance Characteristics

| Service | Input Rate | CPU Usage | Memory | Bottleneck |
|---------|-----------|-----------|--------|------------|
| Core Recorder | 960k samples/min | ~5% | ~50 MB | Network I/O |
| Analytics | 1 file/min | ~10% per channel | ~100 MB | Decimation (scipy) |
| DRF Writer | 1 file/min | ~2% | ~30 MB | Disk I/O |
| Spectrogram | On-demand | ~20% (burst) | ~200 MB | FFT computation |

### Disk Usage

**Per Channel (24 hours):**
- Archives (16 kHz): ~2.6 GB/day (compressed NPZ)
- Decimated (10 Hz): ~1.7 MB/day (compressed NPZ)
- CSVs: ~5 MB/day (all methods combined)
- Spectrograms: ~10 MB/day (PNG)

**Total (9 channels):** ~24 GB/day

### Reliability Design

**Core Recorder:**
- ✅ Minimal dependencies (numpy only)
- ✅ Conservative error handling
- ✅ Changes <5 times per year
- ✅ Systemd restart on failure

**Analytics Service:**
- ✅ Aggressive retry logic
- ✅ Processes backlog on restart
- ✅ Can reprocess historical data
- ✅ Independent per channel

**Data Integrity:**
- ✅ RTP timestamps preserved
- ✅ Gaps filled with zeros
- ✅ Quality metrics recorded
- ✅ Complete provenance

---

## Failure Recovery

### Core Recorder Crash

**Impact:** Missing minutes in 16 kHz archives.

**Detection:**
- Gap in archive file timestamps
- Analytics service reports missing files

**Recovery:**
1. Systemd restarts service automatically
2. Gap minutes lost (can't recreate RTP stream)
3. Quality metrics document gaps
4. Analytics continues with available data

**Prevention:**
- Minimal code complexity
- Conservative error handling
- Regular testing

### Analytics Service Crash

**Impact:** Backlog of unprocessed 16 kHz files.

**Detection:**
- `analytics_state.json` not updating
- Web UI shows stale data

**Recovery:**
1. Systemd restarts service
2. Service detects backlog automatically
3. Processes all unprocessed files
4. Catches up to real-time

**Prevention:**
- Aggressive exception handling
- State file tracking
- Backlog processing logic

### DRF Writer Crash

**Impact:** Missing Digital RF files.

**Detection:**
- No new HDF5 files in digital_rf/
- PSWS upload gaps

**Recovery:**
1. Restart service
2. Reprocesses unprocessed 10Hz NPZ files
3. Generates missing HDF5 files
4. Resumes upload to PSWS

**Prevention:**
- Simple format conversion only
- No complex logic
- Retry on transient errors

### Disk Full

**Impact:** All services stop writing.

**Detection:**
- Monitoring dashboard alert
- Services log disk full errors

**Recovery:**
1. Free disk space (delete old archives or add storage)
2. Services resume automatically
3. Process backlog if any

**Prevention:**
- Monitor disk usage
- Automated cleanup of old data
- Alerts at 80% capacity

### Network Outage (ka9q-radio)

**Impact:** No new RTP packets received.

**Detection:**
- Core recorder logs no data
- Web UI shows no recent archives

**Recovery:**
1. Wait for network restoration
2. Core recorder resumes automatically
3. Gap minutes are lost (no RTP buffering)

**Prevention:**
- Monitor network connectivity
- Alert on stream loss
- Multiple frequency backups

---

## Related Documentation

### Canonical Contracts (Established Nov 2025)
- **`CANONICAL_CONTRACTS.md`** - Overview of project standards
- **`DIRECTORY_STRUCTURE.md`** - Complete path specifications
- **`docs/API_REFERENCE.md`** - Unified API reference

### Core Documentation
- **`CONTEXT.md`** - Project context and quick reference
- **`README.md`** - Installation and quick start
- **`DEPENDENCIES.md`** - External dependencies

### Design Documents
- **`CORE_ANALYTICS_SPLIT_DESIGN.md`** - Original architecture decision
- **`TIMING_ARCHITECTURE_V2.md`** - KA9Q timing approach
- **`MULTI_STATION_TONE_DETECTION.md`** - Tone detector design

### Implementation Details
- **`WWV_WWVH_DISCRIMINATION_METHODS.md`** - Discrimination algorithms
- **`BCD_DISCRIMINATION_IMPLEMENTATION.md`** - BCD analysis details
- **`COHERENT_TICK_REPROCESSING_STATUS.md`** - Tick analysis implementation

---

## Version History

### V2 (November 2025) - Current
- Three-service architecture (Core, Analytics, DRF Writer)
- 10 Hz NPZ as central pivot point
- **Eight voting methods** with weighted scoring
- **Nine cross-validation checks** for mutual reinforcement
- 500/600 Hz ground truth weight boosted to 15 for exclusive minutes
- Doppler stability vote uses std ratio (independent of power)
- Separated CSV outputs per method
- Canonical contracts established (Nov 20, 2025)

### V1 (October 2024) - Deprecated
- Monolithic service
- Direct Digital RF writing
- Single discrimination method
- No reprocessability

---

## Design Principles Summary

1. **Separation of Concerns:** Core stable, Analytics evolving, Consumers flexible
2. **RTP Primary:** Wall clock derived, never stretched
3. **NPZ Archives:** Enable reprocessability and algorithm evolution
4. **10 Hz Pivot:** Efficient size, multiple consumers, embedded metadata
5. **Independent Methods:** Robust discrimination via weighted voting
6. **Canonical Contracts:** Single source of truth for paths/APIs/naming
7. **Scientific Integrity:** Complete data capture, clear provenance
8. **Reliability:** Independent services, automatic recovery, backlog processing

---

**For detailed implementation, see:**
- Path management: `src/signal_recorder/paths.py`
- Discrimination: `src/signal_recorder/wwvh_discrimination.py`
- Tone detection: `src/signal_recorder/tone_detector.py`
- Analytics service: `src/signal_recorder/analytics_service.py`
- CSV writers: `src/signal_recorder/discrimination_csv_writers.py`
