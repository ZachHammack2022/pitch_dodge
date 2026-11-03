import numpy as np
import pytest
from helpers import make_song

from pitch_dodge.chart import FIRST_NOTE_AT, beat_grid, build_chart
from pitch_dodge.config import DIFFICULTIES, NOTE_RADIUS, PADDLE_X

BEATS_120 = np.arange(0.5, 30, 0.5)  # 120 bpm


def test_beat_grid_levels_and_extension():
    grid = beat_grid(np.array([1.0, 1.5, 2.0]), duration=3.0, finest=2)
    times = [round(t, 3) for t, _ in grid]
    # Extended back to 0.5 and 0.0 and forward to 2.5, quartered.
    assert times[:5] == [0.0, 0.125, 0.25, 0.375, 0.5]
    assert times[-1] == pytest.approx(2.875)
    levels = dict(grid)
    assert levels[1.0] == 0 and levels[1.25] == 1 and levels[1.125] == 2


def test_beat_grid_needs_two_beats():
    assert beat_grid(np.array([1.0]), 5.0, 1) == []


def on_grid(t, finest):
    step = 0.5 / (2**finest)
    return abs(t / step - round(t / step)) < 1e-6


@pytest.mark.parametrize("name", ["easy", "normal", "hard"])
def test_notes_land_on_the_grid(name):
    d = DIFFICULTIES[name]
    song = make_song(duration=30, beats=BEATS_120, strength=lambda t: 0.3 + 0.7 * (np.sin(t * 7) > 0))
    chart = build_chart(song, d)
    assert chart.notes
    for n in chart.notes:
        assert on_grid(n.t, d.subdivision), n.t
    gaps = np.diff([n.t for n in chart.notes])
    assert gaps.min() >= d.min_gap - 1e-9
    assert chart.notes[0].t >= FIRST_NOTE_AT


def test_harder_means_more_notes():
    song = make_song(duration=30, beats=BEATS_120, strength=lambda t: 0.2 + 0.8 * ((t * 4) % 1 < 0.5))
    counts = [len(build_chart(song, DIFFICULTIES[d]).notes) for d in ("easy", "normal", "hard")]
    assert counts[0] < counts[1] < counts[2]


def test_weak_beats_are_dropped_but_silence_is_filled():
    # Only every other beat is strong; the max gap rule still keeps notes coming.
    song = make_song(
        duration=20, beats=np.arange(0.5, 20, 0.5), strength=lambda t: 1.0 if (t % 1) < 0.1 else 0.05
    )
    chart = build_chart(song, DIFFICULTIES["easy"])
    strong = [n for n in chart.notes if n.strength > 0.5]
    assert len(strong) >= 15
    assert np.diff([0.3, *[n.t for n in chart.notes], 19.9]).max() <= DIFFICULTIES["easy"].max_gap + 1e-6


def test_falls_back_to_onsets_without_beats():
    song = make_song(duration=10, onsets=[1.0, 2.0, 3.0, 4.5])
    chart = build_chart(song, DIFFICULTIES["normal"])
    assert [n.t for n in chart.notes][:4] == [1.0, 2.0, 3.0, 4.5]


def test_pitch_and_count_in():
    song = make_song(duration=10, beats=BEATS_120, pitch=0.8)
    d = DIFFICULTIES["normal"]
    chart = build_chart(song, d)
    assert all(n.pitch == pytest.approx(0.8) for n in chart.notes)
    assert chart.travel_time == pytest.approx((PADDLE_X + NOTE_RADIUS) / d.speed)
    # Long enough that the first note can travel the whole screen.
    assert chart.count_in + chart.notes[0].t >= chart.travel_time


def test_chart_json_roundtrip_fields():
    chart = build_chart(make_song(duration=5, beats=BEATS_120), DIFFICULTIES["easy"])
    data = chart.to_json()
    assert set(data) == {"notes", "beats", "duration", "speed", "travel_time", "count_in"}
    assert set(data["notes"][0]) >= {"t", "pitch", "kind", "strength", "level"}


def test_notes_carry_the_songs_pitch_class():
    song = make_song(duration=10, beats=BEATS_120)
    song.pitch_class[:] = 7  # G throughout
    chart = build_chart(song, DIFFICULTIES["normal"])
    assert {n.midi for n in chart.notes} == {79}
