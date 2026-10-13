import faulthandler
import sys

try:
    # if the process dies without a Python error (a crash inside a native library),
    # print where it happened instead of exiting silently
    faulthandler.enable()
except Exception:  # noqa: BLE001 - no stderr to write to (e.g. pythonw)
    pass

from .cli import main  # noqa: E402

sys.exit(main())
