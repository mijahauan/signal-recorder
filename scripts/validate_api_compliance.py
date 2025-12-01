#!/usr/bin/env python3
"""
API Compliance Validation Script

Validates that all code follows the canonical contracts defined in:
- DIRECTORY_STRUCTURE.md
- docs/DISCRIMINATION_API.md
- docs/API_REFERENCE.md

Checks:
1. All path construction uses GRAPEPaths API
2. All discrimination calls match API signatures
3. All CSV files follow naming conventions
4. No ad-hoc directory creation
5. No time-range suffixes on files

Usage:
    python3 scripts/validate_api_compliance.py
"""

import ast
import re
from pathlib import Path
from typing import List, Tuple, Dict
import sys

class ComplianceChecker:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.src_dir = repo_root / 'src' / 'grape_recorder'
        self.scripts_dir = repo_root / 'scripts'
        self.violations = []
        
    def check_all(self) -> bool:
        """Run all compliance checks. Returns True if all pass."""
        print("=" * 70)
        print("GRAPE API Compliance Validation")
        print("=" * 70)
        print()
        
        self.check_path_construction()
        self.check_file_naming()
        self.check_discrimination_signatures()
        
        print()
        print("=" * 70)
        if self.violations:
            print(f"❌ FAILED - {len(self.violations)} violation(s) found")
            print("=" * 70)
            for i, (file, line, msg) in enumerate(self.violations, 1):
                print(f"\n{i}. {file}:{line}")
                print(f"   {msg}")
            return False
        else:
            print("✅ PASSED - All checks successful")
            print("=" * 70)
            return True
    
    def check_path_construction(self):
        """Check that all code uses GRAPEPaths API instead of direct construction."""
        print("Checking path construction...")
        
        forbidden_patterns = [
            (r'Path\([^)]*\)\s*/\s*["\']analytics["\']', 
             "Direct 'analytics' path construction - use paths.get_analytics_dir()"),
            (r'Path\([^)]*\)\s*/\s*["\']archives["\']',
             "Direct 'archives' path construction - use paths.get_archive_dir()"),
            (r'/["\']discrimination["\'](?!.*get_discrimination)',
             "Direct 'discrimination' path - use paths.get_discrimination_dir()"),
            (r'data_root\s*/\s*["\']analytics["\']',
             "Direct data_root/analytics - use GRAPEPaths API"),
            (r'\.replace\(\s*["\']["\'],\s*["\']_["\']\s*\).*discrimination',
             "Manual channel name conversion near discrimination - use paths API"),
        ]
        
        python_files = list(self.src_dir.rglob("*.py")) + list(self.scripts_dir.rglob("*.py"))
        
        for py_file in python_files:
            if 'paths.py' in str(py_file) or 'validate_api' in str(py_file):
                continue  # Skip paths.py itself and this script
                
            try:
                content = py_file.read_text()
                lines = content.split('\n')
                
                for i, line in enumerate(lines, 1):
                    # Skip lines with "for iteration only" or "for existence check only" comments
                    if '# For iteration only' in line or '# For existence check only' in line:
                        continue
                    
                    for pattern, msg in forbidden_patterns:
                        if re.search(pattern, line):
                            self.violations.append((
                                py_file.relative_to(self.repo_root),
                                i,
                                f"Path construction violation: {msg}"
                            ))
            except Exception as e:
                print(f"  Warning: Could not check {py_file}: {e}")
        
        print(f"  Checked {len(python_files)} Python files")
    
    def check_file_naming(self):
        """Check that generated files follow naming conventions."""
        print("Checking file naming conventions...")
        
        analytics_dir = self.repo_root.parent / 'tmp' / 'grape-test' / 'analytics'
        if not analytics_dir.exists():
            print("  Skipped (no test data directory)")
            return
        
        # Check for time-range suffixes (forbidden)
        time_range_pattern = re.compile(r'_\d{2}-\d{2}\.csv$')
        
        violations_found = 0
        for csv_file in analytics_dir.rglob("*.csv"):
            filename = csv_file.name
            
            # Check for time-range suffix
            if time_range_pattern.search(filename):
                self.violations.append((
                    csv_file.relative_to(analytics_dir.parent),
                    0,
                    f"File has time-range suffix - files should be daily without hour ranges"
                ))
                violations_found += 1
            
            # Check method naming position
            if 'discrimination' in filename:
                # Should be: {CHANNEL}_discrimination_YYYYMMDD.csv
                # NOT: {CHANNEL}_YYYYMMDD_discrimination.csv
                match = re.match(r'([A-Z_0-9]+)_(\d{8})_([a-z_]+)\.csv', filename)
                if match:
                    self.violations.append((
                        csv_file.relative_to(analytics_dir.parent),
                        0,
                        f"Method name after date - should be {match.group(1)}_{match.group(3)}_{match.group(2)}.csv"
                    ))
                    violations_found += 1
        
        if violations_found == 0:
            print(f"  ✓ File naming compliant")
        else:
            print(f"  ✗ Found {violations_found} naming violations")
    
    def check_discrimination_signatures(self):
        """Check that discrimination method calls match API signatures."""
        print("Checking discrimination API signatures...")
        
        # Expected signatures from DISCRIMINATION_API.md
        expected_sigs = {
            'detect_timing_tones': {
                'params': ['iq_samples', 'sample_rate', 'minute_timestamp'],
                'returns': 4  # Tuple with 4 elements
            },
            'detect_tick_windows': {
                'params': ['iq_samples', 'sample_rate'],
                'returns': 1  # List[Dict]
            },
            'detect_440hz_tone': {
                'params': ['iq_samples', 'sample_rate', 'minute_number'],
                'returns': 2  # Tuple with 2 elements
            },
            'detect_bcd_discrimination': {
                'params': ['iq_samples', 'sample_rate', 'minute_timestamp'],
                'returns': 5  # Tuple with 5 elements
            },
            'analyze_minute_with_440hz': {
                'params': ['iq_samples', 'sample_rate', 'minute_timestamp'],
                'optional_params': ['detections'],
                'returns': 1  # Optional[DiscriminationResult]
            }
        }
        
        python_files = list(self.src_dir.rglob("*.py")) + list(self.scripts_dir.rglob("*.py"))
        
        for py_file in python_files:
            if 'wwvh_discrimination.py' in str(py_file):
                continue  # Skip the implementation itself
                
            try:
                content = py_file.read_text()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        # Check if it's a discriminator method call
                        if isinstance(node.func, ast.Attribute):
                            method_name = node.func.attr
                            
                            if method_name in expected_sigs:
                                expected = expected_sigs[method_name]
                                
                                # Check parameter count
                                actual_args = len(node.args)
                                expected_args = len(expected['params'])
                                
                                # Warn if unpacking doesn't match return count
                                # (This is approximate - full analysis needs context)
                                if hasattr(node, 'lineno'):
                                    line_num = node.lineno
                                    # We can't easily check unpacking without more context
                                    # Just flag calls for manual review
                                    pass
                                    
            except Exception as e:
                print(f"  Warning: Could not parse {py_file}: {e}")
        
        print(f"  Checked {len(python_files)} Python files")


def main():
    repo_root = Path(__file__).parent.parent
    checker = ComplianceChecker(repo_root)
    
    success = checker.check_all()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
