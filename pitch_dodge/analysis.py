"""Turn an audio file into the data the game plays from.

The game needs three things from a song:

* a pitch curve, normalised to 0..1, that decides how high each projectile
  spawns;
* onset times (drum hits, plucked notes...) that decide *when* projectiles
  spawn, so the attack follows the music instead of a fixed timer;
* a loudness envelope, used to make the background pulse.

Analysis takes a few seconds, so results are cached on disk keyed by the file's
contents.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
HOP_LENGTH = 512
FMIN = 65.0  # ~C2
FMAX = 1000.0  # ~B5
CACHE_VERSION = 1


@dataclass(frozen=True)
class SongAnalysis:
    """Per-frame features of a song. Frame ``i`` starts at ``i * hop_seconds``."""

    pitch: np.ndarray  # normalised 0 (low) .. 1 (high), no gaps
    energy: np.ndarray  # normalised 0 (quiet) .. 1 (loud)
    onsets: np.ndarray  # seconds, ascending
    hop_seconds: float
    duration: float

    def _frame(self, t: float) -> int:
        i = int(t / self.hop_seconds)
        return min(max(i, 0), len(self.pitch) - 1)

    def pitch_at(self, t: float) -> float:
        return float(self.pitch[self._frame(t)])

    def energy_at(self, t: float) -> float:
        return float(self.energy[self._frame(t)])


# ---------------------------------------------------------------- features


def _forward_fill(values: np.ndarray, fallback: float) -> np.ndarray:
    """Replace NaNs with the last valid value (leading NaNs take the first valid one)."""
    out = values.astype(float).copy()
    valid = ~np.isnan(out)
    if not valid.any():
        out[:] = fallback
        return out
    idx = np.where(valid, np.arange(len(out)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = out[idx]
    first = out[np.argmax(valid)]
    out[: np.argmax(valid)] = first
    return out


def _median_smooth(values: np.ndarray, width: int) -> np.ndarray:
    if width <= 1 or len(values) < width:
        return values
    pad = width // 2
    padded = np.pad(values, pad, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, width)
    return np.median(windows, axis=1)


def normalise_pitch(hz: np.ndarray, smooth_frames: int = 9) -> np.ndarray:
    """Map a raw pitch track in Hz (NaN = unvoiced) to a gap-free 0..1 curve.

    Works on a log scale so an octave is the same distance anywhere, and uses
    the 5th/95th percentiles as the range so a few stray readings don't squash
    everything else into a thin band.
    """
    hz = np.asarray(hz, dtype=float)
    hz = np.where(hz > 0, hz, np.nan)
    if np.all(np.isnan(hz)):
        return np.full(len(hz), 0.5)

    log = np.log2(hz)
    log = _forward_fill(log, fallback=0.0)
    log = _median_smooth(log, smooth_frames)

    lo, hi = np.percentile(log, [5, 95])
    if hi - lo < 1e-6:
        return np.full(len(hz), 0.5)
    return np.clip((log - lo) / (hi - lo), 0.0, 1.0)


def normalise_energy(rms: np.ndarray) -> np.ndarray:
    rms = np.asarray(rms, dtype=float)
    peak = np.percentile(rms, 98) if len(rms) else 0.0
    if peak <= 0:
        return np.zeros(len(rms))
    return np.clip(rms / peak, 0.0, 1.0)


def analyse_signal(y: np.ndarray, sr: int = SAMPLE_RATE) -> SongAnalysis:
    """Extract pitch, energy and onsets from a mono signal."""
    import librosa

    y = np.asarray(y, dtype=np.float32)
    if len(y) < HOP_LENGTH * 4:
        raise ValueError("Audio is too short to play (needs at least a fraction of a second).")

    pitches, mags = librosa.piptrack(y=y, sr=sr, fmin=FMIN, fmax=FMAX, hop_length=HOP_LENGTH)
    strongest = mags.argmax(axis=0)
    cols = np.arange(pitches.shape[1])
    hz = pitches[strongest, cols]
    mag = mags[strongest, cols]
    # Quiet frames give junk readings; treat them as unvoiced.
    voiced = (hz > 0) & (mag > np.percentile(mag, 25))
    pitch = normalise_pitch(np.where(voiced, hz, np.nan))

    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]
    n = min(len(pitch), len(rms))
    energy = normalise_energy(rms[:n])

    onsets = librosa.onset.onset_detect(y=y, sr=sr, hop_length=HOP_LENGTH, units="time")

    return SongAnalysis(
        pitch=pitch[:n],
        energy=energy,
        onsets=np.asarray(onsets, dtype=float),
        hop_seconds=HOP_LENGTH / sr,
        duration=len(y) / sr,
    )


# ---------------------------------------------------------------- caching


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "pitch_dodge"


def _file_digest(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update(f"v{CACHE_VERSION}".encode())
    return h.hexdigest()


def analyse_file(path: str | os.PathLike, cache_dir: Path | None = None) -> SongAnalysis:
    """Analyse an audio file (anything librosa can read: wav, mp3, ogg, flac...).

    Pass ``cache_dir=None`` to use the default cache, or a path to use another.
    Set the environment variable ``PITCH_DODGE_NO_CACHE=1`` to skip caching.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    use_cache = not os.environ.get("PITCH_DODGE_NO_CACHE")
    cache_file = None
    if use_cache:
        cache_file = (cache_dir or default_cache_dir()) / f"{_file_digest(path)}.npz"
        if cache_file.exists():
            try:
                with np.load(cache_file) as data:
                    return SongAnalysis(
                        pitch=data["pitch"],
                        energy=data["energy"],
                        onsets=data["onsets"],
                        hop_seconds=float(data["hop_seconds"]),
                        duration=float(data["duration"]),
                    )
            except (OSError, KeyError, ValueError):
                pass  # corrupt or stale; re-analyse

    import librosa

    y, sr = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    result = analyse_signal(y, sr)

    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            np.savez(
                cache_file,
                pitch=result.pitch,
                energy=result.energy,
                onsets=result.onsets,
                hop_seconds=result.hop_seconds,
                duration=result.duration,
            )
        except OSError:
            pass  # caching is best-effort
    return result
