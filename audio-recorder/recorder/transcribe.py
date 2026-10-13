"""Local transcription: one Whisper pass per track, merged into a labeled transcript.

Because the user wears headphones, the mic track holds only their voice and the
loopback track holds everyone else, so the track gives the speaker label.
"""

from dataclasses import dataclass, replace
from pathlib import Path


# track file name -> label used in transcripts
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
    """Join consecutive segments of the same speaker that are close together."""
    out = []
    for s in segments:
        if out and out[-1].speaker == s.speaker and s.start - out[-1].end <= max_gap:
            out[-1] = replace(out[-1], end=max(out[-1].end, s.end), text=f"{out[-1].text} {s.text}")
        else:
            out.append(s)
    return out


def _label(segment):
    # an external file has no known speakers, so its segments carry no label
    return f"{segment.speaker}: " if segment.speaker else ""


def to_txt(segments):
    return "".join(f"[{format_clock(s.start)}] {_label(s)}{s.text}\n" for s in segments)


def to_srt(segments):
    blocks = []
    for i, s in enumerate(segments, 1):
        blocks.append(f"{i}\n{format_srt_time(s.start)} --> {format_srt_time(s.end)}\n"
                      f"{_label(s)}{s.text}\n\n")
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


def _free_output_pair(audio_path):
    """``<name>.transcript.txt/.srt`` beside the audio, or ``_2``, ``_3``... if taken."""
    n = 1
    while True:
        tag = "" if n == 1 else f"_{n}"
        txt = audio_path.with_name(f"{audio_path.stem}.transcript{tag}.txt")
        srt = audio_path.with_name(f"{audio_path.stem}.transcript{tag}.srt")
        if not txt.exists() and not srt.exists():
            return txt, srt
        n += 1


def transcribe_file(model, audio_path, language="en"):
    """Transcribe any audio or video file the Whisper decoder can read (m4a, mp3, wav, mp4...).

    Writes the transcript beside the file and never overwrites an earlier one.
    Returns the ``(txt, srt)`` paths.
    """
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"File not found: {audio_path}")
    segments = coalesce(transcribe_track(model, audio_path, "", language))
    txt, srt = _free_output_pair(audio_path)
    txt.write_text(to_txt(segments), encoding="utf-8")
    srt.write_text(to_srt(segments), encoding="utf-8")
    return txt, srt
