"""Guards on the estimator package's boundaries.

The package is a library. It may not reach into the timing core, and it may
not divide by the nominal sample rate anywhere except the one line that
forms the measured rate. Both rules come from the design spec, sections 1
and 7, and both erode one convenience at a time without a test.
"""

import ast
import pathlib
import re

import pytest

import hf_timestd.estimator  # type: ignore[import-untyped]

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

# Exactly one line may divide by f_nom (the sanctioned line to compute rate).
# Pattern requires dots between attribute segments, so it rejects underscore-
# joined false positives like half_f_nom or buf_nom.
NOMINAL_DIVISION = re.compile(
    r"/\s*float\(\s*(?:[A-Za-z_]\w*\.)*f_nom\s*\)"
    r"|/\s*(?:[A-Za-z_]\w*\.)*f_nom\b"
)


def _sources():
    return sorted(PKG_DIR.glob("*.py"))


def test_package_has_sources():
    assert _sources(), f"no python sources under {PKG_DIR}"


def test_no_imports_from_the_timing_core():
    """Reject all imports of forbidden modules using AST parsing.

    Detects: `import hf_timestd.core`, `from hf_timestd import core`,
    and `from hf_timestd import (core, models)`.
    """
    forbidden_short_names = {"core", "models", "interfaces", "io", "replay"}
    offenders = []

    for path in _sources():
        try:
            tree = ast.parse(path.read_text(), filename=path.name)
        except SyntaxError as e:
            offenders.append(f"{path.name}:{e.lineno} (parse error: {e.msg})")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Check: import hf_timestd.core, import hf_timestd.models, etc.
                for alias in node.names:
                    if alias.name.startswith("hf_timestd."):
                        # Allowed: hf_timestd.estimator and submodules
                        if not (
                            alias.name == "hf_timestd.estimator"
                            or alias.name.startswith("hf_timestd.estimator.")
                        ):
                            msg = (
                                f"{path.name}:{node.lineno} "
                                f"imports {alias.name}"
                            )
                            offenders.append(msg)

            elif isinstance(node, ast.ImportFrom):
                # Relative imports are OK
                if node.level > 0:
                    continue

                # Check: from hf_timestd.core import ... or from hf_timestd.*
                if node.module and node.module.startswith("hf_timestd."):
                    # Forbidden if it's not hf_timestd.estimator or a submodule
                    if not (
                        node.module == "hf_timestd.estimator"
                        or node.module.startswith("hf_timestd.estimator.")
                    ):
                        offenders.append(
                            f"{path.name}:{node.lineno} "
                            f"from {node.module} import ..."
                        )

                # Check: from hf_timestd import core, models, etc.
                elif node.module == "hf_timestd":
                    for alias in node.names:
                        if alias.name in forbidden_short_names:
                            offenders.append(
                                f"{path.name}:{node.lineno} "
                                f"from hf_timestd import {alias.name}"
                            )

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

    Note: A textual guard cannot catch a local alias (e.g., ``fs = self.f_nom``
    then ``x / fs``). This test is a smoke alarm, not a proof. The real
    protection comes from the behavioral rate tests in Tasks 4 and 8, where a
    state carrying a non-zero rate whose projection still matches the nominal
    rate fails outright.
    """
    offenders = []
    sanctioned = 0
    for path in _sources():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if not NOMINAL_DIVISION.search(line):
                continue
            if "THE ONE NOMINAL DIVISION" in line:
                sanctioned += 1
                continue
            offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
    assert sanctioned <= 1, (
        f"{sanctioned} lines claim to be the one nominal division"
    )


@pytest.mark.parametrize(
    "line,should_match,reason",
    [
        # MUST match: bare f_nom
        ("        return 1e9 * delta / f_nom", True, "bare f_nom"),
        # MUST match: self.f_nom
        ("        return 1e9 * delta / self.f_nom", True, "self.f_nom"),
        # MUST match: self.config.f_nom
        (
            "        return 1e9 * delta / self.config.f_nom",
            True,
            "self.config.f_nom",
        ),
        # MUST match: float(self.f_nom)
        (
            "        return 1e9 * delta / float(self.f_nom)",
            True,
            "float wrapper",
        ),
        # MUST NOT match: underscore-joined prefix
        ("        return samples / half_f_nom", False, "no dot before f_nom"),
        # MUST NOT match: substring match trap
        ("        return samples / buf_nom", False, "nom ≠ f_nom"),
        # MUST NOT match: similar name, different segment
        ("        return samples / f_nominal", False, "nominal ≠ f_nom"),
        # MUST NOT match: different attribute chain
        ("        return samples / self.f_meas", False, "f_meas ≠ f_nom"),
    ],
)
def test_nominal_division_pattern(line, should_match, reason):
    """Unit test the NOMINAL_DIVISION regex pattern directly.

    Ensures the pattern correctly identifies f_nom divisions and rejects
    false positives (underscore-joined names, substring matches, and similar
    names). Each test case documents why the pattern should or should not
    match.
    """
    match = NOMINAL_DIVISION.search(line)
    if should_match:
        assert match is not None, f"Expected to match {reason}: {line}"
    else:
        assert match is None, f"Should not match {reason}: {line}"
