import numpy as np
import pytest

from pitch_dodge.analysis import SongAnalysis
from pitch_dodge.world import (
    DIFFICULTIES,
    HEIGHT,
    INVULNERABLE_FOR,
    POINTS_DODGE,
    POINTS_PER_LIFE_LEFT,
    STREAK_PER_LEVEL,
    TOP_MARGIN,
    Note,
    World,
    build_spawn_schedule,
    pitch_to_y,
)

NORMAL = DIFFICULTIES["normal"]


def make_song(duration=10.0, onsets=(), pitch=0.5):
    hop = 512 / 22050
    n = int(duration / hop) + 1
    return SongAnalysis(
        pitch=np.full(n, pitch),
        energy=np.full(n, 0.5),
        onsets=np.asarray(onsets, dtype=float),
        hop_seconds=hop,
        duration=duration,
    )


def make_world(**kw):
    w = World(make_song(**kw), NORMAL, seed=0)
    w.schedule = []  # tests place notes by hand
    return w


def note_at_paddle(w, dy=0.0, x_offset=-30, vx=600.0):
    return Note(x=w.paddle.x + x_offset, y=w.paddle.y + dy, vx=vx, vy=0.0, pitch=0.5)


def run(w, seconds, direction=0.0, dt=1 / 60):
    events = []
    for _ in range(int(seconds / dt)):
        events += w.update(w.song_time + dt, dt, direction)
    return events


# ------------------------------------------------------------ schedule


def test_schedule_respects_min_gap_and_bounds():
    onsets = np.arange(0, 30, 0.05)
    times = build_spawn_schedule(onsets, 30.0, NORMAL)
    assert times == sorted(times)
    assert times[0] >= 1.0 and times[-1] < 30.0
    gaps = np.diff(times)
    assert gaps.min() >= NORMAL.end_gap - 1e-9


def test_schedule_gets_denser_over_the_song():
    times = np.array(build_spawn_schedule(np.arange(0, 60, 0.05), 60.0, NORMAL))
    first = np.sum(times < 20)
    last = np.sum(times > 40)
    assert last > first


def test_schedule_fills_silence():
    times = build_spawn_schedule(np.array([]), 10.0, NORMAL)
    assert len(times) > 0
    assert np.diff([1.0 - NORMAL.max_gap, *times, 10.0]).max() <= NORMAL.max_gap + 1e-9


def test_harder_means_more_notes():
    onsets = np.arange(0, 60, 0.05)
    counts = [len(build_spawn_schedule(onsets, 60.0, DIFFICULTIES[d])) for d in ("easy", "normal", "hard")]
    assert counts[0] < counts[1] < counts[2]


def test_pitch_to_y_maps_high_to_top():
    assert pitch_to_y(1.0) < pitch_to_y(0.5) < pitch_to_y(0.0)
    assert TOP_MARGIN < pitch_to_y(1.0) and pitch_to_y(0.0) < HEIGHT
    assert pitch_to_y(5) == pitch_to_y(1) and pitch_to_y(-5) == pitch_to_y(0)


# ------------------------------------------------------------ rules


def test_paddle_stays_on_screen():
    w = make_world()
    run(w, 3, direction=-1)
    assert w.paddle.top == pytest.approx(TOP_MARGIN)
    run(w, 3, direction=1)
    assert w.paddle.bottom == pytest.approx(HEIGHT)


def test_spawns_follow_schedule_and_pitch():
    w = World(make_song(pitch=1.0), NORMAL, seed=0)
    w.schedule = [0.5, 1.0]
    events = w.update(0.6, 0.0, 0)
    assert [e.kind for e in events] == ["spawn"]
    assert w.notes[0].y == pytest.approx(pitch_to_y(1.0))
    w.update(1.1, 0.0, 0)
    assert len(w.notes) == 2


def test_hit_costs_a_life_and_resets_streak():
    w = make_world()
    w.streak = 5
    w.notes.append(note_at_paddle(w))
    events = run(w, 0.2)
    assert "hit" in [e.kind for e in events]
    assert w.lives == NORMAL.lives - 1
    assert w.streak == 0 and w.hits == 1
    assert w.invulnerable
    assert not w.notes  # the note that hit is gone


def test_invulnerability_prevents_a_second_hit_and_wears_off():
    w = make_world()
    w.notes.append(note_at_paddle(w))
    run(w, 0.1)
    w.notes.append(note_at_paddle(w))
    events = run(w, 0.2)
    assert "hit" not in [e.kind for e in events]
    assert "dodge" not in [e.kind for e in events]  # ghosting through isn't a dodge
    assert w.lives == NORMAL.lives - 1
    run(w, INVULNERABLE_FOR)
    assert not w.invulnerable


def test_dodge_scores_with_multiplier():
    w = make_world()
    w.notes.append(note_at_paddle(w, dy=200))
    events = run(w, 0.3)
    assert [e.kind for e in events] == ["dodge"]
    assert w.score == POINTS_DODGE and w.dodged == 1 and w.streak == 1

    w.streak = STREAK_PER_LEVEL * 2
    assert w.multiplier == 3
    w.notes.append(note_at_paddle(w, dy=200))
    run(w, 0.3)
    assert w.score == POINTS_DODGE + POINTS_DODGE * 3


def test_level_up_event():
    w = make_world()
    w.streak = STREAK_PER_LEVEL - 1
    w.notes.append(note_at_paddle(w, dy=200))
    events = run(w, 0.3)
    assert [e.kind for e in events] == ["dodge", "level_up"]
    assert events[-1].value == 2


def test_near_miss_bonus():
    w = make_world()
    gap = w.paddle.height / 2 + 9 + 5  # 5px between note edge and paddle edge
    w.notes.append(note_at_paddle(w, dy=gap))
    events = run(w, 0.3)
    assert [e.kind for e in events] == ["near_miss"]


def test_fast_notes_cannot_tunnel_through_paddle():
    w = make_world()
    w.notes.append(note_at_paddle(w, x_offset=-40, vx=3000))
    events = w.update(1 / 20, 1 / 20, 0)  # one long frame: 150px of travel
    assert "hit" in [e.kind for e in events]


def test_notes_bounce_off_walls():
    w = make_world()
    n = Note(x=100, y=TOP_MARGIN + 12, vx=10, vy=-300, pitch=0.5)
    w.notes.append(n)
    run(w, 0.1)
    assert n.vy > 0 and n.y > TOP_MARGIN


def test_game_over_when_out_of_lives():
    w = make_world()
    w.lives = 1
    w.notes.append(note_at_paddle(w))
    events = run(w, 0.2)
    assert w.over
    assert events[-1].kind == "game_over"
    assert w.update(w.song_time + 1, 1, 0) == []  # frozen afterwards


def test_clearing_the_song_awards_life_bonus():
    w = make_world(duration=1.0)
    events = run(w, 1.2)
    assert w.cleared
    assert w.score == NORMAL.lives * POINTS_PER_LIFE_LEFT
    assert events[-1].kind == "cleared"


def test_speed_increases_with_progress():
    w = make_world(duration=10.0)
    start = w.speed
    w.song_time = 10.0
    assert w.speed == pytest.approx(start * (1 + NORMAL.speed_growth))


def test_seeded_worlds_are_repeatable():
    song = make_song(duration=8.0, onsets=np.arange(0, 8, 0.3))

    def play():
        w = World(song, NORMAL, seed=42)
        for i in range(400):
            w.update(i / 50, 1 / 50, 1 if (i // 30) % 2 else -1)
        return w.score, w.lives, w.dodged

    assert play() == play()
