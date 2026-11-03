"""Game rules, with no pygame in sight so they can be unit tested.

Projectiles ("notes") are fired from the left edge at the height of the song's
current pitch, on the song's onsets. The player's paddle sits near the right
edge; every note that gets past it without touching it scores, and every note
that hits costs a life.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

from .analysis import SongAnalysis

WIDTH = 960
HEIGHT = 600
TOP_MARGIN = 56  # room for the HUD
SPAWN_MARGIN = 30


@dataclass(frozen=True)
class Difficulty:
    name: str
    lives: int
    base_speed: float  # px/s at the start of the song
    speed_growth: float  # extra fraction of base speed by the end of the song
    start_gap: float  # min seconds between notes at the start
    end_gap: float  # ...and at the end
    max_gap: float  # never leave the player idle longer than this
    vy_spread: float  # max vertical speed, px/s
    paddle_height: int


DIFFICULTIES = {
    "easy": Difficulty("easy", 5, 300, 0.5, 0.55, 0.30, 1.2, 60, 64),
    "normal": Difficulty("normal", 3, 360, 0.8, 0.40, 0.18, 0.9, 110, 72),
    "hard": Difficulty("hard", 2, 420, 1.1, 0.28, 0.10, 0.6, 170, 80),
}

PADDLE_WIDTH = 14
PADDLE_X = WIDTH - 110
PADDLE_SPEED = 560.0  # px/s
NOTE_RADIUS = 9
INVULNERABLE_FOR = 1.2  # seconds after a hit
NEAR_MISS_DISTANCE = 18  # px between note edge and paddle edge
POINTS_DODGE = 10
POINTS_NEAR_MISS = 15
STREAK_PER_LEVEL = 10
MAX_MULTIPLIER = 8
POINTS_PER_LIFE_LEFT = 250
MAX_STEP = 1 / 120  # seconds of note movement per collision check


def build_spawn_schedule(
    onsets: np.ndarray, duration: float, difficulty: Difficulty, lead_in: float = 1.0
) -> list[float]:
    """Pick the song times at which notes are fired.

    Onsets are thinned so notes are never closer than the current minimum gap
    (which shrinks as the song goes on), and long quiet stretches are filled so
    there's always something coming.
    """
    if duration <= 0:
        return []

    def min_gap(t: float) -> float:
        p = min(max(t / duration, 0.0), 1.0)
        return difficulty.start_gap + (difficulty.end_gap - difficulty.start_gap) * p

    times: list[float] = []
    last = lead_in - difficulty.max_gap  # allows a note right at lead_in
    for t in sorted(float(o) for o in onsets):
        if t < lead_in or t >= duration:
            continue
        while t - last > difficulty.max_gap:  # fill a long gap
            last += difficulty.max_gap
            if last >= lead_in:
                times.append(last)
        if t - last >= min_gap(t):
            times.append(t)
            last = t
    while duration - last > difficulty.max_gap:  # fill the tail
        last += difficulty.max_gap
        if last < duration:
            times.append(last)
    return times


def pitch_to_y(pitch: float) -> float:
    """0 (low) is the bottom of the play area, 1 (high) the top."""
    top = TOP_MARGIN + SPAWN_MARGIN
    bottom = HEIGHT - SPAWN_MARGIN
    return bottom - min(max(pitch, 0.0), 1.0) * (bottom - top)


@dataclass
class Note:
    x: float
    y: float
    vx: float
    vy: float
    pitch: float
    radius: float = NOTE_RADIUS
    passed: bool = False
    hit: bool = False
    ghosted: bool = False  # went through the paddle while it was invulnerable
    closest_gap: float = float("inf")


@dataclass
class Paddle:
    y: float
    height: int
    x: float = PADDLE_X
    width: int = PADDLE_WIDTH

    @property
    def top(self) -> float:
        return self.y - self.height / 2

    @property
    def bottom(self) -> float:
        return self.y + self.height / 2

    def move(self, direction: float, dt: float) -> None:
        self.y += direction * PADDLE_SPEED * dt
        lo = TOP_MARGIN + self.height / 2
        hi = HEIGHT - self.height / 2
        self.y = min(max(self.y, lo), hi)

    def distance_to(self, note: Note) -> float:
        """Gap between the note's edge and the paddle (negative = overlapping)."""
        cx = min(max(note.x, self.x), self.x + self.width)
        cy = min(max(note.y, self.top), self.bottom)
        return float(np.hypot(note.x - cx, note.y - cy)) - note.radius


@dataclass
class Event:
    kind: str  # "spawn" | "dodge" | "near_miss" | "hit" | "level_up" | "game_over" | "cleared"
    x: float = 0.0
    y: float = 0.0
    value: int = 0


