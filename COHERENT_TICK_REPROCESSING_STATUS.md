# Coherent Integration Reprocessing Status

## Completed ✅
- WWV 10 MHz: 2024-11-13 through 2024-11-19 
  - Errors on some files (format string issues) - being investigated
  - Most data successfully reprocessed with tick_windows_10sec field

## Needs Reprocessing ⚠️
- **WWV 5 MHz**: Old CSV format (15 columns) - missing tick_windows_10sec
- **WWV 2.5 MHz**: Check if reprocessed
- **WWV 15 MHz**: Check if reprocessed

## How to Reprocess

### Single Channel, Specific Date
```bash
./REPROCESS-DISCRIMINATION.sh
# Select option 2, enter date: 20251115
# Enter channel: WWV 5 MHz
```

### All Available Data for One Channel
```bash
python3 scripts/reprocess_discrimination.py \
  --channel "WWV 5 MHz" \
  --all
```

### Specific Date Range
```bash
python3 scripts/reprocess_discrimination.py \
  --channel "WWV 5 MHz" \
  --start-date 20251113 \
  --end-date 20251119
```

## Known Issues

### Format String Error
```
ERROR: unsupported format string passed to NoneType.__format__
```

**Status**: Investigating - some fields may be None when trying to format
**Workaround**: Script now has better error handling to skip problematic files
**Impact**: Some minutes may be missing from reprocessed data

## Verification

Check if a CSV has tick data:
```bash
head -1 /tmp/grape-test/analytics/WWV_5_MHz/discrimination/WWV_5_MHz_discrimination_20251115.csv | grep -o "," | wc -l
```
- **15 commas** = Old format (no tick data)
- **16 commas** = New format (has tick_windows_10sec)

Check web UI:
1. Open http://localhost:3000/discrimination.html
2. Select channel and date
3. Panel 5 should show tick discrimination data (mirrored plot with WWV above, WWVH below)
