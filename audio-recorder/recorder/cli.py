"""Command line interface: ``python -m recorder devices | record | transcribe``."""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .mixer import export_mp3
from .session import MODES, RecordingSession, unique_dir
from .transcribe import (GPU_HINT, SPEAKERS, explain_error, format_clock, load_model, transcribe_file,
                         write_transcripts)

CONSENT = ("Reminder: tell the other participants you are recording. Many places "
           "require everyone's consent.")


def build_parser():
    p = argparse.ArgumentParser(prog="recorder", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list microphones and loopback (speaker) devices")
    gui = sub.add_parser("gui", help="open the simple Record / Stop / Save / Transcribe window")
    add_whisper_args(gui)

    chk = sub.add_parser("check", help="test whether transcription works on the processor and on the GPU")
    chk.add_argument("--model", default="tiny.en", help="a small model keeps the test quick")

    rec = sub.add_parser("record", help="record speakers + microphone")
    rec.add_argument("--mode", choices=sorted(MODES), default="meeting")
    rec.add_argument("--out", default="recordings", help="base folder for session folders")
    rec.add_argument("--mic", type=int, help="microphone device index (see `devices`)")
    rec.add_argument("--loopback", type=int, help="loopback device index (see `devices`)")
    rec.add_argument("--sample-rate", type=int, default=48000)
    rec.add_argument("--mic-gain", type=float, default=1.0)
    rec.add_argument("--music-gain", type=float, default=1.0)
    rec.add_argument("--keep-tracks", action="store_true", default=None,
                     help="keep the separate tracks in karaoke mode")
    rec.add_argument("--mp3", action="store_true",
                     help="also save mix.mp3 (small file, e.g. for Word's Transcribe upload)")
    rec.add_argument("--transcribe", action="store_true",
                     help="transcribe locally after recording (meeting mode)")
    add_whisper_args(rec)

    tr = sub.add_parser("transcribe", help="transcribe a recording folder, or any audio file")
    tr.add_argument("target", help="a recording folder (me.wav / others.wav), or an audio file "
                                   "such as .m4a, .mp3 or .wav")
    add_whisper_args(tr)
    return p


def add_whisper_args(parser):
    parser.add_argument("--model", default="base.en", help="faster-whisper model name")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"])
    parser.add_argument("--compute-type", default=None,
                        help="precision; default is int8 on the processor and auto on a GPU")
    parser.add_argument("--language", default="en")


def default_waiter(session):
    """Show live levels until Ctrl+C."""
    try:
        while True:
            levels = "  ".join(f"{name}: {'#' * int(peak * 20):<20}" for name, peak in session.peaks.items())
            print(f"\r{levels}", end="", flush=True)
            time.sleep(0.25)
    except KeyboardInterrupt:
        print()


def progress_printer(clock=time.monotonic):
    """A callback that rewrites one console line: '00:12:34 of 00:45:10 (27%)  elapsed 00:02:10, 5.8x real time'."""
    started = clock()
    state = {"last": None, "done": 0.0, "shown": False}

    def pace(done, elapsed):
        text = f"elapsed {format_clock(elapsed)}"
        if elapsed >= 1 and done > 0:
            text += f", {done / elapsed:.1f}x real time"
        return text

    def show(done, total):
        percent = int(done / total * 100) if total else None
        if percent is not None and percent == state["last"]:
            return
        state["last"], state["done"] = percent, done
        where = f"{format_clock(done)} of {format_clock(total)} ({percent}%)" if total \
            else f"{format_clock(done)} transcribed so far"
        print("\r  " + where + "  " + pace(done, clock() - started), end="", flush=True)
        state["shown"] = True

    def finish():
        if state["shown"]:
            elapsed = clock() - started
            speed = f" ({state['done'] / elapsed:.1f}x real time)" if elapsed >= 1 else ""
            print(f"\n  Finished in {format_clock(elapsed)}{speed}.")

    show.finish = finish
    return show


def run_transcribe(target, args, model_loader):
    target = Path(target)
    if not target.exists():
        print(f"Not found: {target}")
        return 1
    try:
        print(f"Loading the speech model '{args.model}' (the first run downloads it, "
              "which can take several minutes)...", flush=True)
        model = model_loader(args.model, args.device, args.compute_type)
        print(f"Transcribing {target.name}... (a long file can take about as long as the audio)",
              flush=True)
        progress = progress_printer()
        if target.is_dir():
            txt, srt = write_transcripts(model, target, SPEAKERS, args.language, progress)
        else:
            txt, srt = transcribe_file(model, target, args.language, progress)
        progress.finish()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - always say what went wrong
        print(explain_error(exc))
        return 1
    print(f"Transcript: {txt}\nSubtitles:  {srt}")
    return 0


def run_probe(model, device):
    """Run the self-test in a separate process; returns (ok, exit code, last output lines)."""
    import subprocess

    try:
        done = subprocess.run([sys.executable, "-X", "faulthandler", "-m", "recorder.probe", model, device],
                              capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return False, None, "timed out after 15 minutes"
    text = (done.stdout + "\n" + done.stderr).strip()
    return done.returncode == 0 and "PROBE OK" in done.stdout, done.returncode, "\n".join(text.splitlines()[-6:])


def run_check(args, probe_runner):
    print(f"Testing the speech model '{args.model}' on each device (the first run downloads it)...", flush=True)
    works = {}
    for device in ("cpu", "cuda"):
        ok, code, detail = probe_runner(args.model, device)
        works[device] = ok
        if ok:
            print(f"  {device:<4}: OK")
            continue
        hexcode = f" (0x{code & 0xFFFFFFFF:08X})" if isinstance(code, int) else ""
        print(f"  {device:<4}: FAILED (exit code {code}{hexcode})")
        for line in detail.splitlines():
            print(f"        {line}")
    if works["cuda"]:
        print("Use the GPU:  python -m recorder gui --device cuda   (try --model small.en or medium.en)")
        return 0
    if works["cpu"]:
        print("The processor works. Use:  python -m recorder gui")
        print(GPU_HINT)
        return 0
    print("Neither the processor nor the GPU worked. Please send me this whole output.")
    return 1


def main(argv=None, *, backend=None, waiter=default_waiter, model_loader=load_model,
         now=datetime.now, probe_runner=run_probe):
    args = build_parser().parse_args(argv)
    if backend is None:
        from .wasapi import WasapiBackend
        backend = WasapiBackend()

    if args.command == "check":
        return run_check(args, probe_runner)

    if args.command == "gui":
        try:
            from .gui import run
        except ImportError:
            print("The window needs tkinter, which comes with the python.org installer "
                  "(re-run it and tick 'tcl/tk and IDLE').")
            return 1
        return run(backend, model_name=args.model, device=args.device,
                   compute_type=args.compute_type, language=args.language)

    if args.command == "devices":
        for d in backend.list_devices():
            star = "*" if d["default"] else " "
            print(f"{star} [{d['index']:>3}] {d['kind']:<8} {d['name']}  ({d['channels']} ch, {d['rate']} Hz)")
        print("* = default")
        return 0

    if args.command == "transcribe":
        return run_transcribe(args.target, args, model_loader)

    session_dir = unique_dir(args.out, f"{now():%y_%m%d_%H%M}_{args.mode}")
    mic, loopback = backend.open_sources(args.mic, args.loopback)
    session = RecordingSession(session_dir, mic, loopback, mode=args.mode,
                               sample_rate=args.sample_rate, mic_gain=args.mic_gain,
                               music_gain=args.music_gain, keep_tracks=args.keep_tracks)
    if args.mode == "meeting":
        print(CONSENT)
    session.start()
    print(f"● RECORDING ({args.mode}) -> {session_dir}\n  Press Ctrl+C to stop.")
    try:
        waiter(session)
    finally:
        result = session.stop()
    print(f"Saved {result.duration:.0f}s: {result.mix}")
    for name, path in result.tracks.items():
        print(f"  track {name}: {path}")
    if args.mp3:
        print(f"  mp3: {export_mp3(result.mix, result.mix.with_suffix('.mp3'))}")
    if args.transcribe and args.mode == "meeting":
        run_transcribe(session_dir, args, model_loader)
    return 0


if __name__ == "__main__":
    sys.exit(main())
