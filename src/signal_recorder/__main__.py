"""
Allow running signal_recorder modules with python -m
"""

import sys

if __name__ == '__main__':
    # Check which submodule to run based on argv
    if len(sys.argv) > 1 and sys.argv[1] == 'audio_stream':
        # Remove the submodule name from argv
        sys.argv.pop(1)
        from .audio_stream import main
        main()
    else:
        # Default to CLI
        from .cli import main
        main()
