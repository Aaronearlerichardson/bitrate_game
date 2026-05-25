"""Package entry point: enables `python -m bitrate_game` and Nuitka builds."""

import sys

from bitrate_game.main import main

if __name__ == "__main__":
    sys.exit(main())
