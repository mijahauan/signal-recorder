"""Guards on the estimator package's boundaries.

The package is a library. It may not reach into the timing core, and it may
not divide by the nominal sample rate anywhere except the one line that
forms the measured rate. Both rules come from the design spec, sections 1
and 7, and both erode one convenience at a time without a test.
"""

import ast
import pathlib
import re

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
    # Match any division by an f_nom attribute path: f_nom, self.f_nom,
    # self.config.f_nom, params.f_nom, with or without float() wrapper
    pattern = re.compile(
        r"/\s*float\(\s*[\w.]*f_nom\s*\)|/\s*[\w.]*f_nom\b"
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
    assert sanctioned <= 1, (
        f"{sanctioned} lines claim to be the one nominal division"
    )
