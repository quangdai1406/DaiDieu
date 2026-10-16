"""Block-wise mixing of WAV files, so long recordings never load fully into RAM."""

from pathlib import Path

import numpy as np
import soundfile as sf


def _mono_block(handle, frames):
    data = handle.read(frames, dtype="float32", always_2d=True)
    return data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]


def mix_wavs(inputs, out_path, blocksize=65536):
    """Mix ``[(path, gain), ...]`` into one mono 16-bit WAV.

    Inputs must share a sample rate. Shorter inputs are padded with silence,
    and the sum is hard-clipped to [-1, 1]. Missing files are skipped.
    """
    present = [(Path(p), g) for p, g in inputs if Path(p).exists()]
    if not present:
        raise FileNotFoundError("no input files to mix")
    handles = [(sf.SoundFile(str(p)), g) for p, g in present]
    try:
        rates = {h.samplerate for h, _ in handles}
        if len(rates) != 1:
            raise ValueError(f"sample rates differ: {sorted(rates)}")
        rate = rates.pop()
        total = max(h.frames for h, _ in handles)
        with sf.SoundFile(str(out_path), mode="w", samplerate=rate, channels=1,
                          format="WAV", subtype="PCM_16") as out:
            done = 0
            while done < total:
                n = min(blocksize, total - done)
                mix = np.zeros(n, dtype=np.float32)
                for handle, gain in handles:
                    block = _mono_block(handle, n)
                    mix[: len(block)] += block * gain
                out.write(np.clip(mix, -1.0, 1.0))
                done += n
    finally:
        for handle, _ in handles:
            handle.close()
    return Path(out_path)


def export_mp3(wav_path, mp3_path, blocksize=65536):
    """Convert a mono WAV to MP3 (about 10x smaller; Word's Transcribe accepts it)."""
    with sf.SoundFile(str(wav_path)) as src, sf.SoundFile(
            str(mp3_path), mode="w", samplerate=src.samplerate, channels=1, format="MP3",
            bitrate_mode="VARIABLE", compression_level=0.2) as dst:
        while True:
            block = _mono_block(src, blocksize)
            if len(block) == 0:
                break
            dst.write(block)
    return Path(mp3_path)
