"""Turn a song analysis into a chart: the notes to play, and when they land.

Like a rhythm-game chart, each note has an *arrival* time: the moment it
reaches the paddle, which is placed on the music (a beat or subdivision). Notes
appear one travel time earlier at the left edge, so what the player does lines
up with what they hear.

Both clients play charts: the desktop rules in ``world.py`` and the browser
version in ``web/game.js`` (the server sends charts as JSON).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .analysis import SongAnalysis
from .config import Difficulty

FIRST_NOTE_AT = 0.3  # seconds; nothing before this
MIN_COUNT_IN = 1.0  # seconds of count-in before the music starts, at least

# A grid point is used if its onset strength is at least this quantile of the
# strengths at its level, so the busiest beats survive and weak ones drop out.
LEVEL_QUANTILE = {0: 0.25, 1: 0.55, 2: 0.70}


@dataclass(frozen=True)
class ChartNote:
    t: float  # arrival time at the paddle, seconds into the song
    pitch: float  # 0..1, decides the height
    kind: str = "dodge"
    strength: float = 0.5  # 0..1, how hard the music hits here
    level: int = 0  # 0 = on the beat, 1 = half beat, 2 = quarter beat


@dataclass(frozen=True)
class Chart:
    notes: list[ChartNote]
    beats: list[float]
    duration: float
    speed: float  # px/s
    travel_time: float  # seconds from appearing to reaching the paddle
    count_in: float  # seconds of game time before the music starts

    def to_json(self) -> dict:
        return {
            "notes": [
                {
                    **asdict(n),
                    "t": round(n.t, 4),
                    "pitch": round(n.pitch, 3),
                    "strength": round(n.strength, 3),
                }
                for n in self.notes
            ],
            "beats": [round(b, 4) for b in self.beats],
            "duration": self.duration,
            "speed": self.speed,
            "travel_time": self.travel_time,
            "count_in": self.count_in,
        }


# ---------------------------------------------------------------- the grid


def beat_grid(beats: np.ndarray, duration: float, finest: int) -> list[tuple[float, int]]:
    """Beats and their subdivisions as (time, level) pairs, levels up to ``finest``.

    The grid is extended before the first and after the last detected beat at
    the neighbouring tempo, so intros and outros aren't left empty.
    """
    beats = np.asarray(sorted(float(b) for b in beats if 0 <= b < duration))
    if len(beats) < 2:
        return []
    period = float(np.median(np.diff(beats)))
    if period <= 0:
        return []
    before = np.arange(beats[0] - period, -1e-9, -period)[::-1]
    after = np.arange(beats[-1] + period, duration, period)
    full = np.concatenate([before, beats, after])

    fractions = {0: [0.0], 1: [0.0, 0.5], 2: [0.0, 0.25, 0.5, 0.75]}[min(finest, 2)]
    points: list[tuple[float, int]] = []
    for i, b in enumerate(full):
        step = full[i + 1] - b if i + 1 < len(full) else period
        for f in fractions:
            level = 0 if f == 0 else (1 if f == 0.5 else 2)
            t = b + f * step
            if 0 <= t < duration:
                points.append((float(t), level))
    return points


def _candidates(song: SongAnalysis, difficulty: Difficulty) -> list[tuple[float, int, float]]:
    """(time, level, strength) for every grid point strong enough to hold a note."""
    grid = beat_grid(song.beats, song.duration, difficulty.subdivision)
    if not grid:  # no usable beat: fall back to raw onsets
        return [(float(t), 0, song.strength_at(t)) for t in song.onsets]

    strengths = [song.strength_at(t) for t, _ in grid]
    by_level: dict[int, list[float]] = {}
    for (_, level), s in zip(grid, strengths, strict=True):
        by_level.setdefault(level, []).append(s)
    cutoff = {lvl: float(np.quantile(v, LEVEL_QUANTILE[lvl])) for lvl, v in by_level.items()}
    return [
        (t, level, s) for (t, level), s in zip(grid, strengths, strict=True) if s >= cutoff[level] and s > 0
    ]


def _thin(cands: list[tuple[float, int, float]], min_gap: float) -> list[tuple[float, int, float]]:
    """Enforce a minimum gap, keeping the more important of two close notes."""
    kept: list[tuple[float, int, float]] = []
    for c in sorted(cands):
        if kept and c[0] - kept[-1][0] < min_gap:
            prev = kept[-1]
            # Prefer the coarser level (on the beat), then the stronger hit.
            if (c[1], -c[2]) < (prev[1], -prev[2]):
                kept[-1] = c
            continue
        kept.append(c)
    return kept


def _fill_gaps(
    kept: list[tuple[float, int, float]], grid_beats: list[float], duration: float, max_gap: float
) -> list[tuple[float, int, float]]:
    """Add beats into long silences so there's always something coming."""
    times = [FIRST_NOTE_AT - 1e-9, *[k[0] for k in kept], duration]
    extra = []
    for a, b in zip(times, times[1:], strict=False):
        if b - a <= max_gap:
            continue
        options = [t for t in grid_beats if a + max_gap / 2 <= t <= b - max_gap / 2]
        if not options:  # no beat to use: space evenly
            n = int((b - a) // max_gap)
            options = [a + (b - a) * (i + 1) / (n + 1) for i in range(n)]
        last = a
        for t in options:
            if t - last >= max_gap * 0.9 and b - t >= max_gap * 0.5:
                extra.append((t, 0, 0.0))
                last = t
    return sorted(kept + extra)


# ---------------------------------------------------------------- chart


def build_chart(song: SongAnalysis, difficulty: Difficulty) -> Chart:
    cands = [c for c in _candidates(song, difficulty) if FIRST_NOTE_AT <= c[0] <= song.duration - 0.1]
    kept = _thin(cands, difficulty.min_gap)
    grid_beats = [t for t, lvl in beat_grid(song.beats, song.duration, 0) if lvl == 0]
    kept = _fill_gaps(kept, grid_beats, song.duration - 0.1, difficulty.max_gap)

    notes = [
        ChartNote(t=t, pitch=song.pitch_at(t), kind="dodge", strength=float(np.clip(s, 0, 1)), level=level)
        for t, level, s in kept
    ]
    travel = difficulty.travel_time
    first = notes[0].t if notes else travel
    count_in = max(MIN_COUNT_IN, travel - first + 0.5)
    return Chart(
        notes=notes,
        beats=[float(b) for b in grid_beats],
        duration=song.duration,
        speed=difficulty.speed,
        travel_time=travel,
        count_in=count_in,
    )
