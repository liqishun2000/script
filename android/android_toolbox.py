"""Run with python android/android_toolbox.py or python -m android.toolbox."""

import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from android.toolbox.app import main

    raise SystemExit(main())
