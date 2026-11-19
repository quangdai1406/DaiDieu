import faulthandler
import sys

from .startup import prepare_streams

prepare_streams()

try:
    faulthandler.enable()
except Exception:  # noqa: BLE001 - nothing to write to
    pass

from .cli import main  # noqa: E402

sys.exit(main())
