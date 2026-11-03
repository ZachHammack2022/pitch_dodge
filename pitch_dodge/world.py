"""Game rules, with no pygame in sight so they can be unit tested.

Catch the melody, dodge the drums: catch notes ride the song's pitch line and
score when they meet the paddle; missing one breaks the combo. Hazards fall on
the strongest drum hits; touching one costs a life.

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
    POINTER_SPEED,
    SPAWN_MARGIN,
    TOP_MARGIN,
    WIDTH,
    Difficulty,
    pitch_to_y,
)

INVULNERABLE_FOR = 1.0  # seconds after a hazard hit
POINTS_CATCH = 10
POINTS_PERFECT = 15  # caught near the middle of the paddle
PERFECT_FRACTION = 0.3  # "near the middle" = within this fraction of the paddle's half-height
STREAK_PER_LEVEL = 10
MAX_MULTIPLIER = 8
POINTS_PER_LIFE_LEFT = 250
POINTS_HOLD_PER_SECOND = 20  # while the paddle stays on a hold note's tail (times multiplier)
POINTS_HOLD_BONUS = 10  # for holding all the way without slipping off (times multiplier)


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
    duration: float = 0.0  # > 0: a hold note
    passed: bool = False  # resolved: caught, missed, hit or dodged
    hit: bool = False  # touched the paddle (caught, or a hazard that hurt)
    holding: bool = False  # head caught, tail still running through the paddle
    hold_broken: bool = False  # slipped off the tail at some point
    hold_points: float = 0.0  # fractional points earned on the tail so far

    @property
    def is_hold(self) -> bool:
        return self.duration > 0

    def finished(self, speed: float) -> bool:
        """Can be dropped from play."""
        if self.hit and not self.holding:
            return True
        return self.x - self.duration * speed - self.radius >= WIDTH

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
            duration=n.duration,
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
        self._clamp()

    def move_toward(self, target: float, dt: float) -> None:
        """Follow a pointer, but no faster than POINTER_SPEED so it stays fair."""
        step = POINTER_SPEED * dt
        self.y += min(max(target - self.y, -step), step)
        self._clamp()

    def _clamp(self) -> None:
        lo = TOP_MARGIN + self.height / 2
        hi = HEIGHT - self.height / 2
        self.y = min(max(self.y, lo), hi)

    def gap_y(self, note: Note) -> float:
        """Vertical gap between the note's edge and the paddle (negative = overlapping)."""
        return max(self.top - note.y, note.y - self.bottom, 0.0) - note.radius


@dataclass
class Event:
    # "spawn" | "catch" | "perfect" | "miss" | "hit" | "level_up" | "game_over" | "cleared"
    # | "hold_start" | "hold_break" | "hold_done"
    kind: str
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
    streak: int = 0  # current combo
    best_streak: int = 0
    caught: int = 0
    perfect: int = 0
    missed: int = 0
    hits: int = 0  # hazards that hit
    holds: int = 0  # hold notes whose head was caught
    holds_completed: int = 0  # ...and held to the end without slipping
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

    def update(
        self, song_time: float, dt: float, direction: float, target_y: float | None = None
    ) -> list[Event]:
        """Advance to ``song_time``.

        The paddle follows ``target_y`` (a pointer's height) if given, otherwise
        moves by ``direction``: -1 (up), 0 or 1 (down).
        """
        events: list[Event] = []
        if self.over or self.cleared:
            return events
        prev = self.song_time
        self.song_time = song_time
        if target_y is not None:
            self.paddle.move_toward(target_y, dt)
        else:
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

        self.notes = [n for n in self.notes if not n.finished(self.chart.speed)]

        if song_time >= self.duration and self._next >= len(chart_notes) and not self.notes:
            self.cleared = True
            bonus = self.lives * POINTS_PER_LIFE_LEFT
            self.score += bonus
            events.append(Event("cleared", value=bonus))
        return events

    @property
    def accuracy(self) -> float:
        total = self.caught + self.missed
        return self.caught / total if total else 0.0

    def _step(self, note: Note, prev: float, now: float, events: list[Event]) -> None:
        x_prev = self.x_at(note.t, prev)
        note.x = self.x_at(note.t, now)
        if note.holding:
            self._hold(note, prev, now, events)
            return
        if note.passed:
            return

        p = self.paddle
        # Did the note's path this frame cross the paddle's column?
        crossing = x_prev - note.radius <= p.x + p.width and note.x + note.radius >= p.x
        touching = crossing and p.gap_y(note) < 0
        if note.kind == "hazard":
            if touching and not self.invulnerable:
                self._hurt(note, events)
            elif note.x - note.radius > p.x + p.width:
                note.passed = True  # dodged
        else:
            if touching:
                self._catch(note, events)
            elif note.x - note.radius > p.x + p.width:
                note.passed = True
                self.missed += 1
                self.streak = 0
                events.append(Event("miss", note.x, note.y))

    def _catch(self, note: Note, events: list[Event]) -> None:
        note.hit = note.passed = True
        old_level = self.multiplier
        perfect = abs(note.y - self.paddle.y) <= self.paddle.height / 2 * PERFECT_FRACTION
        self.caught += 1
        self.perfect += perfect
        self.streak += 1
        self.best_streak = max(self.best_streak, self.streak)
        points = (POINTS_PERFECT if perfect else POINTS_CATCH) * old_level
        self.score += points
        events.append(Event("perfect" if perfect else "catch", note.x, note.y, points, note.midi))
        if note.is_hold:
            note.holding = True
            self.holds += 1
            events.append(Event("hold_start", note.x, note.y, int(note.duration * 1000), note.midi))
        if self.multiplier > old_level:
            events.append(Event("level_up", note.x, note.y, self.multiplier, note.midi))

    def _hold(self, note: Note, prev: float, now: float, events: list[Event]) -> None:
        """Score while the paddle stays on a hold note's tail."""
        end = note.t + note.duration
        overlap = max(0.0, min(now, end) - max(prev, note.t))
        p = self.paddle
        on = p.gap_y(note) < 0
        if on:
            before = int(note.hold_points)
            note.hold_points += POINTS_HOLD_PER_SECOND * self.multiplier * overlap
            self.score += int(note.hold_points) - before
        elif not note.hold_broken and overlap > 0:
            note.hold_broken = True
            events.append(Event("hold_break", p.x, note.y, midi=note.midi))
        if now >= end:
            note.holding = False
            if not note.hold_broken:
                bonus = POINTS_HOLD_BONUS * self.multiplier
                self.score += bonus
                self.holds_completed += 1
                events.append(Event("hold_done", p.x, note.y, bonus, note.midi))

    def _hurt(self, note: Note, events: list[Event]) -> None:
        note.hit = note.passed = True
        self.hits += 1
        self.lives -= 1
        self.streak = 0
        self.invulnerable_until = self.song_time + INVULNERABLE_FOR
        events.append(Event("hit", note.x, note.y, self.lives))
        if self.lives <= 0:
            self.over = True
            events.append(Event("game_over", value=self.score))
