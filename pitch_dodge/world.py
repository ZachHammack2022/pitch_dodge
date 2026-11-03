"""Game rules, with no pygame in sight so they can be unit tested.

The World plays a Chart (see chart.py). Each note's position comes straight
from the song time, ``x = PADDLE_X - (arrival - now) * speed``, so a note
crosses the paddle exactly on its beat however uneven the frame rate is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .chart import Chart, ChartNote
from .config import (  # noqa: F401  (re-exported for older imports)
    DIFFICULTIES,
    HEIGHT,
    NOTE_RADIUS,
    PADDLE_SPEED,
    PADDLE_WIDTH,
    PADDLE_X,
    SPAWN_MARGIN,
    TOP_MARGIN,
    WIDTH,
    Difficulty,
    pitch_to_y,
)

INVULNERABLE_FOR = 1.0  # seconds after a hit
NEAR_MISS_DISTANCE = 18  # px between note edge and paddle edge
POINTS_DODGE = 10
POINTS_NEAR_MISS = 15
STREAK_PER_LEVEL = 10
MAX_MULTIPLIER = 8
POINTS_PER_LIFE_LEFT = 250


@dataclass
class Note:
    t: float  # arrival time
    y: float
    pitch: float
    kind: str
    strength: float = 0.5
    midi: int = 72
    x: float = -NOTE_RADIUS
    vx: float = 0.0
    radius: float = NOTE_RADIUS
    passed: bool = False
    hit: bool = False
    ghosted: bool = False  # went through the paddle while it was invulnerable
    closest_gap: float = float("inf")

    @classmethod
    def from_chart(cls, n: ChartNote, speed: float) -> Note:
        radius = NOTE_RADIUS * (0.85 + 0.4 * n.strength)
        return cls(
            t=n.t,
            midi=n.midi,
            y=pitch_to_y(n.pitch),
            pitch=n.pitch,
            kind=n.kind,
            strength=n.strength,
            vx=speed,
            radius=radius,
        )


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

    def gap_y(self, note: Note) -> float:
        """Vertical gap between the note's edge and the paddle (negative = overlapping)."""
        return max(self.top - note.y, note.y - self.bottom, 0.0) - note.radius


@dataclass
class Event:
    kind: str  # "spawn" | "dodge" | "near_miss" | "hit" | "level_up" | "game_over" | "cleared"
    x: float = 0.0
    y: float = 0.0
    value: int = 0
    midi: int = 0  # for sounds that should play in key


@dataclass
class World:
    chart: Chart
    difficulty: Difficulty
    seed: int | None = None  # unused: charts are deterministic

    notes: list[Note] = field(default_factory=list)
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    dodged: int = 0
    hits: int = 0
    song_time: float = 0.0
    invulnerable_until: float = -1e9
    over: bool = False
    cleared: bool = False

    def __post_init__(self) -> None:
        self.lives = self.difficulty.lives
        self.paddle = Paddle(y=(TOP_MARGIN + HEIGHT) / 2, height=self.difficulty.paddle_height)
        self.song_time = -self.chart.count_in
        self._next = 0

    # ------------------------------------------------------------ queries

    @property
    def duration(self) -> float:
        return self.chart.duration

    @property
    def progress(self) -> float:
        if self.duration <= 0:
            return 1.0
        return min(max(self.song_time / self.duration, 0.0), 1.0)

    @property
    def multiplier(self) -> int:
        return min(1 + self.streak // STREAK_PER_LEVEL, MAX_MULTIPLIER)

    @property
    def invulnerable(self) -> bool:
        return self.song_time < self.invulnerable_until

    @property
    def speed(self) -> float:
        return self.chart.speed

    def x_at(self, note_t: float, now: float) -> float:
        return PADDLE_X - (note_t - now) * self.chart.speed

    def skip_to(self, song_time: float) -> None:
        """Jump ahead without playing (for demos): notes due before then are dropped."""
        while self._next < len(self.chart.notes) and self.chart.notes[self._next].t < song_time:
            self._next += 1
        self.song_time = song_time

    # ------------------------------------------------------------ update

    def update(self, song_time: float, dt: float, direction: float) -> list[Event]:
        """Advance to ``song_time``; ``direction`` is -1 (up), 0 or 1 (down)."""
        events: list[Event] = []
        if self.over or self.cleared:
            return events
        prev = self.song_time
        self.song_time = song_time
        self.paddle.move(direction, dt)

        travel = self.chart.travel_time
        chart_notes = self.chart.notes
        while self._next < len(chart_notes) and chart_notes[self._next].t - travel <= song_time:
            n = Note.from_chart(chart_notes[self._next], self.chart.speed)
            self._next += 1
            self.notes.append(n)
            events.append(Event("spawn", 0, n.y))

        for note in self.notes:
            self._step(note, prev, song_time, events)
            if self.over:
                return events

        self.notes = [n for n in self.notes if not n.hit and n.x - n.radius < WIDTH]

        if song_time >= self.duration and self._next >= len(chart_notes) and not self.notes:
            self.cleared = True
            bonus = self.lives * POINTS_PER_LIFE_LEFT
            self.score += bonus
            events.append(Event("cleared", value=bonus))
        return events

    def _step(self, note: Note, prev: float, now: float, events: list[Event]) -> None:
        x_prev = self.x_at(note.t, prev)
        note.x = self.x_at(note.t, now)
        if note.passed:
            return

        p = self.paddle
        # Did the note's path this frame cross the paddle's column?
        crossing = x_prev - note.radius <= p.x + p.width and note.x + note.radius >= p.x
        gap = p.gap_y(note)
        if crossing:
            note.closest_gap = min(note.closest_gap, gap)
            if gap < 0 and self.invulnerable:
                note.ghosted = True
            elif gap < 0:
                self._hit(note, events)
                return

        if note.x - note.radius > p.x + p.width:
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
            events.append(Event("near_miss" if near else "dodge", note.x, note.y, points, note.midi))
            if self.multiplier > old_level:
                events.append(Event("level_up", note.x, note.y, self.multiplier, note.midi))

    def _hit(self, note: Note, events: list[Event]) -> None:
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
