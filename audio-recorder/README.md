# audio-recorder

Records your **speakers** (what you hear) and your **microphone** (your voice) at the same
time, for meetings or karaoke. Windows 10/11, Python 3.10+.

Built for the headphones case: your mic hears only you, and the speaker loopback hears
everyone else. The two tracks stay separate, so the transcript can label **Me** and
**Others** without any speaker-detection model.

## Install (Windows)

```powershell
cd audio-recorder
python -m venv .venv ; .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-transcribe.txt   # only for local transcription (optional)
```

## The simple window

```powershell
.\.venv\Scripts\python -m recorder gui
```

Or double-click `start-recorder.bat`. Four buttons: **Record**, **Stop**, **Save**, **Transcribe**.

- **Record** starts a meeting recording with your default mic and speakers, with a timer and
  live level bars. Recordings are written to `recordings\` as they happen.
- **Stop** finishes the files. **Save** copies the recording to a folder and name you choose
  (and can add a small `mix.mp3`). **Transcribe** shows a "Me" / "Others" transcript in the
  window and saves `transcript.txt` and `transcript.srt` next to the recording.
- **Transcribe an audio file...** (the wide button under the four) lets you pick any audio or
  video file, such as a phone voice memo (`.m4a`, `.mp3`, `.wav`, `.mp4`...). The transcript is
  saved next to that file as `<name>.transcript.txt` and `<name>.transcript.srt`, and shown in
  the window. An earlier transcript is never overwritten (you get `_2`, `_3`...). It does not
  touch the recording you are working on.
- Transcription needs `pip install -r requirements-transcribe.txt`. The first run downloads
  the speech model, so it needs internet and can take a few minutes.
- Closing the window while recording stops and saves the recording first.

## Use (command line)

```powershell
python -m recorder devices                   # list mics and loopback devices
python -m recorder record                    # meeting mode, default devices
python -m recorder record --mic 12 --loopback 15
python -m recorder record --mp3              # also save a small mix.mp3
python -m recorder record --transcribe       # transcribe locally after you stop
python -m recorder record --mode karaoke --mic-gain 1.2 --music-gain 0.8
python -m recorder transcribe recordings\26_1013_0905_meeting
python -m recorder transcribe "C:\path\to\Voice 261013_093023.m4a"   # any audio file
```

Stop with **Ctrl+C**. Each run makes a folder `recordings\YY_MMDD_HHMM_<mode>\`:

| Mode | Files |
|---|---|
| `meeting` | `me.wav`, `others.wav`, `mix.wav` (+ `mix.mp3`, `transcript.txt`, `transcript.srt` if asked) |
| `karaoke` | `mix.wav` only (add `--keep-tracks` to keep `voice.wav` and `music.wav`) |

All files are mono, 16-bit, 48 kHz by default (`--sample-rate` to change).

## Transcribe with Microsoft 365 (no local model needed)

In Word: **Home > Dictate (arrow) > Transcribe > Upload audio**, then pick `mix.wav` or `mix.mp3`.
A WAV is about 345 MB per hour; use `--mp3` for long meetings. Check Microsoft's current
file size and length limits. Word detects speakers itself; for exact Me/Others labels use
the local transcript instead.

## Local transcription (optional)

Uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper), fully offline. It runs
once per track, then the results are merged by time into `transcript.txt` / `.srt`.

Defaults are `--model base.en --device cpu --compute-type int8`, chosen for a laptop GPU
like the GeForce 940M (2 GB, old architecture; modern CUDA builds may not support it).
Use `--model small.en` for better accuracy, slower. `--device cuda` is available on newer GPUs.

Transcribing a file has no speaker labels, because one file is one track. On a CPU, a long
file can take about as long as the audio itself.

If Transcribe fails with `open() got an unexpected keyword argument 'metadata_errors'`, run
`pip install "av<19"`: the newest `av` release removed an option faster-whisper still uses.

## Check your setup, and use an NVIDIA GPU

```powershell
python -m recorder check
```

Tests the speech model on the processor and on the GPU, each in its own process, so a crash
inside a library is reported instead of closing the program silently. It prints which one
works and the command to use. The first run downloads the small `tiny.en` model.

To use an NVIDIA GPU on Windows:

1. `nvidia-smi` shows your GPU, its memory and the driver version. Use a recent driver.
2. `pip install -r requirements-gpu.txt` installs the CUDA 12 libraries (cuBLAS and cuDNN).
   The program finds them by itself; you do not need to edit `PATH`.
3. `python -m recorder check`: the `cuda` line should say `OK`.
4. `python -m recorder gui --device cuda --model small.en` (the same options work with
   `record --transcribe` and `transcribe`). The window title shows the model and device in use.

Bigger models are more accurate but need more video memory. Try `small.en`, then `medium.en`.
The largest models need roughly 5 GB. If the GPU fails, add `--device cpu` (the default).

## How sync works

All chunks are stamped with one monotonic clock. Each track is written at its stamped
position, so the tracks start together and stay the same length. Windows sends no
loopback data while nothing is playing, and those gaps are filled with silence.
Sources at different sample rates are converted to the session rate.

## Limitations

- **Real capture is untested.** The code that talks to PyAudioWPatch was only tested
  against a fake module on Linux. Run `devices`, then a 10-second `record`, and check
  both tracks play before relying on it.
- No continuous clock-drift correction: small timing jumps (over 50 ms) are repaired,
  but slow drift between two devices is not resampled away.
- Resampling is linear interpolation. It is fine between 44.1 and 48 kHz; do not use a
  low `--sample-rate` (such as 16000) when you care about quality.
- Meeting mode records other people. Tell participants and follow local consent law.
- The window has no device pickers or settings: it always uses your default devices (use the command line for `--mic` / `--loopback`), and it records in meeting mode.
- On the command line, stop with Ctrl+C.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```
