"""Command-line entry point: ``pitch-dodge [song] [--difficulty ...]``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .world import DIFFICULTIES

DEFAULT_SONG = Path(__file__).resolve().parent.parent / "music_files" / "jungle_waves.mp3"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pitch-dodge",
        description="Dodge projectiles fired by the melody of any song.",
    )
    parser.add_argument(
        "song",
        nargs="?",
        default=str(DEFAULT_SONG),
        help="audio file to play (wav, mp3, ogg, flac...); defaults to the bundled track",
    )
    parser.add_argument(
        "-d", "--difficulty", choices=list(DIFFICULTIES), default="normal", help="starting difficulty"
    )
    parser.add_argument("--mute", action="store_true", help="play without sound")
    parser.add_argument("--seed", type=int, help="random seed, for repeatable runs")
    parser.add_argument("--no-cache", action="store_true", help="re-analyse the song even if cached")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not Path(args.song).is_file():
        print(f"pitch-dodge: file not found: {args.song}", file=sys.stderr)
        return 1
    if args.no_cache:
        os.environ["PITCH_DODGE_NO_CACHE"] = "1"
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    from .app import App  # imported late so --help is instant

    try:
        App(args.song, difficulty=args.difficulty, mute=args.mute, seed=args.seed).run()
    except KeyboardInterrupt:
        pass
    except ValueError as exc:  # e.g. a song too short to play
        print(f"pitch-dodge: {exc}", file=sys.stderr)
        return 1
    return 0
