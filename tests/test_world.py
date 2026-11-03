import pytest
from helpers import make_chart

from pitch_dodge.chart import ChartNote
from pitch_dodge.config import DIFFICULTIES, HEIGHT, PADDLE_X, TOP_MARGIN, pitch_to_y
from pitch_dodge.world import (
    INVULNERABLE_FOR,
    POINTS_DODGE,
    POINTS_PER_LIFE_LEFT,
    STREAK_PER_LEVEL,
    World,
)

NORMAL = DIFFICULTIES["normal"]
MIDDLE = 0.5  # pitch that maps near the paddle's starting height


def run(w, until, direction=0.0, dt=1 / 60):
    events = []
    while w.song_time < until - 1e-9 and not (w.over or w.cleared):
        t = min(w.song_time + dt, until)
        events += w.update(t, t - w.song_time, direction)
    return events


def paddle_pitch(w):
    """The pitch whose height is the paddle's centre."""
    top, bottom = TOP_MARGIN + 30, HEIGHT - 30
    return (bottom - w.paddle.y) / (bottom - top)


def world(notes, **kw):
    return World(make_chart(notes, **kw), NORMAL)


def test_count_in_starts_negative():
    w = World(make_chart([], count_in=2.0), NORMAL)
    assert w.song_time == -2.0


def test_note_crosses_paddle_exactly_on_its_beat():
    w = world([])
    w.chart.notes.append(ChartNote(t=3.0, pitch=0.0))  # far from the paddle: no collision
    xs = {}
    for i in range(1, 300):
        t = i / 60
        w.update(t, 1 / 60, 0)
        if w.notes:
            xs[round(t, 4)] = w.notes[0].x
    assert xs[3.0] == pytest.approx(PADDLE_X)
    assert xs[2.0] == pytest.approx(PADDLE_X - NORMAL.speed)


def test_note_appears_one_travel_time_early():
    w = world([(5.0, 0.0)])
    run(w, 5.0 - w.chart.travel_time - 0.02)
    assert not w.notes
    run(w, 5.0 - w.chart.travel_time + 0.02)
    assert len(w.notes) == 1 and w.notes[0].x < 20


def test_positions_independent_of_frame_rate():
    a, b = world([(2.0, 0.0)]), world([(2.0, 0.0)])
    run(a, 1.5, dt=1 / 144)
    run(b, 1.5, dt=1 / 15)
    assert a.notes[0].x == pytest.approx(b.notes[0].x)


def test_hit_costs_a_life_and_resets_streak():
    w = world([])
    w.chart.notes.append(ChartNote(t=1.0, pitch=paddle_pitch(w)))
    w.streak = 5
    events = run(w, 1.2)
    assert "hit" in [e.kind for e in events]
    assert w.lives == NORMAL.lives - 1 and w.streak == 0 and w.invulnerable


def test_big_frame_cannot_skip_the_paddle():
    w = world([])
    w.chart.notes.append(ChartNote(t=1.0, pitch=paddle_pitch(w)))
    w.update(0.97, 0.0, 0)
    events = w.update(1.03, 0.0, 0)  # note jumps 27px straight over the paddle column
    assert "hit" in [e.kind for e in events]


def test_invulnerability_lets_next_note_through_without_scoring():
    w = world([])
    p = paddle_pitch(w)
    w.chart.notes.extend([ChartNote(1.0, p), ChartNote(1.3, p)])
    events = run(w, 1.6)
    kinds = [e.kind for e in events]
    assert kinds.count("hit") == 1 and "dodge" not in kinds
    run(w, 1.0 + INVULNERABLE_FOR + 0.1)
    assert not w.invulnerable


def test_dodge_scores_with_multiplier_and_level_up():
    w = world([(1.0, 0.0)])
    events = run(w, 1.5)
    assert [e.kind for e in events if e.kind != "spawn"] == ["dodge"]
    assert w.score == POINTS_DODGE

    w = world([(1.0, 0.0)])
    w.streak = STREAK_PER_LEVEL - 1
    events = run(w, 1.5)
    assert [e.kind for e in events if e.kind != "spawn"] == ["dodge", "level_up"]


def test_near_miss():
    w = world([])
    gap_px = w.paddle.height / 2 + 9 * 1.05 + 6  # radius at strength 0.5 is 9 * 1.05
    top, bottom = TOP_MARGIN + 30, HEIGHT - 30
    pitch = (bottom - (w.paddle.y - gap_px)) / (bottom - top)
    w.chart.notes.append(ChartNote(1.0, pitch))
    events = run(w, 1.5)
    assert "near_miss" in [e.kind for e in events]


def test_game_over_and_frozen():
    w = world([])
    w.lives = 1
    w.chart.notes.append(ChartNote(1.0, paddle_pitch(w)))
    events = run(w, 1.2)
    assert w.over and events[-1].kind == "game_over"
    assert w.update(5, 1, 0) == []


def test_clearing_awards_life_bonus():
    w = world([(0.5, 0.0)], duration=1.0)
    events = run(w, 1.5)
    assert w.cleared and events[-1].kind == "cleared"
    assert w.score == POINTS_DODGE + NORMAL.lives * POINTS_PER_LIFE_LEFT


def test_paddle_stays_on_screen():
    w = world([])
    run(w, 3, direction=-1)
    assert w.paddle.top == pytest.approx(TOP_MARGIN)
    run(w, 6, direction=1)
    assert w.paddle.bottom == pytest.approx(HEIGHT)


def test_pitch_to_y_maps_high_to_top():
    assert pitch_to_y(1.0) < pitch_to_y(0.5) < pitch_to_y(0.0)
    assert pitch_to_y(5) == pitch_to_y(1)
