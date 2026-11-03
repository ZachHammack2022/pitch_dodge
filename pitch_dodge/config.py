"""Shared geometry and difficulty settings for the chart builder and the game rules.

The browser client (``web/game.js``) mirrors the geometry constants; keep them
in step.
"""

from __future__ import annotations

from dataclasses import dataclass

WIDTH = 960
HEIGHT = 600
TOP_MARGIN = 56  # room for the HUD
SPAWN_MARGIN = 30

PADDLE_WIDTH = 14
PADDLE_X = WIDTH - 110
PADDLE_SPEED = 560.0  # px/s
NOTE_RADIUS = 9


@dataclass(frozen=True)
class Difficulty:
    name: str
    lives: int
    speed: float  # scroll speed, px/s
    subdivision: int  # finest grid level used: 0 = beats, 1 = half beats, 2 = quarter beats
    min_gap: float  # never two notes closer than this, seconds
    max_gap: float  # fill silences longer than this, seconds
    paddle_height: int

    @property
    def travel_time(self) -> float:
        """Seconds from a note appearing at the left edge to reaching the paddle."""
        return (PADDLE_X + NOTE_RADIUS) / self.speed


DIFFICULTIES = {
    "easy": Difficulty(
        "easy", lives=5, speed=380, subdivision=0, min_gap=0.32, max_gap=2.0, paddle_height=72
    ),
    "normal": Difficulty(
        "normal", lives=3, speed=450, subdivision=1, min_gap=0.20, max_gap=1.6, paddle_height=72
    ),
    "hard": Difficulty(
        "hard", lives=2, speed=540, subdivision=2, min_gap=0.12, max_gap=1.2, paddle_height=72
    ),
}


def pitch_to_y(pitch: float) -> float:
    """0 (low) is the bottom of the play area, 1 (high) the top."""
    top = TOP_MARGIN + SPAWN_MARGIN
    bottom = HEIGHT - SPAWN_MARGIN
    return bottom - min(max(pitch, 0.0), 1.0) * (bottom - top)
