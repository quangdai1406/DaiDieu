"""Command line interface: ``python -m recorder devices | record | transcribe``."""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .mixer import export_mp3
from .session import MODES, RecordingSession
from .transcribe import load_model, write_transcripts

CONSENT = ("Reminder: tell the other participants you are recording. Many places "
           "require everyone's consent.")
SPEAKERS = {"me": "Me", "others": "Others"}


def build_parser():
    p = argparse.ArgumentParser(prog="recorder", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list microphones and loopback (speaker) devices")

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

    tr = sub.add_parser("transcribe", help="transcribe me.wav / others.wav in a session folder")
    tr.add_argument("session_dir")
    add_whisper_args(tr)
    return p


def add_whisper_args(parser):
    parser.add_argument("--model", default="base.en", help="faster-whisper model name")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"])
    parser.add_argument("--compute-type", default="int8")
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


def run_transcribe(session_dir, args, model_loader):
    model = model_loader(args.model, args.device, args.compute_type)
    txt, srt = write_transcripts(model, session_dir, SPEAKERS, args.language)
    print(f"Transcript: {txt}\nSubtitles:  {srt}")


def main(argv=None, *, backend=None, waiter=default_waiter, model_loader=load_model, now=datetime.now):
    args = build_parser().parse_args(argv)
    if backend is None:
        from .wasapi import WasapiBackend
        backend = WasapiBackend()

    if args.command == "devices":
        for d in backend.list_devices():
            star = "*" if d["default"] else " "
            print(f"{star} [{d['index']:>3}] {d['kind']:<8} {d['name']}  ({d['channels']} ch, {d['rate']} Hz)")
        print("* = default")
        return 0

    if args.command == "transcribe":
        run_transcribe(args.session_dir, args, model_loader)
        return 0

    session_dir = Path(args.out) / f"{now():%y_%m%d_%H%M}_{args.mode}"
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
