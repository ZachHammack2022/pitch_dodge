"""Turn an audio file into the data the game plays from.

What the game takes from a song:

* a pitch curve, normalised to 0..1, that decides how high each note is;
* the beat (tempo and beat times), which notes are snapped to;
* onset strength, overall and split into harmonic (melody, chords) and
  percussive (drums) parts, which decides where notes go and what kind;
* the dominant pitch class over time, so sound effects can play in key;
* a loudness envelope, for visuals and to scale intensity.

Analysis takes several seconds, so results are cached on disk keyed by the
file's contents.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
HOP_LENGTH = 512
FMIN = 65.0  # ~C2
FMAX = 1000.0  # ~B5
CACHE_VERSION = 2


@dataclass(frozen=True)
class SongAnalysis:
    """Per-frame features of a song. Frame ``i`` starts at ``i * hop_seconds``."""

    pitch: np.ndarray  # normalised 0 (low) .. 1 (high), no gaps
    energy: np.ndarray  # normalised 0 (quiet) .. 1 (loud)
    onsets: np.ndarray  # seconds, ascending
    hop_seconds: float
    duration: float
    beats: np.ndarray = field(default_factory=lambda: np.zeros(0))  # seconds, ascending
    onset_strength: np.ndarray = field(default_factory=lambda: np.zeros(0))  # 0..1 per frame
    harmonic_strength: np.ndarray = field(default_factory=lambda: np.zeros(0))  # 0..1 per frame
    percussive_strength: np.ndarray = field(default_factory=lambda: np.zeros(0))  # 0..1 per frame
    pitch_class: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))  # 0 = C .. 11 = B

    def _frame(self, t: float) -> int:
        i = int(t / self.hop_seconds)
        return min(max(i, 0), len(self.pitch) - 1)

    def pitch_at(self, t: float) -> float:
        return float(self.pitch[self._frame(t)])

    def energy_at(self, t: float) -> float:
        return float(self.energy[self._frame(t)])

    def pitch_class_at(self, t: float) -> int:
        if len(self.pitch_class) == 0:
            return 0
        return int(self.pitch_class[min(self._frame(t), len(self.pitch_class) - 1)])

    def strength_at(self, t: float, which: str = "onset", window: float = 0.05) -> float:
        """Peak onset strength within ``window`` seconds of ``t`` (which: onset/harmonic/percussive)."""
        env = getattr(self, f"{which}_strength")
        if len(env) == 0:
            return 0.0
        lo = min(max(int((t - window) / self.hop_seconds), 0), len(env) - 1)
        hi = min(max(int((t + window) / self.hop_seconds) + 1, lo + 1), len(env))
        return float(env[lo:hi].max())


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


Progress = Callable[[float], None]  # called with 0..1 as analysis goes on


def _noop(_: float) -> None:
    pass


def analyse_signal(y: np.ndarray, sr: int = SAMPLE_RATE, progress: Progress = _noop) -> SongAnalysis:
    """Extract pitch, energy and onsets from a mono signal."""
    import librosa

    y = np.asarray(y, dtype=np.float32)
    if len(y) < HOP_LENGTH * 4:
        raise ValueError("Audio is too short to play (needs at least a fraction of a second).")

    progress(0.12)
    pitches, mags = librosa.piptrack(y=y, sr=sr, fmin=FMIN, fmax=FMAX, hop_length=HOP_LENGTH)
    strongest = mags.argmax(axis=0)
    cols = np.arange(pitches.shape[1])
    hz = pitches[strongest, cols]
    mag = mags[strongest, cols]
    # Quiet frames give junk readings; treat them as unvoiced.
    voiced = (hz > 0) & (mag > np.percentile(mag, 25))
    pitch = normalise_pitch(np.where(voiced, hz, np.nan))

    progress(0.3)
    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]
    n = min(len(pitch), len(rms))
    energy = normalise_energy(rms[:n])

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=HOP_LENGTH, units="time")
    progress(0.38)
    _, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=HOP_LENGTH, units="time")

    # Split into harmonic (sustained: melody, chords) and percussive (drums) parts.
    progress(0.45)
    stft = librosa.stft(y, hop_length=HOP_LENGTH)
    harmonic, percussive = librosa.decompose.hpss(stft)
    progress(0.88)
    harm_env = librosa.onset.onset_strength(
        S=librosa.amplitude_to_db(np.abs(harmonic), ref=np.max), sr=sr, hop_length=HOP_LENGTH
    )
    perc_env = librosa.onset.onset_strength(
        S=librosa.amplitude_to_db(np.abs(percussive), ref=np.max), sr=sr, hop_length=HOP_LENGTH
    )
    progress(0.95)
    chroma = librosa.feature.chroma_stft(S=np.abs(harmonic) ** 2, sr=sr, hop_length=HOP_LENGTH)
    pitch_class = chroma.argmax(axis=0)

    def fit(a):
        a = np.asarray(a, dtype=float)[:n]
        return np.pad(a, (0, n - len(a)), mode="edge") if 0 < len(a) < n else a

    return SongAnalysis(
        pitch=pitch[:n],
        energy=energy,
        onsets=np.asarray(onsets, dtype=float),
        hop_seconds=HOP_LENGTH / sr,
        duration=len(y) / sr,
        beats=np.asarray(beats, dtype=float),
        onset_strength=normalise_energy(fit(onset_env)),
        harmonic_strength=normalise_energy(fit(harm_env)),
        percussive_strength=normalise_energy(fit(perc_env)),
        pitch_class=fit(pitch_class).astype(int),
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


def cache_path(path: str | os.PathLike, cache_dir: Path | None = None) -> Path:
    return (cache_dir or default_cache_dir()) / f"{_file_digest(Path(path))}.npz"


def is_cached(path: str | os.PathLike, cache_dir: Path | None = None) -> bool:
    return not os.environ.get("PITCH_DODGE_NO_CACHE") and cache_path(path, cache_dir).exists()


def analyse_file(
    path: str | os.PathLike, cache_dir: Path | None = None, progress: Progress = _noop
) -> SongAnalysis:
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
        cache_file = cache_path(path, cache_dir)
        if cache_file.exists():
            try:
                with np.load(cache_file) as data:
                    values = {f.name: data[f.name] for f in fields(SongAnalysis)}
                values["hop_seconds"] = float(values["hop_seconds"])
                values["duration"] = float(values["duration"])
                return SongAnalysis(**values)
            except (OSError, KeyError, ValueError):
                pass  # corrupt or stale; re-analyse

    import librosa

    progress(0.02)
    y, sr = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    result = analyse_signal(y, sr, progress)

    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            np.savez(cache_file, **{f.name: getattr(result, f.name) for f in fields(SongAnalysis)})
        except OSError:
            pass  # caching is best-effort
    return result
