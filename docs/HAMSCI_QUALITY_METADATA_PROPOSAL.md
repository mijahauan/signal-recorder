# Proposal: Quality Metadata Standard for PSWS/GRAPE Data

**To:** HamSCI GRAPE/PSWS Working Group  
**From:** Signal-Recorder Development Team  
**Date:** November 3, 2025  
**Subject:** Comprehensive Quality Metadata for Time-Series Data Provenance

## Executive Summary

We propose extending the current PSWS/GRAPE data format to include **comprehensive quality metadata** that tracks timing accuracy, data completeness, and signal quality. This metadata provides essential scientific provenance for published research while maintaining backward compatibility with existing tools.

## Motivation

### Current Limitations

The current wsprdaemon/GRAPE pipeline stores only basic metadata:
- Callsign, grid square, receiver name
- Center frequencies
- UUID

**Missing critical information:**
- Data completeness percentage
- Gap locations and durations
- Timing accuracy (especially WWV tone errors)
- Packet loss statistics
- RTP jitter and discontinuities
- Signal quality metrics

### Scientific Impact

Researchers using GRAPE data currently cannot answer:
1. **"How complete is this dataset?"** - No way to know if minutes/hours are missing
2. **"How accurate is the timing?"** - No validation of WWV time synchronization
3. **"What's the data quality?"** - No signal-to-noise or quality assessment
4. **"Were there systematic issues?"** - No way to identify equipment problems

## Proposed Solution

### 1. Extended Digital RF Metadata

Add a `quality_metadata` field to existing Digital RF metadata (backward compatible):

```python
metadata = {
    # Existing fields (unchanged)
    'callsign': 'AI6VN',
    'grid_square': 'CM87',
    'receiver_name': 'GRAPE-S000171',
    'center_frequencies': [2500000.0, ...],
    'sample_rate': 10.0,
    'uuid_str': '<uuid>',
    
    # NEW: Quality metadata (ignored by old readers)
    'quality_metadata': {
        'version': '1.0',
        
        # Data Completeness
        'completeness_percent': 99.87,
        'minutes_expected': 1440,
        'minutes_recorded': 1438,
        'minutes_missing': 2,
        
        # Gap Statistics
        'total_gaps': 23,
        'total_gap_duration_sec': 45.2,
        'longest_gap_sec': 12.4,
        'longest_gap_timestamp': '2025-11-03T14:23:00Z',
        
        # Timing Quality (WWV channels)
        'wwv_timing': {
            'detections_expected': 1440,
            'detections_successful': 1418,
            'detection_rate_percent': 98.47,
            'mean_error_ms': -1.8,
            'std_error_ms': 2.3,
            'max_error_ms': 8.1,
            'drift_ms_per_hour': 0.05
        },
        
        # RTP Quality
        'rtp_statistics': {
            'total_packets_received': 8640000,
            'total_packets_dropped': 1243,
            'packet_loss_percent': 0.014,
            'rtp_resets': 2,
            'mean_jitter_ms': 0.24,
            'max_jitter_ms': 2.1
        },
        
        # Signal Quality
        'signal_quality': {
            'mean_power_db': -42.3,
            'std_power_db': 1.8,
            'dynamic_range_db': 65.2,
            'clipping_detected': False
        },
        
        # Processing Provenance
        'processing': {
            'recorder_version': 'signal-recorder-0.2.0',
            'decimation_method': 'scipy.decimate-3stage-FIR',
            'archive_format': 'npz-compressed',
            'processing_timestamp': '2025-11-04T00:05:23Z'
        }
    }
}
```

### 2. Companion Quality Files

Alongside Digital RF data, provide detailed CSV files:

**`<channel>_minute_quality_<date>.csv`**
- Per-minute metrics (1440 rows)
- Completeness, packet loss, signal power, WWV timing
- Enables time-series quality analysis

**`<channel>_discontinuities_<date>.csv`**
- Every gap, RTP reset, timing adjustment
- Sample-level precision
- Complete audit trail

**`<channel>_daily_summary_<date>.json`**
- Aggregate statistics
- Quick quality assessment
- Machine-readable

### 3. Quality Report PDF

Automated generation of:
- Timeline plots (completeness, packet loss, timing)
- Statistical summaries
- Anomaly identification
- Publication-ready figures

## Implementation

### Reference Implementation

We have implemented this system in `signal-recorder` with:
- ✅ Real-time quality tracking
- ✅ Per-minute compressed archives (full 8 kHz bandwidth)
- ✅ WWV timing analysis with sub-millisecond accuracy
- ✅ Comprehensive gap detection and tracking
- ✅ Digital RF output with embedded quality metadata
- ✅ Automated quality report generation

### Storage Impact

| Item | Size | Notes |
|------|------|-------|
| Minute archives | ~2 GB/day/channel | Full 8 kHz bandwidth, compressed |
| Quality CSVs | ~200 KB/day/channel | Text files |
| Digital RF (10 Hz) | ~7 MB/day/channel | Same as current |
| **Total** | **~2 GB/day/channel** | 99.7% is full-bandwidth archive |

### Computational Cost

- Recording: <5% CPU overhead (quality tracking)
- Post-processing: ~5-10 min/day/channel (decimation + Digital RF creation)
- Report generation: ~1 min/day/channel (plots)

