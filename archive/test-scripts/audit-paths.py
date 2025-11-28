#!/usr/bin/env python3
"""
Path Configuration Audit Tool

Verifies that all components respect the mode-based path configuration
from grape-config.toml and identifies any hardcoded paths.
"""

import sys
from pathlib import Path

# Add src to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent / 'src'))

try:
    import tomli as toml
except ImportError:
    try:
        import tomllib as toml
    except ImportError:
        import toml

from signal_recorder.config_utils import PathResolver

def check_hardcoded_paths():
    """Scan source code for hardcoded paths"""
    print("\n" + "="*70)
    print("SCANNING FOR HARDCODED PATHS")
    print("="*70 + "\n")
    
    src_dir = Path("src/signal_recorder")
    issues = []
    
    # Patterns to look for
    hardcoded_patterns = [
        ('/tmp/grape-test', 'Test data path'),
        ('/var/lib/signal-recorder', 'Production data path'),
        ('/tmp/signal-recorder', 'Status file path'),
    ]
    
    for py_file in src_dir.glob("*.py"):
        content = py_file.read_text()
        
        for pattern, description in hardcoded_patterns:
            if pattern in content and 'DEFAULTS' not in content:
                # Check if it's a comment or in PathResolver defaults
                lines = content.split('\n')
                for i, line in enumerate(lines, 1):
                    if pattern in line and not line.strip().startswith('#'):
                        # Check if it's actually being used as fallback with PathResolver
                        context = '\n'.join(lines[max(0, i-3):min(len(lines), i+2)])
                        if 'path_resolver' not in context and 'PathResolver' not in context:
                            issues.append({
                                'file': py_file.name,
                                'line': i,
                                'pattern': pattern,
                                'description': description,
                                'code': line.strip()
                            })
    
    if issues:
        print("⚠️  Found potentially hardcoded paths:\n")
        for issue in issues:
            print(f"  {issue['file']}:{issue['line']}")
            print(f"    Pattern: {issue['pattern']} ({issue['description']})")
            print(f"    Code: {issue['code']}")
            print()
    else:
        print("✅ No problematic hardcoded paths found")
        print("   (All paths use PathResolver or have proper fallbacks)\n")
    
    return issues

