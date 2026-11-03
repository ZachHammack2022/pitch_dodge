"""The pygame window and the title / playing / paused / results state machine."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pygame

from .analysis import SongAnalysis, analyse_file
from .audio import CountInClock, open_player
from .chart import build_chart
from .render import Renderer
from .scores import Entry, ScoreBoard
from .sfx import Sfx
from .world import DIFFICULTIES, HEIGHT, WIDTH, World

DIFFICULTY_ORDER = ["easy", "normal", "hard"]
MAX_FRAME = 1 / 20  # never simulate more than this per frame


class App:
    def __init__(
        self,
        song_path: str,
        difficulty: str = "normal",
        mute: bool = False,
        seed: int | None = None,
        scores: ScoreBoard | None = None,
        max_frames: int | None = None,
        autoplay: bool = False,
        start_playing: bool = False,
    ):
        self.song_path = str(song_path)
        self.song_name = Path(song_path).stem.replace("_", " ")
        self.difficulty = difficulty
        self.mute = mute
        self.seed = seed
        self.scores = scores or ScoreBoard()
        self.max_frames = max_frames
        self.autoplay = autoplay  # a simple bot, for demos and smoke tests
        self.start_playing = start_playing

        pygame.init()
        flags = pygame.SCALED | pygame.RESIZABLE
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
        pygame.display.set_caption("Pitch Dodge")
        self.renderer = Renderer(self.screen)
        self.clock = pygame.time.Clock()

        self.state = "loading"
        self.world: World | None = None
        self.song: SongAnalysis | None = None
        self.player = None
        self.song_clock: CountInClock | None = None
        self.sfx: Sfx | None = None
        self.rank: int | None = None
        self.t = 0.0
        self.running = True
        self.frames = 0

    # ------------------------------------------------------------ setup

    def _load(self) -> None:
        self.renderer.screen.blit(self.renderer.background, (0, 0))
        self.renderer.draw_message("analysing...", self.song_name)
        pygame.display.flip()
        pygame.event.pump()
        self.song = analyse_file(self.song_path)
        self.player = open_player(self.song_path, self.song.duration, mute=self.mute)
        self.sfx = Sfx(enabled=self.player.audible)
        self.state = "title"

    @property
    def best(self) -> int:
        return self.scores.best(self.song_name, self.difficulty)

    def _start(self) -> None:
        assert self.song is not None and self.player is not None
        difficulty = DIFFICULTIES[self.difficulty]
        chart = build_chart(self.song, difficulty)
        self.world = World(chart, difficulty)
        self.renderer.clear_effects()
        self.rank = None
        if self.song_clock is not None:
            self.song_clock.stop()
        self.song_clock = CountInClock(self.player, chart.count_in)
        self.song_clock.play()
        self.state = "playing"

    def _finish(self) -> None:
        assert self.world is not None
        self.song_clock.stop()
        entry = Entry(
            score=self.world.score,
            best_streak=self.world.best_streak,
            cleared=self.world.cleared,
            date=dt.date.today().isoformat(),
        )
        self.rank = self.scores.submit(self.song_name, self.difficulty, entry)
        self.state = "results"

    # ------------------------------------------------------------ input

    def _handle_event(self, e: pygame.event.Event) -> None:
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type != pygame.KEYDOWN:
            return
        k = e.key

        if k == pygame.K_m:
            self.mute = not self.mute
            self.player.set_volume(0.0 if self.mute else 1.0)
            self.sfx.enabled = not self.mute and self.player.audible
            return

        if self.state == "title":
            if k == pygame.K_ESCAPE:
                self.running = False
            elif k in (pygame.K_LEFT, pygame.K_a, pygame.K_RIGHT, pygame.K_d):
                step = -1 if k in (pygame.K_LEFT, pygame.K_a) else 1
                i = DIFFICULTY_ORDER.index(self.difficulty)
                self.difficulty = DIFFICULTY_ORDER[(i + step) % len(DIFFICULTY_ORDER)]
            elif k in (pygame.K_SPACE, pygame.K_RETURN):
                self._start()
        elif self.state == "playing":
            if k in (pygame.K_p, pygame.K_ESCAPE):
                self.song_clock.pause()
                self.state = "paused"
        elif self.state == "paused":
            if k in (pygame.K_p, pygame.K_ESCAPE, pygame.K_SPACE):
                self.song_clock.resume()
                self.state = "playing"
            elif k == pygame.K_q:
                self.song_clock.stop()
                self.state = "title"
            elif k == pygame.K_r:
                self._start()
        elif self.state == "results":
            if k == pygame.K_r:
                self._start()
            elif k == pygame.K_RETURN:
                self.state = "title"
            elif k == pygame.K_ESCAPE:
                self.running = False

    def _direction(self) -> float:
        if self.autoplay:
            return self._bot_direction()
        keys = pygame.key.get_pressed()
        up = keys[pygame.K_UP] or keys[pygame.K_w]
        down = keys[pygame.K_DOWN] or keys[pygame.K_s]
        return float(down) - float(up)

    def _bot_direction(self) -> float:
        """Steer away from the nearest incoming note (good enough to look alive)."""
        w = self.world
        p = w.paddle
        incoming = [n for n in w.notes if not n.passed and n.x < p.x and p.x - n.x < 260]
        if not incoming:
            target = (HEIGHT + 56) / 2
        else:
            n = min(incoming, key=lambda n: p.x - n.x)
            ny = n.y
            gap = p.height / 2 + n.radius + 14
            if abs(ny - p.y) > gap:
                return 0.0
            target = ny + gap if ny < (HEIGHT + 56) / 2 else ny - gap
        d = target - p.y
        return 0.0 if abs(d) < 4 else (1.0 if d > 0 else -1.0)

    # ------------------------------------------------------------ loop

    def run(self) -> None:
        self._load()
        if self.start_playing:
            self._start()
        while self.running:
            frame_dt = min(self.clock.tick(60) / 1000.0, MAX_FRAME)
            self.t += frame_dt
            for e in pygame.event.get():
                self._handle_event(e)
            self._update(frame_dt)
            self._draw()
            pygame.display.flip()
            self.frames += 1
            if self.max_frames is not None and self.frames >= self.max_frames:
                break
        if self.player:
            self.player.stop()
        pygame.quit()

    def _update(self, frame_dt: float) -> None:
        if self.state == "playing":
            w = self.world
            song_time = self.song_clock.position()
            dt = min(max(song_time - w.song_time, 0.0), MAX_FRAME)
            events = w.update(song_time, dt, self._direction())
            self.renderer.react(events)
            for e in events:
                self.sfx.play(e.kind)
            if w.over or w.cleared:
                self._finish()
        if self.state != "paused":
            self.renderer.tick(frame_dt)

    def _draw(self) -> None:
        r = self.renderer
        if self.state == "title":
            r.draw_title(self.song_name, self.difficulty, self.best, self.t)
            return
        w = self.world
        r.draw_background(w, self.song, w.song_time)
        r.draw_world(w)
        r.draw_hud(w, self.best, self.mute)
        if self.state == "paused":
            r.dim()
            r.draw_message("PAUSED", "P resume    R restart    Q menu")
        elif self.state == "results":
            r.draw_results(w, self.rank, self.best)
        else:
            r.finish_frame()