## Use Cases

### 1. Scientific Publications

**Before:**
> "We analyzed WWV 2.5 MHz data from station AI6VN..."

**After:**
> "We analyzed WWV 2.5 MHz data from station AI6VN (99.87% complete, WWV timing error -1.8±2.3 ms, packet loss 0.014%). See supplementary materials for detailed quality metrics."

### 2. Multi-Station Studies

Compare data quality across network:
- Identify best stations for specific studies
- Detect systematic issues
- Validate cross-correlation results

### 3. Equipment Debugging

Quickly identify:
- Network issues (packet loss patterns)
- Clock drift (WWV timing trends)
- Receiver problems (signal power variations)
- RTP source issues (resets, jitter)

### 4. Long-Term Trending

Track receiver health over months/years:
- Degradation detection
- Maintenance scheduling
- Performance optimization

## Benefits for PSWS Network

1. **Data Quality Assurance** - Know what you're uploading
2. **Network Health Monitoring** - Identify problematic stations
3. **Scientific Credibility** - Transparent quality reporting
4. **Reduced Support Load** - Self-diagnosis of issues
5. **Research Value** - Better data enables better science

## Backward Compatibility

- ✅ Old wsprdaemon tools ignore new metadata fields
- ✅ Digital RF format unchanged
- ✅ File structure compatible
- ✅ No breaking changes

**Migration Path:**
1. Stations can upgrade gradually
2. Both formats coexist
3. Archive data can be reprocessed

## Example Quality Report

See attached: `example_quality_report_WWV2.5_20251103.pdf`

Key features:
- **Completeness timeline** - Visual gap identification
- **Packet loss events** - Network issue detection  
- **WWV timing accuracy** - Sub-ms precision validation
- **Signal power** - Receiver stability assessment

## Adoption Strategy

### Phase 1: Pilot (6 months)
- 3-5 stations adopt new format
- Generate quality reports
- Gather feedback from researchers

### Phase 2: Documentation (3 months)
- Document metadata standard
- Create integration guide
- Provide example code

### Phase 3: Deployment (Ongoing)
- Gradual station upgrades
- Network-wide quality monitoring
- Archive reprocessing

## Alternatives Considered

### Option A: Separate Quality Database
❌ Complexity - requires new infrastructure  
❌ Separation - metadata divorced from data  
✅ Our solution: Embed in existing Digital RF

### Option B: Minimal Metadata Only
❌ Insufficient - doesn't meet scientific needs  
❌ Lost opportunity - reprocessing expensive  
✅ Our solution: Comprehensive from start

### Option C: External Quality Service
❌ Reliability - single point of failure  
❌ Latency - delayed quality feedback  
✅ Our solution: Local, real-time tracking

## Open Questions for Discussion

1. **Metadata Schema Versioning** - How to evolve standard over time?
2. **Server Storage** - Should PSWS archive quality CSVs?
3. **Web Display** - Should PSWS website show quality metrics?
4. **Alert Thresholds** - What quality triggers email alerts?
5. **Archive Policy** - Keep full-bandwidth archives how long?

## Request for Feedback

We seek community input on:
- Metadata schema (what's missing?)
- Quality thresholds (good/bad definitions?)
- Report format (what plots are most useful?)
- Implementation timeline
- Archive storage strategy

## Conclusion

Quality metadata transforms GRAPE data from "black box" recordings to **scientifically validated measurements** with complete provenance. This enhancement requires minimal changes to existing infrastructure while providing substantial benefits for research integrity and network operations.

**We recommend adopting this standard for all new PSWS stations.**

---

## Appendix A: Comparison with Other Networks

| Network | Timing Metadata | Gap Tracking | Quality Metrics | Provenance |
|---------|----------------|--------------|-----------------|------------|
| **PSWS (current)** | ❌ No | ❌ No | ❌ No | ⚠️ Minimal |
| **PSWS (proposed)** | ✅ WWV | ✅ Sample-level | ✅ Comprehensive | ✅ Complete |
| SuperDARN | ⚠️ Basic | ⚠️ Basic | ❌ No | ⚠️ Basic |
| Madrigal | ✅ GPS | ✅ Yes | ⚠️ Limited | ✅ Good |
| GNSS Networks | ✅ Atomic | ✅ Yes | ✅ Yes | ✅ Excellent |

**Our proposal brings PSWS to parity with professional ionospheric networks.**

## Appendix B: Sample Code

```python
# Load Digital RF with quality metadata
import digital_rf as drf

reader = drf.DigitalRFReader('/path/to/data')
metadata = reader.get_properties('WWV_2.5_MHz')

# Check data quality
quality = metadata['quality_metadata']
if quality['completeness_percent'] < 95:
    print("WARNING: Low data completeness!")

if 'wwv_timing' in quality:
    timing_error = quality['wwv_timing']['mean_error_ms']
    print(f"WWV timing error: {timing_error:.1f} ms")
```

## Contact

For questions or feedback:
- GitHub: https://github.com/your-org/signal-recorder
- Email: contact@example.com
- HamSCI Forum: TBD

---

*This proposal is based on real implementation and testing with GRAPE station S000171.*
