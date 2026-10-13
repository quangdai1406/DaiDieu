"""Local transcription: one Whisper pass per track, merged into a labeled transcript.

Because the user wears headphones, the mic track holds only their voice and the
loopback track holds everyone else, so the track gives the speaker label.
"""

from dataclasses import dataclass, replace
from pathlib import Path


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
    """Join consecutive segments of the same speaker that are close together."""
    out = []
    for s in segments:
        if out and out[-1].speaker == s.speaker and s.start - out[-1].end <= max_gap:
            out[-1] = replace(out[-1], end=max(out[-1].end, s.end), text=f"{out[-1].text} {s.text}")
        else:
            out.append(s)
    return out


def to_txt(segments):
    return "".join(f"[{format_clock(s.start)}] {s.speaker}: {s.text}\n" for s in segments)


def to_srt(segments):
    blocks = []
    for i, s in enumerate(segments, 1):
        blocks.append(f"{i}\n{format_srt_time(s.start)} --> {format_srt_time(s.end)}\n"
                      f"{s.speaker}: {s.text}\n\n")
    return "".join(blocks)


def load_model(name="base.en", device="cpu", compute_type="int8"):
    """Load a faster-whisper model (imported lazily: it is an optional dependency)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit("Transcription needs faster-whisper: pip install faster-whisper") from exc
    return WhisperModel(name, device=device, compute_type=compute_type)


def transcribe_track(model, wav_path, speaker, language="en"):
    segments, _info = model.transcribe(str(wav_path), language=language, vad_filter=True)
    return [Segment(s.start, s.end, speaker, s.text.strip()) for s in segments if s.text.strip()]


def write_transcripts(model, session_dir, speakers, language="en"):
    """Transcribe ``{track name: speaker label}`` found in ``session_dir``.

    Writes ``transcript.txt`` and ``transcript.srt`` and returns their paths.
    """
    session_dir = Path(session_dir)
    per_track = []
    for track, speaker in speakers.items():
        wav = session_dir / f"{track}.wav"
        if wav.exists():
            per_track.append(transcribe_track(model, wav, speaker, language))
    segments = coalesce(merge_segments(*per_track))
    txt, srt = session_dir / "transcript.txt", session_dir / "transcript.srt"
    txt.write_text(to_txt(segments), encoding="utf-8")
    srt.write_text(to_srt(segments), encoding="utf-8")
    return txt, srt
