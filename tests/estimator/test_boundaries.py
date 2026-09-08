"""Guards on the estimator package's boundaries.

The package is a library. It may not reach into the timing core, and it may
not divide by the nominal sample rate anywhere except the one line that
forms the measured rate. Both rules come from the design spec, sections 1
and 7, and both erode one convenience at a time without a test.
"""

import pathlib
import re

import hf_timestd.estimator

PKG_DIR = pathlib.Path(hf_timestd.estimator.__file__).parent

FORBIDDEN_MODULES = (
    "hf_timestd.core",
    "hf_timestd.models",
    "hf_timestd.interfaces",
    "hf_timestd.io",
    "hf_timestd.replay",
)

FORBIDDEN_CLOCKS = (
    "time.time(",
    "time.monotonic(",
    "datetime.now(",
    "utcnow(",
    "chronyc",
)


def _sources():
    return sorted(PKG_DIR.glob("*.py"))


def test_package_has_sources():
    assert _sources(), f"no python sources under {PKG_DIR}"


def test_no_imports_from_the_timing_core():
    offenders = []
    for path in _sources():
        text = path.read_text()
        for module in FORBIDDEN_MODULES:
            if module in text:
                offenders.append(f"{path.name} references {module}")
    assert offenders == [], "\n".join(offenders)


def test_no_host_clock_anywhere_in_the_package():
    offenders = []
    for path in _sources():
        text = path.read_text()
        for token in FORBIDDEN_CLOCKS:
            if token in text:
                offenders.append(f"{path.name} uses {token}")
    assert offenders == [], "\n".join(offenders)


def test_only_one_line_divides_by_the_nominal_rate():
    """Exactly one line may divide by f_nom: the line forming f_meas.

    It carries the marker comment ``# THE ONE NOMINAL DIVISION`` so the test
    can tell the sanctioned line from a new one.
    """
    pattern = re.compile(
        r"/\s*(self\.)?f_nom\b|/\s*float\(\s*(self\.)?f_nom\s*\)"
    )
    offenders = []
    sanctioned = 0
    for path in _sources():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if not pattern.search(line):
                continue
            if "THE ONE NOMINAL DIVISION" in line:
                sanctioned += 1
                continue
            offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
    assert (
        sanctioned <= 1
    ), f"{sanctioned} lines claim to be the one nominal division"
