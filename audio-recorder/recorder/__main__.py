import faulthandler
import sys

from .startup import prepare_streams

prepare_streams()

try:
    faulthandler.enable()
except Exception:
    pass

from .cli import main

sys.exit(main())
