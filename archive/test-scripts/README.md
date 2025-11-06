# Development Test Scripts Archive

This directory contains test and diagnostic scripts created during development to investigate specific issues or test individual components.

## Purpose

These scripts were valuable during development but are no longer needed for regular operation. They are preserved for:
- Reference implementations
- Future debugging similar issues
- Understanding component behavior

## Categories

### Test Scripts (test-*.py)
Individual component tests, RTP packet analysis, timing verification, etc.

### Debug Scripts (debug-*.py)
Diagnostic tools for investigating signal quality, packet flow, and timing issues.

### Diagnostic Tools
Signal analysis, spectrum inspection, WWV detection debugging.

## Active Test Suite

For current testing, see:
- `/test_grape_recorder.py` - Integration tests
- `/test_grape_components.py` - Unit tests
- `/test_digital_rf_write.py` - I/O tests
- `/test_resampler.py` - Decimation tests

---

*Archived: November 2025*
