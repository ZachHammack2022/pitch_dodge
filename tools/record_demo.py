"""Render a gameplay GIF (and a title-screen PNG) headlessly, using the autoplay bot.

python tools/record_demo.py --start 30 --seconds 8 --out docs/demo.gif
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402
from PIL import Image  # noqa: E402

from pitch_dodge.app import App  # noqa: E402
from pitch_dodge.audio import SilentClock  # noqa: E402
from pitch_dodge.cli import DEFAULT_SONG  # noqa: E402
from pitch_dodge.scores import ScoreBoard  # noqa: E402


class SteppedClock(SilentClock):
    """Song time that advances exactly one frame per call to ``step``."""

    def __init__(self, duration, start):
        super().__init__(duration)
        self.t = start

    def play(self):
        pass

    def position(self):
        return self.t


def grab(screen, scale):
    raw = pygame.image.tobytes(screen, "RGB")
    img = Image.frombytes("RGB", screen.get_size(), raw)
    return img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", default=str(DEFAULT_SONG))
    ap.add_argument("--start", type=float, default=30.0, help="song time to start at")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--scale", type=float, default=0.45)
    ap.add_argument("--out", default="docs/demo.gif")
    ap.add_argument("--title", default="docs/title.png")
    ap.add_argument("--still", default="docs/gameplay.png", help="full-size frame from the middle")
    args = ap.parse_args()

    scores = ScoreBoard(Path(tempfile.mkdtemp()) / "scores.json")
    app = App(args.song, mute=True, seed=7, scores=scores, autoplay=True)
    app._load()
    app.mute = False  # the clock is silent anyway; keep "muted" off the HUD

    for _ in range(20):
        app.t += 1 / 30
        app._draw()
    grab(app.screen, 1.0).save(args.title)

    clock = SteppedClock(app.song.duration, args.start)
    app._start()
    app.song_clock = clock  # drive time frame by frame instead of from the music
    # Start mid-song: drop notes that would already be on screen, then warm up.
    app.world.skip_to(args.start)

    dt = 1 / args.fps
    frames = []
    warmup = int(2.5 * args.fps)
    for i in range(warmup + int(args.seconds * args.fps)):
        clock.t += dt
        app._update(dt)
        if app.state != "playing":
            break
        app._draw()
        if i >= warmup:
            frames.append(grab(app.screen, args.scale))
        if i == warmup + int(args.seconds * args.fps * 0.6):
            grab(app.screen, 1.0).save(args.still)

    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=48) for f in frames]
    pal[0].save(
        args.out, save_all=True, append_images=pal[1:], duration=int(1000 / args.fps), loop=0, optimize=True
    )
    print(
        f"wrote {args.out} ({len(frames)} frames, {Path(args.out).stat().st_size // 1024} KB), "
        f"{args.title} and {args.still}"
    )
    pygame.quit()


if __name__ == "__main__":
    main()
