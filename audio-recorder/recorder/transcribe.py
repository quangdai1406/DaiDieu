
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path


SPEAKERS = {"me": "Me", "others": "Others"}


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: str
    text: str


def format_clock(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def format_srt_time(seconds):
    millis = int(seconds * 1000)
    return f"{format_clock(millis / 1000)},{millis % 1000:03d}"


def merge_segments(*segment_lists):
    merged = [s for segments in segment_lists for s in segments]
    return sorted(merged, key=lambda s: (s.start, s.end))


def coalesce(segments, max_gap=1.5):
    out = []
    for s in segments:
        if out and out[-1].speaker == s.speaker and s.start - out[-1].end <= max_gap:
            out[-1] = replace(out[-1], end=max(out[-1].end, s.end), text=f"{out[-1].text} {s.text}")
        else:
            out.append(s)
    return out


def _label(segment):
    return f"{segment.speaker}: " if segment.speaker else ""


def to_txt(segments):
    return "".join(f"[{format_clock(s.start)}] {_label(s)}{s.text}\n" for s in segments)


def to_srt(segments):
    blocks = []
    for i, s in enumerate(segments, 1):
        blocks.append(f"{i}\n{format_srt_time(s.start)} --> {format_srt_time(s.end)}\n"
                      f"{_label(s)}{s.text}\n\n")
    return "".join(blocks)


GPU_HINT = ("For the GPU, run: pip install -r requirements-gpu.txt (and update your NVIDIA driver), "
            "or use the processor instead with --device cpu.")


def resolve_compute_type(device, compute_type):
    if compute_type:
        return compute_type
    return "int8" if device == "cpu" else "auto"


def add_nvidia_dll_dirs(search_paths=None):
    found = []
    for base in (sys.path if search_paths is None else search_paths):
        nvidia = Path(base) / "nvidia" if base else None
        if nvidia is None or not nvidia.is_dir():
            continue
        for bin_dir in sorted(nvidia.glob("*/bin")):
            if bin_dir.is_dir() and str(bin_dir) not in found:
                found.append(str(bin_dir))
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for folder in found:
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(folder)
            except OSError:
                pass
        if folder not in parts:
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            parts.insert(0, folder)
    return found


def explain_error(error):
    if isinstance(error, SystemExit):
        return str(error)
    text = f"Transcription failed: {error}"
    if any(word in str(error).lower() for word in ("cublas", "cudnn", "cuda")):
        text += " " + GPU_HINT
    return text


def load_model(name="base.en", device="cpu", compute_type=None):
    if device != "cpu":
        add_nvidia_dll_dirs()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit("Transcription needs faster-whisper: pip install faster-whisper") from exc
    return WhisperModel(name, device=device, compute_type=resolve_compute_type(device, compute_type))


def transcribe_track(model, wav_path, speaker, language="en", on_progress=None):
    segments, info = model.transcribe(str(wav_path), language=language, vad_filter=True)
    total = getattr(info, "duration", None)
    out = []
    for s in segments:
        if s.text.strip():
            out.append(Segment(s.start, s.end, speaker, s.text.strip()))
        if on_progress:
            on_progress(s.end, total)
    return out


def write_transcripts(model, session_dir, speakers, language="en", on_progress=None):
    session_dir = Path(session_dir)
    per_track = []
    for track, speaker in speakers.items():
        wav = session_dir / f"{track}.wav"
        if wav.exists():
            per_track.append(transcribe_track(model, wav, speaker, language, on_progress))
    segments = coalesce(merge_segments(*per_track))
    txt, srt = session_dir / "transcript.txt", session_dir / "transcript.srt"
    txt.write_text(to_txt(segments), encoding="utf-8")
    srt.write_text(to_srt(segments), encoding="utf-8")
    return txt, srt


def _free_output_pair(audio_path):
    n = 1
    while True:
        tag = "" if n == 1 else f"_{n}"
        txt = audio_path.with_name(f"{audio_path.stem}.transcript{tag}.txt")
        srt = audio_path.with_name(f"{audio_path.stem}.transcript{tag}.srt")
        if not txt.exists() and not srt.exists():
            return txt, srt
        n += 1


def transcribe_file(model, audio_path, language="en", on_progress=None):
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"File not found: {audio_path}")
    segments = coalesce(transcribe_track(model, audio_path, "", language, on_progress))
    txt, srt = _free_output_pair(audio_path)
    txt.write_text(to_txt(segments), encoding="utf-8")
    srt.write_text(to_srt(segments), encoding="utf-8")
    return txt, srt
