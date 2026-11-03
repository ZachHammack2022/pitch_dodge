"""Music playback, and the clock the game runs on.

The game is driven by the song's playback position rather than wall-clock
time, so projectiles stay in sync with the music even if a frame stalls. When
no audio device is available (or ``--mute`` is passed) a silent clock stands in.
"""

from __future__ import annotations

import time

import pygame


class SilentClock:
    """Tracks song time without playing anything."""

    def __init__(self, duration: float):
        self.duration = duration
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._offset = 0.0
        self.audible = False

    def play(self) -> None:
        self._started_at = time.perf_counter()
        self._paused_at = None
        self._offset = 0.0

    def pause(self) -> None:
        if self._started_at is not None and self._paused_at is None:
            self._paused_at = time.perf_counter()

    def resume(self) -> None:
        if self._paused_at is not None and self._started_at is not None:
            self._started_at += time.perf_counter() - self._paused_at
            self._paused_at = None

    def stop(self) -> None:
        self._started_at = None
        self._paused_at = None

    def position(self) -> float:
        if self._started_at is None:
            return 0.0
        now = self._paused_at if self._paused_at is not None else time.perf_counter()
        return now - self._started_at + self._offset

    def set_volume(self, volume: float) -> None:
        pass


class MusicPlayer(SilentClock):
    """Plays the song with ``pygame.mixer.music`` and reports its position.

    ``mixer.music.get_pos()`` is coarse (it advances in audio-buffer steps), so
    between updates the position is interpolated with the wall clock, and only
    ever corrected forwards a little at a time to avoid visible jitter.
    """

    def __init__(self, path: str, duration: float):
        super().__init__(duration)
        pygame.mixer.music.load(path)
        self.audible = True
        self._last_reported = -1
        self._smoothed = 0.0
        self._last_wall = time.perf_counter()
        self._paused = False

    def play(self) -> None:
        pygame.mixer.music.play()
        self._smoothed = 0.0
        self._last_reported = -1
        self._last_wall = time.perf_counter()
        self._paused = False

    def pause(self) -> None:
        pygame.mixer.music.pause()
        self._paused = True

    def resume(self) -> None:
        pygame.mixer.music.unpause()
        self._paused = False
        self._last_wall = time.perf_counter()

    def stop(self) -> None:
        pygame.mixer.music.stop()

    def set_volume(self, volume: float) -> None:
        pygame.mixer.music.set_volume(volume)

    def position(self) -> float:
        now = time.perf_counter()
        if self._paused:
            self._last_wall = now
            return self._smoothed
        self._smoothed += now - self._last_wall
        self._last_wall = now

        ms = pygame.mixer.music.get_pos()
        if ms < 0:  # finished
            return max(self._smoothed, self.duration)
        if ms != self._last_reported:
            self._last_reported = ms
            reported = ms / 1000.0
            drift = reported - self._smoothed
            if abs(drift) > 0.25:
                self._smoothed = reported  # way off (e.g. after a stall): jump
            else:
                self._smoothed += drift * 0.1
        return self._smoothed


def open_player(path: str, duration: float, mute: bool = False) -> SilentClock:
    """Return a MusicPlayer, or a SilentClock if audio is muted or unavailable."""
    if mute:
        return SilentClock(duration)
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return MusicPlayer(path, duration)
    except pygame.error as exc:
        print(f"Audio unavailable ({exc}); playing silently.")
        return SilentClock(duration)
