import faulthandler
import sys

from .startup import prepare_streams

prepare_streams()  # a windowless launch (pythonw) has no stdout/stderr: log to a file instead

try:
    # if the process dies without a Python error (a crash inside a native library),
    # print where it happened instead of exiting silently
    faulthandler.enable()
except Exception:  # noqa: BLE001 - nothing to write to
    pass

from .cli import main  # noqa: E402

sys.exit(main())
