"""signalflow CLI: python -m signalflow [run|smoke|topics|prune]"""

from .engine import main

if __name__ == "__main__":
    raise SystemExit(main())
