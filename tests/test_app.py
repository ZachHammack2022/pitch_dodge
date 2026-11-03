"""Smoke tests: run the real game loop headlessly with the autoplay bot."""

import numpy as np
import pygame
import pytest
import soundfile as sf

from pitch_dodge.app import App
from pitch_dodge.cli import main, parse_args
from pitch_dodge.scores import ScoreBoard


@pytest.fixture
def song(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sr = 22050
    t = np.arange(sr * 3) / sr
    y = 0.4 * np.sin(2 * np.pi * (220 + 220 * t / 3) * t) * (1 + np.sign(np.sin(2 * np.pi * 3 * t))) / 2
    path = tmp_path / "test_song.wav"
    sf.write(path, y.astype(np.float32), sr)
    return path


def test_game_loop_runs(song, tmp_path):
    app = App(
        song,
        mute=True,
        seed=1,
        scores=ScoreBoard(tmp_path / "s.json"),
        max_frames=90,
        autoplay=True,
        start_playing=True,
    )
    app.run()
    assert app.frames == 90
    assert app.world is not None
    assert app.world.song_time > -app.world.chart.count_in + 0.5  # time advanced through the count-in


def test_states_respond_to_keys(song, tmp_path):
    app = App(song, mute=True, seed=1, scores=ScoreBoard(tmp_path / "s.json"))
    app._load()
    assert app.state == "title"

    def press(key):
        app._handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    press(pygame.K_RIGHT)
    assert app.difficulty == "hard"
    press(pygame.K_RIGHT)
    assert app.difficulty == "easy"
    press(pygame.K_SPACE)
    assert app.state == "playing"
    press(pygame.K_p)
    assert app.state == "paused"
    press(pygame.K_p)
    assert app.state == "playing"

    app.world.lives = 0
    app.world.over = True
    app._finish()
    assert app.state == "results" and app.rank == 1
    app._draw()
    press(pygame.K_r)
    assert app.state == "playing"
    pygame.quit()


def test_cli_rejects_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "missing.mp3")]) == 1
    assert "not found" in capsys.readouterr().err


def test_cli_defaults():
    args = parse_args([])
    assert args.difficulty == "normal"
    assert args.song.endswith("jungle_waves.mp3")


def test_serve_args():
    from pitch_dodge.cli import parse_serve_args

    args = parse_serve_args(["--port", "9000", "--no-browser"])
    assert args.port == 9000 and args.no_browser and args.host == "127.0.0.1"


def test_latency_shifts_game_time_behind_audio(song, tmp_path):
    app = App(song, mute=True, scores=ScoreBoard(tmp_path / "s.json"), latency_ms=200)
    app._load()
    app._start()

    class Fixed:
        def position(self):
            return 1.0

        def stop(self):
            pass

    app.song_clock = Fixed()
    app._update(1 / 60)
    assert app.world.song_time == pytest.approx(0.8)
    pygame.quit()


def test_cli_latency_flag():
    assert parse_args(["--latency-ms", "180"]).latency_ms == 180
