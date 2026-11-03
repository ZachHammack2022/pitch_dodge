import pytest
from helpers import make_chart

from pitch_dodge.chart import ChartNote
from pitch_dodge.config import DIFFICULTIES, HEIGHT, PADDLE_X, TOP_MARGIN, pitch_to_y
from pitch_dodge.world import (
    INVULNERABLE_FOR,
    POINTS_CATCH,
    POINTS_PER_LIFE_LEFT,
    POINTS_PERFECT,
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


def pitch_at_offset(w, dy):
    """The pitch whose height is ``dy`` px below the paddle's centre."""
    top, bottom = TOP_MARGIN + 30, HEIGHT - 30
    return (bottom - (w.paddle.y + dy)) / (bottom - top)


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


def hazard(t, pitch):
    return ChartNote(t, pitch, kind="hazard")


def test_catching_scores_and_builds_combo():
    w = world([])
    w.chart.notes.append(ChartNote(1.0, paddle_pitch(w), midi=76))
    events = run(w, 1.5)
    kinds = [e.kind for e in events if e.kind != "spawn"]
    assert kinds == ["perfect"]  # dead centre of the paddle
    assert w.score == POINTS_PERFECT and w.caught == 1 and w.streak == 1
    assert [e.midi for e in events if e.kind == "perfect"] == [76]  # sound plays in key
    assert not w.notes  # caught notes disappear


def test_edge_catch_is_not_perfect():
    w = world([])
    w.chart.notes.append(ChartNote(1.0, pitch_at_offset(w, w.paddle.height / 2 + 4)))
    events = run(w, 1.5)
    assert [e.kind for e in events if e.kind != "spawn"] == ["catch"]
    assert w.score == POINTS_CATCH


def test_missing_a_catch_note_breaks_combo_but_costs_no_life():
    w = world([(1.0, 0.0)])
    w.streak = 7
    events = run(w, 1.5)
    assert [e.kind for e in events if e.kind != "spawn"] == ["miss"]
    assert w.streak == 0 and w.missed == 1 and w.lives == NORMAL.lives


def test_multiplier_and_level_up():
    w = world([])
    w.chart.notes.append(ChartNote(1.0, paddle_pitch(w)))
    w.streak = STREAK_PER_LEVEL - 1
    events = run(w, 1.5)
    assert [e.kind for e in events if e.kind != "spawn"] == ["perfect", "level_up"]
    assert w.multiplier == 2


def test_hazard_hit_costs_a_life_and_combo():
    w = world([])
    w.chart.notes.append(hazard(1.0, paddle_pitch(w)))
    w.streak = 5
    events = run(w, 1.2)
    assert "hit" in [e.kind for e in events]
    assert w.lives == NORMAL.lives - 1 and w.streak == 0 and w.invulnerable


def test_dodged_hazard_is_harmless():
    w = world([hazard(1.0, 0.0)])
    events = run(w, 1.5)
    assert [e.kind for e in events if e.kind != "spawn"] == []
    assert w.lives == NORMAL.lives and w.score == 0


def test_big_frame_cannot_skip_the_paddle():
    w = world([])
    w.chart.notes.append(hazard(1.0, paddle_pitch(w)))
    w.update(0.97, 0.0, 0)
    events = w.update(1.03, 0.0, 0)  # note jumps 27px straight over the paddle column
    assert "hit" in [e.kind for e in events]


def test_invulnerable_after_hit_but_can_still_catch():
    w = world([])
    p = paddle_pitch(w)
    w.chart.notes.extend([hazard(1.0, p), hazard(1.3, p), ChartNote(1.5, p)])
    events = run(w, 1.8)
    kinds = [e.kind for e in events]
    assert kinds.count("hit") == 1 and "perfect" in kinds
    run(w, 1.0 + INVULNERABLE_FOR + 0.1)
    assert not w.invulnerable


def test_game_over_and_frozen():
    w = world([])
    w.lives = 1
    w.chart.notes.append(hazard(1.0, paddle_pitch(w)))
    events = run(w, 1.2)
    assert w.over and events[-1].kind == "game_over"
    assert w.update(5, 1, 0) == []


def test_clearing_awards_life_bonus():
    w = world([], duration=1.0)
    w.chart.notes.append(ChartNote(0.5, paddle_pitch(w)))
    events = run(w, 1.5)
    assert w.cleared and events[-1].kind == "cleared"
    assert w.score == POINTS_PERFECT + NORMAL.lives * POINTS_PER_LIFE_LEFT


def test_accuracy():
    w = world([])
    w.chart.notes.extend([ChartNote(1.0, paddle_pitch(w)), ChartNote(1.5, 0.0), ChartNote(2.0, 1.0)])
    run(w, 2.5)
    assert (w.caught, w.missed) == (1, 2)
    assert w.accuracy == pytest.approx(1 / 3)


def test_paddle_stays_on_screen():
    w = world([])
    run(w, 3, direction=-1)
    assert w.paddle.top == pytest.approx(TOP_MARGIN)
    run(w, 6, direction=1)
    assert w.paddle.bottom == pytest.approx(HEIGHT)


def test_pitch_to_y_maps_high_to_top():
    assert pitch_to_y(1.0) < pitch_to_y(0.5) < pitch_to_y(0.0)
    assert pitch_to_y(5) == pitch_to_y(1)


def test_beat_pulse():
    from pitch_dodge.render import beat_pulse

    beats = [1.0, 1.5, 2.0, 2.5, 3.0]
    assert beat_pulse(beats, 0.5) == 0
    assert beat_pulse(beats, 1.0) == pytest.approx(1.0)  # downbeat
    assert beat_pulse(beats, 1.5) == pytest.approx(0.6)  # off-beat is softer
    assert beat_pulse(beats, 1.4) < 0.05  # decayed before the next beat


def test_pointer_moves_paddle_toward_target_with_speed_cap():
    from pitch_dodge.config import POINTER_SPEED

    w = world([])
    start = w.paddle.y
    w.update(0.1, 0.1, 0, target_y=start - 1000)  # far away: capped
    assert w.paddle.y == pytest.approx(start - POINTER_SPEED * 0.1)
    w.update(0.2, 0.1, 0, target_y=w.paddle.y + 20)  # close: lands exactly
    assert w.paddle.y == pytest.approx(start - POINTER_SPEED * 0.1 + 20)
    w.update(5, 5, 0, target_y=10_000)
    assert w.paddle.bottom == pytest.approx(HEIGHT)  # still clamped to the screen


def test_hold_note_scores_while_held_and_bonus_at_end():
    from pitch_dodge.world import POINTS_HOLD_BONUS, POINTS_HOLD_PER_SECOND

    w = world([])
    w.chart.notes.append(ChartNote(1.0, paddle_pitch(w), duration=1.0, midi=74))
    events = run(w, 2.5)
    kinds = [e.kind for e in events if e.kind != "spawn"]
    assert kinds == ["perfect", "hold_start", "hold_done"]
    expected = POINTS_PERFECT + POINTS_HOLD_PER_SECOND * 1.0 + POINTS_HOLD_BONUS
    assert w.score == pytest.approx(expected, abs=1)
    assert (w.holds, w.holds_completed) == (1, 1)
    assert not w.notes


def test_slipping_off_a_hold_breaks_it():
    w = world([])
    w.chart.notes.append(ChartNote(1.0, paddle_pitch(w), duration=1.0))
    events = run(w, 1.3)
    events += run(w, 2.5, direction=-1)  # move away mid-hold
    kinds = [e.kind for e in events if e.kind != "spawn"]
    assert "hold_break" in kinds and "hold_done" not in kinds
    assert w.holds_completed == 0
    assert w.score < POINTS_PERFECT + 20  # got some tail points, not all


def test_missed_hold_head_gives_nothing():
    w = world([(1.0, 0.0)])
    w.chart.notes[0] = ChartNote(1.0, 0.0, duration=1.0)
    events = run(w, 2.5)
    assert [e.kind for e in events if e.kind != "spawn"] == ["miss"]
    assert w.score == 0
