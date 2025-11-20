# GRAPE Canonical Contracts - Project Standards

**Status:** MANDATORY - All code must follow these contracts  
**Created:** 2025-11-20  
**Purpose:** Single source of truth for project standards and references

---

## 📋 What Are Canonical Contracts?

Canonical contracts are the **authoritative references** that all GRAPE code must follow. Before writing any new code or calling any function, **consult these contracts first**.

---

## 📚 The Three Pillars

### 1. Directory Structure Contract
**File:** `DIRECTORY_STRUCTURE.md`  
**Purpose:** WHERE data goes and HOW to name files

**Critical Rules:**
- ✅ Always use `GRAPEPaths` API - never construct paths directly
- ✅ Follow exact naming conventions: `{CHANNEL}_{METHOD}_YYYYMMDD.csv`
- ✅ NO time-range suffixes on daily files
- ✅ Mode-aware paths (test vs production)

**Example:**
```python
# ✅ CORRECT
from signal_recorder.paths import GRAPEPaths
paths = GRAPEPaths(data_root)
csv_file = paths.get_discrimination_dir(channel) / f"{channel_dir}_discrimination_{date}.csv"

# ❌ WRONG
csv_file = Path(data_root) / 'analytics' / channel_dir / 'discrimination' / f"{channel_dir}_discrimination_{date}_12-15.csv"
```

### 2. API Reference Contract
**File:** `docs/API_REFERENCE.md`  
**Purpose:** WHAT functions exist and HOW to call them

**Contains:**
- Complete function signatures for all modules
- Parameter types and return values
- Usage examples
- Data model definitions

**Before You Code:**
1. Check if function already exists in API_REFERENCE.md
2. Verify exact signature and parameters
3. Follow documented patterns

**Example:**
```python
# Check API_REFERENCE.md first!
# Method 1: Timing Tones signature:
def detect_timing_tones(
    self,
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_timestamp: float
) -> Tuple[float, float, Optional[float], List[ToneDetectionResult]]
```

### 3. Architecture Contract
**File:** `ARCHITECTURE.md`  
**Purpose:** WHY the system is designed this way

**Core Principles:**
- Core recorder (stable) vs Analytics service (evolving)
- RTP timestamp as primary time reference
- NPZ archives enable reprocessability
- Independent discrimination methods

---

## 🔧 Enforcement Tools

### Validation Script
**File:** `scripts/validate_api_compliance.py`

Run before committing:
```bash
python3 scripts/validate_api_compliance.py
```

**Checks:**
- All path construction uses GRAPEPaths API
- File naming follows conventions
- No ad-hoc directory creation

**Status:** Should always pass ✅

---

## 📖 Quick Reference Guide

### When starting a new feature:
1. ✅ Read `ARCHITECTURE.md` - understand the design
2. ✅ Check `docs/API_REFERENCE.md` - see if function exists
3. ✅ Review `DIRECTORY_STRUCTURE.md` - know where files go
4. ✅ Write code following contracts
5. ✅ Run `validate_api_compliance.py`

### When calling existing functions:
1. ✅ Look up signature in `docs/API_REFERENCE.md`
2. ✅ Use exact parameter types and order
3. ✅ Handle return values correctly

### When creating new files:
1. ✅ Use `GRAPEPaths` API to get directory
2. ✅ Follow naming convention: `{CHANNEL}_{METHOD}_YYYYMMDD.csv`
3. ✅ NO ad-hoc paths or names

### When reprocessing data:
1. ✅ Load from archives via `paths.get_archive_dir()`
2. ✅ Write to analytics via method-specific dirs
3. ✅ Use discrimination CSV writers for separated outputs

---

## 🎯 Benefits of Canonical Contracts

### Before (Chaos):
- ❌ Direct path construction everywhere
- ❌ Inconsistent file naming (time suffixes, varied formats)
- ❌ Function signatures changed without documentation
- ❌ Duplicate/conflicting APIs (API_REFERENCE.md vs DISCRIMINATION_API.md)
- ❌ Hours wasted debugging path mismatches

### After (Clarity):
- ✅ Single source of truth for paths (`GRAPEPaths`)
- ✅ Consistent naming enforced by contracts
- ✅ Complete API documentation in one place
- ✅ Validation catches violations automatically
- ✅ New developers know exactly what to do

---

## 📊 Contract Compliance Status

**Last Validation:** 2025-11-20  
**Status:** ✅ PASSING

**Fixed Violations:**
- 14 path construction violations corrected
- All scripts now use GRAPEPaths API
- All documentation consolidated

**Files Updated:**
- `src/signal_recorder/paths.py` - Added 4 new directory methods
- `src/signal_recorder/discrimination_csv_writers.py` - Uses GRAPEPaths
- 14 scripts in `scripts/` - Converted to GRAPEPaths
- `docs/API_REFERENCE.md` - Unified API documentation

---

## 🔄 Updating Contracts

When contracts need updating:

1. **Update the contract document first**
2. **Run validation to find violations**
3. **Fix all code to comply**
4. **Verify validation passes**
5. **Commit changes together**

**Never update code without updating contracts!**

---

## 📝 Summary

These three documents form the **foundation** of the GRAPE project:

| Contract | Purpose | When to Use |
|----------|---------|-------------|
| `DIRECTORY_STRUCTURE.md` | File paths and naming | Every file operation |
| `docs/API_REFERENCE.md` | Function signatures | Every function call |
| `ARCHITECTURE.md` | System design | Understanding context |

**Golden Rule:** When in doubt, consult the contracts. If contracts are unclear, improve them first.

---

## See Also

- `CONTEXT.md` - Project context and history
- `DEPENDENCIES.md` - External dependencies
- `scripts/validate_api_compliance.py` - Enforcement tool
- `ARCHITECTURE.md` - System architecture
