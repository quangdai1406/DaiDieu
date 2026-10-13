"""Tiny self-test behind `python -m recorder check`.

Runs in its own process, so a crash inside a native library is reported by
the parent instead of taking the whole program down.
"""

import sys


def main(argv=None):
    argv = sys.argv if argv is None else argv
    model_name, device = argv[1], argv[2]
    import numpy as np

    from . import transcribe

    try:
        model = transcribe.load_model(model_name, device, None)
        segments, _info = model.transcribe(np.zeros(16000, dtype="float32"), language="en")
        list(segments)  # decoding is lazy: this is what touches the GPU libraries
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a plain reason beats a traceback here
        print(transcribe.explain_error(exc))
        return 1
    print("PROBE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
