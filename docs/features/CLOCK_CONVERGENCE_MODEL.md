# Clock Convergence Model

## Philosophy: "Set, Monitor, Intervention"

With a GPSDO-disciplined receiver, the local clock is a secondary standard with parts-per-billion stability. Instead of constantly recalculating clock offset, we:

1. **SET**: Converge to a locked clock offset estimate
2. **MONITOR**: Track residuals to reveal real ionospheric propagation effects
3. **INTERVENTION**: Only re-acquire if anomaly detected or physics violated

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Per-Station Convergence                           │
├─────────────────────────────────────────────────────────────────────┤
│  Accumulator: Running mean, variance, sample count                   │
│  Uncertainty: σ/√N (shrinks with each measurement)                  │
│  Lock Criterion: uncertainty < 1ms AND N > 30 samples               │
│  Anomaly Detection: |residual| > 3σ                                 │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
              ┌─────────────────────────────────────┐
              │  Once Locked:                        │
              │  • D_clock estimate is stable        │
              │  • Residuals = propagation effects   │
              │  • Anomalies → ionospheric events    │
              └─────────────────────────────────────┘
```

## State Machine

```
     ┌──────────────┐
     │  ACQUIRING   │ ◄── N < 10 samples
     └──────┬───────┘
            │ N >= 10
            ▼
     ┌──────────────┐
     │  CONVERGING  │ ◄── Building statistics
     └──────┬───────┘
            │ uncertainty < 1ms AND N >= 30
            ▼
     ┌──────────────┐
     │   LOCKED     │ ◄── Monitoring mode
     └──────┬───────┘
            │ 5 consecutive anomalies
            ▼
     ┌──────────────┐
     │  REACQUIRE   │ ──► Back to ACQUIRING
     └──────────────┘
```

## Convergence Behavior

| Minute | State | Uncertainty | D_clock | Notes |
|--------|-------|-------------|---------|-------|
| 1 | ACQUIRING | ∞ | -4.0 ms | First measurement |
| 10 | CONVERGING | ~10 ms | -5.2 ms | Statistics building |
| 30 | LOCKED | < 1 ms | -5.8 ms | **Lock achieved!** |
| 31+ | LOCKED | ~0.9 ms | -5.8 ms | Monitoring residuals |

## Key Insight: Residuals

Once locked, minute-to-minute variations are **RESIDUALS** that reveal real ionospheric propagation effects:

```python
residual_ms = raw_measurement - converged_d_clock
```

- **Small residual** (< 1σ): Normal jitter
- **Medium residual** (1-3σ): Propagation variation  
- **Large residual** (> 3σ): **Propagation event!** → Log and flag

## Integration with Phase 2

The `Phase2AnalyticsService` automatically uses the convergence model:

```python
# In _write_clock_offset():
convergence_result = self.convergence_model.process_measurement(
    station=station,
    frequency_mhz=frequency_mhz,
    d_clock_ms=result.d_clock_ms,
    timestamp=float(minute_boundary),
    snr_db=self.last_carrier_snr_db,
    quality_grade=result.quality_grade
)

# Use converged values when locked
if convergence_result.is_locked:
    effective_d_clock = convergence_result.d_clock_ms
    effective_uncertainty = convergence_result.uncertainty_ms
    quality_grade = 'A' if uncertainty < 0.5 else 'B'
```

## CSV Output Changes

When the convergence model is locked:

| Field | Before | After (Locked) |
|-------|--------|----------------|
| clock_offset_ms | Raw measurement | Converged mean |
| uncertainty_ms | ~30 ms | < 1 ms |
| quality_grade | D | A or B |
| utc_verified | False | **True** |

## Kalman Funnel Display

The web UI Kalman Funnel now shows:
- **Blue (LOCKED)**: When quality_grade is A/B or utc_verified is True
- **Gray (HOLD)**: Still converging

The funnel width (uncertainty bands) naturally narrows as measurements accumulate.

## State Persistence

Convergence state is persisted to `status/convergence_state.json`:

```json
{
  "version": 1,
  "timestamp": "2025-12-05T13:34:56Z",
  "accumulators": {
    "WWV_10.0": {
      "station": "WWV",
      "frequency_mhz": 10.0,
      "count": 45,
      "mean_ms": -5.823,
      "state": "locked",
      "locked_mean_ms": -5.823,
      "locked_uncertainty_ms": 0.87
    }
  }
}
```

This allows the model to resume after service restart without losing convergence progress.

## Configuration

```python
ClockConvergenceModel(
    lock_uncertainty_ms=1.0,      # Lock when σ/√N < 1ms
    min_samples_for_lock=30,      # Need 30 minutes of data
    anomaly_sigma=3.0,            # 3σ for anomaly detection
    max_consecutive_anomalies=5,  # Force reacquire after 5 anomalies
    state_file=Path('convergence_state.json')
)
```

## Benefits

1. **Proper uncertainty quantification**: σ/√N instead of arbitrary fixed values
2. **Stable D_clock**: Once locked, estimate doesn't jump around
3. **Propagation science**: Residuals reveal real ionospheric dynamics
4. **Anomaly detection**: Automatic flagging of propagation events
5. **Quality grades**: Meaningful A/B grades based on convergence
6. **GPSDO philosophy**: Set once, monitor, intervene only if needed
