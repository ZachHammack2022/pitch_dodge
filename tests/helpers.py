"""Builders for synthetic songs and charts used across tests."""

import numpy as np

from pitch_dodge.analysis import SongAnalysis
from pitch_dodge.chart import Chart, ChartNote

HOP = 512 / 22050


def make_song(duration=10.0, beats=(), onsets=(), pitch=0.5, strength=None, harmonic=None, percussive=None):
    """A SongAnalysis with flat features. ``strength`` etc. may be callables of time."""
    n = int(duration / HOP) + 1
    t = np.arange(n) * HOP

    def env(spec, default):
        if spec is None:
            return np.full(n, default)
        if callable(spec):
            return np.asarray([spec(x) for x in t], dtype=float)
        return np.full(n, float(spec))

    return SongAnalysis(
        pitch=env(pitch, 0.5) if callable(pitch) else np.full(n, pitch),
        energy=np.full(n, 0.5),
        onsets=np.asarray(onsets, dtype=float),
        hop_seconds=HOP,
        duration=duration,
        beats=np.asarray(beats, dtype=float),
        onset_strength=env(strength, 0.5),
        harmonic_strength=env(harmonic, 0.5),
        percussive_strength=env(percussive, 0.5),
        pitch_class=np.zeros(n, dtype=int),
    )


def make_chart(notes=(), duration=10.0, speed=450.0, count_in=0.0):
    from pitch_dodge.config import NOTE_RADIUS, PADDLE_X

    return Chart(
        notes=[n if isinstance(n, ChartNote) else ChartNote(*n) for n in notes],
        beats=[],
        duration=duration,
        speed=speed,
        travel_time=(PADDLE_X + NOTE_RADIUS) / speed,
        count_in=count_in,
    )
