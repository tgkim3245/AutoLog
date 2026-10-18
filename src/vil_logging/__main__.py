"""Freeze support must run before application or UI initialization."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from vil_logging.app import main

    raise SystemExit(main())