@dataclass
class World:
    song: SongAnalysis
    difficulty: Difficulty
    seed: int | None = None

    notes: list[Note] = field(default_factory=list)
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    dodged: int = 0
    hits: int = 0
    song_time: float = 0.0
    invulnerable_until: float = -1.0
    over: bool = False
    cleared: bool = False

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.lives = self.difficulty.lives
        self.paddle = Paddle(y=(TOP_MARGIN + HEIGHT) / 2, height=self.difficulty.paddle_height)
        self.schedule = build_spawn_schedule(self.song.onsets, self.song.duration, self.difficulty)
        self._next_spawn = 0

    # ------------------------------------------------------------ queries

    @property
    def progress(self) -> float:
        if self.song.duration <= 0:
            return 1.0
        return min(max(self.song_time / self.song.duration, 0.0), 1.0)

    @property
    def multiplier(self) -> int:
        return min(1 + self.streak // STREAK_PER_LEVEL, MAX_MULTIPLIER)

    @property
    def invulnerable(self) -> bool:
        return self.song_time < self.invulnerable_until

    @property
    def speed(self) -> float:
        d = self.difficulty
        return d.base_speed * (1 + d.speed_growth * self.progress)

    # ------------------------------------------------------------ update

    def update(self, song_time: float, dt: float, direction: float) -> list[Event]:
        """Advance the world to ``song_time``; ``direction`` is -1 (up), 0 or 1 (down)."""
        events: list[Event] = []
        if self.over or self.cleared:
            return events
        self.song_time = song_time
        self.paddle.move(direction, dt)

        while self._next_spawn < len(self.schedule) and self.schedule[self._next_spawn] <= song_time:
            t = self.schedule[self._next_spawn]
            self._next_spawn += 1
            self._spawn(t, events)

        # Sub-step so fast notes can't tunnel through the paddle on a slow frame.
        steps = max(1, math.ceil(dt / MAX_STEP))
        for _ in range(steps):
            for note in self.notes:
                self._step(note, dt / steps, events)
                if self.over:
                    return events

        self.notes = [n for n in self.notes if not n.hit and n.x - n.radius < WIDTH]

        if song_time >= self.song.duration and self._next_spawn >= len(self.schedule) and not self.notes:
            self.cleared = True
            bonus = self.lives * POINTS_PER_LIFE_LEFT
            self.score += bonus
            events.append(Event("cleared", value=bonus))
        return events

    def _spawn(self, t: float, events: list[Event]) -> None:
        pitch = self.song.pitch_at(t)
        y = pitch_to_y(pitch)
        speed = self.speed * self.rng.uniform(0.85, 1.15)
        vy = self.rng.uniform(-1, 1) * self.difficulty.vy_spread * (0.5 + self.progress)
        self.notes.append(Note(x=-NOTE_RADIUS, y=y, vx=speed, vy=vy, pitch=pitch))
        events.append(Event("spawn", 0, y))

    def _step(self, note: Note, dt: float, events: list[Event]) -> None:
        note.x += note.vx * dt
        note.y += note.vy * dt
        top, bottom = TOP_MARGIN + note.radius, HEIGHT - note.radius
        if note.y < top:
            note.y, note.vy = 2 * top - note.y, abs(note.vy)
        elif note.y > bottom:
            note.y, note.vy = 2 * bottom - note.y, -abs(note.vy)

        if note.passed:
            return

        gap = self.paddle.distance_to(note)
        if gap < 0 and self.invulnerable:
            note.ghosted = True
        elif gap < 0:
            note.hit = True
            note.passed = True
            self.hits += 1
            self.lives -= 1
            self.streak = 0
            self.invulnerable_until = self.song_time + INVULNERABLE_FOR
            events.append(Event("hit", note.x, note.y, self.lives))
            if self.lives <= 0:
                self.over = True
                events.append(Event("game_over", value=self.score))
            return

        if note.x - note.radius > self.paddle.x + self.paddle.width:
            note.passed = True
            if note.ghosted:
                return
            old_level = self.multiplier
            self.dodged += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            near = note.closest_gap < NEAR_MISS_DISTANCE
            points = (POINTS_NEAR_MISS if near else POINTS_DODGE) * old_level
            self.score += points
            events.append(Event("near_miss" if near else "dodge", note.x, note.y, points))
            if self.multiplier > old_level:
                events.append(Event("level_up", note.x, note.y, self.multiplier))
            return

        # Remember how close the note came, for the near-miss bonus.
        note.closest_gap = min(note.closest_gap, gap)