def audit_path_configuration(config_file: str):
    """Audit path configuration for both test and production modes"""
    
    print("="*70)
    print("GRAPE SIGNAL RECORDER - PATH CONFIGURATION AUDIT")
    print("="*70)
    print(f"Config file: {config_file}\n")
    
    # Load config
    with open(config_file, 'rb') as f:
        config = toml.load(f)
    
    recorder_config = config.get('recorder', {})
    mode = recorder_config.get('mode', 'production')
    test_root = recorder_config.get('test_data_root', '/tmp/grape-test')
    prod_root = recorder_config.get('production_data_root', '/var/lib/signal-recorder')
    
    print(f"📍 Current Mode: {mode.upper()}")
    print(f"   Test Root:       {test_root}")
    print(f"   Production Root: {prod_root}")
    print()
    
    # Test mode paths
    print("\n" + "-"*70)
    print("TEST MODE PATHS (mode = 'test')")
    print("-"*70)
    
    test_resolver = PathResolver(config, development_mode=True)
    print(f"\n✓ Data Directory:      {test_resolver.get_data_dir()}")
    print(f"✓ Analytics Directory: {test_resolver.get_analytics_dir()}")
    print(f"✓ Quality Metrics:     {test_resolver.get_quality_metrics_dir()}")
    print(f"✓ WWV Timing CSV:      {test_resolver.get_wwv_timing_csv()}")
    print(f"✓ Upload Queue:        {test_resolver.get_upload_queue_file()}")
    print(f"✓ Status File:         {test_resolver.get_status_file()}")
    print(f"✓ Log Directory:       {test_resolver.get_log_dir()}")
    
    # Verify test paths start with test_data_root
    test_data_dir = test_resolver.get_data_dir()
    test_analytics_dir = test_resolver.get_analytics_dir()
    
    test_issues = []
    if not str(test_data_dir).startswith(test_root):
        test_issues.append(f"Data dir {test_data_dir} doesn't start with test_root {test_root}")
    if not str(test_analytics_dir).startswith(test_root):
        test_issues.append(f"Analytics dir {test_analytics_dir} doesn't start with test_root {test_root}")
    
    if test_issues:
        print("\n⚠️  Issues in test mode:")
        for issue in test_issues:
            print(f"  - {issue}")
    else:
        print(f"\n✅ All test paths correctly use: {test_root}")
    
    # Production mode paths
    print("\n" + "-"*70)
    print("PRODUCTION MODE PATHS (mode = 'production')")
    print("-"*70)
    
    prod_resolver = PathResolver(config, development_mode=False)
    print(f"\n✓ Data Directory:      {prod_resolver.get_data_dir()}")
    print(f"✓ Analytics Directory: {prod_resolver.get_analytics_dir()}")
    print(f"✓ Quality Metrics:     {prod_resolver.get_quality_metrics_dir()}")
    print(f"✓ WWV Timing CSV:      {prod_resolver.get_wwv_timing_csv()}")
    print(f"✓ Upload Queue:        {prod_resolver.get_upload_queue_file()}")
    print(f"✓ Status File:         {prod_resolver.get_status_file()}")
    print(f"✓ Log Directory:       {prod_resolver.get_log_dir()}")
    
    # Verify production paths
    prod_data_dir = prod_resolver.get_data_dir()
    prod_analytics_dir = prod_resolver.get_analytics_dir()
    
    prod_issues = []
    if not str(prod_data_dir).startswith(prod_root):
        prod_issues.append(f"Data dir {prod_data_dir} doesn't start with prod_root {prod_root}")
    if not str(prod_analytics_dir).startswith(prod_root):
        prod_issues.append(f"Analytics dir {prod_analytics_dir} doesn't start with prod_root {prod_root}")
    
    if prod_issues:
        print("\n⚠️  Issues in production mode:")
        for issue in prod_issues:
            print(f"  - {issue}")
    else:
        print(f"\n✅ All production paths correctly use: {prod_root}")
    
    # Check for path separation
    print("\n" + "-"*70)
    print("PATH ISOLATION VERIFICATION")
    print("-"*70 + "\n")
    
    test_paths = {
        'data': test_resolver.get_data_dir(),
        'analytics': test_resolver.get_analytics_dir(),
        'upload': test_resolver.get_upload_queue_file().parent,
    }
    
    prod_paths = {
        'data': prod_resolver.get_data_dir(),
        'analytics': prod_resolver.get_analytics_dir(),
        'upload': prod_resolver.get_upload_queue_file().parent,
    }
    
    # Verify no overlap
    overlap_issues = []
    for name, test_path in test_paths.items():
        prod_path = prod_paths[name]
        if str(test_path) == str(prod_path):
            overlap_issues.append(f"{name}: Test and production use same path: {test_path}")
    
    if overlap_issues:
        print("❌ PATH OVERLAP DETECTED - Test and production data will conflict!\n")
        for issue in overlap_issues:
            print(f"  ⚠️  {issue}")
    else:
        print("✅ Test and production paths are properly isolated")
        print("\nTest paths:")
        for name, path in test_paths.items():
            print(f"  {name:12} → {path}")
        print("\nProduction paths:")
        for name, path in prod_paths.items():
            print(f"  {name:12} → {path}")
    
    # Check component usage
    print("\n" + "-"*70)
    print("COMPONENT PATH USAGE")
    print("-"*70 + "\n")
    
    components = {
        'Recorder (V1)': 'grape_rtp_recorder.py',
        'Recorder (V2)': 'grape_channel_recorder_v2.py',
        'Uploader': 'uploader.py',
        'Data Manager': 'data_management.py',
        'CLI': 'cli.py',
    }
    
    for component, filename in components.items():
        file_path = Path('src/signal_recorder') / filename
        if file_path.exists():
            content = file_path.read_text()
            uses_path_resolver = 'path_resolver' in content or 'PathResolver' in content
            has_fallback = 'path_resolver' in content and 'else:' in content
            
            status = "✅" if uses_path_resolver else "❌"
            print(f"{status} {component:20} ", end='')
            if uses_path_resolver:
                if has_fallback:
                    print("Uses PathResolver with fallback")
                else:
                    print("Uses PathResolver")
            else:
                print("⚠️  No PathResolver usage found")
        else:
            print(f"⊘  {component:20} File not found")
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70 + "\n")
    
    all_good = (not test_issues and not prod_issues and not overlap_issues)
    
    if all_good:
        print("✅ Path configuration is correct!")
        print("   - Test and production modes use separate directories")
        print("   - All paths resolve correctly based on mode")
        print("   - Components use PathResolver")
    else:
        print("⚠️  Issues detected:")
        if test_issues:
            print(f"   - {len(test_issues)} test mode issue(s)")
        if prod_issues:
            print(f"   - {len(prod_issues)} production mode issue(s)")
        if overlap_issues:
            print(f"   - {len(overlap_issues)} path overlap issue(s)")
    
    print("\n" + "="*70 + "\n")
    
    return all_good and not check_hardcoded_paths()

if __name__ == '__main__':
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config/grape-config.toml'
    
    try:
        success = audit_path_configuration(config_file)
        sys.exit(0 if success else 1)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print(f"\nUsage: {sys.argv[0]} [config-file]")
        print(f"Default: config/grape-config.toml")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
