#!/usr/bin/env python3
"""Build witness traces for the estimator's acceptance tests. One-time tool.

Reads a fixture's compressed IQ and sidecar, folds the tick envelope in short
blocks, and writes one phase observation per block per band. The absolute UTC
carries an unknown constant (propagation plus station identity), so the traces
support rate and behaviour tests and never an absolute accuracy claim.

Usage:
    python scripts/build_estimator_corpus.py FIXTURE_DIR OUT_DIR \\
        [--resample-ppm N]
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any, Dict, List

import numpy as np
import zstandard

from hf_timestd.core.registration_acquirer import (  # type: ignore
    band_envelopes,
    fold_envelope,
)

BLOCK_S = 20
MIN_SNR = 1.5
SIGMA_NS = 1_000_000.0  # 1 ms, the acquirer's own origin sigma floor


def read_iq(path: pathlib.Path) -> np.ndarray:
    with open(path, "rb") as fh:
        raw = zstandard.ZstdDecompressor().stream_reader(fh).read()
    return np.frombuffer(raw, dtype=np.complex64)


def resample_ppm(iq: np.ndarray, ppm: float) -> np.ndarray:
    """Stretch the signal as a ruler error of ``ppm`` would, by interpolation.

    A converter running ``ppm`` fast produces this many more samples per real
    second, so the same real signal lands on a longer index axis.
    """
    n_out = int(round(len(iq) * (1.0 + ppm * 1e-6)))
    src = np.arange(len(iq), dtype=np.float64)
    dst = np.linspace(0.0, len(iq) - 1.0, n_out)
    real = np.interp(dst, src, iq.real)
    imag = np.interp(dst, src, iq.imag)
    return (real + 1j * imag).astype(np.complex64)


def trace(
    iq: np.ndarray, meta: Dict[str, Any], fixture: str, block_s: int = BLOCK_S
) -> List[Dict[str, Any]]:
    fs = int(meta["sample_rate"])
    label0 = float(meta["start_system_time"])
    rtp0 = int(meta["start_rtp_timestamp"])
    out: List[Dict[str, Any]] = []
    block_len = block_s * fs
    for b in range(len(iq) // block_len):
        start = b * block_len
        end = start + block_len
        seg = np.abs(iq[start:end]).astype(np.float64)
        seg -= seg.mean()
        label_s = label0 + b * block_s
        for band, env in band_envelopes(seg, fs).items():
            profile, rows = fold_envelope(env, fs, label_s, block_s)
            if rows == 0:
                continue
            peak = int(np.argmax(profile))
            snr = float(profile[peak] / (np.median(profile) + 1e-12))
            if snr < MIN_SNR:
                continue
            mid_rtp = rtp0 + (b * block_s + block_s // 2) * fs
            second = int(np.floor(label0 + b * block_s + block_s // 2))
            utc_ns = second * 1_000_000_000 + peak * 1_000_000_000 // fs
            out.append(
                {
                    "tier": "T3",
                    "rtp": int(mid_rtp),
                    "utc_ns": int(utc_ns),
                    "sigma_ns": SIGMA_NS,
                    "plane": "label",
                    "source": "fold-peak",
                    "band": band,
                    "snr": snr,
                    "fixture": fixture,
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture_dir", type=pathlib.Path)
    ap.add_argument("out_dir", type=pathlib.Path)
    ap.add_argument("--resample-ppm", type=float, default=None)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for sidecar in sorted(args.fixture_dir.glob("*.json")):
        binary = sidecar.with_suffix(".bin.zst")
        if not binary.exists():
            continue
        meta = json.loads(sidecar.read_text())
        iq = read_iq(binary)
        suffix = ""
        if args.resample_ppm is not None:
            iq = resample_ppm(iq, args.resample_ppm)
            suffix = f"-resampled{args.resample_ppm:+g}ppm"
        fixture = f"{args.fixture_dir.name}{suffix}"
        rows = trace(iq, meta, fixture)
        name = f"{fixture}-{meta['channel_name']}.jsonl"
        text = "".join(json.dumps(r) + "\n" for r in rows)
        (args.out_dir / name).write_text(text)
        print(f"{name}: {len(rows)} observations")


if __name__ == "__main__":
    main()
