# Operational Clarification Update

**Date**: Nov 18, 2025 (evening)  
**Trigger**: User clarified actual system configuration

---

## User's Operational Summary

The user provided this critical clarification of the current system:

> **18 input channels** requesting RTP streams from radiod via ka9q-python:
> - 9× Wide bandwidth (16 kHz IQ) 
> - 9× Carrier channels (200 Hz IQ)
>
> **5 data products**:
> 1. 16 kHz wide NPZ with timing/gap metadata (9 frequencies)
> 2. 10 Hz decimated from 16 kHz (9 frequencies)
> 3. 10 Hz decimated from 200 Hz carrier (9 frequencies)
> 4. Tone detection, time_snap, gap analysis records
> 5. WWV/WWVH discrimination (4 shared frequencies)
>
> **Upload strategy**: Select best of Product 2 or 3 for Digital RF upload
>
> **Retention**: Keep wide NPZ + discrimination, upload selected 10 Hz

---

## Documentation Updates Made

### 1. Created OPERATIONAL_SUMMARY.md

**Purpose**: Comprehensive operational reference documenting current system configuration.

**Contents**:
- 18-channel configuration (9 wide + 9 carrier)
- Frequency table with WWV/CHU/WWVH mapping
- Complete specifications for all 5 data products
- Upload strategy (Product 2 vs 3 evaluation criteria)
- Data retention policy
- System data flow diagram
- Current performance metrics

**Value**: 
- Answers "what does the system actually do?"
- Concrete operational state (not historical)
- Reference for operators and future planning

### 2. Updated TECHNICAL_REFERENCE.md

Added operational configuration section at the top:
- Quick summary of 18 channels, 5 products
- Links to OPERATIONAL_SUMMARY.md for details
- Updated architecture diagram with sample counts

### 3. Updated README.md

Added documentation links in Technical Details section:
- **OPERATIONAL_SUMMARY.md** - Current system configuration
- **TECHNICAL_REFERENCE.md** - Developer quick reference
- **PROJECT_NARRATIVE.md** - Complete project history

### 4. Updated DOCUMENTATION_CLEANUP_PLAN.md

- Added OPERATIONAL_SUMMARY.md to "keep" list
- Updated file counts (9 core docs instead of 8)
- Updated "For New Developers" path to include operational overview

### 5. Updated DOCUMENTATION_REVIEW_SUMMARY.md

- Added OPERATIONAL_SUMMARY.md to created files list
- Documented files updated during session

---

## Key Improvements

### Operational Clarity

**Before**: Narrative focused on history and evolution  
**After**: Clear operational state documented separately from history

### Documentation Hierarchy

```
README.md (entry point)
    ↓
OPERATIONAL_SUMMARY.md (what does it do now?)
    ↓
TECHNICAL_REFERENCE.md (how does it work?)
    ↓
PROJECT_NARRATIVE.md (why is it this way?)
    ↓
ARCHITECTURE.md + CONTEXT.md (deep technical details)
```

### For Different Audiences

**Operators**: OPERATIONAL_SUMMARY.md → What's running, what's produced  
**Developers**: TECHNICAL_REFERENCE.md → How to work with it  
**Historians**: PROJECT_NARRATIVE.md → How we got here  
**Architects**: ARCHITECTURE.md → System design

---

## Complete File List (Created This Session)

1. ✅ **OPERATIONAL_SUMMARY.md** - Current system configuration
2. ✅ **PROJECT_NARRATIVE.md** - Complete project history
3. ✅ **TECHNICAL_REFERENCE.md** - Developer quick reference
4. ✅ **DOCUMENTATION_CLEANUP_PLAN.md** - Archival guide
5. ✅ **DOCUMENTATION_REVIEW_SUMMARY.md** - Session summary
6. ✅ **archive-superseded-docs.sh** - Cleanup automation
7. ✅ **OPERATIONAL_CLARIFICATION_UPDATE.md** - This document

**Updated**:
- README.md (added doc links)
- TECHNICAL_REFERENCE.md (added operational section)
- DOCUMENTATION_CLEANUP_PLAN.md (updated counts)
- DOCUMENTATION_REVIEW_SUMMARY.md (updated file lists)

---

## Status

**Documentation**: ✅ Complete and accurate  
**Operational clarity**: ✅ 18 channels, 5 products, upload strategy documented  
**Ready for cleanup**: ✅ Can execute archive-superseded-docs.sh when satisfied

---

**This update captures the operational reality that was missing from the initial narrative-focused documentation.**
